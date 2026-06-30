from __future__ import annotations

import logging
from datetime import datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from agent_trading.domain.enums import OrderSide, OrderStatus, PipelineStopReason
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import AccountLookup, OrderQuery
from agent_trading.services.holding_profile_policy import resolve_policy_timestamp
from agent_trading.services.reverse_trade_hysteresis import (
    evaluate_recent_reverse_trade,
)
from agent_trading.services.validators import ValidationResult

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
DEFAULT_PRE_AI_BUY_MIN_ORDERABLE_AMOUNT = Decimal("500000")
HELD_POSITION_SKIP_HOLD_TTL = timedelta(minutes=20)
HELD_POSITION_SKIP_EVENT_LOOKBACK = timedelta(minutes=30)
HELD_POSITION_SKIP_ORDER_COOLDOWN = timedelta(minutes=20)
SAME_SYMBOL_REENTRY_COOLDOWN = timedelta(minutes=20)
HELD_POSITION_SKIP_DISABLE_AFTER = dtime(14, 30)
_SELL_COOLDOWN_ELIGIBLE_STATUSES = {
    OrderStatus.DRAFT,
    OrderStatus.VALIDATED,
    OrderStatus.PENDING_SUBMIT,
    OrderStatus.SUBMITTED,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.FILLED,
    OrderStatus.RECONCILE_REQUIRED,
}
_BUY_COOLDOWN_ELIGIBLE_STATUSES = {
    OrderStatus.DRAFT,
    OrderStatus.VALIDATED,
    OrderStatus.PENDING_SUBMIT,
    OrderStatus.SUBMITTED,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.FILLED,
    OrderStatus.RECONCILE_REQUIRED,
}


def _normalize_enum_value(value: object | None) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value)).lower()


async def _get_current_signal_feature_snapshot_id(
    repos: RepositoryContainer,
    *,
    instrument_id: Any,
) -> str | None:
    if instrument_id is None:
        return None
    try:
        snapshot = await repos.signal_feature_snapshots.get_latest_by_instrument(
            instrument_id=instrument_id,
            timeframe="1d",
        )
    except Exception:
        logger.exception(
            "Pre-AI gate signal feature lookup failed: instrument_id=%s",
            instrument_id,
        )
        return None
    if snapshot is None:
        return None
    return str(snapshot.signal_feature_snapshot_id)


