from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from agent_trading.domain.entities import TradeDecisionEntity
from agent_trading.domain.enums import DecisionType, EntryStyle, OrderSide
from agent_trading.repositories.bootstrap import build_in_memory_repositories


def _make_decision(
    *,
    created_at,
    symbol="005930",
    source_type="held_position",
    decision_type=DecisionType.HOLD,
    loss_cut_shadow=None,
) -> TradeDecisionEntity:
    return TradeDecisionEntity(
        trade_decision_id=uuid4(),
        decision_context_id=uuid4(),
        decision_type=decision_type,
        side=OrderSide.SELL,
        strategy_id=uuid4(),
        symbol=symbol,
        market="KRX",
        entry_style=EntryStyle.LIMIT,
        created_at=created_at,
        source_type=source_type,
        decision_json={"loss_cut_shadow": loss_cut_shadow} if loss_cut_shadow else {},
    )


async def test_list_loss_cut_shadow_observations_filters_and_orders_desc() -> None:
    repos = build_in_memory_repositories()
    account_id = uuid4()
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)

    older = _make_decision(
        created_at=base,
        loss_cut_shadow={"triggered": True, "tier": "soft"},
    )
    newer = _make_decision(
        created_at=base + timedelta(days=1),
        loss_cut_shadow={"triggered": True, "tier": "hard"},
    )
    no_shadow = _make_decision(created_at=base + timedelta(days=2), loss_cut_shadow=None)

    for d in (older, newer, no_shadow):
        repos.trade_decisions._items[d.trade_decision_id] = d

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(account_id)

    assert [r.trade_decision_id for r in rows] == [
        newer.trade_decision_id,
        older.trade_decision_id,
    ]
    # in-memory 구현은 account_id로 필터링하지 않으므로, 반환된 row의
    # account_id는 호출자가 넘긴 값을 그대로 되돌려준다(문서화된 한계).
    assert all(r.account_id == account_id for r in rows)


async def test_list_loss_cut_shadow_observations_applies_before_and_limit() -> None:
    repos = build_in_memory_repositories()
    account_id = uuid4()
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)

    d1 = _make_decision(created_at=base, loss_cut_shadow={"triggered": False, "tier": None})
    d2 = _make_decision(
        created_at=base + timedelta(hours=1),
        loss_cut_shadow={"triggered": True, "tier": "soft"},
    )
    d3 = _make_decision(
        created_at=base + timedelta(hours=2),
        loss_cut_shadow={"triggered": True, "tier": "hard"},
    )
    for d in (d1, d2, d3):
        repos.trade_decisions._items[d.trade_decision_id] = d

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        account_id, before=base + timedelta(hours=2), limit=1
    )

    assert len(rows) == 1
    assert rows[0].trade_decision_id == d2.trade_decision_id


async def test_list_loss_cut_shadow_observations_filters_by_tier_and_source_type() -> None:
    repos = build_in_memory_repositories()
    account_id = uuid4()
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)

    held = _make_decision(
        created_at=base,
        source_type="held_position",
        loss_cut_shadow={"triggered": True, "tier": "hard"},
    )
    core = _make_decision(
        created_at=base,
        source_type="core",
        loss_cut_shadow={"triggered": True, "tier": "soft"},
    )
    for d in (held, core):
        repos.trade_decisions._items[d.trade_decision_id] = d

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        account_id, tier="hard"
    )
    assert [r.trade_decision_id for r in rows] == [held.trade_decision_id]

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        account_id, source_type="core"
    )
    assert [r.trade_decision_id for r in rows] == [core.trade_decision_id]
