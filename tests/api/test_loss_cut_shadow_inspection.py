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
    RealizedPnlRecomputeQueueEntity,
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


def _get_cause_count(body: dict, cause: str) -> int:
    for item in body["cause_breakdown"]:
        if item["cause"] == cause:
            return item["count"]
    raise AssertionError(f"cause {cause} not found in cause_breakdown")


async def test_missing_first_event_causes_classifies_all_precedence_buckets() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    # 1) missing_instrument_linkage: shadow payload에 instrument_id가 없음.
    linkage_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000001",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow={
            "triggered": True,
            "tier": "hard",
            "shadow_only": True,
        },
    )

    # 2) recompute_required: cost_basis_state가 있고 recompute_required=True.
    recompute_instrument = uuid4()
    recompute_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000002",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=recompute_instrument
        ),
    )
    repos.position_cost_basis_states._items[(account_id, recompute_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=recompute_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
        )
    )

    # 3) missing_position_state: cost_basis_state 자체가 없음.
    no_state_instrument = uuid4()
    no_state_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000003",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=no_state_instrument
        ),
    )

    # 4) still_holding_position: quantity > 0.
    holding_instrument = uuid4()
    holding_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000004",
        created_at=now,
        source_type="core",
        decision_type=DecisionType.WATCH,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="8", instrument_id=holding_instrument
        ),
    )
    repos.position_cost_basis_states._items[(account_id, holding_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=holding_instrument,
            quantity=Decimal("10"),
            average_cost=Decimal("90000"),
            recompute_required=False,
        )
    )

    # 5) position_closed_but_no_realized_event: quantity <= 0, recompute_required=False.
    closed_instrument = uuid4()
    closed_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000005",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.EXIT,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=closed_instrument
        ),
    )
    repos.position_cost_basis_states._items[(account_id, closed_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=closed_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("0"),
            recompute_required=False,
        )
    )

    # matched: first realized event가 실제로 존재 — missing 집계에서 제외돼야 한다.
    matched_instrument = uuid4()
    matched_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000006",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="9", instrument_id=matched_instrument
        ),
    )

    for decision in (
        linkage_decision,
        recompute_decision,
        no_state_decision,
        holding_decision,
        closed_decision,
        matched_decision,
    ):
        repos.trade_decisions._items[decision.trade_decision_id] = decision

    await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=matched_instrument,
            fill_timestamp=now + timedelta(seconds=60),
            realized_pnl_net=Decimal("-100"),
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-causes",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()

    assert body["sample_count"] == 6
    assert body["missing_first_event_count"] == 5
    assert body["missing_first_event_rate"] == pytest.approx(5 / 6)

    assert _get_cause_count(body, "missing_instrument_linkage") == 1
    assert _get_cause_count(body, "recompute_required") == 1
    assert _get_cause_count(body, "missing_position_state") == 1
    assert _get_cause_count(body, "still_holding_position") == 1
    assert _get_cause_count(body, "position_closed_but_no_realized_event") == 1
    assert _get_cause_count(body, "other_unclassified") == 0

    source_type_rows = {r["group_value"]: r for r in body["by_source_type"]}
    assert source_type_rows["held_position"]["sample_count"] == 5
    assert source_type_rows["held_position"]["missing_first_event_count"] == 4
    assert source_type_rows["core"]["sample_count"] == 1
    assert source_type_rows["core"]["missing_first_event_count"] == 1

    tier_rows = {r["group_value"]: r for r in body["by_tier"]}
    assert tier_rows["hard"]["sample_count"] == 4
    assert tier_rows["soft"]["sample_count"] == 2

    decision_type_rows = {r["group_value"]: r for r in body["by_decision_type"]}
    assert decision_type_rows["hold"]["sample_count"] == 4
    assert decision_type_rows["watch"]["sample_count"] == 1
    assert decision_type_rows["exit"]["sample_count"] == 1


def test_missing_first_event_causes_recompute_required_takes_precedence_over_holding() -> None:
    """recompute_required=True이면서 quantity > 0(보유 중)이어도

    recompute_required bucket으로 먼저 분류돼야 한다(precedence 확인)."""
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
    repos.position_cost_basis_states._items[(account_id, instrument_id)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("10"),  # 보유 중이지만
            average_cost=Decimal("100000"),
            recompute_required=True,  # recompute_required가 우선한다.
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-causes",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert _get_cause_count(body, "recompute_required") == 1
    assert _get_cause_count(body, "still_holding_position") == 0


def test_missing_first_event_causes_empty_sample_set() -> None:
    repos = build_in_memory_repositories()
    account_id, _strategy_id, _decision_context_id, now = _seed_common(repos)

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-causes",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 0
    assert body["missing_first_event_count"] == 0
    assert body["missing_first_event_rate"] is None
    assert body["by_source_type"] == []
    assert all(item["count"] == 0 for item in body["cause_breakdown"])


def test_missing_first_event_causes_filters_by_tier() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    hard_instrument = uuid4()
    soft_instrument = uuid4()
    hard_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=hard_instrument
        ),
    )
    soft_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000660",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.WATCH,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="8", instrument_id=soft_instrument
        ),
    )
    for decision in (hard_decision, soft_decision):
        repos.trade_decisions._items[decision.trade_decision_id] = decision

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-causes",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
                "tier": "hard",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 1
    assert body["tier"] == "hard"