async def _get_latest_recent_held_decision(
    repos: RepositoryContainer,
    *,
    symbol: str,
    cutoff: datetime,
    db_conn: Any | None,
    side: str,
    source_type: str | None = "held_position",
) -> tuple[str | None, datetime | None, Decimal | None, str | None, Decimal | None]:
    """최근 판단 1건과 앵커된 포지션/feature를 함께 조회한다."""
    if db_conn is not None:
        if source_type is None:
            row = await db_conn.fetchrow(
                """
                SELECT
                    td.decision_type,
                    td.created_at,
                    ps.quantity AS anchored_position_qty,
                    dc.signal_feature_snapshot_id,
                    td.decision_json -> 'expected_value_gate' ->> 'edge_after_cost_bps'
                      AS anchored_edge_after_cost_bps
                FROM trading.trade_decisions td
                LEFT JOIN trading.decision_contexts dc
                  ON dc.decision_context_id = td.decision_context_id
                LEFT JOIN trading.position_snapshots ps
                  ON ps.position_snapshot_id = dc.position_snapshot_id
                WHERE td.symbol = $1
                  AND LOWER(CAST(td.side AS text)) = $2
                  AND td.created_at >= $3
                ORDER BY td.created_at DESC
                LIMIT 1
                """,
                symbol,
                side,
                cutoff,
            )
        else:
            row = await db_conn.fetchrow(
                """
                SELECT
                    td.decision_type,
                    td.created_at,
                    ps.quantity AS anchored_position_qty,
                    dc.signal_feature_snapshot_id,
                    td.decision_json -> 'expected_value_gate' ->> 'edge_after_cost_bps'
                      AS anchored_edge_after_cost_bps
                FROM trading.trade_decisions td
                LEFT JOIN trading.decision_contexts dc
                  ON dc.decision_context_id = td.decision_context_id
                LEFT JOIN trading.position_snapshots ps
                  ON ps.position_snapshot_id = dc.position_snapshot_id
                WHERE td.symbol = $1
                  AND td.source_type = $2
                  AND LOWER(CAST(td.side AS text)) = $3
                  AND td.created_at >= $4
                ORDER BY td.created_at DESC
                LIMIT 1
                """,
                symbol,
                source_type,
                side,
                cutoff,
            )
        if row is None:
            return None, None, None, None, None
        return (
            _normalize_enum_value(row["decision_type"]),
            row["created_at"],
            row["anchored_position_qty"],
            str(row["signal_feature_snapshot_id"])
            if row["signal_feature_snapshot_id"] is not None
            else None,
            Decimal(str(row["anchored_edge_after_cost_bps"]))
            if row["anchored_edge_after_cost_bps"] not in (None, "")
            else None,
        )

    decisions = await repos.trade_decisions.list_all()
    filtered = [
        decision
        for decision in decisions
        if decision.symbol == symbol
        and (source_type is None or decision.source_type == source_type)
        and _normalize_enum_value(decision.side) == side
        and decision.created_at >= cutoff
    ]
    if not filtered:
        return None, None, None, None, None

    latest = max(filtered, key=lambda item: item.created_at)
    anchored_position_qty: Decimal | None = None
    anchored_signal_feature_snapshot_id: str | None = None
    anchored_edge_after_cost_bps: Decimal | None = None
    if latest.decision_context_id is not None:
        context = await repos.decision_contexts.get(latest.decision_context_id)
        if context is not None:
            if context.position_snapshot_id is not None:
                snapshot = await repos.position_snapshots.get(context.position_snapshot_id)
                if snapshot is not None:
                    anchored_position_qty = snapshot.quantity
            if context.signal_feature_snapshot_id is not None:
                anchored_signal_feature_snapshot_id = str(
                    context.signal_feature_snapshot_id
                )
    expected_value_gate = latest.decision_json.get("expected_value_gate")
    if isinstance(expected_value_gate, dict):
        edge_value = expected_value_gate.get("edge_after_cost_bps")
        if edge_value not in (None, ""):
            try:
                anchored_edge_after_cost_bps = Decimal(str(edge_value))
            except Exception:
                anchored_edge_after_cost_bps = None

    return (
        _normalize_enum_value(latest.decision_type),
        latest.created_at,
        anchored_position_qty,
        anchored_signal_feature_snapshot_id,
        anchored_edge_after_cost_bps,
    )


async def evaluate_pre_ai_skip_reason(
    repos: RepositoryContainer,
    *,
    account_alias: str,
    symbol: str,
    market: str,
    source_type: str,
    remaining_general_buy_budget: int | None = None,
    db_conn: Any | None = None,
    now_utc: datetime | None = None,
    min_orderable_amount: Decimal = DEFAULT_PRE_AI_BUY_MIN_ORDERABLE_AMOUNT,
) -> tuple[str | None, dict[str, str | None]]:
    """기존 호환용 pre-AI skip reason 반환 API."""
    validation_result, details = await evaluate_pre_ai_validation_result(
        repos,
        account_alias=account_alias,
        symbol=symbol,
        market=market,
        source_type=source_type,
        remaining_general_buy_budget=remaining_general_buy_budget,
        db_conn=db_conn,
        now_utc=now_utc,
        min_orderable_amount=min_orderable_amount,
    )
    if validation_result is None:
        return None, details
    return validation_result.stop_reason, details


