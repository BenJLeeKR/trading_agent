from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from agent_trading.services.signal_backbone import (
    PriceBar,
    TechnicalFeatureSnapshot,
    build_shadow_v5_payload_from_feature_snapshot,
    build_signal_feature_entity,
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


def test_build_signal_feature_entity_anchors_snapshot_at_to_2000_kst() -> None:
    bars = _make_bars()
    features, score_card = build_signal_snapshot("005930", bars)

    snapshot = build_signal_feature_entity(
        instrument_id=uuid4(),
        features=features,
        score_card=score_card,
    )

    snapshot_at_kst = snapshot.snapshot_at.astimezone(timezone(timedelta(hours=9)))
    assert snapshot_at_kst.hour == 20
    assert snapshot_at_kst.minute == 0
    assert snapshot_at_kst.second == 0
    assert snapshot_at_kst.date() == features.as_of.astimezone(
        timezone(timedelta(hours=9))
    ).date()


def test_build_signal_feature_entity_includes_score_diagnostics() -> None:
    bars = _make_bars(count=40, last_volume=2200.0)
    features, score_card = build_signal_snapshot("005930", bars)

    snapshot = build_signal_feature_entity(
        instrument_id=uuid4(),
        features=features,
        score_card=score_card,
    )

    diagnostics = snapshot.component_scores_json["diagnostics"]
    assert diagnostics["bar_count"] == 40
    assert diagnostics["overall_bucket"] in {
        "non_negative",
        "mild_negative",
        "moderate_negative",
        "deep_negative",
    }
    assert "short_history_lt_60" in diagnostics["input_quality_flags"]
    assert "missing_sma_60" in diagnostics["missing_feature_flags"]
    assert "missing_return_3m_pct" in diagnostics["missing_feature_flags"]
    assert snapshot.component_scores_json["shadow_signal_backbone_variant"] == (
        "signal_backbone_v1_shadow_v2"
    )
    assert "shadow_slow_score_v2" in snapshot.component_scores_json
    assert "shadow_fast_score_v2" in snapshot.component_scores_json
    assert "shadow_overall_score_v2" in snapshot.component_scores_json
    assert "shadow_component_scores_v2" in snapshot.component_scores_json
    assert "shadow_reason_codes_v2" in snapshot.component_scores_json
    assert "shadow_diagnostics_v2" in snapshot.component_scores_json
    assert snapshot.component_scores_json["shadow_signal_backbone_variant_v5"] == (
        "signal_backbone_v1_shadow_v5"
    )
    assert "shadow_slow_score_v5" in snapshot.component_scores_json
    assert "shadow_fast_score_v5" in snapshot.component_scores_json
    assert "shadow_overall_score_v5" in snapshot.component_scores_json
    assert "shadow_component_scores_v5" in snapshot.component_scores_json
    assert "shadow_reason_codes_v5" in snapshot.component_scores_json
    assert "shadow_diagnostics_v5" in snapshot.component_scores_json


def test_shadow_v2_reduces_slow_negative_pressure_for_borderline_case() -> None:
    bars = _make_bars(count=80, start_price=100.0, daily_step=-0.08, last_volume=1200.0)

    _, score_card = build_signal_snapshot("005930", bars)
    snapshot = build_signal_feature_entity(
        instrument_id=uuid4(),
        features=build_signal_snapshot("005930", bars)[0],
        score_card=score_card,
    )

    shadow_overall = snapshot.component_scores_json["shadow_overall_score_v2"]
    shadow_slow = snapshot.component_scores_json["shadow_slow_score_v2"]
    assert shadow_slow >= float(snapshot.slow_score)
    assert shadow_overall >= float(snapshot.overall_score)


def test_shadow_v5_preserves_deep_negative_for_structural_downtrend() -> None:
    bars = _make_bars(count=80, start_price=100.0, daily_step=-1.0, last_volume=1200.0)

    features, score_card = build_signal_snapshot("005930", bars)
    snapshot = build_signal_feature_entity(
        instrument_id=uuid4(),
        features=features,
        score_card=score_card,
    )

    assert snapshot.component_scores_json["shadow_slow_score_v5"] <= -0.75
    assert snapshot.component_scores_json["shadow_overall_score_v5"] < -0.25


def test_build_shadow_v5_payload_from_feature_snapshot_reconstructs_scores() -> None:
    features = TechnicalFeatureSnapshot(
        symbol="005930",
        as_of=datetime(2026, 7, 3, tzinfo=timezone.utc),
        bar_count=100,
        sma_5=None,
        sma_20=None,
        sma_60=None,
        price_vs_sma_20_pct=3.2,
        price_vs_sma_60_pct=-7.1,
        return_1m_pct=None,
        return_3m_pct=-12.0,
        volatility_20d_pct=3.4,
        atr_14_pct=4.0,
        rsi_14=58.0,
        average_volume_20d=None,
        average_turnover_20d=None,
        volume_surge_ratio=1.5,
        turnover_surge_ratio=1.1,
    )

    payload = build_shadow_v5_payload_from_feature_snapshot(features)

    assert payload["shadow_slow_score_v5"] == pytest.approx(-0.53)
    assert payload["shadow_fast_score_v5"] == pytest.approx(0.0575)
    assert payload["shadow_overall_score_v5"] == pytest.approx(-0.2656)
    assert payload["shadow_component_scores_v5"]["slow_momentum"] == pytest.approx(-0.55)
    assert payload["shadow_component_scores_v5"]["slow_trend"] == pytest.approx(-0.5)
