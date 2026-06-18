from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from agent_trading.domain.entities import SignalFeatureSnapshotEntity
from agent_trading.services.market_regime import classify_market_regime


def _make_snapshot(
    *,
    overall_score: str = "0.40",
    fast_score: str = "0.30",
    slow_score: str = "0.45",
    return_1m_pct: str = "4.0",
    return_3m_pct: str = "8.0",
    price_vs_sma_20_pct: str = "3.5",
    price_vs_sma_60_pct: str = "6.0",
    volatility_20d_pct: str = "2.0",
    atr_14_pct: str = "2.1",
    volume_surge_ratio: str = "1.2",
) -> SignalFeatureSnapshotEntity:
    return SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=uuid4(),
        instrument_id=uuid4(),
        timeframe="1d",
        snapshot_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
        feature_set_version="signal_backbone_v1",
        bar_count=80,
        overall_score=Decimal(overall_score),
        fast_score=Decimal(fast_score),
        slow_score=Decimal(slow_score),
        return_1m_pct=Decimal(return_1m_pct),
        return_3m_pct=Decimal(return_3m_pct),
        price_vs_sma_20_pct=Decimal(price_vs_sma_20_pct),
        price_vs_sma_60_pct=Decimal(price_vs_sma_60_pct),
        volatility_20d_pct=Decimal(volatility_20d_pct),
        atr_14_pct=Decimal(atr_14_pct),
        volume_surge_ratio=Decimal(volume_surge_ratio),
        component_scores_json={},
    )


def test_classify_market_regime_bullish_trend() -> None:
    regime = classify_market_regime(_make_snapshot())

    assert regime is not None
    assert regime.regime_label == "bullish_trend"
    assert regime.volatility_regime == "normal_volatility"
    assert regime.risk_tone == "risk_on"
    assert regime.half_life_hours == 24
    assert "trend_up" in regime.reason_codes
    assert "swing_momentum" in regime.strategy_weights


def test_classify_market_regime_bearish_high_volatility() -> None:
    regime = classify_market_regime(
        _make_snapshot(
            overall_score="-0.35",
            fast_score="-0.2",
            slow_score="-0.4",
            return_1m_pct="-5.0",
            return_3m_pct="-8.0",
            price_vs_sma_20_pct="-4.0",
            price_vs_sma_60_pct="-6.0",
            volatility_20d_pct="5.5",
            atr_14_pct="6.0",
        )
    )

    assert regime is not None
    assert regime.regime_label == "bearish_trend"
    assert regime.volatility_regime == "high_volatility"
    assert regime.risk_tone == "risk_off"
    assert regime.half_life_hours == 12
    assert "trend_down" in regime.reason_codes
    assert "volatility_high" in regime.reason_codes


def test_classify_market_regime_event_driven_unstable() -> None:
    regime = classify_market_regime(
        _make_snapshot(
            overall_score="0.18",
            fast_score="0.28",
            slow_score="0.10",
            return_1m_pct="1.5",
            return_3m_pct="2.0",
            price_vs_sma_20_pct="1.0",
            price_vs_sma_60_pct="0.5",
            volatility_20d_pct="3.2",
            atr_14_pct="3.0",
            volume_surge_ratio="2.0",
        )
    )

    assert regime is not None
    assert regime.regime_label == "event_driven_unstable"
    assert regime.half_life_hours == 6
    assert "fast_breakout" in regime.reason_codes
    assert "event_continuation" in regime.strategy_weights
