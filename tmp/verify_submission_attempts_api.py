"""
E2E 검증: GET /orders/{order_request_id}/submission-attempts (실제 Postgres DB)

1. Migration 0028 실행 (order_submission_attempts 테이블 생성)
2. Postgres repository를 통해 테스트 데이터 INSERT (accepted=true 2개 + accepted=false 1개)
3. FastAPI TestClient (httpx.AsyncClient)로 API 호출
4. 응답 검증
   - 올바른 order_request_id → 3개 attempt 반환
   - 잘못된 order_request_id → 빈 리스트
   - attempt_number 순서 정렬
   - accepted 매핑 정확성
5. 결과 출력 및 성공/실패 판정
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from httpx import AsyncClient, ASGITransport

from agent_trading.api.app import create_app
from agent_trading.api.deps import get_repos
from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.migrations.run import run_migration
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import OrderSubmissionAttemptEntity
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 검증 헬퍼
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def check(condition: bool, msg: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  ✅ PASS: {msg}")
    else:
        _FAIL += 1
        print(f"  ❌ FAIL: {msg}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    global _PASS, _FAIL
    _PASS = 0
    _FAIL = 0

    print("=" * 72)
    print("E2E 검증: GET /orders/{order_request_id}/submission-attempts")
    print("=" * 72)

    # 1) Migration 0028 실행 -------------------------------------------------
    print("\n[1/4] Migration 0028 실행…")
    migration_path = (
        Path(__file__).resolve().parent.parent
        / "db"
        / "migrations"
        / "0028_add_order_submission_attempts.sql"
    )
    if not migration_path.exists():
        print(f"  ❌ Migration file not found: {migration_path}")
        return 1

    config = DatabaseConfig()
    await run_migration(str(migration_path), config=config)
    print("  ✅ Migration 0028 applied (or already exists)")

    # 2) Postgres connection pool 초기화 --------------------------------------
    pool = await create_pool(config)
    print(f"  ✅ Connection pool ready (min={config.min_size}, max={config.max_size})")

    # 3) 트랜잭션 내에서 데이터 INSERT + API 호출 ----------------------------
    print("\n[2/4] 테스트 데이터 INSERT…")
    order_request_id = uuid.uuid4()
    wrong_order_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # accepted=true 인 2개 attempt
    attempt_1 = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=order_request_id,
        attempt_number=1,
        submitted_at=now,
        broker_name="KOREA_INVESTMENT",
        accepted=True,
        broker_native_order_id="BRK-ACC-001",
        broker_status="confirmed",
        raw_code="ACC",
        raw_message="Accepted – first attempt",
        error_type=None,
        retryable=None,
        http_status=200,
        request_payload_uri=None,
        response_payload_uri=None,
        duration_ms=120,
        created_at=now,
    )
    attempt_2 = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=order_request_id,
        attempt_number=2,
        submitted_at=now,
        broker_name="KOREA_INVESTMENT",
        accepted=True,
        broker_native_order_id="BRK-ACC-002",
        broker_status="confirmed",
        raw_code="ACC",
        raw_message="Accepted – second attempt",
        error_type=None,
        retryable=None,
        http_status=200,
        request_payload_uri=None,
        response_payload_uri=None,
        duration_ms=95,
        created_at=now,
    )
    # accepted=false 인 1개 attempt
    attempt_3 = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=order_request_id,
        attempt_number=3,
        submitted_at=now,
        broker_name="KOREA_INVESTMENT",
        accepted=False,
        broker_native_order_id=None,
        broker_status="rejected",
        raw_code="REJ",
        raw_message="Order rejected by broker – insufficient liquidity",
        error_type="BROKER_REJECTION",
        retryable=False,
        http_status=400,
        request_payload_uri=None,
        response_payload_uri=None,
        duration_ms=45,
        created_at=now,
    )

    # 트랜잭션 열기 (force_rollback=True — 테스트 종료 후 rollback)
    async with TransactionManager(force_rollback=True) as tx:
        # Postgres repository container 생성
        repos = build_postgres_repositories(tx)

        # FK 체인 모두 채우기: instruments → clients → broker_accounts → accounts → order_requests
        instr = await tx.connection.fetchrow(
            "INSERT INTO trading.instruments "
            "(symbol, market_code, asset_class, currency, name) "
            "VALUES ('TEST', 'KRX', 'stock', 'KRW', 'Test Instrument E2E') "
            "RETURNING instrument_id"
        )
        instrument_id = instr["instrument_id"]

        cli = await tx.connection.fetchrow(
            "INSERT INTO trading.clients "
            "(client_code, name, status) "
            "VALUES ('E2E-TEST-CLIENT', 'E2E Test Client', 'active') "
            "RETURNING client_id"
        )
        client_id = cli["client_id"]

        ba = await tx.connection.fetchrow(
            "INSERT INTO trading.broker_accounts "
            "(broker_name, account_ref, environment, credential_ref, status) "
            "VALUES ('KOREA_INVESTMENT', 'E2E-ACC-REF', 'paper', 'e2e-cred', 'active') "
            "RETURNING broker_account_id"
        )
        broker_account_id = ba["broker_account_id"]

        acc = await tx.connection.fetchrow(
            "INSERT INTO trading.accounts "
            "(client_id, broker_account_id, environment, account_alias, "
            " account_masked, status) "
            "VALUES ($1, $2, 'paper', 'E2E-Test-Account', '****0000', 'active') "
            "RETURNING account_id",
            client_id,
            broker_account_id,
        )
        account_id = acc["account_id"]

        await tx.connection.execute(
            "INSERT INTO trading.order_requests "
            "(order_request_id, account_id, instrument_id, client_order_id, "
            " idempotency_key, correlation_id, side, order_type, "
            " requested_quantity, status) "
            "VALUES ($1, $2, $3, 'E2E-ORD-001', 'e2e-idem-001', "
            " 'e2e-corr-001', 'buy', 'limit', 100, 'submitted')",
            order_request_id,
            account_id,
            instrument_id,
        )

        # 데이터 INSERT (FK 제약 조건이 충족됨)
        await repos.order_submission_attempts.add(attempt_1)
        await repos.order_submission_attempts.add(attempt_2)
        await repos.order_submission_attempts.add(attempt_3)
        print("  ✅ 3개 attempt INSERT 완료 (FK 체인 포함)")

        # --- DB 레벨 검증 (repository 직접 호출) ---
        print("\n[3/4] DB 레벨 검증 (repository.list_by_order_request)…")
        attempts = await repos.order_submission_attempts.list_by_order_request(
            order_request_id
        )
        check(len(attempts) == 3, f"올바른 order_request_id → 3개 반환 (actual={len(attempts)})")

        check(
            attempts[0].attempt_number == 1
            and attempts[1].attempt_number == 2
            and attempts[2].attempt_number == 3,
            f"attempt_number 순서 정렬: {[a.attempt_number for a in attempts]}",
        )

        check(
            attempts[0].accepted is True
            and attempts[1].accepted is True
            and attempts[2].accepted is False,
            f"accepted 매핑: {[a.accepted for a in attempts]}",
        )

        # 잘못된 order_request_id → 빈 리스트
        wrong_attempts = await repos.order_submission_attempts.list_by_order_request(
            wrong_order_id
        )
        check(
            len(wrong_attempts) == 0,
            f"잘못된 order_request_id → 빈 리스트 (actual={len(wrong_attempts)})",
        )

        # --- API 레벨 검증 (httpx.AsyncClient) ---
        print("\n[4/4] API 레벨 검증 (GET /orders/…/submission-attempts)…")

        # configure_security 직접 호출 (ASGITransport는 lifespan을 실행하지 않음)
        from agent_trading.api.security import configure_security
        configure_security(token="test-token", role="viewer")

        app = create_app(auth_token="test-token")

        # get_repos dependency → Postgres repos (async generator, get_repos와 동일한 시그니처)
        async def _override():
            yield repos

        app.dependency_overrides[get_repos] = _override

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # (a) 올바른 order_request_id → 3개 attempt
            resp = await client.get(
                f"/orders/{order_request_id}/submission-attempts",
                headers={"Authorization": "Bearer test-token"},
            )
            check(
                resp.status_code == 200,
                f"HTTP 200 (actual={resp.status_code})",
            )
            data = resp.json()
            check(
                len(data) == 3,
                f"올바른 order_request_id → 3개 attempt (actual={len(data)})",
            )

            # attempt_number 순서 정렬
            numbers = [item["attempt_number"] for item in data]
            check(
                numbers == [1, 2, 3],
                f"attempt_number 순서 정렬: {numbers}",
            )

            # accepted 매핑
            accepted_vals = [item["accepted"] for item in data]
            check(
                accepted_vals == [True, True, False],
                f"accepted 매핑: {accepted_vals}",
            )

            # broker_name, broker_native_order_id 등 필드 확인
            check(
                data[0]["broker_name"] == "KOREA_INVESTMENT",
                f"broker_name 필드: {data[0].get('broker_name')}",
            )
            check(
                data[0]["broker_native_order_id"] == "BRK-ACC-001",
                f"broker_native_order_id 필드: {data[0].get('broker_native_order_id')}",
            )
            check(
                data[2]["raw_code"] == "REJ",
                f"raw_code 필드 (rejected): {data[2].get('raw_code')}",
            )
            check(
                data[2]["error_type"] == "BROKER_REJECTION",
                f"error_type 필드: {data[2].get('error_type')}",
            )

            # (b) 잘못된 order_request_id → 빈 리스트
            resp2 = await client.get(
                f"/orders/{wrong_order_id}/submission-attempts",
                headers={"Authorization": "Bearer test-token"},
            )
            check(
                resp2.status_code == 200,
                f"[wrong_id] HTTP 200 (actual={resp2.status_code})",
            )
            data2 = resp2.json()
            check(
                data2 == [],
                f"[wrong_id] 빈 리스트 (actual={data2})",
            )

            # (c) 유효하지 않은 UUID → 422
            resp3 = await client.get(
                "/orders/not-a-uuid/submission-attempts",
                headers={"Authorization": "Bearer test-token"},
            )
            check(
                resp3.status_code == 422,
                f"[invalid UUID] HTTP 422 (actual={resp3.status_code})",
            )

        app.dependency_overrides.clear()

    # 트랜잭션은 force_rollback=True 이므로 종료 시 rollback
    print("  ✅ 트랜잭션 rollback (테스트 데이터 정리)")

    # Pool 정리
    await close_pool()

    # -----------------------------------------------------------------------
    # 최종 결과
    # -----------------------------------------------------------------------
    print()
    print("=" * 72)
    total = _PASS + _FAIL
    print(f"검증 완료: {_PASS}/{total} PASS, {_FAIL}/{total} FAIL")
    print("=" * 72)

    if _FAIL == 0:
        print("✅ 전체 E2E 검증 완료")
        return 0
    else:
        print("❌ 검증 실패, 재작업 필요")
        return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sys.exit(asyncio.run(main()))
