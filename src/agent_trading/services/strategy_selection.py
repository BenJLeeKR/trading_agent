from __future__ import annotations

from dataclasses import dataclass, field

from agent_trading.services.market_regime import MarketRegimeAssessment


@dataclass(slots=True, frozen=True)
class StrategySelectionAssessment:
    """결정론적 전략 선택 결과."""

    preferred_strategy: str
    allowed_strategies: tuple[str, ...]
    preferred_entry_style: str
    preferred_time_horizon: str
    confidence: float
    reason_codes: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


def select_strategy(
    *,
    market_regime: MarketRegimeAssessment | None,
    source_type: str,
) -> StrategySelectionAssessment | None:
    """국면과 source_type을 기반으로 전략군과 실행 스타일을 제안한다."""
    if market_regime is None:
        return None

    normalized_source_type = (source_type or "core").strip().lower()
    regime_label = market_regime.regime_label
    volatility_regime = market_regime.volatility_regime
    risk_tone = market_regime.risk_tone

    preferred_strategy = "swing_momentum"
    allowed_strategies = ("swing_momentum", "event_continuation")
    preferred_entry_style = "LIMIT"
    preferred_time_horizon = "swing"
    reason_codes: list[str] = [f"source_type_{normalized_source_type}"]

    # 안 A(2026-08-11 KST, B축 재설계): risk_off 단독 조건이 regime_label과
    # 무관하게(bullish_trend여도) 모멘텀 계열을 전면 배제하던 것을,
    # bullish_trend에 한해서만 완화한다. bearish_trend/range_bound/
    # event_driven_unstable 등 그 외 regime_label에서는 risk_off일 때
    # 기존과 동일하게 방어 전략으로 전면 제한한다(이 조건식 자체는
    # 변경하지 않음 — 아래 `regime_label != "bullish_trend"` 절만 추가).
    if regime_label != "bullish_trend" and (
        regime_label == "bearish_trend" or risk_tone == "risk_off"
    ):
        preferred_strategy = "defensive_low_volatility_rotation"
        allowed_strategies = (
            "defensive_low_volatility_rotation",
            "mean_reversion_bounce",
        )
        preferred_entry_style = "LIMIT"
        preferred_time_horizon = "swing"
        reason_codes.append("risk_off_defensive")
    elif regime_label == "range_bound":
        preferred_strategy = "mean_reversion_bounce"
        allowed_strategies = (
            "mean_reversion_bounce",
            "defensive_low_volatility_rotation",
        )
        preferred_entry_style = "LIMIT"
        preferred_time_horizon = "short"
        reason_codes.append("range_bound_reversion")
    elif regime_label == "event_driven_unstable":
        preferred_strategy = "event_continuation"
        allowed_strategies = (
            "event_continuation",
            "intraday_breakout",
        )
        preferred_entry_style = "MARKET"
        preferred_time_horizon = "short"
        reason_codes.append("event_driven_tactical")
    elif regime_label == "bullish_trend" and risk_tone == "risk_off":
        # 안 A: bullish_trend에서는 risk_off라도 모멘텀 계열을 완전
        # 배제하지 않고 완화된 허용으로 전환한다 — "완전 차단"이 아니라
        # preferred_strategy만 방어적으로 유지하고 allowed_strategies에는
        # swing_momentum/event_continuation을 포함시킨다.
        # "risk_off_defensive"를 재사용하지 않고 새 태그
        # "risk_off_bullish_trend_relaxed"만 남기는 이유: "risk_off_defensive"는
        # 기존 분석 문서(§28~30)에서 "모멘텀 계열 전면 배제"라는 특정 의미로
        # 이미 쓰여왔다 — 이 분기는 그 의미와 다르므로(완화됐으므로) 같은
        # 태그를 재사용하면 과거/향후 집계가 섞여 오염된다.
        preferred_strategy = "defensive_low_volatility_rotation"
        allowed_strategies = (
            "defensive_low_volatility_rotation",
            "mean_reversion_bounce",
            "swing_momentum",
            "event_continuation",
        )
        preferred_entry_style = "LIMIT"
        preferred_time_horizon = "swing"
        reason_codes.append("risk_off_bullish_trend_relaxed")
    elif regime_label == "bullish_trend":
        preferred_strategy = "swing_momentum"
        allowed_strategies = (
            "swing_momentum",
            "event_continuation",
            "intraday_breakout",
        )
        preferred_entry_style = (
            "MARKET" if normalized_source_type == "market_overlay" else "LIMIT"
        )
        preferred_time_horizon = (
            "short" if normalized_source_type == "market_overlay" else "swing"
        )
        reason_codes.append("bullish_trend_momentum")

    if normalized_source_type == "held_position":
        preferred_entry_style = "MARKET"
        if preferred_strategy == "swing_momentum":
            preferred_strategy = "defensive_low_volatility_rotation"
        reason_codes.append("held_position_path")
    elif normalized_source_type == "event_overlay":
        if "event_continuation" not in allowed_strategies:
            allowed_strategies = ("event_continuation",) + allowed_strategies
        preferred_strategy = (
            "event_continuation"
            if regime_label != "bearish_trend"
            else preferred_strategy
        )
        preferred_time_horizon = "short"
        reason_codes.append("event_overlay_bias")

    if volatility_regime == "high_volatility":
        preferred_time_horizon = "short"
        reason_codes.append("high_volatility_shorter_horizon")

    confidence = min(0.99, max(0.1, market_regime.confidence))
    metadata = {
        "regime_label": regime_label,
        "risk_tone": risk_tone,
        "volatility_regime": volatility_regime,
        "source_type": normalized_source_type,
    }
    return StrategySelectionAssessment(
        preferred_strategy=preferred_strategy,
        allowed_strategies=tuple(dict.fromkeys(allowed_strategies)),
        preferred_entry_style=preferred_entry_style,
        preferred_time_horizon=preferred_time_horizon,
        confidence=round(confidence, 4),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        metadata=metadata,
    )
