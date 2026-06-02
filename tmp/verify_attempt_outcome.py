#!/usr/bin/env python3
"""
Phase 9 E2E: ``SubmissionAttemptView.attempt_outcome`` derived field 검증
(실제 Postgres DB, Subtask 5)

시나리오:
  A. accepted=True,  error_type=None          → attempt_outcome == "accepted"
  B. accepted=False, error_type=None          → attempt_outcome == "rejected"
  C. accepted=False, error_type="TIMEOUT"     → attempt_outcome == "exception"
  D. accepted=True,  error_type="EXCEPTION"   → attempt_outcome == "exception" (error_type 우선)

각 시나리오는 FK 체인을 포함한 별도의 order_request로 생성되며,
모든 데이터는 트랜잭션 rollback으로 정리됩니다.
"""

from __future__ import annotations

import asyncio
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
# FK 체인 생성 (instruments → clients → broker_accounts → accounts)
# ---------------------------------------------------------------------------


async def _ensure_fk_chain(tx: TransactionManager, label: str) -> dict:
    """instruments / clients / broker_accounts / accounts 를 한 번씩만 생성."""
    instr = await tx.connection.fetchrow(
        "INSERT INTO trading.instruments "
        "(symbol, market_code, asset_class, currency, name) "
        "VALUES ($1, 'KRX', 'stock', 'KRW', $2) "
        "RETURNING instrument_id",
        f"AO-{label}",
        f"Attempt Outcome Test {label}",
    )
    instrument_id = instr["instrument_id"]

    cli = await tx.connection.fetchrow(
        "INSERT INTO trading.clients "
        "(client_code, name, status) "
        "VALUES ($1, $2, 'active') "
        "RETURNING client_id",
        f"AO-CLIENT-{label}",
        f"AO Client {label}",
    )
    client_id = cli["client_id"]

    ba = await tx.connection.fetchrow(
        "INSERT INTO trading.broker_accounts "
        "(broker_name, account_ref, environment, credential_ref, status) "
        "VALUES ('KOREA_INVESTMENT', $1, 'paper', $2, 'active') "
        "RETURNING broker_account_id",
        f"AO-ACC-REF-{label}",
        f"ao-cred-{label}",
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
        f"AO-Account-{label}",
    )
    account_id = acc["account_id"]

    return {
        "instrument_id": instrument_id,
        "account_id": account_id,
    }