async def evaluate_pre_ai_validation_result(
    repos: RepositoryContainer,
    *,
    account_alias: str,
    symbol: str,
    market: str,
    source_type: str,
    remaining_general_buy_budget: int | None = None,
    db_conn: Any | None = None,
    now_utc: datetime | None = None,
    min_orderable_amount: Decimal = DEFAULT_PRE_AI_BUY_MIN_ORDERABLE_AMOUNT,
) -> tuple[ValidationResult | None, dict[str, str | None]]:
    """Return a deterministic pre-AI validation result to save LLM tokens."""
    details: dict[str, str | None] = {}

    def _blocked(stop_reason: str) -> tuple[ValidationResult, dict[str, str | None]]:
        return (
            ValidationResult.blocked(
                rule_set_version="pre_ai_gate_v1",
                blocking_rule_codes=[stop_reason],
                rule_results={
                    "account_alias": account_alias,
                    "symbol": symbol,
                    "market": market,
                    "source_type": source_type,
                    "stop_reason": stop_reason,
                    "details": dict(details),
                },
                stop_reason=stop_reason,
            ),
            details,
        )

    try:
        account = await repos.accounts.find_one(
            AccountLookup(account_alias=account_alias)
        )
    except Exception:
        logger.exception(
            "Pre-AI skip gate account lookup failed: account_alias=%s symbol=%s",
            account_alias,
            symbol,
        )
        return None, details

    if account is None:
        return None, details

    instrument = None
    try:
        instrument = await repos.instruments.get_by_symbol(
            symbol=symbol,
            market_code=market,
        )
    except Exception:
        logger.exception(
            "Pre-AI gate instrument lookup failed: symbol=%s market=%s source_type=%s",
            symbol,
            market,
            source_type,
        )
        return None, details

    matched_qty: Decimal | None = None
    symbol_state = None
    if instrument is not None:
        try:
            snapshots = await repos.position_snapshots.list_latest_by_account(
                account.account_id
            )
        except Exception:
            logger.exception(
            "Pre-AI gate position lookup failed: account_id=%s symbol=%s source_type=%s",
            account.account_id,
            symbol,
            source_type,
        )
            return None, details

        for snapshot in snapshots:
            if snapshot.instrument_id == instrument.instrument_id:
                matched_qty = snapshot.quantity
                break
        symbol_state = await repos.symbol_trade_states.get_by_account_and_instrument(
            account.account_id,
            instrument.instrument_id,
        )

    details["held_quantity"] = str(matched_qty) if matched_qty is not None else None
    policy_payload = (
        dict(symbol_state.metadata_json.get("holding_profile_policy"))
        if symbol_state is not None
        and isinstance(symbol_state.metadata_json.get("holding_profile_policy"), dict)
        else {}
    )
    current_utc = now_utc or datetime.now(timezone.utc)
    authoritative_earliest_reduce_at = resolve_policy_timestamp(
        policy_payload,
        key="earliest_reduce_at",
        fallback_key="minimum_hold_until",
    ) or (symbol_state.minimum_hold_until if symbol_state is not None else None)
    authoritative_earliest_reentry_at = resolve_policy_timestamp(
        policy_payload,
        key="earliest_reentry_at",
        fallback_key="reentry_cooldown_until",
    ) or (symbol_state.reentry_cooldown_until if symbol_state is not None else None)
    details["authoritative_holding_profile"] = (
        symbol_state.holding_profile if symbol_state is not None else None
    )
    details["authoritative_earliest_reduce_at"] = (
        authoritative_earliest_reduce_at.isoformat(timespec="seconds")
        if authoritative_earliest_reduce_at is not None
        else None
    )
    details["authoritative_earliest_reentry_at"] = (
        authoritative_earliest_reentry_at.isoformat(timespec="seconds")
        if authoritative_earliest_reentry_at is not None
        else None
    )

    if source_type == "held_position":
        if matched_qty is None or matched_qty <= 0:
            return _blocked(PipelineStopReason.NO_HELD_POSITION.value)
        if (
            authoritative_earliest_reduce_at is not None
            and authoritative_earliest_reduce_at > current_utc
        ):
            details["holding_profile_reduce_window_active"] = "true"
            return _blocked(PipelineStopReason.HOLDING_PROFILE_EARLIEST_REDUCE_GUARD.value)
        details["holding_profile_reduce_window_active"] = "false"
        held_skip_reason = await evaluate_held_position_skip_reason(
            repos,
            account_id=account.account_id,
            instrument_id=instrument.instrument_id if instrument is not None else None,
            symbol=symbol,
            matched_qty=matched_qty,
            db_conn=db_conn,
            now_utc=now_utc,
        )
        if held_skip_reason is not None:
            details.update(held_skip_reason[1])
            if held_skip_reason[0] is None:
                return None, details
            return _blocked(held_skip_reason[0])
        return None, details

    has_held_position = matched_qty is not None and matched_qty > 0

    if remaining_general_buy_budget is not None:
        details["remaining_general_buy_budget"] = str(remaining_general_buy_budget)
        if remaining_general_buy_budget <= 0 and not has_held_position:
            return _blocked(PipelineStopReason.GENERAL_BUY_BUDGET_EXHAUSTED.value)

    # Cash-based pre-AI gates are only safe for true 신규 진입 후보.
    # If the account already holds the symbol, the later AI path may
    # legitimately decide HOLD/REDUCE/EXIT, so do not suppress that path
    # solely because orderable cash is low or negative.
    if has_held_position:
        details["holding_profile_reentry_window_active"] = "false"
        return None, details

    if (
        authoritative_earliest_reentry_at is not None
        and authoritative_earliest_reentry_at > current_utc
    ):
        details["holding_profile_reentry_window_active"] = "true"
        return _blocked(PipelineStopReason.HOLDING_PROFILE_EARLIEST_REENTRY_GUARD.value)
    details["holding_profile_reentry_window_active"] = "false"

    reentry_skip_reason = await evaluate_same_symbol_reentry_skip_reason(
        repos,
        account_id=account.account_id,
        instrument_id=instrument.instrument_id if instrument is not None else None,
        symbol=symbol,
        source_type=source_type,
        db_conn=db_conn,
        now_utc=now_utc,
    )
    if reentry_skip_reason is not None and reentry_skip_reason[0] is not None:
        details.update(reentry_skip_reason[1])
        return _blocked(reentry_skip_reason[0])

    try:
        cash_snapshot = await repos.cash_balance_snapshots.get_latest_by_account(
            account.account_id
        )
    except Exception:
        logger.exception(
            "Pre-AI BUY gate cash lookup failed: account_id=%s symbol=%s",
            account.account_id,
            symbol,
        )
        return None, details

    if cash_snapshot is None or cash_snapshot.orderable_amount is None:
        return None, details

    fetch_status = str(getattr(cash_snapshot, "fetch_status", "") or "").lower()
    details["cash_fetch_status"] = fetch_status or None
    if fetch_status == "stale":
        details["cash_gate_skipped"] = "stale_snapshot"
        return None, details

    orderable_amount = cash_snapshot.orderable_amount
    details["orderable_amount"] = str(orderable_amount)
    details["threshold"] = str(min_orderable_amount)

    if orderable_amount < 0:
        return _blocked(PipelineStopReason.NEGATIVE_ORDERABLE_AMOUNT.value)
    if orderable_amount <= min_orderable_amount:
        return _blocked(PipelineStopReason.LOW_ORDERABLE_AMOUNT.value)
    return None, details


