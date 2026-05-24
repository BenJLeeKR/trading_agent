"""Deterministic backend translation — OrderIntent → SubmitOrderRequest (or None).

This module contains **pure transformation functions only**.  Design rules:

1. **No repository access** — no DB queries, no async repo calls.
2. **No logger** — no logging side effects; callers log if needed.
3. **No settings** — no config, env vars, or runtime context.
4. **No domain entity imports** — only ``SubmitOrderRequest`` (API model).
5. **No AI agent references** — this is deterministic backend logic.

The sole function ``build_submit_order_request_from_decision()`` translates an
``OrderIntent`` produced by ``DecisionOrchestratorService.assemble()`` into a
``SubmitOrderRequest`` that can be passed to ``OrderManager.create_order()``.
When the decision type is non-actionable (HOLD, WATCH, or an unrecognised type),
or the quantity is zero/negative, the function returns ``None``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from agent_trading.domain.enums import DecisionType, OrderSide, EntryStyle
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.services.common_types import (
    AIDecisionInputs,
    AssembledContext,
    OrderIntent,
    ScoreResult,
)

__all__ = [
    "build_submit_order_request_from_decision",
    "resolve_decision_type",
    "resolve_order_side",
    "resolve_entry_style",
    "decimal_or_none",
    "calculate_max_order_value",
    "normalize_decision_type",
    "is_missing_agent_symbol",
]


# ---------------------------------------------------------------------------
# Pure translation function
# ---------------------------------------------------------------------------


def build_submit_order_request_from_decision(
    intent: OrderIntent,
    client_order_id: str | None = None,
) -> SubmitOrderRequest | None:
    """Translate an ``OrderIntent`` into a ``SubmitOrderRequest`` for broker submission.

    This is the **deterministic backend translation** step.  It validates
    that the AI decision is actionable and constructs a valid submission
    request from the assembled intent.

    Parameters
    ----------
    intent : OrderIntent
        The fully assembled order intent from ``DecisionOrchestratorService``.
    client_order_id : str | None
        Optional explicit client order ID.  When ``None``, a deterministic
        ID is generated from the decision context ID.

    Returns
    -------
    SubmitOrderRequest | None
        A valid submission request, or ``None`` when the decision type
        indicates no order should be submitted (HOLD / WATCH / REDUCE with
        no quantity).
    """
    # ── Decision type check: skip non-actionable decisions ──
    decision_type = intent.ai_backend_inputs.decision_type
    actionable_types = {"APPROVE", "BUY", "SELL", "EXIT", "REDUCE", "WATCH"}
    if decision_type not in actionable_types:
        return None

    # WATCH decisions are monitored but never submitted.
    # (Caller is responsible for any logging.)
    if decision_type == "WATCH":
        return None

    # ── Quantity validation ──
    if intent.request.quantity <= 0:
        return None

    # ── Generate client_order_id if not provided ──
    resolved_client_order_id: str
    if client_order_id:
        resolved_client_order_id = client_order_id
    elif intent.decision_context_id is not None:
        # Deterministic: "dc-{short_uuid}-{timestamp_suffix}"
        short = str(intent.decision_context_id).split("-")[0]
        ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:10]
        resolved_client_order_id = f"dc-{short}-{ts}"
    else:
        return None

    # ── Build the SubmitOrderRequest from intent.request ──
    return SubmitOrderRequest(
        account_ref=intent.request.account_ref,
        client_order_id=resolved_client_order_id,
        correlation_id=intent.request.correlation_id,
        strategy_id=intent.request.strategy_id,
        symbol=intent.request.symbol,
        market=intent.request.market,
        side=intent.request.side,
        order_type=intent.request.order_type,
        quantity=intent.request.quantity,
        time_in_force=intent.request.time_in_force,
        price=intent.request.price,
        idempotency_key=intent.request.idempotency_key,
        decision_id=intent.request.decision_id,
        decision_context_id=intent.request.decision_context_id,
        order_intent_id=intent.request.order_intent_id,
        price_band_lower=intent.request.price_band_lower,
        price_band_upper=intent.request.price_band_upper,
        max_slippage_bps=intent.request.max_slippage_bps,
        allow_partial_fill=intent.request.allow_partial_fill,
        client_timestamp=intent.request.client_timestamp,
        metadata=intent.request.metadata,
    )


import decimal


# =============================================================================
# Enum 변환 헬퍼
# =============================================================================


def resolve_decision_type(value: str | None) -> DecisionType:
    """Normalize AI output decision_type to canonical backend contract values."""
    if not value:
        return DecisionType.HOLD
    cleaned = value.strip().lower()
    mapping: dict[str, DecisionType] = {
        "buy": DecisionType.BUY,
        "strong_buy": DecisionType.BUY,
        "sell": DecisionType.SELL,
        "strong_sell": DecisionType.SELL,
        "hold": DecisionType.HOLD,
        "neutral": DecisionType.HOLD,
        "close": DecisionType.CLOSE,
        "reduce": DecisionType.REDUCE,
        "review": DecisionType.HOLD,
    }
    return mapping.get(cleaned, DecisionType.HOLD)


def resolve_order_side(value: str | None, fallback: OrderSide) -> OrderSide:
    """Convert a decision_type string into an OrderSide, falling back to a default."""
    dt = resolve_decision_type(value)
    if dt in (DecisionType.BUY,):
        return OrderSide.BUY
    if dt in (DecisionType.SELL, DecisionType.CLOSE):
        return OrderSide.SELL
    return fallback


def resolve_entry_style(value: str | None, fallback: EntryStyle) -> EntryStyle:
    """Map order_type from AI output to a canonical EntryStyle."""
    if not value:
        return fallback
    cleaned = value.strip().lower()
    if "limit" in cleaned:
        return EntryStyle.LIMIT
    if "market" in cleaned:
        return EntryStyle.MARKET
    return fallback


def decimal_or_none(value: object) -> Decimal | None:
    """Safely convert an arbitrary value to Decimal | None."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, decimal.InvalidOperation):
        return None


