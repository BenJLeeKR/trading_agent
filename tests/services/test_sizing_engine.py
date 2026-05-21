"""Tests for the deterministic sizing engine — pure function, no side effects.

Test matrix
-----------
1.  new_entry basic — BUY/APPROVE pass-through with no constraints
2.  new_entry cash constraint — insufficient cash → cash_limit applied
3.  REDUCE position-aware — position data → reduce from current position
4.  REDUCE exceed position — requested qty > position → capped to position
5.  EXIT full position — position data → full exit at position qty
6.  EXIT no position — no position data → fallback to requested_quantity
7.  max_order_qty — qty > max_order_qty → capped
8.  min_order_qty — qty < min_order_qty → skip ``below_min_qty``
9.  concentration constraint — max_single_position_pct → qty capped
10. lot size rounding — lot_size set → rounded down to nearest multiple
11. AI sizing_hint increase — ``size_mode="increase"`` → qty increased
12. AI sizing_hint fractional_reduce — ``size_mode="fractional_reduce"`` → qty reduced
13. All None fallback — all optional fields None → pure pass-through
14. APPROVE + SELL — treated as exit
15. HOLD / WATCH — non_actionable_decision → skip
16. Max order value — price × qty > max_order_value → capped
17. Cash buffer pct — min_cash_buffer_pct reduces effective cash
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agent_trading.domain.enums import OrderSide
from agent_trading.services.ai_agents.schemas import SizingHint
from agent_trading.services.sizing_engine import (
    SizingInputs,
    calculate_sizing,
)


# ======================================================================
# Helpers
# ======================================================================


def _inputs(
    *,
    decision_type: str = "BUY",
    side: OrderSide = OrderSide.BUY,
    requested_quantity: str = "100",
    requested_price: str | None = None,
    sizing_hint: SizingHint | None = None,
    current_position_qty: str | None = None,
    current_position_avg_price: str | None = None,
    available_cash: str | None = None,
    orderable_amount: str | None = None,
    nav: str | None = None,
    max_single_position_pct: str | None = None,
    min_cash_buffer_pct: str | None = None,
    max_order_value: str | None = None,
    min_order_qty: str | None = None,
    max_order_qty: str | None = None,
    lot_size: str | None = None,
    reference_price: str | None = None,
) -> SizingInputs:
    """Factory that converts string kwargs to ``Decimal`` for test readability."""
    kwargs: dict = dict(
        decision_type=decision_type,
        side=side,
        requested_quantity=Decimal(requested_quantity),
    )
    if requested_price is not None:
        kwargs["requested_price"] = Decimal(requested_price)
    if reference_price is not None:
        kwargs["reference_price"] = Decimal(reference_price)
    if sizing_hint is not None:
        kwargs["sizing_hint"] = sizing_hint
    if current_position_qty is not None:
        kwargs["current_position_qty"] = Decimal(current_position_qty)
    if current_position_avg_price is not None:
        kwargs["current_position_avg_price"] = Decimal(current_position_avg_price)
    if available_cash is not None:
        kwargs["available_cash"] = Decimal(available_cash)
    if orderable_amount is not None:
        kwargs["orderable_amount"] = Decimal(orderable_amount)
    if nav is not None:
        kwargs["nav"] = Decimal(nav)
    if max_single_position_pct is not None:
        kwargs["max_single_position_pct"] = Decimal(max_single_position_pct)
    if min_cash_buffer_pct is not None:
        kwargs["min_cash_buffer_pct"] = Decimal(min_cash_buffer_pct)
    if max_order_value is not None:
        kwargs["max_order_value"] = Decimal(max_order_value)
    if min_order_qty is not None:
        kwargs["min_order_qty"] = Decimal(min_order_qty)
    if max_order_qty is not None:
        kwargs["max_order_qty"] = Decimal(max_order_qty)
    if lot_size is not None:
        kwargs["lot_size"] = Decimal(lot_size)
    return SizingInputs(**kwargs)


# ======================================================================
# 1.  New entry — basic pass-through
# ======================================================================


class TestNewEntry:
    """BUY / APPROVE without constraints — quantity passed through."""

    def test_buy_pass_through(self) -> None:
        """BUY with no constraints returns requested quantity unchanged."""
        result = calculate_sizing(_inputs(decision_type="BUY", side=OrderSide.BUY))
        assert result.quantity == Decimal("100")
        assert result.skip_reason is None
        assert result.applied_constraints == ()

    def test_approve_buy_pass_through(self) -> None:
        """APPROVE + BUY is treated as new entry."""
        result = calculate_sizing(
            _inputs(decision_type="APPROVE", side=OrderSide.BUY)
        )
        assert result.quantity == Decimal("100")
        assert result.skip_reason is None


# ======================================================================
# 2.  New entry — cash constraint
# ======================================================================


class TestCashConstraint:
    """BUY orders are capped when available_cash is insufficient."""

    def test_cash_shortage_caps_qty(self) -> None:
        """Available cash of 500 at price 10 → max 50 shares.
        Requested 100 → capped to 50."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="10",
                available_cash="500",
            )
        )
        assert result.quantity == Decimal("50")
        assert "cash_limit" in result.applied_constraints

    def test_cash_sufficient_no_cap(self) -> None:
        """Available cash of 2000 at price 10 → max 200 shares.
        Requested 100 → unchanged."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="10",
                available_cash="2000",
            )
        )
        assert result.quantity == Decimal("100")
        assert "cash_limit" not in result.applied_constraints

    def test_cash_none_skips_constraint(self) -> None:
        """When cash is None, cash constraint is not applied."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="10",
                available_cash=None,
            )
        )
        assert result.quantity == Decimal("100")

    def test_sell_no_cash_constraint(self) -> None:
        """SELL orders (non-BUY side) skip cash constraint."""
        result = calculate_sizing(
            _inputs(
                decision_type="SELL",
                side=OrderSide.SELL,
                requested_quantity="100",
                requested_price="10",
                available_cash="50",
            )
        )
        assert result.quantity == Decimal("100")

    # ── orderable_amount (ord_psbl_amt) priority tests ──

    def test_orderable_amount_negative_blocks_buy(self) -> None:
        """orderable_amount < 0 → BUY blocked entirely (0 qty + constraint)."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="10",
                available_cash="5000",
                orderable_amount="-1000",
            )
        )
        assert result.quantity == Decimal("0")
        assert "orderable_amount_zero" in result.applied_constraints

    def test_orderable_amount_zero_blocks_buy(self) -> None:
        """orderable_amount == 0 → BUY blocked entirely (0 qty + constraint)."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="10",
                available_cash="5000",
                orderable_amount="0",
            )
        )
        assert result.quantity == Decimal("0")
        assert "orderable_amount_zero" in result.applied_constraints

    def test_orderable_amount_positive_used_as_cash_source(self) -> None:
        """orderable_amount > 0 → used as cash source (priority over available_cash)."""
        # available_cash=5000 → max 500 shares at price 10
        # orderable_amount=200 → max 20 shares at price 10
        # Requested 100 → capped to 20 (orderable_amount takes priority)
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="10",
                available_cash="5000",
                orderable_amount="200",
            )
        )
        assert result.quantity == Decimal("20")
        assert "cash_limit" in result.applied_constraints

    def test_orderable_amount_none_fallback_to_available_cash(self) -> None:
        """orderable_amount=None → falls back to available_cash (existing behaviour)."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="10",
                available_cash="500",
                orderable_amount=None,
            )
        )
        assert result.quantity == Decimal("50")
        assert "cash_limit" in result.applied_constraints

    def test_orderable_amount_negative_does_not_block_sell(self) -> None:
        """orderable_amount < 0 → SELL is NOT blocked (non-BUY side)."""
        result = calculate_sizing(
            _inputs(
                decision_type="SELL",
                side=OrderSide.SELL,
                requested_quantity="100",
                requested_price="10",
                available_cash="5000",
                orderable_amount="-1000",
            )
        )
        assert result.quantity == Decimal("100")
        assert "orderable_amount_zero" not in result.applied_constraints


# ======================================================================
# 3.  REDUCE — position-aware
# ======================================================================


class TestReduce:
    """REDUCE decision type uses position data."""

    def test_reduce_from_position(self) -> None:
        """REDUCE with position data → quantity = requested (capped by position)."""
        result = calculate_sizing(
            _inputs(
                decision_type="REDUCE",
                side=OrderSide.SELL,
                requested_quantity="30",
                current_position_qty="100",
                current_position_avg_price="50",
            )
        )
        assert result.quantity == Decimal("30")
        assert result.skip_reason is None

    def test_reduce_exceeds_position_capped(self) -> None:
        """REDUCE with requested qty > position → capped to position."""
        result = calculate_sizing(
            _inputs(
                decision_type="REDUCE",
                side=OrderSide.SELL,
                requested_quantity="200",
                current_position_qty="100",
                current_position_avg_price="50",
            )
        )
        assert result.quantity == Decimal("100")

    def test_reduce_no_position_fallback(self) -> None:
        """REDUCE without position data → fallback to requested_quantity."""
        result = calculate_sizing(
            _inputs(
                decision_type="REDUCE",
                side=OrderSide.SELL,
                requested_quantity="30",
                current_position_qty=None,
            )
        )
        assert result.quantity == Decimal("30")


# ======================================================================
# 4.  EXIT — position-aware
# ======================================================================


class TestExit:
    """EXIT decision type exits full position."""

    def test_exit_full_position(self) -> None:
        """EXIT with position data → quantity = position."""
        result = calculate_sizing(
            _inputs(
                decision_type="EXIT",
                side=OrderSide.SELL,
                requested_quantity="10",
                current_position_qty="100",
                current_position_avg_price="50",
            )
        )
        assert result.quantity == Decimal("100")

    def test_exit_no_position_fallback(self) -> None:
        """EXIT without position data → fallback to requested_quantity."""
        result = calculate_sizing(
            _inputs(
                decision_type="EXIT",
                side=OrderSide.SELL,
                requested_quantity="10",
                current_position_qty=None,
            )
        )
        assert result.quantity == Decimal("10")


# ======================================================================
# 5.  Max order qty constraint
# ======================================================================


class TestMaxOrderQty:
    """max_order_qty caps quantity."""

    def test_qty_exceeds_max_capped(self) -> None:
        """Requested 100 with max_order_qty=50 → capped."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                max_order_qty="50",
            )
        )
        assert result.quantity == Decimal("50")
        assert "max_qty" in result.applied_constraints

    def test_qty_within_max_unchanged(self) -> None:
        """Requested 30 with max_order_qty=50 → unchanged."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="30",
                max_order_qty="50",
            )
        )
        assert result.quantity == Decimal("30")
        assert "max_qty" not in result.applied_constraints


# ======================================================================
# 6.  Min order qty constraint
# ======================================================================


class TestMinOrderQty:
    """min_order_qty rejects orders below threshold."""

    def test_qty_below_min_skipped(self) -> None:
        """Requested 5 with min_order_qty=10 → skip with ``below_min_qty``."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="5",
                min_order_qty="10",
            )
        )
        assert result.quantity == Decimal("0")
        assert result.skip_reason == "below_min_qty"

    def test_qty_above_min_unchanged(self) -> None:
        """Requested 20 with min_order_qty=10 → unchanged."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="20",
                min_order_qty="10",
            )
        )
        assert result.quantity == Decimal("20")


# ======================================================================
# 7.  Position concentration constraint
# ======================================================================


class TestConcentration:
    """max_single_position_pct caps position size relative to NAV."""

    def test_concentration_caps_qty(self) -> None:
        """NAV=10000, max_single=10%, current pos=0 → max value=1000.
        Price=10 → max 100 shares.  Requested 200 → capped to 100."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="200",
                requested_price="10",
                nav="10000",
                max_single_position_pct="10",
                current_position_qty="0",
                current_position_avg_price="0",
            )
        )
        assert result.quantity == Decimal("100")
        assert "position_concentration" in result.applied_constraints

    def test_concentration_remaining_capacity(self) -> None:
        """Existing position of 300 @ 10 = 3000 value.
        NAV=10000, max_single=50% → max value=5000.
        Remaining capacity = 2000.  Price=10 → max 200 more shares.
        Requested 100 → unchanged."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="10",
                nav="10000",
                max_single_position_pct="50",
                current_position_qty="300",
                current_position_avg_price="10",
            )
        )
        assert result.quantity == Decimal("100")
        assert "position_concentration" not in result.applied_constraints

    def test_concentration_exceeded_returns_zero(self) -> None:
        """Existing position already exceeds max → remaining_capacity ≤ 0 → zero."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="10",
                nav="10000",
                max_single_position_pct="5",  # max value = 500
                current_position_qty="60",
                current_position_avg_price="10",  # current value = 600
            )
        )
        assert result.quantity == Decimal("0")
        assert "position_concentration" in result.applied_constraints
        assert result.skip_reason == "zero_after_constraints"


