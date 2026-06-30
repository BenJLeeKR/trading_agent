from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agent_trading.domain.entities import (
    OrderRequestEntity,
    PositionSnapshotEntity,
    SymbolTradeStateEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.symbol_trade_state_machine import (
    reconcile_account_symbol_trade_states,
    resolve_symbol_trade_state,
)


def _make_symbol_state(**overrides) -> SymbolTradeStateEntity:
    now = datetime.now(timezone.utc)
    base = SymbolTradeStateEntity(
        symbol_trade_state_id=uuid4(),
        account_id=uuid4(),
        instrument_id=uuid4(),
        symbol="005930",
        market="KRX",
        state="entry_pending",
        position_quantity=Decimal("0"),
        reentry_cooldown_until=None,
        metadata_json={},
        created_at=now,
        updated_at=now,
    )
    return replace(base, **overrides)


def _make_order(
    *,
    account_id,
    instrument_id,
    side: OrderSide,
    status: OrderStatus,
) -> OrderRequestEntity:
    now = datetime.now(timezone.utc)
    return OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id=str(uuid4()),
        idempotency_key=str(uuid4()),
        correlation_id="corr",
        side=side,
        order_type=OrderType.MARKET,
        requested_quantity=Decimal("10"),
        status=status,
        time_in_force=TimeInForce.DAY,
        created_at=now,
        updated_at=now,
    )


def test_resolve_state_promotes_to_held_active_when_position_exists() -> None:
    now = datetime.now(timezone.utc)
    state = _make_symbol_state(state="entry_pending")
    resolved = resolve_symbol_trade_state(
        current_state=state,
        position_quantity=Decimal("7"),
        latest_buy_order=_make_order(
            account_id=state.account_id,
            instrument_id=state.instrument_id,
            side=OrderSide.BUY,
            status=OrderStatus.PARTIALLY_FILLED,
        ),
        latest_sell_order=None,
        now_utc=now,
    )
    assert resolved.state == "held_active"
    assert resolved.reason_codes == ("authoritative_position_positive",)


def test_resolve_state_keeps_flat_cooldown_when_position_zero_and_cooldown_alive() -> None:
    now = datetime.now(timezone.utc)
    state = _make_symbol_state(
        state="exit_pending",
        reentry_cooldown_until=now + timedelta(minutes=10),
    )
    resolved = resolve_symbol_trade_state(
        current_state=state,
        position_quantity=Decimal("0"),
        latest_buy_order=None,
        latest_sell_order=None,
        now_utc=now,
    )
    assert resolved.state == "flat_cooldown"


@pytest.mark.asyncio
async def test_reconcile_account_symbol_trade_states_updates_repo_authoritatively() -> None:
    repos = build_in_memory_repositories()
    now = datetime.now(timezone.utc)
    state = _make_symbol_state(state="entry_pending")
    await repos.symbol_trade_states.upsert(state)
    buy_order = _make_order(
        account_id=state.account_id,
        instrument_id=state.instrument_id,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
    )
    await repos.orders.add(buy_order)
    await repos.position_snapshots.add(
        PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=state.account_id,
            instrument_id=state.instrument_id,
            quantity=Decimal("12"),
            average_price=Decimal("50000"),
            market_price=Decimal("51000"),
            unrealized_pnl=Decimal("12000"),
            source_of_truth="kis",
            snapshot_at=now,
            created_at=now,
        )
    )

    updated = await reconcile_account_symbol_trade_states(
        symbol_trade_state_repo=repos.symbol_trade_states,
        position_snapshot_repo=repos.position_snapshots,
        order_repo=repos.orders,
        account_id=state.account_id,
        now_utc=now,
    )

    assert updated == 1
    refreshed = await repos.symbol_trade_states.get_by_account_and_instrument(
        state.account_id,
        state.instrument_id,
    )
    assert refreshed is not None
    assert refreshed.state == "held_active"
    assert refreshed.position_quantity == Decimal("12")
    assert refreshed.last_reason_codes == ["authoritative_position_positive"]
