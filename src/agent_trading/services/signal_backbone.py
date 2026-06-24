from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from math import sqrt
from statistics import mean, pstdev
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from agent_trading.domain.entities import SignalFeatureSnapshotEntity

KST = ZoneInfo("Asia/Seoul")


@dataclass(slots=True, frozen=True)
class PriceBar:
    """결정론적 signal 계산용 일봉 입력."""

    timestamp: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    turnover: float | None = None


@dataclass(slots=True, frozen=True)
class TechnicalFeatureSnapshot:
    """기술/모멘텀/변동성 feature snapshot."""

    symbol: str
    as_of: datetime
    bar_count: int
    sma_5: float | None
    sma_20: float | None
    sma_60: float | None
    price_vs_sma_20_pct: float | None
    price_vs_sma_60_pct: float | None
    return_1m_pct: float | None
    return_3m_pct: float | None
    volatility_20d_pct: float | None
    atr_14_pct: float | None
    rsi_14: float | None
    average_volume_20d: float | None
    average_turnover_20d: float | None
    volume_surge_ratio: float | None
    turnover_surge_ratio: float | None


@dataclass(slots=True, frozen=True)
class SignalScoreCard:
    """Fast/Slow layer 분리형 signal score 결과."""

    symbol: str
    as_of: datetime
    fast_score: float
    slow_score: float
    overall_score: float
    component_scores: dict[str, float] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()


def build_signal_snapshot(
    symbol: str,
    bars: list[PriceBar],
) -> tuple[TechnicalFeatureSnapshot, SignalScoreCard]:
    """가격 이력 기반 feature snapshot과 score card를 함께 계산한다."""
    normalized = _normalize_bars(bars)
    features = _calculate_features(symbol, normalized)
    score_card = _score_features(features)
    return features, score_card


def build_signal_feature_entity(
    *,
    instrument_id: UUID,
    features: TechnicalFeatureSnapshot,
    score_card: SignalScoreCard,
    timeframe: str = "1d",
    feature_set_version: str = "signal_backbone_v1",
) -> SignalFeatureSnapshotEntity:
    """계산된 feature/score를 저장용 엔티티로 변환한다."""
    snapshot_at = _to_after_market_snapshot_at(features.as_of)
    return SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=uuid4(),
        instrument_id=instrument_id,
        timeframe=timeframe,
        snapshot_at=snapshot_at,
        feature_set_version=feature_set_version,
        bar_count=features.bar_count,
        sma_5=_decimal_or_none(features.sma_5),
        sma_20=_decimal_or_none(features.sma_20),
        sma_60=_decimal_or_none(features.sma_60),
        price_vs_sma_20_pct=_decimal_or_none(features.price_vs_sma_20_pct),
        price_vs_sma_60_pct=_decimal_or_none(features.price_vs_sma_60_pct),
        return_1m_pct=_decimal_or_none(features.return_1m_pct),
        return_3m_pct=_decimal_or_none(features.return_3m_pct),
        volatility_20d_pct=_decimal_or_none(features.volatility_20d_pct),
        atr_14_pct=_decimal_or_none(features.atr_14_pct),
        rsi_14=_decimal_or_none(features.rsi_14),
        average_volume_20d=_decimal_or_none(features.average_volume_20d),
        average_turnover_20d=_decimal_or_none(features.average_turnover_20d),
        volume_surge_ratio=_decimal_or_none(features.volume_surge_ratio),
        turnover_surge_ratio=_decimal_or_none(features.turnover_surge_ratio),
        fast_score=_decimal_or_none(score_card.fast_score),
        slow_score=_decimal_or_none(score_card.slow_score),
        overall_score=_decimal_or_none(score_card.overall_score),
        component_scores_json={
            key: float(value) for key, value in score_card.component_scores.items()
        },
        reason_codes=list(score_card.reason_codes) or None,
    )


def _to_after_market_snapshot_at(as_of: datetime) -> datetime:
    """일봉 기준 영업일을 장후 feature snapshot anchor 시각으로 정규화한다."""
    as_of_kst = as_of.astimezone(KST)
    return datetime.combine(
        as_of_kst.date(),
        time(20, 0),
        tzinfo=KST,
    )


def _normalize_bars(bars: list[PriceBar]) -> list[PriceBar]:
    if len(bars) < 20:
        raise ValueError("최소 20개 일봉이 필요합니다.")
    return sorted(bars, key=lambda item: item.timestamp)


