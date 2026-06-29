from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from math import log
from statistics import stdev
from typing import Sequence

from agent_trading.domain.entities import RiskLimitSnapshotEntity

VAR_CONFIDENCE_LEVEL = Decimal("0.95")
VAR_Z_SCORE = Decimal("1.65")
VAR_HORIZON_DAYS = 1
VAR_LOOKBACK_DAYS = 20
_PCT_SCALE = Decimal("0.0001")
_NUMERIC_SCALE = Decimal("0.00000001")


@dataclass(slots=True, frozen=True)
class DeterministicVarPositionInput:
    symbol: str
    close_prices: tuple[Decimal, ...]
    held_market_value: Decimal = Decimal("0")
    pending_buy_exposure: Decimal = Decimal("0")
    pending_sell_exposure: Decimal = Decimal("0")
    reference_price: Decimal | None = None


@dataclass(slots=True, frozen=True)
class DeterministicVarSymbolAssessment:
    symbol: str
    effective_market_value: Decimal
    sigma: Decimal | None
    var_1d: Decimal
    marginal_contribution_pct: Decimal
    weight_pct: Decimal | None
    concentration_penalty_pct: Decimal
    status: str
    reason_codes: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class DeterministicVarAssessment:
    confidence_level: Decimal
    horizon_days: int
    lookback_days: int
    portfolio_var_1d: Decimal | None
    portfolio_var_1d_adjusted: Decimal | None
    largest_var_symbol: str | None
    largest_var_contribution_pct: Decimal | None
    concentration_penalty_pct: Decimal | None
    status: str
    reason_codes: tuple[str, ...]
    symbol_assessments: tuple[DeterministicVarSymbolAssessment, ...] = ()

    @property
    def symbol_var_json(self) -> dict[str, float]:
        return {
            item.symbol: float(item.var_1d)
            for item in self.symbol_assessments
            if item.var_1d > 0
        }

    @property
    def symbol_marginal_contribution_json(self) -> dict[str, float]:
        return {
            item.symbol: float(item.marginal_contribution_pct)
            for item in self.symbol_assessments
            if item.marginal_contribution_pct > 0
        }


def calculate_deterministic_var(
    *,
    nav: Decimal | None,
    positions: Sequence[DeterministicVarPositionInput],
    max_single_position_pct: Decimal | None,
) -> DeterministicVarAssessment:
    reason_codes: list[str] = []
    if nav is None or nav <= 0:
        return DeterministicVarAssessment(
            confidence_level=VAR_CONFIDENCE_LEVEL,
            horizon_days=VAR_HORIZON_DAYS,
            lookback_days=VAR_LOOKBACK_DAYS,
            portfolio_var_1d=None,
            portfolio_var_1d_adjusted=None,
            largest_var_symbol=None,
            largest_var_contribution_pct=None,
            concentration_penalty_pct=None,
            status="insufficient_data",
            reason_codes=("nav_missing",),
            symbol_assessments=(),
        )
    if not positions:
        return DeterministicVarAssessment(
            confidence_level=VAR_CONFIDENCE_LEVEL,
            horizon_days=VAR_HORIZON_DAYS,
            lookback_days=VAR_LOOKBACK_DAYS,
            portfolio_var_1d=Decimal("0").quantize(_NUMERIC_SCALE),
            portfolio_var_1d_adjusted=Decimal("0").quantize(_NUMERIC_SCALE),
            largest_var_symbol=None,
            largest_var_contribution_pct=Decimal("0.0000"),
            concentration_penalty_pct=Decimal("0.0000"),
            status="ready",
            reason_codes=("phase1_ready", "no_positions"),
            symbol_assessments=(),
        )

    assessments: list[DeterministicVarSymbolAssessment] = []
    base_var = Decimal("0")
    max_penalty_pct = Decimal("0")
    has_ready_symbol = False
    has_zero_variance_symbol = False
    all_non_ready_reasons: list[str] = []

    for position in positions:
        effective_market_value = _resolve_effective_market_value(position)
        sigma, sigma_status, sigma_reason_codes = _calculate_sigma(position.close_prices)
        concentration_penalty_pct = _calculate_concentration_penalty_pct(
            market_value=effective_market_value,
            nav=nav,
            max_single_position_pct=max_single_position_pct,
        )
        weight_pct = (
            _quantize_pct(effective_market_value / nav * Decimal("100"))
            if effective_market_value > 0 and nav > 0
            else Decimal("0.0000")
        )
        if sigma is None or effective_market_value <= 0:
            var_1d = Decimal("0")
        else:
            var_1d = _quantize_numeric(VAR_Z_SCORE * sigma * effective_market_value)

        assessments.append(
            DeterministicVarSymbolAssessment(
                symbol=position.symbol,
                effective_market_value=_quantize_numeric(effective_market_value),
                sigma=_quantize_numeric(sigma) if sigma is not None else None,
                var_1d=var_1d,
                marginal_contribution_pct=Decimal("0"),
                weight_pct=weight_pct,
                concentration_penalty_pct=concentration_penalty_pct,
                status=sigma_status,
                reason_codes=sigma_reason_codes,
            )
        )

        if sigma_status == "ready":
            has_ready_symbol = True
        elif sigma_status == "zero_variance":
            has_zero_variance_symbol = True
        else:
            all_non_ready_reasons.extend(sigma_reason_codes)

        if var_1d > 0:
            base_var += var_1d
        if concentration_penalty_pct > max_penalty_pct:
            max_penalty_pct = concentration_penalty_pct

    if base_var > 0:
        largest_symbol = max(assessments, key=lambda item: item.var_1d)
        adjusted: list[DeterministicVarSymbolAssessment] = []
        for item in assessments:
            contribution_pct = _quantize_pct(item.var_1d / base_var * Decimal("100"))
            adjusted.append(
                replace(
                    item,
                    marginal_contribution_pct=contribution_pct,
                )
            )
        portfolio_var_1d = _quantize_numeric(base_var)
        portfolio_var_1d_adjusted = _quantize_numeric(
            base_var * (Decimal("1") + max_penalty_pct / Decimal("100"))
        )
        return DeterministicVarAssessment(
            confidence_level=VAR_CONFIDENCE_LEVEL,
            horizon_days=VAR_HORIZON_DAYS,
            lookback_days=VAR_LOOKBACK_DAYS,
            portfolio_var_1d=portfolio_var_1d,
            portfolio_var_1d_adjusted=portfolio_var_1d_adjusted,
            largest_var_symbol=largest_symbol.symbol,
            largest_var_contribution_pct=_quantize_pct(
                largest_symbol.var_1d / base_var * Decimal("100")
            ),
            concentration_penalty_pct=max_penalty_pct,
            status="ready",
            reason_codes=tuple(dict.fromkeys(["phase1_ready", *reason_codes])),
            symbol_assessments=tuple(adjusted),
        )

    if has_zero_variance_symbol and not has_ready_symbol:
        status = "zero_variance"
        reason_codes = ["zero_variance"]
    else:
        status = "insufficient_data"
        reason_codes = list(dict.fromkeys(all_non_ready_reasons or ["insufficient_data"]))

    return DeterministicVarAssessment(
        confidence_level=VAR_CONFIDENCE_LEVEL,
        horizon_days=VAR_HORIZON_DAYS,
        lookback_days=VAR_LOOKBACK_DAYS,
        portfolio_var_1d=None,
        portfolio_var_1d_adjusted=None,
        largest_var_symbol=None,
        largest_var_contribution_pct=None,
        concentration_penalty_pct=max_penalty_pct if assessments else None,
        status=status,
        reason_codes=tuple(reason_codes),
        symbol_assessments=tuple(assessments),
    )


