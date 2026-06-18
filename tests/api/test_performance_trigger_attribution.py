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
