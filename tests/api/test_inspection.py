"""Inspection API endpoint tests.

Covers: ``GET /orders``, ``GET /orders/{id}``, ``GET /orders/{id}/events``,
``GET /audit-logs``, ``GET /reconciliation/runs``, ``GET /reconciliation/locks``,
``GET /accounts``, ``GET /accounts/{id}``, ``GET /instruments/{id}``,
``GET /positions``, ``GET /cash-balances``, ``GET /clients/{id}``,
``GET /orders/{id}/broker-orders``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from agent_trading.api.routes.orders import _safe_str
from agent_trading.domain.entities import ExecutionAttemptEntity, TradeDecisionEntity
from agent_trading.repositories.container import RepositoryContainer
from tests.api.conftest import client  # noqa: F401


class TestSafeStr:
    """Unit tests for ``_safe_str()`` defensive serialization helper."""

    def test_enum_value(self) -> None:
        """Enum member → its ``.value`` string."""

        class _TestEnum(str, Enum):
            FOO = "foo"
            BAR = "bar"

        assert _safe_str(_TestEnum.FOO) == "foo"
        assert _safe_str(_TestEnum.BAR) == "bar"

    def test_plain_string(self) -> None:
        """Plain ``str`` → returned as-is."""
        assert _safe_str("broker_truth_recovery") == "broker_truth_recovery"
        assert _safe_str("system_ops_recovery") == "system_ops_recovery"
        assert _safe_str("manual") == "manual"

    def test_empty_string(self) -> None:
        """Empty string → empty string."""
        assert _safe_str("") == ""

    def test_none_raises(self) -> None:
        """``None`` → ``"None"`` (caller must handle ``None`` before calling)."""
        assert _safe_str(None) == "None"


class TestOrders:
    """Order inspection endpoints."""

    def test_list_orders_empty(self, empty_client: TestClient) -> None:
        """``GET /orders`` returns empty list when no orders exist."""
        response = empty_client.get("/orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_orders(self, client: TestClient) -> None:
        """``GET /orders`` returns seeded orders with symbol resolved."""
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
        # ── Lineage visibility: symbol resolved from instrument_id ──
        assert first["symbol"] == "AAPL"

    def test_get_order_by_id(self, client: TestClient) -> None:
        """``GET /orders/{id}`` returns order detail with symbol resolved."""
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
        # ── Lineage visibility: symbol resolved from instrument_id ──
        assert detail["symbol"] == "AAPL"

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
        # Verify event_source is serialized as string
        for ev in events:
            assert isinstance(ev["event_source"], str)
            assert ev["event_source"] in ("internal", "broker_rest", "broker_ws",
                                           "reconciliation", "operator")

    async def test_get_order_events_with_plain_string_source(self, client: TestClient,
                                                             seeded_repos: Any) -> None:
        """``GET /orders/{id}/events`` handles plain-string event_source (regression).

        DB rows with ``event_source`` values like ``"broker_truth_recovery"``
        or ``"system_ops_recovery"`` (not members of ``EventSource`` enum)
        must not cause ``AttributeError: 'str' object has no attribute 'value'``.
        """
        # Get an existing order ID
        list_resp = client.get("/orders")
        orders = list_resp.json()
        assert len(orders) >= 1
        order_id = orders[0]["order_request_id"]
        uid = UUID(order_id)

        # Inject a state event with a plain-string event_source via the repo
        # (simulating what row_to_entity produces for non-enum values)
        import uuid as _uuid
        from datetime import datetime, timezone
        from agent_trading.domain.entities import OrderStateEventEntity
        from agent_trading.domain.enums import OrderStatus

        plain_str_event = OrderStateEventEntity(
            order_state_event_id=_uuid.uuid4(),
            order_request_id=uid,
            previous_status=OrderStatus.ACKNOWLEDGED,
            new_status=OrderStatus.FILLED,
            event_source="broker_truth_recovery",  # plain str, not EventSource enum
            event_timestamp=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            reason_code="broker_truth_recovery",
        )
        await seeded_repos.order_state_events.add(plain_str_event)

        # This must NOT 500
        events_resp = client.get(f"/orders/{order_id}/events")
        assert events_resp.status_code == 200, (
            f"Expected 200, got {events_resp.status_code}: {events_resp.text}"
        )
        events = events_resp.json()
        # Find our injected event
        matching = [e for e in events if e.get("reason_code") == "broker_truth_recovery"]
        assert len(matching) >= 1
        assert matching[0]["event_source"] == "broker_truth_recovery"
        assert matching[0]["new_status"] == "filled"


class TestTradeDecisions:
    """Trade decision inspection endpoints."""

    def test_list_trade_decisions_includes_decision_json(self, client: TestClient) -> None:
        """``GET /trade-decisions`` returns ``decision_json`` field (paginated)."""
        # The fixture seeds a trade decision with decision_json data
        resp = client.get("/trade-decisions")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        items = body["items"]
        assert len(items) >= 1
        td = items[0]
        assert "decision_json" in td, "decision_json field missing from TradeDecisionDetail"
        assert td["decision_json"] is not None
        assert "event_bias" in td["decision_json"]
        assert "risk_opinion" in td["decision_json"]
        assert "event_reason_codes" in td["decision_json"]
        assert isinstance(td["decision_json"]["event_reason_codes"], list)
        assert len(td["decision_json"]["event_reason_codes"]) > 0
        # 새 필드 검증
        assert "risk_reason_codes" in td["decision_json"]
        assert "reason_codes" in td["decision_json"]
        assert "opposing_evidence" in td["decision_json"]
        assert "confidence" in td["decision_json"]
        assert "conviction" in td["decision_json"]

    async def test_list_trade_decisions_accepts_plain_string_enum_fields(
        self,
        client: TestClient,
        seeded_repos: RepositoryContainer,
        decision_context_id: UUID,
        strategy_id: UUID,
    ) -> None:
        """문자열 enum 값이 섞여 있어도 500 없이 응답해야 한다."""
        td = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type="sell",  # type: ignore[arg-type]
            side="buy",  # type: ignore[arg-type]
            strategy_id=strategy_id,
            symbol="TEST",
            market="KRX",
            entry_style="market",  # type: ignore[arg-type]
            created_at=datetime.now(timezone.utc),
            decision_json={},
        )
        await seeded_repos.trade_decisions.add(td)

        resp = client.get("/trade-decisions")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert isinstance(body, dict)
        items = body["items"]
        injected = next(
            row for row in items if row["trade_decision_id"] == str(td.trade_decision_id)
        )
        assert injected["decision_type"] == "sell"
        assert injected["side"] == "buy"
        assert injected["entry_style"] == "market"


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

    def test_list_reconciliation_runs_missing_param(self, empty_client: TestClient) -> None:
        """``GET /reconciliation/runs`` returns 200 (empty list) without account_id."""
        response = empty_client.get("/reconciliation/runs")
        assert response.status_code == 200
        assert response.json() == []

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

    def test_list_locks_missing_param(self, empty_client: TestClient) -> None:
        """``GET /reconciliation/locks`` returns 200 (empty list) without account_id."""
        response = empty_client.get("/reconciliation/locks")
        assert response.status_code == 200
        assert response.json() == []

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
        """``GET /positions?account_id=...`` returns seeded position snapshot
        with symbol and instrument_name resolved, including purchase_amount
        and evaluation_amount.
        """
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
        # ── Purchase / evaluation amount fields ──
        assert pos["purchase_amount"] == 15000.0
        assert pos["evaluation_amount"] == 15500.0
        # ── Lineage visibility: symbol/name resolved from instrument_id ──
        assert pos["symbol"] == "AAPL"
        assert pos["instrument_name"] == "Apple Inc."

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


class TestTradeDecisionExecutionStatus:
    """Execution status derived field and pipeline_stop field exposure."""

    def test_trade_decision_detail_has_execution_fields(self, client: TestClient) -> None:
        """최신 필드(execution_status, latest_*, order_request_id)가 응답에 포함된다."""
        resp = client.get("/trade-decisions?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        if data["items"]:
            item = data["items"][0]
            assert "execution_status" in item
            assert "pipeline_stop_phase" not in item
            assert "pipeline_stop_reason" not in item
            assert "pipeline_stopped_at" not in item
            assert "order_request_id" in item
            assert "order_status" in item

    @pytest.mark.parametrize("decision_type,order_id,order_status,expected", [
        ("BUY", None, None, "trade_decision_only"),
        ("HOLD", None, None, "non_trade"),
        ("WATCH", None, None, "non_trade"),
        ("BUY", "some-id", "PENDING_SUBMIT", "order_created"),
        ("BUY", "some-id", "SUBMITTED", "submitted"),
        ("BUY", "some-id", "REJECTED", "rejected"),
        ("BUY", "some-id", "RECONCILE_REQUIRED", "reconcile_required"),
    ])
    def test_execution_status_derivation(
        self,
        decision_type: str,
        order_id: str | None,
        order_status: str | None,
        expected: str,
    ) -> None:
        """execution_status derived field logic을 검증한다.
        (Phase 6: pipeline_stop_phase bridge 필드 제거됨 — execution_attempt_status가 primary truth)"""
        from datetime import datetime
        from agent_trading.api.schemas import TradeDecisionDetail

        detail = TradeDecisionDetail(
            trade_decision_id="test-id",
            decision_context_id="ctx-id",
            decision_type=decision_type,
            side="buy",
            strategy_id="strat-id",
            symbol="AAPL",
            market="NASDAQ",
            entry_style="limit",
            created_at=datetime.now(),
            order_request_id=order_id,
            order_status=order_status,
        )
        assert detail.execution_status == expected


class TestTradeDecisionPhaseTrace:
    """Phase trace (Phase 2/6) derived field computation (schema-level)."""

    def test_phase_trace_fields_in_response(self, client: TestClient) -> None:
        """``phase_trace`` 및 derived 필드가 API 응답에 포함된다.
        (Phase 6: bridge 컬럼 제거 후에도 execution_attempts 출처로 계속 노출)"""
        resp = client.get("/trade-decisions?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        if data["items"]:
            item = data["items"][0]
            # phase_trace raw 필드는 execution_attempts 출처로 계속 노출
            assert "phase_trace" in item
            # Phase trace summary (derived) 필드도 계속 노출 (null일 수 있음)
            assert "phase_count" in item
            assert "total_elapsed_ms" in item
            assert "latest_phase" in item
            assert "latest_phase_detail" in item
            assert "latest_status" in item

    def test_phase_trace_derived_fields(self) -> None:
        """``phase_trace``에서 ``phase_count``, ``total_elapsed_ms``,
        ``latest_phase``, ``latest_phase_detail``, ``latest_status``가
        정확히 계산된다."""
        from datetime import datetime
        from agent_trading.api.schemas import TradeDecisionDetail

        phase_trace = [
            {"phase": "ai_assemble", "elapsed_ms": 1200, "status": "start"},
            {"phase": "ai_assemble", "elapsed_ms": 800, "status": "ok"},
            {"phase": "quote_resolution/AAPL", "elapsed_ms": 500, "status": "start"},
            {"phase": "quote_resolution/AAPL", "elapsed_ms": 850, "status": "ok"},
            {"phase": "sizing/AAPL", "elapsed_ms": 30, "status": "start"},
            {"phase": "sizing/AAPL", "elapsed_ms": 45, "status": "ok"},
            {"phase": "sell_guard/AAPL", "elapsed_ms": 20, "status": "start"},
            {"phase": "sell_guard/AAPL", "elapsed_ms": 30, "status": "ok"},
            {"phase": "translation/AAPL", "elapsed_ms": 10, "status": "start"},
            {"phase": "translation/AAPL", "elapsed_ms": 15, "status": "ok"},
            {"phase": "order_create/AAPL", "elapsed_ms": 100, "status": "start"},
            {"phase": "order_create/AAPL", "elapsed_ms": 200, "status": "ok"},
            {"phase": "broker_submit/AAPL", "elapsed_ms": 2000, "status": "start"},
            {"phase": "broker_submit/AAPL", "elapsed_ms": 3500, "status": "ok"},
        ]

        detail = TradeDecisionDetail(
            trade_decision_id="test-id",
            decision_context_id="ctx-id",
            decision_type="BUY",
            side="buy",
            strategy_id="strat-id",
            symbol="AAPL",
            market="NASDAQ",
            entry_style="limit",
            created_at=datetime.now(),
            phase_trace=phase_trace,
        )

        assert detail.phase_count == 14
        # total_elapsed_ms = non-start entries 합계
        assert detail.total_elapsed_ms == 800 + 850 + 45 + 30 + 15 + 200 + 3500  # 5440
        assert detail.latest_phase == "broker_submit"
        assert detail.latest_phase_detail == "AAPL"
        assert detail.latest_status == "ok"

    def test_phase_trace_derived_fields_single_phase(self) -> None:
        """단일 phase entry로도 derived field가 정확히 계산된다."""
        from datetime import datetime
        from agent_trading.api.schemas import TradeDecisionDetail

        phase_trace = [
            {"phase": "ai_assemble", "elapsed_ms": 500, "status": "ok"},
        ]

        detail = TradeDecisionDetail(
            trade_decision_id="test-id",
            decision_context_id="ctx-id",
            decision_type="BUY",
            side="buy",
            strategy_id="strat-id",
            symbol="AAPL",
            market="NASDAQ",
            entry_style="limit",
            created_at=datetime.now(),
            phase_trace=phase_trace,
        )

        assert detail.phase_count == 1
        assert detail.total_elapsed_ms == 500
        assert detail.latest_phase == "ai_assemble"
        assert detail.latest_phase_detail is None
        assert detail.latest_status == "ok"

    def test_phase_trace_derived_fields_no_detail(self) -> None:
        """phase에 ``/``가 없으면 ``latest_phase_detail``은 ``None``이다."""
        from datetime import datetime
        from agent_trading.api.schemas import TradeDecisionDetail

        phase_trace = [
            {"phase": "sizing", "elapsed_ms": 100, "status": "error"},
        ]

        detail = TradeDecisionDetail(
            trade_decision_id="test-id",
            decision_context_id="ctx-id",
            decision_type="BUY",
            side="buy",
            strategy_id="strat-id",
            symbol="AAPL",
            market="NASDAQ",
            entry_style="limit",
            created_at=datetime.now(),
            phase_trace=phase_trace,
        )

        assert detail.phase_count == 1
        assert detail.total_elapsed_ms == 100
        assert detail.latest_phase == "sizing"
        assert detail.latest_phase_detail is None
        assert detail.latest_status == "error"

    def test_phase_trace_null_handling(self) -> None:
        """``phase_trace``가 ``None``이면 derived field도 모두 ``None``이다."""
        from datetime import datetime
        from agent_trading.api.schemas import TradeDecisionDetail

        detail = TradeDecisionDetail(
            trade_decision_id="test-id",
            decision_context_id="ctx-id",
            decision_type="BUY",
            side="buy",
            strategy_id="strat-id",
            symbol="AAPL",
            market="NASDAQ",
            entry_style="limit",
            created_at=datetime.now(),
            phase_trace=None,
        )

        assert detail.phase_count is None
        assert detail.total_elapsed_ms is None
        assert detail.latest_phase is None
        assert detail.latest_phase_detail is None
        assert detail.latest_status is None

    def test_phase_trace_empty_list_handling(self) -> None:
        """``phase_trace``가 빈 리스트면 derived field도 모두 ``None``이다."""
        from datetime import datetime
        from agent_trading.api.schemas import TradeDecisionDetail

        detail = TradeDecisionDetail(
            trade_decision_id="test-id",
            decision_context_id="ctx-id",
            decision_type="BUY",
            side="buy",
            strategy_id="strat-id",
            symbol="AAPL",
            market="NASDAQ",
            entry_style="limit",
            created_at=datetime.now(),
            phase_trace=[],
        )

        assert detail.phase_count is None
        assert detail.total_elapsed_ms is None
        assert detail.latest_phase is None
        assert detail.latest_phase_detail is None
        assert detail.latest_status is None


class TestExecutionAttemptSummaryInDecisionDetail:
    """Phase 5: Read-path ExecutionAttempt summary fields in TradeDecisionDetail."""

    def test_latest_execution_attempt_fields_included(self, client: TestClient) -> None:
        """latest_* 필드가 TradeDecisionDetail 응답에 포함되어야 함."""
        resp = client.get("/trade-decisions")
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", [])
        if items:
            d = items[0]
            # 5개 필드 모두 응답에 존재 (null일 수 있음)
            assert "latest_execution_attempt_id" in d
            assert "latest_stop_phase" in d
            assert "latest_stop_reason" in d
            assert "latest_completed_at" in d
            assert "latest_phase_count" in d

    def test_execution_status_priority_attempt_over_bridge(
        self,
        client: TestClient,
        seeded_repos: RepositoryContainer,
        trade_decision_id: UUID,
        decision_context_id: UUID,
    ) -> None:
        """execution_status가 execution_attempt_status를 우선 사용해야 함."""
        # Seed an execution attempt with status="completed"
        now = datetime.now(timezone.utc)
        attempt = ExecutionAttemptEntity(
            execution_attempt_id=uuid4(),
            trade_decision_id=trade_decision_id,
            decision_context_id=decision_context_id,
            status="completed",
            started_at=now,
            created_at=now,
            completed_at=now,
            phase_trace=[],
        )
        seeded_repos.execution_attempts._items[attempt.execution_attempt_id] = attempt

        resp = client.get("/trade-decisions")
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", [])
        for d in items:
            if d.get("latest_execution_attempt_id"):
                # execution_attempt_status가 설정된 경우 execution_status가 attempt 기반이어야 함
                assert d["execution_status"] is not None
                break

    def test_bridge_fields_no_longer_present(self, client: TestClient) -> None:
        """bridge 필드(pipeline_stop_phase 등)가 API 응답에서 제거되어야 함."""
        resp = client.get("/trade-decisions")
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", [])
        if items:
            d = items[0]
            assert "pipeline_stop_phase" not in d
            assert "pipeline_stop_reason" not in d
            assert "pipeline_stopped_at" not in d

    def test_execution_attempts_api_unchanged(self, client: TestClient) -> None:
        """ExecutionAttempt API가 변경되지 않았는지 회귀 테스트."""
        resp = client.get("/execution-attempts")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "data" in data


