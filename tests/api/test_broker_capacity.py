"""Tests for ``GET /broker-capacity`` — broker capacity inspection endpoint.

Test coverage
-------------
1. ``client_with_adapter`` — 200 with all expected response fields.
2. Response structure — ``rest_budget`` contains per-bucket snapshots.
3. WebSocket subscription snapshot — counters are reflected correctly.
4. ``empty_client`` (no adapter) — 503 with descriptive message.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


class TestBrokerCapacityWithAdapter:
    """Tests when a mock broker adapter is configured."""

    def test_returns_200_with_adapter(
        self, client_with_adapter: TestClient
    ) -> None:
        """``GET /broker-capacity`` returns 200 when adapter is configured."""
        resp = client_with_adapter.get("/broker-capacity")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_response_structure(self, client_with_adapter: TestClient) -> None:
        """All expected top-level fields are present."""
        resp = client_with_adapter.get("/broker-capacity")
        data = resp.json()

        assert "broker_name" in data
        assert "environment" in data
        assert "rest_budget" in data
        assert "can_accept_new_entries" in data
        assert "websocket" in data
        assert "market_data_subscriptions" in data
        assert "order_event_accounts" in data

        assert data["broker_name"] == "MagicMock"
        assert data["environment"] == "paper"
        assert data["can_accept_new_entries"] is True
        assert data["market_data_subscriptions"] == 2
        assert data["order_event_accounts"] == ["account-1"]

    def test_rest_budget_contains_buckets(
        self, client_with_adapter: TestClient
    ) -> None:
        """``rest_budget`` contains per-operation-type bucket snapshots."""
        resp = client_with_adapter.get("/broker-capacity")
        data = resp.json()
        budget = data["rest_budget"]

        # Should have order, inquiry, reconciliation, market_data, auth
        for key in ("order", "inquiry", "reconciliation", "market_data", "auth"):
            assert key in budget, f"Missing bucket: {key}"
            bucket = budget[key]
            assert "remaining" in bucket
            assert "capacity" in bucket
            assert "refill_rate" in bucket
            assert "utilization" in bucket

        # Verify a specific value
        assert budget["order"]["remaining"] == 3.0
        assert budget["order"]["capacity"] == 5.0

    def test_websocket_snapshot(self, client_with_adapter: TestClient) -> None:
        """WebSocket subscription counters are reflected correctly."""
        resp = client_with_adapter.get("/broker-capacity")
        data = resp.json()
        ws = data["websocket"]

        assert ws["max_subscriptions"] == 100
        assert ws["critical_limit"] == 20
        assert ws["optional_limit"] == 80
        assert ws["current_critical"] == 3
        assert ws["current_optional"] == 5
        assert ws["total_used"] == 8
        assert ws["remaining"] == 92

    def test_session_id_excluded_from_rest_budget(
        self, client_with_adapter: TestClient
    ) -> None:
        """``session_id`` is filtered out of ``rest_budget``."""
        resp = client_with_adapter.get("/broker-capacity")
        data = resp.json()
        assert "session_id" not in data["rest_budget"]


class TestBrokerCapacityWithoutAdapter:
    """Tests when no broker adapter is configured."""

    def test_returns_503_without_adapter(
        self, empty_client: TestClient
    ) -> None:
        """``GET /broker-capacity`` returns 503 when no adapter is configured."""
        resp = empty_client.get("/broker-capacity")
        assert resp.status_code == 503
        detail = resp.json().get("detail", "")
        assert "not configured" in detail.lower()