def calculate_max_order_value(price: Decimal | None, quantity: Decimal | None) -> Decimal | None:
    """Calculate max order value = price * quantity, floored at 0.

    Returns ``None`` when either *price* or *quantity* is ``None``
    (e.g. MARKET orders where price is not yet known).
    """
    if price is None or quantity is None:
        return None
    return max(price * quantity, Decimal("0"))


# =============================================================================
# AI 출력 정규화 헬퍼 (decision_orchestrator.py에서 이동)
# =============================================================================


def normalize_decision_type(decision_type: str) -> str:
    """Normalize AI output decision_type to canonical backend contract values.

    Maps known drift vocabulary to equivalent canonical values while
    preserving direct matches and existing BUY/SELL handling.

    == Canonical pass-through (그대로 유지) ==
    APPROVE, REJECT, HOLD, WATCH, EXIT, REDUCE
    BUY, SELL  (actionable_types에서 이미 처리 중이므로 보존)

    == Known drift → canonical mapping (대소문자 불변) ==
    entry → APPROVE  (단, side=BUY/SELL이 별도로 존재한다는 전제)
    no_action → HOLD
    no_trade → HOLD
    none → HOLD

    == 대소문자/표기 변형 처리 ==
    - 입력을 strip() + upper()로 정규화 후 매핑
    - ENTRY, entry, Entry → 모두 "ENTRY" → APPROVE
    - NO_TRADE, no_trade, No_Trade → 모두 "NO_TRADE" → HOLD

    == Fallback ==
    Any other unknown value → HOLD (same as existing _resolve_decision_type)
    """
    normalized = decision_type.strip().upper()

    # Direct canonical match — pass through
    if normalized in {
        "APPROVE", "REJECT", "HOLD", "WATCH", "EXIT", "REDUCE",
        "BUY", "SELL",
    }:
        return normalized

    # Known drift vocabulary → canonical mapping
    mapping: dict[str, str] = {
        "ENTRY": "APPROVE",
        "NO_ACTION": "HOLD",
        "NO_TRADE": "HOLD",
        "NONE": "HOLD",
    }
    return mapping.get(normalized, "HOLD")


def is_missing_agent_symbol(value: str | None) -> bool:
    """Return true when an agent omitted or emitted an unknown symbol."""
    if value is None:
        return True
    normalized = value.strip().upper()
    return normalized in {"", "UNKNOWN", "(NOT AVAILABLE)", "N/A", "NONE", "NULL"}
