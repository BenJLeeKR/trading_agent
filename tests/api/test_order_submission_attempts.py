"""Tests for ``GET /orders/{order_request_id}/submission-attempts``
and order detail summary (Phase 7)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.api.deps import get_repos
from agent_trading.domain.entities import (
    InstrumentEntity,
    OrderRequestEntity,
    OrderSubmissionAttemptEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.bootstrap import build_in_memory_repositories


def test_list_submission_attempts_empty():
    """No attempts → empty list."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    order_request_id = uuid.uuid4()
    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{order_request_id}/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    assert resp.json() == []

    app.dependency_overrides.clear()


def test_list_submission_attempts_with_data():
    """Seeded attempts → list with correct fields."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    order_request_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    attempt = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=order_request_id,
        attempt_number=1,
        submitted_at=now,
        broker_name="KOREA_INVESTMENT",
        accepted=True,
        broker_native_order_id="BRK-001",
        broker_status="confirmed",
        raw_code="ACC",
        raw_message="Accepted",
        error_type=None,
        retryable=None,
        http_status=200,
        duration_ms=150,
        created_at=now,
    )
    asyncio.run(repos.order_submission_attempts.add(attempt))

    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{order_request_id}/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["accepted"] is True
    assert data[0]["broker_name"] == "KOREA_INVESTMENT"
    assert data[0]["broker_native_order_id"] == "BRK-001"
    assert data[0]["attempt_number"] == 1
    assert data[0]["raw_code"] == "ACC"
    assert data[0]["http_status"] == 200
    assert data[0]["duration_ms"] == 150

    app.dependency_overrides.clear()


def test_list_submission_attempts_multiple():
    """Multiple attempts for same order → ordered by attempt_number."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    order_request_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    for i in range(3):
        attempt = OrderSubmissionAttemptEntity(
            attempt_id=uuid.uuid4(),
            order_request_id=order_request_id,
            attempt_number=i + 1,
            submitted_at=now,
            broker_name="KOREA_INVESTMENT",
            accepted=(i == 2),  # last one succeeds
            broker_native_order_id=f"BRK-00{i+1}" if i == 2 else None,
            raw_code="PEN" if i < 2 else "ACC",
            raw_message="Pending" if i < 2 else "Accepted",
            error_type=None,
            retryable=True if i < 2 else None,
            http_status=200,
            duration_ms=100 * (i + 1),
            created_at=now,
        )
        asyncio.run(repos.order_submission_attempts.add(attempt))

    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{order_request_id}/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    for i, item in enumerate(data):
        assert item["attempt_number"] == i + 1  # ordered correctly

    app.dependency_overrides.clear()


def test_list_submission_attempts_wrong_order():
    """Different order_request_id → empty list."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    order_request_id = uuid.uuid4()
    other_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    attempt = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=other_id,  # different order
        attempt_number=1,
        submitted_at=now,
        broker_name="KOREA_INVESTMENT",
        accepted=True,
        broker_native_order_id="BRK-001",
        raw_code="ACC",
        raw_message="Accepted",
        duration_ms=100,
        created_at=now,
    )
    asyncio.run(repos.order_submission_attempts.add(attempt))

    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{order_request_id}/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    assert resp.json() == []  # 다른 order_id이므로 빈 리스트

    app.dependency_overrides.clear()


def test_list_submission_attempts_invalid_uuid():
    """Invalid UUID → 422."""
    app = create_app(auth_token="test-token")

    with TestClient(app) as client:
        resp = client.get(
            "/orders/not-a-uuid/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 422

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Phase 7 — Order detail submission attempt summary tests
# ---------------------------------------------------------------------------


def _seed_order(
    repos,
    order_request_id: uuid.UUID,
    instrument_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Helper: seed an ``OrderRequestEntity`` into in-memory repos."""
    now = datetime.now(timezone.utc)
    order = OrderRequestEntity(
        order_request_id=order_request_id,
        account_id=uuid.uuid4(),
        instrument_id=instrument_id or uuid.uuid4(),
        client_order_id="CLI-001",
        idempotency_key="idem-001",
        correlation_id="corr-001",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        requested_quantity=Decimal("10"),
        status=OrderStatus.SUBMITTED,
        time_in_force=TimeInForce.DAY,
        created_at=now,
        updated_at=now,
        submitted_at=now,
        version=1,
    )
    asyncio.run(repos.orders.add(order))
    return order.order_request_id


