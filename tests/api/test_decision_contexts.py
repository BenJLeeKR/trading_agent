from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    StrategyEntity,
)
from agent_trading.domain.enums import Environment
from agent_trading.repositories.bootstrap import build_in_memory_repositories


def test_get_decision_context_exposes_signal_feature_snapshot_id() -> None:
    repos = build_in_memory_repositories()
    now = datetime.now(timezone.utc)

    client_id = uuid4()
    broker_account_id = uuid4()
    account_id = uuid4()
    strategy_id = uuid4()
    config_version_id = uuid4()
    decision_context_id = uuid4()
    signal_feature_snapshot_id = uuid4()

    repos.broker_accounts._items[broker_account_id] = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref-decision-context",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****1001",
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
        correlation_id="decision-context-api-test",
        signal_feature_snapshot_id=signal_feature_snapshot_id,
        created_at=now,
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(f"/decision-contexts/{decision_context_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["decision_context_id"] == str(decision_context_id)
    assert body["signal_feature_snapshot_id"] == str(signal_feature_snapshot_id)
