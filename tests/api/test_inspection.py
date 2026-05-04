"""Inspection API endpoint tests.

Covers: ``GET /orders``, ``GET /orders/{id}``, ``GET /orders/{id}/events``,
``GET /audit-logs``, ``GET /reconciliation/runs``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.conftest import client  # noqa: F401


class TestOrders:
    """Order inspection endpoints."""

    def test_list_orders_empty(self, empty_client: TestClient) -> None:
        """``GET /orders`` returns empty list when no orders exist."""
        response = empty_client.get("/orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_orders(self, client: TestClient) -> None:
        """``GET /orders`` returns seeded orders."""
        response = client.get("/orders")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        first = data[0]
        assert first["side"] == "buy"
        assert first["order_type"] == "limit"
        assert first["status"] == "acknowledged"
        assert first["requested_quantity"] == 100.0
        assert first["requested_price"] == 150.0

    def test_get_order_by_id(self, client: TestClient) -> None:
        """``GET /orders/{id}`` returns order detail."""
        # First get list to find an ID
        list_resp = client.get("/orders")
        orders = list_resp.json()
        assert len(orders) >= 1
        order_id = orders[0]["order_request_id"]

        detail_resp = client.get(f"/orders/{order_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["order_request_id"] == order_id
        assert detail["side"] == "buy"
        assert detail["status"] == "acknowledged"
        # Detail-specific fields
        assert "instrument_id" in detail
        assert "time_in_force" in detail

    def test_get_order_not_found(self, client: TestClient) -> None:
        """``GET /orders/{id}`` returns 404 for unknown ID."""
        response = client.get("/orders/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_get_order_invalid_uuid(self, client: TestClient) -> None:
        """``GET /orders/{id}`` returns 400 for invalid UUID."""
        response = client.get("/orders/not-a-uuid")
        assert response.status_code == 400

    def test_get_order_events(self, client: TestClient) -> None:
        """``GET /orders/{id}/events`` returns state transition events."""
        list_resp = client.get("/orders")
        orders = list_resp.json()
        assert len(orders) >= 1
        order_id = orders[0]["order_request_id"]

        events_resp = client.get(f"/orders/{order_id}/events")
        assert events_resp.status_code == 200
        events = events_resp.json()
        assert len(events) >= 2  # PENDING + ACKNOWLEDGED
        # Verify sort order: ascending by event_timestamp
        timestamps = [e["event_timestamp"] for e in events]
        assert timestamps == sorted(timestamps)


class TestAuditLogs:
    """Audit log inspection endpoint."""

    def test_list_audit_logs(self, client: TestClient) -> None:
        """``GET /audit-logs`` returns audit entries filtered by correlation_id."""
        # Get the correlation_id from an order
        orders_resp = client.get("/orders")
        orders = orders_resp.json()
        assert len(orders) >= 1
        corr_id = orders[0]["correlation_id"]

        response = client.get(f"/audit-logs?correlation_id={corr_id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["action"] == "order.created"
        assert data[0]["target_entity_type"] == "order"

    def test_list_audit_logs_missing_param(self, client: TestClient) -> None:
        """``GET /audit-logs`` returns 422 when correlation_id is missing."""
        response = client.get("/audit-logs")
        assert response.status_code == 422

    def test_list_audit_logs_nonexistent(self, client: TestClient) -> None:
        """``GET /audit-logs`` returns empty list for unknown correlation_id."""
        response = client.get("/audit-logs?correlation_id=nonexistent")
        assert response.status_code == 200
        assert response.json() == []


class TestReconciliation:
    """Reconciliation inspection endpoints."""

    def test_list_reconciliation_runs(self, client: TestClient) -> None:
        """``GET /reconciliation/runs`` returns seeded runs."""
        # Get an account_id from orders
        orders_resp = client.get("/orders")
        orders = orders_resp.json()
        assert len(orders) >= 1
        acct_id = orders[0]["account_id"]

        response = client.get(f"/reconciliation/runs?account_id={acct_id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["trigger_type"] == "post_submit"
        assert data[0]["status"] == "started"

    def test_list_reconciliation_runs_missing_param(self, client: TestClient) -> None:
        """``GET /reconciliation/runs`` returns 422 when account_id is missing."""
        response = client.get("/reconciliation/runs")
        assert response.status_code == 422
