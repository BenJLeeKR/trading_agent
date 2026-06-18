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
    TradeDecisionEntity,
)
from agent_trading.domain.enums import DecisionType, EntryStyle, Environment, OrderSide
from agent_trading.repositories.bootstrap import build_in_memory_repositories


def test_list_trade_decisions_exposes_signal_feature_snapshot_id() -> None:
    repos = build_in_memory_repositories()
    now = datetime.now(timezone.utc)

    client_id = uuid4()
    broker_account_id = uuid4()
    account_id = uuid4()
    strategy_id = uuid4()
    config_version_id = uuid4()
    decision_context_id = uuid4()
    trade_decision_id = uuid4()
    signal_feature_snapshot_id = uuid4()

    repos.broker_accounts._items[broker_account_id] = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref-td-anchor",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****3001",
    )
    repos.accounts._items[account_id] = AccountEntity(
        account_id=account_id,
        client_id=client_id,
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="td-anchor-account",
        account_masked="****9876",
        status="active",
    )
    repos.strategies._items[strategy_id] = StrategyEntity(
        strategy_id=strategy_id,
        client_id=client_id,
        strategy_code="TD_ANCHOR",
        name="Trade Decision Anchor Strategy",
        asset_class="KR_STOCK",
        status="active",
    )
    repos.config_versions._items[config_version_id] = ConfigVersionEntity(
        config_version_id=config_version_id,
        client_id=client_id,
        environment=Environment.PAPER,
        version_tag="v1.0",
        config_json={},
        checksum="td-anchor-abc123",
    )
    repos.decision_contexts._items[decision_context_id] = DecisionContextEntity(
        decision_context_id=decision_context_id,
        account_id=account_id,
        strategy_id=strategy_id,
        config_version_id=config_version_id,
        market_timestamp=now,
        correlation_id="td-anchor-correlation",
        signal_feature_snapshot_id=signal_feature_snapshot_id,
        created_at=now,
    )
    repos.trade_decisions._items[trade_decision_id] = TradeDecisionEntity(
        trade_decision_id=trade_decision_id,
        decision_context_id=decision_context_id,
        decision_type=DecisionType.BUY,
        side=OrderSide.BUY,
        strategy_id=strategy_id,
        symbol="005930",
        market="KRX",
        entry_style=EntryStyle.LIMIT,
        created_at=now,
        decision_json={},
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get("/trade-decisions?limit=10&offset=0")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["trade_decision_id"] == str(trade_decision_id)
    assert body["items"][0]["signal_feature_snapshot_id"] == str(signal_feature_snapshot_id)
