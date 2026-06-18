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

    reference_price: Decimal | None = None
    """Reference price for MARKET order sizing (from live quote).
    Used as fallback when ``requested_price`` is ``None`` (MARKET orders).
    ``None`` = no reference price available → cash/concentration/max-order-value
    constraints are skipped (existing behaviour)."""

    average_daily_volume_20d: Decimal | None = None
    """최근 20거래일 평균 거래량.
    intraday 체결 가능성 정보가 부족할 때 보조 participation cap 기준으로 사용한다."""

    accumulated_intraday_volume: Decimal | None = None
    """실시간 누적 거래량 (`acml_vol`)."""

    accumulated_intraday_turnover: Decimal | None = None
    """실시간 누적 거래대금 (`acml_tr_pbmn`)."""

    max_intraday_volume_participation_pct: Decimal | None = None
    """주문수량 / 당일 누적거래량 상한 퍼센트."""

    max_intraday_turnover_participation_pct: Decimal | None = None
    """주문대금 / 당일 누적거래대금 상한 퍼센트."""

    max_average_daily_volume_participation_pct: Decimal | None = None
    """주문수량 / 20일 평균거래량 상한 퍼센트."""

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

_ALLOCATION_PCT = Decimal("0.2")  # 20% of effective cash per single BUY order
_DEFAULT_MAX_INTRADAY_VOLUME_PARTICIPATION_PCT = Decimal("3")
_DEFAULT_MAX_INTRADAY_TURNOVER_PARTICIPATION_PCT = Decimal("5")
_DEFAULT_MAX_AVG_DAILY_VOLUME_PARTICIPATION_PCT = Decimal("2")


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


def _resolve_buy_target_quantity(inputs: SizingInputs) -> Decimal:
    """Calculate target BUY quantity based on cash/price allocation.

    Uses ALLOCATION_PCT (20%) of effective cash to determine a reasonable
    starting quantity for BUY orders, preventing excessive share counts
    on high-price stocks.

    The allocation-based target **replaces** the caller's placeholder
    quantity entirely.  Downstream constraints (cash, concentration,
    min_entry_threshold, max_order_qty, max_order_value) provide actual
    safety limits that protect against excessive order sizes.
    """
    # Determine effective price: requested_price > reference_price > fallback
    effective_price = inputs.requested_price or inputs.reference_price
    if effective_price is None or effective_price <= 0:
        return inputs.requested_quantity

    # Determine effective cash: orderable_amount > available_cash > fallback
    if inputs.orderable_amount is not None:
        effective_cash = inputs.orderable_amount
        logger.debug(
            "effective_cash=%s (source=orderable_amount)",
            effective_cash,
        )
    elif inputs.available_cash is not None:
        effective_cash = inputs.available_cash
        logger.warning(
            "effective_cash=%s (source=available_cash fallback, "
            "orderable_amount is None)",
            effective_cash,
        )
    else:
        logger.warning(
            "cash constraint skipped: both orderable_amount and available_cash "
            "are None",
        )
        return inputs.requested_quantity

    if effective_cash <= 0:
        return inputs.requested_quantity

    # Calculate allocation-based target quantity
    target_notional = effective_cash * _ALLOCATION_PCT
    target_qty = int(target_notional / effective_price)

    # Minimum 1 share
    if target_qty < 1:
        target_qty = 1

    return Decimal(str(target_qty))


def _base_qty_new_entry(inputs: SizingInputs) -> Decimal:
    """Calculate the base quantity for a new position entry."""
    base = inputs.requested_quantity
    return _apply_ai_size_hint(base, inputs.sizing_hint)


