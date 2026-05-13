#!/usr/bin/env python3
"""Check DB state after submit + sync."""

import asyncio

import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(
        host="localhost", port=5432, user="trading", password="trading", database="trading"
    )
    try:
        # 1. Broker orders count
        cnt = await conn.fetchval("SELECT COUNT(*) FROM broker_orders")
        print(f"broker_orders: {cnt}")

        # 2. Recent broker orders
        rows = await conn.fetch("""
            SELECT broker_order_id, broker_native_order_id, broker_status, 
                   last_synced_at, created_at
            FROM broker_orders
            ORDER BY created_at DESC
            LIMIT 10
        """)
        print("\n=== Recent Broker Orders ===")
        for r in rows:
            print(f"  id={r['broker_order_id']} native_id={r['broker_native_order_id']} "
                  f"status={r['broker_status']} synced={r['last_synced_at']} "
                  f"created={r['created_at']}")

        # 3. Order requests count
        cnt2 = await conn.fetchval("SELECT COUNT(*) FROM order_requests")
        print(f"\norder_requests: {cnt2}")

        # 4. Recent order requests
        reqs = await conn.fetch("""
            SELECT order_request_id, status, requested_price, requested_quantity,
                   submitted_at, created_at
            FROM order_requests
            ORDER BY created_at DESC
            LIMIT 10
        """)
        print("\n=== Recent Order Requests ===")
        for r in reqs:
            print(f"  id={r['order_request_id']} status={r['status']} "
                  f"price={r['requested_price']} qty={r['requested_quantity']} "
                  f"submitted={r['submitted_at']} created={r['created_at']}")

        # 5. Order state events count
        cnt3 = await conn.fetchval("SELECT COUNT(*) FROM order_state_events")
        print(f"\norder_state_events: {cnt3}")

        # 6. Recent order state events
        evts = await conn.fetch("""
            SELECT order_state_event_id, order_request_id, previous_status, new_status, created_at
            FROM order_state_events
            ORDER BY created_at DESC
            LIMIT 10
        """)
        print("\n=== Recent Order State Events ===")
        for r in evts:
            print(f"  id={r['order_state_event_id']} order={r['order_request_id']} "
                  f"prev={r['previous_status']} new={r['new_status']} at={r['created_at']}")

        # 7. Trade decisions count
        cnt4 = await conn.fetchval("SELECT COUNT(*) FROM trade_decisions")
        print(f"\ntrade_decisions: {cnt4}")

        # 8. Decision contexts count
        cnt5 = await conn.fetchval("SELECT COUNT(*) FROM decision_contexts")
        print(f"decision_contexts: {cnt5}")

        # 9. Agent runs count
        cnt6 = await conn.fetchval("SELECT COUNT(*) FROM agent_runs")
        print(f"agent_runs: {cnt6}")

        # 10. Snapshot sync runs count
        cnt7 = await conn.fetchval("SELECT COUNT(*) FROM snapshot_sync_runs")
        print(f"snapshot_sync_runs: {cnt7}")

        # 11. Cash balance
        cash = await conn.fetchrow("""
            SELECT available_cash, settled_cash, snapshot_at
            FROM cash_balance_snapshots
            ORDER BY snapshot_at DESC
            LIMIT 1
        """)
        if cash:
            print(f"\n=== Latest Cash Balance ===")
            print(f"  available={cash['available_cash']} settled={cash['settled_cash']} "
                  f"at={cash['snapshot_at']}")

        # 12. External events count
        cnt8 = await conn.fetchval("SELECT COUNT(*) FROM external_events")
        print(f"\nexternal_events: {cnt8}")

        # 13. Smoke event state
        smoke = await conn.fetchrow("""
            SELECT event_id, published_at, ingested_at, headline, severity, direction, metadata::text
            FROM external_events
            WHERE source_name = 'smoke_test_v1'
        """)
        if smoke:
            print(f"\n=== Smoke Event State ===")
            for k, v in smoke.items():
                print(f"  {k}: {v}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
