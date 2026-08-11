from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _seed_common(repos):
    now = datetime.now(timezone.utc)
    client_id = uuid4()
    broker_account_id = uuid4()
    account_id = uuid4()
    strategy_id = uuid4()
    config_version_id = uuid4()
    decision_context_id = uuid4()

    repos.broker_accounts._items[broker_account_id] = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref-loss-cut-shadow",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****3002",
    )
    repos.accounts._items[account_id] = AccountEntity(
        account_id=account_id,
        client_id=client_id,
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="loss-cut-shadow-account",
        account_masked="****1234",
        status="active",
    )
    repos.strategies._items[strategy_id] = StrategyEntity(
        strategy_id=strategy_id,
        client_id=client_id,
        strategy_code="LOSS_CUT_SHADOW",
        name="Loss Cut Shadow Strategy",
        asset_class="KR_STOCK",
        status="active",
    )
    repos.config_versions._items[config_version_id] = ConfigVersionEntity(
        config_version_id=config_version_id,
        client_id=client_id,
        environment=Environment.PAPER,
        version_tag="v1.0",
        config_json={},
        checksum="loss-cut-shadow-abc123",
    )
    repos.decision_contexts._items[decision_context_id] = DecisionContextEntity(
        decision_context_id=decision_context_id,
        account_id=account_id,
        strategy_id=strategy_id,
        config_version_id=config_version_id,
        market_timestamp=now,
        correlation_id="loss-cut-shadow-correlation",
        created_at=now,
    )
    return account_id, strategy_id, decision_context_id, now


def _make_decision(
    *,
    decision_context_id,
    strategy_id,
    symbol,
    created_at,
    source_type,
    decision_type,
    loss_cut_shadow,
) -> TradeDecisionEntity:
    return TradeDecisionEntity(
        trade_decision_id=uuid4(),
        decision_context_id=decision_context_id,
        decision_type=decision_type,
        side=OrderSide.SELL,
        strategy_id=strategy_id,
        symbol=symbol,
        market="KRX",
        entry_style=EntryStyle.LIMIT,
        created_at=created_at,
        source_type=source_type,
        decision_json={"loss_cut_shadow": loss_cut_shadow} if loss_cut_shadow else {},
    )


def _shadow_payload(*, triggered, tier, loss_pct):
    return {
        "account_id": str(uuid4()),
        "instrument_id": str(uuid4()),
        "source_type": "held_position",
        "average_price": "100000",
        "market_price": "85000",
        "loss_pct": loss_pct,
        "triggered": triggered,
        "tier": tier,
        "skipped_reason": None,
        "shadow_only": True,
        "decision_unaffected_by_shadow": True,
    }


def test_loss_cut_shadow_summary_counts_by_tier_and_decision_type() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    decisions = [
        _make_decision(
            decision_context_id=decision_context_id,
            strategy_id=strategy_id,
            symbol="005930",
            created_at=now,
            source_type="held_position",
            decision_type=DecisionType.HOLD,
            loss_cut_shadow=_shadow_payload(triggered=True, tier="hard", loss_pct="15"),
        ),
        _make_decision(
            decision_context_id=decision_context_id,
            strategy_id=strategy_id,
            symbol="000660",
            created_at=now,
            source_type="held_position",
            decision_type=DecisionType.WATCH,
            loss_cut_shadow=_shadow_payload(triggered=True, tier="soft", loss_pct="8"),
        ),
        _make_decision(
            decision_context_id=decision_context_id,
            strategy_id=strategy_id,
            symbol="035420",
            created_at=now,
            source_type="core",
            decision_type=DecisionType.HOLD,
            loss_cut_shadow=_shadow_payload(triggered=False, tier=None, loss_pct="2"),
        ),
        # loss_cut_shadow가 없는 TD는 집계에서 제외돼야 한다.
        _make_decision(
            decision_context_id=decision_context_id,
            strategy_id=strategy_id,
            symbol="005380",
            created_at=now,
            source_type="core",
            decision_type=DecisionType.APPROVE,
            loss_cut_shadow=None,
        ),
    ]
    for decision in decisions:
        repos.trade_decisions._items[decision.trade_decision_id] = decision

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/summary",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_observation_count"] == 3
    assert body["triggered_count"] == 2
    assert body["soft_trigger_count"] == 1
    assert body["hard_trigger_count"] == 1
    assert body["shadow_only_count"] == 3
    assert body["trigger_rate"] == 2 / 3
    source_counts = {item["key"]: item["count"] for item in body["source_type_counts"]}
    assert source_counts == {"held_position": 2, "core": 1}
    decision_counts = {
        item["key"]: item["count"] for item in body["actual_decision_type_counts"]
    }
    assert decision_counts["hold"] == 2
    assert decision_counts["watch"] == 1


def test_loss_cut_shadow_summary_empty_result_has_null_trigger_rate() -> None:
    repos = build_in_memory_repositories()
    account_id, _strategy_id, _decision_context_id, now = _seed_common(repos)

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/summary",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_observation_count"] == 0
    assert body["trigger_rate"] is None


def test_loss_cut_shadow_samples_filters_by_tier_and_limits_fields() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    hard_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(triggered=True, tier="hard", loss_pct="15"),
    )
    soft_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000660",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.WATCH,
        loss_cut_shadow=_shadow_payload(triggered=True, tier="soft", loss_pct="8"),
    )
    for decision in (hard_decision, soft_decision):
        repos.trade_decisions._items[decision.trade_decision_id] = decision

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/samples",
            params={"account_id": str(account_id), "tier": "hard"},
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["trade_decision_id"] == str(hard_decision.trade_decision_id)
    assert item["tier"] == "hard"
    assert item["triggered"] is True
    assert item["symbol"] == "005930"
    assert item["source_type"] == "held_position"
    assert item["actual_decision_type"] == "hold"
    assert item["shadow_only"] is True
