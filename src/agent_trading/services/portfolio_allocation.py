from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
)
from agent_trading.services.market_regime import MarketRegimeAssessment
from agent_trading.services.strategy_selection import StrategySelectionAssessment


@dataclass(slots=True, frozen=True)
class PortfolioAllocationAssessment:
    """결정론적 포트폴리오 배분/집중도 평가 결과."""

    target_weight_pct: float
    current_weight_pct: float | None
    max_single_position_pct: float
    remaining_concentration_pct: float | None
    remaining_gross_budget_pct: float | None
    max_new_capital_pct: float
    orderable_cash: Decimal | None
    available_allocation_cash: Decimal | None
    recommended_max_order_value: Decimal | None
    allocation_bias: str
    confidence: float
    reason_codes: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


def assess_portfolio_allocation(
    *,
    symbol: str,
    source_type: str,
    config_version: ConfigVersionEntity | None,
    position_snapshot: PositionSnapshotEntity | None,
    cash_balance_snapshot: CashBalanceSnapshotEntity | None,
    risk_limit_snapshot: RiskLimitSnapshotEntity | None,
    market_regime: MarketRegimeAssessment | None,
    strategy_selection: StrategySelectionAssessment | None,
) -> PortfolioAllocationAssessment | None:
    """현재 계좌 상태에서 종목별 배분 가능 예산을 계산한다."""
    if (
        config_version is None
        and position_snapshot is None
        and cash_balance_snapshot is None
        and risk_limit_snapshot is None
        and market_regime is None
        and strategy_selection is None
    ):
        return None

    config_json = config_version.config_json if config_version is not None else {}
    risk_config = config_json.get("risk", {}) if isinstance(config_json, dict) else {}
    execution_config = (
        config_json.get("execution", {}) if isinstance(config_json, dict) else {}
    )

    max_single_position_pct = _resolve_max_single_position_pct(
        risk_config=risk_config,
        config_json=config_json if isinstance(config_json, dict) else {},
    )
    max_gross_exposure_pct = _resolve_max_gross_exposure_pct(risk_config=risk_config)

    nav, nav_source = _resolve_nav(risk_limit_snapshot, cash_balance_snapshot)
    orderable_cash, cash_source = _resolve_orderable_cash(cash_balance_snapshot)
    current_position_value = _resolve_current_position_value(position_snapshot)
    symbol_exposure_pct = _extract_symbol_pct(
        risk_limit_snapshot.symbol_exposure_json if risk_limit_snapshot else {},
        symbol,
    )
    open_order_exposure_pct = _extract_symbol_pct(
        risk_limit_snapshot.open_order_exposure_json if risk_limit_snapshot else {},
        symbol,
    )

    current_weight_pct: float | None = None
    if nav is not None and nav > 0:
        if current_position_value is not None:
            current_weight_pct = float(current_position_value / nav * Decimal("100"))
        elif symbol_exposure_pct is not None:
            current_weight_pct = symbol_exposure_pct

    target_weight_pct, allocation_bias, target_reason_codes = _resolve_target_weight_pct(
        source_type=source_type,
        market_regime=market_regime,
        strategy_selection=strategy_selection,
        current_weight_pct=current_weight_pct,
    )

    gross_exposure_pct = (
        float(risk_limit_snapshot.gross_exposure_pct)
        if risk_limit_snapshot is not None
        and risk_limit_snapshot.gross_exposure_pct is not None
        else None
    )
    remaining_gross_budget_pct = (
        max(0.0, max_gross_exposure_pct - gross_exposure_pct)
        if gross_exposure_pct is not None
        else None
    )

    occupied_weight_pct = (current_weight_pct or 0.0) + (open_order_exposure_pct or 0.0)
    remaining_concentration_pct = max(0.0, max_single_position_pct - occupied_weight_pct)

    desired_increment_pct = max(0.0, target_weight_pct - occupied_weight_pct)
    cash_budget_pct: float | None = None
    if nav is not None and nav > 0 and orderable_cash is not None and orderable_cash > 0:
        cash_budget_pct = float(orderable_cash / nav * Decimal("100"))

    candidate_caps = [desired_increment_pct, remaining_concentration_pct]
    if remaining_gross_budget_pct is not None:
        candidate_caps.append(remaining_gross_budget_pct)
    if cash_budget_pct is not None:
        candidate_caps.append(cash_budget_pct)
    max_new_capital_pct = max(0.0, min(candidate_caps)) if candidate_caps else 0.0

    available_allocation_cash: Decimal | None = None
    if nav is not None and nav > 0:
        available_allocation_cash = (
            nav * Decimal(str(max_new_capital_pct)) / Decimal("100")
        )
    if orderable_cash is not None:
        available_allocation_cash = (
            min(available_allocation_cash, orderable_cash)
            if available_allocation_cash is not None
            else orderable_cash
        )

    recommended_max_order_value = available_allocation_cash
    execution_max_order_value = _decimal_or_none(execution_config.get("max_order_value"))
    if execution_max_order_value is not None:
        recommended_max_order_value = (
            min(recommended_max_order_value, execution_max_order_value)
            if recommended_max_order_value is not None
            else execution_max_order_value
        )

    reason_codes = list(target_reason_codes)
    if current_weight_pct is not None and current_weight_pct >= max_single_position_pct:
        reason_codes.append("single_position_limit_reached")
    if remaining_gross_budget_pct is not None and remaining_gross_budget_pct <= 0:
        reason_codes.append("gross_exposure_limit_reached")
    if cash_budget_pct is not None and cash_budget_pct <= 0:
        reason_codes.append("cash_budget_exhausted")
    if orderable_cash is None:
        reason_codes.append("orderable_cash_missing")
    if nav is None:
        reason_codes.append("nav_missing")

    confidence = _resolve_confidence(market_regime, strategy_selection)
    metadata = {
        "symbol": symbol,
        "source_type": (source_type or "core").strip().lower(),
        "nav_source": nav_source,
        "cash_source": cash_source,
        "nav": str(nav) if nav is not None else None,
        "current_position_value": (
            str(current_position_value) if current_position_value is not None else None
        ),
        "gross_exposure_pct": gross_exposure_pct,
        "open_order_exposure_pct": open_order_exposure_pct,
        "symbol_exposure_pct": symbol_exposure_pct,
        "cash_budget_pct": cash_budget_pct,
        "occupied_weight_pct": occupied_weight_pct,
    }
    return PortfolioAllocationAssessment(
        target_weight_pct=round(target_weight_pct, 4),
        current_weight_pct=(
            round(current_weight_pct, 4) if current_weight_pct is not None else None
        ),
        max_single_position_pct=round(max_single_position_pct, 4),
        remaining_concentration_pct=round(remaining_concentration_pct, 4),
        remaining_gross_budget_pct=(
            round(remaining_gross_budget_pct, 4)
            if remaining_gross_budget_pct is not None
            else None
        ),
        max_new_capital_pct=round(max_new_capital_pct, 4),
        orderable_cash=orderable_cash,
        available_allocation_cash=available_allocation_cash,
        recommended_max_order_value=recommended_max_order_value,
        allocation_bias=allocation_bias,
        confidence=round(confidence, 4),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        metadata=metadata,
    )