async def test_missing_first_event_samples_lists_missing_rows_with_cause_and_position_info() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    holding_instrument = uuid4()
    holding_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=holding_instrument
        ),
    )
    repos.trade_decisions._items[holding_decision.trade_decision_id] = holding_decision
    repos.position_cost_basis_states._items[(account_id, holding_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=holding_instrument,
            quantity=Decimal("10"),
            average_cost=Decimal("90000"),
            recompute_required=False,
        )
    )

    # matched sample — 응답에 나타나면 안 된다.
    matched_instrument = uuid4()
    matched_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000660",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="9", instrument_id=matched_instrument
        ),
    )
    repos.trade_decisions._items[matched_decision.trade_decision_id] = matched_decision
    await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=matched_instrument,
            fill_timestamp=now + timedelta(seconds=60),
            realized_pnl_net=Decimal("-100"),
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-samples",
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
    assert item["trade_decision_id"] == str(holding_decision.trade_decision_id)
    assert item["symbol"] == "005930"
    assert item["instrument_id"] == str(holding_instrument)
    assert item["source_type"] == "held_position"
    assert item["actual_decision_type"] == "hold"
    assert item["tier"] == "hard"
    assert item["triggered"] is True
    assert item["cause"] == "still_holding_position"
    assert item["recompute_required"] is False
    assert Decimal(item["position_quantity"]) == Decimal("10")
    assert item["has_first_realized_event"] is False


def test_missing_first_event_samples_filters_by_cause_matches_causes_endpoint() -> None:
    """``cause`` 필터가 ``missing-first-event-causes``와 동일한 판정을

    쓰는지 교차 확인한다 — 같은 표본 집합에 대해 causes endpoint의
    특정 bucket count와 samples endpoint의 해당 cause 필터 결과
    건수가 반드시 일치해야 한다."""
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    recompute_instrument = uuid4()
    recompute_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=recompute_instrument
        ),
    )
    repos.trade_decisions._items[recompute_decision.trade_decision_id] = recompute_decision
    repos.position_cost_basis_states._items[(account_id, recompute_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=recompute_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
        )
    )

    holding_instrument = uuid4()
    holding_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000660",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.WATCH,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="8", instrument_id=holding_instrument
        ),
    )
    repos.trade_decisions._items[holding_decision.trade_decision_id] = holding_decision
    repos.position_cost_basis_states._items[(account_id, holding_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=holding_instrument,
            quantity=Decimal("5"),
            average_cost=Decimal("50000"),
            recompute_required=False,
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    params_common = {
        "account_id": str(account_id),
        "start_date": (now - timedelta(days=1)).date().isoformat(),
        "end_date": (now + timedelta(days=1)).date().isoformat(),
    }
    with TestClient(app) as tc:
        causes_response = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-causes",
            params=params_common,
        )
        samples_response = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-samples",
            params={**params_common, "cause": "recompute_required"},
        )

    causes_body = causes_response.json()
    samples_body = samples_response.json()

    recompute_cause_count = next(
        item["count"]
        for item in causes_body["cause_breakdown"]
        if item["cause"] == "recompute_required"
    )
    assert recompute_cause_count == 1
    assert len(samples_body["items"]) == recompute_cause_count
    assert samples_body["items"][0]["trade_decision_id"] == str(
        recompute_decision.trade_decision_id
    )
    assert samples_body["items"][0]["cause"] == "recompute_required"


def test_missing_first_event_samples_respects_limit_and_before_cursor() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    decisions = []
    for i in range(3):
        instrument_id = uuid4()
        decision = _make_decision(
            decision_context_id=decision_context_id,
            strategy_id=strategy_id,
            symbol=f"00000{i}",
            created_at=now + timedelta(hours=i),
            source_type="held_position",
            decision_type=DecisionType.HOLD,
            loss_cut_shadow=_shadow_payload(
                triggered=True, tier="hard", loss_pct="15", instrument_id=instrument_id
            ),
        )
        repos.trade_decisions._items[decision.trade_decision_id] = decision
        decisions.append(decision)

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        limited = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-samples",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
                "limit": 1,
            },
        )
        before_cursor = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-samples",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
                "before": (now + timedelta(hours=2)).isoformat(),
            },
        )

    assert len(limited.json()["items"]) == 1
    # 최신순이므로 limit=1이면 가장 최근(hours=2) 표본만 나와야 한다.
    assert limited.json()["items"][0]["trade_decision_id"] == str(
        decisions[2].trade_decision_id
    )

    # before=now+2h면 hours=2 표본은 제외되고 hours=0,1만 남아야 한다.
    before_ids = {item["trade_decision_id"] for item in before_cursor.json()["items"]}
    assert before_ids == {
        str(decisions[0].trade_decision_id),
        str(decisions[1].trade_decision_id),
    }