# ======================================================================
# 8.  Lot size rounding
# ======================================================================


class TestLotSize:
    """Lot size rounding floors quantity to nearest multiple."""

    def test_lot_size_rounds_down(self) -> None:
        """lot_size=10, qty=57 → rounded down to 50."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="57",
                lot_size="10",
            )
        )
        assert result.quantity == Decimal("50")

    def test_lot_size_exact_multiple_unchanged(self) -> None:
        """lot_size=10, qty=50 → unchanged."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="50",
                lot_size="10",
            )
        )
        assert result.quantity == Decimal("50")

    def test_lot_size_none_no_rounding(self) -> None:
        """lot_size=None → no rounding applied."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="57",
                lot_size=None,
            )
        )
        assert result.quantity == Decimal("57")


# ======================================================================
# 9.  AI sizing hint — increase
# ======================================================================


class TestAiSizingHintIncrease:
    """AI sizing hint with ``size_mode="increase"`` boosts quantity."""

    def test_increase_applied(self) -> None:
        """size_adjustment_factor=0.5 → qty increased by 50% → 150."""
        hint = SizingHint(size_mode="increase", size_adjustment_factor=0.5)
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                sizing_hint=hint,
            )
        )
        assert result.quantity == Decimal("150")

    def test_increase_zero_factor_no_change(self) -> None:
        """factor=0 → no increase."""
        hint = SizingHint(size_mode="increase", size_adjustment_factor=0.0)
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                sizing_hint=hint,
            )
        )
        assert result.quantity == Decimal("100")


# ======================================================================
# 10. AI sizing hint — fractional_reduce
# ======================================================================


class TestAiSizingHintReduce:
    """AI sizing hint with ``size_mode="fractional_reduce"`` reduces quantity."""

    def test_fractional_reduce_applied(self) -> None:
        """size_adjustment_factor=0.3 → qty reduced by 30% → 70."""
        hint = SizingHint(size_mode="fractional_reduce", size_adjustment_factor=0.3)
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                sizing_hint=hint,
            )
        )
        assert result.quantity == Decimal("70")

    def test_fractional_reduce_redce_alias(self) -> None:
        """``size_mode="reduce"`` is treated the same as fractional_reduce."""
        hint = SizingHint(size_mode="reduce", size_adjustment_factor=0.25)
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                sizing_hint=hint,
            )
        )
        assert result.quantity == Decimal("75")

    def test_fractional_reduce_overridden_by_config(self) -> None:
        """AI hint increases qty, but max_order_qty caps it."""
        hint = SizingHint(size_mode="increase", size_adjustment_factor=0.5)
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                sizing_hint=hint,
                max_order_qty="120",
            )
        )
        assert result.quantity == Decimal("120")
        assert "max_qty" in result.applied_constraints


# ======================================================================
# 11. All None fallback
# ======================================================================


class TestAllNoneFallback:
    """All optional fields as None → the engine passes through quantity unchanged."""

    def test_all_none_pass_through(self) -> None:
        """BUY with only required fields → quantity unchanged."""
        result = calculate_sizing(
            SizingInputs(
                decision_type="APPROVE",
                side=OrderSide.BUY,
                requested_quantity=Decimal("100"),
            )
        )
        assert result.quantity == Decimal("100")
        assert result.applied_constraints == ()
        assert result.skip_reason is None


# ======================================================================
# 12. APPROVE + SELL — treated as exit
# ======================================================================


class TestApproveSell:
    """APPROVE + SELL is treated as a position exit."""

    def test_approve_sell_exits_position(self) -> None:
        """APPROVE + SELL with position data → exit at position qty."""
        result = calculate_sizing(
            _inputs(
                decision_type="APPROVE",
                side=OrderSide.SELL,
                requested_quantity="10",
                current_position_qty="100",
                current_position_avg_price="50",
            )
        )
        assert result.quantity == Decimal("100")

    def test_approve_sell_no_position_fallback(self) -> None:
        """APPROVE + SELL without position → fallback to requested."""
        result = calculate_sizing(
            _inputs(
                decision_type="APPROVE",
                side=OrderSide.SELL,
                requested_quantity="10",
                current_position_qty=None,
            )
        )
        assert result.quantity == Decimal("10")


# ======================================================================
# 13. HOLD / WATCH — non-actionable
# ======================================================================


class TestNonActionable:
    """HOLD and WATCH decisions result in zero quantity."""

    @pytest.mark.parametrize("decision_type", ["HOLD", "WATCH"])
    def test_hold_or_watch_skip(self, decision_type: str) -> None:
        """HOLD/WATCH → quantity=0, skip_reason=non_actionable_decision."""
        result = calculate_sizing(
            SizingInputs(
                decision_type=decision_type,
                side=OrderSide.BUY,
                requested_quantity=Decimal("100"),
            )
        )
        assert result.quantity == Decimal("0")
        assert result.skip_reason == "non_actionable_decision"


# ======================================================================
# 14. Max order value constraint
# ======================================================================


class TestMaxOrderValue:
    """max_order_value caps price × quantity."""

    def test_value_exceeded_caps_qty(self) -> None:
        """price=10, qty=100 → value=1000.  max_order_value=500 → cap to 50."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="10",
                max_order_value="500",
            )
        )
        assert result.quantity == Decimal("50")
        assert "max_order_value" in result.applied_constraints

    def test_value_within_limit_unchanged(self) -> None:
        """price=10, qty=50 → value=500.  max_order_value=1000 → unchanged."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="50",
                requested_price="10",
                max_order_value="1000",
            )
        )
        assert result.quantity == Decimal("50")
        assert "max_order_value" not in result.applied_constraints


# ======================================================================
# 15. Cash buffer percentage
# ======================================================================


class TestCashBuffer:
    """min_cash_buffer_pct reserves a portion of cash."""

    def test_cash_buffer_factor_applied(self) -> None:
        """cash=1000, buffer=20% → effective cash=800.
        Price=10 → max 80 shares.  Requested 100 → capped to 80."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="10",
                available_cash="1000",
                min_cash_buffer_pct="20",
            )
        )
        assert result.quantity == Decimal("80")
        assert "cash_limit" in result.applied_constraints


