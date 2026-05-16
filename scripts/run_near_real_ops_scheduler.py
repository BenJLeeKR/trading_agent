#!/usr/bin/env python3
"""
Operations scheduler — KIS market session aware trading scheduler.

NOTE: This module is kept for backward compatibility.
The canonical entrypoint is scripts.run_ops_scheduler.

This is a single-process, in-application scheduler for the KIS trading
day. It does not depend on cron/systemd timers for task timing.

The scheduler intentionally reuses the existing operational entrypoints:

* ``run_snapshot_sync_loop.py --max-cycles 1``
* ``run_event_ingestion_loop.py --count 1``
* ``run_paper_decision_loop.py --count 1``
* ``run_post_submit_sync_loop.py --once``

P0 scope is conservative: one process manages timing and safety gates, while
the existing scripts keep broker/API/database behavior unchanged.

Session Gate (P1, 2026-05-16)
==============================
Before each phase transition (pre-market / intraday / EOD), the scheduler
calls ``MarketSessionProvider.is_trading_day()`` to confirm the current
date is an actual KIS trading day:

* ``KisHolidayProvider``: 076 REST API (국내휴장일조회) — **live credential**
  completely separated from paper/live order path.
* ``FallbackSessionProvider``: weekday heuristic when live-info not configured
  or API unavailable.

Dual-provider architecture prevents accidental live credential leakage into
submit/order/balance paths while enabling accurate holiday detection.
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

# Session gate — P1 market session hardening (076 API + fallback)
from agent_trading.services.market_session import (
    CombinedSessionProvider,
    MarketSessionProvider,
    SCHEDULER_ADVISORY_LOCK_KEY,
    SessionInfo,
    create_session_provider,
    try_scheduler_lock,
)

# P2: 163 WebSocket market state + DB session persistence
from agent_trading.brokers.koreainvestment.market_state_client import (
    KisMarketStateClient,
    MarketPhaseCode,
    MarketStateProvider,
)
from agent_trading.config.settings import AppSettings

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

# After-hours snapshot window (seconds after EOD phase)
AFTER_HOURS_SNAPSHOT_WINDOW_SECONDS: int = 3600  # 1 hour
# Budget-consuming order statuses for DB-based submit budget safeguard.
# These statuses indicate that a submit budget slot was consumed.
#
# NOTE: reconcile_required is intentionally excluded because broker truth has
# not yet been confirmed.  Counting it as budget-consumed would cause the
# submit gate to block legitimate submissions (see scheduler_submit_gate_block
# post-mortem: plans/scheduler_submit_gate_block_reason_2026-05-15.md).
_BUDGET_CONSUMING_STATUSES: frozenset[str] = frozenset({
    "submitted",
    "acknowledged",
    "partially_filled",
    "filled",
})

PRE_MARKET_START = dtime(8, 0)
INTRADAY_START = dtime(8, 50)
MARKET_CLOSE = dtime(15, 30)
END_OF_DAY_END = dtime(16, 30)

logger = logging.getLogger("ops_scheduler")


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
    after_hours_mode: bool = False
    after_hours_next_snapshot_at: datetime | None = None
    submit_count: int = 0
    cycles: int = 0
    command_results: list[CommandResult] = field(default_factory=list)
    # P1: Session gate state
    session_info: SessionInfo | None = None
    # P2: Real-time market phase tracking
    market_phase: str | None = None
    last_phase_change: datetime | None = None
    session_db_id: int | None = None


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


async def _session_gate(
    session_provider: MarketSessionProvider,
    run_date: date,
    state: SchedulerState,
    phase_name: str,
) -> bool:
    """Check if the session gate permits the given phase to run.

    Returns ``True`` if the phase may proceed, ``False`` if it should be
    skipped (non-trading day).

    On first call for the day, fetches ``SessionInfo`` via the provider and
    caches it in ``state.session_info`` for observability logging.
    On subsequent calls, reuses the cached info.
    """
    if state.session_info is None:
        try:
            info = await session_provider.get_session_info(run_date)
        except Exception:
            logger.exception(
                "session_gate: provider.get_session_info failed for %s — "
                "allowing phase to proceed conservatively",
                run_date.isoformat(),
            )
            state.session_info = SessionInfo(
                is_trading_day=True,
                source="gate_error_fallback",
                reason="provider exception — conservative allow",
            )
            return True
        state.session_info = info

    if not state.session_info.is_trading_day:
        logger.warning(
            "session_gate: SKIP phase=%s run_date=%s "
            "session_source=%s opnd_yn=%s bzdy_yn=%s tr_day_yn=%s reason=%s",
            phase_name,
            run_date.isoformat(),
            state.session_info.source,
            state.session_info.opnd_yn,
            state.session_info.bzdy_yn,
            state.session_info.tr_day_yn,
            state.session_info.reason,
        )
        return False

    logger.info(
        "session_gate: ALLOW phase=%s run_date=%s "
        "session_source=%s opnd_yn=%s bzdy_yn=%s tr_day_yn=%s "
        "market_phase=%s",
        phase_name,
        run_date.isoformat(),
        state.session_info.source,
        state.session_info.opnd_yn,
        state.session_info.bzdy_yn,
        state.session_info.tr_day_yn,
        state.market_phase or state.session_info.market_phase or "N/A",
    )
    return True


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
    """Return true when a decision command consumed the daily submit budget.

    Only ``SUBMITTED`` is considered budget-consuming because it confirms
    the broker accepted the order.  ``RECONCILE_REQUIRED`` is excluded:
    broker truth has not been confirmed, so counting it would inflate the
    submit budget and potentially block legitimate submissions.
    """
    if not result.ok:
        return False
    for obj in _extract_json_objects(result.stdout):
        status = str(obj.get("status", "")).upper()
        if status in {"SUBMITTED"}:
            return True
    return False


def _parse_snapshot_sync_summary(result: CommandResult) -> dict[str, Any]:
    """Parse snapshot sync summary metrics from command stdout.

    The snapshot sync loop logs a structured line like::

        sync-cycle  accounts=1 (ok=1 partial=0 fail=0 skip=0)  positions=5 (skipped=0)  cash=1  errors=0

    Returns a dict with parsed metrics or empty dict on failure.
    """
    metrics: dict[str, Any] = {}
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if "sync-cycle" in stripped:
            # Extract key=value pairs from the log line
            import re
            m = re.search(
                r"accounts=(\d+).*?ok=(\d+).*?partial=(\d+).*?fail=(\d+).*?skip=(\d+).*?"
                r"positions=(\d+).*?skipped=(\d+).*?cash=(\d+).*?errors=(\d+)",
                stripped,
            )
            if m:
                metrics["total_accounts"] = int(m.group(1))
                metrics["succeeded"] = int(m.group(2))
                metrics["partial"] = int(m.group(3))
                metrics["failed"] = int(m.group(4))
                metrics["skipped"] = int(m.group(5))
                metrics["total_positions_synced"] = int(m.group(6))
                metrics["total_positions_skipped"] = int(m.group(7))
                metrics["total_cash_synced"] = int(m.group(8))
                metrics["errors"] = int(m.group(9))
            break
    return metrics


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
    if result.stderr.strip():
        logger.error(
            "task=%s stderr:\n%s",
            name,
            result.stderr.strip(),
        )
    if result.stdout.strip():
        logger.log(
            logging.ERROR if not result.ok else logging.DEBUG,
            "task=%s stdout:\n%s",
            name,
            result.stdout.strip(),
        )
    return result


def _snapshot_command(*, after_hours: bool = False) -> list[str]:
    argv = [PYTHON_BIN, "scripts/run_snapshot_sync_loop.py", "--max-cycles", "1"]
    if after_hours:
        argv.append("--after-hours")
    return argv


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
    """Run one-time pre-market preparation tasks.

    After snapshot sync, validates that both cash and position snapshots
    were successfully refreshed. Logs a warning if cash sync is missing
    (e.g., KIS API not yet available before market open).
    """
    logger.info("phase=pre-market start")

    # ── Step 1: Snapshot sync ──────────────────────────────────────────
    snap_result = await _run_and_record(
        state,
        "pre_snapshot_sync",
        _snapshot_command(),
        timeout_seconds=timeout_seconds,
        env=env,
    )

    # Validate snapshot sync result: cash must be synced
    snap_metrics = _parse_snapshot_sync_summary(snap_result)
    if snap_metrics:
        total_cash = snap_metrics.get("total_cash_synced", 0)
        total_accounts = snap_metrics.get("total_accounts", 0)
        if total_cash == 0 and total_accounts > 0:
            logger.warning(
                "pre-market snapshot sync: cash_synced=0 accounts=%d "
                "positions=%d — KIS API may not yet return cash balance "
                "before market open. Stale-snapshot guardrail will block "
                "submits until cash is refreshed.",
                total_accounts,
                snap_metrics.get("total_positions_synced", 0),
            )
        elif total_cash > 0:
            logger.info(
                "pre-market snapshot sync: cash_synced=%d accounts=%d positions=%d",
                total_cash,
                total_accounts,
                snap_metrics.get("total_positions_synced", 0),
            )
    else:
        logger.warning(
            "pre-market snapshot sync: could not parse sync summary from stdout. "
            "task=%s returncode=%s",
            snap_result.name,
            snap_result.returncode,
        )

    # ── Step 2: Event ingestion ────────────────────────────────────────
    await _run_and_record(
        state,
        "pre_event_ingestion",
        _event_command(),
        timeout_seconds=timeout_seconds,
        env=env,
    )

    # ── Step 3: Post-submit sync ───────────────────────────────────────
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
    snapshot_interval: int = DEFAULT_SNAPSHOT_INTERVAL_SECONDS,
) -> None:
    """Run one-time end-of-day finalization tasks.

    After the initial EOD snapshot and post-submit sync, transitions
    into after-hours mode where only snapshot sync continues at regular
    intervals (no decision loop, no event ingestion, no post-submit-sync).
    """
    logger.info("phase=end-of-day start")
    await _run_and_record(
        state,
        "eod_snapshot_sync",
        _snapshot_command(after_hours=True),  # EOD snapshot uses after-hours flag
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
    # Enter after-hours mode: continue snapshot sync only
    state.after_hours_mode = True
    now = datetime.now(KST)
    state.after_hours_next_snapshot_at = now + timedelta(seconds=snapshot_interval)
    logger.info(
        "phase=end-of-day complete — entering after-hours snapshot mode "
        "(next snapshot at %s, interval=%ds, window=%ds)",
        state.after_hours_next_snapshot_at.isoformat(),
        snapshot_interval,
        AFTER_HOURS_SNAPSHOT_WINDOW_SECONDS,
    )


async def _run_after_hours_snapshot_cycle(
    state: SchedulerState,
    *,
    timeout_seconds: int,
    env: dict[str, str],
    now: datetime,
) -> None:
    """Run a single after-hours snapshot sync cycle.

    Only snapshot sync is performed — no decision loop, event ingestion,
    or post-submit-sync runs during after-hours.

    This is called from the main loop when ``state.after_hours_mode`` is
    True and the snapshot timer has elapsed.
    """
    if state.after_hours_next_snapshot_at is None or now < state.after_hours_next_snapshot_at:
        return
    logger.info(
        "phase=after-hours snapshot cycle due at %s",
        now.isoformat(),
    )
    await _run_and_record(
        state,
        "after_hours_snapshot_sync",
        _snapshot_command(after_hours=True),  # after-hours cycle always uses --after-hours
        timeout_seconds=timeout_seconds,
        env=env,
    )
    # Schedule next after-hours snapshot
    state.after_hours_next_snapshot_at = now + timedelta(
        seconds=DEFAULT_SNAPSHOT_INTERVAL_SECONDS,
    )
    logger.info(
        "after-hours snapshot cycle complete — next at %s",
        state.after_hours_next_snapshot_at.isoformat(),
    )


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
    logger.info("ops-scheduler summary")
    logger.info("  run_date            : %s", state.run_date.isoformat())
    logger.info("  cycles              : %d", state.cycles)
    logger.info("  tasks               : %d", total)
    logger.info("  failed_tasks         : %d", len(failed))
    logger.info("  submit_count         : %d", state.submit_count)
    logger.info("  pre_market_done      : %s", state.pre_market_done)
    logger.info("  end_of_day_done      : %s", state.end_of_day_done)
    logger.info("  after_hours_active   : %s", state.after_hours_mode)
    if state.session_info:
        logger.info("  session_source       : %s", state.session_info.source)
        logger.info("  session_opnd_yn      : %s", state.session_info.opnd_yn)
        logger.info("  session_bzdy_yn      : %s", state.session_info.bzdy_yn)
        logger.info("  session_tr_day_yn    : %s", state.session_info.tr_day_yn)
        logger.info("  session_is_trading_day: %s", state.session_info.is_trading_day)
        logger.info("  session_market_phase : %s", state.session_info.market_phase or "N/A")
    # P2: Market phase tracking summary
    logger.info("  last_known_phase    : %s", state.market_phase or "N/A")
    logger.info("  last_phase_change_at: %s", state.last_phase_change.isoformat() if state.last_phase_change else "N/A")
    logger.info("  session_db_id       : %s", state.session_db_id or "N/A")
    for result in failed[:10]:
        logger.info(
            "  failed task          : %s returncode=%s timeout=%s",
            result.name,
            result.returncode,
            result.timed_out,
        )
    logger.info("=" * 72)


async def _init_market_state_provider() -> KisMarketStateClient | None:
    """Initialize 163 WebSocket market state client if live-info is configured.

    Returns ``None`` if live-info is not enabled or credentials are missing.
    """
    env = _build_base_env()
    kis_live_info_enabled = env.get("KIS_LIVE_INFO_ENABLED", "").strip().lower() == "true"
    if not kis_live_info_enabled:
        logger.info("Market state provider: skipped (KIS_LIVE_INFO_ENABLED != true)")
        return None

    # 163 Market State Provider는 KIS_LIVE_INFO_* 전용 credential 사용
    app_key = env.get("KIS_LIVE_INFO_APP_KEY", "").strip()
    api_secret = env.get("KIS_LIVE_INFO_APP_SECRET", "").strip()
    base_ws_url = env.get("KIS_LIVE_INFO_WS_URL", "").strip() or None
    if not app_key or not api_secret:
        logger.warning("market_state_provider=disabled (KIS_LIVE_INFO_APP_KEY missing)")
        return None

    # Build a minimal AppSettings for KisMarketStateClient
    settings = AppSettings()
    try:
        client = KisMarketStateClient(
            settings=settings,
            app_key=app_key,
            api_secret=api_secret,
            base_ws_url=base_ws_url,
        )
        logger.info("market_state_provider=enabled (KIS_LIVE_INFO_APP_KEY present)")
        return client
    except Exception as exc:
        logger.warning("Market state provider init failed: %s — skipping", exc)
        return None


async def _init_session_provider(
    market_state_provider: MarketStateProvider | None = None,
) -> MarketSessionProvider:
    """Initialize session provider from environment configuration.

    Uses ``create_session_provider()`` which resolves:
    - ``KisHolidayProvider`` (076 API) if ``KIS_LIVE_INFO_ENABLED=true`` + credentials
    - ``FallbackSessionProvider`` (weekday heuristic) otherwise

    If ``market_state_provider`` is provided, wraps the base provider in
    ``CombinedSessionProvider`` for 076+163 combined phase detection.
    """
    base_provider = await create_session_provider()

    if market_state_provider is not None and market_state_provider.is_connected:
        combined = CombinedSessionProvider(
            holiday_provider=base_provider,
            market_state_provider=market_state_provider,
        )
        logger.info(
            "Session provider initialized: CombinedSessionProvider "
            "(base=%s, market_state=%s)",
            type(base_provider).__name__,
            type(market_state_provider).__name__,
        )
        return combined

    logger.info(
        "Session provider initialized: %s (163 WS not available)",
        type(base_provider).__name__,
    )
    return base_provider


async def _close_session_provider(provider: MarketSessionProvider | None) -> None:
    """Close the session provider's underlying resources if applicable."""
    if provider is None:
        return
    # If KisHolidayProvider, close the underlying KISHolidayClient
    try:
        # Check if provider has a _client attribute (KisHolidayProvider)
        inner = getattr(provider, "_client", None)
        if inner is not None and hasattr(inner, "close"):
            await inner.close()
            logger.debug("Session provider HTTP client closed")
    except Exception:
        logger.debug("Session provider close (ignored)", exc_info=True)


