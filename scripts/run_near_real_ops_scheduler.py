#!/usr/bin/env python3
"""Near-real operations scheduler.

This is a single-process, in-application scheduler for the KIS near-real
operating day. It does not depend on cron/systemd timers for task timing.

The scheduler intentionally reuses the existing operational entrypoints:

* ``run_snapshot_sync_loop.py --max-cycles 1``
* ``run_event_ingestion_loop.py --count 1``
* ``run_paper_decision_loop.py --count 1``
* ``run_post_submit_sync_loop.py --once``

P0 scope is conservative: one process manages timing and safety gates, while
the existing scripts keep broker/API/database behavior unchanged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is declared in pyproject
    load_dotenv = None  # type: ignore[assignment]

KST = ZoneInfo("Asia/Seoul")

DEFAULT_SNAPSHOT_INTERVAL_SECONDS = 300
DEFAULT_EVENT_INTERVAL_SECONDS = 300
DEFAULT_DECISION_INTERVAL_SECONDS = 300
DEFAULT_POST_SUBMIT_INTERVAL_SECONDS = 30
DEFAULT_TASK_TIMEOUT_SECONDS = 240
PYTHON_BIN = "python3"

DEFAULT_MAX_SUBMIT_PER_DAY = 1

# Budget-consuming order statuses for DB-based submit budget safeguard.
# These statuses indicate that a submit budget slot was consumed.
_BUDGET_CONSUMING_STATUSES: frozenset[str] = frozenset({
    "submitted",
    "acknowledged",
    "partially_filled",
    "filled",
    "reconcile_required",
})

PRE_MARKET_START = dtime(8, 0)
INTRADAY_START = dtime(8, 50)
MARKET_CLOSE = dtime(15, 30)
END_OF_DAY_END = dtime(16, 30)

logger = logging.getLogger("near_real_ops_scheduler")


@dataclass(slots=True)
class CommandResult:
    """Completed subprocess execution result."""

    name: str
    argv: list[str]
    returncode: int
    duration_seconds: float
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass(slots=True)
class ScheduledTask:
    """Periodic task state."""

    name: str
    interval_seconds: int
    next_run_at: datetime

    def due(self, now: datetime) -> bool:
        return now >= self.next_run_at

    def mark_ran(self, now: datetime) -> None:
        self.next_run_at = now + timedelta(seconds=self.interval_seconds)


@dataclass(slots=True)
class SchedulerState:
    """Mutable scheduler state for a single operating day."""

    run_date: date
    pre_market_done: bool = False
    end_of_day_done: bool = False
    submit_count: int = 0
    cycles: int = 0
    command_results: list[CommandResult] = field(default_factory=list)


def _parse_hhmm(value: str) -> dtime:
    """Parse ``HH:MM`` into ``datetime.time``."""
    try:
        hour, minute = value.split(":", 1)
        return dtime(int(hour), int(minute))
    except Exception as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid time {value!r}; expected HH:MM"
        ) from exc


def _combine(run_date: date, clock: dtime) -> datetime:
    """Return a timezone-aware KST datetime for ``run_date`` + ``clock``."""
    return datetime.combine(run_date, clock, tzinfo=KST)


def _load_env() -> None:
    """Load .env if python-dotenv is available.

    Existing environment variables are not overwritten, which keeps Docker or
    manually exported runtime settings authoritative.
    """
    if load_dotenv is not None:
        load_dotenv()


def _build_base_env() -> dict[str, str]:
    """Build subprocess environment."""
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _extract_json_objects(text: str) -> list[dict[str, Any]]:
    """Extract JSON objects from line-oriented command output."""
    objects: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{") or not stripped.endswith("}"):
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
    return objects


def _is_submit_consuming_result(result: CommandResult) -> bool:
    """Return true when a decision command consumed the daily submit budget."""
    if not result.ok:
        return False
    for obj in _extract_json_objects(result.stdout):
        status = str(obj.get("status", "")).upper()
        if status in {"SUBMITTED", "RECONCILE_REQUIRED"}:
            return True
    return False


async def _get_db_submit_count(run_date: date) -> int:
    """Query ``trading.order_requests`` for today's submit budget consumption.

    Returns the count of orders whose status is in the budget-consuming set
    and whose ``created_at`` falls on the KST operating date.

    On any failure (connection error, query error, etc.), returns
    ``DEFAULT_MAX_SUBMIT_PER_DAY`` (conservative dry-run fallback).
    """
    import asyncpg

    from dotenv import load_dotenv

    load_dotenv()  # ensure .env loaded (idempotent)

    dsn = os.getenv("DATABASE_DSN")
    if dsn is None:
        host = os.getenv("DATABASE_HOST") or os.getenv("DB_HOST") or "localhost"
        port = os.getenv("DATABASE_PORT") or os.getenv("DB_PORT") or "5432"
        user = os.getenv("DATABASE_USER") or os.getenv("DB_USER") or "trading"
        password = os.getenv("DATABASE_PASSWORD") or os.getenv("DB_PASSWORD") or "trading"
        database = os.getenv("DATABASE_NAME") or os.getenv("DB_NAME") or "trading"
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    try:
        conn = await asyncpg.connect(dsn=dsn)
        try:
            # KST operating day boundaries
            kst_midnight = datetime.combine(run_date, dtime(0, 0, 0), tzinfo=KST)
            kst_end_of_day = kst_midnight + timedelta(days=1)

            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS cnt
                FROM trading.order_requests
                WHERE created_at >= $1
                  AND created_at < $2
                  AND status = ANY($3::text[])
                """,
                kst_midnight,
                kst_end_of_day,
                list(_BUDGET_CONSUMING_STATUSES),
            )
            count: int = row["cnt"] if row else 0
            logger.info(
                "db_submit_count=%d run_date=%s statuses=%s",
                count,
                run_date.isoformat(),
                sorted(_BUDGET_CONSUMING_STATUSES),
            )
            return count
        finally:
            await conn.close()
    except Exception:
        logger.exception(
            "db_submit_count query failed — conservative dry-run fallback"
        )
        return DEFAULT_MAX_SUBMIT_PER_DAY


