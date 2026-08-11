from __future__ import annotations

from decimal import Decimal

from agent_trading.services.loss_cut_shadow import (
    LOSS_CUT_SHADOW_TIER_HARD,
    LOSS_CUT_SHADOW_TIER_SOFT,
    evaluate_loss_cut_shadow,
)

SOFT = Decimal("7")
HARD = Decimal("12")


def test_evaluate_loss_cut_shadow_no_average_price() -> None:
    verdict = evaluate_loss_cut_shadow(
        average_price=None,
        market_price=Decimal("50000"),
        soft_threshold_pct=SOFT,
        hard_threshold_pct=HARD,
    )
    assert verdict.triggered is False
    assert verdict.tier is None
    assert verdict.loss_pct is None
    assert verdict.skipped_reason == "no_average_price"


def test_evaluate_loss_cut_shadow_zero_average_price_treated_as_missing() -> None:
    verdict = evaluate_loss_cut_shadow(
        average_price=Decimal("0"),
        market_price=Decimal("50000"),
        soft_threshold_pct=SOFT,
        hard_threshold_pct=HARD,
    )
    assert verdict.skipped_reason == "no_average_price"


def test_evaluate_loss_cut_shadow_no_market_price() -> None:
    verdict = evaluate_loss_cut_shadow(
        average_price=Decimal("50000"),
        market_price=None,
        soft_threshold_pct=SOFT,
        hard_threshold_pct=HARD,
    )
    assert verdict.triggered is False
    assert verdict.tier is None
    assert verdict.loss_pct is None
    assert verdict.skipped_reason == "no_market_price"


def test_evaluate_loss_cut_shadow_below_soft_threshold_not_triggered() -> None:
    verdict = evaluate_loss_cut_shadow(
        average_price=Decimal("100000"),
        market_price=Decimal("95000"),  # -5% loss
        soft_threshold_pct=SOFT,
        hard_threshold_pct=HARD,
    )
    assert verdict.triggered is False
    assert verdict.tier is None
    assert verdict.loss_pct == Decimal("5")
    assert verdict.skipped_reason is None


def test_evaluate_loss_cut_shadow_soft_threshold_triggered() -> None:
    verdict = evaluate_loss_cut_shadow(
        average_price=Decimal("100000"),
        market_price=Decimal("91000"),  # -9% loss
        soft_threshold_pct=SOFT,
        hard_threshold_pct=HARD,
    )
    assert verdict.triggered is True
    assert verdict.tier == LOSS_CUT_SHADOW_TIER_SOFT
    assert verdict.loss_pct == Decimal("9")


def test_evaluate_loss_cut_shadow_hard_threshold_triggered() -> None:
    verdict = evaluate_loss_cut_shadow(
        average_price=Decimal("100000"),
        market_price=Decimal("85000"),  # -15% loss
        soft_threshold_pct=SOFT,
        hard_threshold_pct=HARD,
    )
    assert verdict.triggered is True
    assert verdict.tier == LOSS_CUT_SHADOW_TIER_HARD
    assert verdict.loss_pct == Decimal("15")


def test_evaluate_loss_cut_shadow_exact_soft_boundary_triggers_soft() -> None:
    verdict = evaluate_loss_cut_shadow(
        average_price=Decimal("100000"),
        market_price=Decimal("93000"),  # exactly -7%
        soft_threshold_pct=SOFT,
        hard_threshold_pct=HARD,
    )
    assert verdict.triggered is True
    assert verdict.tier == LOSS_CUT_SHADOW_TIER_SOFT


def test_evaluate_loss_cut_shadow_exact_hard_boundary_triggers_hard() -> None:
    verdict = evaluate_loss_cut_shadow(
        average_price=Decimal("100000"),
        market_price=Decimal("88000"),  # exactly -12%
        soft_threshold_pct=SOFT,
        hard_threshold_pct=HARD,
    )
    assert verdict.triggered is True
    assert verdict.tier == LOSS_CUT_SHADOW_TIER_HARD


def test_evaluate_loss_cut_shadow_profit_not_triggered() -> None:
    verdict = evaluate_loss_cut_shadow(
        average_price=Decimal("100000"),
        market_price=Decimal("120000"),  # gain, negative loss_pct
        soft_threshold_pct=SOFT,
        hard_threshold_pct=HARD,
    )
    assert verdict.triggered is False
    assert verdict.tier is None
    assert verdict.loss_pct == Decimal("-20")