async def evaluate_held_position_skip_reason(
    repos: RepositoryContainer,
    *,
    account_id: Any,
    instrument_id: Any,
    symbol: str,
    matched_qty: Decimal,
    db_conn: Any | None = None,
    now_utc: datetime | None = None,
) -> tuple[str | None, dict[str, str | None]] | None:
    """Return a conservative held-position pre-AI skip reason."""
    current_utc = now_utc or datetime.now(timezone.utc)
    now_kst = current_utc.astimezone(KST)
    details: dict[str, str | None] = {
        "held_quantity": str(matched_qty),
        "evaluated_at_kst": now_kst.isoformat(timespec="seconds"),
    }
    current_signal_feature_snapshot_id = await _get_current_signal_feature_snapshot_id(
        repos,
        instrument_id=instrument_id,
    )
    details["current_signal_feature_snapshot_id"] = current_signal_feature_snapshot_id
    if now_kst.time() >= HELD_POSITION_SKIP_DISABLE_AFTER:
        details["skip_guard"] = "disabled_after_cutoff"
        return None, details

    recent_events = await repos.external_events.list_by_symbol(
        symbol,
        current_utc - HELD_POSITION_SKIP_EVENT_LOOKBACK,
        include_seeded_news=True,
    )
    details["recent_event_count"] = str(len(recent_events))
    if recent_events:
        return None, details

    recent_orders = await repos.orders.list(
        OrderQuery(
            account_id=account_id,
            created_from=current_utc - HELD_POSITION_SKIP_ORDER_COOLDOWN,
            created_to=current_utc,
            limit=50,
        )
    )
    if instrument_id is not None:
        recent_orders = [
            order for order in recent_orders if order.instrument_id == instrument_id
        ]
    details["recent_order_count"] = str(len(recent_orders))
    recent_buy_orders = [
        order
        for order in recent_orders
        if order.side == OrderSide.BUY
        and order.status in _BUY_COOLDOWN_ELIGIBLE_STATUSES
    ]
    details["recent_buy_order_count"] = str(len(recent_buy_orders))
    if recent_buy_orders:
        latest_buy_order = max(
            recent_buy_orders,
            key=lambda order: order.submitted_at or order.created_at or current_utc,
        )
        details["latest_buy_order_status"] = _normalize_enum_value(
            latest_buy_order.status
        )
        latest_buy_order_at = latest_buy_order.submitted_at or latest_buy_order.created_at
        details["latest_buy_order_at"] = (
            latest_buy_order_at.isoformat(timespec="seconds")
            if latest_buy_order_at is not None
            else None
        )
    else:
        details["latest_buy_order_status"] = None
        details["latest_buy_order_at"] = None
    recent_sell_orders = [
        order
        for order in recent_orders
        if order.side == OrderSide.SELL
        and order.status in _SELL_COOLDOWN_ELIGIBLE_STATUSES
    ]
    details["recent_sell_order_count"] = str(len(recent_sell_orders))
    if recent_sell_orders:
        latest_sell_order = max(
            recent_sell_orders,
            key=lambda order: order.submitted_at or order.created_at or current_utc,
        )
        details["latest_sell_order_status"] = _normalize_enum_value(
            latest_sell_order.status
        )
        latest_sell_order_at = latest_sell_order.submitted_at or latest_sell_order.created_at
        details["latest_sell_order_at"] = (
            latest_sell_order_at.isoformat(timespec="seconds")
            if latest_sell_order_at is not None
            else None
        )
    else:
        details["latest_sell_order_status"] = None
        details["latest_sell_order_at"] = None

    cutoff = current_utc - HELD_POSITION_SKIP_HOLD_TTL
    latest_decision_type, latest_decision_created_at, _, _, _ = (
        await _get_latest_recent_held_decision(
            repos,
            symbol=symbol,
            cutoff=cutoff,
            db_conn=db_conn,
            side="buy",
        )
    )
    details["latest_held_decision_type"] = latest_decision_type
    details["latest_held_decision_at"] = (
        latest_decision_created_at.isoformat(timespec="seconds")
        if latest_decision_created_at is not None
        else None
    )
    (
        latest_buy_decision_type,
        latest_buy_decision_created_at,
        anchored_buy_position_qty,
        latest_buy_signal_feature_snapshot_id,
        latest_buy_edge_after_cost_bps,
    ) = await _get_latest_recent_held_decision(
        repos,
        symbol=symbol,
        cutoff=cutoff,
        db_conn=db_conn,
        side="buy",
        source_type=None,
    )
    details["latest_buy_decision_type"] = latest_buy_decision_type
    details["latest_buy_decision_at"] = (
        latest_buy_decision_created_at.isoformat(timespec="seconds")
        if latest_buy_decision_created_at is not None
        else None
    )
    details["latest_buy_position_qty"] = (
        str(anchored_buy_position_qty) if anchored_buy_position_qty is not None else None
    )
    details["latest_buy_signal_feature_snapshot_id"] = (
        latest_buy_signal_feature_snapshot_id
    )
    details["latest_buy_edge_after_cost_bps"] = (
        str(latest_buy_edge_after_cost_bps)
        if latest_buy_edge_after_cost_bps is not None
        else None
    )
    buy_reverse_trade = evaluate_recent_reverse_trade(
        current_signal_feature_snapshot_id=current_signal_feature_snapshot_id,
        last_signal_feature_snapshot_id=latest_buy_signal_feature_snapshot_id,
        recent_opposite_order_count=len(recent_buy_orders),
        latest_decision_type=latest_buy_decision_type,
        eligible_decision_types={"approve", "buy"},
        cooldown_stop_reason=PipelineStopReason.HELD_POSITION_RECENT_BUY_SELL_COOLDOWN.value,
        details=details,
        snapshot_unchanged_detail_key="buy_signal_feature_snapshot_unchanged",
        activity_flag_detail_key="buy_cooldown_position_unchanged_or_increased",
        require_matching_decision_type=True,
    )
    if (
        recent_buy_orders
        and anchored_buy_position_qty is not None
        and matched_qty >= anchored_buy_position_qty
    ):
        details.update(buy_reverse_trade.details)
        if buy_reverse_trade.blocked and buy_reverse_trade.stop_reason is not None:
            return buy_reverse_trade.stop_reason, details
    else:
        details["buy_cooldown_position_unchanged_or_increased"] = "false"
        details.setdefault("buy_signal_feature_snapshot_unchanged", "false")
    if latest_decision_type == "hold" and not recent_orders:
        return PipelineStopReason.HELD_POSITION_RECENT_HOLD_NO_CHANGE.value, details

    (
        latest_sell_decision_type,
        latest_sell_decision_created_at,
        anchored_position_qty,
        latest_sell_signal_feature_snapshot_id,
        latest_sell_edge_after_cost_bps,
    ) = await _get_latest_recent_held_decision(
        repos,
        symbol=symbol,
        cutoff=cutoff,
        db_conn=db_conn,
        side="sell",
    )
    details["latest_held_sell_decision_type"] = latest_sell_decision_type
    details["latest_held_sell_decision_at"] = (
        latest_sell_decision_created_at.isoformat(timespec="seconds")
        if latest_sell_decision_created_at is not None
        else None
    )
    details["latest_held_sell_position_qty"] = (
        str(anchored_position_qty) if anchored_position_qty is not None else None
    )
    details["latest_held_sell_signal_feature_snapshot_id"] = (
        latest_sell_signal_feature_snapshot_id
    )
    details["latest_held_sell_edge_after_cost_bps"] = (
        str(latest_sell_edge_after_cost_bps)
        if latest_sell_edge_after_cost_bps is not None
        else None
    )
    sell_reverse_trade = evaluate_recent_reverse_trade(
        current_signal_feature_snapshot_id=current_signal_feature_snapshot_id,
        last_signal_feature_snapshot_id=latest_sell_signal_feature_snapshot_id,
        recent_opposite_order_count=len(recent_sell_orders),
        latest_decision_type=latest_sell_decision_type,
        eligible_decision_types={"reduce", "exit", "sell"},
        cooldown_stop_reason=PipelineStopReason.HELD_POSITION_RECENT_RISK_SELL_COOLDOWN.value,
        details=details,
        snapshot_unchanged_detail_key="sell_signal_feature_snapshot_unchanged",
        activity_flag_detail_key="sell_cooldown_position_unchanged_or_reduced",
        require_matching_decision_type=True,
    )
    if (
        recent_sell_orders
        and anchored_position_qty is not None
        and matched_qty <= anchored_position_qty
    ):
        details.update(sell_reverse_trade.details)
        if sell_reverse_trade.blocked and sell_reverse_trade.stop_reason is not None:
            return sell_reverse_trade.stop_reason, details
    else:
        details["sell_cooldown_position_unchanged_or_reduced"] = "false"
        details.setdefault("sell_signal_feature_snapshot_unchanged", "false")
    return None, details