def _resolve_target_weight_pct(
    *,
    source_type: str,
    market_regime: MarketRegimeAssessment | None,
    strategy_selection: StrategySelectionAssessment | None,
    current_weight_pct: float | None,
) -> tuple[float, str, tuple[str, ...]]:
    normalized_source_type = (source_type or "core").strip().lower()
    regime_label = market_regime.regime_label if market_regime is not None else "unknown"
    risk_tone = market_regime.risk_tone if market_regime is not None else "neutral"
    volatility_regime = (
        market_regime.volatility_regime if market_regime is not None else "normal_volatility"
    )

    target_weight_pct = 5.0
    allocation_bias = "neutral"
    reason_codes: list[str] = [f"portfolio_source_{normalized_source_type}"]

    if regime_label == "bullish_trend":
        target_weight_pct = 8.0
        allocation_bias = "accumulate"
        reason_codes.append("portfolio_bullish_target")
    elif regime_label == "range_bound":
        target_weight_pct = 5.0
        allocation_bias = "balanced"
        reason_codes.append("portfolio_range_target")
    elif regime_label == "event_driven_unstable":
        target_weight_pct = 4.0
        allocation_bias = "tactical"
        reason_codes.append("portfolio_event_target")
    elif regime_label == "bearish_trend":
        target_weight_pct = 2.5
        allocation_bias = "defensive"
        reason_codes.append("portfolio_bearish_target")

    if risk_tone == "risk_off":
        target_weight_pct = min(target_weight_pct, 3.0)
        allocation_bias = "de_risk"
        reason_codes.append("portfolio_risk_off_cap")

    if volatility_regime == "high_volatility":
        target_weight_pct = min(target_weight_pct, 4.0)
        reason_codes.append("portfolio_high_volatility_cap")

    if normalized_source_type == "event_overlay":
        target_weight_pct = min(target_weight_pct, 4.0)
        allocation_bias = "tactical"
        reason_codes.append("portfolio_event_overlay_cap")
    elif normalized_source_type == "market_overlay":
        target_weight_pct = min(target_weight_pct, 5.0)
        reason_codes.append("portfolio_market_overlay_cap")
    elif normalized_source_type == "held_position":
        if current_weight_pct is not None and current_weight_pct > target_weight_pct:
            allocation_bias = "de_risk"
        else:
            allocation_bias = "maintain"
        reason_codes.append("portfolio_held_position_path")

    if (
        strategy_selection is not None
        and strategy_selection.preferred_time_horizon == "short"
    ):
        target_weight_pct = min(target_weight_pct, 4.0)
        reason_codes.append("portfolio_short_horizon_cap")

    return target_weight_pct, allocation_bias, tuple(dict.fromkeys(reason_codes))


