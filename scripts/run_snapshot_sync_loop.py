#!/usr/bin/env python3
"""Periodic KIS snapshot sync loop — dedicated scheduler process.

Usage
-----
    # Default interval (5 minutes)
    python scripts/run_snapshot_sync_loop.py

    # Custom interval
    KIS_SNAPSHOT_SYNC_INTERVAL_SECONDS=60 python scripts/run_snapshot_sync_loop.py

Designed to be run as a dedicated Docker service (``snapshot-sync``) that
continuously keeps KIS account snapshots fresh.  Each iteration:

1. Creates an authenticated ``KISRestClient``.
2. Connects to Postgres and builds repositories.
3. Calls ``sync_all_kis_accounts()`` (auto-discover all KIS accounts).
4. Logs a structured summary (accounts synced/partial/failed, positions,
   cash, errors).
5. Sleeps for the configured interval.

On SIGTERM/SIGINT the current sync completes gracefully before exit.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.transaction import transaction
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.kis_snapshot_sync import (
    build_sync_run_entity,
    sync_all_kis_accounts,
)

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


def _read_interval() -> int:
    """Read the sync interval from the environment (seconds)."""
    raw = os.getenv(ENV_INTERVAL, str(DEFAULT_INTERVAL_SECONDS))
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


async def _run_one_cycle(settings: AppSettings) -> None:
    """Execute a single sync cycle with its own KIS client + DB connection."""
    # Lazy imports to keep module-level import fast
    from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
    from agent_trading.brokers.rate_limit import build_kis_budget_manager

    rest_client: KISRestClient | None = None
    started_at = datetime.now(timezone.utc)

    try:
        # ── 1. KIS REST client ─────────────────────────────────────────
        logger.info(
            "Creating KISRestClient (env=%s, account=%s) ...",
            settings.kis_env,
            settings.kis_account_number or "(auto-discover)",
        )
        budget_manager = build_kis_budget_manager(
            kis_env=settings.kis_env,
            real_rest_rps=settings.kis_real_rest_rps,
            paper_rest_rps=settings.kis_paper_rest_rps,
        )
        rest_client = KISRestClient(
            api_key=settings.kis_api_key,
            api_secret=settings.kis_api_secret,
            account_number=settings.kis_account_number,
            account_product_code=settings.kis_account_product_code,
            env=settings.kis_env,
            base_url=settings.kis_base_url,
            budget_manager=budget_manager,
        )

        logger.info("Authenticating with KIS ...")
        await rest_client.authenticate()
        logger.info("KIS authentication successful.")

        # ── 2. Postgres connection ─────────────────────────────────────
        logger.info("Connecting to Postgres ...")
        db_config = DatabaseConfig()
        await create_pool(db_config)

        # ── 3. Run auto-discover sync ──────────────────────────────────
        async with transaction() as tx:
            repos = build_postgres_repositories(tx)
            logger.info("Repositories ready. Running sync_all_kis_accounts() ...")

            batch = await sync_all_kis_accounts(
                rest_client=rest_client,
                instrument_repo=repos.instruments,
                position_snapshot_repo=repos.position_snapshots,
                cash_balance_snapshot_repo=repos.cash_balance_snapshots,
                broker_account_repo=repos.broker_accounts,
                account_repo=repos.accounts,
                kis_account_number=settings.kis_account_number,
            )

            # ── 4. Save execution history ──────────────────────────────
            run_entity = build_sync_run_entity(
                batch,
                trigger_type="scheduler",
                scope="all",
                dry_run=False,
                started_at=started_at,
            )
            await repos.snapshot_sync_runs.add(run_entity)

            await tx.commit()

        # ── 5. Log structured summary ──────────────────────────────────
        _log_sync_summary(batch)

    except Exception as exc:
        logger.error("Sync cycle failed: %s", exc, exc_info=True)
    finally:
        if rest_client is not None:
            try:
                await rest_client.close()
            except Exception:
                pass
        try:
            await close_pool()
        except Exception:
            pass


async def _run_loop() -> None:
    """Main loop: run sync cycles until shutdown is requested."""
    interval = _read_interval()
    logger.info(
        "Starting KIS snapshot sync loop (interval=%ds, env=%s) ...",
        interval,
        os.getenv("KIS_ENV", "paper"),
    )
    logger.info(
        "Set %s to change interval (default=%d).",
        ENV_INTERVAL,
        DEFAULT_INTERVAL_SECONDS,
    )

    settings = AppSettings()

    cycle_count = 0
    while not _shutdown_event.is_set():
        cycle_count += 1
        logger.info("=== Cycle %d ===", cycle_count)

        cycle_start = time.monotonic()
        await _run_one_cycle(settings)
        elapsed = time.monotonic() - cycle_start

        logger.info(
            "Cycle %d complete (took %.1fs). Next cycle in %ds ...",
            cycle_count,
            elapsed,
            interval,
        )

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


def main() -> int:
    """Entry point for ``snapshot-sync`` scheduler."""
    # Install signal handlers before entering the event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers()

    try:
        loop.run_until_complete(_run_loop())
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