def test_missing_first_event_samples_invalid_cause_returns_400() -> None:
    repos = build_in_memory_repositories()
    account_id, _strategy_id, _decision_context_id, now = _seed_common(repos)

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-samples",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
                "cause": "not_a_real_cause",
            },
        )

    assert response.status_code == 400


def _make_recompute_queue_item(
    *, account_id, instrument_id, requested_at, reason_code="ledger_mismatch"
) -> RealizedPnlRecomputeQueueEntity:
    return RealizedPnlRecomputeQueueEntity(
        recompute_queue_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        reason_code=reason_code,
        requested_at=requested_at,
    )


async def test_recompute_cross_check_classifies_match_missing_and_extra_cases() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    # 케이스 1: recompute_required=true + queue pending 있음(match).
    match_instrument = uuid4()
    match_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000001",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=match_instrument
        ),
    )
    repos.trade_decisions._items[match_decision.trade_decision_id] = match_decision
    repos.position_cost_basis_states._items[(account_id, match_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=match_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
        )
    )
    await repos.realized_pnl_recompute_queue.add(
        _make_recompute_queue_item(
            account_id=account_id,
            instrument_id=match_instrument,
            requested_at=now - timedelta(hours=1),
        )
    )
    await repos.realized_pnl_recompute_queue.add(
        _make_recompute_queue_item(
            account_id=account_id,
            instrument_id=match_instrument,
            requested_at=now - timedelta(hours=2),
            reason_code="out_of_order_fill",
        )
    )

    # 케이스 2: recompute_required=true인데 queue pending 없음(missing).
    missing_instrument = uuid4()
    missing_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000002",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=missing_instrument
        ),
    )
    repos.trade_decisions._items[missing_decision.trade_decision_id] = missing_decision
    repos.position_cost_basis_states._items[(account_id, missing_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=missing_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
        )
    )

    # 케이스 3: recompute_required가 아닌데(still_holding) queue pending 있음(extra).
    extra_instrument = uuid4()
    extra_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000003",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.WATCH,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="8", instrument_id=extra_instrument
        ),
    )
    repos.trade_decisions._items[extra_decision.trade_decision_id] = extra_decision
    repos.position_cost_basis_states._items[(account_id, extra_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=extra_instrument,
            quantity=Decimal("10"),
            average_cost=Decimal("90000"),
            recompute_required=False,
        )
    )
    await repos.realized_pnl_recompute_queue.add(
        _make_recompute_queue_item(
            account_id=account_id,
            instrument_id=extra_instrument,
            requested_at=now - timedelta(minutes=30),
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-recompute-cross-check",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()

    assert body["sample_count"] == 3
    assert body["queue_pending_match_count"] == 1
    assert body["queue_pending_missing_count"] == 1
    assert body["queue_pending_extra_count"] == 1
    assert body["recompute_required_queue_match_rate"] == pytest.approx(0.5)

    items_by_symbol = {item["symbol"]: item for item in body["items"]}

    match_item = items_by_symbol["000001"]
    assert match_item["recompute_required"] is True
    assert match_item["queue_pending"] is True
    assert match_item["queue_pending_count"] == 2
    assert set(match_item["queue_reason_codes"]) == {"ledger_mismatch", "out_of_order_fill"}
    assert datetime.fromisoformat(match_item["queue_oldest_requested_at"]) == (
        now - timedelta(hours=2)
    )
    assert match_item["has_first_realized_event"] is False

    missing_item = items_by_symbol["000002"]
    assert missing_item["recompute_required"] is True
    assert missing_item["queue_pending"] is False
    assert missing_item["queue_pending_count"] == 0
    assert missing_item["queue_oldest_requested_at"] is None

    extra_item = items_by_symbol["000003"]
    assert extra_item["recompute_required"] is False
    assert extra_item["queue_pending"] is True
    assert extra_item["queue_pending_count"] == 1
    assert extra_item["cause"] == "still_holding_position"


async def test_recompute_cross_check_ignores_queue_items_from_other_accounts() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)
    other_account_id = uuid4()
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
    repos.position_cost_basis_states._items[(account_id, instrument_id)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
        )
    )
    # 다른 계좌의 같은 instrument_id에 대한 queue pending — 섞이면 안 된다.
    await repos.realized_pnl_recompute_queue.add(
        _make_recompute_queue_item(
            account_id=other_account_id,
            instrument_id=instrument_id,
            requested_at=now - timedelta(hours=1),
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-recompute-cross-check",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["queue_pending"] is False
    assert body["queue_pending_missing_count"] == 1


async def test_recompute_cross_check_respects_limit_and_before_cursor() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    decisions = []
    for i in range(3):
        instrument_id = uuid4()
        decision = _make_decision(
            decision_context_id=decision_context_id,
            strategy_id=strategy_id,
            symbol=f"00000{i}",
            created_at=now + timedelta(hours=i),
            source_type="held_position",
            decision_type=DecisionType.HOLD,
            loss_cut_shadow=_shadow_payload(
                triggered=True, tier="hard", loss_pct="15", instrument_id=instrument_id
            ),
        )
        repos.trade_decisions._items[decision.trade_decision_id] = decision
        decisions.append(decision)

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        limited = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-recompute-cross-check",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
                "limit": 1,
            },
        )

    assert limited.status_code == 200
    body = limited.json()
    # limit이 원시 조회 행 수가 아니라 missing 조건을 만족하는 행 수 기준임을
    # 확인한다 — sample_count(모집단 전체)는 3이지만 items는 1건만 나온다.
    assert body["sample_count"] == 3
    assert len(body["items"]) == 1
    assert body["items"][0]["trade_decision_id"] == str(decisions[2].trade_decision_id)