async def _persist_session_state(
    state: SchedulerState,
    dsn: str | None,
) -> None:
    """Persist current session state to the ``trading.market_sessions`` table.

    Uses direct ``asyncpg`` connection (consistent with existing
    ``_get_db_submit_count`` pattern). If ``dsn`` is ``None`` or the DB
    operation fails, the error is logged and the in-memory state is preserved.
    """
    if dsn is None:
        return
    try:
        import asyncpg

        conn = await asyncpg.connect(dsn=dsn)
        try:
            opnd_yn = state.session_info.opnd_yn if state.session_info else None
            bzdy_yn = state.session_info.bzdy_yn if state.session_info else None
            tr_day_yn = state.session_info.tr_day_yn if state.session_info else None
            is_trading_day = state.session_info.is_trading_day if state.session_info else True
            source = state.session_info.source if state.session_info else "scheduler"
            reason = state.session_info.reason if state.session_info else ""
            market_phase = state.market_phase
            raw_opnd = state.session_info.raw_opnd_yn if state.session_info else None
            raw_mkop = state.session_info.raw_mkop_cls_code if state.session_info else None
            raw_antc = state.session_info.raw_antc_mkop_cls_code if state.session_info else None

            row = await conn.fetchrow(
                """
                INSERT INTO trading.market_sessions
                    (run_date, is_trading_day, opnd_yn, bzdy_yn, tr_day_yn,
                     market_phase, raw_opnd_yn, raw_mkop_cls_code,
                     raw_antc_mkop_cls_code, source, reason, checked_at)
                VALUES
                    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (run_date) DO UPDATE SET
                    is_trading_day = EXCLUDED.is_trading_day,
                    opnd_yn = EXCLUDED.opnd_yn,
                    bzdy_yn = EXCLUDED.bzdy_yn,
                    tr_day_yn = EXCLUDED.tr_day_yn,
                    market_phase = EXCLUDED.market_phase,
                    raw_opnd_yn = EXCLUDED.raw_opnd_yn,
                    raw_mkop_cls_code = EXCLUDED.raw_mkop_cls_code,
                    raw_antc_mkop_cls_code = EXCLUDED.raw_antc_mkop_cls_code,
                    source = EXCLUDED.source,
                    reason = EXCLUDED.reason,
                    checked_at = EXCLUDED.checked_at,
                    updated_at = NOW()
                RETURNING id
                """,
                state.run_date,
                is_trading_day,
                opnd_yn,
                bzdy_yn,
                tr_day_yn,
                market_phase,
                raw_opnd,
                raw_mkop,
                raw_antc,
                source,
                reason,
                datetime.now(),
            )
            if row:
                state.session_db_id = row["id"]
        finally:
            await conn.close()
    except Exception:
        logger.exception("Failed to persist session state to DB")


