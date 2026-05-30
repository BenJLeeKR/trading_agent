#!/usr/bin/env python3
"""
tmp/apply_expired_fallback.py

Worker의 ``_try_expired_fallback()`` 로직을 직접 실행합니다.
KIS API 인증 실패(403)로 Worker가 broker adapter를 생성할 수 없는 경우,
DB를 통해 직접 EXPIRED 상태 전이를 수행합니다.

Flow
----
1. ``trigger_type='requires_reconciliation'`` reconciliation run 조회
2. Run에 연결된 order link 조회
3. 각 order의 age 확인 (grace period 30분) — 모두 30분 초과
4. ``update_status()`` 로 EXPIRED 전이 + ``reason_code='reconciliation_expired_fallback'``
5. Reconciliation run을 ``completed`` 상태로 마킹
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import asyncpg


DSN = (
    f"postgresql://{os.getenv('DATABASE_USER', 'trading')}"
    f":{os.getenv('DATABASE_PASSWORD', 'trading')}"
    f"@{os.getenv('DATABASE_HOST', 'localhost')}"
    f":{os.getenv('DATABASE_PORT', '5432')}"
    f"/{os.getenv('DATABASE_NAME', 'trading')}"
)

GRACE_PERIOD_MINUTES = 30
EXPIRED_STATUS = "expired"
FALLBACK_REASON_CODE = "reconciliation_expired_fallback"
RUN_COMPLETED_STATUS = "completed"


async def main() -> int:
    conn = await asyncpg.connect(DSN)
    try:
        now = datetime.now(timezone.utc)
        print(f"[{now.isoformat()}] Expired fallback script started")
        print(f"[DSN] {DSN.replace('trading:trading', 'trading:****')}")

        # ── 1. Find reconciliation run with order links ──
        run_row = await conn.fetchrow(
            """
            SELECT r.reconciliation_run_id, r.account_id, r.status, r.started_at,
                   COUNT(rol.order_request_id) AS link_count
            FROM trading.reconciliation_runs r
            JOIN trading.reconciliation_order_links rol
                ON rol.reconciliation_run_id = r.reconciliation_run_id
            WHERE r.trigger_type = 'requires_reconciliation'
            GROUP BY r.reconciliation_run_id
            ORDER BY r.started_at DESC
            LIMIT 1
            """
        )
        if run_row is None:
            print("[SKIP] No reconciliation run with order links found.")
            return 0

        run_id = run_row["reconciliation_run_id"]
        account_id = run_row["account_id"]
        run_status = run_row["status"]
        link_count = run_row["link_count"]
        print(f"[RUN] Found run: {run_id} (account={account_id}, status={run_status}, links={link_count})")

        # ── 2. Get order links with full status info ──
        link_rows = await conn.fetch(
            """
            SELECT rol.order_request_id, o.status, o.version, o.created_at,
                   o.status_reason_code
            FROM trading.reconciliation_order_links rol
            JOIN trading.order_requests o ON o.order_request_id = rol.order_request_id
            WHERE rol.reconciliation_run_id = $1
            ORDER BY o.created_at
            """,
            run_id,
        )

        if not link_rows:
            print(f"[SKIP] No order links found for run {run_id}")
            return 0

        print(f"[LINKS] Found {len(link_rows)} order(s) linked to run {run_id}")

        # ── 3. Process each order ──
        expired_count = 0
        skipped_count = 0
        failed_count = 0

        for row in link_rows:
            order_id = row["order_request_id"]
            current_status = row["status"]
            version = row["version"]
            created_at = row["created_at"]
            status_reason_code = row["status_reason_code"]

            # Age check
            age_minutes = (now - created_at).total_seconds() / 60 if created_at else 0

            print(
                f"  Order {order_id}: "
                f"status={current_status} "
                f"version={version} "
                f"age={age_minutes:.1f}min "
                f"status_reason_code={status_reason_code}"
            )

            if current_status != "reconcile_required":
                print(f"    → SKIP (status={current_status}, not reconcile_required)")
                skipped_count += 1
                continue

            if age_minutes < GRACE_PERIOD_MINUTES:
                print(
                    f"    → SKIP (age={age_minutes:.1f}min < grace={GRACE_PERIOD_MINUTES}min)"
                )
                skipped_count += 1
                continue

            # ── 4. Apply EXPIRED transition via version-checked UPDATE ──
            try:
                result = await conn.execute(
                    """
                    UPDATE trading.order_requests
                    SET status = $2,
                        status_reason_code = $3,
                        status_reason_message = $4,
                        version = version + 1,
                        updated_at = NOW()
                    WHERE order_request_id = $1
                      AND version = $5
                      AND status = 'reconcile_required'
                    """,
                    order_id,
                    EXPIRED_STATUS,
                    FALLBACK_REASON_CODE,
                    f"Expired fallback via reconciliation (age={age_minutes:.1f}min)",
                    version,
                )
                if result != "UPDATE 1":
                    current = await conn.fetchrow(
                        "SELECT status, version FROM trading.order_requests WHERE order_request_id = $1",
                        order_id,
                    )
                    print(
                        f"    → VERSION CONFLICT: expected version={version}, "
                        f"current version={current['version'] if current else 'N/A'}, "
                        f"status={current['status'] if current else 'N/A'}"
                    )
                    failed_count += 1
                else:
                    print(
                        f"    → EXPIRED ✓ (reason_code={FALLBACK_REASON_CODE}, "
                        f"version={version}→{version+1})"
                    )
                    expired_count += 1
            except Exception as exc:
                print(f"    → ERROR: {exc}")
                failed_count += 1

        # ── 5. Mark reconciliation run as completed ──
        summary = {
            "resolved_via": "expired_fallback_script",
            "expired_count": expired_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "total_orders": len(link_rows),
            "completed_at": now.isoformat(),
        }

        await conn.execute(
            """
            UPDATE trading.reconciliation_runs
            SET status = $2,
                mismatch_count = $3,
                summary_json = $4::jsonb,
                completed_at = NOW()
            WHERE reconciliation_run_id = $1
            """,
            run_id,
            RUN_COMPLETED_STATUS,
            expired_count,
            json.dumps(summary),
        )
        print(f"[RUN] Marked run {run_id} as {RUN_COMPLETED_STATUS}")

        # ── Summary ──
        print(f"\n=== Expired Fallback Summary ===")
        print(f"  Reconciliation run:      {run_id}")
        print(f"  Total orders linked:     {len(link_rows)}")
        print(f"  Expired transitions:     {expired_count}")
        print(f"  Skipped:                 {skipped_count}")
        print(f"  Failed:                  {failed_count}")
        print(f"  Run new status:          {RUN_COMPLETED_STATUS}")
        print(f"=================================")

        return 1 if failed_count > 0 else 0

    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