def test_order_detail_has_submission_attempt_summary():
    """``GET /orders/{id}`` 응답에 ``submission_attempt_summary`` 필드가 포함됨."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    order_request_id = _seed_order(repos, order_request_id=uuid.uuid4())
    now = datetime.now(timezone.utc)

    # Seed 2 submission attempts
    for i in range(2):
        attempt = OrderSubmissionAttemptEntity(
            attempt_id=uuid.uuid4(),
            order_request_id=order_request_id,
            attempt_number=i + 1,
            submitted_at=now,
            broker_name="KOREA_INVESTMENT",
            accepted=(i == 1),  # 마지막 attempt만 accepted
            broker_native_order_id=f"BRK-00{i+1}",
            raw_code="ACC" if i == 1 else "PEN",
            raw_message="Accepted" if i == 1 else "Pending",
            error_type=None if i == 1 else "TIMEOUT",
            retryable=True if i == 0 else None,
            http_status=200,
            duration_ms=100 * (i + 1),
            created_at=now,
        )
        asyncio.run(repos.order_submission_attempts.add(attempt))

    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{order_request_id}",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    summary = data.get("submission_attempt_summary")
    assert summary is not None, "submission_attempt_summary should not be None"
    assert summary["attempt_count"] == 2
    assert summary["latest_accepted"] is True
    assert summary["latest_raw_code"] == "ACC"
    assert summary["latest_raw_message"] == "Accepted"
    assert summary["latest_error_type"] is None
    assert summary["last_submitted_at"] is not None

    app.dependency_overrides.clear()


def test_order_detail_summary_null_when_no_attempts():
    """제출 시도가 없는 order의 summary는 ``None``."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    order_request_id = _seed_order(repos, order_request_id=uuid.uuid4())

    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{order_request_id}",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("submission_attempt_summary") is None, (
        "summary should be None when no attempts exist"
    )

    app.dependency_overrides.clear()


def test_order_detail_summary_fields_accuracy():
    """summary 필드 값 정확성 검증 — 여러 attempt 중 마지막이 반영됨."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    order_request_id = _seed_order(repos, order_request_id=uuid.uuid4())
    now = datetime.now(timezone.utc)

    # 3 attempts, 마지막이 rejected
    for i in range(3):
        attempt = OrderSubmissionAttemptEntity(
            attempt_id=uuid.uuid4(),
            order_request_id=order_request_id,
            attempt_number=i + 1,
            submitted_at=now,
            broker_name="KOREA_INVESTMENT",
            accepted=(i == 0),         # 첫번째만 accepted
            broker_native_order_id=f"BRK-00{i+1}" if i == 0 else None,
            raw_code="REJ",
            raw_message="Rejected by broker",
            error_type="BROKER_REJECTION",
            retryable=False,
            http_status=400,
            duration_ms=50 * (i + 1),
            created_at=now,
        )
        asyncio.run(repos.order_submission_attempts.add(attempt))

    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{order_request_id}",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    summary = data.get("submission_attempt_summary")
    assert summary is not None

    # 총 3회 시도
    assert summary["attempt_count"] == 3
    # 마지막 attempt (index 2): accepted=False, raw_code="REJ"
    assert summary["latest_accepted"] is False
    assert summary["latest_raw_code"] == "REJ"
    assert summary["latest_raw_message"] == "Rejected by broker"
    assert summary["latest_error_type"] == "BROKER_REJECTION"
    assert summary["last_submitted_at"] is not None
    # Phase 8: derived outcome (error_type != None → "exception")
    assert summary["latest_outcome"] == "exception", (
        "expected 'exception' because error_type is set"
    )

    app.dependency_overrides.clear()


def test_order_detail_summary_outcome_accepted():
    """latest_outcome == 'accepted' 검증 (accepted=True, error_type=None)."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    order_request_id = _seed_order(repos, order_request_id=uuid.uuid4())
    now = datetime.now(timezone.utc)

    # accepted attempt with no error
    attempt = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=order_request_id,
        attempt_number=1,
        submitted_at=now,
        broker_name="KOREA_INVESTMENT",
        accepted=True,
        broker_native_order_id="BRK-001",
        raw_code="ACC",
        raw_message="Accepted",
        error_type=None,
        retryable=None,
        http_status=200,
        duration_ms=150,
        created_at=now,
    )
    asyncio.run(repos.order_submission_attempts.add(attempt))

    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{order_request_id}",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    summary = resp.json().get("submission_attempt_summary")
    assert summary is not None
    assert summary["latest_outcome"] == "accepted"

    app.dependency_overrides.clear()


