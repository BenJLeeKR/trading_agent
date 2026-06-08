#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.transaction import transaction
from agent_trading.domain.entities import FillSyncRunEntity
from agent_trading.domain.enums import Environment
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.fill_history_sync import (
    build_fill_sync_run_entity,
    sync_all_fill_history,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] fill-sync: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fill_sync_loop")

DEFAULT_INTERVAL_SECONDS = 600
ENV_INTERVAL = "FILL_SYNC_INTERVAL_SECONDS"
_shutdown_event = asyncio.Event()


def _read_interval() -> int:
    raw = os.getenv(ENV_INTERVAL)
    if raw is None:
        return DEFAULT_INTERVAL_SECONDS
    try:
        return max(60, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS


def _handle_signal(signum: int, _frame: object) -> None:
    logger.info("Received %s — exiting after current cycle", signal.Signals(signum).name)
    _shutdown_event.set()


def _install_signal_handlers() -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s, None))
        except NotImplementedError:
            signal.signal(sig, _handle_signal)


def _log_summary(batch: object) -> None:
    logger.info(
        "fill-sync-cycle accounts=%s succeeded=%s partial=%s failed=%s skipped=%s fills=%s skipped_fills=%s retries=%s retried_accounts=%s errors=%s",
        getattr(batch, "total_accounts", 0),
        getattr(batch, "succeeded", 0),
        getattr(batch, "partial", 0),
        getattr(batch, "failed", 0),
        getattr(batch, "skipped", 0),
        getattr(batch, "total_fills_synced", 0),
        getattr(batch, "total_fills_skipped", 0),
        getattr(batch, "total_retries", 0),
        getattr(batch, "retried_accounts", 0),
        len(getattr(batch, "errors", [])),
    )


async def _run_one_cycle(
    settings: AppSettings,
    *,
    after_hours: bool = False,
) -> None:
    from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
    from agent_trading.brokers.rate_limit import build_kis_budget_manager

    budget_manager = build_kis_budget_manager(
        kis_env=settings.kis_env,
        real_rest_rps=settings.kis_real_rest_rps,
        paper_rest_rps=settings.kis_paper_rest_rps,
        shared_budget_file=settings.kis_shared_budget_file,
    )
    client = KISRestClient(
        api_key=settings.kis_api_key,
        api_secret=settings.kis_api_secret,
        account_number=settings.kis_account_number,
        account_product_code=settings.kis_account_product_code,
        env=settings.kis_env,
        base_url=settings.kis_base_url,
        budget_manager=budget_manager,
        dev_token_cache_enabled=settings.kis_dev_token_cache_enabled,
        dev_token_cache_path=settings.kis_dev_token_cache_path,
        approval_cache_enabled=settings.kis_approval_key_cache_enabled,
        approval_cache_path=settings.kis_approval_key_cache_path,
    )
    started_at = datetime.now(timezone.utc)
    run_id = uuid4()
    try:
        await client.authenticate()
        await create_pool(DatabaseConfig())
        async with transaction() as tx:
            repos = build_postgres_repositories(tx)
            running = FillSyncRunEntity(
                fill_sync_run_id=run_id,
                trigger_type="scheduler",
                scope="all",
                dry_run=False,
                total_accounts=0,
                succeeded_accounts=0,
                partial_accounts=0,
                failed_accounts=0,
                skipped_accounts=0,
                fills_synced_total=0,
                fills_skipped_total=0,
                error_count=0,
                status="running",
                started_at=started_at,
                env_filter=settings.kis_env,
                summary_json=None,
                completed_at=None,
            )
            await repos.fill_sync_runs.add(running)
            batch = await sync_all_fill_history(
                rest_client=client,
                broker_account_repo=repos.broker_accounts,
                account_repo=repos.accounts,
                fill_repo=repos.broker_fill_snapshots,
                broker_order_repo=repos.broker_orders,
                broker_name="koreainvestment",
                env=Environment(settings.kis_env),
                account_number=settings.kis_account_number,
                fill_sync_run_id=run_id,
                order_day=datetime.now(timezone(timedelta(hours=9))).date(),
                after_hours=after_hours,
            )
            run = build_fill_sync_run_entity(
                batch,
                trigger_type="scheduler",
                scope="all",
                started_at=started_at,
                env_filter=settings.kis_env,
                fill_sync_run_id=run_id,
            )
            await repos.fill_sync_runs.update_run(run)
            await tx.commit()
        _log_summary(batch)
    finally:
        await client.close()
        await close_pool()


async def _run_loop(*, max_cycles: int = 0, after_hours: bool = False) -> None:
    interval = _read_interval()
    settings = AppSettings()
    cycle = 0
    while not _shutdown_event.is_set():
        cycle += 1
        start = time.monotonic()
        await _run_one_cycle(settings, after_hours=after_hours)
        elapsed = time.monotonic() - start
        logger.info("Cycle %d complete (%.1fs)", cycle, elapsed)
        if max_cycles > 0 and cycle >= max_cycles:
            break
        try:
            await asyncio.wait_for(_shutdown_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VTTC0081R fill history sync loop")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--after-hours", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers()
    try:
        if args.once:
            loop.run_until_complete(_run_loop(max_cycles=1, after_hours=args.after_hours))
        elif args.count > 0:
            loop.run_until_complete(_run_loop(max_cycles=args.count, after_hours=args.after_hours))
        else:
            loop.run_until_complete(_run_loop(after_hours=args.after_hours))
        return 0
    finally:
        loop.close()


if __name__ == "__main__":
    raise SystemExit(main())
