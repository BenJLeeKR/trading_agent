#!/usr/bin/env python3
"""Realized PnL Recompute Worker — ``realized_pnl_recompute_queue`` pending 항목을 소비한다.

Usage
-----
    # Loop mode (default interval: 300 seconds)
    python3 scripts/run_realized_pnl_recompute_worker.py

    # Single cycle
    python3 scripts/run_realized_pnl_recompute_worker.py --once

    # N cycles
    python3 scripts/run_realized_pnl_recompute_worker.py --count 3

    # Custom batch size and interval
    python3 scripts/run_realized_pnl_recompute_worker.py --limit 20 --interval 120

설계 근거
---------
계산/replay 로직은 전혀 새로 만들지 않는다 — 매 사이클마다
``RealizedPnlRecomputeService.process_pending_queue()``(이미 구현된
recompute/replay 서비스, ``realized_pnl_recompute_service.py`` 참고)를
그대로 호출할 뿐이다. 이 스크립트의 책임은 (1) 주기 실행, (2) DB 연결/
트랜잭션 준비, (3) 결과 집계 로그, (4) graceful shutdown뿐이다.

``scripts/run_reconciliation_worker.py``와 동일한 "독립 장기 실행
워커 컨테이너가 자체 polling 루프로 pending 큐를 소비한다" 패턴을
그대로 따른다 — ``run_ops_scheduler.py``의 subprocess-per-cadence
패턴(거래 시간대에 종속된 snapshot/event/decision/post_submit/fill_sync
태스크)에 새 태스크를 끼워 넣는 대신 이 패턴을 선택한 이유:

1. recompute는 거래 시간대(장중/장외)에 종속되지 않는 데이터 품질
   유지보수 작업이다 — ops_scheduler의 태스크들과 달리 시장 상태나
   거래일 판단과 무관하게 항상 동일하게 동작해야 한다.
2. reconciliation-worker가 이미 "다른 서비스가 큐(``reconciliation_runs``)
   에 넣어둔 pending 항목을 주기적으로 소비"하는 정확히 같은 형태의
   문제를 이 아키텍처로 풀고 있다 — 새 패턴을 만들 필요가 없다.
3. ops_scheduler.py(약 4000줄)에 새 ``ScheduledTask``/커맨드 빌더를
   추가하는 것보다, 이미 검증된 독립 워커 스크립트를 복제하는 쪽이
   기존 거래 스케줄링 로직에 대한 회귀 위험이 없다.

각 사이클은 실패해도 워커 전체를 죽이지 않는다 — 계좌×종목 단위
실패는 ``RealizedPnlRecomputeService.recompute_account_instrument()``가
자체적으로 흡수해 ``computation_run.status="failed"``로 기록하고 다음
pending 항목 처리를 계속한다(그 서비스의 기존 책임, 여기서 다시
구현하지 않는다). 이 스크립트는 그 결과를 집계해 로그로 남길 뿐이다.

On SIGTERM/SIGINT the current cycle completes gracefully before exit.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time

from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.transaction import transaction
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.realized_pnl_recompute_service import (
    RealizedPnlRecomputeService,
    RecomputeOutcome,
)

# ── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] realized-pnl-recompute-worker: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("realized_pnl_recompute_worker")


# ── Config ─────────────────────────────────────────────────────────────────

DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_QUEUE_LIMIT = 100

ENV_INTERVAL = "REALIZED_PNL_RECOMPUTE_WORKER_INTERVAL_SECONDS"
ENV_QUEUE_LIMIT = "REALIZED_PNL_RECOMPUTE_WORKER_QUEUE_LIMIT"


def _read_interval() -> int:
    """Read the worker interval from the environment (seconds)."""
    raw = os.getenv(ENV_INTERVAL, str(DEFAULT_INTERVAL_SECONDS))
    try:
        val = int(raw)
        if val < 5:
            logger.warning(
                "Interval %d is too short (< 5s), using %d instead.",
                val, DEFAULT_INTERVAL_SECONDS,
            )
            return DEFAULT_INTERVAL_SECONDS
        return val
    except (ValueError, TypeError):
        logger.warning(
            "Invalid %s=%r, using default %d.",
            ENV_INTERVAL, raw, DEFAULT_INTERVAL_SECONDS,
        )
        return DEFAULT_INTERVAL_SECONDS


def _read_queue_limit() -> int:
    """Read the worker per-cycle queue limit from the environment."""
    raw = os.getenv(ENV_QUEUE_LIMIT, str(DEFAULT_QUEUE_LIMIT))
    try:
        return max(1, int(raw))
    except (ValueError, TypeError):
        logger.warning(
            "Invalid %s=%r, using default %d.",
            ENV_QUEUE_LIMIT, raw, DEFAULT_QUEUE_LIMIT,
        )
        return DEFAULT_QUEUE_LIMIT


# ── Structured logging helpers ─────────────────────────────────────────────


def _log_cycle_summary(
    outcomes: tuple[RecomputeOutcome, ...],
    cycle_start: float,
) -> None:
    """Log a structured summary of the cycle results."""
    if not outcomes:
        logger.info("No pending recompute queue items found.")
        return

    processed = len(outcomes)
    completed = sum(1 for o in outcomes if o.computation_run.status == "completed")
    failed = sum(1 for o in outcomes if o.computation_run.status == "failed")
    queue_resolved = sum(len(o.resolved_queue_item_ids) for o in outcomes)

    elapsed = time.monotonic() - cycle_start

    logger.info(
        "cycle-complete  "
        "recompute_processed_count=%d recompute_completed_count=%d "
        "recompute_failed_count=%d recompute_queue_resolved_count=%d  "
        "elapsed=%.1fs",
        processed, completed, failed, queue_resolved, elapsed,
    )

    for outcome in outcomes:
        if outcome.computation_run.status == "failed":
            logger.warning(
                "recompute-failed  account_id=%s instrument_id=%s "
                "computation_run_id=%s summary=%s",
                outcome.account_id,
                outcome.instrument_id,
                outcome.computation_run.computation_run_id,
                outcome.computation_run.summary_json,
            )


# ── Core logic ─────────────────────────────────────────────────────────────


_shutdown_event = asyncio.Event()


def _handle_signal(signum: int, _frame: object) -> None:
    """Set the shutdown event on SIGTERM/SIGINT."""
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — completing current cycle then exiting ...", sig_name)
    _shutdown_event.set()


def _install_signal_handlers() -> None:
    """Install signal handlers for graceful shutdown."""
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s, None))
        except NotImplementedError:
            signal.signal(sig, _handle_signal)


async def _run_one_cycle(
    repos,
    *,
    limit: int,
) -> tuple[RecomputeOutcome, ...]:
    """Execute a single recompute cycle.

    계산/저장 로직은 전부 ``RealizedPnlRecomputeService``에 위임한다 —
    여기서는 서비스를 만들고 ``process_pending_queue()``를 호출할 뿐이다.
    """
    service = RealizedPnlRecomputeService(repos)
    return await service.process_pending_queue(limit=limit)


async def _run_loop(
    *,
    limit: int = DEFAULT_QUEUE_LIMIT,
    max_cycles: int = 0,
) -> None:
    """Main loop: run recompute cycles until shutdown is requested."""
    interval = _read_interval()

    logger.info(
        "Starting realized-pnl-recompute worker loop "
        "(interval=%ds, limit=%d, max_cycles=%d) ...",
        interval, limit, max_cycles,
    )

    cycle_count = 0
    while not _shutdown_event.is_set():
        cycle_count += 1
        logger.info("=== Cycle %d ===", cycle_count)

        cycle_start = time.monotonic()

        # ── DB connection + repositories ──
        db_config = DatabaseConfig()
        await create_pool(db_config)

        try:
            async with transaction() as tx:
                repos = build_postgres_repositories(tx)

                outcomes = await _run_one_cycle(repos, limit=limit)

                await tx.commit()

            _log_cycle_summary(outcomes, cycle_start)

        except Exception as exc:
            logger.error("Cycle failed: %s", exc, exc_info=True)
        finally:
            try:
                await close_pool()
            except Exception:
                pass

        elapsed = time.monotonic() - cycle_start
        logger.info(
            "Cycle %d complete (took %.1fs). Next cycle in %ds ...",
            cycle_count, elapsed, interval,
        )

        # Check max_cycles limit
        if max_cycles > 0 and cycle_count >= max_cycles:
            logger.info("Reached max_cycles=%d — exiting.", max_cycles)
            break

        # Wait for the interval (or shutdown signal)
        try:
            await asyncio.wait_for(
                _shutdown_event.wait(),
                timeout=interval,
            )
            break
        except asyncio.TimeoutError:
            pass

    logger.info("Shutdown complete (%d cycles executed).", cycle_count)


# ── CLI ────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Realized PnL Recompute Worker — consumes realized_pnl_recompute_queue pending items.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Run a single cycle and exit (--count 1).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Maximum number of cycles to run (0 = infinite, default).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=f"Maximum recompute_queue items to fetch per cycle "
             f"(default: env {ENV_QUEUE_LIMIT} or {DEFAULT_QUEUE_LIMIT}).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help=f"Loop interval in seconds (default: env {ENV_INTERVAL} or {DEFAULT_INTERVAL_SECONDS}s).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``realized-pnl-recompute-worker``."""
    args = _parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # Override interval/limit via env if not explicitly set via CLI
    if args.interval is not None:
        os.environ[ENV_INTERVAL] = str(args.interval)
    if args.limit is not None:
        os.environ[ENV_QUEUE_LIMIT] = str(args.limit)

    limit = _read_queue_limit()
    max_cycles = 1 if args.once else args.count

    # Install signal handlers before entering the event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers()

    try:
        loop.run_until_complete(_run_loop(
            limit=limit,
            max_cycles=max_cycles,
        ))
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — exiting.")
    finally:
        try:
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