async def test_recompute_cross_check_empty_population_returns_nulls() -> None:
    repos = build_in_memory_repositories()
    account_id, _strategy_id, _decision_context_id, now = _seed_common(repos)

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/missing-first-event-recompute-cross-check",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 0
    assert body["queue_pending_match_count"] == 0
    assert body["queue_pending_missing_count"] == 0
    assert body["queue_pending_extra_count"] == 0
    assert body["recompute_required_queue_match_rate"] is None
    assert body["items"] == []


async def test_recompute_missing_queue_causes_classifies_recent_and_old_cases() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    # recompute_required=true + queue pending 없음 + 최근에 recompute_required가
    # 세팅됨(1시간 이내) -> recent_pending_gap.
    recent_instrument = uuid4()
    recent_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000001",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=recent_instrument
        ),
    )
    repos.trade_decisions._items[recent_decision.trade_decision_id] = recent_decision
    repos.position_cost_basis_states._items[(account_id, recent_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=recent_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )

    # recompute_required=true + queue pending 없음 + 오래 전(1시간 초과)
    # -> queue_write_path_suspected.
    old_instrument = uuid4()
    old_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000002",
        created_at=now,
        source_type="core",
        decision_type=DecisionType.WATCH,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="8", instrument_id=old_instrument
        ),
    )
    repos.trade_decisions._items[old_decision.trade_decision_id] = old_decision
    repos.position_cost_basis_states._items[(account_id, old_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=old_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=datetime.now(timezone.utc) - timedelta(hours=3),
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/recompute-missing-queue-causes",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()

    assert body["sample_count"] == 2
    assert body["queue_scan_limit"] == 100
    assert body["queue_scan_limit_reached"] is False

    cause_counts = {item["cause"]: item["count"] for item in body["cause_breakdown"]}
    assert cause_counts["recent_pending_gap"] == 1
    assert cause_counts["queue_write_path_suspected"] == 1
    assert cause_counts["missing_instrument_linkage"] == 0
    assert cause_counts["queue_scan_limit_suspected"] == 0

    items_by_symbol = {item["symbol"]: item for item in body["items"]}
    assert items_by_symbol["000001"]["cause"] == "recent_pending_gap"
    assert items_by_symbol["000002"]["cause"] == "queue_write_path_suspected"
    for item in body["items"]:
        assert item["recompute_required"] is True
        assert item["queue_pending"] is False
        assert item["has_first_realized_event"] is False
        assert item["queue_scan_limit_reached"] is False

    source_type_rates = {r["group_value"]: r for r in body["by_source_type"]}
    assert source_type_rates["held_position"]["count"] == 1
    assert source_type_rates["held_position"]["rate"] == pytest.approx(0.5)
    assert source_type_rates["core"]["count"] == 1

    tier_rates = {r["group_value"]: r for r in body["by_tier"]}
    assert tier_rates["hard"]["count"] == 1
    assert tier_rates["soft"]["count"] == 1


async def test_recompute_missing_queue_causes_falls_back_to_created_at_when_no_updated_at() -> None:
    """``position_cost_basis_state.updated_at``가 없으면 sample

    ``created_at``을 근사치로 써서 recency를 판단해야 한다."""
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, _now = _seed_common(repos)
    old_created_at = datetime.now(timezone.utc) - timedelta(hours=5)
    instrument_id = uuid4()

    decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="005930",
        created_at=old_created_at,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=instrument_id
        ),
    )
    repos.trade_decisions._items[decision.trade_decision_id] = decision
    repos.position_cost_basis_states._items[(account_id, instrument_id)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=None,
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/recompute-missing-queue-causes",
            params={
                "account_id": str(account_id),
                "start_date": (old_created_at - timedelta(days=1)).date().isoformat(),
                "end_date": (old_created_at + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["cause"] == "queue_write_path_suspected"
    assert body["items"][0]["recompute_required_since"] is None


async def test_recompute_missing_queue_causes_scan_limit_suspected_when_queue_full() -> None:
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
    repos.position_cost_basis_states._items[(account_id, instrument_id)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=datetime.now(timezone.utc) - timedelta(hours=5),
        )
    )

    # 다른 계좌 소유의 pending 100건으로 전역 스캔 한계(100)를 채운다 —
    # 우리 계좌 sample의 population 자체는 오염시키지 않는다.
    other_account_id = uuid4()
    for i in range(100):
        await repos.realized_pnl_recompute_queue.add(
            _make_recompute_queue_item(
                account_id=other_account_id,
                instrument_id=uuid4(),
                requested_at=now - timedelta(hours=i + 1),
            )
        )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/recompute-missing-queue-causes",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["queue_scan_limit_reached"] is True
    assert body["items"][0]["cause"] == "queue_scan_limit_suspected"
    assert body["items"][0]["queue_scan_limit_reached"] is True


async def test_recompute_missing_queue_causes_excludes_non_matching_population() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)

    # recompute_required=False -> 모집단 아님.
    not_recompute_instrument = uuid4()
    not_recompute_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000001",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=not_recompute_instrument
        ),
    )
    repos.trade_decisions._items[not_recompute_decision.trade_decision_id] = (
        not_recompute_decision
    )
    repos.position_cost_basis_states._items[(account_id, not_recompute_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=not_recompute_instrument,
            quantity=Decimal("10"),
            average_cost=Decimal("100000"),
            recompute_required=False,
        )
    )

    # recompute_required=True지만 queue pending도 있음 -> 모집단 아님(cross-check의 match).
    pending_instrument = uuid4()
    pending_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000002",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=pending_instrument
        ),
    )
    repos.trade_decisions._items[pending_decision.trade_decision_id] = pending_decision
    repos.position_cost_basis_states._items[(account_id, pending_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=pending_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
        )
    )
    await repos.realized_pnl_recompute_queue.add(
        _make_recompute_queue_item(
            account_id=account_id,
            instrument_id=pending_instrument,
            requested_at=now - timedelta(hours=1),
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/recompute-missing-queue-causes",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 0
    assert body["items"] == []


async def test_queue_write_path_suspected_timelines_batches_events_across_samples() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)
    old_updated_at = datetime.now(timezone.utc) - timedelta(hours=3)

    # sample 1: queue_write_path_suspected + 이후 realized event 있음.
    with_event_instrument = uuid4()
    with_event_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000001",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=with_event_instrument
        ),
    )
    repos.trade_decisions._items[with_event_decision.trade_decision_id] = with_event_decision
    repos.position_cost_basis_states._items[(account_id, with_event_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=with_event_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=old_updated_at,
        )
    )
    await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=with_event_instrument,
            fill_timestamp=now + timedelta(hours=2),
            realized_pnl_net=Decimal("-3000"),
        )
    )

    # sample 2: queue_write_path_suspected + 이후 realized event 없음.
    without_event_instrument = uuid4()
    without_event_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000002",
        created_at=now,
        source_type="core",
        decision_type=DecisionType.WATCH,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="8", instrument_id=without_event_instrument
        ),
    )
    repos.trade_decisions._items[without_event_decision.trade_decision_id] = (
        without_event_decision
    )
    repos.position_cost_basis_states._items[(account_id, without_event_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=without_event_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=old_updated_at,
        )
    )

    # sample 3: recent_pending_gap(오래되지 않음) — 이 endpoint 모집단이 아니다.
    recent_instrument = uuid4()
    recent_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000003",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=recent_instrument
        ),
    )
    repos.trade_decisions._items[recent_decision.trade_decision_id] = recent_decision
    repos.position_cost_basis_states._items[(account_id, recent_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=recent_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/queue-write-path-suspected-timelines",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()

    # recent_pending_gap 표본은 제외되고 queue_write_path_suspected 2건만 포함된다.
    assert body["sample_count"] == 2
    assert body["timeline_with_events_count"] == 1
    assert body["timeline_without_events_count"] == 1
    assert body["first_event_found_rate"] == pytest.approx(0.5)
    assert body["max_observed_latency_seconds"] == pytest.approx(7200.0)
    assert body["avg_first_event_latency_seconds"] == pytest.approx(7200.0)

    items_by_symbol = {item["symbol"]: item for item in body["items"]}
    assert set(items_by_symbol) == {"000001", "000002"}

    with_event_item = items_by_symbol["000001"]
    assert with_event_item["cause"] == "queue_write_path_suspected"
    assert with_event_item["first_event_found"] is True
    assert with_event_item["timeline_event_count"] == 1
    assert with_event_item["first_event_latency_seconds"] == pytest.approx(7200.0)
    assert len(with_event_item["events"]) == 1
    assert with_event_item["events"][0]["realized_pnl_net"] == "-3000"
    assert with_event_item["recompute_required"] is True
    assert with_event_item["queue_pending"] is False
    assert with_event_item["has_first_realized_event"] is False

    without_event_item = items_by_symbol["000002"]
    assert without_event_item["first_event_found"] is False
    assert without_event_item["timeline_event_count"] == 0
    assert without_event_item["first_event_latency_seconds"] is None
    assert without_event_item["events"] == []


async def test_queue_write_path_suspected_timelines_respects_event_limit() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)
    old_updated_at = datetime.now(timezone.utc) - timedelta(hours=3)
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
    repos.position_cost_basis_states._items[(account_id, instrument_id)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=old_updated_at,
        )
    )
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
            "/trade-decisions/loss-cut-shadow/queue-write-path-suspected-timelines",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
                "event_limit": 1,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["event_limit"] == 1
    assert body["items"][0]["timeline_event_count"] == 1
    assert len(body["items"][0]["events"]) == 1