async def _create_order(
    tx: TransactionManager,
    repos,
    order_request_id: uuid.UUID,
    fk: dict,
) -> None:
    """order_requests INSERT."""
    now = datetime.now(timezone.utc)
    order = OrderRequestEntity(
        order_request_id=order_request_id,
        account_id=fk["account_id"],
        instrument_id=fk["instrument_id"],
        client_order_id=f"AO-ORD-{order_request_id}",
        idempotency_key=f"ao-idem-{order_request_id}",
        correlation_id=f"ao-corr-{order_request_id}",
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


# ---------------------------------------------------------------------------
# Attempt 생성 헬퍼
# ---------------------------------------------------------------------------


async def _create_attempt(
    repos,
    order_request_id: uuid.UUID,
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
        attempt_number=1,
        submitted_at=now,
        broker_name="KOREA_INVESTMENT",
        accepted=accepted,
        broker_native_order_id="BRK-AO-001" if accepted else None,
        broker_status="received" if accepted else "failed",
        raw_code=raw_code,
        raw_message=raw_message,
        error_type=error_type,
        retryable=(error_type is not None),
        http_status=200 if accepted else (500 if error_type else 400),
        duration_ms=100,
        created_at=now,
    )
    await repos.order_submission_attempts.add(attempt)


# ---------------------------------------------------------------------------
# 시나리오 실행
# ---------------------------------------------------------------------------


async def _scenario_a(repos, tx: TransactionManager) -> bool:
    """Scenario A: accepted → attempt_outcome == 'accepted'."""
    label = "SCN-A"
    oid = uuid.uuid4()
    fk = await _ensure_fk_chain(tx, label)
    await _create_order(tx, repos, oid, fk)
    await _create_attempt(repos, oid, accepted=True, error_type=None,
                          raw_code="ACC", raw_message="Accepted")

    app = create_app(auth_token="test-token")
    configure_security(token="test-token", role="viewer")

    async def _override():
        yield repos

    app.dependency_overrides[get_repos] = _override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/orders/{oid}/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    app.dependency_overrides.clear()

    _check(resp.status_code == 200, f"[A] HTTP 200 (actual={resp.status_code})")
    if resp.status_code != 200:
        return False

    data = resp.json()
    _check(len(data) == 1, f"[A] 1 attempt (actual={len(data)})")
    if len(data) == 0:
        return False

    actual = data[0]["attempt_outcome"]
    _check(actual == "accepted",
           f"[A] attempt_outcome == 'accepted' (actual={actual!r})")
    _check(data[0]["accepted"] is True, "[A] accepted == True")
    _check(data[0]["error_type"] is None, "[A] error_type == None")
    return True


async def _scenario_b(repos, tx: TransactionManager) -> bool:
    """Scenario B: rejected → attempt_outcome == 'rejected'."""
    label = "SCN-B"
    oid = uuid.uuid4()
    fk = await _ensure_fk_chain(tx, label)
    await _create_order(tx, repos, oid, fk)
    await _create_attempt(repos, oid, accepted=False, error_type=None,
                          raw_code="REJ", raw_message="Rejected by broker")

    app = create_app(auth_token="test-token")
    configure_security(token="test-token", role="viewer")

    async def _override():
        yield repos

    app.dependency_overrides[get_repos] = _override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/orders/{oid}/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    app.dependency_overrides.clear()

    _check(resp.status_code == 200, f"[B] HTTP 200 (actual={resp.status_code})")
    if resp.status_code != 200:
        return False

    data = resp.json()
    _check(len(data) == 1, f"[B] 1 attempt (actual={len(data)})")
    if len(data) == 0:
        return False

    actual = data[0]["attempt_outcome"]
    _check(actual == "rejected",
           f"[B] attempt_outcome == 'rejected' (actual={actual!r})")
    _check(data[0]["accepted"] is False, "[B] accepted == False")
    _check(data[0]["error_type"] is None, "[B] error_type == None")
    return True


async def _scenario_c(repos, tx: TransactionManager) -> bool:
    """Scenario C: exception → attempt_outcome == 'exception'."""
    label = "SCN-C"
    oid = uuid.uuid4()
    fk = await _ensure_fk_chain(tx, label)
    await _create_order(tx, repos, oid, fk)
    await _create_attempt(repos, oid, accepted=False, error_type="TIMEOUT",
                          raw_code=None, raw_message="Broker timeout")

    app = create_app(auth_token="test-token")
    configure_security(token="test-token", role="viewer")

    async def _override():
        yield repos

    app.dependency_overrides[get_repos] = _override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/orders/{oid}/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    app.dependency_overrides.clear()

    _check(resp.status_code == 200, f"[C] HTTP 200 (actual={resp.status_code})")
    if resp.status_code != 200:
        return False

    data = resp.json()
    _check(len(data) == 1, f"[C] 1 attempt (actual={len(data)})")
    if len(data) == 0:
        return False

    actual = data[0]["attempt_outcome"]
    _check(actual == "exception",
           f"[C] attempt_outcome == 'exception' (actual={actual!r})")
    _check(data[0]["accepted"] is False, "[C] accepted == False")
    _check(data[0]["error_type"] == "TIMEOUT", "[C] error_type == 'TIMEOUT'")
    return True


async def _scenario_d(repos, tx: TransactionManager) -> bool:
    """Scenario D: accepted=True + error_type='EXCEPTION' → error_type 우선 → attempt_outcome == 'exception'."""
    label = "SCN-D"
    oid = uuid.uuid4()
    fk = await _ensure_fk_chain(tx, label)
    await _create_order(tx, repos, oid, fk)
    # accepted=True 이지만 error_type이 있으므로 'exception'이 우선
    await _create_attempt(repos, oid, accepted=True, error_type="EXCEPTION",
                          raw_code=None, raw_message="Internal exception")

    app = create_app(auth_token="test-token")
    configure_security(token="test-token", role="viewer")

    async def _override():
        yield repos

    app.dependency_overrides[get_repos] = _override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/orders/{oid}/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    app.dependency_overrides.clear()

    _check(resp.status_code == 200, f"[D] HTTP 200 (actual={resp.status_code})")
    if resp.status_code != 200:
        return False

    data = resp.json()
    _check(len(data) == 1, f"[D] 1 attempt (actual={len(data)})")
    if len(data) == 0:
        return False

    actual = data[0]["attempt_outcome"]
    _check(actual == "exception",
           f"[D] attempt_outcome == 'exception' (actual={actual!r})")
    _check(data[0]["error_type"] == "EXCEPTION", "[D] error_type == 'EXCEPTION'")
    # accepted=True 이지만 error_type이 우선하므로 exception
    _check(data[0]["accepted"] is True, "[D] accepted == True")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    global _PASS, _FAIL

    print("=" * 60)
    print("Phase 9 E2E: SubmissionAttemptView.attempt_outcome 검증")
    print("=" * 60)

    await create_pool(DatabaseConfig())

    async with TransactionManager(force_rollback=True) as tx:
        repos = build_postgres_repositories(tx)

        # 순차 실행 (asyncpg connection은 동시 요청 미지원)
        scenarios = [
            ("A", _scenario_a(repos, tx)),
            ("B", _scenario_b(repos, tx)),
            ("C", _scenario_c(repos, tx)),
            ("D", _scenario_d(repos, tx)),
        ]
        for label, coro in scenarios:
            try:
                await coro
            except Exception as e:
                print(f"  💥 Scenario {label} raised: {e}")

    await close_pool()

    print(f"\n{'=' * 60}")
    print(f"결과: {_PASS}/{_PASS + _FAIL} PASS")
    print(f"{'=' * 60}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