def _resolve_confidence(
    market_regime: MarketRegimeAssessment | None,
    strategy_selection: StrategySelectionAssessment | None,
) -> float:
    values: list[float] = []
    if market_regime is not None:
        values.append(float(market_regime.confidence))
    if strategy_selection is not None:
        values.append(float(strategy_selection.confidence))
    if not values:
        return 0.3
    return min(0.99, max(0.1, sum(values) / len(values)))


def _resolve_max_single_position_pct(
    *,
    risk_config: dict[str, object],
    config_json: dict[str, object],
) -> float:
    nested = _decimal_or_none(risk_config.get("max_single_position_pct"))
    if nested is not None:
        return float(nested)

    legacy = _decimal_or_none(config_json.get("max_position_size"))
    if legacy is None:
        return 15.0
    if Decimal("0") < legacy <= Decimal("1"):
        legacy = legacy * Decimal("100")
    return float(legacy)


def _resolve_max_gross_exposure_pct(*, risk_config: dict[str, object]) -> float:
    gross = _decimal_or_none(risk_config.get("max_gross_exposure_pct"))
    return float(gross) if gross is not None else 100.0


def _resolve_nav(
    risk_limit_snapshot: RiskLimitSnapshotEntity | None,
    cash_balance_snapshot: CashBalanceSnapshotEntity | None,
) -> tuple[Decimal | None, str]:
    if risk_limit_snapshot is not None and risk_limit_snapshot.nav is not None:
        return risk_limit_snapshot.nav, "risk_limit_snapshot.nav"
    if cash_balance_snapshot is not None and cash_balance_snapshot.total_asset is not None:
        return cash_balance_snapshot.total_asset, "cash_balance_snapshot.total_asset"
    return None, "missing"


def _resolve_orderable_cash(
    cash_balance_snapshot: CashBalanceSnapshotEntity | None,
) -> tuple[Decimal | None, str]:
    if cash_balance_snapshot is None:
        return None, "missing"
    if cash_balance_snapshot.orderable_amount is not None:
        return cash_balance_snapshot.orderable_amount, "cash_balance_snapshot.orderable_amount"
    return cash_balance_snapshot.available_cash, "cash_balance_snapshot.available_cash"


def _resolve_current_position_value(
    position_snapshot: PositionSnapshotEntity | None,
) -> Decimal | None:
    if position_snapshot is None:
        return None
    if position_snapshot.evaluation_amount is not None:
        return position_snapshot.evaluation_amount
    if (
        position_snapshot.quantity is not None
        and position_snapshot.market_price is not None
    ):
        return position_snapshot.quantity * position_snapshot.market_price
    if (
        position_snapshot.quantity is not None
        and position_snapshot.average_price is not None
    ):
        return position_snapshot.quantity * position_snapshot.average_price
    return None


def _extract_symbol_pct(
    payload: dict[str, object],
    symbol: str,
) -> float | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get(symbol)
    if isinstance(raw, dict):
        for key in ("exposure_pct", "weight_pct", "gross_exposure_pct", "pct"):
            value = raw.get(key)
            if value is not None:
                return float(value)
        return None
    if raw is not None:
        return float(raw)
    return None


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
