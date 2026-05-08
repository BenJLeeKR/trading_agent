#!/usr/bin/env python3
"""CLI script to sync KIS account positions/cash-balance into snapshot tables.

Usage
-----
    python scripts/sync_kis_snapshots.py --account-id <UUID>

Requires the usual KIS environment variables (``KIS_API_KEY``, ``KIS_API_SECRET``,
``KIS_ACCOUNT_NUMBER``, ``KIS_ACCOUNT_PRODUCT_CODE``, etc.) and a running
Postgres database (``DATABASE_URL``).

The script:
1. Loads ``AppSettings`` from environment.
2. Creates an authenticated ``KISRestClient``.
3. Connects to Postgres and builds repositories.
4. Calls ``sync_kis_account_snapshots()``.
5. Prints a summary of what was synced.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from uuid import UUID

from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import DatabaseConfig, create_pool
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.kis_snapshot_sync import sync_kis_account_snapshots

# ── KISRestClient import (lazy to avoid circular issues at module level) ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_kis_snapshots")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync KIS account positions/cash-balance into snapshot tables."
    )
    parser.add_argument(
        "--account-id",
        required=True,
        type=UUID,
        help="AccountEntity.account_id (UUID) to associate snapshots with.",
    )
    return parser.parse_args(argv)


async def _run(account_id: UUID) -> int:
    from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
    from agent_trading.brokers.rate_limit import build_kis_budget_manager
    from agent_trading.db.transaction import transaction

    settings = AppSettings()

    # ── 1. KIS REST client ─────────────────────────────────────────────
    logger.info("Creating KISRestClient (env=%s) ...", settings.kis_env)
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

    try:
        logger.info("Authenticating with KIS ...")
        await rest_client.authenticate()
        logger.info("KIS authentication successful.")

        # ── 2. Postgres connection + transaction ──────────────────────
        logger.info("Connecting to Postgres ...")
        db_config = DatabaseConfig()
        await create_pool(db_config)

        async with transaction() as tx:
            repos = build_postgres_repositories(tx)
            logger.info("Postgres repositories ready.")

            # ── 3. Run sync ───────────────────────────────────────────
            logger.info("Syncing snapshots for account_id=%s ...", account_id)
            result = await sync_kis_account_snapshots(
                rest_client=rest_client,
                instrument_repo=repos.instruments,
                position_snapshot_repo=repos.position_snapshots,
                cash_balance_snapshot_repo=repos.cash_balance_snapshots,
                account_id=account_id,
            )

            await tx.commit()

        # ── 4. Report ─────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("  KIS Snapshot Sync — Summary")
        print("=" * 60)
        print(f"  Positions synced     : {result.positions_synced}")
        print(f"  Positions skipped    : {result.positions_skipped}")
        print(f"  Cash balance         : {'synced' if result.cash_balance_synced else 'failed/skipped'}")
        if result.errors:
            print(f"  Errors ({len(result.errors)}):")
            for err in result.errors:
                print(f"    - {err}")
        print("=" * 60 + "\n")

        if result.errors:
            logger.warning("Sync completed with %d warning(s).", len(result.errors))
            return 1
        logger.info("Sync completed successfully.")
        return 0

    finally:
        await rest_client.close()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_run(args.account_id))


if __name__ == "__main__":
    sys.exit(main())