async def evaluate_same_symbol_reentry_skip_reason(
    repos: RepositoryContainer,
    *,
    account_id: Any,
    instrument_id: Any,
    symbol: str,
    source_type: str,
    db_conn: Any | None = None,
    now_utc: datetime | None = None,
) -> tuple[str | None, dict[str, str | None]] | None:
    """최근 SELL/REDUCE/EXIT 직후 동일 종목 신규 BUY 재진입을 억제한다."""
    normalized_source_type = (source_type or "").strip().lower()
    if normalized_source_type not in {"core", "event_overlay", "market_overlay"}:
        return None

    current_utc = now_utc or datetime.now(timezone.utc)
    cutoff = current_utc - SAME_SYMBOL_REENTRY_COOLDOWN
    details: dict[str, str | None] = {
        "reentry_cooldown_minutes": str(
            int(SAME_SYMBOL_REENTRY_COOLDOWN.total_seconds() // 60)
        ),
        "reentry_source_type": normalized_source_type,
    }
    current_signal_feature_snapshot_id = await _get_current_signal_feature_snapshot_id(
        repos,
        instrument_id=instrument_id,
    )
    details["current_signal_feature_snapshot_id"] = current_signal_feature_snapshot_id

    recent_orders = await repos.orders.list(
        OrderQuery(
            account_id=account_id,
            created_from=cutoff,
            created_to=current_utc,
            limit=50,
        )
    )
    if instrument_id is not None:
        recent_orders = [
            order for order in recent_orders if order.instrument_id == instrument_id
        ]
    recent_sell_orders = [
        order
        for order in recent_orders
        if order.side == OrderSide.SELL
        and order.status in _SELL_COOLDOWN_ELIGIBLE_STATUSES
    ]
    details["reentry_recent_sell_order_count"] = str(len(recent_sell_orders))

    (
        latest_sell_decision_type,
        latest_sell_decision_created_at,
        anchored_position_qty,
        latest_sell_signal_feature_snapshot_id,
        latest_sell_edge_after_cost_bps,
    ) = await _get_latest_recent_held_decision(
        repos,
        symbol=symbol,
        cutoff=cutoff,
        db_conn=db_conn,
        side="sell",
    )
    details["reentry_latest_sell_decision_type"] = latest_sell_decision_type
    details["reentry_latest_sell_decision_at"] = (
        latest_sell_decision_created_at.isoformat(timespec="seconds")
        if latest_sell_decision_created_at is not None
        else None
    )
    details["reentry_latest_sell_position_qty"] = (
        str(anchored_position_qty) if anchored_position_qty is not None else None
    )
    details["reentry_latest_sell_signal_feature_snapshot_id"] = (
        latest_sell_signal_feature_snapshot_id
    )
    details["reentry_latest_sell_edge_after_cost_bps"] = (
        str(latest_sell_edge_after_cost_bps)
        if latest_sell_edge_after_cost_bps is not None
        else None
    )
    recent_reentry_events = await repos.external_events.list_by_symbol(
        symbol,
        cutoff,
        include_seeded_news=True,
    )
    reentry_event_novelty_passed = any(
        bool(event.metadata.get("supports_entry"))
        and str(event.metadata.get("novelty") or event.severity or "").strip().lower()
        in {"high", "medium", "surprising", "fresh"}
        for event in recent_reentry_events
    )
    reentry_reverse_trade = evaluate_recent_reverse_trade(
        current_signal_feature_snapshot_id=current_signal_feature_snapshot_id,
        last_signal_feature_snapshot_id=latest_sell_signal_feature_snapshot_id,
        recent_opposite_order_count=len(recent_sell_orders),
        latest_decision_type=latest_sell_decision_type,
        eligible_decision_types={"reduce", "exit", "sell"},
        cooldown_stop_reason=PipelineStopReason.SAME_SYMBOL_REENTRY_COOLDOWN.value,
        details=details,
        snapshot_unchanged_detail_key="reentry_signal_feature_snapshot_unchanged",
        require_matching_decision_type=True,
        event_novelty_passed=reentry_event_novelty_passed,
        event_novelty_label="present" if reentry_event_novelty_passed else "none",
    )
    details.update(reentry_reverse_trade.details)
    if reentry_reverse_trade.blocked and reentry_reverse_trade.stop_reason is not None:
        return (
            reentry_reverse_trade.stop_reason,
            details,
        )
    return None, details
