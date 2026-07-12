from __future__ import annotations

from scripts.analyze_trigger_proxy_attribution import (
    _build_snapshot_feature_payload,
    _build_entry_score_bias_report,
    _coerce_json_list,
    _coerce_json_mapping,
    _coerce_snapshot_component_scores,
    _enrich_snapshot_component_scores,
    _hydrate_core_risk_off_experiment_from_snapshot,
)


def test_coerce_json_mapping_accepts_serialized_json() -> None:
    payload = _coerce_json_mapping('{"active": true, "shadow_floor_bucket": "mild_relax"}')
    assert payload == {
        "active": True,
        "shadow_floor_bucket": "mild_relax",
    }


def test_coerce_json_list_accepts_serialized_json() -> None:
    payload = _coerce_json_list('["a", "b", "c"]')
    assert payload == ["a", "b", "c"]


def test_coerce_json_mapping_rejects_non_mapping_json() -> None:
    payload = _coerce_json_mapping('["not", "mapping"]')
    assert payload == {}


def test_coerce_snapshot_component_scores_accepts_serialized_json() -> None:
    payload = _coerce_snapshot_component_scores(
        '{"shadow_overall_score_v5": -0.18, "shadow_slow_score_v5": -0.14}'
    )

    assert payload == {
        "shadow_overall_score_v5": -0.18,
        "shadow_slow_score_v5": -0.14,
    }


def test_hydrate_core_risk_off_experiment_from_snapshot_fills_missing_v5_fields() -> None:
    hydrated = _hydrate_core_risk_off_experiment_from_snapshot(
        source_type="core",
        core_experiment={
            "active": True,
            "shadow_overall_score_v5": None,
            "shadow_slow_score_v5": None,
        },
        snapshot_component_scores={
            "shadow_overall_score_v5": -0.18,
            "shadow_slow_score_v5": -0.14,
            "shadow_component_scores_v5": {"slow_momentum": -0.30},
            "shadow_reason_codes_v5": ["momentum_3m_soft_negative_shadow_v5"],
        },
    )

    assert hydrated["shadow_overall_score_v5"] == -0.18
    assert hydrated["shadow_slow_score_v5"] == -0.14
    assert hydrated["shadow_component_scores_v5"] == {"slow_momentum": -0.30}
    assert hydrated["shadow_reason_codes_v5"] == [
        "momentum_3m_soft_negative_shadow_v5"
    ]


def test_hydrate_core_risk_off_experiment_from_snapshot_preserves_existing_v5_fields() -> None:
    hydrated = _hydrate_core_risk_off_experiment_from_snapshot(
        source_type="core",
        core_experiment={
            "active": True,
            "shadow_overall_score_v5": -0.25,
            "shadow_slow_score_v5": -0.20,
        },
        snapshot_component_scores={
            "shadow_overall_score_v5": -0.18,
            "shadow_slow_score_v5": -0.14,
        },
    )

    assert hydrated["shadow_overall_score_v5"] == -0.25
    assert hydrated["shadow_slow_score_v5"] == -0.20


def test_hydrate_core_risk_off_experiment_from_snapshot_fills_empty_core_payload() -> None:
    hydrated = _hydrate_core_risk_off_experiment_from_snapshot(
        source_type="core",
        core_experiment={},
        snapshot_component_scores={
            "shadow_overall_score_v5": -0.18,
            "shadow_slow_score_v5": -0.14,
            "shadow_component_scores_v5": {"slow_trend": -0.20},
        },
    )

    assert hydrated["shadow_overall_score_v5"] == -0.18
    assert hydrated["shadow_slow_score_v5"] == -0.14
    assert hydrated["shadow_component_scores_v5"] == {"slow_trend": -0.20}