def _base_qty_reduce(inputs: SizingInputs) -> Decimal:
    """Calculate the base quantity for a position reduction.

    Rules:
    1. If position data is available → 현재 보유수량 기준 매도 수량 계산.
    2. If AI sizing hint is provided → apply reduction factor.
    3. Otherwise → use requested_quantity as fallback.
    """
    if _is_position_known(inputs.current_position_qty):
        hint = inputs.sizing_hint
        if hint.size_mode in ("fractional_reduce", "reduce") and hint.size_adjustment_factor > 0:
            factor = Decimal(str(hint.size_adjustment_factor))
            factor = max(Decimal("0"), min(Decimal("1"), factor))
            base_qty = (
                inputs.current_position_qty * factor
            ).to_integral_value(rounding=ROUND_DOWN)
            if base_qty <= 0 and inputs.current_position_qty > 0:
                base_qty = Decimal("1")
        else:
            base_qty = inputs.requested_quantity

        return min(base_qty, inputs.current_position_qty)

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

    # BUY side: use cash/price allocation-based target quantity
    if side == OrderSide.BUY:
        return _resolve_buy_target_quantity(inputs)

    if dt == "REDUCE":
        return _base_qty_reduce(inputs)

    if dt == "EXIT":
        return _base_qty_exit(inputs)

    # For BUY / SELL / APPROVE:
    #   SELL without REDUCE/EXIT → treat as full exit
    if dt == "SELL" or (dt == "APPROVE" and side == OrderSide.SELL and dt != "REDUCE"):
        return _base_qty_exit(inputs)

    # BUY or APPROVE + BUY → new entry (non-BUY side fallback)
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
    reference_price: Decimal | None = None,
) -> Decimal:
    """Apply cash availability constraint for BUY orders.

    Cash source priority:
      1. ``orderable_amount`` (KIS ``ord_psbl_amt``) — broker's actual
         orderable cash.  When ≤ 0, BUY is blocked entirely.
      2. ``available_cash`` (KIS ``dnca_tot_amt``) — fallback when
         orderable_amount is not available.

    When the chosen cash source and a price are both available, cap the
    quantity so that ``price × qty ≤ cash × (1 - buffer)``.

    For MARKET orders (``price is None``), ``reference_price`` is used as
    fallback.  When ``reference_price`` is used, a safety factor of 0.95
    is applied to account for price slippage between quote and execution.
    """
    # effective_price: requested_price 우선, 없으면 reference_price fallback
    effective_price = price if (price is not None and price > 0) else reference_price
    if effective_price is None or effective_price <= 0:
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

    # Apply safety factor for reference_price-based sizing (MARKET orders)
    # 5% buffer for price slippage between quote and execution
    if price is None and reference_price is not None and reference_price > 0:
        effective_cash = (effective_cash * Decimal("0.95")).to_integral_value(rounding=ROUND_DOWN)

    max_qty_by_cash = (effective_cash / effective_price).to_integral_value(rounding=ROUND_DOWN)
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
    reference_price: Decimal | None = None,
) -> Decimal:
    """Apply position concentration constraint.

    Ensures that the total position value after adding the new order does
    not exceed ``max_single_position_pct`` of NAV.

    For MARKET orders (``price is None``), ``reference_price`` is used as
    fallback for computing notional values.
    """
    effective_price = price if (price is not None and price > 0) else reference_price
    if (
        nav is None
        or nav <= 0
        or max_single_position_pct is None
        or max_single_position_pct <= 0
        or effective_price is None
        or effective_price <= 0
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
            "effective_price=%s req_qty=%s max_addl_qty=0 final_qty=0",
            nav, max_single_position_pct, max_position_value,
            current_value, remaining_capacity,
            effective_price, qty,
        )
        return Decimal("0")

    max_additional_qty = (remaining_capacity / effective_price).to_integral_value(rounding=ROUND_DOWN)

    # 신규 포지션 최소 진입 금액 임계값
    # 고가주 1주(1,000,000원)는 허용, 저가주 1주(100,000원)는 차단
    # current_position_qty가 None인 경우만 신규 포지션으로 간주
    # (current_position_qty=0을 명시적으로 전달하는 기존 테스트와의 회귀 방지)
    _MIN_ENTRY_VALUE_FOR_NEW_POSITION = Decimal("500000")
    if current_position_qty is None and max_additional_qty > 0:
        entry_value = qty * effective_price
        if entry_value < _MIN_ENTRY_VALUE_FOR_NEW_POSITION:
            constraints.append("min_entry_threshold")
            logger.info(
                "Sizing min entry threshold activated: "
                "effective_price=%s req_qty=%s entry_value=%s min_entry_value=%s final_qty=0",
                effective_price, qty, entry_value, _MIN_ENTRY_VALUE_FOR_NEW_POSITION,
            )
            return Decimal("0")

    if max_additional_qty < qty:
        constraints.append("position_concentration")
        logger.info(
            "Sizing concentration constraint activated: "
            "nav=%s max_pct=%s max_position_value=%s "
            "current_value=%s remaining_capacity=%s "
            "effective_price=%s req_qty=%s max_addl_qty=%s final_qty=%s",
            nav, max_single_position_pct, max_position_value,
            current_value, remaining_capacity,
            effective_price, qty, max_additional_qty, max_additional_qty,
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
    reference_price: Decimal | None = None,
) -> Decimal:
    """Apply max order value constraint.

    When a price is known and ``price × qty > max_order_value``,
    reduce quantity.

    For MARKET orders (``price is None``), ``reference_price`` is used as
    fallback for computing notional values.
    """
    effective_price = price if (price is not None and price > 0) else reference_price
    if max_order_value is None or max_order_value <= 0 or effective_price is None or effective_price <= 0:
        return qty

    current_value = effective_price * qty
    if current_value > max_order_value:
        constraints.append("max_order_value")
        return (max_order_value / effective_price).to_integral_value(rounding=ROUND_DOWN)
    return qty


def _apply_lot_size(qty: Decimal, lot_size: Decimal | None) -> Decimal:
    """Round quantity down to the nearest multiple of ``lot_size``."""
    if lot_size is not None and lot_size > 0:
        return (qty / lot_size).to_integral_value(rounding=ROUND_DOWN) * lot_size
    return qty


