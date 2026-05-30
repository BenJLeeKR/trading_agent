#!/usr/bin/env python3
"""Phase 7d Subtask 3: 실행 후 DB 상세 검증"""
import asyncio, os, sys, json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

async def verify_post_run():
    import asyncpg
    
    # .env에서 직접 구성
    env_path = '/workspace/agent_trading/.env'
    for line in open(env_path):
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())
    
    user = os.environ.get('DATABASE_USER', os.environ.get('DB_USER', 'trading'))
    pw = os.environ.get('DATABASE_PASSWORD', os.environ.get('DB_PASSWORD', 'trading'))
    host = os.environ.get('DATABASE_HOST', os.environ.get('DB_HOST', 'localhost'))
    port = os.environ.get('DATABASE_PORT', os.environ.get('DB_PORT', '5432'))
    db = os.environ.get('DATABASE_NAME', os.environ.get('DB_NAME', 'trading'))
    dsn = f"postgresql://{user}:{pw}@{host}:{port}/{db}"
    
    conn = await asyncpg.connect(dsn=dsn)
    try:
        now = datetime.now(timezone.utc)
        kst_now = now.astimezone(timezone(timedelta(hours=9)))
        print(f"검증 시각: {kst_now}")
        print("=" * 80)
        
        # 0. 실행 전 baseline 확인 (5/27~5/29 reconcile_required)
        rr_before_query = """
            SELECT COUNT(*) FROM trading.order_requests
            WHERE status = 'reconcile_required'
              AND created_at >= '2026-05-27 00:00:00+09'
              AND created_at < '2026-05-30 00:00:00+09'
        """
        rr_before = await conn.fetchval(rr_before_query)
        print(f"\n0. 5/27~5/29 reconcile_required (baseline): {rr_before}건")
        
        # 1. reconcile_required 건수 (전체)
        rr_total = await conn.fetchval("SELECT COUNT(*) FROM trading.order_requests WHERE status = 'reconcile_required'")
        print(f"\n1. reconcile_required (전체): {rr_total}건 (Subtask 2에서 16건 → 변화: {rr_total - 16:+d}건)")
        
        # 2. c87f5ec3 상태 확인
        target = await conn.fetchrow("""
            SELECT order_request_id, status, status_reason_code, updated_at
            FROM trading.order_requests
            WHERE order_request_id = 'c87f5ec3-2647-440c-a959-5c185a9886cd'
        """)
        if target:
            print(f"\n2. c87f5ec3 (target order):")
            print(f"   order_request_id: {target['order_request_id']}")
            print(f"   status: {target['status']}")
            print(f"   status_reason_code: {target['status_reason_code']}")
            print(f"   updated_at: {target['updated_at']}")
        else:
            print(f"\n2. c87f5ec3: NOT FOUND")
        
        # 3. reconciliation_runs 상태 (requires_reconciliation 트리거)
        runs = await conn.fetch("""
            SELECT reconciliation_run_id, trigger_type, status, mismatch_count, started_at, completed_at
            FROM trading.reconciliation_runs
            WHERE trigger_type = 'requires_reconciliation'
            ORDER BY created_at DESC
        """)
        print(f"\n3. reconciliation_runs (requires_reconciliation): {len(runs)}건")
        for r in runs:
            rid = str(r['reconciliation_run_id'])[:8]
            started = str(r['started_at'])[:19] if r['started_at'] else 'N/A'
            completed = str(r['completed_at'])[:19] if r['completed_at'] else 'N/A'
            print(f"   {rid}... trigger={r['trigger_type']} status={r['status']} mismatch={r['mismatch_count']} started={started} completed={completed}")
        
        # 4. reconciliation_order_links 상태
        links = await conn.fetch("""
            SELECT rol.order_request_id, rol.mismatch_type
            FROM trading.reconciliation_order_links rol
            JOIN trading.reconciliation_runs rr ON rr.reconciliation_run_id = rol.reconciliation_run_id
            WHERE rr.trigger_type = 'requires_reconciliation'
            ORDER BY rr.created_at DESC, rol.created_at
        """)
        print(f"\n4. reconciliation_order_links: {len(links)}건")
        if links:
            for l in links:
                print(f"   {str(l['order_request_id'])[:8]}... mismatch={l['mismatch_type']}")
        else:
            print(f"   (데이터 없음)")
        
        # 5. order_state_events 확인 (c87f5ec3)
        events = await conn.fetch("""
            SELECT previous_status, new_status, reason_code, event_timestamp, created_at
            FROM trading.order_state_events
            WHERE order_request_id = 'c87f5ec3-2647-440c-a959-5c185a9886cd'
            ORDER BY event_timestamp
        """)
        print(f"\n5. order_state_events (c87f5ec3): {len(events)}건")
        if events:
            for e in events:
                print(f"   {e['previous_status']} → {e['new_status']} reason={e['reason_code']} @ {e['event_timestamp']}")
        else:
            print(f"   (이벤트 없음)")
        
        # 6. reconcile_required 상세 (expired로 전이되지 않은 나머지)
        remaining = await conn.fetch("""
            SELECT o.order_request_id, o.side, i.symbol, o.created_at, o.status_reason_code
            FROM trading.order_requests o
            LEFT JOIN trading.instruments i ON i.instrument_id = o.instrument_id
            WHERE o.status = 'reconcile_required'
            ORDER BY o.created_at
        """)
        print(f"\n6. 잔여 reconcile_required 상세: {len(remaining)}건")
        for r in remaining:
            created = r['created_at']
            if created.tzinfo is None:
                age = (now - created.replace(tzinfo=timezone.utc)).total_seconds() / 60
            else:
                age = (now - created).total_seconds() / 60
            print(f"   {str(r['order_request_id'])[:8]}... {r['side']} {r['symbol']} age={age:.0f}min reason={r['status_reason_code']}")
        
        # 7. 비정상 expired (status=expired 에서 broker_orders broker_status=reconcile_required)
        # order_requests에는 broker_status가 없으므로, broker_orders와 조인
        abnormal = await conn.fetchval("""
            SELECT COUNT(*) FROM trading.order_requests o
            WHERE o.status = 'expired'
              AND EXISTS (
                SELECT 1 FROM trading.broker_orders bo
                WHERE bo.order_request_id = o.order_request_id
                  AND bo.broker_status = 'reconcile_required'
              )
        """)
        print(f"\n7. 비정상 expired (order status=expired + broker_status=reconcile_required): {abnormal}건")
        
        # 8. 5/27~5/29 전체 status 분포
        dist = await conn.fetch("""
            SELECT status, COUNT(*) as cnt
            FROM trading.order_requests
            WHERE created_at >= '2026-05-27 00:00:00+09'
              AND created_at < '2026-05-30 00:00:00+09'
            GROUP BY status
            ORDER BY COUNT(*) DESC
        """)
        print(f"\n8. 5/27~5/29 전체 상태 분포:")
        if dist:
            for r in dist:
                print(f"   status={str(r['status']):<25} count={r['cnt']}")
        else:
            print(f"   (데이터 없음)")
        
        # 9. broker_orders broker_status 분포 (관련 order들)
        broker_dist = await conn.fetch("""
            SELECT bo.broker_status, COUNT(*) as cnt
            FROM trading.broker_orders bo
            JOIN trading.order_requests o ON o.order_request_id = bo.order_request_id
            WHERE o.created_at >= '2026-05-27 00:00:00+09'
              AND o.created_at < '2026-05-30 00:00:00+09'
            GROUP BY bo.broker_status
            ORDER BY COUNT(*) DESC
        """)
        print(f"\n9. broker_orders broker_status 분포 (5/27~5/29 연관):")
        if broker_dist:
            for r in broker_dist:
                print(f"   broker_status={str(r['broker_status']):<25} count={r['cnt']}")
        else:
            print(f"   (데이터 없음)")
        
        print("\n" + "=" * 80)
        print("검증 완료")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(verify_post_run())