async def _handle_phase_change(
    state: SchedulerState,
    old_phase: str | None,
    new_phase: str,
    dsn: str | None = None,
) -> None:
    """React to a market phase change.

    - Detects transition to ``AFTER_HOURS`` → sets ``state.after_hours_mode = True``
    - Detects transition to ``HALT`` / ``UNKNOWN`` → logs warning
    - Persists updated session state to DB if DSN is available
    """
    now = datetime.now(KST)
    state.market_phase = new_phase
    state.last_phase_change = now

    if new_phase == MarketPhaseCode.AFTER_HOURS.value:
        if not state.after_hours_mode:
            state.after_hours_mode = True
            logger.info(
                "Phase change: %s -> AFTER_HOURS — enabling after-hours snapshot mode",
                old_phase or "NONE",
            )
    elif new_phase in (MarketPhaseCode.HALT.value, MarketPhaseCode.UNKNOWN.value):
        logger.warning(
            "Phase change: %s -> %s — unsafe market state detected",
            old_phase or "NONE",
            new_phase,
        )
    else:
        logger.info(
            "Phase change: %s -> %s",
            old_phase or "NONE",
            new_phase,
        )

    # Persist session state to DB
    await _persist_session_state(state, dsn)


async def _session_phase_monitor(
    state: SchedulerState,
    market_state_provider: MarketStateProvider,
    *,
    poll_interval: int = 5,
    dsn: str | None = None,
) -> None:
    """Background task that polls ``MarketStateProvider`` for phase changes.

    Runs at a configurable interval (default 5 seconds). On detecting a phase
    change, calls ``_handle_phase_change()`` to update in-memory state and
    persist to DB.

    Designed to run as an ``asyncio`` task alongside the main scheduler loop.
    """
    logger.info(
        "Session phase monitor started (poll_interval=%ds, db_persist=%s)",
        poll_interval,
        dsn is not None,
    )
    while True:
        try:
            current_state = await market_state_provider.get_current_state()
            new_phase = current_state.phase.value
            old_phase = state.market_phase

            if new_phase != old_phase:
                await _handle_phase_change(state, old_phase, new_phase, dsn)
        except asyncio.CancelledError:
            logger.info("Session phase monitor cancelled")
            break
        except Exception:
            logger.debug("Session phase monitor poll error (ignored)", exc_info=True)

        await asyncio.sleep(poll_interval)