async def test_queue_write_path_suspected_timelines_top_level_stats_cover_full_population_beyond_limit() -> None:
    """``limit``이 ``items`` 표시 건수만 줄이고, top-level 집계

    (``sample_count``/``timeline_with_events_count`` 등)는 전체
    모집단 기준으로 유지되는지 확인한다 — 그래야 이 raw endpoint와
    ``queue-write-path-suspected-timeline-summary``의 수치가 항상
    일치한다."""
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)
    old_updated_at = datetime.now(timezone.utc) - timedelta(hours=3)

    for i in range(3):
        instrument_id = uuid4()
        decision = _make_decision(
            decision_context_id=decision_context_id,
            strategy_id=strategy_id,
            symbol=f"00000{i}",
            created_at=now,
            source_type="held_position",
            decision_type=DecisionType.HOLD,
            loss_cut_shadow=_shadow_payload(
                triggered=True, tier="hard", loss_pct="15", instrument_id=instrument_id
            ),
        )
        repos.trade_decisions._items[decision.trade_decision_id] = decision
        repos.position_cost_basis_states._items[(account_id, instrument_id)] = (
            PositionCostBasisStateEntity(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("0"),
                average_cost=Decimal("100000"),
                recompute_required=True,
                updated_at=old_updated_at,
            )
        )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/queue-write-path-suspected-timelines",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
                "limit": 1,
            },
        )

    assert response.status_code == 200
    body = response.json()
    # 모집단은 3건이지만 items는 limit=1로 1건만 표시된다.
    assert body["sample_count"] == 3
    assert body["timeline_without_events_count"] == 3
    assert len(body["items"]) == 1


