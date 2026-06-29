from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from math import log
from statistics import stdev
from uuid import uuid4

import pytest

from agent_trading.domain.entities import RiskLimitSnapshotEntity
from agent_trading.services.deterministic_var_engine import (
    DeterministicVarPositionInput,
    VAR_Z_SCORE,
    apply_var_assessment_to_risk_limit_snapshot,
    calculate_deterministic_var,
)


def _make_close_prices(values: list[str]) -> tuple[Decimal, ...]:
    return tuple(Decimal(value) for value in values)


def _manual_sigma(close_prices: tuple[Decimal, ...]) -> Decimal:
    returns = [
        log(float(close_prices[idx] / close_prices[idx - 1]))
        for idx in range(1, len(close_prices))
    ]
    return Decimal(str(stdev(returns[-20:])))


def test_calculate_deterministic_var_ready_with_concentration_penalty() -> None:
    symbol_a = DeterministicVarPositionInput(
        symbol="AAA",
        close_prices=_make_close_prices([
            "100", "102", "101", "104", "103", "105", "106",
            "108", "107", "110", "109", "111", "113", "112",
            "115", "114", "117", "116", "118", "121", "120",
        ]),
        held_market_value=Decimal("7000000"),
        pending_buy_exposure=Decimal("1000000"),
        pending_sell_exposure=Decimal("2000000"),
    )
    symbol_b = DeterministicVarPositionInput(
        symbol="BBB",
        close_prices=_make_close_prices([
            "50", "51", "52", "51", "53", "54", "55", "54", "56", "57", "56",
            "58", "59", "60", "59", "61", "62", "61", "63", "64", "65",
        ]),
        held_market_value=Decimal("2000000"),
    )

    assessment = calculate_deterministic_var(
        nav=Decimal("10000000"),
        positions=[symbol_a, symbol_b],
        max_single_position_pct=Decimal("30"),
    )

    expected_mv_a = Decimal("6000000")
    expected_mv_b = Decimal("2000000")
    sigma_a = _manual_sigma(symbol_a.close_prices)
    sigma_b = _manual_sigma(symbol_b.close_prices)
    expected_var_a = (VAR_Z_SCORE * sigma_a * expected_mv_a).quantize(Decimal("0.00000001"))
    expected_var_b = (VAR_Z_SCORE * sigma_b * expected_mv_b).quantize(Decimal("0.00000001"))
    expected_base = expected_var_a + expected_var_b

    assert assessment.status == "ready"
    assert assessment.portfolio_var_1d == expected_base
    assert assessment.largest_var_symbol == "AAA"
    assert assessment.largest_var_contribution_pct is not None
    assert float(assessment.largest_var_contribution_pct) > 50.0
    assert assessment.concentration_penalty_pct == Decimal("100.0000")
    assert assessment.portfolio_var_1d_adjusted == expected_base * Decimal("2")
    assert assessment.symbol_var_json["AAA"] == float(expected_var_a)
    assert set(assessment.symbol_marginal_contribution_json) == {"AAA", "BBB"}


def test_calculate_deterministic_var_insufficient_history() -> None:
    assessment = calculate_deterministic_var(
        nav=Decimal("5000000"),
        positions=[
            DeterministicVarPositionInput(
                symbol="SHORT",
                close_prices=_make_close_prices(["100", "101", "102"]),
                held_market_value=Decimal("1000000"),
            )
        ],
        max_single_position_pct=Decimal("10"),
    )

    assert assessment.status == "insufficient_data"
    assert assessment.portfolio_var_1d is None
    assert assessment.reason_codes == ("insufficient_history",)
    assert assessment.symbol_assessments[0].status == "insufficient_data"


def test_calculate_deterministic_var_zero_variance() -> None:
    assessment = calculate_deterministic_var(
        nav=Decimal("5000000"),
        positions=[
            DeterministicVarPositionInput(
                symbol="FLAT",
                close_prices=_make_close_prices(["100"] * 21),
                held_market_value=Decimal("1000000"),
            )
        ],
        max_single_position_pct=Decimal("10"),
    )

    assert assessment.status == "zero_variance"
    assert assessment.portfolio_var_1d is None
    assert assessment.reason_codes == ("zero_variance",)
    assert assessment.symbol_assessments[0].var_1d == Decimal("0")


def test_apply_var_assessment_to_risk_limit_snapshot() -> None:
    snapshot = RiskLimitSnapshotEntity(
        risk_limit_snapshot_id=uuid4(),
        account_id=uuid4(),
        snapshot_at=datetime.now(timezone.utc),
        nav=Decimal("10000000"),
        cash_available=Decimal("2500000"),
    )
    assessment = calculate_deterministic_var(
        nav=Decimal("10000000"),
        positions=[
            DeterministicVarPositionInput(
                symbol="AAA",
                close_prices=_make_close_prices([
                    "100", "102", "101", "104", "103", "105", "106",
                    "108", "107", "110", "109", "111", "113", "112",
                    "115", "114", "117", "116", "118", "121", "120",
                ]),
                held_market_value=Decimal("4000000"),
            )
        ],
        max_single_position_pct=Decimal("30"),
    )

    enriched = apply_var_assessment_to_risk_limit_snapshot(snapshot, assessment)

    assert enriched.var_status == "ready"
    assert enriched.var_confidence_level == Decimal("0.95")
    assert enriched.var_horizon_days == 1
    assert enriched.var_lookback_days == 20
    assert enriched.portfolio_var_1d is not None
    assert enriched.symbol_var_json["AAA"] > 0
    assert enriched.var_reason_codes == ["phase1_ready"]


def test_calculate_deterministic_var_requires_nav() -> None:
    assessment = calculate_deterministic_var(
        nav=None,
        positions=[],
        max_single_position_pct=Decimal("10"),
    )

    assert assessment.status == "insufficient_data"
    assert assessment.reason_codes == ("nav_missing",)


def test_calculate_deterministic_var_ready_with_no_positions() -> None:
    assessment = calculate_deterministic_var(
        nav=Decimal("5000000"),
        positions=[],
        max_single_position_pct=Decimal("10"),
    )

    assert assessment.status == "ready"
    assert assessment.portfolio_var_1d == Decimal("0E-8")
    assert assessment.portfolio_var_1d_adjusted == Decimal("0E-8")
    assert assessment.reason_codes == ("phase1_ready", "no_positions")
