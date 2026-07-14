"""Inspection API endpoint tests.

Covers: ``GET /orders``, ``GET /orders/{id}``, ``GET /orders/{id}/events``,
``GET /audit-logs``, ``GET /reconciliation/runs``, ``GET /reconciliation/locks``,
``GET /accounts``, ``GET /accounts/{id}``, ``GET /instruments/{id}``,
``GET /positions``, ``GET /cash-balances``, ``GET /clients/{id}``,
``GET /orders/{id}/broker-orders``.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.api.deps import get_db, get_repos
from agent_trading.api.routes.decisions import _to_detail
from agent_trading.api.routes.orders import _safe_str
from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    ExternalEventEntity,
    InstrumentEntity,
    OrderRequestEntity,
    OrderSubmissionAttemptEntity,
    PositionSnapshotEntity,
    UniverseFreezeRunEntity,
    UniverseFreezeRunItemEntity,
)
from agent_trading.domain.enums import (
    DecisionType,
    EntryStyle,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.domain.entities import ExecutionAttemptEntity, TradeDecisionEntity
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.contracts import TradeDecisionRow
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

    def test_get_buy_block_summary(self) -> None:
        """``GET /orders/buy-block-summary`` returns BUY broker submit failure counts."""
        repos = build_in_memory_repositories()
        app = create_app(repos=repos, auth_enabled=False)
        account_id = uuid4()
        instrument_id = uuid4()
        decision_context_id = uuid4()
        strategy_id = uuid4()
        now = datetime(2026, 6, 2, 3, 0, tzinfo=timezone.utc)

        td_buy_failed = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type=DecisionType.APPROVE,
            side=OrderSide.BUY,
            strategy_id=strategy_id,
            symbol="AAPL",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=now,
            entry_price=Decimal("150"),
            quantity=Decimal("10"),
            decision_json={},
            source_type="core",
        )
        td_buy_exception = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type=DecisionType.APPROVE,
            side=OrderSide.BUY,
            strategy_id=strategy_id,
            symbol="MSFT",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=now,
            entry_price=Decimal("300"),
            quantity=Decimal("5"),
            decision_json={},
            source_type="core",
        )
        td_buy_ok = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type=DecisionType.APPROVE,
            side=OrderSide.BUY,
            strategy_id=strategy_id,
            symbol="TSLA",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=now,
            entry_price=Decimal("200"),
            quantity=Decimal("3"),
            decision_json={},
            source_type="held_position",
        )
        td_sell_failed = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type=DecisionType.APPROVE,
            side=OrderSide.SELL,
            strategy_id=strategy_id,
            symbol="GOOG",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=now,
            entry_price=Decimal("120"),
            quantity=Decimal("2"),
            decision_json={},
            source_type="market_overlay",
        )

        for td in (td_buy_failed, td_buy_exception, td_buy_ok, td_sell_failed):
            import asyncio
            asyncio.run(repos.trade_decisions.add(td))

        buy_failed_order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument_id,
            client_order_id="BUY-BLOCK-001",
            idempotency_key=f"idem-{uuid4()}",
            correlation_id="buy-block-test",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            requested_quantity=Decimal("10"),
            status=OrderStatus.SUBMITTED,
            trade_decision_id=td_buy_failed.trade_decision_id,
            decision_context_id=decision_context_id,
            requested_price=Decimal("150"),
            time_in_force=TimeInForce.DAY,
            created_at=now,
            updated_at=now,
        )
        buy_exception_order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument_id,
            client_order_id="BUY-BLOCK-002",
            idempotency_key=f"idem-{uuid4()}",
            correlation_id="buy-block-test",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            requested_quantity=Decimal("5"),
            status=OrderStatus.REJECTED,
            trade_decision_id=td_buy_exception.trade_decision_id,
            decision_context_id=decision_context_id,
            requested_price=Decimal("300"),
            time_in_force=TimeInForce.DAY,
            created_at=now,
            updated_at=now,
        )
        buy_ok_order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument_id,
            client_order_id="BUY-BLOCK-003",
            idempotency_key=f"idem-{uuid4()}",
            correlation_id="buy-block-test",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            requested_quantity=Decimal("3"),
            status=OrderStatus.FILLED,
            trade_decision_id=td_buy_ok.trade_decision_id,
            decision_context_id=decision_context_id,
            requested_price=Decimal("200"),
            time_in_force=TimeInForce.DAY,
            created_at=now,
            updated_at=now,
        )
        sell_failed_order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument_id,
            client_order_id="BUY-BLOCK-004",
            idempotency_key=f"idem-{uuid4()}",
            correlation_id="buy-block-test",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            requested_quantity=Decimal("2"),
            status=OrderStatus.REJECTED,
            trade_decision_id=td_sell_failed.trade_decision_id,
            decision_context_id=decision_context_id,
            requested_price=Decimal("120"),
            time_in_force=TimeInForce.DAY,
            created_at=now,
            updated_at=now,
        )
        asyncio.run(repos.orders.add(buy_failed_order))
        asyncio.run(repos.orders.add(buy_exception_order))
        asyncio.run(repos.orders.add(buy_ok_order))
        asyncio.run(repos.orders.add(sell_failed_order))

        asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
            attempt_id=uuid4(),
            order_request_id=buy_failed_order.order_request_id,
            attempt_number=1,
            submitted_at=now,
            broker_name="kis",
            accepted=False,
            raw_code="REJECT",
            raw_message="broker rejected",
        )))
        asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
            attempt_id=uuid4(),
            order_request_id=buy_exception_order.order_request_id,
            attempt_number=1,
            submitted_at=now,
            broker_name="kis",
            accepted=False,
            error_type="TIMEOUT",
            raw_message="timeout",
        )))
        asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
            attempt_id=uuid4(),
            order_request_id=buy_ok_order.order_request_id,
            attempt_number=1,
            submitted_at=now,
            broker_name="kis",
            accepted=True,
            broker_native_order_id="BRK-001",
        )))
        asyncio.run(repos.order_submission_attempts.add(OrderSubmissionAttemptEntity(
            attempt_id=uuid4(),
            order_request_id=sell_failed_order.order_request_id,
            attempt_number=1,
            submitted_at=now,
            broker_name="kis",
            accepted=False,
            raw_code="SELL-REJECT",
            raw_message="sell rejected",
        )))

        with TestClient(app) as client:
            response = client.get(
                "/orders/buy-block-summary",
                params={"date": date(2026, 6, 2).isoformat()},
            )
            assert response.status_code == 200, response.text
            data = response.json()
        assert data["total_buy_orders_count"] == 3
        assert data["buy_submission_attempted_count"] == 3
        assert data["blocked_count"] == 2
        assert data["rejected_count"] == 1
        assert data["exception_count"] == 1

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

    def test_get_order_daily_summary_kst_date(self) -> None:
        repos = build_in_memory_repositories()
        app = create_app(auth_token="test-token")
        app.dependency_overrides[get_repos] = lambda: repos

        account_id = uuid4()
        instrument_id = uuid4()
        now = datetime.now(timezone.utc)
        import asyncio
        from decimal import Decimal

        asyncio.run(
            repos.instruments.add(
                InstrumentEntity(
                    instrument_id=instrument_id,
                    symbol="005930",
                    market_code="KRX",
                    asset_class="stock",
                    currency="KRW",
                    name="Samsung Electronics",
                    is_active=True,
                    created_at=now,
                )
            )
        )

        def _seed_order(
            *,
            client_order_id: str,
            status: OrderStatus,
            created_at: datetime,
        ) -> None:
            asyncio.run(
                repos.orders.add(
                    OrderRequestEntity(
                        order_request_id=uuid4(),
                        account_id=account_id,
                        instrument_id=instrument_id,
                        client_order_id=client_order_id,
                        idempotency_key=f"idem-{client_order_id}",
                        correlation_id=f"corr-{client_order_id}",
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        requested_quantity=Decimal("1"),
                        requested_price=Decimal("70000"),
                        status=status,
                        time_in_force=TimeInForce.DAY,
                        created_at=created_at,
                        updated_at=created_at,
                        version=1,
                    )
                )
            )

        _seed_order(
            client_order_id="today-filled",
            status=OrderStatus.FILLED,
            created_at=datetime(2026, 6, 1, 1, 0, tzinfo=timezone.utc),  # 10:00 KST
        )
        _seed_order(
            client_order_id="today-pending",
            status=OrderStatus.PENDING_SUBMIT,
            created_at=datetime(2026, 6, 1, 2, 0, tzinfo=timezone.utc),  # 11:00 KST
        )
        _seed_order(
            client_order_id="today-submitted",
            status=OrderStatus.SUBMITTED,
            created_at=datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc),  # 12:00 KST
        )
        _seed_order(
            client_order_id="prev-day",
            status=OrderStatus.FILLED,
            created_at=datetime(2026, 5, 31, 14, 0, tzinfo=timezone.utc),  # 23:00 KST prev day
        )

        with TestClient(app) as client:
            response = client.get(
                "/orders/daily-summary",
                params={"date": date(2026, 6, 1).isoformat()},
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["date"] == "2026-06-01"
        assert data["timezone"] == "Asia/Seoul"
        assert data["total_count"] == 3
        assert data["filled_count"] == 1
        assert data["pending_submit_count"] == 1
        assert data["submitted_count"] == 1

        app.dependency_overrides.clear()

    def test_get_truth_probe_pending_summary(self) -> None:
        repos = build_in_memory_repositories()
        app = create_app(repos=repos, auth_enabled=False)
        account_id = uuid4()
        instrument_id = uuid4()
        now = datetime(2026, 6, 3, 3, 0, tzinfo=timezone.utc)  # 12:00 KST

        import asyncio

        asyncio.run(
            repos.instruments.add(
                InstrumentEntity(
                    instrument_id=instrument_id,
                    symbol="001740",
                    market_code="KRX",
                    asset_class="stock",
                    currency="KRW",
                    name="SK Networks",
                    is_active=True,
                    created_at=now,
                )
            )
        )

        pending_submitted = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument_id,
            client_order_id="TPP-001",
            idempotency_key=f"idem-{uuid4()}",
            correlation_id="truth-probe-pending-1",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("10"),
            status=OrderStatus.SUBMITTED,
            requested_price=None,
            time_in_force=TimeInForce.DAY,
            status_reason_code="truth_probe_fill_snapshot_incomplete",
            status_reason_message="snapshot_rows=2 positive_rows=0 odno=000123 Awaiting next fill sync / broker status convergence.",
            submitted_at=now,
            created_at=now,
            updated_at=now,
            version=1,
        )
        pending_partial = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument_id,
            client_order_id="TPP-002",
            idempotency_key=f"idem-{uuid4()}",
            correlation_id="truth-probe-pending-2",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("5"),
            status=OrderStatus.PARTIALLY_FILLED,
            requested_price=None,
            time_in_force=TimeInForce.DAY,
            status_reason_code="truth_probe_fill_snapshot_incomplete",
            status_reason_message="snapshot_rows=1 positive_rows=0 odno=000124 Awaiting next fill sync / broker status convergence.",
            submitted_at=now,
            created_at=now,
            updated_at=now.replace(minute=5),
            version=1,
        )
        unrelated = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument_id,
            client_order_id="TPP-003",
            idempotency_key=f"idem-{uuid4()}",
            correlation_id="truth-probe-pending-3",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("3"),
            status=OrderStatus.FILLED,
            requested_price=None,
            time_in_force=TimeInForce.DAY,
            status_reason_code="truth_probe_fill_snapshot",
            status_reason_message="filled=3 requested=3 remaining=0 source=fill_snapshot_cumulative_max",
            submitted_at=now,
            created_at=now,
            updated_at=now,
            version=1,
        )
        for order in (pending_submitted, pending_partial, unrelated):
            asyncio.run(repos.orders.add(order))

        from agent_trading.domain.entities import BrokerOrderEntity

        asyncio.run(
            repos.broker_orders.add(
                BrokerOrderEntity(
                    broker_order_id=uuid4(),
                    order_request_id=pending_partial.order_request_id,
                    broker_name="koreainvestment",
                    broker_status="submitted",
                    broker_native_order_id="000124",
                    created_at=now,
                    updated_at=now.replace(minute=6),
                )
            )
        )

        with TestClient(app) as client:
            response = client.get(
                "/orders/truth-probe-pending-summary",
                params={"date": date(2026, 6, 3).isoformat(), "limit": 10},
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["date"] == "2026-06-03"
        assert data["timezone"] == "Asia/Seoul"
        assert data["reason_code"] == "truth_probe_fill_snapshot_incomplete"
        assert data["total_count"] == 2
        assert data["status_counts"] == {
            "submitted": 1,
            "partially_filled": 1,
        }
        assert len(data["recent_orders"]) == 2
        assert data["recent_orders"][0]["order_request_id"] == str(pending_partial.order_request_id)
        assert data["recent_orders"][0]["symbol"] == "001740"
        assert data["recent_orders"][0]["broker_native_order_id"] == "000124"
        assert data["recent_orders"][1]["order_request_id"] == str(pending_submitted.order_request_id)

    def test_get_truth_probe_pending_summary_empty(self) -> None:
        repos = build_in_memory_repositories()
        app = create_app(repos=repos, auth_enabled=False)

        with TestClient(app) as client:
            response = client.get(
                "/orders/truth-probe-pending-summary",
                params={"date": date(2026, 6, 3).isoformat()},
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["date"] == "2026-06-03"
        assert data["total_count"] == 0
        assert data["status_counts"] == {}
        assert data["recent_orders"] == []


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

    def test_list_trade_decisions_includes_compliance_inspection(self, client: TestClient) -> None:
        """합본 compliance inspection view가 응답에 포함되어야 한다."""
        resp = client.get("/trade-decisions")
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) >= 1
        td = items[0]
        inspection = td.get("compliance_inspection")
        assert inspection is not None
        assert inspection["agreement_status"] == "aligned"
        assert inspection["ai_projection"]["opinion"] == "allow"
        assert inspection["ai_projection"]["check_passed"] is True
        assert inspection["ai_agent_run"]["agent_type"] == "ai_compliance"
        assert inspection["deterministic_validator"]["rule_set_version"] == "compliance_validator_v1"
        assert inspection["deterministic_validator"]["overall_passed"] is True

    async def test_list_trade_decisions_includes_decision_inspection_summary(
        self,
        client: TestClient,
        seeded_repos: RepositoryContainer,
        decision_context_id: UUID,
        strategy_id: UUID,
    ) -> None:
        td = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type=DecisionType.REDUCE,
            side=OrderSide.SELL,
            strategy_id=strategy_id,
            symbol="005930",
            market="KRX",
            entry_style=EntryStyle.LIMIT,
            created_at=datetime.now(timezone.utc),
            decision_json={
                "holding_profile_policy": {
                    "holding_profile": "core_swing",
                    "minimum_hold_until": "2026-06-30T01:00:00+00:00",
                    "earliest_reduce_at": "2026-06-30T01:10:00+00:00",
                    "earliest_reentry_at": "2026-06-30T02:00:00+00:00",
                    "metadata": {
                        "source_type": "core",
                        "time_horizon": "swing",
                    },
                },
                "expected_value_anchor": {
                    "anchor_required": True,
                    "anchor_passed": True,
                    "current_edge_after_cost_bps": "18.00",
                    "last_exit_edge_after_cost_bps": "12.00",
                    "edge_vs_last_exit_delta_bps": "6.00",
                    "reentry_edge_improved_vs_last_exit": True,
                },
            },
        )
        await seeded_repos.trade_decisions.add(td)

        resp = client.get("/trade-decisions")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        item = next(
            row for row in body["items"]
            if row["trade_decision_id"] == str(td.trade_decision_id)
        )
        inspection = item["decision_inspection"]
        assert inspection is not None
        assert inspection["holding_profile"]["holding_profile"] == "core_swing"
        assert inspection["expected_value_anchor"]["anchor_passed"] is True
        assert inspection["reverse_trade"]["blocked"] is False
        assert inspection["probe_churn"]["blocked"] is False

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

    def test_get_watch_diagnostics(self) -> None:
        """``GET /trade-decisions/watch-diagnostics`` returns WATCH/HOLD analysis."""
        mock_conn = AsyncMock()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        mock_conn.fetchrow.return_value = {
            "total_decision_count": 120,
            "hold_count": 100,
            "watch_count": 5,
            "no_material_events_watch_count": 1,
            "no_material_events_hold_count": 80,
        }
        mock_conn.fetch.side_effect = [
            [
                {
                    "source_type": "core",
                    "decision_count": 90,
                    "watch_count": 2,
                    "hold_count": 80,
                },
                {
                    "source_type": "market_overlay",
                    "decision_count": 10,
                    "watch_count": 3,
                    "hold_count": 5,
                },
            ],
            [
                {
                    "evidence_strength": "none",
                    "decision_count": 80,
                    "watch_count": 1,
                    "hold_count": 75,
                },
                {
                    "evidence_strength": "weak",
                    "decision_count": 25,
                    "watch_count": 4,
                    "hold_count": 20,
                },
            ],
            [
                {"reason_code": "price_action", "decision_count": 3},
                {"reason_code": "volume_surge", "decision_count": 2},
            ],
            [
                {
                    "trade_decision_id": uuid4(),
                    "symbol": "004000",
                    "market": "KRX",
                    "source_type": "core",
                    "decision_type": "watch",
                    "evidence_strength": "weak",
                    "no_material_events": False,
                    "detected_event_count": 1,
                    "interpreted_event_count": 1,
                    "event_bias": "neutral",
                    "rationale_summary": "watch sample",
                    "created_at": now,
                }
            ],
        ]

        async def override():
            yield mock_conn

        app = create_app(auth_enabled=False)
        app.dependency_overrides[get_db] = override

        with TestClient(app) as client:
            response = client.get(
                "/trade-decisions/watch-diagnostics?lookback_days=30&sample_limit=5"
            )
        assert response.status_code == 200
        data = response.json()
        assert data["lookback_days"] == 30
        assert data["sample_limit"] == 5
        assert data["total_decision_count"] == 120
        assert data["hold_count"] == 100
        assert data["watch_count"] == 5
        assert data["watch_rate"] == 5 / 120
        assert data["no_material_events_watch_count"] == 1
        assert data["no_material_events_hold_count"] == 80
        assert data["source_type_items"][0]["source_type"] == "core"
        assert data["source_type_items"][1]["source_type"] == "market_overlay"
        assert data["evidence_strength_items"][0]["evidence_strength"] == "none"
        assert data["top_watch_event_reason_codes"][0]["reason_code"] == "price_action"
        assert data["recent_watch_items"][0]["decision_type"] == "watch"
        assert data["recent_watch_items"][0]["evidence_strength"] == "weak"
        assert data["recent_watch_items"][0]["no_material_events"] is False
        assert data["recent_watch_items"][0]["detected_event_count"] == 1
        assert data["recent_watch_items"][0]["interpreted_event_count"] == 1

        summary_sql = mock_conn.fetchrow.await_args.args[0]
        source_sql = mock_conn.fetch.await_args_list[0].args[0]
        evidence_sql = mock_conn.fetch.await_args_list[1].args[0]
        reason_sql = mock_conn.fetch.await_args_list[2].args[0]
        sample_sql = mock_conn.fetch.await_args_list[3].args[0]
        assert "no_material_events_watch_count" in summary_sql
        assert "GROUP BY COALESCE(td.source_type, 'unknown')" in source_sql
        assert "decision_json->>'evidence_strength'" in evidence_sql
        assert "jsonb_array_elements_text" in reason_sql
        assert "IN ('watch', 'hold')" in sample_sql

        app.dependency_overrides.clear()

    def test_get_candidate_alignment_diagnostics(self) -> None:
        """``GET /trade-decisions/candidate-alignment-diagnostics`` returns override analysis."""
        mock_conn = AsyncMock()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        mock_conn.fetchrow.return_value = {
            "total_decision_count": 120,
            "candidate_tracked_count": 90,
            "override_applied_count": 25,
            "matched_count": 65,
        }
        mock_conn.fetch.side_effect = [
            [
                {"alignment_status": "matched", "decision_count": 65},
                {"alignment_status": "downgraded", "decision_count": 20},
                {"alignment_status": "suppressed", "decision_count": 5},
            ],
            [
                {"intent": "buy", "decision_count": 40},
                {"intent": "sell", "decision_count": 30},
                {"intent": "watch", "decision_count": 20},
            ],
            [
                {"intent": "buy", "decision_count": 25},
                {"intent": "sell", "decision_count": 15},
                {"intent": "no_action", "decision_count": 50},
            ],
            [
                {
                    "trade_decision_id": uuid4(),
                    "symbol": "000030",
                    "market": "KRX",
                    "source_type": "core",
                    "primary_candidate": "SELL_CANDIDATE",
                    "candidate_intent": "sell",
                    "final_decision_type": "HOLD",
                    "final_intent": "no_action",
                    "alignment_status": "downgraded",
                    "override_applied": True,
                    "rationale_summary": "risk override",
                    "created_at": now,
                }
            ],
        ]

        async def override():
            yield mock_conn

        app = create_app(auth_enabled=False)
        app.dependency_overrides[get_db] = override

        with TestClient(app) as client:
            response = client.get(
                "/trade-decisions/candidate-alignment-diagnostics?lookback_days=30&sample_limit=5"
            )
        assert response.status_code == 200
        data = response.json()
        assert data["lookback_days"] == 30
        assert data["sample_limit"] == 5
        assert data["total_decision_count"] == 120
        assert data["candidate_tracked_count"] == 90
        assert data["candidate_missing_count"] == 30
        assert data["override_applied_count"] == 25
        assert data["matched_count"] == 65
        assert data["candidate_coverage_rate"] == 90 / 120
        assert data["match_rate"] == 65 / 90
        assert data["alignment_status_items"][0]["alignment_status"] == "matched"
        assert data["candidate_intent_items"][0]["intent"] == "buy"
        assert data["final_intent_items"][2]["intent"] == "no_action"
        assert data["recent_misaligned_items"][0]["primary_candidate"] == "SELL_CANDIDATE"
        assert data["recent_misaligned_items"][0]["override_applied"] is True

        summary_sql = mock_conn.fetchrow.await_args.args[0]
        alignment_sql = mock_conn.fetch.await_args_list[0].args[0]
        candidate_sql = mock_conn.fetch.await_args_list[1].args[0]
        final_sql = mock_conn.fetch.await_args_list[2].args[0]
        sample_sql = mock_conn.fetch.await_args_list[3].args[0]
        assert "candidate_tracked_count" in summary_sql
        assert "alignment_status" in alignment_sql
        assert "candidate_intent" in candidate_sql
        assert "final_intent" in final_sql
        assert "<> 'matched'" in sample_sql

        app.dependency_overrides.clear()


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

    def test_get_instrument_mapping_consistency_summary(self) -> None:
        """``GET /instruments/mapping-consistency/summary`` returns gap summary."""
        mock_conn = AsyncMock()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        mock_conn.fetchval.return_value = 123
        mock_conn.fetch.side_effect = [
            [
                {
                    "symbol": "UNMAPPED_EVT",
                    "occurrence_count": 4,
                    "latest_observed_at": now,
                }
            ],
            [
                {
                    "symbol": "UNMAPPED_FILL",
                    "occurrence_count": 2,
                    "latest_observed_at": now,
                }
            ],
            [
                {
                    "symbol": "005940",
                    "occurrence_count": 3,
                    "latest_observed_at": now,
                }
            ],
        ]

        async def override():
            yield mock_conn

        app = create_app(auth_enabled=False)
        app.dependency_overrides[get_db] = override

        with TestClient(app) as client:
            response = client.get("/instruments/mapping-consistency/summary?lookback_days=14")
        assert response.status_code == 200
        data = response.json()
        assert data["lookback_days"] == 14
        assert data["active_instrument_count"] == 123
        assert data["has_gap"] is True
        assert data["total_unmapped_external_event_symbols"] == 1
        assert data["total_unmapped_broker_fill_symbols"] == 1
        assert data["total_unmapped_snapshot_position_symbols"] == 1
        assert data["unmapped_external_event_symbols"][0]["symbol"] == "UNMAPPED_EVT"
        assert data["unmapped_broker_fill_symbols"][0]["symbol"] == "UNMAPPED_FILL"
        assert data["unmapped_snapshot_position_symbols"][0]["symbol"] == "005940"

        fetchval_sql = mock_conn.fetchval.await_args.args[0]
        assert "FROM trading.instruments" in fetchval_sql
        first_fetch_sql = mock_conn.fetch.await_args_list[0].args[0]
        second_fetch_sql = mock_conn.fetch.await_args_list[1].args[0]
        third_fetch_sql = mock_conn.fetch.await_args_list[2].args[0]
        assert "FROM trading.external_events e" in first_fetch_sql
        assert "FROM trading.broker_fill_snapshots bfs" in second_fetch_sql
        assert "FROM trading.snapshot_sync_runs ssr" in third_fetch_sql

        app.dependency_overrides.clear()

    def test_get_trading_universe_preview(self) -> None:
        """``GET /instruments/trading-universe/preview`` returns composed universe."""
        repos = build_in_memory_repositories()
        account_id = uuid4()
        now = datetime.now(timezone.utc)

        held_inst = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="005930",
            market_code="KRX",
            asset_class="KR_STOCK",
            currency="KRW",
            name="Samsung Electronics",
            is_active=True,
        )
        event_inst = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="000660",
            market_code="KRX",
            asset_class="KR_STOCK",
            currency="KRW",
            name="SK hynix",
            is_active=True,
        )
        asyncio.run(repos.instruments.add(held_inst))
        asyncio.run(repos.instruments.add(event_inst))
        asyncio.run(
            repos.position_snapshots.add(
                PositionSnapshotEntity(
                    position_snapshot_id=uuid4(),
                    account_id=account_id,
                    instrument_id=held_inst.instrument_id,
                    quantity=Decimal("10"),
                    average_price=Decimal("50000"),
                    market_price=Decimal("51000"),
                    unrealized_pnl=Decimal("10000"),
                    source_of_truth="test",
                    snapshot_at=now,
                    created_at=now,
                )
            )
        )
        asyncio.run(
            repos.external_events.add(
                ExternalEventEntity(
                    event_id=uuid4(),
                    symbol="000660",
                    market="KRX",
                    source_name="opendart",
                    event_type="disclosure",
                    severity="high",
                    headline="High importance disclosure",
                    published_at=now,
                    ingested_at=now,
                    dedup_key_hash="evt-000660",
                )
            )
        )

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as client:
            response = client.get(
                f"/instruments/trading-universe/preview?account_id={account_id}"
            )
        assert response.status_code == 200
        data = response.json()
        assert data["account_id"] == str(account_id)
        assert data["kis_env"] is None
        assert data["total_count"] == 2
        assert data["core_cap"] == 12
        assert data["source_type_counts"] == {
            "held_position": 1,
            "event_overlay": 1,
        }
        assert data["market_overlay_diagnostics"]["enabled"] is False
        assert data["market_overlay_diagnostics"]["skipped_reason"] == "no_kis_client"
        assert data["inclusion_reason_counts"]["held_position_mandatory"] == 1
        assert data["items"][0]["symbol"] == "005930"
        assert data["items"][0]["source_type"] == "held_position"
        assert data["items"][0]["priority"] == 0
        assert data["items"][1]["symbol"] == "000660"
        assert data["items"][1]["source_type"] == "event_overlay"
        assert data["items"][1]["priority"] == 2

    def test_get_trading_universe_preview_preserves_kosdaq_market(self) -> None:
        """등록된 KOSDAQ 종목은 preview 응답에서 market=KOSDAQ로 유지돼야 한다."""
        repos = build_in_memory_repositories()
        account_id = uuid4()
        kosdaq_inst = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="090150",
            market_code="KOSDAQ",
            asset_class="KR_STOCK",
            currency="KRW",
            name="광진윈텍",
            is_active=True,
            metadata={"core_universe": True},
        )
        asyncio.run(repos.instruments.add(kosdaq_inst))

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as client:
            response = client.get(
                f"/instruments/trading-universe/preview?account_id={account_id}&max_cap=3&core_cap=3"
            )

        assert response.status_code == 200
        data = response.json()
        assert any(
            item["symbol"] == "090150" and item["market"] == "KOSDAQ"
            for item in data["items"]
        )

    def test_get_trading_universe_preview_with_market_overlay(self) -> None:
        """market overlay candidate is visible when a live/real KIS client exists."""
        repos = build_in_memory_repositories()
        account_id = uuid4()
        instrument = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="001740",
            market_code="KRX",
            asset_class="KR_STOCK",
            currency="KRW",
            name="SK Networks",
            is_active=True,
            metadata={"market_discovery_pool": True, "market_segment": "KOSPI"},
        )
        asyncio.run(repos.instruments.add(instrument))

        class _MockRestClient:
            env = "real"

            async def get_quotes_batch(self, symbols, **kwargs):
                return {
                    "001740": {
                        "stck_prpr": "5100",
                        "prdy_ctrt": "4.1",
                        "acml_tr_pbmn": "700000000000",
                        "stck_hgpr": "5200",
                        "stck_lwpr": "4900",
                        "stck_oprc": "4950",
                        "iscd_stat_cls_code": "",
                    }
                }

        class _MockBrokerAdapter:
            rest_client = _MockRestClient()

        app = create_app(
            repos=repos,
            auth_enabled=False,
            broker_adapter=_MockBrokerAdapter(),
        )
        with TestClient(app) as client:
            response = client.get(
                f"/instruments/trading-universe/preview?account_id={account_id}&market_overlay_cap=1"
            )
        assert response.status_code == 200
        data = response.json()
        assert data["kis_env"] == "real"
        assert data["total_count"] == 1
        assert data["core_cap"] == 12
        assert data["source_type_counts"]["market_overlay"] == 1
        assert data["market_overlay_diagnostics"]["enabled"] is True
        assert data["market_overlay_diagnostics"]["skipped_reason"] is None
        assert data["market_overlay_diagnostics"]["quotes_requested_count"] == 1
        assert data["market_overlay_diagnostics"]["quotes_received_count"] == 1
        assert data["market_overlay_diagnostics"]["added_count"] == 1
        assert data["market_overlay_diagnostics"]["quote_success_rate"] == 1.0
        assert data["market_overlay_diagnostics"]["filter_pass_rate"] == 1.0
        assert data["market_overlay_diagnostics"]["scored_capture_rate"] == 1.0
        assert data["items"][0]["symbol"] == "001740"
        assert data["items"][0]["source_type"] == "market_overlay"

    def test_get_trading_universe_preview_applies_core_cap(self) -> None:
        """preview API는 core_cap query를 universe composition에 반영해야 한다."""
        repos = build_in_memory_repositories()
        account_id = uuid4()
        for symbol in ("005930", "000660", "035420"):
            asyncio.run(
                repos.instruments.add(
                    InstrumentEntity(
                        instrument_id=uuid4(),
                        symbol=symbol,
                        market_code="KRX",
                        asset_class="KR_STOCK",
                        currency="KRW",
                        name=f"Test-{symbol}",
                        is_active=True,
                        metadata={"market_segment": "KOSPI"},
                    )
                )
            )

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as client:
            response = client.get(
                f"/instruments/trading-universe/preview?account_id={account_id}&max_cap=3&core_cap=1"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["core_cap"] == 1
        assert data["total_count"] == 1
        assert data["items"][0]["source_type"] == "core"

    def test_get_trading_universe_preview_includes_active_intraday_freeze(self) -> None:
        """preview 응답은 live compose와 active intraday freeze를 함께 보여줘야 한다."""
        repos = build_in_memory_repositories()
        account_id = uuid4()
        now = datetime.now(timezone.utc)

        held_inst = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="005930",
            market_code="KRX",
            asset_class="KR_STOCK",
            currency="KRW",
            name="Samsung Electronics",
            is_active=True,
            metadata={"market_segment": "KOSPI"},
        )
        event_inst = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="000660",
            market_code="KRX",
            asset_class="KR_STOCK",
            currency="KRW",
            name="SK hynix",
            is_active=True,
            metadata={"market_segment": "KOSPI"},
        )
        freeze_only_inst = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="035420",
            market_code="KRX",
            asset_class="KR_STOCK",
            currency="KRW",
            name="NAVER",
            is_active=True,
            metadata={"market_segment": "KOSPI"},
        )
        for inst in (held_inst, event_inst, freeze_only_inst):
            asyncio.run(repos.instruments.add(inst))
        asyncio.run(
            repos.position_snapshots.add(
                PositionSnapshotEntity(
                    position_snapshot_id=uuid4(),
                    account_id=account_id,
                    instrument_id=held_inst.instrument_id,
                    quantity=Decimal("10"),
                    average_price=Decimal("50000"),
                    market_price=Decimal("51000"),
                    unrealized_pnl=Decimal("10000"),
                    source_of_truth="test",
                    snapshot_at=now,
                    created_at=now,
                )
            )
        )
        asyncio.run(
            repos.external_events.add(
                ExternalEventEntity(
                    event_id=uuid4(),
                    symbol="000660",
                    market="KRX",
                    source_name="opendart",
                    event_type="disclosure",
                    severity="high",
                    headline="High importance disclosure",
                    published_at=now,
                    ingested_at=now,
                    dedup_key_hash="evt-000660-freeze",
                )
            )
        )
        business_date = now.astimezone(timezone(timedelta(hours=9))).date()
        freeze_run_id = uuid4()
        asyncio.run(
            repos.universe_freeze_runs.add(
                UniverseFreezeRunEntity(
                    universe_freeze_run_id=freeze_run_id,
                    business_date=business_date,
                    freeze_purpose="decision_loop_intraday",
                    freeze_sequence=1,
                    frozen_at=now,
                    selection_version="decision_loop_intraday.freeze.v1",
                    target_count=2,
                    status="materialized",
                )
            )
        )
        asyncio.run(
            repos.universe_freeze_run_items.add_many(
                (
                    UniverseFreezeRunItemEntity(
                        universe_freeze_run_item_id=uuid4(),
                        universe_freeze_run_id=freeze_run_id,
                        instrument_id=held_inst.instrument_id,
                        symbol="005930",
                        market_code="KRX",
                        source_type="held_position",
                        inclusion_reason="held_position_mandatory",
                        rank=1,
                        cap_bucket="held_position",
                    ),
                    UniverseFreezeRunItemEntity(
                        universe_freeze_run_item_id=uuid4(),
                        universe_freeze_run_id=freeze_run_id,
                        instrument_id=freeze_only_inst.instrument_id,
                        symbol="035420",
                        market_code="KRX",
                        source_type="core",
                        inclusion_reason="approved_core_universe",
                        rank=2,
                        cap_bucket="core",
                    ),
                )
            )
        )

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as client:
            response = client.get(
                f"/instruments/trading-universe/preview?account_id={account_id}"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["active_intraday_freeze"]["freeze_purpose"] == "decision_loop_intraday"
        assert data["active_intraday_freeze"]["target_count"] == 2
        assert data["active_intraday_freeze"]["source_type_counts"] == {
            "held_position": 1,
            "core": 1,
        }
        assert data["active_intraday_freeze_comparison"]["exact_match"] is False
        assert data["active_intraday_freeze_comparison"]["common_symbol_count"] == 2
        assert data["active_intraday_freeze_comparison"]["live_only_symbols"] == [
            "000660:KRX"
        ]
        assert data["active_intraday_freeze_comparison"]["freeze_only_symbols"] == []

    def test_get_trading_universe_freeze_summary(self) -> None:
        """``GET /instruments/trading-universe/freeze-summary``는 라이브 재계산 없이
        오늘 freeze 결과만 반환해야 한다(계좌 파라미터도 필요 없다)."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)

        held_inst = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="005930",
            market_code="KRX",
            asset_class="KR_STOCK",
            currency="KRW",
            name="Samsung Electronics",
            is_active=True,
            metadata={"market_segment": "KOSPI"},
        )
        freeze_only_inst = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="035420",
            market_code="KRX",
            asset_class="KR_STOCK",
            currency="KRW",
            name="NAVER",
            is_active=True,
            metadata={"market_segment": "KOSPI"},
        )
        for inst in (held_inst, freeze_only_inst):
            asyncio.run(repos.instruments.add(inst))

        business_date = now.astimezone(timezone(timedelta(hours=9))).date()
        freeze_run_id = uuid4()
        asyncio.run(
            repos.universe_freeze_runs.add(
                UniverseFreezeRunEntity(
                    universe_freeze_run_id=freeze_run_id,
                    business_date=business_date,
                    freeze_purpose="decision_loop_intraday",
                    freeze_sequence=1,
                    frozen_at=now,
                    selection_version="decision_loop_intraday.freeze.v1",
                    target_count=2,
                    status="materialized",
                )
            )
        )
        asyncio.run(
            repos.universe_freeze_run_items.add_many(
                (
                    UniverseFreezeRunItemEntity(
                        universe_freeze_run_item_id=uuid4(),
                        universe_freeze_run_id=freeze_run_id,
                        instrument_id=held_inst.instrument_id,
                        symbol="005930",
                        market_code="KRX",
                        source_type="held_position",
                        inclusion_reason="held_position_mandatory",
                        rank=1,
                        cap_bucket="held_position",
                    ),
                    UniverseFreezeRunItemEntity(
                        universe_freeze_run_item_id=uuid4(),
                        universe_freeze_run_id=freeze_run_id,
                        instrument_id=freeze_only_inst.instrument_id,
                        symbol="035420",
                        market_code="KRX",
                        source_type="core",
                        inclusion_reason="approved_core_universe",
                        rank=2,
                        cap_bucket="core",
                    ),
                )
            )
        )

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as client:
            response = client.get("/instruments/trading-universe/freeze-summary")

        assert response.status_code == 200
        data = response.json()
        assert data["freeze_purpose"] == "decision_loop_intraday"
        assert data["target_count"] == 2
        assert data["source_type_counts"] == {"held_position": 1, "core": 1}
        # 라이브 재계산/비교 관련 필드는 이 응답에 아예 없어야 한다(별도 엔드포인트라서).
        assert "active_intraday_freeze_comparison" not in data
        assert "market_overlay_diagnostics" not in data

    def test_get_trading_universe_freeze_summary_returns_null_when_no_freeze_run(self) -> None:
        """오늘 freeze run이 없으면 200 + null을 반환해야 한다(에러 아님)."""
        repos = build_in_memory_repositories()
        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as client:
            response = client.get("/instruments/trading-universe/freeze-summary")

        assert response.status_code == 200
        assert response.json() is None

    def test_get_trading_universe_coverage_summary(self) -> None:
        """``GET /instruments/trading-universe/coverage-summary`` returns source coverage."""
        mock_conn = AsyncMock()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        mock_conn.fetch = AsyncMock(
            side_effect=[
                [
                    {
                        "source_type": "held_position",
                        "decision_count": 10,
                        "order_count": 4,
                        "first_decision_at": now,
                        "last_decision_at": now,
                        "last_order_at": now,
                    },
                    {
                        "source_type": "market_overlay",
                        "decision_count": 5,
                        "order_count": 1,
                        "first_decision_at": now,
                        "last_decision_at": now,
                        "last_order_at": now,
                    },
                ],
                [
                    {"market": "KOSPI", "decision_count": 10},
                    {"market": "KOSDAQ", "decision_count": 5},
                ],
            ]
        )

        async def override():
            yield mock_conn

        app = create_app(auth_enabled=False)
        app.dependency_overrides[get_db] = override

        with TestClient(app) as client:
            response = client.get(
                "/instruments/trading-universe/coverage-summary?lookback_days=21"
            )
        assert response.status_code == 200
        data = response.json()
        assert data["lookback_days"] == 21
        assert data["total_decision_count"] == 15
        assert data["total_order_count"] == 5
        assert data["market_overlay_active"] is True
        assert data["market_counts"] == {"KOSPI": 10, "KOSDAQ": 5}
        assert data["items"][0]["source_type"] == "held_position"
        assert data["items"][0]["order_conversion_rate"] == 0.4
        assert data["items"][1]["source_type"] == "market_overlay"
        assert data["items"][1]["order_conversion_rate"] == 0.2

        first_fetch_sql = mock_conn.fetch.await_args_list[0].args[0]
        second_fetch_sql = mock_conn.fetch.await_args_list[1].args[0]
        assert "WITH decision_stats AS" in first_fetch_sql
        assert "FROM trading.trade_decisions td" in first_fetch_sql
        assert "FROM trading.order_requests o" in first_fetch_sql
        assert "COALESCE(td.market, 'unknown')" in second_fetch_sql

        app.dependency_overrides.clear()

    def test_get_market_overlay_funnel(self) -> None:
        """``GET /instruments/trading-universe/market-overlay-funnel`` returns recent funnel metrics."""
        mock_conn = AsyncMock()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        decision_id = uuid4()
        order_id = uuid4()
        mock_conn.fetchrow.return_value = {
            "decision_count": 3,
            "order_count": 1,
        }
        mock_conn.fetch.side_effect = [
            [
                {"decision_type": "hold", "decision_count": 2},
                {"decision_type": "approve", "decision_count": 1},
            ],
            [
                {"order_status": "submitted", "order_count": 1},
            ],
            [
                {
                    "trade_decision_id": decision_id,
                    "symbol": "001740",
                    "market": "KRX",
                    "decision_type": "approve",
                    "side": "buy",
                    "inclusion_reason": "trade_strength",
                    "rationale_summary": "Momentum confirmation",
                    "created_at": now,
                    "order_request_id": order_id,
                    "order_status": "submitted",
                    "order_created_at": now,
                }
            ],
        ]

        async def override():
            yield mock_conn

        app = create_app(auth_enabled=False)
        app.dependency_overrides[get_db] = override

        with TestClient(app) as client:
            response = client.get(
                "/instruments/trading-universe/market-overlay-funnel?lookback_days=7&sample_limit=5"
            )
        assert response.status_code == 200
        data = response.json()
        assert data["lookback_days"] == 7
        assert data["sample_limit"] == 5
        assert data["decision_count"] == 3
        assert data["order_count"] == 1
        assert data["order_conversion_rate"] == pytest.approx(1 / 3)
        assert data["decision_type_counts"] == {"hold": 2, "approve": 1}
        assert data["order_status_counts"] == {"submitted": 1}
        assert len(data["recent_items"]) == 1
        assert data["recent_items"][0]["trade_decision_id"] == str(decision_id)
        assert data["recent_items"][0]["symbol"] == "001740"
        assert data["recent_items"][0]["order_request_id"] == str(order_id)
        assert data["recent_items"][0]["order_status"] == "submitted"

        fetchrow_sql = mock_conn.fetchrow.await_args.args[0]
        assert "FROM trading.trade_decisions td" in fetchrow_sql
        first_fetch_sql = mock_conn.fetch.await_args_list[0].args[0]
        second_fetch_sql = mock_conn.fetch.await_args_list[1].args[0]
        third_fetch_sql = mock_conn.fetch.await_args_list[2].args[0]
        assert "LOWER(COALESCE(td.source_type, '')) = 'market_overlay'" in first_fetch_sql
        assert "FROM latest_orders" in second_fetch_sql
        assert "LEFT JOIN latest_orders lo" in third_fetch_sql

        app.dependency_overrides.clear()