# ======================================================================
# 16. Max order value in result
# ======================================================================


class TestMaxOrderValueResult:
    """SizingResult.max_order_value is populated when price is available."""

    def test_max_order_value_calculated(self) -> None:
        """price=10, qty=50 → max_order_value=500."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="50",
                requested_price="10",
            )
        )
        assert result.max_order_value == Decimal("500")

    def test_max_order_value_none_when_no_price(self) -> None:
        """price=None → max_order_value=None."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="50",
                requested_price=None,
            )
        )
        assert result.max_order_value is None


# ======================================================================
# 17. Combined constraints (multiple applied)
# ======================================================================


class TestCombinedConstraints:
    """Multiple constraints apply in order, earliest takes precedence."""

    def test_cash_then_concentration(self) -> None:
        """Both cash shortage and concentration apply.
        Cash limits to 50; concentration would allow 80.
        Cash limit is applied first."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="200",
                requested_price="10",
                available_cash="500",   # → max 50 shares
                nav="10000",
                max_single_position_pct="10",  # → would allow 100 shares
                current_position_qty="0",
                current_position_avg_price="0",
            )
        )
        # Cash limits to 50; concentration doesn't further cap
        assert result.quantity == Decimal("50")
        assert "cash_limit" in result.applied_constraints


# ======================================================================
# 18. Config key normalization — legacy flat-key fallback
# ======================================================================
# These tests verify that the sizing engine correctly interprets config
# values regardless of whether they come from the nested ``risk.*`` /
# ``execution.*`` structure or the legacy flat keys.
#
# NOTE: ``_build_sizing_inputs()`` is a method on
# ``DecisionOrchestratorService`` and requires a full context mock.
# The tests below validate the *sizing engine* side (pure function) —
# i.e. that when ``max_single_position_pct`` is correctly resolved and
# passed to ``calculate_sizing()``, the concentration constraint works
# as expected.  The key-resolution logic itself is tested via the
# orchestrator's unit tests.
# ======================================================================


class TestLegacyMaxPositionSizeFallback:
    """``max_single_position_pct`` resolved from legacy flat key
    ``max_position_size`` behaves identically to the nested key."""

    def test_legacy_flat_key_10pct(self) -> None:
        """max_position_size='10' → max_single_position_pct=10%.
        NAV=100M, current_position=0 → allows up to 10M worth of shares."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="200",
                requested_price="100000",   # 100,000 won per share
                nav="100000000",            # 100M NAV
                max_single_position_pct="10",  # 10% = 10M max
                current_position_qty="0",
                current_position_avg_price="0",
            )
        )
        # max_position_value = 100M * 10% = 10M
        # max_additional_qty = 10M / 100,000 = 100
        # Requested 200 → capped to 100
        assert result.quantity == Decimal("100")
        assert "position_concentration" in result.applied_constraints

    def test_nested_key_takes_priority(self) -> None:
        """When both nested ``risk.max_single_position_pct`` and legacy
        ``max_position_size`` are present, nested key wins.
        (This test simulates the orchestrator resolving the nested key
        and passing the correct value to the sizing engine.)"""
        # Simulate nested key resolved to 15%
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="200",
                requested_price="100000",
                nav="100000000",
                max_single_position_pct="15",  # 15% (nested key won)
                current_position_qty="0",
                current_position_avg_price="0",
            )
        )
        # max_position_value = 100M * 15% = 15M
        # max_additional_qty = 15M / 100,000 = 150
        # Requested 200 → capped to 150
        assert result.quantity == Decimal("150")
        assert "position_concentration" in result.applied_constraints