def _build_dsn(env: dict[str, str]) -> str | None:
    """Build a DSN from environment variables.

    Resolution order:
    1. ``DATABASE_URL`` (full DSN)
    2. ``DATABASE_DSN`` (full DSN, legacy)
    3. ``DATABASE_HOST`` + ``DATABASE_PORT`` + ``DATABASE_USER`` + ``DATABASE_PASSWORD`` + ``DATABASE_NAME``
    """
    dsn = env.get("DATABASE_URL") or env.get("DATABASE_DSN")
    if dsn:
        return dsn

    host = env.get("DATABASE_HOST") or env.get("DB_HOST") or "localhost"
    port = env.get("DATABASE_PORT") or env.get("DB_PORT") or "5432"
    user = env.get("DATABASE_USER") or env.get("DB_USER") or "trading"
    password = env.get("DATABASE_PASSWORD") or env.get("DB_PASSWORD") or "trading"
    database = env.get("DATABASE_NAME") or env.get("DB_NAME") or "trading"
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


async def _heartbeat_task(state: SchedulerState, pool) -> None:
    """10초 간격으로 DB heartbeat 업데이트."""
    while True:
        try:
            if state.session_db_id is not None:
                await pool.execute(
                    "UPDATE trading.market_sessions SET last_heartbeat_at = NOW(), updated_at = NOW() WHERE id = $1",
                    state.session_db_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Heartbeat update skipped (session not yet persisted)")
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise


async def _log_startup_info(env: dict[str, str], state: SchedulerState, pool_ok: bool) -> None:
    """스케줄러 시작 정보 로깅."""
    logger.info("=" * 60)
    logger.info("🚀 Ops Scheduler starting up")
    logger.info("=" * 60)
    logger.info("  KIS env:             %s", env.get("KIS_ENV", "paper"))
    logger.info("  Live-info enabled:   %s", env.get("KIS_LIVE_INFO_ENABLED", "false"))
    logger.info("  Live-info token cache: %s (path: %s)",
        env.get("KIS_LIVE_TOKEN_CACHE_ENABLED", "false"),
        env.get("KIS_LIVE_TOKEN_CACHE_PATH", "N/A"),
    )
    logger.info("  Live-info WS URL:    %s", env.get("KIS_LIVE_INFO_WS_URL", "N/A"))
    logger.info("  Session source:      CombinedSessionProvider (076+163+fallback)")
    logger.info("  After-hours window:  %ss", env.get("SCHEDULER_AFTER_HOURS_WINDOW", "3600"))
    logger.info("  Instance ID:         %s", env.get("SCHEDULER_INSTANCE_ID", "default"))
    logger.info("  Run date:            %s", datetime.now(KST).strftime("%Y-%m-%d %A"))
    logger.info("  DB pool:             %s", "connected" if pool_ok else "not connected")
    logger.info("  Advisory lock:       enabled (key=0x%X)", SCHEDULER_ADVISORY_LOCK_KEY)
    # Credential presence diagnostics (without exposing secrets)
    trading_key_present = "present" if env.get("KIS_APP_KEY") else "missing"
    live_info_key_present = "present" if env.get("KIS_LIVE_INFO_APP_KEY") else "missing"
    logger.info("  trading_kis_config=%s", trading_key_present)
    logger.info("  live_info_kis_config=%s", live_info_key_present)
    market_state = "enabled" if (
        env.get("KIS_LIVE_INFO_ENABLED", "").strip().lower() == "true"
        and env.get("KIS_LIVE_INFO_APP_KEY")
    ) else "disabled"
    logger.info("  market_state_provider=%s", market_state)
    logger.info("=" * 60)


async def _run_scheduler(args: argparse.Namespace) -> int:
    """Run the operations scheduler."""
    _load_env()

    env = _build_base_env()
    kis_env = env.get("KIS_ENV", "paper")

    # P3: Build DSN for DB operations
    dsn = _build_dsn(env)

    run_date = args.run_date or datetime.now(KST).date()
    state = SchedulerState(run_date=run_date)

    pre_market_at = _combine(run_date, args.pre_market_start)
    intraday_at = _combine(run_date, args.intraday_start)
    market_close_at = _combine(run_date, args.market_close)
    end_at = _combine(run_date, args.end_of_day_end)

    # P2: Initialize 163 WebSocket market state provider
    market_state_provider = await _init_market_state_provider()

    # P1+P2: Initialize session provider (CombinedSessionProvider if WS available)
    session_provider = await _init_session_provider(market_state_provider)

    # P2: Start background phase monitor task
    phase_monitor_task: asyncio.Task[None] | None = None
    if market_state_provider is not None and market_state_provider.is_connected:
        phase_monitor_task = asyncio.create_task(
            _session_phase_monitor(
                state,
                market_state_provider,
                dsn=dsn,
            )
        )
        logger.info("Phase monitor background task created")

    # P3: Create DB pool for advisory lock and heartbeat
    pool = None
    if dsn:
        try:
            import asyncpg
            pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=int(env.get("DB_POOL_MIN", "2")),
                max_size=int(env.get("DB_POOL_MAX", "10")),
            )
        except Exception:
            logger.warning("Failed to create DB pool — advisory lock and heartbeat disabled")

    # P3: Startup info logging
    await _log_startup_info(env, state, pool is not None)

    # P3: Advisory lock wrapper
    async def _run_with_lock() -> int:
        """Inner scheduler logic with lock context."""
        nonlocal phase_monitor_task, run_date, state, pre_market_at, intraday_at, market_close_at, end_at

        # P3: Heartbeat task
        heartbeat_task: asyncio.Task[None] | None = None
        if pool is not None:
            heartbeat_task = asyncio.create_task(_heartbeat_task(state, pool))
            logger.info("Heartbeat background task created (interval=10s)")

        try:
            if args.once:
                now = datetime.now(KST)
                tasks = _build_tasks(
                    now,
                    snapshot_interval=args.snapshot_interval,
                    event_interval=args.event_interval,
                    decision_interval=args.decision_interval,
                    post_submit_interval=args.post_submit_interval,
                )
                # --once mode: session gate applies to all phases
                if not args.skip_pre_market:
                    if await _session_gate(session_provider, run_date, state, "pre_market"):
                        await _run_pre_market(
                            state,
                            timeout_seconds=args.task_timeout,
                            env=env,
                        )
                    else:
                        logger.info("--once: pre-market phase skipped by session gate")

                if await _session_gate(session_provider, run_date, state, "intraday"):
                    await _run_intraday_due_tasks(
                        state,
                        tasks,
                        max_submit_per_day=args.max_submit_per_day,
                        timeout_seconds=args.task_timeout,
                        env=env,
                        now=now,
                    )
                else:
                    logger.info("--once: intraday phase skipped by session gate")

                if args.run_eod:
                    if await _session_gate(session_provider, run_date, state, "end_of_day"):
                        await _run_end_of_day(
                            state,
                            timeout_seconds=args.task_timeout,
                            env=env,
                            snapshot_interval=args.snapshot_interval,
                        )
                    else:
                        logger.info("--once: end-of-day phase skipped by session gate")

                # P2: Persist final session state on --once exit
                if state.session_info is not None:
                    await _persist_session_state(state, dsn)
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
                    logger.info(
                        "═══ Reached scheduler end time — entering idle mode until next run date ═══"
                    )
                    await _persist_session_state(state, dsn)  # 현재 session state 저장
                    _log_summary(state)  # 오늘 summary 출력
                    # Idle 전환: run_date + 1일, state 초기화
                    run_date = run_date + timedelta(days=1)
                    state = SchedulerState(run_date=run_date)
                    # 시간 상수 재계산
                    pre_market_at = _combine(run_date, args.pre_market_start)
                    intraday_at = _combine(run_date, args.intraday_start)
                    market_close_at = _combine(run_date, args.market_close)
                    end_at = _combine(run_date, args.end_of_day_end)
                    logger.info("═══ Next run_date: %s — waiting for market hours ═══", run_date)
                    continue

                # 비영업일 early termination — session gate가 모든 phase를 차단하면
                # 16:30까지 대기하지 않고 즉시 graceful shutdown
                if state.session_info is not None and not state.session_info.is_trading_day:
                    logger.info(
                        "═══ Non-trading day detected (source=%s) — entering idle mode ═══",
                        state.session_info.source,
                    )
                    await _persist_session_state(state, dsn)  # 현재 session state 저장
                    _log_summary(state)  # 오늘 summary 출력
                    # 다음 날로 run_date rollover
                    run_date = run_date + timedelta(days=1)
                    state = SchedulerState(run_date=run_date)
                    # 시간 상수 재계산
                    pre_market_at = _combine(run_date, args.pre_market_start)
                    intraday_at = _combine(run_date, args.intraday_start)
                    market_close_at = _combine(run_date, args.market_close)
                    end_at = _combine(run_date, args.end_of_day_end)
                    logger.info("═══ Next run_date: %s — waiting for next trading day ═══", run_date)
                    continue

                # P1: Session gate — check before each phase
                if now >= pre_market_at and not state.pre_market_done and not args.skip_pre_market:
                    if await _session_gate(session_provider, run_date, state, "pre_market"):
                        await _run_pre_market(
                            state,
                            timeout_seconds=args.task_timeout,
                            env=env,
                        )
                    else:
                        state.pre_market_done = True  # Mark done to avoid retry
                        logger.info(
                            "Pre-market phase skipped by session gate for %s",
                            run_date.isoformat(),
                        )

                if intraday_at <= now < market_close_at:
                    if await _session_gate(session_provider, run_date, state, "intraday"):
                        await _run_intraday_due_tasks(
                            state,
                            tasks,
                            max_submit_per_day=args.max_submit_per_day,
                            timeout_seconds=args.task_timeout,
                            env=env,
                            now=now,
                        )
                    else:
                        logger.info(
                            "Intraday tasks skipped by session gate for %s",
                            run_date.isoformat(),
                        )

                if now >= market_close_at and not state.end_of_day_done:
                    if await _session_gate(session_provider, run_date, state, "end_of_day"):
                        await _run_end_of_day(
                            state,
                            timeout_seconds=args.task_timeout,
                            env=env,
                            snapshot_interval=args.snapshot_interval,
                        )
                    else:
                        state.end_of_day_done = True  # Mark done to avoid retry
                        logger.info(
                            "End-of-day phase skipped by session gate for %s",
                            run_date.isoformat(),
                        )

                # After-hours: continue snapshot sync only (no decision/post-submit)
                if state.after_hours_mode:
                    await _run_after_hours_snapshot_cycle(
                        state,
                        timeout_seconds=args.task_timeout,
                        env=env,
                        now=now,
                    )

                # Idle/non-trading day: 긴 polling interval (60초)
                if state.session_info is None or state.cycles == 0:
                    await asyncio.sleep(min(args.tick_seconds, 60))
                else:
                    await asyncio.sleep(args.tick_seconds)

            # Main loop exited via SIGTERM/SIGINT only — rollover 시에는 이미
            # _log_summary + _persist_session_state가 각 idle 전환에서 처리됨
            logger.info("Scheduler main loop exited — cleaning up background tasks")
            return 0
        finally:
            # P3: Cancel heartbeat task
            if heartbeat_task is not None and not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            # P2: Cancel phase monitor task
            if phase_monitor_task is not None and not phase_monitor_task.done():
                phase_monitor_task.cancel()
                try:
                    await phase_monitor_task
                except asyncio.CancelledError:
                    pass

            # P2: Disconnect market state provider (WebSocket)
            if market_state_provider is not None:
                try:
                    await market_state_provider.disconnect()
                    logger.debug("Market state provider disconnected")
                except Exception:
                    logger.debug("Market state provider disconnect (ignored)", exc_info=True)

            await _close_session_provider(session_provider)

    # P3: Run inner logic with advisory lock
    if pool is not None:
        async with try_scheduler_lock(pool) as acquired:
            if not acquired:
                logger.warning("❗ Scheduler advisory lock NOT acquired — another instance is running. Exiting.")
                return 1
            logger.info("✅ Scheduler advisory lock acquired — proceeding with main loop")
            return await _run_with_lock()
    else:
        logger.warning("No DB pool — running without advisory lock")
        return await _run_with_lock()


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
        format="%(asctime)s [%(levelname)s] ops-scheduler: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = _parse_args(argv)
    return asyncio.run(_run_scheduler(args))


if __name__ == "__main__":
    sys.exit(main())