async def test_queue_write_path_suspected_timelines_empty_population() -> None:
    repos = build_in_memory_repositories()
    account_id, _strategy_id, _decision_context_id, now = _seed_common(repos)

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/queue-write-path-suspected-timelines",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 0
    assert body["timeline_with_events_count"] == 0
    assert body["timeline_without_events_count"] == 0
    assert body["first_event_found_rate"] is None
    assert body["max_observed_latency_seconds"] is None
    assert body["avg_first_event_latency_seconds"] is None
    assert body["items"] == []


async def test_queue_write_path_suspected_timelines_excludes_scan_limit_suspected() -> None:
    """스캔 한계에 걸리면 ``queue_scan_limit_suspected``로 분류돼

    이 endpoint 모집단(``queue_write_path_suspected``만)에서 제외돼야
    한다."""
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
    repos.position_cost_basis_states._items[(account_id, instrument_id)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=datetime.now(timezone.utc) - timedelta(hours=5),
        )
    )
    other_account_id = uuid4()
    for i in range(100):
        await repos.realized_pnl_recompute_queue.add(
            _make_recompute_queue_item(
                account_id=other_account_id,
                instrument_id=uuid4(),
                requested_at=now - timedelta(hours=i + 1),
            )
        )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/queue-write-path-suspected-timelines",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=1)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 0
    assert body["items"] == []