def _calculate_features(
    symbol: str,
    bars: list[PriceBar],
) -> TechnicalFeatureSnapshot:
    closes = [bar.close_price for bar in bars]
    volumes = [bar.volume for bar in bars]
    turnovers = [bar.turnover for bar in bars]
    as_of = bars[-1].timestamp
    sma_5 = _sma(closes, 5)
    sma_20 = _sma(closes, 20)
    sma_60 = _sma(closes, 60)
    last_close = closes[-1]
    avg_volume_20 = _average(volumes[-20:])
    avg_turnover_20 = _average_optional(
        [value for value in turnovers[-20:] if value is not None]
    )
    prev_20_volumes = volumes[-21:-1] if len(volumes) >= 21 else volumes[-20:]
    prev_turnover_bars = bars[-21:-1] if len(bars) >= 21 else bars[-20:]
    prev_20_turnovers = [
        bar.turnover for bar in prev_turnover_bars if bar.turnover is not None
    ]

    return TechnicalFeatureSnapshot(
        symbol=symbol,
        as_of=as_of,
        bar_count=len(bars),
        sma_5=sma_5,
        sma_20=sma_20,
        sma_60=sma_60,
        price_vs_sma_20_pct=_pct_diff(last_close, sma_20),
        price_vs_sma_60_pct=_pct_diff(last_close, sma_60),
        return_1m_pct=_window_return_pct(closes, 20),
        return_3m_pct=_window_return_pct(closes, 60),
        volatility_20d_pct=_volatility_pct(closes, 20),
        atr_14_pct=_atr_pct(bars, 14),
        rsi_14=_rsi(closes, 14),
        average_volume_20d=avg_volume_20,
        average_turnover_20d=avg_turnover_20,
        volume_surge_ratio=(
            bars[-1].volume / _average(prev_20_volumes)
            if prev_20_volumes and _average(prev_20_volumes) > 0
            else None
        ),
        turnover_surge_ratio=(
            bars[-1].turnover / _average_optional(prev_20_turnovers)
            if bars[-1].turnover is not None
            and prev_20_turnovers
            and (_average_optional(prev_20_turnovers) or 0.0) > 0
            else None
        ),
    )


def _score_features(features: TechnicalFeatureSnapshot) -> SignalScoreCard:
    component_scores: dict[str, float] = {}
    reason_codes: list[str] = []

    slow_momentum = _score_return_3m(features.return_3m_pct, reason_codes)
    slow_trend = _score_price_vs_ma(
        features.price_vs_sma_60_pct,
        positive_reason="above_sma60",
        negative_reason="below_sma60",
        reason_codes=reason_codes,
    )
    fast_trend = _score_price_vs_ma(
        features.price_vs_sma_20_pct,
        positive_reason="above_sma20",
        negative_reason="below_sma20",
        reason_codes=reason_codes,
    )
    volume_confirmation = _score_volume_surge(
        features.volume_surge_ratio,
        features.turnover_surge_ratio,
        reason_codes,
    )
    rsi_signal = _score_rsi(features.rsi_14, reason_codes)
    volatility_penalty = _score_volatility_penalty(
        features.volatility_20d_pct,
        features.atr_14_pct,
        reason_codes,
    )

    component_scores["slow_momentum"] = slow_momentum
    component_scores["slow_trend"] = slow_trend
    component_scores["fast_trend"] = fast_trend
    component_scores["volume_confirmation"] = volume_confirmation
    component_scores["rsi_signal"] = rsi_signal
    component_scores["volatility_penalty"] = volatility_penalty

    slow_score = _round_score((slow_momentum * 0.6) + (slow_trend * 0.4))
    fast_score = _round_score(
        (fast_trend * 0.3)
        + (volume_confirmation * 0.2)
        + (rsi_signal * 0.15)
        + (volatility_penalty * 0.35)
    )
    overall_score = _round_score((slow_score * 0.55) + (fast_score * 0.45))

    return SignalScoreCard(
        symbol=features.symbol,
        as_of=features.as_of,
        fast_score=fast_score,
        slow_score=slow_score,
        overall_score=overall_score,
        component_scores=component_scores,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return _average(values[-window:])


def _average(values: list[float]) -> float:
    return mean(values) if values else 0.0


def _average_optional(values: list[float]) -> float | None:
    return mean(values) if values else None


def _decimal_or_none(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(value, 8)))


def _pct_diff(last_value: float, baseline: float | None) -> float | None:
    if baseline is None or baseline == 0:
        return None
    return ((last_value / baseline) - 1.0) * 100.0


def _window_return_pct(closes: list[float], lookback: int) -> float | None:
    if len(closes) <= lookback:
        return None
    base = closes[-(lookback + 1)]
    if base == 0:
        return None
    return ((closes[-1] / base) - 1.0) * 100.0