class TestConcentrationConstraintWithPositionValue:
    """Verify the concentration constraint math with real position values."""

    def test_concentration_constraint_with_position_value_check(self) -> None:
        """NAV=100M, max_single_position_pct=10, current_position=5M won,
        new order=100 shares @ 100,000 won.

        max_position_value = 10M
        current_value = 5M
        remaining = 5M
        max_additional_qty = 5M / 100,000 = 50
        Requested 100 → capped to 50."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="100000",
                nav="100000000",
                max_single_position_pct="10",
                current_position_qty="50",       # 50 shares held
                current_position_avg_price="100000",  # avg price 100,000
            )
        )
        # current_value = 50 * 100,000 = 5,000,000
        # max_position_value = 100,000,000 * 10% = 10,000,000
        # remaining = 10,000,000 - 5,000,000 = 5,000,000
        # max_additional_qty = 5,000,000 / 100,000 = 50
        assert result.quantity == Decimal("50")
        assert "position_concentration" in result.applied_constraints

    def test_concentration_constraint_blocks_over_limit(self) -> None:
        """NAV=100M, max_single_position_pct=10, current_position=12M won.
        current_value(12M) > max_position_value(10M) → remaining <= 0
        → qty = 0."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="100000",
                nav="100000000",
                max_single_position_pct="10",
                current_position_qty="120",      # 120 shares held
                current_position_avg_price="100000",  # avg price 100,000
            )
        )
        # current_value = 120 * 100,000 = 12,000,000
        # max_position_value = 100,000,000 * 10% = 10,000,000
        # remaining = 10,000,000 - 12,000,000 = -2,000,000 <= 0
        assert result.quantity == Decimal("0")
        assert "position_concentration" in result.applied_constraints


