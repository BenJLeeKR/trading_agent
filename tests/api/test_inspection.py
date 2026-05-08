"""Inspection API endpoint tests.

Covers: ``GET /orders``, ``GET /orders/{id}``, ``GET /orders/{id}/events``,
``GET /audit-logs``, ``GET /reconciliation/runs``, ``GET /reconciliation/locks``,
``GET /accounts``, ``GET /accounts/{id}``, ``GET /instruments/{id}``,
``GET /positions``, ``GET /cash-balances``, ``GET /clients/{id}``,
``GET /orders/{id}/broker-orders``, ``GET /agent-runs``.
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

    # -- Plan 44: Lock inspection tests --

    def test_list_locks(self, client: TestClient) -> None:
        """``GET /reconciliation/locks`` returns active locks."""
        orders_resp = client.get("/orders")
        orders = orders_resp.json()
        assert len(orders) >= 1
        acct_id = orders[0]["account_id"]

        response = client.get(f"/reconciliation/locks?account_id={acct_id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        lock = data[0]
        assert lock["account_id"] == acct_id
        assert lock["symbol"] == "AAPL"
        assert lock["side"] == "buy"
        assert lock["is_active"] is True
        assert "lock_id" in lock
        assert "locked_at" in lock

    def test_list_locks_missing_param(self, client: TestClient) -> None:
        """``GET /reconciliation/locks`` returns 422 when account_id is missing."""
        response = client.get("/reconciliation/locks")
        assert response.status_code == 422

    def test_list_locks_invalid_uuid(self, client: TestClient) -> None:
        """``GET /reconciliation/locks`` returns 400 for invalid UUID."""
        response = client.get("/reconciliation/locks?account_id=not-a-uuid")
        assert response.status_code == 400

    # -- Plan 64: Aggregate summary endpoint --

    def test_reconciliation_summary(self, client: TestClient) -> None:
        """``GET /reconciliation/summary`` returns aggregate metrics."""
        response = client.get("/reconciliation/summary")
        assert response.status_code == 200
        data = response.json()
        # Should have at least the seeded lock and run
        assert data["active_locks_count"] >= 1
        assert data["incomplete_recon_count"] >= 1
        assert len(data["recent_active_locks"]) >= 1
        assert len(data["recent_incomplete_runs"]) >= 1
        # generated_at freshness timestamp
        assert "generated_at" in data
        # Check structure of first lock
        lock = data["recent_active_locks"][0]
        assert "lock_id" in lock
        assert "account_id" in lock
        assert "symbol" in lock
        assert "is_active" in lock
        # Check structure of first incomplete run
        run = data["recent_incomplete_runs"][0]
        assert run["status"] != "completed"
        assert "reconciliation_run_id" in run
        assert "account_id" in run


# ── Phase 2: Account, Client, Instrument, Position, Cash-balance, Broker-order ──


class TestAccounts:
    """Account inspection endpoints."""

    def test_list_accounts(self, client: TestClient) -> None:
        """``GET /accounts?client_id=...`` returns seeded accounts."""
        # Get a client_id from orders
        orders_resp = client.get("/orders")
        orders = orders_resp.json()
        assert len(orders) >= 1
        client_id = orders[0]["account_id"]  # not ideal — use seeded client_id directly
        # Instead, find the client_code from an order's correlation_id
        # Better: get accounts via a known client_id from seed data
        # We know the seeded account has client_id we can discover via get-order detail
        detail_resp = client.get(f"/orders/{orders[0]['order_request_id']}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        # account_id is in detail — use it to find client_id through accounts
        acct_resp = client.get(f"/accounts/{detail['account_id']}")
        assert acct_resp.status_code == 200
        acct_data = acct_resp.json()
        known_client_id = acct_data["client_id"]

        response = client.get(f"/accounts?client_id={known_client_id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["client_id"] == known_client_id

    def test_list_accounts_missing_param(self, client: TestClient) -> None:
        """``GET /accounts`` returns 422 when client_id is missing."""
        response = client.get("/accounts")
        assert response.status_code == 422

    def test_list_accounts_invalid_uuid(self, client: TestClient) -> None:
        """``GET /accounts`` returns 400 for invalid client_id UUID."""
        response = client.get("/accounts?client_id=not-a-uuid")
        assert response.status_code == 400

    def test_get_account_by_id(self, client: TestClient) -> None:
        """``GET /accounts/{id}`` returns account detail."""
        # Discover seeded account_id from orders
        orders_resp = client.get("/orders")
        orders = orders_resp.json()
        assert len(orders) >= 1
        detail_resp = client.get(f"/orders/{orders[0]['order_request_id']}")
        assert detail_resp.status_code == 200
        known_acct_id = detail_resp.json()["account_id"]

        response = client.get(f"/accounts/{known_acct_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["account_id"] == known_acct_id
        assert "environment" in data
        assert "status" in data

    def test_get_account_not_found(self, client: TestClient) -> None:
        """``GET /accounts/{id}`` returns 404 for unknown ID."""
        response = client.get("/accounts/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_get_account_invalid_uuid(self, client: TestClient) -> None:
        """``GET /accounts/{id}`` returns 400 for invalid UUID."""
        response = client.get("/accounts/not-a-uuid")
        assert response.status_code == 400


class TestInstruments:
    """Instrument inspection endpoints."""

    def test_get_instrument_by_id(self, client: TestClient) -> None:
        """``GET /instruments/{id}`` returns instrument detail."""
        # Discover seeded instrument_id from orders
        orders_resp = client.get("/orders")
        orders = orders_resp.json()
        assert len(orders) >= 1
        detail_resp = client.get(f"/orders/{orders[0]['order_request_id']}")
        assert detail_resp.status_code == 200
        known_instr_id = detail_resp.json()["instrument_id"]

        response = client.get(f"/instruments/{known_instr_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["instrument_id"] == known_instr_id
        assert data["symbol"] == "AAPL"
        assert data["market_code"] == "NASDAQ"
        assert data["is_active"] is True

    def test_get_instrument_not_found(self, client: TestClient) -> None:
        """``GET /instruments/{id}`` returns 404 for unknown ID."""
        response = client.get("/instruments/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_get_instrument_invalid_uuid(self, client: TestClient) -> None:
        """``GET /instruments/{id}`` returns 400 for invalid UUID."""
        response = client.get("/instruments/not-a-uuid")
        assert response.status_code == 400


class TestPositions:
    """Position / cash-balance inspection endpoints."""

    def test_list_positions(self, client: TestClient) -> None:
        """``GET /positions?account_id=...`` returns seeded position snapshot."""
        # Discover seeded account_id
        orders_resp = client.get("/orders")
        orders = orders_resp.json()
        assert len(orders) >= 1
        detail_resp = client.get(f"/orders/{orders[0]['order_request_id']}")
        assert detail_resp.status_code == 200
        known_acct_id = detail_resp.json()["account_id"]

        response = client.get(f"/positions?account_id={known_acct_id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        pos = data[0]
        assert pos["account_id"] == known_acct_id
        assert pos["quantity"] == 100.0
        assert pos["average_price"] == 150.0
        assert pos["market_price"] == 155.0

    def test_list_positions_missing_param(self, client: TestClient) -> None:
        """``GET /positions`` returns 422 when account_id is missing."""
        response = client.get("/positions")
        assert response.status_code == 422

    def test_list_positions_invalid_uuid(self, client: TestClient) -> None:
        """``GET /positions`` returns 400 for invalid account_id UUID."""
        response = client.get("/positions?account_id=not-a-uuid")
        assert response.status_code == 400

    def test_list_positions_empty(self, client: TestClient) -> None:
        """``GET /positions`` returns empty list for unknown account."""
        response = client.get("/positions?account_id=00000000-0000-0000-0000-000000000000")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_cash_balance(self, client: TestClient) -> None:
        """``GET /cash-balances?account_id=...`` returns seeded cash balance."""
        orders_resp = client.get("/orders")
        orders = orders_resp.json()
        assert len(orders) >= 1
        detail_resp = client.get(f"/orders/{orders[0]['order_request_id']}")
        assert detail_resp.status_code == 200
        known_acct_id = detail_resp.json()["account_id"]

        response = client.get(f"/cash-balances?account_id={known_acct_id}")
        assert response.status_code == 200
        data = response.json()
        assert data is not None
        assert data["account_id"] == known_acct_id
        assert data["currency"] == "KRW"
        assert data["available_cash"] == 1000000.0

    def test_get_cash_balance_missing_param(self, client: TestClient) -> None:
        """``GET /cash-balances`` returns 422 when account_id is missing."""
        response = client.get("/cash-balances")
        assert response.status_code == 422

    def test_get_cash_balance_empty(self, client: TestClient) -> None:
        """``GET /cash-balances`` returns 200 null for unknown account."""
        response = client.get("/cash-balances?account_id=00000000-0000-0000-0000-000000000000")
        assert response.status_code == 200
        assert response.json() is None


class TestClients:
    """Client inspection endpoints."""

    def test_get_client_by_id(self, client: TestClient) -> None:
        """``GET /clients/{id}`` returns client detail."""
        # Discover client_id from accounts
        orders_resp = client.get("/orders")
        orders = orders_resp.json()
        assert len(orders) >= 1
        detail_resp = client.get(f"/orders/{orders[0]['order_request_id']}")
        assert detail_resp.status_code == 200
        acct_resp = client.get(f"/accounts/{detail_resp.json()['account_id']}")
        assert acct_resp.status_code == 200
        known_client_id = acct_resp.json()["client_id"]

        response = client.get(f"/clients/{known_client_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["client_id"] == known_client_id
        assert data["client_code"] == "API_TEST"
        assert data["name"] == "API Test Client"
        assert data["base_currency"] == "KRW"

    def test_get_client_not_found(self, client: TestClient) -> None:
        """``GET /clients/{id}`` returns 404 for unknown ID."""
        response = client.get("/clients/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_get_client_invalid_uuid(self, client: TestClient) -> None:
        """``GET /clients/{id}`` returns 400 for invalid UUID."""
        response = client.get("/clients/not-a-uuid")
        assert response.status_code == 400


class TestBrokerOrders:
    """Broker-order inspection endpoints."""

    def test_get_broker_orders(self, client: TestClient) -> None:
        """``GET /orders/{id}/broker-orders`` returns broker order refs."""
        orders_resp = client.get("/orders")
        orders = orders_resp.json()
        assert len(orders) >= 1
        order_id = orders[0]["order_request_id"]

        response = client.get(f"/orders/{order_id}/broker-orders")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        bo = data[0]
        assert bo["broker_name"] == "KIS"
        assert bo["broker_status"] == "filled"
        assert bo["broker_native_order_id"] == "KIS-12345"

    def test_get_broker_orders_not_found(self, client: TestClient) -> None:
        """``GET /orders/{id}/broker-orders`` returns 404 for unknown order."""
        response = client.get("/orders/00000000-0000-0000-0000-000000000000/broker-orders")
        assert response.status_code == 404

    def test_get_broker_orders_invalid_uuid(self, client: TestClient) -> None:
        """``GET /orders/{id}/broker-orders`` returns 400 for invalid UUID."""
        response = client.get("/orders/not-a-uuid/broker-orders")
        assert response.status_code == 400


class TestAgentRuns:
    """Agent run inspection endpoints."""

    def test_list_agent_runs_empty(self, empty_client: TestClient) -> None:
        """``GET /agent-runs`` returns empty list when no runs exist."""
        response = empty_client.get("/agent-runs")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_agent_runs(self, client: TestClient) -> None:
        """``GET /agent-runs`` returns seeded agent runs ordered by started_at DESC."""
        response = client.get("/agent-runs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        agent_types = {r["agent_type"] for r in data}
        assert agent_types == {
            "event_interpretation",
            "ai_risk",
            "final_decision_composer",
        }
        # Verify started_at DESC ordering
        started_ats = [r["started_at"] for r in data]
        assert started_ats == sorted(started_ats, reverse=True), (
            f"Expected started_at DESC order, got: {started_ats}"
        )

    def test_list_agent_runs_filter_by_decision_context(
        self, client: TestClient
    ) -> None:
        """``GET /agent-runs?decision_context_id=...`` filters correctly."""
        # First get the full list to find a decision_context_id
        list_resp = client.get("/agent-runs")
        runs = list_resp.json()
        assert len(runs) >= 1
        ctx_id = runs[0]["decision_context_id"]

        response = client.get(f"/agent-runs?decision_context_id={ctx_id}")
        assert response.status_code == 200
        filtered = response.json()
        assert len(filtered) == 3
        for run in filtered:
            assert run["decision_context_id"] == ctx_id

    def test_list_agent_runs_filter_invalid_uuid(
        self, client: TestClient
    ) -> None:
        """``GET /agent-runs?decision_context_id=...`` returns 400 for invalid UUID."""
        response = client.get("/agent-runs?decision_context_id=not-a-uuid")
        assert response.status_code == 400

    def test_list_agent_runs_filter_no_match(
        self, client: TestClient
    ) -> None:
        """``GET /agent-runs?decision_context_id=...`` returns empty for unknown UUID."""
        response = client.get(
            "/agent-runs?decision_context_id=00000000-0000-0000-0000-000000000000"
        )
        assert response.status_code == 200
        assert response.json() == []
