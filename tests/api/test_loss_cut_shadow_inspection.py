from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    PositionCostBasisStateEntity,
    RealizedPnlDailyAggregateEntity,
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


def _shadow_payload(*, triggered, tier, loss_pct, instrument_id=None):
    return {
        "account_id": str(uuid4()),
        "instrument_id": str(instrument_id or uuid4()),
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


def test_loss_cut_shadow_daily_splits_observations_by_kst_date() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)
    day1 = now.replace(hour=10, minute=0, second=0, microsecond=0)
    day2 = day1 + timedelta(days=1)

    decisions = [
        _make_decision(
            decision_context_id=decision_context_id,
            strategy_id=strategy_id,
            symbol="005930",
            created_at=day1,
            source_type="held_position",
            decision_type=DecisionType.HOLD,
            loss_cut_shadow=_shadow_payload(triggered=True, tier="hard", loss_pct="15"),
        ),
        _make_decision(
            decision_context_id=decision_context_id,
            strategy_id=strategy_id,
            symbol="000660",
            created_at=day1,
            source_type="held_position",
            decision_type=DecisionType.WATCH,
            loss_cut_shadow=_shadow_payload(triggered=False, tier=None, loss_pct="3"),
        ),
        _make_decision(
            decision_context_id=decision_context_id,
            strategy_id=strategy_id,
            symbol="035420",
            created_at=day2,
            source_type="held_position",
            decision_type=DecisionType.WATCH,
            loss_cut_shadow=_shadow_payload(triggered=True, tier="soft", loss_pct="8"),
        ),
    ]
    for decision in decisions:
        repos.trade_decisions._items[decision.trade_decision_id] = decision

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/daily",
            params={
                "account_id": str(account_id),
                "start_date": (day1 - timedelta(days=1)).date().isoformat(),
                "end_date": (day2 + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["days"]) == 2

    day1_kst = day1.astimezone(timezone(timedelta(hours=9))).date().isoformat()
    day2_kst = day2.astimezone(timezone(timedelta(hours=9))).date().isoformat()
    by_date = {d["trade_date"]: d for d in body["days"]}

    assert by_date[day1_kst]["total_observation_count"] == 2
    assert by_date[day1_kst]["triggered_count"] == 1
    assert by_date[day1_kst]["hard_trigger_count"] == 1
    assert by_date[day1_kst]["soft_trigger_count"] == 0
    assert by_date[day1_kst]["trigger_rate"] == 0.5

    assert by_date[day2_kst]["total_observation_count"] == 1
    assert by_date[day2_kst]["triggered_count"] == 1
    assert by_date[day2_kst]["soft_trigger_count"] == 1
    assert by_date[day2_kst]["trigger_rate"] == 1.0

    # 날짜는 오름차순으로 나와야 한다.
    assert [d["trade_date"] for d in body["days"]] == sorted(
        d["trade_date"] for d in body["days"]
    )


def test_loss_cut_shadow_daily_triggered_filter() -> None:
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
            loss_cut_shadow=_shadow_payload(triggered=False, tier=None, loss_pct="3"),
        ),
    ]
    for decision in decisions:
        repos.trade_decisions._items[decision.trade_decision_id] = decision

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/daily",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
                "triggered": "true",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["days"]) == 1
    assert body["days"][0]["total_observation_count"] == 1
    assert body["days"][0]["triggered_count"] == 1
    assert body["triggered"] is True


def test_loss_cut_shadow_daily_empty_result_returns_empty_days() -> None:
    repos = build_in_memory_repositories()
    account_id, _strategy_id, _decision_context_id, now = _seed_common(repos)

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/daily",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["days"] == []