async def _run_command(
    name: str,
    argv: list[str],
    *,
    timeout_seconds: int,
    env: dict[str, str],
) -> CommandResult:
    """Run a subprocess command without using a shell."""
    start = time.monotonic()
    logger.info("task=%s start argv=%s", name, " ".join(argv))

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    timed_out = False
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        timed_out = True
        proc.terminate()
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            stdout_b, stderr_b = await proc.communicate()

    duration = time.monotonic() - start
    result = CommandResult(
        name=name,
        argv=argv,
        returncode=proc.returncode if proc.returncode is not None else -1,
        duration_seconds=round(duration, 3),
        stdout=stdout_b.decode(errors="replace"),
        stderr=stderr_b.decode(errors="replace"),
        timed_out=timed_out,
    )

    level = logging.INFO if result.ok else logging.ERROR
    logger.log(
        level,
        "task=%s complete ok=%s returncode=%s timeout=%s duration=%.2fs",
        name,
        result.ok,
        result.returncode,
        result.timed_out,
        result.duration_seconds,
    )
    if result.stdout.strip():
        logger.debug("task=%s stdout:\n%s", name, result.stdout.strip())
    if result.stderr.strip():
        logger.debug("task=%s stderr:\n%s", name, result.stderr.strip())
    return result


def _snapshot_command() -> list[str]:
    return [PYTHON_BIN, "scripts/run_snapshot_sync_loop.py", "--max-cycles", "1"]


def _event_command() -> list[str]:
    return [
        PYTHON_BIN,
        "-m",
        "scripts.run_event_ingestion_loop",
        "--count",
        "1",
        "--output",
        "json",
    ]


def _decision_command(*, dry_run: bool) -> list[str]:
    argv = [
        PYTHON_BIN,
        "-m",
        "scripts.run_paper_decision_loop",
        "--count",
        "1",
        "--output",
        "json",
    ]
    if dry_run:
        argv.append("--dry-run")
    else:
        argv.append("--submit")
    return argv


def _post_submit_command() -> list[str]:
    return [PYTHON_BIN, "scripts/run_post_submit_sync_loop.py", "--once"]


async def _run_and_record(
    state: SchedulerState,
    name: str,
    argv: list[str],
    *,
    timeout_seconds: int,
    env: dict[str, str],
) -> CommandResult:
    result = await _run_command(
        name,
        argv,
        timeout_seconds=timeout_seconds,
        env=env,
    )
    state.command_results.append(result)
    return result