def test_build_snapshot_feature_payload_reconstructs_v5_scores() -> None:
    payload = _build_snapshot_feature_payload(
        {
            "symbol": "005930",
            "snapshot_at": "2026-07-03T11:00:00+00:00",
            "bar_count": 100,
            "price_vs_sma_20_pct": 3.2,
            "price_vs_sma_60_pct": -7.1,
            "return_3m_pct": -12.0,
            "volatility_20d_pct": 3.4,
            "atr_14_pct": 4.0,
            "rsi_14": 58.0,
            "volume_surge_ratio": 1.5,
            "turnover_surge_ratio": 1.1,
        }
    )

    assert payload["shadow_slow_score_v5"] == -0.53
    assert payload["shadow_overall_score_v5"] == -0.2656
    assert payload["shadow_component_scores_v5"]["slow_trend"] == -0.5


def test_enrich_snapshot_component_scores_backfills_missing_v5_fields() -> None:
    enriched = _enrich_snapshot_component_scores(
        {
            "slow_momentum": -0.8,
            "slow_trend": -0.45,
            "fast_trend": 0.45,
            "volume_confirmation": 0.35,
            "rsi_signal": 0.3,
            "volatility_penalty": -0.2,
        },
        snapshot_row={
            "symbol": "005930",
            "snapshot_at": "2026-07-03T11:00:00+00:00",
            "bar_count": 100,
            "price_vs_sma_20_pct": 3.2,
            "price_vs_sma_60_pct": -7.1,
            "return_3m_pct": -12.0,
            "volatility_20d_pct": 3.4,
            "atr_14_pct": 4.0,
            "rsi_14": 58.0,
            "volume_surge_ratio": 1.5,
            "turnover_surge_ratio": 1.1,
        },
    )

    assert enriched["shadow_slow_score_v5"] == -0.53
    assert enriched["shadow_overall_score_v5"] == -0.2656
    assert enriched["slow_momentum"] == -0.8


def test_build_entry_score_bias_report_summarizes_counterfactuals() -> None:
    report = _build_entry_score_bias_report(
        [
            {
                "trade_date": "2026-07-08",
                "symbol": "001450",
                "source_type": "core",
                "entry_score": 0.54,
                "ranking_score": 0.31,
                "watch_candidate": True,
                "eligibility_passed": False,
                "trigger_regime_label": "bullish_trend",
                "trigger_risk_tone": "risk_off",
                "trigger_preferred_strategy": "defensive_low_volatility_rotation",
                "portfolio_max_new_capital_pct": 3.0,
                "snapshot_overall_score": 0.4,
                "snapshot_fast_score": 0.1,
                "snapshot_slow_score": 0.2,
                "volume_surge_ratio": 1.05,
                "turnover_surge_ratio": 1.08,
                "trigger_reason_codes": [
                    "trigger_bullish_regime",
                    "trigger_risk_off_penalty",
                    "trigger_allocation_budget_available",
                    "trigger_watch_candidate",
                ],
            },
            {
                "trade_date": "2026-07-09",
                "symbol": "005930",
                "source_type": "event_overlay",
                "entry_score": 0.58,
                "ranking_score": 0.42,
                "watch_candidate": True,
                "eligibility_passed": False,
                "trigger_regime_label": "bullish_trend",
                "trigger_risk_tone": "risk_off",
                "trigger_preferred_strategy": "event_continuation",
                "portfolio_max_new_capital_pct": 3.0,
                "snapshot_overall_score": 0.5,
                "snapshot_fast_score": 0.2,
                "snapshot_slow_score": 0.3,
                "volume_surge_ratio": 1.8,
                "turnover_surge_ratio": 1.4,
                "trigger_reason_codes": [
                    "trigger_bullish_regime",
                    "trigger_risk_off_penalty",
                    "trigger_allocation_budget_available",
                    "trigger_strategy_alignment",
                    "trigger_relative_activity_bonus",
                    "trigger_watch_candidate",
                ],
            },
        ]
    )

    assert report["all"]["count"] == 2
    assert report["core"]["count"] == 1
    assert report["near_buy_floor"]["count"] == 2
    assert report["near_buy_floor_counterfactual"]["cross_if_remove_risk_off_penalty"] == 2
    assert report["near_buy_floor_counterfactual"]["cross_if_add_strategy_bonus"] == 0
    assert report["top_core_samples"][0]["symbol"] == "001450"