def _volatility_pct(closes: list[float], window: int) -> float | None:
    if len(closes) <= window:
        return None
    returns = [
        ((closes[idx] / closes[idx - 1]) - 1.0) * 100.0
        for idx in range(len(closes) - window, len(closes))
        if closes[idx - 1] != 0
    ]
    if len(returns) < 2:
        return None
    return pstdev(returns)


def _atr_pct(bars: list[PriceBar], window: int) -> float | None:
    if len(bars) <= window:
        return None
    true_ranges: list[float] = []
    for idx in range(len(bars) - window, len(bars)):
        bar = bars[idx]
        prev_close = bars[idx - 1].close_price
        tr = max(
            bar.high_price - bar.low_price,
            abs(bar.high_price - prev_close),
            abs(bar.low_price - prev_close),
        )
        true_ranges.append(tr)
    last_close = bars[-1].close_price
    if last_close == 0:
        return None
    return (_average(true_ranges) / last_close) * 100.0


def _rsi(closes: list[float], window: int) -> float | None:
    if len(closes) <= window:
        return None
    deltas = [closes[idx] - closes[idx - 1] for idx in range(len(closes) - window, len(closes))]
    gains = [delta for delta in deltas if delta > 0]
    losses = [-delta for delta in deltas if delta < 0]
    avg_gain = _average(gains)
    avg_loss = _average(losses)
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _score_return_3m(
    value: float | None,
    reason_codes: list[str],
) -> float:
    if value is None:
        return 0.0
    if value >= 15.0:
        reason_codes.append("momentum_3m_strong")
        return 0.9
    if value >= 5.0:
        reason_codes.append("momentum_3m_positive")
        return 0.55
    if value <= -10.0:
        reason_codes.append("momentum_3m_negative")
        return -0.8
    if value <= -3.0:
        reason_codes.append("momentum_3m_soft_negative")
        return -0.35
    return 0.0


def _score_price_vs_ma(
    value: float | None,
    *,
    positive_reason: str,
    negative_reason: str,
    reason_codes: list[str],
) -> float:
    if value is None:
        return 0.0
    if value >= 5.0:
        reason_codes.append(positive_reason)
        return 0.8
    if value >= 1.5:
        reason_codes.append(positive_reason)
        return 0.45
    if value <= -5.0:
        reason_codes.append(negative_reason)
        return -0.8
    if value <= -1.5:
        reason_codes.append(negative_reason)
        return -0.45
    return 0.0


def _score_volume_surge(
    volume_value: float | None,
    turnover_value: float | None,
    reason_codes: list[str],
) -> float:
    volume_score = _score_single_surge_ratio(volume_value)
    turnover_score = _score_single_surge_ratio(turnover_value)
    best_score = max(volume_score, turnover_score)
    if best_score >= 0.75:
        reason_codes.append("volume_surge_strong")
    elif best_score >= 0.35:
        reason_codes.append("volume_surge_supportive")
    elif min(volume_score, turnover_score) <= -0.35:
        reason_codes.append("volume_dry_up")
    return best_score


def _score_single_surge_ratio(value: float | None) -> float:
    if value is None:
        return 0.0
    if value >= 2.0:
        return 0.75
    if value >= 1.3:
        return 0.35
    if value <= 0.6:
        return -0.35
    return 0.0


def _score_rsi(
    value: float | None,
    reason_codes: list[str],
) -> float:
    if value is None:
        return 0.0
    if value >= 75.0:
        reason_codes.append("rsi_overbought")
        return -0.45
    if value >= 55.0:
        reason_codes.append("rsi_bullish_range")
        return 0.3
    if value <= 25.0:
        reason_codes.append("rsi_oversold")
        return 0.25
    if value <= 40.0:
        reason_codes.append("rsi_weak_range")
        return -0.2
    return 0.0


def _score_volatility_penalty(
    volatility_20d_pct: float | None,
    atr_14_pct: float | None,
    reason_codes: list[str],
) -> float:
    penalty = 0.0
    if volatility_20d_pct is not None:
        if volatility_20d_pct >= 4.5:
            reason_codes.append("volatility_elevated")
            penalty -= 0.7
        elif volatility_20d_pct >= 3.0:
            reason_codes.append("volatility_watch")
            penalty -= 0.35
    if atr_14_pct is not None:
        if atr_14_pct >= 6.0:
            reason_codes.append("atr_expanded")
            penalty -= 0.5
        elif atr_14_pct >= 3.5:
            reason_codes.append("atr_watch")
            penalty -= 0.2
    return max(-1.0, penalty)


def _round_score(value: float) -> float:
    return round(max(-1.0, min(1.0, value)), 4)