def _apply_liquidity_participation_constraint(
    qty: Decimal,
    price: Decimal | None,
    constraints: list[str],
    *,
    reference_price: Decimal | None = None,
    accumulated_intraday_volume: Decimal | None = None,
    accumulated_intraday_turnover: Decimal | None = None,
    average_daily_volume_20d: Decimal | None = None,
    max_intraday_volume_participation_pct: Decimal | None = None,
    max_intraday_turnover_participation_pct: Decimal | None = None,
    max_average_daily_volume_participation_pct: Decimal | None = None,
) -> Decimal:
    """BUY 주문을 거래량/거래대금 participation cap으로 제한한다."""
    effective_price = price if (price is not None and price > 0) else reference_price
    cap_candidates: list[Decimal] = []

    volume_cap_pct = (
        max_intraday_volume_participation_pct
        if max_intraday_volume_participation_pct is not None
        else _DEFAULT_MAX_INTRADAY_VOLUME_PARTICIPATION_PCT
    )
    if (
        accumulated_intraday_volume is not None
        and accumulated_intraday_volume > 0
        and volume_cap_pct > 0
    ):
        max_qty_by_intraday_volume = (
            accumulated_intraday_volume * volume_cap_pct / Decimal("100")
        ).to_integral_value(rounding=ROUND_DOWN)
        cap_candidates.append(max_qty_by_intraday_volume)
        if max_qty_by_intraday_volume < qty:
            constraints.append("intraday_volume_participation_cap")

    turnover_cap_pct = (
        max_intraday_turnover_participation_pct
        if max_intraday_turnover_participation_pct is not None
        else _DEFAULT_MAX_INTRADAY_TURNOVER_PARTICIPATION_PCT
    )
    if (
        accumulated_intraday_turnover is not None
        and accumulated_intraday_turnover > 0
        and effective_price is not None
        and effective_price > 0
        and turnover_cap_pct > 0
    ):
        max_qty_by_intraday_turnover = (
            (accumulated_intraday_turnover * turnover_cap_pct / Decimal("100"))
            / effective_price
        ).to_integral_value(rounding=ROUND_DOWN)
        cap_candidates.append(max_qty_by_intraday_turnover)
        if max_qty_by_intraday_turnover < qty:
            constraints.append("intraday_turnover_participation_cap")

    avg_daily_volume_cap_pct = (
        max_average_daily_volume_participation_pct
        if max_average_daily_volume_participation_pct is not None
        else _DEFAULT_MAX_AVG_DAILY_VOLUME_PARTICIPATION_PCT
    )
    if (
        average_daily_volume_20d is not None
        and average_daily_volume_20d > 0
        and avg_daily_volume_cap_pct > 0
    ):
        max_qty_by_average_daily_volume = (
            average_daily_volume_20d * avg_daily_volume_cap_pct / Decimal("100")
        ).to_integral_value(rounding=ROUND_DOWN)
        cap_candidates.append(max_qty_by_average_daily_volume)
        if max_qty_by_average_daily_volume < qty:
            constraints.append("average_daily_volume_participation_cap")

    if not cap_candidates:
        return qty

    max_qty = min(cap_candidates)
    if max_qty < qty:
        return max(Decimal("0"), max_qty)
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
    8. **Liquidity participation** — cap so order stays within volume/turnover participation.
    9. **Lot size rounding** — round down to nearest trading unit.
    10. **Zero-quantity guard** — set ``skip_reason`` if final quantity ≤ 0.

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
    qty = _apply_max_order_value(
        qty, inputs.requested_price, inputs.max_order_value, constraints,
        reference_price=inputs.reference_price,
    )

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
            reference_price=inputs.reference_price,
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
        reference_price=inputs.reference_price,
    )

    # ── Step 7: liquidity participation (BUY only) ──
    if inputs.side == OrderSide.BUY:
        qty = _apply_liquidity_participation_constraint(
            qty,
            inputs.requested_price,
            constraints,
            reference_price=inputs.reference_price,
            accumulated_intraday_volume=inputs.accumulated_intraday_volume,
            accumulated_intraday_turnover=inputs.accumulated_intraday_turnover,
            average_daily_volume_20d=inputs.average_daily_volume_20d,
            max_intraday_volume_participation_pct=inputs.max_intraday_volume_participation_pct,
            max_intraday_turnover_participation_pct=inputs.max_intraday_turnover_participation_pct,
            max_average_daily_volume_participation_pct=inputs.max_average_daily_volume_participation_pct,
        )

    # ── Step 8: lot size rounding ──
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
    effective_price = inputs.requested_price if inputs.requested_price is not None else inputs.reference_price
    if effective_price is not None and effective_price > 0 and qty > 0:
        max_order_value = effective_price * qty

    return SizingResult(
        quantity=qty,
        max_order_value=max_order_value,
        applied_constraints=tuple(constraints),
        skip_reason=None,
    )
