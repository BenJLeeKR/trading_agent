#!/usr/bin/env python3
"""Reconciliation Worker — consumes reconciliation_runs with status='started'.

Usage
-----
    # Loop mode (default interval: 30 seconds)
    python3 scripts/run_reconciliation_worker.py

    # Single cycle
    python3 scripts/run_reconciliation_worker.py --once

    # N cycles
    python3 scripts/run_reconciliation_worker.py --count 3

    # Specific account
    python3 scripts/run_reconciliation_worker.py --account-id <uuid>

    # Specific run
    python3 scripts/run_reconciliation_worker.py --run-id <uuid>

    # Dry-run (no state changes)
    python3 scripts/run_reconciliation_worker.py --once --dry-run

    # Custom batch size and interval
    python3 scripts/run_reconciliation_worker.py --limit 5 --interval 120

Designed to be run as a dedicated Docker service (``reconciliation-worker``)
that continuously consumes pending reconciliation runs. Each iteration:

1. Connects to Postgres and builds repositories.
2. Creates a ReconciliationService instance.
3. Calls ``list_pending_runs()`` to find started runs.
4. For each run, creates a ``ReconciliationRunProcessor`` and processes it.
5. Logs a structured summary (resolved/retained/escalated/skipped).
6. Sleeps for the configured interval.

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
from datetime import datetime, timezone
from uuid import UUID

from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.transaction import transaction
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.reconciliation_service import ReconciliationService
from agent_trading.services.reconciliation_worker import (
    ProcessingResult,
    ReconciliationRunProcessor,
)

# ── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] reconciliation-worker: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("reconciliation_worker")


# ── Config ─────────────────────────────────────────────────────────────────

DEFAULT_INTERVAL_SECONDS = 30
DEFAULT_BATCH_LIMIT = 10

ENV_INTERVAL = "RECONCILIATION_WORKER_INTERVAL_SECONDS"
ENV_BATCH_LIMIT = "RECONCILIATION_WORKER_BATCH_SIZE"


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


def _read_batch_limit() -> int:
    """Read the worker batch limit from the environment."""
    raw = os.getenv(ENV_BATCH_LIMIT, str(DEFAULT_BATCH_LIMIT))
    try:
        return max(1, int(raw))
    except (ValueError, TypeError):
        logger.warning(
            "Invalid %s=%r, using default %d.",
            ENV_BATCH_LIMIT, raw, DEFAULT_BATCH_LIMIT,
        )
        return DEFAULT_BATCH_LIMIT


# ── Structured logging helpers ─────────────────────────────────────────────


def _log_cycle_summary(
    results: list[ProcessingResult],
    cycle_start: float,
) -> None:
    """Log a structured summary of the cycle results."""
    resolved = sum(1 for r in results if r.status == "resolved")
    skipped = sum(1 for r in results if r.status == "skipped_no_links")
    failed = sum(1 for r in results if r.status in ("failed", "escalated"))
    retained = sum(1 for r in results if r.status == "retained")
    total_orders = sum(r.orders_processed for r in results)

    elapsed = time.monotonic() - cycle_start

    logger.info(
        "cycle-complete  "
        "runs=%d (resolved=%d skipped=%d failed=%d retained=%d)  "
        "orders=%d  elapsed=%.1fs",
        len(results), resolved, skipped, failed, retained,
        total_orders, elapsed,
    )

    for r in results:
        if r.status in ("failed", "escalated"):
            logger.warning(
                "run-%s: status=%s orders=%d error=%s",
                r.run_id, r.status, r.orders_processed, r.error or "none",
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
    repos: RepositoryContainer,
    settings: AppSettings,
    *,
    account_id: UUID | None = None,
    run_id: UUID | None = None,
    limit: int = 10,
    dry_run: bool = False,
) -> list[ProcessingResult]:
    """Execute a single reconciliation cycle.

    Parameters
    ----------
    repos : RepositoryContainer
        The repository container.
    account_id : UUID | None
        Optional account filter.
    run_id : UUID | None
        Optional run ID filter.
    limit : int
        Maximum runs to process.
    dry_run : bool
        If True, no state changes are made.

    Returns
    -------
    list[ProcessingResult]
        Results for each processed run.
    """
    reconciliation_service = ReconciliationService(repos)
    processor = ReconciliationRunProcessor(
        repos=repos,
        reconciliation_service=reconciliation_service,
        settings=settings,
        dry_run=dry_run,
    )

    # ── 1. Fetch pending runs ──
    pending_runs = await reconciliation_service.list_pending_runs(
        limit=limit,
        account_id=account_id,
        run_id=run_id,
    )

    if not pending_runs:
        logger.info("No pending reconciliation runs found.")
        return []

    logger.info(
        "Found %d pending reconciliation run(s) to process.",
        len(pending_runs),
    )

    # ── 2. Process each run sequentially ──
    results: list[ProcessingResult] = []
    for run in pending_runs:
        try:
            result = await processor.process_run(run)
            results.append(result)
        except Exception as exc:
            logger.error(
                "Run processing failed with exception: run_id=%s error=%s",
                run.reconciliation_run_id, exc, exc_info=True,
            )
            results.append(ProcessingResult(
                status="failed",
                error=str(exc),
                run_id=run.reconciliation_run_id,
            ))

    return results


async def _run_loop(
    *,
    account_id: UUID | None = None,
    run_id: UUID | None = None,
    limit: int = 10,
    dry_run: bool = False,
    max_cycles: int = 0,
) -> None:
    """Main loop: run reconciliation cycles until shutdown is requested."""
    interval = _read_interval()

    logger.info(
        "Starting reconciliation worker loop "
        "(interval=%ds, limit=%d, max_cycles=%d, dry_run=%s, "
        "account_id=%s, run_id=%s) ...",
        interval, limit, max_cycles, dry_run,
        account_id, run_id,
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
            settings = AppSettings()
            async with transaction() as tx:
                repos = build_postgres_repositories(tx)

                results = await _run_one_cycle(
                    repos,
                    settings,
                    account_id=account_id,
                    run_id=run_id,
                    limit=limit,
                    dry_run=dry_run,
                )

                await tx.commit()

            _log_cycle_summary(results, cycle_start)

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
        description="Reconciliation Worker — consumes reconciliation_runs with status='started'.",
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
        "--account-id",
        type=str,
        default=None,
        help="Only process runs for this account UUID.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Only process this specific reconciliation run UUID.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="No state changes — only log what would be done.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_BATCH_LIMIT,
        help=f"Maximum runs to process per cycle (default: {DEFAULT_BATCH_LIMIT}).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Loop interval in seconds (default: env RECONCILIATION_WORKER_INTERVAL_SECONDS or 30s).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``reconciliation-worker``."""
    args = _parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # Resolve account_id and run_id
    account_id: UUID | None = None
    if args.account_id:
        try:
            account_id = UUID(args.account_id)
        except ValueError:
            logger.error("Invalid account-id: %s", args.account_id)
            return 1

    run_id: UUID | None = None
    if args.run_id:
        try:
            run_id = UUID(args.run_id)
        except ValueError:
            logger.error("Invalid run-id: %s", args.run_id)
            return 1

    # Override interval via env if not explicitly set
    if args.interval is not None:
        os.environ[ENV_INTERVAL] = str(args.interval)

    max_cycles = 1 if args.once else args.count

    # Install signal handlers before entering the event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers()

    try:
        loop.run_until_complete(_run_loop(
            account_id=account_id,
            run_id=run_id,
            limit=args.limit,
            dry_run=args.dry_run,
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
