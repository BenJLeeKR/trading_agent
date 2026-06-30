from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Sequence

from agent_trading.domain.entities import (
    OrderRequestEntity,
    SymbolTradeStateEntity,
)
from agent_trading.domain.enums import OrderStatus
from agent_trading.repositories.contracts import (
    OrderRepository,
    PositionSnapshotRepository,
    SymbolTradeStateRepository,
)
from agent_trading.repositories.filters import OrderQuery

_ACTIVE_ORDER_STATUSES = frozenset(
    {
        OrderStatus.DRAFT,
        OrderStatus.VALIDATED,
        OrderStatus.PENDING_SUBMIT,
        OrderStatus.SUBMITTED,
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.CANCEL_PENDING,
        OrderStatus.RECONCILE_REQUIRED,
    }
)


@dataclass(slots=True, frozen=True)
class SymbolTradeStateResolution:
    state: str
    position_quantity: Decimal
    reason_codes: tuple[str, ...]


def resolve_symbol_trade_state(
    *,
    current_state: SymbolTradeStateEntity,
    position_quantity: Decimal,
    latest_buy_order: OrderRequestEntity | None,
    latest_sell_order: OrderRequestEntity | None,
    now_utc: datetime,
) -> SymbolTradeStateResolution:
    active_buy = latest_buy_order is not None and latest_buy_order.status in _ACTIVE_ORDER_STATUSES
    active_sell = latest_sell_order is not None and latest_sell_order.status in _ACTIVE_ORDER_STATUSES
    cooldown_active = (
        current_state.reentry_cooldown_until is not None
        and current_state.reentry_cooldown_until > now_utc
    )

    if position_quantity > 0:
        if active_sell:
            if current_state.state == "exit_pending":
                return SymbolTradeStateResolution(
                    state="exit_pending",
                    position_quantity=position_quantity,
                    reason_codes=("authoritative_position_positive", "active_sell_order"),
                )
            return SymbolTradeStateResolution(
                state="reduce_pending",
                position_quantity=position_quantity,
                reason_codes=("authoritative_position_positive", "active_sell_order"),
            )
        return SymbolTradeStateResolution(
            state="held_active",
            position_quantity=position_quantity,
            reason_codes=("authoritative_position_positive",),
        )

    if active_buy:
        return SymbolTradeStateResolution(
            state="entry_pending",
            position_quantity=Decimal("0"),
            reason_codes=("authoritative_flat_position", "active_buy_order"),
        )

    if cooldown_active:
        return SymbolTradeStateResolution(
            state="flat_cooldown",
            position_quantity=Decimal("0"),
            reason_codes=("authoritative_flat_position", "reentry_cooldown_active"),
        )

    return SymbolTradeStateResolution(
        state="flat",
        position_quantity=Decimal("0"),
        reason_codes=("authoritative_flat_position",),
    )


async def reconcile_account_symbol_trade_states(
    *,
    symbol_trade_state_repo: SymbolTradeStateRepository,
    position_snapshot_repo: PositionSnapshotRepository,
    order_repo: OrderRepository,
    account_id: Any,
    now_utc: datetime,
) -> int:
    states = await symbol_trade_state_repo.list_by_account(account_id)
    if not states:
        return 0

    latest_positions = await position_snapshot_repo.list_latest_by_account(account_id)
    position_by_instrument = {
        snapshot.instrument_id: snapshot
        for snapshot in latest_positions
    }
    orders = await order_repo.list(OrderQuery(account_id=account_id, limit=1000))
    orders_by_instrument: dict[Any, list[OrderRequestEntity]] = {}
    for order in orders:
        orders_by_instrument.setdefault(order.instrument_id, []).append(order)

    updated_count = 0
    for state in states:
        position_snapshot = position_by_instrument.get(state.instrument_id)
        position_quantity = (
            position_snapshot.quantity
            if position_snapshot is not None
            else Decimal("0")
        )
        instrument_orders = orders_by_instrument.get(state.instrument_id, ())
        latest_buy_order = _latest_order_for_side(instrument_orders, "buy")
        latest_sell_order = _latest_order_for_side(instrument_orders, "sell")
        resolution = resolve_symbol_trade_state(
            current_state=state,
            position_quantity=position_quantity,
            latest_buy_order=latest_buy_order,
            latest_sell_order=latest_sell_order,
            now_utc=now_utc,
        )
        if (
            state.state == resolution.state
            and state.position_quantity == resolution.position_quantity
        ):
            continue

        metadata = dict(state.metadata_json)
        metadata["authoritative_state_machine"] = {
            "state": resolution.state,
            "reason_codes": list(resolution.reason_codes),
            "reconciled_at": now_utc.isoformat(),
        }
        await symbol_trade_state_repo.upsert(
            SymbolTradeStateEntity(
                symbol_trade_state_id=state.symbol_trade_state_id,
                account_id=state.account_id,
                instrument_id=state.instrument_id,
                symbol=state.symbol,
                market=state.market,
                state=resolution.state,
                holding_profile=state.holding_profile,
                position_quantity=resolution.position_quantity,
                last_entry_order_request_id=state.last_entry_order_request_id,
                last_exit_order_request_id=state.last_exit_order_request_id,
                last_entry_source_type=state.last_entry_source_type,
                last_entry_at=state.last_entry_at,
                last_reduce_at=state.last_reduce_at,
                last_exit_at=state.last_exit_at,
                minimum_hold_until=state.minimum_hold_until,
                reentry_cooldown_until=state.reentry_cooldown_until,
                sell_cooldown_until=state.sell_cooldown_until,
                last_signal_feature_snapshot_id=state.last_signal_feature_snapshot_id,
                last_decision_context_id=state.last_decision_context_id,
                last_reason_codes=list(resolution.reason_codes),
                thesis_state_hash=state.thesis_state_hash,
                metadata_json=metadata,
                created_at=state.created_at,
                updated_at=now_utc,
            )
        )
        updated_count += 1

    return updated_count


def _latest_order_for_side(
    orders: Sequence[OrderRequestEntity],
    side: str,
) -> OrderRequestEntity | None:
    matched = [order for order in orders if order.side.value == side]
    if not matched:
        return None
    matched.sort(
        key=lambda item: item.updated_at or item.submitted_at or item.created_at or datetime.min,
        reverse=True,
    )
    return matched[0]