# ======================================================================
# Orchestrator-path integration tests
# ======================================================================


class TestOrchestratorSizingPath:
    """Simulate orchestrator-path scenarios for concentration constraint.

    These tests use ``calculate_sizing()`` directly (pure function) but
    with input values that mirror what ``_build_sizing_inputs()`` would
    produce when called from ``assemble_and_submit()`` Phase 1.5.
    """

    def test_legacy_key_fallback(self) -> None:
        """Legacy flat key ``max_position_size`` is interpreted as
        ``max_single_position_pct``.

        config_json = {"max_position_size": "10"}
        → max_single_position_pct = 10
        → NAV 100M → max_position_value = 10M
        → current_value = 0, remaining = 10M
        → requested 100 shares at 50,000 = 5M < 10M → passes
        """
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="50000",
                nav="100000000",
                max_single_position_pct="10",
            )
        )
        # 100 * 50,000 = 5,000,000 < 10,000,000 → no constraint
        assert result.quantity == Decimal("100")
        assert "position_concentration" not in result.applied_constraints

    def test_over_limit_blocked(self) -> None:
        """Position already exceeds max_single_position_pct → qty = 0.

        config_json = {"risk": {"max_single_position_pct": "5"}}
        → max_single_position_pct = 5
        → NAV 100M → max_position_value = 5M
        → current: qty=100, avg_price=100,000 → current_value = 10M
        → remaining = 5M - 10M = -5M ≤ 0 → blocked
        """
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="50",
                requested_price="100000",
                nav="100000000",
                max_single_position_pct="5",
                current_position_qty="100",
                current_position_avg_price="100000",
            )
        )
        # current_value = 100 * 100,000 = 10,000,000
        # max_position_value = 100,000,000 * 5% = 5,000,000
        # remaining = 5,000,000 - 10,000,000 = -5,000,000 ≤ 0
        assert result.quantity == Decimal("0")
        assert "position_concentration" in result.applied_constraints

    def test_partial_reduce(self) -> None:
        """Requested qty exceeds remaining capacity → capped.

        config_json = {"risk": {"max_single_position_pct": "10"}}
        → max_single_position_pct = 10
        → NAV 100M → max_position_value = 10M
        → current: qty=30, avg_price=100,000 → current_value = 3M
        → remaining = 10M - 3M = 7M
        → max_additional_qty = 7M / 100,000 = 70
        → requested 100 → capped to 70
        """
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price="100000",
                nav="100000000",
                max_single_position_pct="10",
                current_position_qty="30",
                current_position_avg_price="100000",
            )
        )
        # current_value = 30 * 100,000 = 3,000,000
        # max_position_value = 100,000,000 * 10% = 10,000,000
        # remaining = 10,000,000 - 3,000,000 = 7,000,000
        # max_additional_qty = 7,000,000 / 100,000 = 70
        assert result.quantity == Decimal("70")
        assert "position_concentration" in result.applied_constraints

    def test_under_limit_passes(self) -> None:
        """Requested qty is within remaining capacity → passes through.

        config_json = {"risk": {"max_single_position_pct": "10"}}
        → max_single_position_pct = 10
        → NAV 100M → max_position_value = 10M
        → current: qty=10, avg_price=50,000 → current_value = 500K
        → remaining = 10M - 500K = 9.5M
        → requested 50 at 50,000 = 2.5M < 9.5M → passes
        """
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="50",
                requested_price="50000",
                nav="100000000",
                max_single_position_pct="10",
                current_position_qty="10",
                current_position_avg_price="50000",
            )
        )
        # current_value = 10 * 50,000 = 500,000
        # max_position_value = 100,000,000 * 10% = 10,000,000
        # remaining = 10,000,000 - 500,000 = 9,500,000
        # max_additional_qty = 9,500,000 / 50,000 = 190
        # requested 50 < 190 → passes through
        assert result.quantity == Decimal("50")
        assert "position_concentration" not in result.applied_constraints


