import asyncio
import asyncpg
import os
from datetime import datetime, timezone

async def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL not set")
        return
    
    conn = await asyncpg.connect(dsn)
    
    try:
        # 1. Reconciliation runs created today
        rows = await conn.fetch("""
            SELECT reconciliation_run_id, trigger_type, status, created_at,
                   (SELECT COUNT(*) FROM trading.reconciliation_order_links rol WHERE rol.reconciliation_run_id = rr.reconciliation_run_id) AS order_count
            FROM trading.reconciliation_runs rr
            WHERE created_at >= $1
            ORDER BY created_at DESC
        """, datetime(2026, 5, 29, 15, 0, 0, tzinfo=timezone.utc))  # KST 2026-05-30 00:00
        
        print(f"\n=== Reconciliation runs (KST 2026-05-30~) ===")
        print(f"Total runs: {len(rows)}")
        for r in rows:
            print(f"  reconciliation_run_id={r['reconciliation_run_id']}, trigger={r['trigger_type']}, status={r['status']}, created={r['created_at']}, orders={r['order_count']}")
        
        # 2. Remaining reconcile_required in date range
        remaining = await conn.fetch("""
            SELECT COUNT(*) AS cnt
            FROM trading.order_requests
            WHERE created_at >= '2026-05-27T15:00:00Z'
              AND created_at < '2026-05-29T15:00:00Z'
              AND status = 'reconcile_required'
        """)
        print(f"\n=== Remaining reconcile_required (5/28~5/29) ===")
        print(f"  Count: {remaining[0]['cnt']}")
        
        if remaining[0]['cnt'] > 0:
            details = await conn.fetch("""
                SELECT order_request_id, side, requested_quantity, status_reason_code,
                       (SELECT last_synced_at FROM trading.broker_orders bo WHERE bo.order_request_id = or2.order_request_id LIMIT 1) AS last_synced_at
                FROM trading.order_requests or2
                WHERE created_at >= '2026-05-27T15:00:00Z'
                  AND created_at < '2026-05-29T15:00:00Z'
                  AND status = 'reconcile_required'
                ORDER BY created_at
                LIMIT 10
            """)
            for d in details:
                print(f"  order_request_id={d['order_request_id']}, side={d['side']}, qty={d['requested_quantity']}, reason={d['status_reason_code']}, last_sync={d['last_synced_at']}")
        
        # 3. Expired + broker_status='reconcile_required' (non-actionable, for awareness)
        expired_stuck = await conn.fetch("""
            SELECT COUNT(*) AS cnt
            FROM trading.order_requests or2
            JOIN trading.broker_orders bo ON bo.order_request_id = or2.order_request_id
            WHERE or2.created_at >= '2026-05-27T15:00:00Z'
              AND or2.created_at < '2026-05-29T15:00:00Z'
              AND or2.status = 'expired'
              AND bo.broker_status = 'reconcile_required'
        """)
        print(f"\n=== Expired with broker_status=reconcile_required ===")
        print(f"  Count: {expired_stuck[0]['cnt']}")
        
        # 4. Overall status distribution (post-fix)
        dist = await conn.fetch("""
            SELECT status, COUNT(*) AS cnt
            FROM trading.order_requests
            WHERE created_at >= '2026-05-27T15:00:00Z'
              AND created_at < '2026-05-29T15:00:00Z'
            GROUP BY status
            ORDER BY status
        """)
        print(f"\n=== Overall status distribution (post-fix) ===")
        for d in dist:
            print(f"  {d['status']}: {d['cnt']}")
            
    finally:
        await conn.close()

asyncio.run(main())