def test_loss_cut_shadow_daily_kst_boundary_crosses_to_next_day() -> None:
    """UTC 기준으로는 같은 날이어도, KST로는 다음 날로 넘어가는 경계값을

    올바르게 처리하는지 확인한다(UTC 15:30 == KST 00:30 다음 날)."""
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, _now = _seed_common(repos)

    utc_late = datetime(2026, 8, 1, 15, 30, tzinfo=timezone.utc)
    decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=utc_late,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(triggered=True, tier="hard", loss_pct="15"),
    )
    repos.trade_decisions._items[decision.trade_decision_id] = decision

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/daily",
            params={
                "account_id": str(account_id),
                "start_date": "2026-08-02",
                "end_date": "2026-08-02",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["days"]) == 1
    assert body["days"][0]["trade_date"] == "2026-08-02"
    assert body["days"][0]["total_observation_count"] == 1

    with TestClient(app) as tc:
        response_prev_day = tc.get(
            "/trade-decisions/loss-cut-shadow/daily",
            params={
                "account_id": str(account_id),
                "start_date": "2026-08-01",
                "end_date": "2026-08-01",
            },
        )
    assert response_prev_day.json()["days"] == []


def test_loss_cut_shadow_by_instrument_joins_realized_pnl_and_cost_basis() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    instrument_id = uuid4()
    computation_run_id = uuid4()

    # 같은 종목에 대해 hard 1건 + soft 1건 발동.
    hard_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=instrument_id
        ),
    )
    soft_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now + timedelta(hours=1),
        source_type="held_position",
        decision_type=DecisionType.WATCH,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="8", instrument_id=instrument_id
        ),
    )
    # 다른 종목: triggered=False라 by-instrument에는 나타나지 않아야 한다.
    other_instrument_id = uuid4()
    not_triggered_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000660",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=False, tier=None, loss_pct="2", instrument_id=other_instrument_id
        ),
    )
    for decision in (hard_decision, soft_decision, not_triggered_decision):
        repos.trade_decisions._items[decision.trade_decision_id] = decision

    repos.realized_pnl_daily_aggregates._items[
        (account_id, instrument_id, date(2026, 7, 30))
    ] = RealizedPnlDailyAggregateEntity(
        account_id=account_id,
        instrument_id=instrument_id,
        trade_date=date(2026, 7, 30),
        realized_pnl_net_sum=Decimal("-50000"),
        sell_event_count=2,
        computation_run_id=computation_run_id,
    )
    repos.realized_pnl_daily_aggregates._items[
        (account_id, instrument_id, date(2026, 7, 31))
    ] = RealizedPnlDailyAggregateEntity(
        account_id=account_id,
        instrument_id=instrument_id,
        trade_date=date(2026, 7, 31),
        realized_pnl_net_sum=Decimal("-10000"),
        sell_event_count=1,
        computation_run_id=computation_run_id,
    )
    repos.position_cost_basis_states._items[(account_id, instrument_id)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("10"),
            average_cost=Decimal("100000"),
            recompute_required=True,
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/by-instrument",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["instrument_id"] == str(instrument_id)
    assert item["symbol"] == "005930"
    assert item["shadow_triggered_count"] == 2
    assert item["soft_trigger_count"] == 1
    assert item["hard_trigger_count"] == 1
    assert Decimal(item["realized_pnl_net_sum"]) == Decimal("-60000")
    assert item["realized_sell_event_count"] == 3
    assert item["recompute_required"] is True


def test_loss_cut_shadow_by_instrument_missing_cost_basis_state_is_null() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)
    instrument_id = uuid4()

    decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=instrument_id
        ),
    )
    repos.trade_decisions._items[decision.trade_decision_id] = decision

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/by-instrument",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert Decimal(item["realized_pnl_net_sum"]) == Decimal("0")
    assert item["realized_sell_event_count"] == 0
    assert item["recompute_required"] is None


def test_loss_cut_shadow_by_instrument_empty_when_nothing_triggered() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(triggered=False, tier=None, loss_pct="1"),
    )
    repos.trade_decisions._items[decision.trade_decision_id] = decision

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/by-instrument",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
            },
        )

    assert response.status_code == 200
    assert response.json()["items"] == []