def test_order_detail_summary_outcome_rejected():
    """latest_outcome == 'rejected' 검증 (accepted=False, error_type=None)."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    order_request_id = _seed_order(repos, order_request_id=uuid.uuid4())
    now = datetime.now(timezone.utc)

    # rejected attempt with no error_type (plain rejection)
    attempt = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=order_request_id,
        attempt_number=1,
        submitted_at=now,
        broker_name="KOREA_INVESTMENT",
        accepted=False,
        broker_native_order_id=None,
        raw_code="REJ",
        raw_message="Rejected",
        error_type=None,
        retryable=False,
        http_status=400,
        duration_ms=100,
        created_at=now,
    )
    asyncio.run(repos.order_submission_attempts.add(attempt))

    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{order_request_id}",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    summary = resp.json().get("submission_attempt_summary")
    assert summary is not None
    assert summary["latest_outcome"] == "rejected"

    app.dependency_overrides.clear()


def test_order_detail_summary_outcome_exception():
    """latest_outcome == 'exception' 검증 (error_type is not None)."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    order_request_id = _seed_order(repos, order_request_id=uuid.uuid4())
    now = datetime.now(timezone.utc)

    # attempt with an error (exception case)
    attempt = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=order_request_id,
        attempt_number=1,
        submitted_at=now,
        broker_name="KOREA_INVESTMENT",
        accepted=False,
        broker_native_order_id=None,
        raw_code="ERR",
        raw_message="Broker timeout",
        error_type="TIMEOUT",
        retryable=True,
        http_status=500,
        duration_ms=5000,
        created_at=now,
    )
    asyncio.run(repos.order_submission_attempts.add(attempt))

    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{order_request_id}",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    summary = resp.json().get("submission_attempt_summary")
    assert summary is not None
    assert summary["latest_outcome"] == "exception"

    app.dependency_overrides.clear()


def test_order_detail_summary_outcome_none_when_no_attempts():
    """latest_outcome == None 검증 (제출 시도 없음)."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    order_request_id = _seed_order(repos, order_request_id=uuid.uuid4())

    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{order_request_id}",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    # No attempts → summary is None, so latest_outcome is not present
    assert data.get("submission_attempt_summary") is None, (
        "summary should be None when no attempts exist"
    )

    app.dependency_overrides.clear()


def test_list_attempts_outcome_accepted():
    """``attempt_outcome == 'accepted'`` when accepted=True, error_type=None."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    oid = uuid.uuid4()
    asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=oid,
        attempt_number=1,
        accepted=True,
        raw_code="ACC",
        raw_message="Accepted",
        error_type=None,
        submitted_at=datetime.now(timezone.utc),
    )))
    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{oid}/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["attempt_outcome"] == "accepted"

    app.dependency_overrides.clear()


