"""Tests for ``PUT /orders/{order_request_id}/status`` (manual operator override).

Coverage (8 cases):

| # | Scenario | Expected |
|---|----------|----------|
| 1 | ``reconcile_required`` → ``rejected`` | 200, audit_log evidence, event_source=operator |
| 2 | ``reconcile_required`` → ``filled`` | 200 (whitelist includes filled) |
| 3 | Non-existent ``order_request_id`` | 404 |
| 4 | ``target_status`` outside whitelist (e.g. ``draft``) | 400 |
| 5 | ``evidence`` missing (empty dict) | 400 |
| 6 | Audit trail: ``order_state_events`` contains ``EventSource.OPERATOR`` | verified |
| 7 | Terminal → change attempt (``rejected`` → ``filled``) | 400 |
| 8 | Existing ``GET /orders/{id}`` regression (no schema change) | 200 |
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.domain.entities import (
    OrderRequestEntity,
    OrderStateEventEntity,
)
from agent_trading.domain.enums import (
    EventSource,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer

# Shared token for all admin-client fixtures
_ADMIN_TOKEN = "test-admin-token"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reconcile_order_id() -> UUID:
    return uuid4()


@pytest.fixture
def correlation_id() -> str:
    return f"manual-resolve-test-{uuid4()}"


@pytest.fixture
async def seeded_repos_with_reconcile(
    reconcile_order_id: UUID,
    correlation_id: str,
) -> RepositoryContainer:
    """Build in-memory repos seeded with an order in ``RECONCILE_REQUIRED``.

    Also adds a plain ``ACKNOWLEDGED`` order (for regression test #8).
    """
    repos = build_in_memory_repositories()
    now = datetime.now(timezone.utc)
    account_id = uuid4()
    instrument_id = uuid4()
    trade_decision_id = uuid4()

    # ── Order A: in RECONCILE_REQUIRED (target for manual resolve) ──
    reconcile_order = OrderRequestEntity(
        order_request_id=reconcile_order_id,
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id="MANUAL-RSLV-001",
        idempotency_key=f"idem-{uuid4()}",
        correlation_id=correlation_id,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        requested_quantity=Decimal("100"),
        requested_price=Decimal("150.00"),
        status=OrderStatus.RECONCILE_REQUIRED,
        status_reason_code="RECONCILE_REQUIRED",
        status_reason_message="Test reconcile state",
        time_in_force=TimeInForce.DAY,
        created_at=now,
        updated_at=now,
    )
    await repos.orders.add(reconcile_order)

    # Seed a state event showing RECONCILE_REQUIRED
    await repos.order_state_events.add(
        OrderStateEventEntity(
            order_state_event_id=uuid4(),
            order_request_id=reconcile_order_id,
            previous_status=OrderStatus.SUBMITTED,
            new_status=OrderStatus.RECONCILE_REQUIRED,
            event_source=EventSource.RECONCILIATION,
            event_timestamp=now,
            ingested_at=now,
            reason_code="broker_unknown",
            correlation_id=correlation_id,
        )
    )

    # ── Order B: in ACKNOWLEDGED (for regression test #8) ──
    ack_order = OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id="REGRESSION-001",
        idempotency_key=f"idem-{uuid4()}",
        correlation_id=f"regression-{uuid4()}",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        requested_quantity=Decimal("50"),
        requested_price=Decimal("100.00"),
        status=OrderStatus.ACKNOWLEDGED,
        time_in_force=TimeInForce.DAY,
        created_at=now,
        updated_at=now,
    )
    await repos.orders.add(ack_order)

    return repos


@pytest.fixture
async def admin_client(
    seeded_repos_with_reconcile: RepositoryContainer,
) -> TestClient:
    """TestClient with seeded repos + admin auth enabled.

    Uses ``auth_token="test-admin-token"`` and ``auth_role="admin"``.
    All requests to the PUT endpoint must include ``Authorization: Bearer test-admin-token``.
    """
    app = create_app(
        repos=seeded_repos_with_reconcile,
        auth_token=_ADMIN_TOKEN,
        auth_role="admin",
    )
    with TestClient(app) as tc:
        yield tc


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_ADMIN_TOKEN}"}


def _put_url(order_id: UUID | str) -> str:
    return f"/orders/{order_id}/status"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestManualResolve:
    """``PUT /orders/{order_request_id}/status`` — operator manual override."""

    # ── Case 1: RECONCILE_REQUIRED → REJECTED (success) ──
    def test_reconcile_to_rejected(
        self,
        admin_client: TestClient,
        reconcile_order_id: UUID,
        correlation_id: str,
    ) -> None:
        """RECONCILE_REQUIRED → REJECTED: 200, audit trail with operator."""
        body = {
            "target_status": "rejected",
            "reason_code": "MANUAL_RESOLVE",
            "reason_message": "Operator resolved — broker confirmed rejected",
            "evidence": {
                "source": "operator",
                "checked_at": "2026-05-16T10:00:00Z",
                "detail": "Verified via broker phone call",
            },
        }
        resp = admin_client.put(_put_url(reconcile_order_id), json=body, headers=_auth_headers())
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["order_id"] == str(reconcile_order_id)
        assert data["old_status"] == "reconcile_required"
        assert data["new_status"] == "rejected"
        assert data["actor"] == "admin"
        assert data["updated_at"] is not None

    # ── Case 2: RECONCILE_REQUIRED → FILLED (success, whitelist includes filled) ──
    def test_reconcile_to_filled(
        self,
        admin_client: TestClient,
        reconcile_order_id: UUID,
    ) -> None:
        """RECONCILE_REQUIRED → FILLED: 200 (filled is in _MANUAL_RESOLVE_TARGETS)."""
        body = {
            "target_status": "filled",
            "reason_code": "MANUAL_RESOLVE",
            "evidence": {
                "source": "operator",
                "checked_at": "2026-05-16T10:00:00Z",
                "detail": "Broker confirmed filled",
            },
        }
        resp = admin_client.put(_put_url(reconcile_order_id), json=body, headers=_auth_headers())
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["new_status"] == "filled"

    # ── Case 3: Non-existent order_request_id ──
    def test_order_not_found(
        self,
        admin_client: TestClient,
    ) -> None:
        """Non-existent order_request_id → 404."""
        fake_id = uuid4()
        body = {
            "target_status": "rejected",
            "evidence": {"source": "operator", "checked_at": "2026-05-16T10:00:00Z"},
        }
        resp = admin_client.put(_put_url(fake_id), json=body, headers=_auth_headers())
        assert resp.status_code == 404
        assert "not found" in resp.text.lower()

    # ── Case 4: target_status outside whitelist ──
    def test_target_outside_whitelist(
        self,
        admin_client: TestClient,
        reconcile_order_id: UUID,
    ) -> None:
        """target_status=draft (not in whitelist) → 400."""
        body = {
            "target_status": "draft",
            "evidence": {"source": "operator", "checked_at": "2026-05-16T10:00:00Z"},
        }
        resp = admin_client.put(_put_url(reconcile_order_id), json=body, headers=_auth_headers())
        assert resp.status_code == 400
        assert "not a valid manual resolve target" in resp.text.lower()

    # ── Case 5: evidence missing (empty dict) ──
    def test_evidence_missing(
        self,
        admin_client: TestClient,
        reconcile_order_id: UUID,
    ) -> None:
        """Empty evidence dict → 400."""
        body = {
            "target_status": "rejected",
            "evidence": {},
        }
        resp = admin_client.put(_put_url(reconcile_order_id), json=body, headers=_auth_headers())
        assert resp.status_code == 400
        assert "evidence" in resp.text.lower()

    # ── Case 6: Audit trail — order_state_events has EventSource.OPERATOR ──
    async def test_audit_trail_operator_source(
        self,
        admin_client: TestClient,
        seeded_repos_with_reconcile: RepositoryContainer,
        reconcile_order_id: UUID,
    ) -> None:
        """After successful resolve, order_state_events contain EventSource.OPERATOR."""
        body = {
            "target_status": "cancelled",
            "reason_code": "MANUAL_RESOLVE",
            "evidence": {
                "source": "operator",
                "checked_at": "2026-05-16T10:00:00Z",
            },
        }
        resp = admin_client.put(_put_url(reconcile_order_id), json=body, headers=_auth_headers())
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        # Query the in-memory repos directly
        events = await seeded_repos_with_reconcile.order_state_events.list_by_order_request(
            reconcile_order_id,
        )
        # Find the manual resolve event (most recent one with EventSource.OPERATOR)
        operator_events = [e for e in events if e.event_source == EventSource.OPERATOR]
        assert len(operator_events) == 1, (
            f"Expected exactly 1 operator event, got {len(operator_events)}"
        )
        op_event = operator_events[0]
        assert op_event.previous_status == OrderStatus.RECONCILE_REQUIRED
        assert op_event.new_status == OrderStatus.CANCELLED
        assert op_event.event_source == EventSource.OPERATOR
        assert op_event.reason_code == "MANUAL_RESOLVE"

    # ── Case 7: Terminal state → change attempt ──
    def test_terminal_order_rejected(
        self,
        admin_client: TestClient,
        reconcile_order_id: UUID,
    ) -> None:
        """Resolve to terminal → then retry → 400."""
        # First resolve: RECONCILE_REQUIRED → REJECTED
        body1 = {
            "target_status": "rejected",
            "evidence": {"source": "operator", "checked_at": "2026-05-16T10:00:00Z"},
        }
        resp1 = admin_client.put(_put_url(reconcile_order_id), json=body1, headers=_auth_headers())
        assert resp1.status_code == 200

        # Second resolve: same order (now REJECTED = terminal) → should fail
        body2 = {
            "target_status": "filled",
            "evidence": {"source": "operator", "checked_at": "2026-05-16T10:00:00Z"},
        }
        resp2 = admin_client.put(_put_url(reconcile_order_id), json=body2, headers=_auth_headers())
        assert resp2.status_code == 400
        assert "terminal" in resp2.text.lower() or "reconcile_required only" in resp2.text.lower()

    # ── Case 8: GET /orders/{id} regression (no schema change) ──
    def test_get_order_regression(
        self,
        admin_client: TestClient,
        reconcile_order_id: UUID,
    ) -> None:
        """``GET /orders/{id}`` still works — no schema regression."""
        resp = admin_client.get(f"/orders/{reconcile_order_id}", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["order_request_id"] == str(reconcile_order_id)
        assert data["status"] == "reconcile_required"
