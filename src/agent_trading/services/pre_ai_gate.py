from __future__ import annotations

import logging
from datetime import datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from agent_trading.domain.enums import PipelineStopReason
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import AccountLookup, OrderQuery

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
DEFAULT_PRE_AI_BUY_MIN_ORDERABLE_AMOUNT = Decimal("500000")
HELD_POSITION_SKIP_HOLD_TTL = timedelta(minutes=20)
HELD_POSITION_SKIP_EVENT_LOOKBACK = timedelta(minutes=30)
HELD_POSITION_SKIP_ORDER_COOLDOWN = timedelta(minutes=20)
HELD_POSITION_SKIP_DISABLE_AFTER = dtime(14, 30)


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
    """Return a deterministic pre-AI skip reason to save LLM tokens."""
    details: dict[str, str | None] = {}
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

    details["held_quantity"] = str(matched_qty) if matched_qty is not None else None

    if source_type == "held_position":
        if matched_qty is None or matched_qty <= 0:
            return PipelineStopReason.NO_HELD_POSITION.value, details
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
            return held_skip_reason[0], details
        return None, details

    has_held_position = matched_qty is not None and matched_qty > 0

    if remaining_general_buy_budget is not None:
        details["remaining_general_buy_budget"] = str(remaining_general_buy_budget)
        if remaining_general_buy_budget <= 0 and not has_held_position:
            return PipelineStopReason.GENERAL_BUY_BUDGET_EXHAUSTED.value, details

    # Cash-based pre-AI gates are only safe for true 신규 진입 후보.
    # If the account already holds the symbol, the later AI path may
    # legitimately decide HOLD/REDUCE/EXIT, so do not suppress that path
    # solely because orderable cash is low or negative.
    if has_held_position:
        return None, details

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

    orderable_amount = cash_snapshot.orderable_amount
    details["orderable_amount"] = str(orderable_amount)
    details["threshold"] = str(min_orderable_amount)

    if orderable_amount < 0:
        return PipelineStopReason.NEGATIVE_ORDERABLE_AMOUNT.value, details
    if orderable_amount <= min_orderable_amount:
        return PipelineStopReason.LOW_ORDERABLE_AMOUNT.value, details
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
    if recent_orders:
        return None, details

    latest_decision_type: str | None = None
    latest_decision_created_at: datetime | None = None
    cutoff = current_utc - HELD_POSITION_SKIP_HOLD_TTL
    if db_conn is not None:
        row = await db_conn.fetchrow(
            """
            SELECT decision_type, created_at
            FROM trading.trade_decisions
            WHERE symbol = $1
              AND source_type = 'held_position'
              AND side = 'buy'
              AND created_at >= $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            symbol,
            cutoff,
        )
        if row is not None:
            latest_decision_type = str(
                getattr(row["decision_type"], "value", row["decision_type"])
            ).lower()
            latest_decision_created_at = row["created_at"]
    else:
        decisions = await repos.trade_decisions.list_all()
        filtered = [
            decision
            for decision in decisions
            if decision.symbol == symbol
            and decision.source_type == "held_position"
            and str(getattr(decision.side, "value", decision.side)).lower() == "buy"
            and decision.created_at >= cutoff
        ]
        if filtered:
            latest = max(filtered, key=lambda item: item.created_at)
            latest_decision_type = str(
                getattr(latest.decision_type, "value", latest.decision_type)
            ).lower()
            latest_decision_created_at = latest.created_at

    details["latest_held_decision_type"] = latest_decision_type
    details["latest_held_decision_at"] = (
        latest_decision_created_at.isoformat(timespec="seconds")
        if latest_decision_created_at is not None
        else None
    )
    if latest_decision_type == "hold":
        return PipelineStopReason.HELD_POSITION_RECENT_HOLD_NO_CHANGE.value, details
    return None, details