class TestIndexMembershipStaleness:
    """UNIV-4: ``GET /instruments/index-membership/staleness`` (read-only 감시)."""

    def test_returns_not_stale_when_recent(self) -> None:
        repos = build_in_memory_repositories()
        instrument_id = uuid4()
        recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).date()
        asyncio.run(
            repos.instrument_index_memberships.sync_current_memberships(
                instrument_id,
                ["KOSPI200"],
                effective_from=recent_date,
            )
        )

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as client:
            response = client.get("/instruments/index-membership/staleness")

        assert response.status_code == 200
        data = response.json()
        assert data["latest_effective_from"] == recent_date.isoformat()
        assert data["threshold_days"] == 21
        assert data["is_stale"] is False
        assert data["age_days"] == 5

    def test_returns_stale_when_no_data(self) -> None:
        """membership 데이터가 전혀 없으면 보수적으로 stale=True를 반환한다."""
        repos = build_in_memory_repositories()

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as client:
            response = client.get("/instruments/index-membership/staleness")

        assert response.status_code == 200
        data = response.json()
        assert data["latest_effective_from"] is None
        assert data["is_stale"] is True
        assert data["age_days"] is None

    def test_respects_custom_threshold_days(self) -> None:
        repos = build_in_memory_repositories()
        instrument_id = uuid4()
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).date()
        asyncio.run(
            repos.instrument_index_memberships.sync_current_memberships(
                instrument_id,
                ["KOSPI200"],
                effective_from=old_date,
            )
        )

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as client:
            response = client.get(
                "/instruments/index-membership/staleness?threshold_days=7"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["threshold_days"] == 7
        assert data["is_stale"] is True


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

    def test_get_account_snapshots_latest_backfills_recent_orderable_amount(self) -> None:
        """Latest combined snapshot backfills recent non-null orderable_amount for UI."""
        repos = build_in_memory_repositories()
        app = create_app(repos=repos, auth_enabled=False)
        account_id = uuid4()
        now = datetime.now(timezone.utc).replace(microsecond=0)

        older = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account_id,
            currency="KRW",
            available_cash=Decimal("2114882"),
            settled_cash=Decimal("1576303"),
            unsettled_cash=Decimal("538579"),
            source_of_truth="broker",
            snapshot_at=now,
            settlement_amount=Decimal("445828"),
            orderable_amount=Decimal("443598"),
            created_at=now,
        )
        newer_at = now + timedelta(minutes=1)
        newer = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account_id,
            currency="KRW",
            available_cash=Decimal("2114882"),
            settled_cash=Decimal("1576303"),
            unsettled_cash=Decimal("538579"),
            source_of_truth="broker",
            snapshot_at=newer_at,
            settlement_amount=Decimal("445828"),
            orderable_amount=None,
            created_at=newer_at,
        )
        asyncio.run(repos.cash_balance_snapshots.add(older))
        asyncio.run(repos.cash_balance_snapshots.add(newer))

        with TestClient(app) as client:
            response = client.get(f"/account-snapshots/latest?account_id={account_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["cash_balance"] is not None
        assert data["cash_balance"]["orderable_amount"] == 443598.0
        assert data["cash_balance"]["settlement_amount"] == 445828.0


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

    def test_trade_decisions_support_buy_block_drilldown_filters(self) -> None:
        """``GET /trade-decisions`` supports date/side/source/stop_reason_prefix/has_order filters."""
        repos = build_in_memory_repositories()
        app = create_app(repos=repos, auth_enabled=False)
        decision_context_id = uuid4()
        strategy_id = uuid4()
        account_id = uuid4()
        instrument_id = uuid4()
        now = datetime(2026, 6, 2, 3, 0, tzinfo=timezone.utc)

        td_core = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type=DecisionType.APPROVE,
            side=OrderSide.BUY,
            strategy_id=strategy_id,
            symbol="AAPL",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=now,
            decision_json={},
            source_type="core",
        )
        td_overlay = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type=DecisionType.APPROVE,
            side=OrderSide.BUY,
            strategy_id=strategy_id,
            symbol="MSFT",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=now,
            decision_json={},
            source_type="market_overlay",
        )

        import asyncio
        asyncio.run(repos.trade_decisions.add(td_core))
        asyncio.run(repos.trade_decisions.add(td_overlay))
        asyncio.run(repos.execution_attempts.add(
            ExecutionAttemptEntity(
                execution_attempt_id=uuid4(),
                trade_decision_id=td_core.trade_decision_id,
                decision_context_id=decision_context_id,
                status="non_trade",
                stop_phase="scheduler_gate",
                stop_reason="general_submit_disabled_core",
                phase_trace=[],
                order_request_id=None,
                started_at=now,
                completed_at=now,
                created_at=now,
            )
        ))
        asyncio.run(repos.orders.add(
            OrderRequestEntity(
                order_request_id=uuid4(),
                account_id=account_id,
                instrument_id=instrument_id,
                client_order_id="DRILL-001",
                idempotency_key=f"idem-{uuid4()}",
                correlation_id="drilldown-test",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                requested_quantity=Decimal("1"),
                status=OrderStatus.SUBMITTED,
                trade_decision_id=td_overlay.trade_decision_id,
                decision_context_id=decision_context_id,
                time_in_force=TimeInForce.DAY,
                created_at=now,
                updated_at=now,
            )
        ))

        with TestClient(app) as client:
            resp = client.get(
                "/trade-decisions?date=2026-06-02&side=buy&source_type=core"
                "&decision_type=approve&latest_stop_reason_prefix=general_submit_disabled&has_order=false"
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()

        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["trade_decision_id"] == str(td_core.trade_decision_id)
        assert body["items"][0]["latest_stop_reason"] == "general_submit_disabled_core"

    def test_trade_decisions_date_filter_applies_to_total_count(self) -> None:
        """``GET /trade-decisions?date=...``는 KST 기준 날짜 필터를 total/items 모두에 적용한다."""
        repos = build_in_memory_repositories()
        app = create_app(repos=repos, auth_enabled=False)
        decision_context_id = uuid4()
        strategy_id = uuid4()
        same_day = datetime(2026, 6, 18, 1, 0, tzinfo=timezone.utc)
        next_day = datetime(2026, 6, 18, 16, 0, tzinfo=timezone.utc)

        td_today = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type=DecisionType.APPROVE,
            side=OrderSide.BUY,
            strategy_id=strategy_id,
            symbol="TODAY",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=same_day,
            decision_json={},
            source_type="core",
        )
        td_next_day = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type=DecisionType.APPROVE,
            side=OrderSide.SELL,
            strategy_id=strategy_id,
            symbol="NEXT",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=next_day,
            decision_json={},
            source_type="core",
        )

        import asyncio
        asyncio.run(repos.trade_decisions.add(td_today))
        asyncio.run(repos.trade_decisions.add(td_next_day))

        with TestClient(app) as client:
            resp = client.get("/trade-decisions?date=2026-06-18")
            assert resp.status_code == 200, resp.text
            body = resp.json()

        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["trade_decision_id"] == str(td_today.trade_decision_id)
        assert body["items"][0]["symbol"] == "TODAY"

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

    def test_to_detail_passes_execution_attempt_status_to_schema(self) -> None:
        """Route helper가 execution_attempt_status를 누락하지 않아야 한다.

        회귀 배경:
        ``_to_detail()``가 ``TradeDecisionRow.execution_attempt_status``를
        ``TradeDecisionDetail``에 전달하지 않으면, 스키마가 bridge fallback만
        사용해 ``order_created``로 잘못 표시할 수 있다.
        """
        now = datetime.now(timezone.utc)
        entity = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=uuid4(),
            decision_type=DecisionType.APPROVE,
            side=OrderSide.BUY,
            strategy_id=uuid4(),
            symbol="AAPL",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=now,
            rationale_summary="test",
        )
        row = TradeDecisionRow(
            entity=entity,
            order_request_id=str(uuid4()),
            order_status="PENDING_SUBMIT",
            execution_attempt_status="submitted",
        )

        detail = _to_detail(row)

        assert detail.execution_status == "submitted"

    def test_to_detail_coerces_string_phase_trace_to_list(self) -> None:
        """Read path may surface phase_trace as JSON string; route should normalize it."""
        now = datetime.now(timezone.utc)
        entity = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=uuid4(),
            decision_type=DecisionType.APPROVE,
            side=OrderSide.BUY,
            strategy_id=uuid4(),
            symbol="AAPL",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=now,
            rationale_summary="test",
        )
        row = TradeDecisionRow(
            entity=entity,
            phase_trace="[]",
        )

        detail = _to_detail(row)
        assert detail.phase_trace == []

    def test_list_trade_decisions_filters_by_execution_status(
        self,
        seeded_repos: RepositoryContainer,
        decision_context_id: UUID,
    ) -> None:
        """execution_status 필터가 submitted/rejected를 서버에서 정확히 걸러야 한다."""
        now = datetime.now(timezone.utc)

        submitted_td = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type=DecisionType.APPROVE,
            side=OrderSide.BUY,
            strategy_id=uuid4(),
            symbol="AAPL",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=now,
            rationale_summary="submitted",
        )
        rejected_td = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type=DecisionType.APPROVE,
            side=OrderSide.BUY,
            strategy_id=uuid4(),
            symbol="TSLA",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=now,
            rationale_summary="rejected",
        )
        watch_td = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=decision_context_id,
            decision_type=DecisionType.WATCH,
            side=OrderSide.BUY,
            strategy_id=uuid4(),
            symbol="MSFT",
            market="NASDAQ",
            entry_style=EntryStyle.LIMIT,
            created_at=now,
            rationale_summary="watch",
        )

        asyncio.run(seeded_repos.trade_decisions.add(submitted_td))
        asyncio.run(seeded_repos.trade_decisions.add(rejected_td))
        asyncio.run(seeded_repos.trade_decisions.add(watch_td))

        submitted_attempt = ExecutionAttemptEntity(
            execution_attempt_id=uuid4(),
            trade_decision_id=submitted_td.trade_decision_id,
            decision_context_id=decision_context_id,
            status="submitted",
            started_at=now,
            created_at=now,
            completed_at=now,
            phase_trace=[],
        )
        rejected_attempt = ExecutionAttemptEntity(
            execution_attempt_id=uuid4(),
            trade_decision_id=rejected_td.trade_decision_id,
            decision_context_id=decision_context_id,
            status="failed",
            started_at=now,
            created_at=now,
            completed_at=now,
            phase_trace=[],
        )
        seeded_repos.execution_attempts._items[submitted_attempt.execution_attempt_id] = submitted_attempt
        seeded_repos.execution_attempts._items[rejected_attempt.execution_attempt_id] = rejected_attempt

        from agent_trading.api.routes.decisions import list_trade_decisions

        submitted_resp = asyncio.run(
            list_trade_decisions(
                decision_context_id=None,
                created_date=None,
                side=None,
                source_type=None,
                decision_type=None,
                execution_status="submitted",
                latest_stop_reason=None,
                latest_stop_reason_prefix=None,
                has_order=None,
                limit=50,
                offset=0,
                repos=seeded_repos,
            )
        )
        submitted_items = submitted_resp.model_dump()["items"]
        assert any(item["trade_decision_id"] == str(submitted_td.trade_decision_id) for item in submitted_items)
        assert all(item["execution_status"] == "submitted" for item in submitted_items)

        rejected_resp = asyncio.run(
            list_trade_decisions(
                decision_context_id=None,
                created_date=None,
                side=None,
                source_type=None,
                decision_type=None,
                execution_status="rejected",
                latest_stop_reason=None,
                latest_stop_reason_prefix=None,
                has_order=None,
                limit=50,
                offset=0,
                repos=seeded_repos,
            )
        )
        rejected_items = rejected_resp.model_dump()["items"]
        assert any(item["trade_decision_id"] == str(rejected_td.trade_decision_id) for item in rejected_items)
        assert all(item["execution_status"] == "rejected" for item in rejected_items)

        non_trade_resp = asyncio.run(
            list_trade_decisions(
                decision_context_id=None,
                created_date=None,
                side=None,
                source_type=None,
                decision_type=None,
                execution_status="non_trade",
                latest_stop_reason=None,
                latest_stop_reason_prefix=None,
                has_order=None,
                limit=50,
                offset=0,
                repos=seeded_repos,
            )
        )
        non_trade_items = non_trade_resp.model_dump()["items"]
        assert any(item["trade_decision_id"] == str(watch_td.trade_decision_id) for item in non_trade_items)
        assert all(item["execution_status"] == "non_trade" for item in non_trade_items)

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
