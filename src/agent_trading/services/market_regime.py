from __future__ import annotations

from dataclasses import dataclass, field

from agent_trading.domain.entities import SignalFeatureSnapshotEntity


@dataclass(slots=True, frozen=True)
class MarketRegimeAssessment:
    """결정론적 시장 국면 분류 결과."""

    regime_label: str
    volatility_regime: str
    risk_tone: str
    confidence: float
    half_life_hours: int
    strategy_weights: dict[str, float] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()


def classify_market_regime(
    snapshot: SignalFeatureSnapshotEntity | None,
) -> MarketRegimeAssessment | None:
    """Signal feature snapshot을 기반으로 시장 국면을 분류한다."""
    if snapshot is None:
        return None

    overall = _float_or_none(snapshot.overall_score) or 0.0
    fast = _float_or_none(snapshot.fast_score) or 0.0
    slow = _float_or_none(snapshot.slow_score) or 0.0
    ret_1m = _float_or_none(snapshot.return_1m_pct) or 0.0
    ret_3m = _float_or_none(snapshot.return_3m_pct) or 0.0
    px_sma20 = _float_or_none(snapshot.price_vs_sma_20_pct) or 0.0
    px_sma60 = _float_or_none(snapshot.price_vs_sma_60_pct) or 0.0
    vol20 = _float_or_none(snapshot.volatility_20d_pct) or 0.0
    atr14 = _float_or_none(snapshot.atr_14_pct) or 0.0
    volume_surge = _float_or_none(snapshot.volume_surge_ratio) or 0.0

    reason_codes: list[str] = []
    regime_label = "range_bound"
    risk_tone = "neutral"

    if slow >= 0.35 and ret_3m >= 5.0 and px_sma60 >= 2.0:
        regime_label = "bullish_trend"
        reason_codes.extend(["trend_up", "momentum_positive"])
    elif slow <= -0.25 and ret_3m <= -3.0 and px_sma60 <= -2.0:
        regime_label = "bearish_trend"
        reason_codes.extend(["trend_down", "momentum_negative"])
    elif fast >= 0.2 and volume_surge >= 1.5:
        regime_label = "event_driven_unstable"
        reason_codes.extend(["fast_breakout", "volume_expansion"])
    elif abs(ret_1m) <= 3.0 and abs(px_sma20) <= 2.0:
        regime_label = "range_bound"
        reason_codes.append("range_compression")

    volatility_regime = "normal_volatility"
    if vol20 >= 4.0 or atr14 >= 4.5:
        volatility_regime = "high_volatility"
        reason_codes.append("volatility_high")
    elif vol20 > 0 and vol20 <= 1.5 and atr14 > 0 and atr14 <= 1.5:
        volatility_regime = "low_volatility"
        reason_codes.append("volatility_low")

    if regime_label == "bullish_trend" and volatility_regime != "high_volatility":
        risk_tone = "risk_on"
        reason_codes.append("risk_on")
    elif regime_label == "bearish_trend" or volatility_regime == "high_volatility":
        risk_tone = "risk_off"
        reason_codes.append("risk_off")

    confidence = _clamp_confidence(
        base=0.45,
        trend_strength=max(abs(slow), abs(overall)),
        volatility_penalty=0.12 if volatility_regime == "high_volatility" else 0.0,
        volume_bonus=0.08 if volume_surge >= 1.5 else 0.0,
    )
    half_life_hours = _resolve_half_life_hours(
        regime_label=regime_label,
        volatility_regime=volatility_regime,
    )
    strategy_weights = _build_strategy_weights(
        regime_label=regime_label,
        volatility_regime=volatility_regime,
        risk_tone=risk_tone,
    )

    return MarketRegimeAssessment(
        regime_label=regime_label,
        volatility_regime=volatility_regime,
        risk_tone=risk_tone,
        confidence=round(confidence, 4),
        half_life_hours=half_life_hours,
        strategy_weights=strategy_weights,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def _build_strategy_weights(
    *,
    regime_label: str,
    volatility_regime: str,
    risk_tone: str,
) -> dict[str, float]:
    if regime_label == "bullish_trend":
        return {
            "swing_momentum": 0.45,
            "event_continuation": 0.3,
            "intraday_breakout": 0.25 if volatility_regime != "high_volatility" else 0.2,
        }
    if regime_label == "bearish_trend":
        return {
            "defensive_low_volatility_rotation": 0.45,
            "mean_reversion_bounce": 0.2,
            "event_continuation": 0.15,
        }
    if regime_label == "event_driven_unstable":
        return {
            "event_continuation": 0.4,
            "intraday_breakout": 0.35,
            "swing_momentum": 0.15,
        }
    base = {
        "mean_reversion_bounce": 0.35,
        "defensive_low_volatility_rotation": 0.25,
        "swing_momentum": 0.2,
    }
    if risk_tone == "risk_on":
        base["swing_momentum"] = 0.3
    return base


def _resolve_half_life_hours(
    *,
    regime_label: str,
    volatility_regime: str,
) -> int:
    if regime_label == "event_driven_unstable":
        return 6
    if volatility_regime == "high_volatility":
        return 12
    if regime_label in {"bullish_trend", "bearish_trend"}:
        return 24
    return 18


def _clamp_confidence(
    *,
    base: float,
    trend_strength: float,
    volatility_penalty: float,
    volume_bonus: float,
) -> float:
    confidence = base + min(trend_strength, 0.45) + volume_bonus - volatility_penalty
    if confidence < 0.05:
        return 0.05
    if confidence > 0.99:
        return 0.99
    return confidence


def _float_or_none(value: object) -> float | None:
    return float(value) if value is not None else None
