#!/usr/bin/env python3
"""Cleanup after APPROVE re-verification:
1. Restore smoke_test_v1 event to original state
2. Clean up PENDING_SUBMIT orders from failed attempts
"""

import asyncio

import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(
        host="localhost", port=5432, user="trading", password="trading", database="trading"
    )
    try:
        # 1. Restore smoke event to original state
        # severity/direction have NOT NULL constraints with defaults 'medium'/'neutral'
        result1 = await conn.execute("""
            UPDATE external_events
            SET
                published_at = '2026-05-11T00:38:14.347Z'::timestamptz,
                ingested_at = '2026-05-11T00:38:14.347Z'::timestamptz,
                headline = NULL,
                body_summary = NULL,
                severity = DEFAULT,
                direction = DEFAULT,
                metadata = '{"purpose": "smoke_test", "version": "v1", "synthetic": true}'
            WHERE event_id = '1f1ccf81-6da9-42d7-9e5f-9cd655027767'
        """)
        print(f"Smoke event restore: {result1}")

        # 2. Clean up PENDING_SUBMIT orders (failed submit attempts)
        # These are orders that never reached the broker
        # Delete order_state_events first (FK dependency)
        result2 = await conn.execute("""
            DELETE FROM order_state_events ose
            WHERE ose.order_request_id IN (
                SELECT order_request_id FROM order_requests
                WHERE status = 'pending_submit'
                AND created_at >= '2026-05-13'
            )
        """)
        print(f"Deleted order_state_events for pending_submit orders: {result2}")

        # Delete broker_orders (FK dependency)
        result3 = await conn.execute("""
            DELETE FROM broker_orders
            WHERE order_request_id IN (
                SELECT order_request_id FROM order_requests
                WHERE status = 'pending_submit'
                AND created_at >= '2026-05-13'
            )
        """)
        print(f"Deleted broker_orders for pending_submit orders: {result3}")

        # Finally delete the order_requests
        result4 = await conn.execute("""
            DELETE FROM order_requests
            WHERE status = 'pending_submit'
            AND created_at >= '2026-05-13'
        """)
        print(f"Deleted pending_submit order_requests: {result4}")

        # 3. Keep the SUBMITTED order (50c7032e) and its broker_order (ebb4113a)
        # as they represent the successful verification

        # 4. Verify smoke event restored
        smoke = await conn.fetchrow("""
            SELECT event_id, published_at, headline, severity, direction, metadata::text
            FROM external_events
            WHERE source_name = 'smoke_test_v1'
        """)
        print(f"\n=== Smoke Event After Restore ===")
        for k, v in smoke.items():
            print(f"  {k}: {v}")

        # 5. Count remaining orders
        cnt_or = await conn.fetchval("SELECT COUNT(*) FROM order_requests")
        cnt_bo = await conn.fetchval("SELECT COUNT(*) FROM broker_orders")
        cnt_ose = await conn.fetchval("SELECT COUNT(*) FROM order_state_events")
        print(f"\n=== After Cleanup ===")
        print(f"  order_requests: {cnt_or}")
        print(f"  broker_orders: {cnt_bo}")
        print(f"  order_state_events: {cnt_ose}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
