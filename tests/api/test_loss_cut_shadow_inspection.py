from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    PositionCostBasisStateEntity,
    RealizedPnlDailyAggregateEntity,
    RealizedPnlEventEntity,
    StrategyEntity,
    TradeDecisionEntity,
)
from agent_trading.domain.enums import (
    DecisionType,
    EntryStyle,
    Environment,
    OrderSide,
    RealizedPnlFeeTaxSource,
)
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


def _make_realized_pnl_event(
    *,
    account_id,
    instrument_id,
    fill_timestamp,
    realized_pnl_net,
) -> RealizedPnlEventEntity:
    return RealizedPnlEventEntity(
        realized_pnl_event_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        fill_event_id=uuid4(),
        broker_order_id=uuid4(),
        order_request_id=uuid4(),
        sell_quantity=Decimal("5"),
        sell_price=Decimal("90000"),
        avg_cost_basis_before=Decimal("100000"),
        fee=Decimal("100"),
        tax=Decimal("50"),
        fee_tax_source=RealizedPnlFeeTaxSource.REPORTED,
        realized_pnl_gross=realized_pnl_net + Decimal("150"),
        realized_pnl_net=realized_pnl_net,
        position_quantity_after=Decimal("5"),
        computation_run_id=uuid4(),
        fill_timestamp=fill_timestamp,
    )


async def test_loss_cut_shadow_sample_timeline_lists_events_after_shadow() -> None:
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

    before_event = await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=instrument_id,
            fill_timestamp=now - timedelta(hours=1),
            realized_pnl_net=Decimal("-1000"),
        )
    )
    after_event_1 = await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=instrument_id,
            fill_timestamp=now + timedelta(hours=1),
            realized_pnl_net=Decimal("-30000"),
        )
    )
    after_event_2 = await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=instrument_id,
            fill_timestamp=now + timedelta(hours=2),
            realized_pnl_net=Decimal("-5000"),
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            f"/trade-decisions/loss-cut-shadow/samples/{decision.trade_decision_id}/timeline",
            params={"account_id": str(account_id)},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample"]["trade_decision_id"] == str(decision.trade_decision_id)
    assert body["sample"]["triggered"] is True
    assert body["sample"]["tier"] == "hard"
    assert body["sample"]["symbol"] == "005930"

    # shadow 시점 이전 이벤트는 제외되고, 이후 2건만 시간순으로 나온다.
    events = body["realized_events"]
    assert len(events) == 2
    assert events[0]["realized_pnl_event_id"] == str(after_event_1.realized_pnl_event_id)
    assert events[1]["realized_pnl_event_id"] == str(after_event_2.realized_pnl_event_id)
    assert events[0]["seconds_after_shadow"] == 3600.0
    assert events[1]["seconds_after_shadow"] == 7200.0
    assert before_event.realized_pnl_event_id not in {
        e["realized_pnl_event_id"] for e in events
    }


async def test_loss_cut_shadow_sample_timeline_respects_event_limit() -> None:
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

    for i in range(3):
        await repos.realized_pnl_events.add(
            _make_realized_pnl_event(
                account_id=account_id,
                instrument_id=instrument_id,
                fill_timestamp=now + timedelta(hours=i + 1),
                realized_pnl_net=Decimal("-1000"),
            )
        )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            f"/trade-decisions/loss-cut-shadow/samples/{decision.trade_decision_id}/timeline",
            params={"account_id": str(account_id), "event_limit": 1},
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["realized_events"]) == 1
    assert body["realized_event_limit"] == 1


async def test_loss_cut_shadow_sample_timeline_no_events_returns_empty_list() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(triggered=False, tier=None, loss_pct="2"),
    )
    repos.trade_decisions._items[decision.trade_decision_id] = decision

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            f"/trade-decisions/loss-cut-shadow/samples/{decision.trade_decision_id}/timeline",
            params={"account_id": str(account_id)},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["realized_events"] == []
    assert body["sample"]["triggered"] is False


async def test_loss_cut_shadow_sample_timeline_404_for_unknown_trade_decision() -> None:
    repos = build_in_memory_repositories()
    account_id, _strategy_id, _decision_context_id, _now = _seed_common(repos)

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            f"/trade-decisions/loss-cut-shadow/samples/{uuid4()}/timeline",
            params={"account_id": str(account_id)},
        )

    assert response.status_code == 404


