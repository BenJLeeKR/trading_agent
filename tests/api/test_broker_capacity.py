"""Tests for ``GET /broker-capacity`` — broker capacity inspection endpoint.

Test coverage
-------------
1. ``client_with_adapter`` — 200 with all expected response fields.
2. Response structure — ``rest_budget`` contains per-bucket snapshots.
3. WebSocket subscription snapshot — counters are reflected correctly.
4. ``empty_client`` (no adapter) — 503 with descriptive message.
5. ``create_app_from_env`` wiring — adapter is built in postgres mode.
6. ``build_api_broker_adapter`` — graceful handling of missing credentials.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app_from_env
from agent_trading.runtime.bootstrap import build_api_broker_adapter


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
        assert "generated_at" in data

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
        """WebSocket subscription counters and connection state are reflected correctly."""
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
        assert ws["ws_connected"] is True

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


class TestBuildApiBrokerAdapter:
    """Tests for ``build_api_broker_adapter()`` graceful handling."""

    def test_returns_none_when_credentials_missing(self) -> None:
        """Returns ``None`` when KIS API key and secret are both empty."""
        from agent_trading.config.settings import AppSettings

        settings = AppSettings(
            kis_api_key="",
            kis_api_secret="",
        )
        result = build_api_broker_adapter(settings)
        assert result is None

    def test_returns_none_on_build_failure(self) -> None:
        """Returns ``None`` when ``_build_kis_adapter`` raises."""
        from agent_trading.config.settings import AppSettings

        settings = AppSettings(
            kis_api_key="dummy-key",
            kis_api_secret="dummy-secret",
        )
        # Patch _build_kis_adapter (the private function inside bootstrap) to raise.
        with patch(
            "agent_trading.runtime.bootstrap._build_kis_adapter",
            side_effect=RuntimeError("Simulated build failure"),
        ):
            result = build_api_broker_adapter(settings)
            assert result is None


class TestCreateAppFromEnvWiring:
    """Tests that ``create_app_from_env()`` wires the broker adapter correctly.

    ``create_app_from_env`` reads ``INSPECTION_API_TOKEN`` from the environment
    and enables auth when it is set.  All requests to protected endpoints
    (including ``/broker-capacity``) must include ``Authorization: Bearer ...``.
    """

    _AUTH_HEADER = {"Authorization": "Bearer test-token"}

    def test_postgres_mode_builds_adapter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """In postgres mode, ``create_app_from_env`` attempts to build an adapter."""
        monkeypatch.setenv("API_RUNTIME_MODE", "postgres")
        monkeypatch.setenv("INSPECTION_API_TOKEN", "test-token")
        # Clear KIS credentials so build_api_broker_adapter returns None
        # (we just want to verify the wiring path, not a live adapter).
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_API_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)
        monkeypatch.delenv("KIS_API_SECRET", raising=False)

        app = create_app_from_env()
        # The app should start without error, and broker_adapter is None
        # because credentials are missing — that's expected.
        with TestClient(app) as client:
            resp = client.get("/broker-capacity", headers=self._AUTH_HEADER)
            assert resp.status_code == 503

    def test_in_memory_mode_skips_adapter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """In in-memory mode, no broker adapter is built."""
        monkeypatch.setenv("API_RUNTIME_MODE", "in_memory")
        monkeypatch.setenv("INSPECTION_API_TOKEN", "test-token")

        app = create_app_from_env()
        with TestClient(app) as client:
            resp = client.get("/broker-capacity", headers=self._AUTH_HEADER)
            assert resp.status_code == 503
            detail = resp.json().get("detail", "")
            assert "not configured" in detail.lower()

    def test_postgres_mode_with_mock_adapter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """In postgres mode with valid credentials, adapter is wired and returns 200."""
        monkeypatch.setenv("API_RUNTIME_MODE", "postgres")
        monkeypatch.setenv("INSPECTION_API_TOKEN", "test-token")
        monkeypatch.setenv("KIS_APP_KEY", "test-key")
        monkeypatch.setenv("KIS_APP_SECRET", "test-secret")
        monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678-01")
        monkeypatch.setenv("KIS_ENV", "paper")
        monkeypatch.setenv("KIS_BASE_URL", "https://mock.kis.com")
        monkeypatch.setenv("KIS_WS_URL", "wss://mock.kis.com/ws")

        # Patch build_api_broker_adapter to return a mock adapter.
        # The function lives in agent_trading.runtime.bootstrap, and
        # create_app_from_env imports it at runtime.
        mock_adapter = MagicMock()
        mock_adapter._mode = "paper"
        mock_adapter._rest = MagicMock()
        mock_adapter._rest.budget_manager = MagicMock()
        mock_adapter._rest.budget_manager.snapshot.return_value = {
            "can_accept_new_entries": True,
            "order": {"remaining": 5.0, "capacity": 5.0, "refill_rate": 1.0, "utilization": 0.0},
            "inquiry": {"remaining": 10.0, "capacity": 10.0, "refill_rate": 2.0, "utilization": 0.0},
            "reconciliation": {"remaining": 3.0, "capacity": 3.0, "refill_rate": 0.5, "utilization": 0.0},
            "market_data": {"remaining": 8.0, "capacity": 8.0, "refill_rate": 1.0, "utilization": 0.0},
            "auth": {"remaining": 1.0, "capacity": 1.0, "refill_rate": 0.1, "utilization": 0.0},
        }
        mock_adapter._subscription_budget = MagicMock()
        mock_adapter._subscription_budget.max_subscriptions = 100
        mock_adapter._subscription_budget.critical_limit = 20
        mock_adapter._subscription_budget.optional_limit = 80
        mock_adapter._subscription_budget.current_critical = 0
        mock_adapter._subscription_budget.current_optional = 0
        mock_adapter._subscription_budget.total_used = 0
        mock_adapter._subscription_budget.remaining = 100
        mock_adapter._market_data_subscriptions = {}
        mock_adapter._order_event_accounts = []

        with patch(
            "agent_trading.runtime.bootstrap.build_api_broker_adapter",
            return_value=mock_adapter,
        ):
            app = create_app_from_env()
            with TestClient(app) as client:
                resp = client.get("/broker-capacity", headers=self._AUTH_HEADER)
                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
                data = resp.json()
                assert data["broker_name"] == "MagicMock"
                assert data["environment"] == "paper"
                assert data["can_accept_new_entries"] is True