async def test_queue_write_path_suspected_timeline_summary_matches_raw_endpoint_top_level() -> None:
    """같은 조회 조건으로 raw batch endpoint와 summary endpoint를

    호출하면 top-level 수치가 항상 일치해야 한다(공통 helper 재사용
    확인)."""
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)
    old_updated_at = datetime.now(timezone.utc) - timedelta(hours=3)

    with_event_instrument = uuid4()
    with_event_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000001",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=with_event_instrument
        ),
    )
    repos.trade_decisions._items[with_event_decision.trade_decision_id] = with_event_decision
    repos.position_cost_basis_states._items[(account_id, with_event_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=with_event_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=old_updated_at,
        )
    )
    await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=with_event_instrument,
            fill_timestamp=now + timedelta(hours=2),
            realized_pnl_net=Decimal("-3000"),
        )
    )

    without_event_instrument = uuid4()
    without_event_decision = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000002",
        created_at=now,
        source_type="core",
        decision_type=DecisionType.WATCH,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="8", instrument_id=without_event_instrument
        ),
    )
    repos.trade_decisions._items[without_event_decision.trade_decision_id] = (
        without_event_decision
    )
    repos.position_cost_basis_states._items[(account_id, without_event_instrument)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=without_event_instrument,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=old_updated_at,
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    params = {
        "account_id": str(account_id),
        "start_date": (now - timedelta(days=1)).date().isoformat(),
        "end_date": (now + timedelta(days=1)).date().isoformat(),
    }
    with TestClient(app) as tc:
        raw = tc.get(
            "/trade-decisions/loss-cut-shadow/queue-write-path-suspected-timelines",
            params=params,
        )
        summary = tc.get(
            "/trade-decisions/loss-cut-shadow/queue-write-path-suspected-timeline-summary",
            params=params,
        )

    raw_body = raw.json()
    summary_body = summary.json()

    assert raw_body["sample_count"] == summary_body["sample_count"] == 2
    assert (
        raw_body["timeline_with_events_count"]
        == summary_body["timeline_with_events_count"]
        == 1
    )
    assert (
        raw_body["timeline_without_events_count"]
        == summary_body["timeline_without_events_count"]
        == 1
    )
    assert raw_body["first_event_found_rate"] == summary_body["first_event_found_rate"]
    assert (
        raw_body["max_observed_latency_seconds"]
        == summary_body["max_observed_latency_seconds"]
        == pytest.approx(7200.0)
    )
    assert (
        raw_body["avg_first_event_latency_seconds"]
        == summary_body["avg_first_event_latency_seconds"]
    )
    assert summary_body["median_first_event_latency_seconds"] == pytest.approx(7200.0)


async def test_queue_write_path_suspected_timeline_summary_by_instrument_and_latency_bucket() -> None:
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)
    old_updated_at = datetime.now(timezone.utc) - timedelta(hours=3)

    # instrument A: 1건 발생, 5분 뒤(under_10m).
    instrument_a = uuid4()
    decision_a = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000001",
        created_at=now,
        source_type="held_position",
        decision_type=DecisionType.HOLD,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="hard", loss_pct="15", instrument_id=instrument_a
        ),
    )
    repos.trade_decisions._items[decision_a.trade_decision_id] = decision_a
    repos.position_cost_basis_states._items[(account_id, instrument_a)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=instrument_a,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=old_updated_at,
        )
    )
    await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=instrument_a,
            fill_timestamp=now + timedelta(minutes=5),
            realized_pnl_net=Decimal("-500"),
        )
    )

    # instrument B: 2건 발생 — 1건은 2일 뒤(over_1d), 1건은 event 없음.
    instrument_b = uuid4()
    decision_b1 = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000002",
        created_at=now,
        source_type="core",
        decision_type=DecisionType.WATCH,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="8", instrument_id=instrument_b
        ),
    )
    # 이 decision은 아래에서 기록할 realized event(now+2일)보다 나중에
    # 생성되므로, "그 이후" event가 없어 timeline_without_events에
    # 들어가야 한다.
    decision_b2 = _make_decision(
        decision_context_id=decision_context_id,
        strategy_id=strategy_id,
        symbol="000002",
        created_at=now + timedelta(days=3),
        source_type="core",
        decision_type=DecisionType.WATCH,
        loss_cut_shadow=_shadow_payload(
            triggered=True, tier="soft", loss_pct="9", instrument_id=instrument_b
        ),
    )
    repos.trade_decisions._items[decision_b1.trade_decision_id] = decision_b1
    repos.trade_decisions._items[decision_b2.trade_decision_id] = decision_b2
    repos.position_cost_basis_states._items[(account_id, instrument_b)] = (
        PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=instrument_b,
            quantity=Decimal("0"),
            average_cost=Decimal("100000"),
            recompute_required=True,
            updated_at=old_updated_at,
        )
    )
    await repos.realized_pnl_events.add(
        _make_realized_pnl_event(
            account_id=account_id,
            instrument_id=instrument_b,
            fill_timestamp=now + timedelta(days=2),
            realized_pnl_net=Decimal("-700"),
        )
    )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/queue-write-path-suspected-timeline-summary",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=4)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 3

    by_instrument = {item["symbol"]: item for item in body["by_instrument"]}
    assert by_instrument["000001"]["sample_count"] == 1
    assert by_instrument["000001"]["timeline_with_events_count"] == 1
    assert by_instrument["000002"]["sample_count"] == 2
    assert by_instrument["000002"]["timeline_with_events_count"] == 1
    assert by_instrument["000002"]["timeline_without_events_count"] == 1

    bucket_counts = {item["bucket"]: item["count"] for item in body["by_latency_bucket"]}
    assert bucket_counts["under_10m"] == 1
    assert bucket_counts["over_1d"] == 1
    assert bucket_counts["no_event_found"] == 1
    assert bucket_counts["10m_to_1h"] == 0
    assert bucket_counts["1h_to_1d"] == 0

    source_type_rows = {r["group_value"]: r for r in body["by_source_type"]}
    assert source_type_rows["held_position"]["sample_count"] == 1
    assert source_type_rows["core"]["sample_count"] == 2

    tier_rows = {r["group_value"]: r for r in body["by_tier"]}
    assert tier_rows["hard"]["sample_count"] == 1
    assert tier_rows["soft"]["sample_count"] == 2


