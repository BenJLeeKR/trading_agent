"""API-level contract tests for ``GET /performance-trigger-attribution``."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.api.deps import get_db


class TestPerformanceTriggerAttribution:
    """`GET /performance-trigger-attribution` 응답/검증 계약."""

    def test_returns_trigger_alignment_execution_summary(self) -> None:
        mock_conn = AsyncMock()
        account_id = str(uuid4())
        mock_conn.fetchrow.return_value = {
            "total_decision_count": 120,
            "tracked_decision_count": 90,
            "actionable_decision_count": 80,
            "ordered_decision_count": 44,
            "filled_decision_count": 18,
        }
        mock_conn.fetch.side_effect = [
            [
                {
                    "bucket": "matched",
                    "decision_count": 50,
                    "actionable_decision_count": 45,
                    "order_count": 30,
                    "filled_order_count": 15,
                },
                {
                    "bucket": "downgraded",
                    "decision_count": 25,
                    "actionable_decision_count": 25,
                    "order_count": 10,
                    "filled_order_count": 2,
                },
            ],
            [
                {
                    "bucket": "buy",
                    "decision_count": 40,
                    "actionable_decision_count": 40,
                    "order_count": 28,
                    "filled_order_count": 12,
                },
                {
                    "bucket": "sell",
                    "decision_count": 20,
                    "actionable_decision_count": 20,
                    "order_count": 8,
                    "filled_order_count": 4,
                },
            ],
        ]

        async def override():
            yield mock_conn

        app = create_app(auth_enabled=False)
        app.dependency_overrides[get_db] = override

        with TestClient(app) as client:
            response = client.get(
                "/performance-trigger-attribution",
                params={"account_id": account_id, "lookback_days": 30},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["account_id"] == account_id
        assert data["lookback_days"] == 30
        assert data["total_decision_count"] == 120
        assert data["tracked_decision_count"] == 90
        assert data["actionable_decision_count"] == 80
        assert data["ordered_decision_count"] == 44
        assert data["filled_decision_count"] == 18
        assert data["decision_to_order_rate"] == 44 / 80
        assert data["decision_to_fill_rate"] == 18 / 80
        assert data["alignment_items"][0]["bucket"] == "matched"
        assert data["alignment_items"][0]["order_conversion_rate"] == 30 / 45
        assert data["candidate_intent_items"][0]["bucket"] == "buy"
        assert data["candidate_intent_items"][1]["fill_conversion_rate"] == 4 / 20

        summary_sql = mock_conn.fetchrow.await_args.args[0]
        alignment_sql = mock_conn.fetch.await_args_list[0].args[0]
        candidate_sql = mock_conn.fetch.await_args_list[1].args[0]
        assert "decision_contexts dc" in summary_sql
        assert "alignment_status" in alignment_sql
        assert "candidate_intent" in candidate_sql

        app.dependency_overrides.clear()

    def test_invalid_account_id_returns_400(self) -> None:
        app = create_app(auth_enabled=False)
        dummy_conn = AsyncMock()

        async def override():
            yield dummy_conn

        app.dependency_overrides[get_db] = override
        with TestClient(app) as client:
            response = client.get(
                "/performance-trigger-attribution",
                params={"account_id": "not-a-uuid", "lookback_days": 14},
            )
        assert response.status_code == 400
        assert "Invalid account_id UUID" in response.json()["detail"]
        app.dependency_overrides.clear()


class TestPerformanceHoldingProfileAttribution:
    """`GET /performance-holding-profile-attribution` 응답/검증 계약."""

    def test_returns_holding_profile_and_guardrail_attribution_summary(self) -> None:
        mock_conn = AsyncMock()
        account_id = str(uuid4())
        mock_conn.fetchrow.side_effect = [
            {
                "total_decision_count": 120,
                "reverse_trade_blocked_count": 12,
                "probe_churn_blocked_count": 7,
                "holding_profile_guard_blocked_count": 5,
            },
            {
                "realized_opposite_fill_churn_count": 9,
                "realized_opposite_fill_non_churn_count": 4,
            },
        ]
        mock_conn.fetch.side_effect = [
            [
                {
                    "holding_profile": "core_swing",
                    "decision_count": 60,
                    "actionable_decision_count": 45,
                    "ordered_decision_count": 20,
                    "filled_decision_count": 11,
                    "avg_edge_after_cost_bps": 22.5,
                    "closed_trade_count": 6,
                    "avg_holding_minutes": 1500.0,
                    "avg_realized_return_pct": 3.2,
                },
                {
                    "holding_profile": "event_probe",
                    "decision_count": 25,
                    "actionable_decision_count": 12,
                    "ordered_decision_count": 4,
                    "filled_decision_count": 2,
                    "avg_edge_after_cost_bps": 38.0,
                    "closed_trade_count": 1,
                    "avg_holding_minutes": 40.0,
                    "avg_realized_return_pct": 0.8,
                },
            ],
            [
                {
                    "guardrail_family": "reverse_trade",
                    "reason_code": "reverse_trade_same_signal_feature_snapshot",
                    "decision_count": 8,
                },
                {
                    "guardrail_family": "probe_churn",
                    "reason_code": "probe_churn_single_share_blocked",
                    "decision_count": 5,
                },
            ],
            [
                {
                    "edge_bucket": "20_35",
                    "closed_trade_count": 4,
                    "avg_holding_minutes": 900.0,
                    "avg_realized_return_pct": 2.5,
                },
                {
                    "edge_bucket": "ge_35",
                    "closed_trade_count": 2,
                    "avg_holding_minutes": 120.0,
                    "avg_realized_return_pct": 0.9,
                },
            ],
        ]

        async def override():
            yield mock_conn

        app = create_app(auth_enabled=False)
        app.dependency_overrides[get_db] = override

        with TestClient(app) as client:
            response = client.get(
                "/performance-holding-profile-attribution",
                params={
                    "account_id": account_id,
                    "lookback_days": 30,
                    "churn_window_hours": 24,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["account_id"] == account_id
        assert data["lookback_days"] == 30
        assert data["churn_window_hours"] == 24
        assert data["total_decision_count"] == 120
        assert data["reverse_trade_blocked_count"] == 12
        assert data["probe_churn_blocked_count"] == 7
        assert data["holding_profile_guard_blocked_count"] == 5
        assert data["realized_opposite_fill_churn_count"] == 9
        assert data["realized_opposite_fill_non_churn_count"] == 4
        assert data["holding_profile_items"][0]["holding_profile"] == "core_swing"
        assert data["holding_profile_items"][0]["avg_edge_after_cost_bps"] == 22.5
        assert data["guardrail_items"][0]["guardrail_family"] == "reverse_trade"
        assert data["edge_outcome_items"][1]["edge_bucket"] == "ge_35"

        summary_sql = mock_conn.fetchrow.await_args_list[0].args[0]
        holding_sql = mock_conn.fetch.await_args_list[0].args[0]
        guardrail_sql = mock_conn.fetch.await_args_list[1].args[0]
        edge_sql = mock_conn.fetch.await_args_list[2].args[0]
        churn_sql = mock_conn.fetchrow.await_args_list[1].args[0]
        assert "holding_profile_policy" in holding_sql
        assert "reverse_trade_same_signal_feature_snapshot" in summary_sql
        assert "guardrail_family" in guardrail_sql
        assert "edge_bucket" in edge_sql
        assert "realized_opposite_fill_churn_count" in churn_sql

        app.dependency_overrides.clear()

    def test_invalid_account_id_returns_400(self) -> None:
        app = create_app(auth_enabled=False)
        dummy_conn = AsyncMock()

        async def override():
            yield dummy_conn

        app.dependency_overrides[get_db] = override
        with TestClient(app) as client:
            response = client.get(
                "/performance-holding-profile-attribution",
                params={"account_id": "not-a-uuid", "lookback_days": 14},
            )
        assert response.status_code == 400
        assert "Invalid account_id UUID" in response.json()["detail"]
        app.dependency_overrides.clear()