class TestNavFallbackFromCashBalance:
    """risk_limit_snapshot=None일 때 cash_balance_snapshot.total_asset에서
    NAV를 fallback 읽어오는지 검증합니다."""

    @pytest.mark.asyncio
    async def test_nav_fallback_from_cash_balance(
        self, in_memory_repos,
    ) -> None:
        """Fallback to cash_balance_snapshot.total_asset when
        risk_limit_snapshot is not available."""
        from datetime import datetime, timezone
        from decimal import Decimal
        from uuid import UUID, uuid4

        from agent_trading.domain.entities import CashBalanceSnapshotEntity
        from agent_trading.domain.enums import OrderSide, OrderType
        from agent_trading.domain.models import SubmitOrderRequest
        from agent_trading.services.decision_orchestrator import (
            AssembledContext,
            DecisionOrchestratorService,
            OrderIntent,
            ScoreResult,
        )

        service = DecisionOrchestratorService(
            repos=in_memory_repos,
            event_interpretation_agent=None,
            ai_risk_agent=None,
            final_decision_agent=None,
        )

        # cash_balance_snapshot with total_asset set
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=UUID("00000000-0000-0000-0000-000000000001"),
            currency="KRW",
            available_cash=Decimal("10000000"),
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="KIS",
            snapshot_at=datetime.now(timezone.utc),
            total_asset=Decimal("50000000"),
            settlement_amount=Decimal("0"),
            total_unrealized_pnl=Decimal("0"),
        )

        ctx = AssembledContext(
            score=ScoreResult(score=75.0),
            position_snapshot=None,
            cash_balance_snapshot=cash_snapshot,
            risk_limit_snapshot=None,  # 핵심: None
        )

        request = SubmitOrderRequest(
            account_ref="test-account",
            client_order_id="test-order-001",
            correlation_id="test-corr-001",
            strategy_id="test-strategy-001",
            symbol="005930",
            market="KRX",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("50000"),
        )

        intent = OrderIntent(
            decision_context_id=None,
            order_intent_id=None,
            request=request,
            context=ctx,
        )

        inputs = service._build_sizing_inputs(intent)
        assert inputs.nav == Decimal("50000000"), (
            f"Expected nav=50000000, got {inputs.nav}"
        )


