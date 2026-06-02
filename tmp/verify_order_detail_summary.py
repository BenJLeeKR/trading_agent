"""
E2E 검증: GET /orders/{order_request_id} 응답의 submission_attempt_summary (실제 Postgres DB)

테스트 시나리오:
  a) Migration 0028 확인 (order_submission_attempts 테이블 존재)
  b) Postgres repos를 통해 client + strategy + account + instrument + order_request seed
  c) Postgres repos를 통해 3개의 submission attempts INSERT
     - attempt 1: accepted=true,  raw_code="ACC", broker_name="KOREA_INVESTMENT"
     - attempt 2: accepted=true,  raw_code="PEN", broker_name="KOREA_INVESTMENT"
     - attempt 3: accepted=false, raw_code="REJ", raw_message="Insufficient cash",
                   error_type="REJECTED"
  d) API 클라이언트로 GET /orders/{order_request_id} 호출
  e) 응답 검증 (submission_attempt_summary)
  f) 제출 시도가 없는 order에 대해 summary=None 검증
  g) 결과 출력 및 PASS/FAIL 판정
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone

from httpx import AsyncClient, ASGITransport

from agent_trading.api.app import create_app
from agent_trading.api.deps import get_repos
from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import (
    InstrumentEntity,
    OrderRequestEntity,
    OrderSubmissionAttemptEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
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
    print("E2E 검증: GET /orders/{order_request_id} submission_attempt_summary")
    print("=" * 72)

    # 1) Migration 0028 확인 (order_submission_attempts 테이블 존재) ----------
    print("\n[1/7] Migration 0028 확인 (order_submission_attempts 테이블)…")
    config = DatabaseConfig()
    pool = await create_pool(config)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'trading' AND table_name = 'order_submission_attempts'"
        )
    check(row is not None, "order_submission_attempts 테이블 존재")

    # 2) Postgres repos를 통해 seed 데이터 생성 (force_rollback=False) --------
    print("\n[2/7] Seed 데이터 생성 (client + strategy + account + instrument + order)…")
    async with TransactionManager() as tx:
        repos = build_postgres_repositories(tx)

        # Client 생성
        client_id = uuid.uuid4()
        from agent_trading.domain.entities import ClientEntity
        await repos.clients.add(ClientEntity(
            client_id=client_id,
            client_code="E2E-SUMMARY-CLIENT",
            name="E2E Summary Test Client",
            status="active",
            base_currency="KRW",
        ))

        # Strategy 생성
        strategy_id = uuid.uuid4()
        from agent_trading.domain.entities import StrategyEntity
        await repos.strategies.add(StrategyEntity(
            strategy_id=strategy_id,
            client_id=client_id,
            strategy_code="E2E-SUMMARY-STRAT",
            name="E2E Summary Test Strategy",
            asset_class="stock",
            status="active",
            description="E2E test strategy for order detail summary verification",
        ))

        # BrokerAccount 생성 (accounts FK 필요)
        broker_account_id = uuid.uuid4()
        from agent_trading.domain.entities import BrokerAccountEntity
        from agent_trading.domain.enums import Environment
        await repos.broker_accounts.add(BrokerAccountEntity(
            broker_account_id=broker_account_id,
            broker_name="KOREA_INVESTMENT",
            account_ref="E2E-SUMMARY-BA-REF",
            environment=Environment.PAPER,
            credential_ref="e2e-summary-cred",
            base_url=None,
            status="active",
            broker_account_code="E2E-SUMMARY-BA",
        ))

        # Account 생성
        account_id = uuid.uuid4()
        from agent_trading.domain.entities import AccountEntity
        await repos.accounts.add(AccountEntity(
            account_id=account_id,
            client_id=client_id,
            broker_account_id=broker_account_id,
            environment=Environment.PAPER,
            account_alias="E2E-SUMMARY-ACC",
            account_masked="****0000",
            status="active",
            risk_profile={},
            account_code="E2E-SUMMARY-001",
        ))

        # Instrument 생성
        instrument_id = uuid.uuid4()
        await repos.instruments.add(InstrumentEntity(
            instrument_id=instrument_id,
            symbol="E2ESUM",
            market_code="KRX",
            asset_class="stock",
            currency="KRW",
            name="E2E Summary Test Instrument",
            tick_size=None,
            lot_size=None,
            is_active=True,
            metadata={},
        ))

        # OrderRequest 생성 (with attempts)
        order_request_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        order1 = OrderRequestEntity(
            order_request_id=order_request_id,
            account_id=account_id,
            instrument_id=instrument_id,
            client_order_id="E2E-ORD-SUMMARY-001",
            idempotency_key="e2e-idem-summary-001",
            correlation_id="e2e-corr-summary-001",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            requested_quantity=10,
            status=OrderStatus.SUBMITTED,
            time_in_force=TimeInForce.DAY,
            created_at=now,
            updated_at=now,
            submitted_at=now,
            version=1,
        )
        await repos.orders.add(order1)
        print(f"  ✅ Order (with attempts): {order_request_id}")

        # OrderRequest 생성 (no attempts)
        order_no_attempts_id = uuid.uuid4()
        order2 = OrderRequestEntity(
            order_request_id=order_no_attempts_id,
            account_id=account_id,
            instrument_id=instrument_id,
            client_order_id="E2E-ORD-SUMMARY-NOATT",
            idempotency_key="e2e-idem-summary-noatt",
            correlation_id="e2e-corr-summary-noatt",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            requested_quantity=5,
            status=OrderStatus.PENDING_SUBMIT,
            time_in_force=TimeInForce.DAY,
            created_at=now,
            updated_at=now,
            submitted_at=None,
            version=1,
        )
        await repos.orders.add(order2)
        print(f"  ✅ Order (no attempts): {order_no_attempts_id}")

        # 3) Submission attempts INSERT ------------------------------------------
        print("\n[3/7] Submission attempts INSERT…")

        attempt1 = OrderSubmissionAttemptEntity(
            attempt_id=uuid.uuid4(),
            order_request_id=order_request_id,
            attempt_number=1,
            submitted_at=now,
            broker_name="KOREA_INVESTMENT",
            accepted=True,
            broker_native_order_id="BRK-E2E-001",
            broker_status="confirmed",
            raw_code="ACC",
            raw_message="Accepted",
            error_type=None,
            retryable=None,
            http_status=200,
            duration_ms=100,
            created_at=now,
        )
        await repos.order_submission_attempts.add(attempt1)
        print(f"  ✅ attempt 1: attempt_number=1, accepted=True, raw_code=ACC")

        attempt2 = OrderSubmissionAttemptEntity(
            attempt_id=uuid.uuid4(),
            order_request_id=order_request_id,
            attempt_number=2,
            submitted_at=now,
            broker_name="KOREA_INVESTMENT",
            accepted=True,
            broker_native_order_id="BRK-E2E-002",
            broker_status="pending",
            raw_code="PEN",
            raw_message="Pending",
            error_type=None,
            retryable=True,
            http_status=200,
            duration_ms=200,
            created_at=now,
        )
        await repos.order_submission_attempts.add(attempt2)
        print(f"  ✅ attempt 2: attempt_number=2, accepted=True, raw_code=PEN")

        attempt3 = OrderSubmissionAttemptEntity(
            attempt_id=uuid.uuid4(),
            order_request_id=order_request_id,
            attempt_number=3,
            submitted_at=now,
            broker_name="KOREA_INVESTMENT",
            accepted=False,
            broker_native_order_id=None,
            broker_status="rejected",
            raw_code="REJ",
            raw_message="Insufficient cash",
            error_type="REJECTED",
            retryable=False,
            http_status=400,
            duration_ms=50,
            created_at=now,
        )
        await repos.order_submission_attempts.add(attempt3)
        print(f"  ✅ attempt 3: attempt_number=3, accepted=False, raw_code=REJ")

        # 4) DB 레벨 검증 --------------------------------------------------------
        print("\n[4/7] DB 레벨 검증 (repository.list_by_order_request)…")
        attempts = await repos.order_submission_attempts.list_by_order_request(
            order_request_id
        )
        check(len(attempts) == 3, f"올바른 order_request_id → 3개 attempt 반환 (actual={len(attempts)})")
        check(
            attempts[0].attempt_number == 1
            and attempts[1].attempt_number == 2
            and attempts[2].attempt_number == 3,
            f"attempt_number 순서 정렬: {[a.attempt_number for a in attempts]}",
        )

        # 5) API 레벨 검증 — GET /orders/{id} (with attempts) --------------------
        print("\n[5/7] API 레벨 검증 — GET /orders/{order_request_id} (with attempts)…")

        from agent_trading.api.security import configure_security
        configure_security(token="test-token", role="viewer")

        app = create_app(auth_token="test-token")

        async def _override():
            yield repos

        app.dependency_overrides[get_repos] = _override

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # (a) GET /orders/{order_request_id} with 3 attempts
            resp = await client.get(
                f"/orders/{order_request_id}",
                headers={"Authorization": "Bearer test-token"},
            )
            check(resp.status_code == 200, f"HTTP 200 (actual={resp.status_code})")
            data = resp.json()

            # submission_attempt_summary 필드 존재
            summary = data.get("submission_attempt_summary")
            check(summary is not None, "submission_attempt_summary 필드 존재")

            # attempt_count == 3
            check(
                summary["attempt_count"] == 3,
                f"attempt_count == 3 (actual={summary.get('attempt_count')})",
            )

            # latest_accepted == false (마지막 시도 = attempt 3)
            check(
                summary["latest_accepted"] is False,
                f"latest_accepted == false (actual={summary.get('latest_accepted')})",
            )

            # latest_raw_code == "REJ"
            check(
                summary["latest_raw_code"] == "REJ",
                f"latest_raw_code == REJ (actual={summary.get('latest_raw_code')})",
            )

            # latest_raw_message == "Insufficient cash"
            check(
                summary["latest_raw_message"] == "Insufficient cash",
                f"latest_raw_message == 'Insufficient cash' (actual={summary.get('latest_raw_message')})",
            )

            # latest_error_type == "REJECTED"
            check(
                summary["latest_error_type"] == "REJECTED",
                f"latest_error_type == REJECTED (actual={summary.get('latest_error_type')})",
            )

            # last_submitted_at이 None이 아님
            check(
                summary["last_submitted_at"] is not None,
                f"last_submitted_at is not None (actual={summary.get('last_submitted_at')})",
            )

        # 6) API 레벨 검증 — GET /orders/{id} (no attempts) --------------------
        print("\n[6/7] API 레벨 검증 — GET /orders/{order_request_id} (no attempts)…")

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp2 = await client.get(
                f"/orders/{order_no_attempts_id}",
                headers={"Authorization": "Bearer test-token"},
            )
            check(resp2.status_code == 200, f"[no attempts] HTTP 200 (actual={resp2.status_code})")
            data2 = resp2.json()
            summary2 = data2.get("submission_attempt_summary")
            check(
                summary2 is None,
                f"[no attempts] submission_attempt_summary is None (actual={summary2})",
            )

        app.dependency_overrides.clear()

    # Transaction 종료 시 자동 rollback
    print("\n[7/7] 트랜잭션 rollback (테스트 데이터 정리)")

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
        print("✅ 전체 E2E 검증 완료 — 주문 상세 + submission attempts 요약 Postgres 정상 동작 확인")
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