async def _run_pre_market(
    state: SchedulerState,
    *,
    timeout_seconds: int,
    env: dict[str, str],
) -> None:
    """Run one-time pre-market preparation tasks."""
    logger.info("phase=pre-market start")
    await _run_and_record(
        state,
        "pre_snapshot_sync",
        _snapshot_command(),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    await _run_and_record(
        state,
        "pre_event_ingestion",
        _event_command(),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    await _run_and_record(
        state,
        "pre_post_submit_sync",
        _post_submit_command(),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    state.pre_market_done = True
    logger.info("phase=pre-market complete")


async def _run_end_of_day(
    state: SchedulerState,
    *,
    timeout_seconds: int,
    env: dict[str, str],
) -> None:
    """Run one-time end-of-day finalization tasks."""
    logger.info("phase=end-of-day start")
    await _run_and_record(
        state,
        "eod_snapshot_sync",
        _snapshot_command(),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    await _run_and_record(
        state,
        "eod_post_submit_sync",
        _post_submit_command(),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    state.end_of_day_done = True
    logger.info("phase=end-of-day complete")


async def _run_intraday_due_tasks(
    state: SchedulerState,
    tasks: dict[str, ScheduledTask],
    *,
    max_submit_per_day: int,
    timeout_seconds: int,
    env: dict[str, str],
    now: datetime,
) -> None:
    """Run due intraday periodic tasks sequentially."""
    if tasks["snapshot"].due(now):
        await _run_and_record(
            state,
            "snapshot_sync",
            _snapshot_command(),
            timeout_seconds=timeout_seconds,
            env=env,
        )
        tasks["snapshot"].mark_ran(now)

    if tasks["event"].due(now):
        await _run_and_record(
            state,
            "event_ingestion",
            _event_command(),
            timeout_seconds=timeout_seconds,
            env=env,
        )
        tasks["event"].mark_ran(now)

    if tasks["decision"].due(now):
        # DB-based submit budget check (survives process crash/restart)
        db_submit_count = await _get_db_submit_count(state.run_date)
        effective_submit_count = max(state.submit_count, db_submit_count)
        dry_run = effective_submit_count >= max_submit_per_day
        result = await _run_and_record(
            state,
            "decision_dry_run" if dry_run else "decision_submit_gate",
            _decision_command(dry_run=dry_run),
            timeout_seconds=timeout_seconds,
            env=env,
        )
        if not dry_run and _is_submit_consuming_result(result):
            state.submit_count += 1
            logger.warning(
                "submit budget consumed: submit_count=%d db_submit_count=%d "
                "effective=%d max=%d",
                state.submit_count,
                db_submit_count,
                effective_submit_count,
                max_submit_per_day,
            )
        tasks["decision"].mark_ran(now)

    if tasks["post_submit"].due(now):
        await _run_and_record(
            state,
            "post_submit_sync",
            _post_submit_command(),
            timeout_seconds=timeout_seconds,
            env=env,
        )
        tasks["post_submit"].mark_ran(now)


def _build_tasks(
    now: datetime,
    *,
    snapshot_interval: int,
    event_interval: int,
    decision_interval: int,
    post_submit_interval: int,
) -> dict[str, ScheduledTask]:
    """Build initial periodic task state."""
    return {
        "snapshot": ScheduledTask("snapshot", snapshot_interval, now),
        "event": ScheduledTask("event", event_interval, now),
        "decision": ScheduledTask("decision", decision_interval, now),
        "post_submit": ScheduledTask("post_submit", post_submit_interval, now),
    }


def _log_summary(state: SchedulerState) -> None:
    """Log end-of-process summary."""
    total = len(state.command_results)
    failed = [r for r in state.command_results if not r.ok]
    logger.info("=" * 72)
    logger.info("near-real scheduler summary")
    logger.info("  run_date            : %s", state.run_date.isoformat())
    logger.info("  cycles              : %d", state.cycles)
    logger.info("  tasks               : %d", total)
    logger.info("  failed_tasks         : %d", len(failed))
    logger.info("  submit_count         : %d", state.submit_count)
    logger.info("  pre_market_done      : %s", state.pre_market_done)
    logger.info("  end_of_day_done      : %s", state.end_of_day_done)
    for result in failed[:10]:
        logger.info(
            "  failed task          : %s returncode=%s timeout=%s",
            result.name,
            result.returncode,
            result.timed_out,
        )
    logger.info("=" * 72)


async def _run_scheduler(args: argparse.Namespace) -> int:
    """Run the near-real operations scheduler."""
    _load_env()

    env = _build_base_env()
    kis_env = env.get("KIS_ENV", "paper")
    logger.info(
        "Starting near-real scheduler (KIS_ENV=%s, paper is treated as near-real).",
        kis_env,
    )

    run_date = args.run_date or datetime.now(KST).date()
    state = SchedulerState(run_date=run_date)

    pre_market_at = _combine(run_date, args.pre_market_start)
    intraday_at = _combine(run_date, args.intraday_start)
    market_close_at = _combine(run_date, args.market_close)
    end_at = _combine(run_date, args.end_of_day_end)

    if args.once:
        now = datetime.now(KST)
        tasks = _build_tasks(
            now,
            snapshot_interval=args.snapshot_interval,
            event_interval=args.event_interval,
            decision_interval=args.decision_interval,
            post_submit_interval=args.post_submit_interval,
        )
        if not args.skip_pre_market:
            await _run_pre_market(
                state,
                timeout_seconds=args.task_timeout,
                env=env,
            )
        await _run_intraday_due_tasks(
            state,
            tasks,
            max_submit_per_day=args.max_submit_per_day,
            timeout_seconds=args.task_timeout,
            env=env,
            now=now,
        )
        if args.run_eod:
            await _run_end_of_day(
                state,
                timeout_seconds=args.task_timeout,
                env=env,
            )
        _log_summary(state)
        return 0 if all(r.ok for r in state.command_results) else 1

    now = datetime.now(KST)
    tasks = _build_tasks(
        max(now, intraday_at),
        snapshot_interval=args.snapshot_interval,
        event_interval=args.event_interval,
        decision_interval=args.decision_interval,
        post_submit_interval=args.post_submit_interval,
    )

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        logger.info("Shutdown requested; current task will finish before exit.")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # pragma: no cover
            signal.signal(sig, lambda _sig, _frame: _request_stop())

    while not stop_event.is_set():
        state.cycles += 1
        now = datetime.now(KST)

        if now.date() > run_date or now >= end_at:
            logger.info("Reached scheduler end time: now=%s end=%s", now, end_at)
            break

        if now >= pre_market_at and not state.pre_market_done and not args.skip_pre_market:
            await _run_pre_market(
                state,
                timeout_seconds=args.task_timeout,
                env=env,
            )

        if intraday_at <= now < market_close_at:
            await _run_intraday_due_tasks(
                state,
                tasks,
                max_submit_per_day=args.max_submit_per_day,
                timeout_seconds=args.task_timeout,
                env=env,
                now=now,
            )

        if now >= market_close_at and not state.end_of_day_done:
            await _run_end_of_day(
                state,
                timeout_seconds=args.task_timeout,
                env=env,
            )

        await asyncio.sleep(args.tick_seconds)

    _log_summary(state)
    return 0 if all(r.ok for r in state.command_results) else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Near-real internal operations scheduler.",
    )
    parser.add_argument(
        "--run-date",
        type=lambda value: date.fromisoformat(value),
        default=None,
        help="KST operating date in YYYY-MM-DD format (default: today).",
    )
    parser.add_argument("--pre-market-start", type=_parse_hhmm, default=PRE_MARKET_START)
    parser.add_argument("--intraday-start", type=_parse_hhmm, default=INTRADAY_START)
    parser.add_argument("--market-close", type=_parse_hhmm, default=MARKET_CLOSE)
    parser.add_argument("--end-of-day-end", type=_parse_hhmm, default=END_OF_DAY_END)
    parser.add_argument("--snapshot-interval", type=int, default=DEFAULT_SNAPSHOT_INTERVAL_SECONDS)
    parser.add_argument("--event-interval", type=int, default=DEFAULT_EVENT_INTERVAL_SECONDS)
    parser.add_argument("--decision-interval", type=int, default=DEFAULT_DECISION_INTERVAL_SECONDS)
    parser.add_argument("--post-submit-interval", type=int, default=DEFAULT_POST_SUBMIT_INTERVAL_SECONDS)
    parser.add_argument("--tick-seconds", type=int, default=5)
    parser.add_argument("--task-timeout", type=int, default=DEFAULT_TASK_TIMEOUT_SECONDS)
    parser.add_argument("--max-submit-per-day", type=int, default=1)
    parser.add_argument("--skip-pre-market", action="store_true", default=False)
    parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Run one scheduler tick immediately for smoke validation.",
    )
    parser.add_argument(
        "--run-eod",
        action="store_true",
        default=False,
        help="With --once, also run end-of-day tasks.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] near-real-scheduler: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = _parse_args(argv)
    return asyncio.run(_run_scheduler(args))


if __name__ == "__main__":
    sys.exit(main())
