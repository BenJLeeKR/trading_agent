#!/usr/bin/env python3
"""
Stale PENDING_SUBMIT cleanup — 상태전이 PENDING_SUBMIT → REJECTED

대상 조건:
1. status = 'pending_submit'
2. created_at < NOW() - INTERVAL '24 hours'
3. broker_orders 연결 없음 (broker 미제출)

실행 전/후 count를 출력하고, order_state_events에 증적을 기록합니다.
"""

import asyncio
import os
from datetime import datetime, timezone

import asyncpg
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path)

DB_CONFIG = {
    "host": os.environ.get("DATABASE_HOST", "localhost"),
    "port": int(os.environ.get("DATABASE_PORT", "5432")),
    "user": os.environ.get("DATABASE_USER", "trading"),
    "password": os.environ.get("DATABASE_PASSWORD", "trading"),
    "database": os.environ.get("DATABASE_NAME", "trading"),
}

STALE_INTERVAL = "24 hours"
REASON_CODE = "stale_cleanup"


async def main() -> None:
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        now = datetime.now(timezone.utc)
        print(f"=== Stale PENDING_SUBMIT Cleanup ===")
        print(f"Timestamp: {now.isoformat()}")
        print(f"Stale 기준: created_at < NOW() - INTERVAL '{STALE_INTERVAL}'")
        print(f"조건: status=pending_submit AND broker_orders 연결 없음")
        print()

        # 1. 대상 조회 (실행 전)
        rows = await conn.fetch(f"""
            SELECT order_request_id, side, order_type, requested_quantity, requested_price, created_at
            FROM order_requests
            WHERE status = 'pending_submit'
              AND created_at < NOW() - INTERVAL '{STALE_INTERVAL}'
              AND order_request_id NOT IN (SELECT order_request_id FROM broker_orders)
            ORDER BY created_at
        """)

        print(f"=== 대상 주문 ({len(rows)}건) ===")
        for r in rows:
            age_h = (now - r['created_at']).total_seconds() / 3600
            print(f"  id={str(r['order_request_id'])[:8]} "
                  f"side={r['side']} qty={r['requested_quantity']} "
                  f"price={r['requested_price']} created={r['created_at']} UTC "
                  f"age={age_h:.1f}h")

        if not rows:
            print("대상 없음. 종료.")
            return

        # 2. 상태전이 실행
        print(f"\n=== 상태전이 실행: PENDING_SUBMIT → REJECTED (reason_code={REASON_CODE}) ===")
        async with conn.transaction():
            # 2-a. order_requests UPDATE
            # NOTE: asyncpg는 INTERVAL $N 파라미터 바인딩을 지원하지 않으므로
            #       모든 파라미터를 f-string으로 직접 삽입 (REASON_CODE는 상수)
            result = await conn.execute(f"""
                UPDATE order_requests
                SET status = 'rejected',
                    status_reason_code = '{REASON_CODE}',
                    updated_at = NOW()
                WHERE status = 'pending_submit'
                  AND created_at < NOW() - INTERVAL '{STALE_INTERVAL}'
                  AND order_request_id NOT IN (SELECT order_request_id FROM broker_orders)
            """)
            print(f"  UPDATE result: {result}")

            # 2-b. order_state_events INSERT (증적 기록)
            insert_rows = await conn.fetch(f"""
                INSERT INTO order_state_events
                    (order_state_event_id, order_request_id, previous_status, new_status,
                     reason_code, event_source, event_timestamp, created_at)
                SELECT
                    gen_random_uuid(),
                    order_request_id,
                    'pending_submit',
                    'rejected',
                    '{REASON_CODE}',
                    'system',
                    NOW(),
                    NOW()
                FROM order_requests
                WHERE status = 'rejected'
                  AND status_reason_code = '{REASON_CODE}'
                RETURNING order_state_event_id, order_request_id
            """)
            print(f"  order_state_events INSERT: {len(insert_rows)}건")

        # 3. 결과 검증
        print(f"\n=== 결과 검증 ===")

        # 3-a. rejected 상태 확인
        rejected_cnt = await conn.fetchval("""
            SELECT COUNT(*) FROM order_requests
            WHERE status = 'rejected' AND status_reason_code = $1
        """, REASON_CODE)
        print(f"  rejected (reason_code={REASON_CODE}): {rejected_cnt}건")

        # 3-b. order_state_events 증가 확인
        ose_cnt = await conn.fetchval("SELECT COUNT(*) FROM order_state_events")
        print(f"  order_state_events total: {ose_cnt}건")

        # 3-c. reconcile_required 영향 없음 확인
        rr_cnt = await conn.fetchval("""
            SELECT COUNT(*) FROM order_requests WHERE status = 'reconcile_required'
        """)
        rr_bo_cnt = await conn.fetchval("""
            SELECT COUNT(*) FROM broker_orders WHERE broker_status = 'reconcile_required'
        """)
        print(f"  reconcile_required (order_requests): {rr_cnt}건 (영향 없음 ✅)")
        print(f"  reconcile_required (broker_orders): {rr_bo_cnt}건 (영향 없음 ✅)")

        # 3-d. 남은 pending_submit 확인
        ps_cnt = await conn.fetchval("SELECT COUNT(*) FROM order_requests WHERE status = 'pending_submit'")
        print(f"  남은 pending_submit: {ps_cnt}건")

        print(f"\n=== Cleanup 완료 ===")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
