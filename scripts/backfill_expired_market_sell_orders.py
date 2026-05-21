#!/usr/bin/env python3
"""Backfill already-expired market SELL orders using position-delta truth.

Usage:
    python scripts/backfill_expired_market_sell_orders.py          # 실제 복구
    python scripts/backfill_expired_market_sell_orders.py --dry-run  # 미리보기
    python scripts/backfill_expired_market_sell_orders.py --limit 5  # 최대 5건만
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg
from agent_trading.db.connection import get_pool
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.order_sync_service import OrderSyncService

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill false-expired market SELL orders using position truth.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only — do not persist any changes.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of orders to process.",
    )
    return parser.parse_args()


async def find_target_orders(
    pool: asyncpg.Pool,
    dry_run: bool,
    limit: int | None,
) -> list[dict[str, Any]]:
    """Query DB for target EXPIRED market SELL orders with broker_native_order_id.

    Returns list of dicts with keys:
        order_request_id, account_id, instrument_id, requested_quantity,
        status, created_at, broker_order_id, broker_native_order_id, broker_status
    """
    async with pool.acquire() as conn:
        query = """
            SELECT o.order_request_id, o.account_id, o.instrument_id,
                   o.requested_quantity, o.status, o.created_at,
                   bo.broker_order_id, bo.broker_native_order_id, bo.broker_status
            FROM trading.order_requests o
            JOIN trading.broker_orders bo ON bo.order_request_id = o.order_request_id
            WHERE o.order_type = 'market'
              AND o.status = 'expired'
              AND o.side = 'sell'
              AND bo.broker_native_order_id IS NOT NULL
              AND bo.broker_status = 'expired'
              AND o.created_at >= NOW() - INTERVAL '24 hours'
              AND NOT EXISTS (
                  SELECT 1 FROM trading.broker_orders bo2
                  WHERE bo2.order_request_id = o.order_request_id
                    AND bo2.broker_status IN ('rejected', 'cancelled')
              )
            ORDER BY o.created_at DESC
        """
        if limit is not None:
            query += f" LIMIT {limit}"
        rows = await conn.fetch(query)
        return [dict(row) for row in rows]


async def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info(
        "Starting backfill (dry_run=%s, limit=%s)", args.dry_run, args.limit,
    )

    async with postgres_runtime() as runtime:
        repos: RepositoryContainer = runtime["repositories"]
        order_manager = OrderManager(repos)
        sync_service = OrderSyncService(repos, order_manager)

        pool = await get_pool()
        targets = await find_target_orders(pool, args.dry_run, args.limit)

        if not targets:
            logger.info("No target orders found. Nothing to do.")
            return

        logger.info("Found %d target orders.", len(targets))

        if args.dry_run:
            for t in targets:
                logger.info(
                    "[DRY-RUN] order=%s instrument=%s qty=%s broker_order=%s broker_native=%s",
                    t["order_request_id"],
                    t["instrument_id"],
                    t["requested_quantity"],
                    t["broker_order_id"],
                    t["broker_native_order_id"],
                )
            logger.info("Dry-run complete. %d orders would be processed.", len(targets))
            return

        success_count = 0
        failed_count = 0

        for t in targets:
            order = await repos.orders.get(t["order_request_id"])
            if order is None:
                logger.warning("Order not found: %s", t["order_request_id"])
                failed_count += 1
                continue

            broker_order = await repos.broker_orders.get(t["broker_order_id"])
            if broker_order is None:
                logger.warning("BrokerOrder not found: %s", t["broker_order_id"])
                failed_count += 1
                continue

            result = await sync_service.recover_expired_sell_by_position(
                order, broker_order,
            )

            if result is not None and result.status_changed:
                logger.info(
                    "[OK] order=%s %s→%s",
                    order.order_request_id, order.status.value, result.current_status.value,
                )
                success_count += 1
            else:
                logger.warning(
                    "[FAIL] order=%s no recovery (result=%s)",
                    order.order_request_id, result,
                )
                failed_count += 1

        logger.info(
            "Backfill complete: success=%d failed=%d total=%d",
            success_count, failed_count, len(targets),
        )


if __name__ == "__main__":
    asyncio.run(main())
