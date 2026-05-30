#!/usr/bin/env python3
"""
Phase 7d Subtask 4: DB 검증 스크립트
- reconcile_required 상태 주문 조회
- reconciliation_runs 상태 확인
- reconciliation_order_links 연결 상태
- _try_expired_fallback() 조건 충족 여부 분석
"""
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

async def verify_db_state():
    import asyncpg
    
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL environment variable not set")
        return False
    
    conn = await asyncpg.connect(dsn=dsn)
    try:
        print("=" * 70)
        print("DB 검증: Phase 7d — _try_expired_fallback() 조건 확인")
        print("=" * 70)
        
        now = datetime.now(timezone.utc)
        kst_now = now.astimezone(timezone(timedelta(hours=9)))
        
        # =========================================================================
        # 1. reconcile_required 주문 조회 (broker_orders JOIN으로 broker_status 포함)
        # =========================================================================
        rows = await conn.fetch("""
            SELECT 
                o.order_request_id,
                o.side,
                o.status,
                o.status_reason_code,
                o.created_at,
                o.updated_at,
                o.requested_quantity,
                i.symbol,
                bo.broker_status
            FROM trading.order_requests o
            LEFT JOIN trading.instruments i ON i.instrument_id = o.instrument_id
            LEFT JOIN trading.broker_orders bo ON bo.order_request_id = o.order_request_id
            WHERE o.status = 'reconcile_required'
            ORDER BY o.created_at DESC
        """)
        
        print(f"\n{'='*70}")
        print(f"1. reconcile_required 주문: {len(rows)}건")
        print(f"{'ORDER_REQUEST_ID':<38} {'SIDE':<5} {'SYMBOL':<8} {'QTY':<8} {'BROKER_STATUS':<25} {'CREATED_AT':<30} {'AGE(min)':<10} {'FALLBACK_OK':<12}")
        print("-" * 140)
        
        fallback_ok_count = 0
        is_after_hours = 15 <= kst_now.hour < 18
        
        for r in rows:
            created = r['created_at']
            if created and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_minutes = (now - created).total_seconds() / 60 if created else 0
            
            grace_period_ok = age_minutes >= 30
            fallback_ok = grace_period_ok or is_after_hours
            
            if fallback_ok:
                fallback_ok_count += 1
            
            oid = str(r['order_request_id'])
            broker_st = r['broker_status'] or 'N/A'
            print(f"{oid:<38} {r['side']:<5} {r['symbol'] or 'N/A':<8} {str(r['requested_quantity']):<8} {str(broker_st):<25} {str(created):<30} {age_minutes:<10.1f} {'✅' if fallback_ok else '❌':<12}")
        
        print(f"\n   → Fallback 조건 충족 (age>=30min OR after-hours): {fallback_ok_count}/{len(rows)}건")
        print(f"   현재 KST: {kst_now}, After-hours: {is_after_hours}")
        
        # =========================================================================
        # 2. reconciliation_runs 상태 (trigger_type = 'requires_reconciliation')
        # =========================================================================
        runs = await conn.fetch("""
            SELECT 
                rr.reconciliation_run_id,
                rr.status,
                rr.trigger_type,
                rr.mismatch_count,
                rr.summary_json,
                rr.started_at,
                rr.completed_at,
                rr.created_at,
                (SELECT COUNT(*) FROM trading.reconciliation_order_links rol 
                 WHERE rol.reconciliation_run_id = rr.reconciliation_run_id) AS order_count
            FROM trading.reconciliation_runs rr
            WHERE rr.trigger_type = 'requires_reconciliation'
            ORDER BY rr.created_at DESC
        """)
        
        print(f"\n{'='*70}")
        print(f"2. reconciliation_runs (requires_reconciliation): {len(runs)}건")
        for r in runs:
            print(f"   ┌─ Run ID:       {r['reconciliation_run_id']}")
            print(f"   ├─ Status:       {r['status']}")
            print(f"   ├─ Trigger:      {r['trigger_type']}")
            print(f"   ├─ Mismatch cnt: {r['mismatch_count']}")
            print(f"   ├─ Summary:      {str(r['summary_json'])[:100] if r['summary_json'] else 'None'}")
            print(f"   ├─ Started:      {r['started_at']}")
            print(f"   ├─ Completed:    {r['completed_at']}")
            print(f"   ├─ Created:      {r['created_at']}")
            print(f"   └─ Order count:  {r['order_count']}")
            print()
        
        # =========================================================================
        # 3. reconciliation_order_links 상세
        # =========================================================================
        links = await conn.fetch("""
            SELECT 
                rol.reconciliation_run_id,
                rol.order_request_id,
                rol.mismatch_type,
                rol.details_json,
                o.status AS order_status,
                o.created_at,
                i.symbol
            FROM trading.reconciliation_order_links rol
            JOIN trading.order_requests o ON o.order_request_id = rol.order_request_id
            LEFT JOIN trading.instruments i ON i.instrument_id = o.instrument_id
            WHERE rol.reconciliation_run_id IN (
                SELECT reconciliation_run_id 
                FROM trading.reconciliation_runs 
                WHERE trigger_type = 'requires_reconciliation'
            )
            ORDER BY rol.reconciliation_run_id, o.created_at
        """)
        
        print(f"{'='*70}")
        print(f"3. reconciliation_order_links 상세: {len(links)}건")
        for r in links:
            rid = str(r['reconciliation_run_id'])[:8]
            oid = str(r['order_request_id'])[:8]
            print(f"   Run: {rid}... | Order: {oid}... | Mismatch: {r['mismatch_type']:<15} | Order status: {r['order_status']:<20} | Symbol: {r['symbol'] or 'N/A'}")
        
        # =========================================================================
        # 4. 5/27~5/29 전체 status 분포
        # =========================================================================
        status_dist = await conn.fetch("""
            SELECT 
                o.status,
                COALESCE(bo.broker_status, 'N/A') AS broker_status,
                COUNT(*) as cnt
            FROM trading.order_requests o
            LEFT JOIN trading.broker_orders bo ON bo.order_request_id = o.order_request_id
            WHERE o.created_at >= '2026-05-27 00:00:00+09'
              AND o.created_at < '2026-05-30 00:00:00+09'
            GROUP BY o.status, bo.broker_status
            ORDER BY COUNT(*) DESC
        """)
        
        print(f"\n{'='*70}")
        print(f"4. 5/27~5/29 전체 status 분포 (order_requests.status x broker_orders.broker_status):")
        for r in status_dist:
            print(f"   status={str(r['status']):<25} broker={str(r['broker_status']):<25} count={r['cnt']}")
        
        # =========================================================================
        # 5. _try_expired_fallback() 시뮬레이션
        # =========================================================================
        print(f"\n{'='*70}")
        print(f"5. _try_expired_fallback() 시뮬레이션")
        print(f"   현재 KST: {kst_now}")
        print(f"   After-hours (15:00~18:00 KST): {is_after_hours}")
        
        rec_rows = await conn.fetch("""
            SELECT 
                o.order_request_id,
                o.status,
                o.created_at,
                o.side,
                i.symbol
            FROM trading.order_requests o
            LEFT JOIN trading.instruments i ON i.instrument_id = o.instrument_id
            WHERE o.status = 'reconcile_required'
        """)
        
        eligible = 0
        for r in rec_rows:
            created = r['created_at']
            if created and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_minutes = (now - created).total_seconds() / 60 if created else 0
            
            if age_minutes >= 30 or is_after_hours:
                eligible += 1
                print(f"   ✅ {str(r['order_request_id'])[:8]}... | {r['side']} {r['symbol'] or 'N/A'} | age={age_minutes:.0f}min → EXPIRED fallback 적용 가능")
            else:
                print(f"   ❌ {str(r['order_request_id'])[:8]}... | {r['side']} {r['symbol'] or 'N/A'} | age={age_minutes:.0f}min → 조건 미달")
        
        print(f"\n   → EXPIRED fallback 적용 가능: {eligible}/{len(rec_rows)}건")
        
        # =========================================================================
        # 6. 비정상 expired 확인 (status=expired지만 broker_status=reconcile_required인 경우)
        # =========================================================================
        abnormal = await conn.fetch("""
            SELECT 
                o.order_request_id,
                o.status,
                o.status_reason_code,
                o.side,
                o.created_at,
                i.symbol,
                bo.broker_status
            FROM trading.order_requests o
            LEFT JOIN trading.instruments i ON i.instrument_id = o.instrument_id
            LEFT JOIN trading.broker_orders bo ON bo.order_request_id = o.order_request_id
            WHERE o.status = 'expired' AND bo.broker_status = 'reconcile_required'
        """)
        
        print(f"\n{'='*70}")
        print(f"6. 비정상 expired (status=expired, broker_status=reconcile_required): {len(abnormal)}건")
        for r in abnormal:
            created = r['created_at']
            if created and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            print(f"   {str(r['order_request_id'])[:8]}... | {r['side']} {r['symbol'] or 'N/A'} | created={created} | reason={r['status_reason_code'] or 'N/A'}")
        
        # =========================================================================
        # 7. 추가: order_state_events에서 reconcile_required 관련 이벤트 확인
        # =========================================================================
        events = await conn.fetch("""
            SELECT 
                ose.order_request_id,
                ose.previous_status,
                ose.new_status,
                ose.event_source,
                ose.event_timestamp,
                ose.reason_code
            FROM trading.order_state_events ose
            WHERE ose.order_request_id IN (
                SELECT order_request_id FROM trading.order_requests WHERE status = 'reconcile_required'
            )
            ORDER BY ose.event_timestamp DESC
            LIMIT 50
        """)
        
        print(f"\n{'='*70}")
        print(f"7. reconcile_required 주문의 상태 이벤트 (최대 50건): {len(events)}건")
        for r in events:
            print(f"   {str(r['order_request_id'])[:8]}... | {r['previous_status'] or 'N/A':<15} → {r['new_status']:<20} | source={str(r['event_source']):<15} | time={str(r['event_timestamp'])[:19]} | reason={r['reason_code'] or 'N/A'}")
        
        # =========================================================================
        # 8. broker_orders broker_status 분포 (reconcile_required 주문 중)
        # =========================================================================
        bo_dist = await conn.fetch("""
            SELECT 
                bo.broker_status,
                COUNT(*) as cnt
            FROM trading.order_requests o
            JOIN trading.broker_orders bo ON bo.order_request_id = o.order_request_id
            WHERE o.status = 'reconcile_required'
            GROUP BY bo.broker_status
            ORDER BY COUNT(*) DESC
        """)
        
        print(f"\n{'='*70}")
        print(f"8. reconcile_required 주문의 broker_status 분포:")
        for r in bo_dist:
            print(f"   broker_status={str(r['broker_status']):<25} count={r['cnt']}")
        
        print(f"\n{'='*70}")
        print("검증 완료")
        print(f"{'='*70}")
        
        return True
    finally:
        await conn.close()

if __name__ == "__main__":
    success = asyncio.run(verify_db_state())
    sys.exit(0 if success else 1)