# ======================================================================
# 19.  MARKET order + reference_price — cash constraint
# ======================================================================


class TestMarketBuyReferencePriceCashConstraint:
    """BUY MARKET + reference_price로 cash constraint가 적용되어야 함."""

    def test_market_buy_cash_constraint_with_reference_price(self) -> None:
        """MARKET BUY: reference_price=60000, orderable_amount=9000000
        → effective_cash = 9000000 * 0.95 = 8550000
        → max_qty = floor(8550000 / 60000) = 142
        Requested 1000 → capped to 142."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="1000",
                requested_price=None,
                reference_price="60000",
                orderable_amount="9000000",
            )
        )
        assert result.quantity == Decimal("142"), (
            f"Expected 142, got {result.quantity}"
        )
        assert "cash_limit" in result.applied_constraints

    def test_market_buy_no_reference_price_skips_cash_constraint(self) -> None:
        """MARKET BUY: reference_price=None → cash constraint skip,
        requested_quantity 유지."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="1000",
                requested_price=None,
                reference_price=None,
                orderable_amount="9000000",
            )
        )
        assert result.quantity == Decimal("1000"), (
            "Cash constraint should be skipped"
        )
        assert "cash_limit" not in result.applied_constraints

    def test_market_buy_zero_orderable_amount_returns_zero(self) -> None:
        """MARKET BUY: orderable_amount=0 → cash constraint가 0을 반환."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="1000",
                requested_price=None,
                reference_price="60000",
                orderable_amount="0",
            )
        )
        assert result.quantity == Decimal("0")
        assert "orderable_amount_zero" in result.applied_constraints

    def test_market_buy_cash_constraint_fallback_to_available_cash(self) -> None:
        """orderable_amount=None → available_cash로 fallback.
        effective_cash = 5000000 * 0.95 = 4750000
        max_qty = floor(4750000 / 60000) = 79
        Requested 1000 → capped to 79."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="1000",
                requested_price=None,
                reference_price="60000",
                orderable_amount=None,
                available_cash="5000000",
            )
        )
        assert result.quantity == Decimal("79"), (
            f"Expected 79, got {result.quantity}"
        )
        assert "cash_limit" in result.applied_constraints


# ======================================================================
# 20.  LIMIT order with reference_price — reference_price 무시됨
# ======================================================================


