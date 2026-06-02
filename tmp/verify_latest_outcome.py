"""
E2E 검증: ``GET /orders/{order_request_id}`` 응답의 ``latest_outcome`` derived field
(실제 Postgres DB, Phase 8 Subtask 5)

시나리오:
  A. accepted  경로 — accepted=True,  error_type=None          → latest_outcome == "accepted"
  B. rejected  경로 — accepted=False, error_type=None, raw_code="REJ"  → latest_outcome == "rejected"
  C. exception 경로 — accepted=False, error_type="TIMEOUT"     → latest_outcome == "exception"
  D. 제출 시도 없음  — attempt 없음                             → submission_attempt_summary == None
  E. 여러 attempt 중 마지막 기준 — [accepted, timeout, rejected] → latest_outcome == "rejected"

각 시나리오는 별도의 ``order_request_id``로 생성되며,
모든 데이터는 트랜잭션 rollback으로 정리됩니다.
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
from agent_trading.api.security import configure_security
from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import (
    OrderRequestEntity,
    OrderSubmissionAttemptEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 전역 PASS / FAIL 카운터
# ---------------------------------------------------------------------------
_PASS = 0
_FAIL = 0


def _check(condition: bool, msg: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  ✅ PASS: {msg}")
    else:
        _FAIL += 1
        print(f"  ❌ FAIL: {msg}")


# ---------------------------------------------------------------------------
# 시나리오별 헬퍼: FK 체인 생성 + order 생성
# ---------------------------------------------------------------------------


async def _ensure_fk_chain(tx, label: str) -> dict:
    """instruments / clients / broker_accounts / accounts 를 한 번씩만 생성.

    ``label`` 은 PK 충돌을 피하기 위한 식별자 접미사.
    """
    instr = await tx.connection.fetchrow(
        "INSERT INTO trading.instruments "
        "(symbol, market_code, asset_class, currency, name) "
        "VALUES ($1, 'KRX', 'stock', 'KRW', $2) "
        "RETURNING instrument_id",
        f"LO-{label}",
        f"Latest Outcome Test {label}",
    )
    instrument_id = instr["instrument_id"]

    cli = await tx.connection.fetchrow(
        "INSERT INTO trading.clients "
        "(client_code, name, status) "
        "VALUES ($1, $2, 'active') "
        "RETURNING client_id",
        f"LO-CLIENT-{label}",
        f"Latest Outcome Client {label}",
    )
    client_id = cli["client_id"]

    ba = await tx.connection.fetchrow(
        "INSERT INTO trading.broker_accounts "
        "(broker_name, account_ref, environment, credential_ref, status) "
        "VALUES ('KOREA_INVESTMENT', $1, 'paper', $2, 'active') "
        "RETURNING broker_account_id",
        f"LO-ACC-REF-{label}",
        f"lo-cred-{label}",
    )
    broker_account_id = ba["broker_account_id"]

    acc = await tx.connection.fetchrow(
        "INSERT INTO trading.accounts "
        "(client_id, broker_account_id, environment, account_alias, "
        " account_masked, status) "
        "VALUES ($1, $2, 'paper', $3, '****0000', 'active') "
        "RETURNING account_id",
        client_id,
        broker_account_id,
        f"LO-Account-{label}",
    )
    account_id = acc["account_id"]

    return {
        "instrument_id": instrument_id,
        "account_id": account_id,
    }


async def _create_order(
    repos, order_request_id: uuid.UUID, fk: dict
) -> None:
    """order_requests INSERT."""
    now = datetime.now(timezone.utc)
    order = OrderRequestEntity(
        order_request_id=order_request_id,
        account_id=fk["account_id"],
        instrument_id=fk["instrument_id"],
        client_order_id=f"LO-ORD-{order_request_id}",
        idempotency_key=f"lo-idem-{order_request_id}",
        correlation_id=f"lo-corr-{order_request_id}",
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
    await repos.orders.add(order)


async def _create_attempt(
    repos,
    order_request_id: uuid.UUID,
    attempt_number: int,
    *,
    accepted: bool,
    error_type: str | None = None,
    raw_code: str | None = None,
    raw_message: str | None = None,
) -> None:
    """order_submission_attempts INSERT."""
    now = datetime.now(timezone.utc)
    attempt = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=order_request_id,
        attempt_number=attempt_number,
        submitted_at=now,
        broker_name="KOREA_INVESTMENT",
        accepted=accepted,
        broker_native_order_id="BRK-LO-001" if accepted else None,
        raw_code=raw_code,
        raw_message=raw_message or f"Attempt {attempt_number}",
        error_type=error_type,
        retryable=(error_type is not None),
        http_status=200 if accepted else (500 if error_type else 400),
        duration_ms=100 * attempt_number,
        created_at=now,
    )
    await repos.order_submission_attempts.add(attempt)


# ---------------------------------------------------------------------------
# 시나리오 실행
# ---------------------------------------------------------------------------


async def _scenario_a(repos, tx) -> bool:
    """Scenario A: accepted 경로 → latest_outcome == 'accepted'."""
    label = "SCN-A"
    oid = uuid.uuid4()
    fk = await _ensure_fk_chain(tx, label)
    await _create_order(repos, oid, fk)
    await _create_attempt(repos, oid, 1, accepted=True, error_type=None,
                         raw_code="ACC", raw_message="Accepted")

    app = create_app(auth_token="test-token")
    configure_security(token="test-token", role="viewer")

    async def _override():
        yield repos

    app.dependency_overrides[get_repos] = _override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/orders/{oid}",
            headers={"Authorization": "Bearer test-token"},
        )
    app.dependency_overrides.clear()

    _check(resp.status_code == 200, f"[A] HTTP 200 (actual={resp.status_code})")
    if resp.status_code != 200:
        return False

    data = resp.json()
    summary = data.get("submission_attempt_summary")
    _check(summary is not None, "[A] submission_attempt_summary 존재")
    if summary is None:
        return False

    _check(summary["latest_outcome"] == "accepted",
           f"[A] latest_outcome == 'accepted' (actual={summary.get('latest_outcome')!r})")
    _check(summary["attempt_count"] == 1, "[A] attempt_count == 1")
    _check(summary["latest_accepted"] is True, "[A] latest_accepted == True")
    _check(summary["latest_raw_code"] == "ACC", "[A] latest_raw_code == 'ACC'")
    return True


async def _scenario_b(repos, tx) -> bool:
    """Scenario B: rejected 경로 → latest_outcome == 'rejected'."""
    label = "SCN-B"
    oid = uuid.uuid4()
    fk = await _ensure_fk_chain(tx, label)
    await _create_order(repos, oid, fk)
    await _create_attempt(repos, oid, 1, accepted=False, error_type=None,
                         raw_code="REJ", raw_message="Rejected by broker")

    app = create_app(auth_token="test-token")
    configure_security(token="test-token", role="viewer")

    async def _override():
        yield repos

    app.dependency_overrides[get_repos] = _override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/orders/{oid}",
            headers={"Authorization": "Bearer test-token"},
        )
    app.dependency_overrides.clear()

    _check(resp.status_code == 200, f"[B] HTTP 200 (actual={resp.status_code})")
    if resp.status_code != 200:
        return False

    data = resp.json()
    summary = data.get("submission_attempt_summary")
    _check(summary is not None, "[B] submission_attempt_summary 존재")
    if summary is None:
        return False

    _check(summary["latest_outcome"] == "rejected",
           f"[B] latest_outcome == 'rejected' (actual={summary.get('latest_outcome')!r})")
    _check(summary["attempt_count"] == 1, "[B] attempt_count == 1")
    _check(summary["latest_accepted"] is False, "[B] latest_accepted == False")
    _check(summary["latest_raw_code"] == "REJ", "[B] latest_raw_code == 'REJ'")
    _check(summary["latest_error_type"] is None, "[B] latest_error_type == None")
    return True


async def _scenario_c(repos, tx) -> bool:
    """Scenario C: exception 경로 → latest_outcome == 'exception'."""
    label = "SCN-C"
    oid = uuid.uuid4()
    fk = await _ensure_fk_chain(tx, label)
    await _create_order(repos, oid, fk)
    await _create_attempt(repos, oid, 1, accepted=False, error_type="TIMEOUT",
                         raw_code=None, raw_message="Broker timeout")

    app = create_app(auth_token="test-token")
    configure_security(token="test-token", role="viewer")

    async def _override():
        yield repos

    app.dependency_overrides[get_repos] = _override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/orders/{oid}",
            headers={"Authorization": "Bearer test-token"},
        )
    app.dependency_overrides.clear()

    _check(resp.status_code == 200, f"[C] HTTP 200 (actual={resp.status_code})")
    if resp.status_code != 200:
        return False

    data = resp.json()
    summary = data.get("submission_attempt_summary")
    _check(summary is not None, "[C] submission_attempt_summary 존재")
    if summary is None:
        return False

    _check(summary["latest_outcome"] == "exception",
           f"[C] latest_outcome == 'exception' (actual={summary.get('latest_outcome')!r})")
    _check(summary["attempt_count"] == 1, "[C] attempt_count == 1")
    _check(summary["latest_accepted"] is False, "[C] latest_accepted == False")
    _check(summary["latest_error_type"] == "TIMEOUT",
           f"[C] latest_error_type == 'TIMEOUT' (actual={summary.get('latest_error_type')!r})")
    _check(summary["latest_raw_code"] is None, "[C] latest_raw_code == None")
    return True


async def _scenario_d(repos, tx) -> bool:
    """Scenario D: 제출 시도 없음 → submission_attempt_summary == None."""
    label = "SCN-D"
    oid = uuid.uuid4()
    fk = await _ensure_fk_chain(tx, label)
    await _create_order(repos, oid, fk)
    # No attempts created

    app = create_app(auth_token="test-token")
    configure_security(token="test-token", role="viewer")

    async def _override():
        yield repos

    app.dependency_overrides[get_repos] = _override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/orders/{oid}",
            headers={"Authorization": "Bearer test-token"},
        )
    app.dependency_overrides.clear()

    _check(resp.status_code == 200, f"[D] HTTP 200 (actual={resp.status_code})")
    if resp.status_code != 200:
        return False

    data = resp.json()
    summary = data.get("submission_attempt_summary")
    _check(summary is None,
           f"[D] submission_attempt_summary is None (actual={summary})")
    return True


async def _scenario_e(repos, tx) -> bool:
    """Scenario E: 여러 attempt 중 마지막 기준
       - attempt 1: accepted=True, error_type=None
       - attempt 2: accepted=False, error_type="TIMEOUT"
       - attempt 3: accepted=False, error_type=None, raw_code="REJ"
       → latest_outcome == "rejected" (마지막 attempt 기준)
    """
    label = "SCN-E"
    oid = uuid.uuid4()
    fk = await _ensure_fk_chain(tx, label)
    await _create_order(repos, oid, fk)

    # attempt 1: accepted (성공)
    await _create_attempt(repos, oid, 1, accepted=True, error_type=None,
                         raw_code="ACC", raw_message="Accepted")
    # attempt 2: exception (타임아웃)
    await _create_attempt(repos, oid, 2, accepted=False, error_type="TIMEOUT",
                         raw_code=None, raw_message="Timeout")
    # attempt 3: rejected (거절)
    await _create_attempt(repos, oid, 3, accepted=False, error_type=None,
                         raw_code="REJ", raw_message="Rejected")

    app = create_app(auth_token="test-token")
    configure_security(token="test-token", role="viewer")

    async def _override():
        yield repos

    app.dependency_overrides[get_repos] = _override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/orders/{oid}",
            headers={"Authorization": "Bearer test-token"},
        )
    app.dependency_overrides.clear()

    _check(resp.status_code == 200, f"[E] HTTP 200 (actual={resp.status_code})")
    if resp.status_code != 200:
        return False

    data = resp.json()
    summary = data.get("submission_attempt_summary")
    _check(summary is not None, "[E] submission_attempt_summary 존재")
    if summary is None:
        return False

    _check(summary["latest_outcome"] == "rejected",
           f"[E] latest_outcome == 'rejected' (actual={summary.get('latest_outcome')!r})")
    _check(summary["attempt_count"] == 3,
           f"[E] attempt_count == 3 (actual={summary.get('attempt_count')})")
    _check(summary["latest_accepted"] is False, "[E] latest_accepted == False")
    _check(summary["latest_raw_code"] == "REJ",
           f"[E] latest_raw_code == 'REJ' (actual={summary.get('latest_raw_code')!r})")
    _check(summary["latest_error_type"] is None, "[E] latest_error_type == None")

    # 추가 검증: attempt 2의 error_type(TIMEOUT)이 아닌 attempt 3의 값이 반영
    _check(summary["latest_raw_message"] == "Rejected",
           f"[E] latest_raw_message == 'Rejected' (actual={summary.get('latest_raw_message')!r})")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    global _PASS, _FAIL
    _PASS = 0
    _FAIL = 0

    print("=" * 72)
    print("Phase 8 Subtask 5 — latest_outcome E2E 검증 (Postgres)")
    print("=" * 72)

    # ------------------------------------------------------------------
    # 1) Postgres connection pool 초기화
    # ------------------------------------------------------------------
    config = DatabaseConfig()
    await create_pool(config)
    print(f"\n[Setup] Connection pool ready (min={config.min_size}, max={config.max_size})")

    # ------------------------------------------------------------------
    # 2) Postgres transaction (force_rollback=True → 종료 시 rollback)
    # ------------------------------------------------------------------
    print("\n[Setup] Postgres transaction 시작 (force_rollback)…")
    async with TransactionManager(force_rollback=True) as tx:
        repos = build_postgres_repositories(tx)

        # Scenario A
        print("\n── Scenario A: accepted 경로 ──────────────────────────")
        await _scenario_a(repos, tx)

        # Scenario B
        print("\n── Scenario B: rejected 경로 ──────────────────────────")
        await _scenario_b(repos, tx)

        # Scenario C
        print("\n── Scenario C: exception 경로 ─────────────────────────")
        await _scenario_c(repos, tx)

        # Scenario D
        print("\n── Scenario D: 제출 시도 없음 ─────────────────────────")
        await _scenario_d(repos, tx)

        # Scenario E
        print("\n── Scenario E: 여러 attempt 중 마지막 기준 ────────────")
        await _scenario_e(repos, tx)

    print("\n  ✅ 트랜잭션 rollback (테스트 데이터 정리)")

    # ------------------------------------------------------------------
    # 3) Pool 정리
    # ------------------------------------------------------------------
    await close_pool()

    # ------------------------------------------------------------------
    # 최종 결과
    # ------------------------------------------------------------------
    print()
    print("=" * 72)
    total = _PASS + _FAIL
    print(f"검증 완료: {_PASS}/{total} PASS, {_FAIL}/{total} FAIL")
    print("=" * 72)

    if _FAIL == 0:
        print("✅ 전체 E2E 검증 완료 — latest_outcome Postgres 정상 동작 확인")
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