async def test_queue_write_path_suspected_timeline_summary_latency_bucket_boundaries() -> None:
    """경계값(정확히 600초/3600초/86400초)이 어느 bucket으로

    분류되는지 확인한다 — 각 구간은 하한 포함(``<`` 비교)이다."""
    repos = build_in_memory_repositories()
    account_id, strategy_id, decision_context_id, now = _seed_common(repos)
    old_updated_at = datetime.now(timezone.utc) - timedelta(hours=3)

    boundary_seconds = [599, 600, 3599, 3600, 86399, 86400]
    for i, seconds in enumerate(boundary_seconds):
        instrument_id = uuid4()
        decision = _make_decision(
            decision_context_id=decision_context_id,
            strategy_id=strategy_id,
            symbol=f"B{i}",
            created_at=now,
            source_type="held_position",
            decision_type=DecisionType.HOLD,
            loss_cut_shadow=_shadow_payload(
                triggered=True, tier="hard", loss_pct="15", instrument_id=instrument_id
            ),
        )
        repos.trade_decisions._items[decision.trade_decision_id] = decision
        repos.position_cost_basis_states._items[(account_id, instrument_id)] = (
            PositionCostBasisStateEntity(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("0"),
                average_cost=Decimal("100000"),
                recompute_required=True,
                updated_at=old_updated_at,
            )
        )
        await repos.realized_pnl_events.add(
            _make_realized_pnl_event(
                account_id=account_id,
                instrument_id=instrument_id,
                fill_timestamp=now + timedelta(seconds=seconds),
                realized_pnl_net=Decimal("-100"),
            )
        )

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/queue-write-path-suspected-timeline-summary",
            params={
                "account_id": str(account_id),
                "start_date": (now - timedelta(days=1)).date().isoformat(),
                "end_date": (now + timedelta(days=2)).date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    bucket_counts = {item["bucket"]: item["count"] for item in body["by_latency_bucket"]}
    # 599 -> under_10m, 600 -> 10m_to_1h, 3599 -> 10m_to_1h, 3600 -> 1h_to_1d,
    # 86399 -> 1h_to_1d, 86400 -> over_1d
    assert bucket_counts["under_10m"] == 1
    assert bucket_counts["10m_to_1h"] == 2
    assert bucket_counts["1h_to_1d"] == 2
    assert bucket_counts["over_1d"] == 1
    assert bucket_counts["no_event_found"] == 0


async def test_queue_write_path_suspected_timeline_summary_empty_population() -> None:
    repos = build_in_memory_repositories()
    account_id, _strategy_id, _decision_context_id, now = _seed_common(repos)

    app = create_app(repos=repos, auth_enabled=False)
    with TestClient(app) as tc:
        response = tc.get(
            "/trade-decisions/loss-cut-shadow/queue-write-path-suspected-timeline-summary",
            params={
                "account_id": str(account_id),
                "start_date": now.date().isoformat(),
                "end_date": now.date().isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 0
    assert body["first_event_found_rate"] is None
    assert body["max_observed_latency_seconds"] is None
    assert body["avg_first_event_latency_seconds"] is None
    assert body["median_first_event_latency_seconds"] is None
    assert body["by_instrument"] == []
    assert body["by_source_type"] == []
    assert body["by_tier"] == []
    assert all(item["count"] == 0 for item in body["by_latency_bucket"])
