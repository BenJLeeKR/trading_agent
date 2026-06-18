from __future__ import annotations

from agent_trading.services.market_regime import MarketRegimeAssessment
from agent_trading.services.strategy_selection import select_strategy


def _make_regime(
    *,
    regime_label: str = "bullish_trend",
    volatility_regime: str = "normal_volatility",
    risk_tone: str = "risk_on",
) -> MarketRegimeAssessment:
    return MarketRegimeAssessment(
        regime_label=regime_label,
        volatility_regime=volatility_regime,
        risk_tone=risk_tone,
        confidence=0.78,
        half_life_hours=24,
        strategy_weights={"swing_momentum": 0.45},
        reason_codes=("trend_up",),
    )


def test_select_strategy_bullish_core() -> None:
    result = select_strategy(
        market_regime=_make_regime(),
        source_type="core",
    )

    assert result is not None
    assert result.preferred_strategy == "swing_momentum"
    assert result.preferred_entry_style == "LIMIT"
    assert result.preferred_time_horizon == "swing"
    assert "bullish_trend_momentum" in result.reason_codes


def test_select_strategy_market_overlay_prefers_faster_style() -> None:
    result = select_strategy(
        market_regime=_make_regime(),
        source_type="market_overlay",
    )

    assert result is not None
    assert result.preferred_strategy == "swing_momentum"
    assert result.preferred_entry_style == "MARKET"
    assert result.preferred_time_horizon == "short"


def test_select_strategy_event_overlay_biases_event_continuation() -> None:
    result = select_strategy(
        market_regime=_make_regime(regime_label="range_bound", risk_tone="neutral"),
        source_type="event_overlay",
    )

    assert result is not None
    assert result.preferred_strategy == "event_continuation"
    assert "event_continuation" in result.allowed_strategies
    assert "event_overlay_bias" in result.reason_codes


def test_select_strategy_risk_off_becomes_defensive() -> None:
    result = select_strategy(
        market_regime=_make_regime(
            regime_label="bearish_trend",
            volatility_regime="high_volatility",
            risk_tone="risk_off",
        ),
        source_type="held_position",
    )

    assert result is not None
    assert result.preferred_strategy == "defensive_low_volatility_rotation"
    assert result.preferred_entry_style == "MARKET"
    assert result.preferred_time_horizon == "short"
    assert "risk_off_defensive" in result.reason_codes
