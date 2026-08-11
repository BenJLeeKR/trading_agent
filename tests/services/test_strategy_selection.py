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


# ---------------------------------------------------------------------------
# 안 A(2026-08-11 KST, B축 재설계) — risk_off + bullish_trend 완화
# ---------------------------------------------------------------------------


def test_select_strategy_bearish_trend_risk_off_stays_fully_defensive() -> None:
    """bearish_trend는 risk_off 완화 대상이 아니다 — 기존처럼 모멘텀
    계열이 allowed_strategies에서 완전 배제돼야 한다."""
    result = select_strategy(
        market_regime=_make_regime(
            regime_label="bearish_trend",
            risk_tone="risk_off",
        ),
        source_type="core",
    )

    assert result is not None
    assert result.preferred_strategy == "defensive_low_volatility_rotation"
    assert result.allowed_strategies == (
        "defensive_low_volatility_rotation",
        "mean_reversion_bounce",
    )
    assert "swing_momentum" not in result.allowed_strategies
    assert "event_continuation" not in result.allowed_strategies
    assert "risk_off_defensive" in result.reason_codes
    assert "risk_off_bullish_trend_relaxed" not in result.reason_codes


def test_select_strategy_bullish_trend_risk_off_relaxes_momentum_allowance() -> None:
    """bullish_trend + risk_off는 완화 분기를 타야 한다 — 모멘텀 계열이
    allowed_strategies에 포함되되, preferred_strategy는 방어적으로 유지."""
    result = select_strategy(
        market_regime=_make_regime(
            regime_label="bullish_trend",
            risk_tone="risk_off",
        ),
        source_type="core",
    )

    assert result is not None
    # preferred_strategy는 의도대로 방어적으로 유지된다.
    assert result.preferred_strategy == "defensive_low_volatility_rotation"
    # 완전 배제가 아니라 완화된 허용 — 모멘텀 계열이 포함돼야 한다.
    assert "swing_momentum" in result.allowed_strategies
    assert "event_continuation" in result.allowed_strategies
    assert "defensive_low_volatility_rotation" in result.allowed_strategies
    assert "mean_reversion_bounce" in result.allowed_strategies
    # 새 reason_code만 남고, 기존 risk_off_defensive는 재사용하지 않는다
    # (의미가 다르므로 과거/향후 집계 오염 방지).
    assert "risk_off_bullish_trend_relaxed" in result.reason_codes
    assert "risk_off_defensive" not in result.reason_codes


def test_select_strategy_bullish_trend_risk_on_unchanged() -> None:
    """bullish_trend + risk_on은 기존 모멘텀 경로 그대로 유지돼야 한다."""
    result = select_strategy(
        market_regime=_make_regime(
            regime_label="bullish_trend",
            risk_tone="risk_on",
        ),
        source_type="core",
    )

    assert result is not None
    assert result.preferred_strategy == "swing_momentum"
    assert result.allowed_strategies == (
        "swing_momentum",
        "event_continuation",
        "intraday_breakout",
    )
    assert "bullish_trend_momentum" in result.reason_codes
    assert "risk_off_bullish_trend_relaxed" not in result.reason_codes
    assert "risk_off_defensive" not in result.reason_codes


def test_select_strategy_bullish_trend_risk_off_held_position_unaffected() -> None:
    """held_position 보정 로직(진입스타일 MARKET 강제 등)은 완화 분기와도
    그대로 동작해야 한다 — held_position churn-control은 변경 대상이 아님."""
    result = select_strategy(
        market_regime=_make_regime(
            regime_label="bullish_trend",
            risk_tone="risk_off",
        ),
        source_type="held_position",
    )

    assert result is not None
    assert result.preferred_entry_style == "MARKET"
    assert "held_position_path" in result.reason_codes
    # 완화 분기의 preferred_strategy는 이미 defensive이므로 held_position의
    # swing_momentum→defensive 강제 치환 조건에는 애초에 해당하지 않는다.
    assert result.preferred_strategy == "defensive_low_volatility_rotation"
    assert "risk_off_bullish_trend_relaxed" in result.reason_codes


def test_select_strategy_bullish_trend_risk_off_event_overlay_bias_applies() -> None:
    """event_overlay bias 후처리(선호 전략을 event_continuation으로 전환)가
    완화 분기 위에서도 기존과 동일하게 적용돼야 한다 — bullish_trend에서는
    risk_on 경로와 마찬가지로 event_continuation이 우선된다."""
    result = select_strategy(
        market_regime=_make_regime(
            regime_label="bullish_trend",
            risk_tone="risk_off",
        ),
        source_type="event_overlay",
    )

    assert result is not None
    assert "event_continuation" in result.allowed_strategies
    assert "swing_momentum" in result.allowed_strategies
    assert result.preferred_strategy == "event_continuation"
    assert result.preferred_time_horizon == "short"
    assert "event_overlay_bias" in result.reason_codes
    assert "risk_off_bullish_trend_relaxed" in result.reason_codes
