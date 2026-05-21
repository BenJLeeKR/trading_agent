#!/usr/bin/env python3
"""Clean up orphan broker_orders where order_request is already in terminal state."""
import asyncio
import os
import sys

import asyncpg
from dotenv import load_dotenv


async def main() -> int:
    load_dotenv()
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("FATAL: DATABASE_URL not set", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(dsn=dsn)
    try:
        # Find orphan broker_orders
        orphans = await conn.fetch("""
            SELECT b.broker_order_id, b.order_request_id, o.status as req_status
            FROM trading.broker_orders b
            LEFT JOIN trading.order_requests o ON b.order_request_id = o.order_request_id
            WHERE b.broker_status = 'reconcile_required'
              AND o.status IS DISTINCT FROM 'reconcile_required'
              AND o.status IS NOT NULL
        """)

        if not orphans:
            print("No orphan broker_orders found.")
            return 0

        print(f"Found {len(orphans)} orphan broker_orders:")
        for row in orphans:
            print(f"  broker_order_id={row['broker_order_id']}, order_request_id={row['order_request_id']}, req_status={row['req_status']}")

        # Update them
        for row in orphans:
            target_status = 'rejected' if row['req_status'] == 'rejected' else 'cancelled'
            await conn.execute("""
                UPDATE trading.broker_orders
                SET broker_status = $1, updated_at = NOW()
                WHERE broker_order_id = $2
            """, target_status, row['broker_order_id'])
            print(f"  → Updated broker_order {row['broker_order_id']} to {target_status}")

        print(f"\n✅ {len(orphans)} orphan broker_orders cleaned up.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
