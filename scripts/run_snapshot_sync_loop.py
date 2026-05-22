#!/usr/bin/env python3
"""Broker-agnostic snapshot sync loop — manual/debug job or scheduler subprocess.

Usage
-----
    # Default interval (5 minutes)
    python scripts/run_snapshot_sync_loop.py

    # Custom interval (supports both env var names)
    SNAPSHOT_SYNC_INTERVAL_SECONDS=60 python scripts/run_snapshot_sync_loop.py
    KIS_SNAPSHOT_SYNC_INTERVAL_SECONDS=60 python scripts/run_snapshot_sync_loop.py

    # Explicit broker (currently only koreainvestment)
    python scripts/run_snapshot_sync_loop.py --broker koreainvestment

Designed to be run either:

* manually via ``docker compose run snapshot-sync`` for debug/isolation, or
* as a one-shot subprocess launched by ``ops-scheduler`` during pre-market,
  intraday, and after-hours phases.

It is **not** the steady-state primary scheduler container.  Each iteration:

1. Creates an authenticated broker REST client via a ``SnapshotFetchProvider``.
2. Connects to Postgres and builds repositories.
3. Calls ``sync_all_accounts()`` (auto-discover all broker accounts).
4. Logs a structured summary (accounts synced/partial/failed, positions,
   cash, errors).
5. Sleeps for the configured interval.

On SIGTERM/SIGINT the current sync completes gracefully before exit.
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

from agent_trading.brokers.snapshot_factory import build_snapshot_sync_components
from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.transaction import transaction
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.kis_snapshot_sync import (
    BatchSyncResult,
    build_sync_run_entity,
)
from agent_trading.services.snapshot_sync import sync_all_accounts

# ── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] snapshot-sync: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("snapshot_sync_loop")


# ── Config ─────────────────────────────────────────────────────────────────

DEFAULT_INTERVAL_SECONDS = 300  # 5 minutes

ENV_INTERVAL = "KIS_SNAPSHOT_SYNC_INTERVAL_SECONDS"

# Broker-agnostic alias: SNAPSHOT_SYNC_INTERVAL_SECONDS (preferred),
# falls back to KIS_SNAPSHOT_SYNC_INTERVAL_SECONDS.
ENV_INTERVAL_AGNOSTIC = "SNAPSHOT_SYNC_INTERVAL_SECONDS"


def _read_interval() -> int:
    """Read the sync interval from the environment (seconds).

    Prefers ``SNAPSHOT_SYNC_INTERVAL_SECONDS`` (broker-agnostic alias),
    falls back to ``KIS_SNAPSHOT_SYNC_INTERVAL_SECONDS``.
    """
    raw = os.getenv(ENV_INTERVAL_AGNOSTIC) or os.getenv(
        ENV_INTERVAL, str(DEFAULT_INTERVAL_SECONDS)
    )
    try:
        val = int(raw)
        if val < 10:
            logger.warning(
                "Interval %d is too short (< 10s), using %d instead.",
                val,
                DEFAULT_INTERVAL_SECONDS,
            )
            return DEFAULT_INTERVAL_SECONDS
        return val
    except (ValueError, TypeError):
        logger.warning(
            "Invalid %s=%r, using default %d.",
            ENV_INTERVAL,
            raw,
            DEFAULT_INTERVAL_SECONDS,
        )
        return DEFAULT_INTERVAL_SECONDS


# ── Structured logging helpers ─────────────────────────────────────────────


def _log_sync_summary(result: object) -> None:
    """Extract metrics from a ``BatchSyncResult`` and log them."""
    # Using __dict__ / public properties since BatchSyncResult is a frozen dataclass
    total = getattr(result, "total_accounts", 0)
    succeeded = getattr(result, "succeeded", 0)
    partial = getattr(result, "partial", 0)
    failed = getattr(result, "failed", 0)
    skipped = getattr(result, "skipped", 0)
    positions_synced = getattr(result, "total_positions_synced", 0)
    positions_skipped = getattr(result, "total_positions_skipped", 0)
    cash_synced = getattr(result, "total_cash_synced", 0)
    errors = getattr(result, "errors", [])

    logger.info(
        "sync-cycle  "
        "accounts=%d (ok=%d partial=%d fail=%d skip=%d)  "
        "positions=%d (skipped=%d)  "
        "cash=%d  "
        "errors=%d",
        total,
        succeeded,
        partial,
        failed,
        skipped,
        positions_synced,
        positions_skipped,
        cash_synced,
        len(errors),
    )

    if cash_synced == 0 and total > 0:
        logger.warning(
            "sync-cycle CASH_SYNC_ZERO: accounts=%d positions=%d — "
            "cash balance was not synced for any account. "
            "Stale-snapshot guardrail will block submits until cash is refreshed.",
            total,
            positions_synced,
        )

    if errors:
        for err in errors[:5]:  # Log at most 5 errors per cycle
            logger.warning("sync-error %s", err)
        if len(errors) > 5:
            logger.warning("sync-error ... (%d more not shown)", len(errors) - 5)


# ── Core loop ──────────────────────────────────────────────────────────────

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
            # Windows or environments without signal handles
            signal.signal(sig, _handle_signal)


async def _run_one_cycle(
    settings: AppSettings,
    broker: str,
    after_hours: bool = False,
    fetch_positions: bool = True,
) -> None:
    """Execute a single sync cycle with its own broker client + DB connection."""
    # Lazy imports to keep module-level import fast
    components = build_snapshot_sync_components(broker, settings)

    provider = components.provider
    started_at = datetime.now(timezone.utc)

    try:
        # ── 1. Broker authentication ─────────────────────────────────────
        logger.info(
            "Authenticating broker client (broker=%s, env=%s, account=%s) ...",
            broker,
            settings.kis_env,
            settings.kis_account_number or "(auto-discover)",
        )
        await components.client.authenticate()
        logger.info("Broker authentication successful.")

        # ── 2. Postgres connection ─────────────────────────────────────
        logger.info("Connecting to Postgres ...")
        db_config = DatabaseConfig()
        await create_pool(db_config)

        # ── 3. Run auto-discover sync ──────────────────────────────────
        async with transaction() as tx:
            repos = build_postgres_repositories(tx)
            logger.info(
                "Repositories ready. Running sync_all_accounts(after_hours=%s, fetch_positions=%s) ...",
                after_hours,
                fetch_positions,
            )

            batch = await sync_all_accounts(
                fetch_provider=provider,
                instrument_repo=repos.instruments,
                position_snapshot_repo=repos.position_snapshots,
                cash_balance_snapshot_repo=repos.cash_balance_snapshots,
                risk_limit_snapshot_repo=repos.risk_limit_snapshots,
                broker_account_repo=repos.broker_accounts,
                account_repo=repos.accounts,
                broker_name=broker,
                account_number=settings.kis_account_number,
                after_hours=after_hours,
                fetch_positions=fetch_positions,
            )

            # ── 4. Save execution history ──────────────────────────────
            run_entity = build_sync_run_entity(
                batch,
                trigger_type="scheduler",
                scope="all",
                dry_run=False,
                started_at=started_at,
                after_hours=after_hours,
            )
            await repos.snapshot_sync_runs.add(run_entity)

            await tx.commit()

        # ── 5. Log structured summary ──────────────────────────────────
        _log_sync_summary(batch)

    except Exception as exc:
        logger.error("Sync cycle failed: %s", exc, exc_info=True)
    finally:
        try:
            await components.client.close()
        except Exception:
            pass
        try:
            await close_pool()
        except Exception:
            pass


async def _run_loop(
    broker: str,
    max_cycles: int = 0,
    after_hours: bool = False,
    fetch_positions: bool = True,
) -> None:
    """Main loop: run sync cycles until shutdown is requested."""
    interval = _read_interval()
    logger.info(
        "Starting snapshot sync loop (broker=%s, interval=%ds, max_cycles=%d, after_hours=%s, env=%s) ...",
        broker,
        interval,
        max_cycles,
        after_hours,
        os.getenv("KIS_ENV", "paper"),
    )
    logger.info(
        "Set %s (or %s) to change interval (default=%d).",
        ENV_INTERVAL_AGNOSTIC,
        ENV_INTERVAL,
        DEFAULT_INTERVAL_SECONDS,
    )

    settings = AppSettings()
    logger.info(
        "Token cache: enabled=%s path=%s",
        settings.kis_dev_token_cache_enabled,
        settings.kis_dev_token_cache_path,
    )

    cycle_count = 0
    while not _shutdown_event.is_set():
        cycle_count += 1
        logger.info("=== Cycle %d (broker=%s) ===", cycle_count, broker)

        cycle_start = time.monotonic()
        await _run_one_cycle(
            settings, broker,
            after_hours=after_hours,
            fetch_positions=fetch_positions,
        )
        elapsed = time.monotonic() - cycle_start

        logger.info(
            "Cycle %d complete (took %.1fs). Next cycle in %ds ...",
            cycle_count,
            elapsed,
            interval,
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
            # If shutdown is set, break immediately
            break
        except asyncio.TimeoutError:
            # Normal timeout — proceed to next cycle
            pass

    logger.info("Shutdown complete (%d cycles executed).", cycle_count)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Snapshot sync scheduler — continuously keep broker account snapshots fresh.",
    )
    parser.add_argument(
        "--broker",
        type=str,
        default="koreainvestment",
        help="Broker name (default: koreainvestment).",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=0,
        help="Maximum number of cycles to run (0 = infinite, default).",
    )
    parser.add_argument(
        "--after-hours",
        action="store_true",
        default=False,
        help="Enable after-hours mode: passes after_hours=True so AFHR_FLPR_YN=Y is used for cash balance inquiry.",
    )
    parser.add_argument(
        "--fetch-positions",
        type=lambda x: x.lower() in ("true", "1", "yes"),
        default=True,
        help="Fetch positions (default: True). Set False for cash+orderable only.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``snapshot-sync`` scheduler."""
    args = _parse_args(argv)
    broker = args.broker
    max_cycles = args.max_cycles
    after_hours = args.after_hours
    fetch_positions = args.fetch_positions

    # Install signal handlers before entering the event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers()

    try:
        loop.run_until_complete(
            _run_loop(
                broker, max_cycles,
                after_hours=after_hours,
                fetch_positions=fetch_positions,
            )
        )
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — exiting.")
    finally:
        try:
            # Cancel any pending tasks
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
