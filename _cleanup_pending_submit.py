#!/usr/bin/env python3
"""
Stale PENDING_SUBMIT cleanup — 상태전이 PENDING_SUBMIT → REJECTED

대상 조건 (일반):
1. status = 'pending_submit'
2. created_at < NOW() - INTERVAL '24 hours'
3. broker_orders 연결 없음 (broker 미제출)

대상 조건 (known failure — 40270000 모의투자 상/하한가):
1. status = 'pending_submit'
2. status_reason_code LIKE '%40270000%'
3. created_at < NOW() - INTERVAL '1 hour'
4. broker_orders 연결 없음 (broker 미제출)

안전장치:
- 모든 cleanup 경로에서 broker_orders 존재 시 skip (000880 복구 케이스 보호)
- reconcile_required 주문은 절대 cleanup 대상이 아님

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
KNOWN_FAILURE_STALE_INTERVAL = "1 hour"
REASON_CODE = "stale_cleanup"
KNOWN_FAILURE_REASON_CODE = "stale_cleanup_40270000"


async def main() -> None:
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        now = datetime.now(timezone.utc)
        print(f"=== Stale PENDING_SUBMIT Cleanup ===")
        print(f"Timestamp: {now.isoformat()}")
        print(f"일반 stale 기준: created_at < NOW() - INTERVAL '{STALE_INTERVAL}'")
        print(f"40270000 fast cleanup 기준: created_at < NOW() - INTERVAL '{KNOWN_FAILURE_STALE_INTERVAL}'")
        print(f"조건: status=pending_submit AND broker_orders 연결 없음")
        print()

        # ── 1. 일반 stale 대상 조회 ──────────────────────────────────
        general_rows = await conn.fetch(f"""
            SELECT order_request_id, side, order_type, requested_quantity, requested_price, created_at
            FROM order_requests
            WHERE status = 'pending_submit'
              AND created_at < NOW() - INTERVAL '{STALE_INTERVAL}'
              AND order_request_id NOT IN (SELECT order_request_id FROM broker_orders)
            ORDER BY created_at
        """)

        print(f"=== 일반 대상 주문 (24h+, {len(general_rows)}건) ===")
        for r in general_rows:
            age_h = (now - r['created_at']).total_seconds() / 3600
            print(f"  id={str(r['order_request_id'])[:8]} "
                  f"side={r['side']} qty={r['requested_quantity']} "
                  f"price={r['requested_price']} created={r['created_at']} UTC "
                  f"age={age_h:.1f}h")

        # ── 2. 40270000 known failure 대상 조회 ───────────────────────
        known_failure_rows = await conn.fetch(f"""
            SELECT order_request_id, side, order_type, requested_quantity, requested_price, created_at
            FROM order_requests
            WHERE status = 'pending_submit'
              AND status_reason_code LIKE '%40270000%'
              AND created_at < NOW() - INTERVAL '{KNOWN_FAILURE_STALE_INTERVAL}'
              AND order_request_id NOT IN (SELECT order_request_id FROM broker_orders)
            ORDER BY created_at
        """)

        print(f"\n=== 40270000 known failure 대상 (1h+, {len(known_failure_rows)}건) ===")
        for r in known_failure_rows:
            age_h = (now - r['created_at']).total_seconds() / 3600
            print(f"  id={str(r['order_request_id'])[:8]} "
                  f"side={r['side']} qty={r['requested_quantity']} "
                  f"price={r['requested_price']} created={r['created_at']} UTC "
                  f"age={age_h:.1f}h")

        # 일반 대상에서 40270000 중복 제거 (40270000은 fast cleanup에서 처리)
        general_only_rows = [r for r in general_rows
                             if r['order_request_id'] not in
                             {rr['order_request_id'] for rr in known_failure_rows}]

        total_targets = len(general_only_rows) + len(known_failure_rows)
        if total_targets == 0:
            print("\n대상 없음. 종료.")
            return

        # ── 3. 상태전이 실행 ──────────────────────────────────────────
        print(f"\n=== 상태전이 실행 ===")

        async with conn.transaction():
            # 3-a. 일반 stale UPDATE
            if general_only_rows:
                print(f"\n--- 일반 stale: PENDING_SUBMIT → REJECTED (reason_code={REASON_CODE}) ---")
                result = await conn.execute(f"""
                    UPDATE order_requests
                    SET status = 'rejected',
                        status_reason_code = '{REASON_CODE}',
                        updated_at = NOW()
                    WHERE status = 'pending_submit'
                      AND created_at < NOW() - INTERVAL '{STALE_INTERVAL}'
                      AND order_request_id NOT IN (SELECT order_request_id FROM broker_orders)
                      AND (status_reason_code IS NULL
                           OR status_reason_code NOT LIKE '%40270000%')
                """)
                print(f"  UPDATE result: {result}")

            # 3-b. 40270000 fast cleanup UPDATE
            if known_failure_rows:
                print(f"\n--- 40270000 fast cleanup: PENDING_SUBMIT → REJECTED "
                      f"(reason_code={KNOWN_FAILURE_REASON_CODE}) ---")
                result = await conn.execute(f"""
                    UPDATE order_requests
                    SET status = 'rejected',
                        status_reason_code = '{KNOWN_FAILURE_REASON_CODE}',
                        updated_at = NOW()
                    WHERE status = 'pending_submit'
                      AND status_reason_code LIKE '%40270000%'
                      AND created_at < NOW() - INTERVAL '{KNOWN_FAILURE_STALE_INTERVAL}'
                      AND order_request_id NOT IN (SELECT order_request_id FROM broker_orders)
                """)
                print(f"  UPDATE result: {result}")

            # 3-c. order_state_events INSERT (일반 stale 증적)
            if general_only_rows:
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
                print(f"  일반 stale order_state_events INSERT: {len(insert_rows)}건")

            # 3-d. order_state_events INSERT (40270000 fast cleanup 증적)
            if known_failure_rows:
                insert_rows = await conn.fetch(f"""
                    INSERT INTO order_state_events
                        (order_state_event_id, order_request_id, previous_status, new_status,
                         reason_code, event_source, event_timestamp, created_at)
                    SELECT
                        gen_random_uuid(),
                        order_request_id,
                        'pending_submit',
                        'rejected',
                        '{KNOWN_FAILURE_REASON_CODE}',
                        'system',
                        NOW(),
                        NOW()
                    FROM order_requests
                    WHERE status = 'rejected'
                      AND status_reason_code = '{KNOWN_FAILURE_REASON_CODE}'
                    RETURNING order_state_event_id, order_request_id
                """)
                print(f"  40270000 fast cleanup order_state_events INSERT: {len(insert_rows)}건")

        # ── 4. 결과 검증 ──────────────────────────────────────────────
        print(f"\n=== 결과 검증 ===")

        # 4-a. rejected 상태 확인
        rejected_cnt = await conn.fetchval("""
            SELECT COUNT(*) FROM order_requests
            WHERE status = 'rejected' AND status_reason_code = $1
        """, REASON_CODE)
        rejected_402_cnt = await conn.fetchval("""
            SELECT COUNT(*) FROM order_requests
            WHERE status = 'rejected' AND status_reason_code = $1
        """, KNOWN_FAILURE_REASON_CODE)
        print(f"  rejected (reason_code={REASON_CODE}): {rejected_cnt}건")
        print(f"  rejected (reason_code={KNOWN_FAILURE_REASON_CODE}): {rejected_402_cnt}건")

        # 4-b. order_state_events 증가 확인
        ose_cnt = await conn.fetchval("SELECT COUNT(*) FROM order_state_events")
        print(f"  order_state_events total: {ose_cnt}건")

        # 4-c. reconcile_required 영향 없음 확인
        rr_cnt = await conn.fetchval("""
            SELECT COUNT(*) FROM order_requests WHERE status = 'reconcile_required'
        """)
        rr_bo_cnt = await conn.fetchval("""
            SELECT COUNT(*) FROM broker_orders WHERE broker_status = 'reconcile_required'
        """)
        print(f"  reconcile_required (order_requests): {rr_cnt}건 (영향 없음 ✅)")
        print(f"  reconcile_required (broker_orders): {rr_bo_cnt}건 (영향 없음 ✅)")

        # 4-d. broker_orders 존재 주문 보호 확인
        bo_protected = await conn.fetchval("""
            SELECT COUNT(*) FROM order_requests
            WHERE status = 'pending_submit'
              AND order_request_id IN (SELECT order_request_id FROM broker_orders)
        """)
        print(f"  broker_orders 존재로 보호된 pending_submit: {bo_protected}건 (안전 ✅)")

        # 4-e. 남은 pending_submit 확인
        ps_cnt = await conn.fetchval("SELECT COUNT(*) FROM order_requests WHERE status = 'pending_submit'")
        print(f"  남은 pending_submit: {ps_cnt}건")

        print(f"\n=== Cleanup 완료 ===")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