class TestLimitBuyIgnoresReferencePrice:
    """LIMIT BUY: requested_price가 있으면 reference_price는 영향을 주지 않음."""

    def test_limit_buy_cash_constraint_uses_requested_price_not_reference(self) -> None:
        """LIMIT BUY: requested_price=50000, reference_price=60000,
        orderable_amount=9000000 → effective_cash = 9000000 (safety_factor 1.0)
        → max_qty = floor(9000000 / 50000) = 180
        Requested 1000 → capped to 180."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="1000",
                requested_price="50000",
                reference_price="60000",
                orderable_amount="9000000",
            )
        )
        assert result.quantity == Decimal("180"), (
            f"Expected 180, got {result.quantity}"
        )
        assert "cash_limit" in result.applied_constraints


# ======================================================================
# 21.  SELL MARKET + reference_price — cash constraint 미적용
# ======================================================================


class TestMarketSellNoCashConstraint:
    """SELL MARKET: reference_price가 있어도 cash constraint는 BUY에만 적용."""

    def test_market_sell_ignores_cash_constraint_even_with_reference_price(self) -> None:
        """SELL: cash constraint는 BUY에만 적용되므로 SELL은 skip."""
        result = calculate_sizing(
            _inputs(
                decision_type="SELL",
                side=OrderSide.SELL,
                requested_quantity="100",
                requested_price=None,
                reference_price="60000",
                current_position_qty="100",  # full exit → qty=100
            )
        )
        assert result.quantity == Decimal("100"), (
            "SELL should not apply cash constraint"
        )
        assert "cash_limit" not in result.applied_constraints


# ======================================================================
# 22.  safety_factor — MARKET에만 적용, LIMIT에는 미적용
# ======================================================================


class TestSafetyFactorMarketOnly:
    """safety_factor=0.95는 MARKET(requested_price=None)에만 적용됨."""

    def test_safety_factor_only_for_market_not_limit(self) -> None:
        """MARKET: 1000000 / 10000 * 0.95 = 95
        LIMIT: 1000000 / 10000 = 100
        MARKET qty < LIMIT qty여야 함."""
        market = SizingInputs(
            decision_type="BUY",
            side=OrderSide.BUY,
            requested_quantity=Decimal("1000"),
            requested_price=None,
            reference_price=Decimal("10000"),
            orderable_amount=Decimal("1000000"),
        )
        limit = SizingInputs(
            decision_type="BUY",
            side=OrderSide.BUY,
            requested_quantity=Decimal("1000"),
            requested_price=Decimal("10000"),
            reference_price=None,
            orderable_amount=Decimal("1000000"),
        )
        m_result = calculate_sizing(market)
        l_result = calculate_sizing(limit)
        assert m_result.quantity == Decimal("95"), (
            f"Expected MARKET=95, got {m_result.quantity}"
        )
        assert l_result.quantity == Decimal("100"), (
            f"Expected LIMIT=100, got {l_result.quantity}"
        )
        assert m_result.quantity < l_result.quantity, (
            "MARKET with safety_factor should be less than LIMIT without it"
        )


# ======================================================================
# 23.  MARKET + concentration constraint with reference_price
# ======================================================================


class TestMarketBuyConcentrationWithReferencePrice:
    """MARKET BUY: concentration constraint도 reference_price 기반으로 적용."""

    def test_market_buy_concentration_constraint_with_reference_price(self) -> None:
        """NAV=10000000, max_single=10%, reference_price=50000
        → max_position_value = 10000000 * 0.1 = 1000000
        → max_addl_qty = floor(1000000 / 50000) = 20
        Requested 50 → capped to 20."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="50",
                requested_price=None,
                reference_price="50000",
                nav="10000000",
                max_single_position_pct="10",
            )
        )
        assert result.quantity == Decimal("20"), (
            f"Expected 20, got {result.quantity}"
        )
        assert "position_concentration" in result.applied_constraints


# ======================================================================
# 24.  MARKET + max_order_value with reference_price
# ======================================================================


class TestMarketBuyMaxOrderValueWithReferencePrice:
    """MARKET BUY: max_order_value constraint도 reference_price 기반으로 적용."""

    def test_market_buy_max_order_value_with_reference_price(self) -> None:
        """reference_price=50000, max_order_value=500000
        → max_qty = floor(500000 / 50000) = 10
        Requested 50 → capped to 10."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="50",
                requested_price=None,
                reference_price="50000",
                max_order_value="500000",
            )
        )
        assert result.quantity == Decimal("10"), (
            f"Expected 10, got {result.quantity}"
        )
        assert "max_order_value" in result.applied_constraints


# ======================================================================
# 25.  SizingResult.max_order_value with reference_price
# ======================================================================


class TestMaxOrderValueWithReferencePrice:
    """SizingResult.max_order_value가 reference_price 기반으로 계산되어야 함."""

    def test_max_order_value_with_reference_price(self) -> None:
        """reference_price=50000, qty=10 → max_order_value=500000."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="10",
                requested_price=None,
                reference_price="50000",
            )
        )
        assert result.max_order_value == Decimal("500000"), (
            f"Expected max_order_value=500000, got {result.max_order_value}"
        )

    def test_max_order_value_none_when_no_price_and_no_reference(self) -> None:
        """requested_price=None, reference_price=None → max_order_value=None."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="10",
                requested_price=None,
                reference_price=None,
            )
        )
        assert result.max_order_value is None, (
            f"Expected max_order_value=None, got {result.max_order_value}"
        )


# ======================================================================
# 26.  min_cash_buffer_pct + safety_factor compounding
# ======================================================================


class TestMarketBuyCashBufferAndSafetyFactor:
    """min_cash_buffer_pct와 safety_factor가 함께 적용되어야 함."""

    def test_market_buy_cash_buffer_and_safety_factor(self) -> None:
        """available_cash=1000000, min_cash_buffer=10%, reference_price=50000
        → effective_cash = 1000000 * 0.9 * 0.95 = 855000
        → max_qty = floor(855000 / 50000) = 17
        Requested 100 → capped to 17."""
        result = calculate_sizing(
            _inputs(
                decision_type="BUY",
                side=OrderSide.BUY,
                requested_quantity="100",
                requested_price=None,
                reference_price="50000",
                available_cash="1000000",
                min_cash_buffer_pct="10",
            )
        )
        assert result.quantity == Decimal("17"), (
            f"Expected 17, got {result.quantity}"
        )
        assert "cash_limit" in result.applied_constraints