async def test_loss_cut_shadow_sample_timeline_404_for_missing_shadow() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now,
        source_type="core",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=None,
    )
    repos.trade_decisions._items[decision.trade_decision_id] = decision

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            f"/trade-decisions/loss-cut-shadow/samples/{decision.trade_decision_id}/timeline",
            params={"account_id": str(account_id)},
        )

    assert response.status_code == 404


async def test_loss_cut_shadow_sample_timeline_404_for_account_mismatch() -> None:
    repos = build_in_memory_repositories()
    _account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(triggered=True, tier="hard", loss_pct="15"),
    )
    repos.trade_decisions._items[decision.trade_decision_id] = decision

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            f"/trade-decisions/loss-cut-shadow/samples/{decision.trade_decision_id}/timeline",
            params={"account_id": str(uuid4())},
        )

    assert response.status_code == 404


async def test_first_realized_event_latency_computes_distribution_stats() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    # sample 1: hard, 첫 event 100초 뒤
    instrument_a = uuid4()
    sample_a = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=instrument_a
        ),
    )
    # sample 2: soft, 첫 event 300초 뒤
    instrument_b = uuid4()
    sample_b = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000660",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.WATCH,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="8", instrument_id=instrument_b
        ),
    )
    # sample 3: hard, 이후 event 없음
    instrument_c = uuid4()
    sample_c = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="035420",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="20", instrument_id=instrument_c
        ),
    )
    for decision in (sample_a, sample_b, sample_c):
        repos.trade_decisions._items[decision.trade_decision_id] = decision

    await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=instrument_a,
            fill_timestamp=now + timedelta(seconds=100),
            realized_pnl_net=Decimal("-1000"),
        )
    )
    # a 종목에 event가 하나 더 있어도 "가장 먼저" 것만 써야 한다.
    await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=instrument_a,
            fill_timestamp=now + timedelta(seconds=9000),
            realized_pnl_net=Decimal("-9999"),
        )
    )
    await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=instrument_b,
            fill_timestamp=now + timedelta(seconds=300),
            realized_pnl_net=Decimal("-2000"),
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/first-realized-event-latency",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 3
    assert body["matched_first_event_count"] == 2
    assert body["missing_first_event_count"] == 1
    assert body["missing_first_event_rate"] == pytest.approx(1 / 3)
    assert body["latency_seconds_min"] == 100.0
    assert body["latency_seconds_max"] == 300.0
    assert body["latency_seconds_avg"] == pytest.approx(200.0)
    assert body["latency_seconds_median"] == pytest.approx(200.0)
    assert Decimal(body["first_realized_event_pnl_net_avg"]) == Decimal("-1500")
    assert Decimal(body["first_realized_event_pnl_net_median"]) == Decimal("-1500")


async def test_first_realized_event_latency_filters_by_tier() -> None:
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
    await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=instrument_id,
            fill_timestamp=now + timedelta(seconds=50),
            realized_pnl_net=Decimal("-500"),
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        soft_only = tc.get(
            "/trade-decisions/loss-cut-shadow/first-realized-event-latency",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
                "tier": "soft",
            },
        )
        hard_only = tc.get(
            "/trade-decisions/loss-cut-shadow/first-realized-event-latency",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
                "tier": "hard",
            },
        )

    assert soft_only.json()["sample_count"] == 0
    assert hard_only.json()["sample_count"] == 1
    assert hard_only.json()["matched_first_event_count"] == 1
    assert hard_only.json()["latency_seconds_min"] == 50.0


async def test_first_realized_event_latency_empty_sample_set_returns_nulls() -> None:
    repos = build_in_memory_repositories()
    account_id, _strategy_id, _decision_context_id, now = _seed_common(repos)

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/first-realized-event-latency",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 0
    assert body["matched_first_event_count"] == 0
    assert body["missing_first_event_count"] == 0
    assert body["missing_first_event_rate"] is None
    assert body["latency_seconds_min"] is None
    assert body["latency_seconds_avg"] is None
    assert body["first_realized_event_pnl_net_avg"] is None


async def test_first_realized_event_latency_all_missing_events() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(triggered=True, tier="hard", loss_pct="15"),
    )
    repos.trade_decisions._items[decision.trade_decision_id] = decision

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/first-realized-event-latency",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 1
    assert body["matched_first_event_count"] == 0
    assert body["missing_first_event_count"] == 1
    assert body["missing_first_event_rate"] == 1.0
    assert body["latency_seconds_min"] is None