def apply_var_assessment_to_risk_limit_snapshot(
    snapshot: RiskLimitSnapshotEntity,
    assessment: DeterministicVarAssessment,
) -> RiskLimitSnapshotEntity:
    return replace(
        snapshot,
        var_confidence_level=assessment.confidence_level,
        var_horizon_days=assessment.horizon_days,
        var_lookback_days=assessment.lookback_days,
        portfolio_var_1d=assessment.portfolio_var_1d,
        portfolio_var_1d_adjusted=assessment.portfolio_var_1d_adjusted,
        largest_var_symbol=assessment.largest_var_symbol,
        largest_var_contribution_pct=assessment.largest_var_contribution_pct,
        concentration_penalty_pct=assessment.concentration_penalty_pct,
        var_status=assessment.status,
        var_reason_codes=list(assessment.reason_codes) or None,
        symbol_var_json=assessment.symbol_var_json,
        symbol_marginal_contribution_json=assessment.symbol_marginal_contribution_json,
    )


def _resolve_effective_market_value(
    position: DeterministicVarPositionInput,
) -> Decimal:
    held = max(Decimal("0"), position.held_market_value)
    pending_buy = max(Decimal("0"), position.pending_buy_exposure)
    pending_sell = max(Decimal("0"), position.pending_sell_exposure)
    pending_sell_offset = min(pending_sell, held)
    market_value = held + pending_buy - pending_sell_offset
    return max(Decimal("0"), market_value)


def _calculate_sigma(
    close_prices: Sequence[Decimal],
) -> tuple[Decimal | None, str, tuple[str, ...]]:
    if len(close_prices) < VAR_LOOKBACK_DAYS + 1:
        return None, "insufficient_data", ("insufficient_history",)
    returns: list[float] = []
    for idx in range(1, len(close_prices)):
        prev_close = close_prices[idx - 1]
        current_close = close_prices[idx]
        if prev_close <= 0 or current_close <= 0:
            return None, "insufficient_data", ("non_positive_close_price",)
        returns.append(log(float(current_close / prev_close)))
    realized_returns = returns[-VAR_LOOKBACK_DAYS:]
    if len(realized_returns) < VAR_LOOKBACK_DAYS:
        return None, "insufficient_data", ("insufficient_history",)
    sigma_value = stdev(realized_returns)
    if sigma_value < 0:
        return None, "invalid_sigma", ("invalid_sigma",)
    if sigma_value == 0:
        return Decimal("0"), "zero_variance", ("zero_variance",)
    return Decimal(str(sigma_value)), "ready", ()


def _calculate_concentration_penalty_pct(
    *,
    market_value: Decimal,
    nav: Decimal,
    max_single_position_pct: Decimal | None,
) -> Decimal:
    if (
        market_value <= 0
        or nav <= 0
        or max_single_position_pct is None
        or max_single_position_pct <= 0
    ):
        return Decimal("0.0000")
    weight_pct = market_value / nav * Decimal("100")
    over_weight_pct = weight_pct - max_single_position_pct
    if over_weight_pct <= 0:
        return Decimal("0.0000")
    penalty_ratio = over_weight_pct / max_single_position_pct
    return _quantize_pct(penalty_ratio * Decimal("100"))


def _quantize_pct(value: Decimal) -> Decimal:
    return value.quantize(_PCT_SCALE)


def _quantize_numeric(value: Decimal) -> Decimal:
    return value.quantize(_NUMERIC_SCALE)
