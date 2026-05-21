#!/usr/bin/env python3
"""Post-submit sync scheduler — dedicated process for order convergence.

Periodically polls active orders (SUBMITTED / ACKNOWLEDGED /
PARTIALLY_FILLED) and syncs their broker-side status and fills so that
the internal order state converges toward the terminal broker state
(FILLED / CANCELLED / REJECTED / EXPIRED).

Usage
-----
    # Default interval (30 seconds)
    python scripts/run_post_submit_sync_loop.py

    # Custom interval
    POST_SUBMIT_SYNC_INTERVAL_SECONDS=10 python scripts/run_post_submit_sync_loop.py

    # Single-shot (run once and exit)
    python scripts/run_post_submit_sync_loop.py --once

    # Run N cycles and exit
    python scripts/run_post_submit_sync_loop.py --count 5 --interval 15

Designed to be run as a companion to ``run_snapshot_sync_loop.py`` in a
dedicated container or process.  The snapshot-sync loop refreshes
position/cash data, while this loop converges order state.

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
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.transaction import transaction
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.kis_snapshot_sync import sync_kis_account_snapshots
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.order_sync_service import (
    OrderSyncService,
    PostSubmitSyncRunner,
    SyncCycleResult,
)

# ── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] post-submit-sync: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("post_submit_sync_loop")

# ── Config ─────────────────────────────────────────────────────────────────

DEFAULT_INTERVAL_SECONDS = 30

ENV_INTERVAL = "POST_SUBMIT_SYNC_INTERVAL_SECONDS"


def _read_interval() -> int:
    """Read the sync interval from the environment (seconds)."""
    raw = os.getenv(ENV_INTERVAL)
    if raw is None:
        return DEFAULT_INTERVAL_SECONDS
    try:
        val = int(raw)
        if val < 5:
            logger.warning(
                "Interval %d is too short (< 5s), using %d instead.",
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


# ── Snapshot refresh callback ──────────────────────────────────────────────


def _build_refresh_callback(
    repos: Any,
    broker_adapter: BrokerAdapter,
) -> Callable[[UUID], Awaitable[None]]:
    """Build an async callback that refreshes snapshots for a given account.

    The returned callback can be passed as ``snapshot_refresh_cb`` to
    ``PostSubmitSyncRunner``.  Failures are silently logged so that a
    failed snapshot refresh does not interrupt the sync cycle.
    """

    async def _refresh(account_id: UUID) -> None:
        try:
            # We need a KISRestClient for sync_kis_account_snapshots.
            # If the adapter is a KoreaInvestmentAdapter, use its rest client.
            # Otherwise log a warning and skip.
            client = getattr(broker_adapter, "_rest_client", None)
            if client is None:
                logger.warning(
                    "Snapshot refresh skipped: broker adapter %r has no _rest_client",
                    type(broker_adapter).__name__,
                )
                return
            result = await sync_kis_account_snapshots(
                rest_client=client,
                instrument_repo=repos.instruments,
                position_snapshot_repo=repos.position_snapshots,
                cash_balance_snapshot_repo=repos.cash_balance_snapshots,
                account_id=account_id,
            )
            logger.info(
                "Snapshot refresh complete for account=%s: "
                "positions=%d cash=%s",
                account_id,
                result.positions_synced,
                result.cash_synced,
            )
        except Exception as exc:
            logger.warning(
                "Snapshot refresh failed for account=%s: %s",
                account_id,
                exc,
            )

    return _refresh


# ── Structured logging helpers ─────────────────────────────────────────────


def _log_cycle_summary(result: SyncCycleResult, elapsed: float) -> None:
    """Log a structured summary of a sync cycle."""
    logger.info(
        "sync-cycle  "
        "orders=%d (updated=%d filled=%d partial=%d)  "
        "snapshots=%d  "
        "errors=%d  "
        "elapsed=%.2fs",
        result.total_orders,
        result.updated,
        result.filled,
        result.partial,
        result.snapshots_refreshed,
        len(result.errors),
        elapsed,
    )
    if result.errors:
        for err in result.errors[:10]:
            logger.warning("sync-error %s", err)
        if len(result.errors) > 10:
            logger.warning("sync-error ... (%d more not shown)", len(result.errors) - 10)


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
            signal.signal(sig, _handle_signal)


async def _run_one_cycle(
    settings: AppSettings,
    *,
    account_ref: str | None,
    after_hours: bool = False,
    recovery: bool = False,
) -> SyncCycleResult:
    """Execute a single post-submit sync cycle."""
    from agent_trading.brokers.koreainvestment.adapter import (
        KoreaInvestmentAdapter,
    )
    from agent_trading.brokers.koreainvestment.rest_client import (
        KISRestClient,
    )
    from agent_trading.brokers.rate_limit import (
        build_kis_budget_manager,
    )

    broker: BrokerAdapter | None = None
    try:
        # ── 1. Broker adapter ─────────────────────────────────────────
        logger.info("Creating broker adapter (env=%s) ...", settings.kis_env)
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
            dev_token_cache_enabled=settings.kis_dev_token_cache_enabled,
            dev_token_cache_path=settings.kis_dev_token_cache_path,
        )
        broker = KoreaInvestmentAdapter(
            rest_client=rest_client,
            ws_url=settings.kis_ws_url,
        )
        await broker.authenticate()
        logger.info("Broker authentication successful.")

        # ── 2. Postgres connection ─────────────────────────────────────
        logger.info("Connecting to Postgres ...")
        db_config = DatabaseConfig()
        await create_pool(db_config)

        async with transaction() as tx:
            repos = build_postgres_repositories(tx)
            order_manager = OrderManager(repos=repos)
            sync_service = OrderSyncService(
                repos=repos,
                order_manager=order_manager,
            )
            refresh_cb = _build_refresh_callback(repos, broker)
            runner = PostSubmitSyncRunner(
                repos=repos,
                sync_service=sync_service,
                broker=broker,
                snapshot_refresh_cb=refresh_cb,
            )

            logger.info(
                "Running post-submit sync cycle (account_ref=%s) ...",
                account_ref or "(default)",
            )
            # Pass tx_manager so run_sync_cycle can use per-order savepoints.
            # If a single order's sync fails (e.g. DB constraint violation),
            # only that order's savepoint is rolled back; the outer
            # transaction remains valid for remaining orders and the final
            # commit.
            result = await runner.run_sync_cycle(
                account_ref=account_ref,
                tx_manager=tx,
                after_hours=after_hours,
                recovery_mode=recovery,
            )
            await tx.commit()

        return result

    except Exception as exc:
        logger.error("Sync cycle failed: %s", exc, exc_info=True)
        return SyncCycleResult(
            total_orders=0,
            updated=0,
            filled=0,
            partial=0,
            errors=[f"cycle_failed: {exc}"],
        )
    finally:
        if broker is not None:
            try:
                await broker.close()  # type: ignore[union-attr]
            except Exception:
                pass
        try:
            await close_pool()
        except Exception:
            pass


async def _run_loop(
    *,
    account_ref: str | None,
    interval: int,
    max_cycles: int,
    after_hours: bool = False,
    recovery: bool = False,
) -> None:
    """Main loop: run sync cycles until shutdown or count limit."""
    logger.info(
        "Starting post-submit sync loop (interval=%ds, max_cycles=%s, account_ref=%s) ...",
        interval,
        "infinite" if max_cycles <= 0 else str(max_cycles),
        account_ref or "(default)",
    )
    logger.info(
        "Set %s to change interval (default=%d).",
        ENV_INTERVAL,
        DEFAULT_INTERVAL_SECONDS,
    )

    settings = AppSettings()
    cycle_count = 0

    while not _shutdown_event.is_set():
        if max_cycles > 0 and cycle_count >= max_cycles:
            logger.info("Reached requested cycle count (%d).", max_cycles)
            break

        cycle_count += 1
        logger.info("=== Cycle %d ===", cycle_count)

        cycle_start = time.monotonic()
        result = await _run_one_cycle(
            settings,
            account_ref=account_ref,
            after_hours=after_hours,
            recovery=recovery,
        )
        elapsed = time.monotonic() - cycle_start

        _log_cycle_summary(result, elapsed)

        # Check if we should continue
        if max_cycles > 0 and cycle_count >= max_cycles:
            break

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
            break
        except asyncio.TimeoutError:
            pass

    logger.info("Shutdown complete (%d cycles executed).", cycle_count)


# ── CLI ────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post-submit sync scheduler — periodically converge "
                    "active order states toward their broker-terminal status.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Run a single sync cycle and exit (overrides --interval and --count).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help=f"Seconds between sync cycles (default: {DEFAULT_INTERVAL_SECONDS}s, "
             f"overridable via {ENV_INTERVAL}).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of cycles to run (0 = infinite, default).",
    )
    parser.add_argument(
        "--account-ref",
        type=str,
        default=None,
        help="Broker account reference (default: settings.kis_account_number).",
    )
    parser.add_argument(
        "--after-hours",
        action="store_true",
        help="After-hours mode: allow EXPIRED fallback for unfilled orders",
    )
    parser.add_argument(
        "--recovery",
        action="store_true",
        help="Recovery mode: include EXPIRED orders, filter to today's orders only",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the post-submit sync scheduler."""
    args = _parse_args(argv)

    interval = args.interval or _read_interval()
    max_cycles = 1 if args.once else args.count

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers()

    try:
        loop.run_until_complete(
            _run_loop(
                account_ref=args.account_ref,
                interval=interval,
                max_cycles=max_cycles,
                after_hours=args.after_hours,
                recovery=args.recovery,
            )
        )
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
