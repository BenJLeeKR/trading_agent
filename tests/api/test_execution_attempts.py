"""API-level contract tests for ``GET /execution-attempts``.

Tests:
1. ``test_list_empty`` — ``GET /execution-attempts?trade_decision_id=<uuid>`` → 빈 리스트
2. ``test_get_not_found`` — ``GET /execution-attempts/<uuid>`` → 404
3. ``test_get_by_id`` — attempt 추가 후 ``GET /execution-attempts/<id>`` → detail 반환
4. ``test_list_by_trade_decision`` — attempt 추가 후 리스트 반환
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    ExecutionAttemptEntity,
    StrategyEntity,
    TradeDecisionEntity,
)
from agent_trading.domain.enums import DecisionType, EntryStyle, Environment, OrderSide
from agent_trading.repositories.bootstrap import build_in_memory_repositories

from tests.api.conftest import empty_client  # noqa: F401


def _seed_attempts(repos, trade_decision_id: UUID, decision_context_id: UUID) -> list[UUID]:
    """Helper: seed execution attempts into in-memory repos and return their IDs."""
    now = datetime.now(timezone.utc)

    attempt1_id = uuid4()
    attempt2_id = uuid4()

    repos.execution_attempts._items[attempt1_id] = ExecutionAttemptEntity(
        execution_attempt_id=attempt1_id,
        trade_decision_id=trade_decision_id,
        decision_context_id=decision_context_id,
        status="running",
        started_at=now,
        created_at=now,
    )
    repos.execution_attempts._items[attempt2_id] = ExecutionAttemptEntity(
        execution_attempt_id=attempt2_id,
        trade_decision_id=trade_decision_id,
        decision_context_id=decision_context_id,
        status="submitted",
        stop_phase="broker_submit",
        stop_reason="order_submitted",
        started_at=now,
        completed_at=now,
        created_at=now,
    )
    return [attempt1_id, attempt2_id]


def _seed_minimal_repos(repos):
    """Seed minimal data into in-memory repos so trade_decisions and contexts exist."""
    account_id = uuid4()
    client_id = uuid4()
    broker_account_id = uuid4()
    strategy_id = uuid4()
    config_version_id = uuid4()
    decision_context_id = uuid4()
    trade_decision_id = uuid4()
    now = datetime.now(timezone.utc)

    repos.broker_accounts._items[broker_account_id] = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****0001",
    )

    repos.accounts._items[account_id] = AccountEntity(
        account_id=account_id,
        client_id=client_id,
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="test-account",
        account_masked="****1234",
        status="active",
    )

    repos.strategies._items[strategy_id] = StrategyEntity(
        strategy_id=strategy_id,
        client_id=client_id,
        strategy_code="TEST_STRAT",
        name="Test Strategy",
        asset_class="KR_STOCK",
        status="active",
    )

    repos.config_versions._items[config_version_id] = ConfigVersionEntity(
        config_version_id=config_version_id,
        client_id=client_id,
        environment=Environment.PAPER,
        version_tag="v1.0",
        config_json={},
        checksum="abc123",
    )

    repos.decision_contexts._items[decision_context_id] = DecisionContextEntity(
        decision_context_id=decision_context_id,
        account_id=account_id,
        strategy_id=strategy_id,
        config_version_id=config_version_id,
        market_timestamp=now,
        correlation_id=f"test-correlation-{uuid4()}",
    )

    repos.trade_decisions._items[trade_decision_id] = TradeDecisionEntity(
        trade_decision_id=trade_decision_id,
        decision_context_id=decision_context_id,
        decision_type=DecisionType.APPROVE,
        side=OrderSide.BUY,
        strategy_id=strategy_id,
        symbol="AAPL",
        market="NASDAQ",
        entry_style=EntryStyle.LIMIT,
        created_at=now,
    )

    return {
        "trade_decision_id": trade_decision_id,
        "decision_context_id": decision_context_id,
        "broker_account_id": broker_account_id,
        "account_id": account_id,
        "strategy_id": strategy_id,
        "config_version_id": config_version_id,
        "client_id": client_id,
    }


class TestExecutionAttemptsList:
    """``GET /execution-attempts`` — list/filter API 계약 검증."""

    def test_list_empty(self, empty_client: TestClient) -> None:
        """``GET /execution-attempts?trade_decision_id=<uuid>`` returns empty list."""
        response = empty_client.get(
            f"/execution-attempts?trade_decision_id={uuid4()}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["data"] == []

    def test_list_empty_no_filter(self, empty_client: TestClient) -> None:
        """``GET /execution-attempts`` without filter returns ``data=[]``."""
        response = empty_client.get("/execution-attempts")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["data"] == []

    def test_list_by_trade_decision(self) -> None:
        """``GET /execution-attempts?trade_decision_id=...`` returns attempts."""
        repos = build_in_memory_repositories()
        ids = _seed_minimal_repos(repos)
        attempt_ids = _seed_attempts(repos, ids["trade_decision_id"], ids["decision_context_id"])

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as tc:
            response = tc.get(
                f"/execution-attempts?trade_decision_id={ids['trade_decision_id']}"
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert len(data["data"]) == 2

        returned_ids = {item["execution_attempt_id"] for item in data["data"]}
        assert returned_ids == {str(aid) for aid in attempt_ids}

        # Verify field shape
        item = data["data"][0]
        assert "execution_attempt_id" in item
        assert "trade_decision_id" in item
        assert "decision_context_id" in item
        assert "status" in item
        assert "started_at" in item
        assert "created_at" in item

    def test_list_filter_no_match(self, empty_client: TestClient) -> None:
        """``GET /execution-attempts?trade_decision_id=...`` returns empty for unknown UUID."""
        response = empty_client.get(
            "/execution-attempts?trade_decision_id=00000000-0000-0000-0000-000000000000"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["data"] == []

    def test_list_filter_invalid_uuid(self, empty_client: TestClient) -> None:
        """``GET /execution-attempts?trade_decision_id=...`` returns 400 for invalid UUID."""
        response = empty_client.get(
            "/execution-attempts?trade_decision_id=not-a-uuid"
        )
        assert response.status_code == 400


class TestExecutionAttemptsDetail:
    """``GET /execution-attempts/{id}`` — detail endpoint."""

    def test_get_by_id(self) -> None:
        """``GET /execution-attempts/{id}`` returns a single attempt."""
        repos = build_in_memory_repositories()
        ids = _seed_minimal_repos(repos)

        # Seed one attempt
        attempt_id = uuid4()
        repos.execution_attempts._items[attempt_id] = ExecutionAttemptEntity(
            execution_attempt_id=attempt_id,
            trade_decision_id=ids["trade_decision_id"],
            decision_context_id=ids["decision_context_id"],
            status="running",
            started_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as tc:
            response = tc.get(f"/execution-attempts/{attempt_id}")
        assert response.status_code == 200
        detail = response.json()
        assert detail["execution_attempt_id"] == str(attempt_id)
        assert detail["trade_decision_id"] == str(ids["trade_decision_id"])
        assert detail["decision_context_id"] == str(ids["decision_context_id"])
        assert detail["status"] == "running"
        assert "started_at" in detail
        assert "created_at" in detail

    def test_get_not_found(self, empty_client: TestClient) -> None:
        """``GET /execution-attempts/<unknown-uuid>`` returns 404."""
        response = empty_client.get(
            "/execution-attempts/00000000-0000-0000-0000-000000000000"
        )
        assert response.status_code == 404

    def test_get_invalid_uuid(self, empty_client: TestClient) -> None:
        """``GET /execution-attempts/<invalid-uuid>`` returns 400."""
        response = empty_client.get("/execution-attempts/not-a-uuid")
        assert response.status_code == 400
