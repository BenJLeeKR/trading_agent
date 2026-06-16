from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent_trading.services.signal_backbone import (
    PriceBar,
    build_signal_snapshot,
)


def _make_bars(
    *,
    count: int = 80,
    start_price: float = 100.0,
    daily_step: float = 1.0,
    base_volume: float = 1000.0,
    last_volume: float | None = None,
    range_width: float = 2.0,
) -> list[PriceBar]:
    bars: list[PriceBar] = []
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for idx in range(count):
        close_price = start_price + (daily_step * idx)
        bars.append(
            PriceBar(
                timestamp=started_at + timedelta(days=idx),
                open_price=close_price - 0.5,
                high_price=close_price + range_width,
                low_price=close_price - range_width,
                close_price=close_price,
                volume=(
                    last_volume
                    if last_volume is not None and idx == count - 1
                    else base_volume
                ),
                turnover=close_price * base_volume,
            )
        )
    return bars


def test_build_signal_snapshot_calculates_core_features() -> None:
    bars = _make_bars(last_volume=3000.0)

    features, score_card = build_signal_snapshot("005930", bars)

    assert features.bar_count == 80
    assert features.sma_5 == pytest.approx(177.0)
    assert features.sma_20 == pytest.approx(169.5)
    assert features.sma_60 == pytest.approx(149.5)
    assert features.return_1m_pct == pytest.approx(12.57861635)
    assert features.return_3m_pct == pytest.approx(50.42016807)
    assert features.volume_surge_ratio == pytest.approx(3.0)
    assert features.rsi_14 == pytest.approx(100.0)
    assert score_card.slow_score > 0


def test_positive_trend_produces_positive_scores_and_reason_codes() -> None:
    bars = _make_bars(last_volume=2600.0)

    _, score_card = build_signal_snapshot("000660", bars)

    assert score_card.slow_score > 0.5
    assert score_card.fast_score > 0
    assert score_card.overall_score > 0.3
    assert "momentum_3m_strong" in score_card.reason_codes
    assert "above_sma20" in score_card.reason_codes
    assert "above_sma60" in score_card.reason_codes
    assert "volume_surge_strong" in score_card.reason_codes


def test_high_volatility_penalty_reduces_fast_score() -> None:
    bars: list[PriceBar] = []
    started_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    prices = [
        100, 108, 95, 112, 92, 116, 90, 118, 88, 121,
        86, 124, 84, 126, 82, 128, 80, 130, 78, 132,
        76, 134, 74, 136, 72, 138, 70, 140, 68, 142,
    ]
    for idx, close_price in enumerate(prices):
        bars.append(
            PriceBar(
                timestamp=started_at + timedelta(days=idx),
                open_price=close_price - 2,
                high_price=close_price + 10,
                low_price=close_price - 10,
                close_price=close_price,
                volume=1000.0,
                turnover=close_price * 1000.0,
            )
        )

    features, score_card = build_signal_snapshot("035420", bars)

    assert features.volatility_20d_pct is not None
    assert features.volatility_20d_pct > 10.0
    assert features.atr_14_pct is not None
    assert features.atr_14_pct > 10.0
    assert "volatility_elevated" in score_card.reason_codes
    assert "atr_expanded" in score_card.reason_codes
    assert score_card.fast_score < 0


def test_requires_minimum_bar_count() -> None:
    bars = _make_bars(count=10)

    with pytest.raises(ValueError, match="최소 20개 일봉"):
        build_signal_snapshot("005930", bars)
