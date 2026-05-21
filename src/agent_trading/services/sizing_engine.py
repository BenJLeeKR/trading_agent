"""Deterministic sizing engine — pure function, no side effects.

Responsibility
--------------
Given an AI decision + account state snapshot + config-driven limits,
calculate the final order quantity deterministically.

Design principles
-----------------
1. **Pure function** — no DB access, no I/O, no async.
2. **Every input is optional** — graceful fallback when data is unavailable.
3. **Applied constraints are tracked** in ``SizingResult.applied_constraints``.
4. **Zero quantity → skip_reason** explaining why the order was rejected.
5. **AI hint is advisory only** — ``SizingHint.size_mode`` and
   ``size_adjustment_factor`` influence the base quantity but are overridden
   by hard config limits.

Integration
-----------
Called from ``DecisionOrchestratorService.assemble_and_submit()`` as
Phase 1.5, between ``assemble()`` and
``build_submit_order_request_from_decision()``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from typing import Sequence

from agent_trading.domain.enums import OrderSide
from agent_trading.services.ai_agents.schemas import SizingHint

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class SizingInputs:
    """Deterministic sizing engine inputs — all data resolved before sizing call.

    Attributes are the minimal set needed for position-aware + config-driven
    sizing.  Every field is optional — the engine falls back gracefully when
    data is unavailable.
    """

    # ── Decision context ────────────────────────────────────────────────
    decision_type: str
    """AI decision type: ``"BUY"``, ``"SELL"``, ``"EXIT"``, ``"REDUCE"``,
    ``"APPROVE"``."""

    side: OrderSide
    """Trade side (``OrderSide.BUY`` or ``OrderSide.SELL``)."""

    requested_quantity: Decimal
    """Original quantity from the assembled request (AI or caller-supplied)."""

    requested_price: Decimal | None = None
    """Original price from the assembled request (or ``None`` for MARKET)."""

    # ── AI sizing hint (advisory only, non-binding) ─────────────────────
    sizing_hint: SizingHint = field(default_factory=SizingHint)
    """Advisory sizing hint from the AI.  ``size_mode`` and
    ``size_adjustment_factor`` influence base quantity but are overridden
    by hard config limits."""

    # ── Position (nullable, for position-aware sizing) ──────────────────
    current_position_qty: Decimal | None = None
    """Current position quantity (``None`` = not queried / unavailable)."""

    current_position_avg_price: Decimal | None = None
    """Average entry price of the current position."""

    # ── Cash (nullable, for cash-aware constraint) ──────────────────────
    available_cash: Decimal | None = None
    """Available cash balance from the latest snapshot (dnca_tot_amt)."""

    orderable_amount: Decimal | None = None
    """Orderable amount from broker (ord_psbl_amt).  Preferred over
    ``available_cash`` when present.  Negative means no buying power."""

    # ── Risk / NAV (nullable, for concentration limit) ──────────────────
    nav: Decimal | None = None
    """Net asset value from the latest risk limit snapshot."""

    # ── Config-driven limits (nullable, from ``config_version.config_json``) ──
    max_single_position_pct: Decimal | None = None
    """``risk.max_single_position_pct`` — max % of NAV a single position
    may represent."""

    min_cash_buffer_pct: Decimal | None = None
    """``risk.min_cash_buffer_pct`` — minimum % of cash to keep reserved."""

    max_order_value: Decimal | None = None
    """Hard cap on the total order value (price × quantity)."""

    min_order_qty: Decimal | None = None
    """Minimum allowed order quantity.  Orders below this are rejected."""

    max_order_qty: Decimal | None = None
    """Maximum allowed order quantity.  Orders above this are capped."""

    lot_size: Decimal | None = None
    """Trading lot / tick unit for quantity rounding.
    When set, final quantity is rounded down to the nearest multiple.
    ``None`` = no rounding."""


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class SizingResult:
    """Output of the deterministic sizing engine.

    Always contains a valid quantity (may be zero when constraints reject
    the order).
    """

    quantity: Decimal
    """Final calculated quantity (≥ 0).  Zero means the order was rejected
    by one or more constraints."""

    max_order_value: Decimal | None = None
    """Calculated maximum order value after all constraints (price × quantity
    when price is available, otherwise ``None``)."""

    applied_constraints: tuple[str, ...] = ()
    """Labels of constraints that were applied (e.g. ``"cash_limit"``,
    ``"position_concentration"``, ``"max_qty"``).  Empty when the requested
    quantity passed all checks unchanged."""

    skip_reason: str | None = None
    """When ``quantity == 0``, a human-readable explanation of why the order
    was rejected (e.g. ``"below_min_qty"``).  ``None`` when the order can
    proceed."""


# ---------------------------------------------------------------------------
# Sizing strategies (internal dispatch helpers)
# ---------------------------------------------------------------------------

_SKIP_DECISION_TYPES: frozenset[str] = frozenset({"HOLD", "WATCH"})


def _is_new_entry(decision_type: str, side: OrderSide) -> bool:
    """Return ``True`` when the decision represents a **new** position entry.

    ``REDUCE`` / ``EXIT`` are never new entries regardless of side.
    ``APPROVE`` + ``BUY`` → new buy entry.
    ``APPROVE`` + ``SELL`` → new sell entry (short).
    ``BUY`` / ``SELL`` (without REDUCE/EXIT) → new entry.
    """
    if decision_type in ("REDUCE", "EXIT"):
        return False
    return True


def _is_position_known(pos_qty: Decimal | None) -> bool:
    """Return ``True`` when a non‑zero position snapshot is available."""
    return pos_qty is not None and pos_qty > 0


# ---------------------------------------------------------------------------
# Position-aware base quantity
# ---------------------------------------------------------------------------


def _apply_ai_size_hint(
    base_qty: Decimal,
    hint: SizingHint,
) -> Decimal:
    """Apply the AI advisory sizing hint to the base quantity.

    The hint is **advisory only** — hard config limits applied later will
    override any AI-derived value.
    """
    if hint.size_mode == "increase" and hint.size_adjustment_factor > 0:
        return (base_qty * (Decimal("1") + Decimal(str(hint.size_adjustment_factor)))).to_integral_value(rounding=ROUND_DOWN)
    if hint.size_mode in ("fractional_reduce", "reduce") and hint.size_adjustment_factor > 0:
        reduction = base_qty * Decimal(str(hint.size_adjustment_factor))
        return (base_qty - reduction).to_integral_value(rounding=ROUND_DOWN)
    # "no_change" or unknown mode → return as-is
    return base_qty


def _base_qty_new_entry(inputs: SizingInputs) -> Decimal:
    """Calculate the base quantity for a new position entry."""
    base = inputs.requested_quantity
    return _apply_ai_size_hint(base, inputs.sizing_hint)


def _base_qty_reduce(inputs: SizingInputs) -> Decimal:
    """Calculate the base quantity for a position reduction.

    Rules:
    1. If position data is available → reduce from current position.
    2. If AI sizing hint is provided → apply reduction factor.
    3. Otherwise → use requested_quantity as fallback.
    """
    if _is_position_known(inputs.current_position_qty):
        hint = inputs.sizing_hint
        if hint.size_mode in ("fractional_reduce", "reduce") and hint.size_adjustment_factor > 0:
            # AI-suggested reduction from current position
            reduction = inputs.current_position_qty * Decimal(str(hint.size_adjustment_factor))
            base_qty = (inputs.current_position_qty - reduction).to_integral_value(rounding=ROUND_DOWN)
        else:
            # No AI reduction hint → use requested_quantity, capped by position
            base_qty = inputs.requested_quantity

        # Never reduce more than the current position
        return min(base_qty, inputs.current_position_qty)

    # Position data unavailable → fallback to requested quantity
    return inputs.requested_quantity


def _base_qty_exit(inputs: SizingInputs) -> Decimal:
    """Calculate the base quantity for a full position exit.

    Rules:
    1. If position data is available → exit full position.
    2. Otherwise → use requested_quantity as fallback.
    """
    if _is_position_known(inputs.current_position_qty):
        return inputs.current_position_qty
    return inputs.requested_quantity


def _resolve_base_quantity(inputs: SizingInputs) -> Decimal:
    """Dispatch to the correct sizing strategy based on decision type + side.

    Returns the **base quantity** before config‑driven constraints.
    Base quantity is always ≥ 0.
    """
    dt = inputs.decision_type
    side = inputs.side

    # Non-actionable → zero
    if dt in _SKIP_DECISION_TYPES:
        return Decimal("0")

    if dt == "REDUCE":
        return _base_qty_reduce(inputs)

    if dt == "EXIT":
        return _base_qty_exit(inputs)

    # For BUY / SELL / APPROVE:
    #   SELL without REDUCE/EXIT → treat as full exit
    if dt == "SELL" or (dt == "APPROVE" and side == OrderSide.SELL and dt != "REDUCE"):
        return _base_qty_exit(inputs)

    # BUY or APPROVE + BUY → new entry
    return _base_qty_new_entry(inputs)


# ---------------------------------------------------------------------------
# Config-driven constraint application
# ---------------------------------------------------------------------------


def _apply_cash_constraint(
    qty: Decimal,
    price: Decimal | None,
    available_cash: Decimal | None,
    min_cash_buffer_pct: Decimal | None,
    constraints: list[str],
    orderable_amount: Decimal | None = None,
) -> Decimal:
    """Apply cash availability constraint for BUY orders.

    Cash source priority:
      1. ``orderable_amount`` (KIS ``ord_psbl_amt``) — broker's actual
         orderable cash.  When ≤ 0, BUY is blocked entirely.
      2. ``available_cash`` (KIS ``dnca_tot_amt``) — fallback when
         orderable_amount is not available.

    When the chosen cash source and ``price`` are both available, cap the
    quantity so that ``price × qty ≤ cash × (1 - buffer)``.
    """
    if price is None or price <= 0:
        return qty

    # ── Determine effective cash source ──
    # Priority: orderable_amount > available_cash
    if orderable_amount is not None:
        if orderable_amount <= 0:
            constraints.append("orderable_amount_zero")
            logger.info("BUY blocked: orderable_amount=%s <= 0", orderable_amount)
            return Decimal("0")
        effective_cash = orderable_amount
    elif available_cash is not None:
        # orderable_amount가 None (KIS paper API 미지원) → available_cash fallback
        # 실전 환경(KIS real API)에서는 ord_psbl_amt가 정상 제공되므로
        # 이 fallback은 paper 환경에서만 동작함
        logger.info(
            "orderable_amount=None (KIS paper API), falling back to available_cash=%s",
            available_cash,
        )
        effective_cash = available_cash
    else:
        return qty  # No cash info available — skip constraint

    if min_cash_buffer_pct is not None and min_cash_buffer_pct > 0:
        effective_cash = effective_cash * (Decimal("1") - min_cash_buffer_pct / Decimal("100"))

    max_qty_by_cash = (effective_cash / price).to_integral_value(rounding=ROUND_DOWN)
    if max_qty_by_cash < qty:
        constraints.append("cash_limit")
        return max_qty_by_cash
    return qty


def _apply_concentration_constraint(
    qty: Decimal,
    price: Decimal | None,
    current_position_qty: Decimal | None,
    current_position_avg_price: Decimal | None,
    nav: Decimal | None,
    max_single_position_pct: Decimal | None,
    constraints: list[str],
) -> Decimal:
    """Apply position concentration constraint.

    Ensures that the total position value after adding the new order does
    not exceed ``max_single_position_pct`` of NAV.
    """
    if (
        nav is None
        or nav <= 0
        or max_single_position_pct is None
        or max_single_position_pct <= 0
        or price is None
        or price <= 0
    ):
        return qty

    max_position_value = nav * max_single_position_pct / Decimal("100")

    current_value = Decimal("0")
    if current_position_qty is not None and current_position_avg_price is not None:
        current_value = current_position_qty * current_position_avg_price

    remaining_capacity = max_position_value - current_value
    if remaining_capacity <= 0:
        constraints.append("position_concentration")
        logger.info(
            "Sizing concentration constraint activated: "
            "nav=%s max_pct=%s max_position_value=%s "
            "current_value=%s remaining_capacity=%s "
            "price=%s req_qty=%s max_addl_qty=0 final_qty=0",
            nav, max_single_position_pct, max_position_value,
            current_value, remaining_capacity,
            price, qty,
        )
        return Decimal("0")

    max_additional_qty = (remaining_capacity / price).to_integral_value(rounding=ROUND_DOWN)
    if max_additional_qty < qty:
        constraints.append("position_concentration")
        logger.info(
            "Sizing concentration constraint activated: "
            "nav=%s max_pct=%s max_position_value=%s "
            "current_value=%s remaining_capacity=%s "
            "price=%s req_qty=%s max_addl_qty=%s final_qty=%s",
            nav, max_single_position_pct, max_position_value,
            current_value, remaining_capacity,
            price, qty, max_additional_qty, max_additional_qty,
        )
        return max_additional_qty
    return qty


def _apply_qty_bounds(
    qty: Decimal,
    max_order_qty: Decimal | None,
    min_order_qty: Decimal | None,
    constraints: list[str],
) -> Decimal:
    """Apply min/max order quantity bounds."""
    if max_order_qty is not None and max_order_qty > 0 and qty > max_order_qty:
        constraints.append("max_qty")
        qty = max_order_qty

    if min_order_qty is not None and min_order_qty > 0 and qty < min_order_qty:
        constraints.append("min_qty")
        return Decimal("0")

    return qty


def _apply_max_order_value(
    qty: Decimal,
    price: Decimal | None,
    max_order_value: Decimal | None,
    constraints: list[str],
) -> Decimal:
    """Apply max order value constraint.

    When ``price`` is known and ``price × qty > max_order_value``,
    reduce quantity.
    """
    if max_order_value is None or max_order_value <= 0 or price is None or price <= 0:
        return qty

    current_value = price * qty
    if current_value > max_order_value:
        constraints.append("max_order_value")
        return (max_order_value / price).to_integral_value(rounding=ROUND_DOWN)
    return qty


def _apply_lot_size(qty: Decimal, lot_size: Decimal | None) -> Decimal:
    """Round quantity down to the nearest multiple of ``lot_size``."""
    if lot_size is not None and lot_size > 0:
        return (qty / lot_size).to_integral_value(rounding=ROUND_DOWN) * lot_size
    return qty


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def calculate_sizing(inputs: SizingInputs) -> SizingResult:
    """Deterministic sizing engine: position-aware → config-driven.

    Decision pipeline (applied in order):

    1. **Decision type dispatch** — map decision to sizing strategy.
    2. **Position-aware base quantity** — calculate starting quantity from
       position data and AI sizing hint.
    3. **Max order value** — cap ``price × qty`` if configured.
    4. **Max order qty** — cap absolute quantity if configured.
    5. **Min order qty** — reject if below configured minimum.
    6. **Cash availability** — cap for BUY orders based on available cash.
    7. **Position concentration** — cap so total position ≤ % of NAV.
    8. **Lot size rounding** — round down to nearest trading unit.
    9. **Zero-quantity guard** — set ``skip_reason`` if final quantity ≤ 0.

    Parameters
    ----------
    inputs : SizingInputs
        All resolved inputs for the sizing calculation.

    Returns
    -------
    SizingResult
        The final quantity, optional max order value, applied constraints,
        and optional skip reason.
    """
    constraints: list[str] = []

    # ── Step 1 & 2: decision dispatch + position-aware base qty ──
    qty = _resolve_base_quantity(inputs)
    if qty <= 0:
        return SizingResult(
            quantity=Decimal("0"),
            max_order_value=None,
            applied_constraints=tuple(constraints),
            skip_reason="non_actionable_decision",
        )

    # ── Step 3: max order value ──
    qty = _apply_max_order_value(qty, inputs.requested_price, inputs.max_order_value, constraints)

    # ── Step 4: max order qty ──
    qty = _apply_qty_bounds(qty, inputs.max_order_qty, inputs.min_order_qty, constraints)

    # If already zero after bounds, return early
    if qty <= 0:
        return SizingResult(
            quantity=Decimal("0"),
            max_order_value=None,
            applied_constraints=tuple(constraints),
            skip_reason="below_min_qty",
        )

    # ── Step 5: cash availability (BUY only) ──
    if inputs.side == OrderSide.BUY:
        qty = _apply_cash_constraint(
            qty,
            inputs.requested_price,
            inputs.available_cash,
            inputs.min_cash_buffer_pct,
            constraints,
            orderable_amount=inputs.orderable_amount,
        )

    # ── Step 6: position concentration ──
    qty = _apply_concentration_constraint(
        qty,
        inputs.requested_price,
        inputs.current_position_qty,
        inputs.current_position_avg_price,
        inputs.nav,
        inputs.max_single_position_pct,
        constraints,
    )

    # ── Step 7: lot size rounding ──
    qty = _apply_lot_size(qty, inputs.lot_size)

    # ── Step 8: zero-quantity guard ──
    if qty <= 0:
        return SizingResult(
            quantity=Decimal("0"),
            max_order_value=None,
            applied_constraints=tuple(constraints),
            skip_reason="zero_after_constraints",
        )

    # ── Calculate max order value ──
    max_order_value: Decimal | None = None
    if inputs.requested_price is not None and qty > 0:
        max_order_value = inputs.requested_price * qty

    return SizingResult(
        quantity=qty,
        max_order_value=max_order_value,
        applied_constraints=tuple(constraints),
        skip_reason=None,
    )