def test_list_attempts_outcome_rejected():
    """``attempt_outcome == 'rejected'`` when accepted=False, error_type=None."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    oid = uuid.uuid4()
    asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=oid,
        attempt_number=1,
        accepted=False,
        raw_code="REJ",
        raw_message="Rejected",
        error_type=None,
        submitted_at=datetime.now(timezone.utc),
    )))
    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{oid}/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["attempt_outcome"] == "rejected"

    app.dependency_overrides.clear()


def test_list_attempts_outcome_exception():
    """``attempt_outcome == 'exception'`` when error_type is set."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    oid = uuid.uuid4()
    asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=oid,
        attempt_number=1,
        accepted=False,
        raw_code="",
        raw_message="Timeout",
        error_type="TIMEOUT",
        submitted_at=datetime.now(timezone.utc),
    )))
    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{oid}/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["attempt_outcome"] == "exception"

    app.dependency_overrides.clear()


def test_list_attempts_outcome_none():
    """``attempt_outcome`` is None when all outcome fields are None."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    oid = uuid.uuid4()
    asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=oid,
        attempt_number=1,
        accepted=None,
        raw_code=None,
        raw_message=None,
        error_type=None,
        submitted_at=datetime.now(timezone.utc),
    )))
    with TestClient(app) as client:
        resp = client.get(
            f"/orders/{oid}/submission-attempts",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["attempt_outcome"] is None

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Phase 12 — GET /orders/recent-failures tests
# ---------------------------------------------------------------------------


def test_list_recent_failures_returns_rejected_and_exception():
    """``GET /orders/recent-failures`` should return rejected/exception attempts,
    but not accepted ones."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    now = datetime.now(timezone.utc)
    oid_ok = uuid.uuid4()       # accepted — should not appear
    oid_rej = uuid.uuid4()      # rejected — should appear
    oid_err = uuid.uuid4()      # exception — should appear

    # accepted attempt
    asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=oid_ok,
        attempt_number=1,
        submitted_at=now,
        accepted=True,
        raw_code="ACC",
        raw_message="Accepted",
        error_type=None,
    )))

    # rejected attempt
    asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=oid_rej,
        attempt_number=1,
        submitted_at=now,
        accepted=False,
        raw_code="REJ",
        raw_message="Rejected by broker",
        error_type=None,
    )))

    # exception attempt
    asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=oid_err,
        attempt_number=1,
        submitted_at=now,
        accepted=False,
        raw_code="ERR",
        raw_message="Broker timeout",
        error_type="TIMEOUT",
    )))

    with TestClient(app) as client:
        resp = client.get(
            "/orders/recent-failures",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    # accepted should not appear
    assert len(data) == 2, f"Expected 2 failures, got {len(data)}: {data}"

    result_ids = {item["order_request_id"] for item in data}
    assert str(oid_rej) in result_ids
    assert str(oid_err) in result_ids
    assert str(oid_ok) not in result_ids

    # Validate outcome strings
    for item in data:
        assert item["latest_outcome"] in ("rejected", "exception")
        assert item["symbol"] is None  # InMemory has no order join
        assert item["side"] is None   # InMemory has no order join

    app.dependency_overrides.clear()


def test_list_recent_failures_empty_when_none():
    """When all attempts are accepted, endpoint returns empty list."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    now = datetime.now(timezone.utc)
    oid = uuid.uuid4()
    asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=oid,
        attempt_number=1,
        submitted_at=now,
        accepted=True,
        raw_code="ACC",
        raw_message="Accepted",
        error_type=None,
    )))

    with TestClient(app) as client:
        resp = client.get(
            "/orders/recent-failures",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    assert resp.json() == []

    app.dependency_overrides.clear()


def test_list_recent_failures_limit():
    """``limit`` parameter should cap results."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    now = datetime.now(timezone.utc)
    oids = [uuid.uuid4() for _ in range(5)]
    for i, oid in enumerate(oids):
        asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
            attempt_id=uuid.uuid4(),
            order_request_id=oid,
            attempt_number=1,
            submitted_at=now,
            accepted=False,
            raw_code="REJ",
            raw_message="Rejected",
            error_type=None,
        )))

    with TestClient(app) as client:
        resp = client.get(
            "/orders/recent-failures?limit=3",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3, f"Expected 3, got {len(data)}"

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Phase 13 — GET /orders/failure-summary tests
# ---------------------------------------------------------------------------


def test_get_failure_summary_with_data():
    """``GET /orders/failure-summary`` with mixed data returns correct aggregates."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    now = datetime.now(timezone.utc)
    oid_acc = uuid.uuid4()    # accepted — not a failure
    oid_rej = uuid.uuid4()    # rejected — is a failure
    oid_err = uuid.uuid4()    # exception — is a failure

    # accepted attempt
    asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=oid_acc,
        attempt_number=1,
        submitted_at=now,
        accepted=True,
        raw_code="ACC",
        raw_message="Accepted",
        error_type=None,
    )))

    # rejected attempt
    asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=oid_rej,
        attempt_number=1,
        submitted_at=now,
        accepted=False,
        raw_code="REJ",
        raw_message="Rejected by broker",
        error_type=None,
    )))

    # exception attempt
    asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=oid_err,
        attempt_number=1,
        submitted_at=now,
        accepted=False,
        raw_code="ERR",
        raw_message="Broker timeout",
        error_type="TIMEOUT",
    )))

    with TestClient(app) as client:
        resp = client.get(
            "/orders/failure-summary",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()

    assert data["last_1h_count"] == 2   # rejected + exception
    assert data["last_24h_count"] == 2
    assert data["rejected_count"] == 1
    assert data["exception_count"] == 1
    assert data["total_submissions_24h"] == 3  # accepted + rejected + exception
    assert data["failure_rate_pct_24h"] == pytest.approx(66.7, abs=0.1)
    assert data["today_count"] == 2
    assert data["rejected_count_today"] == 1
    assert data["exception_count_today"] == 1
    assert data["total_submissions_today"] == 3
    assert data["failure_rate_pct_today"] == pytest.approx(66.7, abs=0.1)

    app.dependency_overrides.clear()


def test_get_failure_summary_empty():
    """When no failures exist, all counts are zero and failure_rate is None."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    now = datetime.now(timezone.utc)
    oid = uuid.uuid4()
    asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=oid,
        attempt_number=1,
        submitted_at=now,
        accepted=True,
        raw_code="ACC",
        raw_message="Accepted",
        error_type=None,
    )))

    with TestClient(app) as client:
        resp = client.get(
            "/orders/failure-summary",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["last_1h_count"] == 0
    assert data["last_24h_count"] == 0
    assert data["rejected_count"] == 0
    assert data["exception_count"] == 0
    assert data["total_submissions_24h"] == 1
    assert data["failure_rate_pct_24h"] == 0.0
    assert data["today_count"] == 0
    assert data["rejected_count_today"] == 0
    assert data["exception_count_today"] == 0
    assert data["total_submissions_today"] == 1
    assert data["failure_rate_pct_today"] == 0.0

    app.dependency_overrides.clear()


def test_get_failure_summary_no_attempts():
    """When there are zero attempts at all, all counts are 0 and rate is None."""
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    with TestClient(app) as client:
        resp = client.get(
            "/orders/failure-summary",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["last_1h_count"] == 0
    assert data["last_24h_count"] == 0
    assert data["rejected_count"] == 0
    assert data["exception_count"] == 0
    assert data["total_submissions_24h"] == 0
    assert data["failure_rate_pct_24h"] is None
    assert data["today_count"] == 0
    assert data["rejected_count_today"] == 0
    assert data["exception_count_today"] == 0
    assert data["total_submissions_today"] == 0
    assert data["failure_rate_pct_today"] is None

    app.dependency_overrides.clear()
