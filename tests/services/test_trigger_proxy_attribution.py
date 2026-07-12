from __future__ import annotations

import pytest

from agent_trading.services.trigger_proxy_attribution import (
    DailyPriceBar,
    _classify_pre_buy_boundary_activity_buy_shape_detail,
    build_core_risk_off_floor_bucket_rows,
    build_core_risk_off_floor_diagnostic_rows,
    build_core_risk_off_floor_diagnostics_report,
    build_core_risk_off_floor_report,
    build_core_risk_off_floor_v2_bucket_rows,
    build_core_risk_off_floor_v2_diagnostic_rows,
    build_core_risk_off_floor_v2_diagnostics_report,
    build_core_risk_off_floor_v2_report,
    build_core_risk_off_floor_v3_bucket_rows,
    build_core_risk_off_floor_v3_diagnostic_rows,
    build_core_risk_off_floor_v3_diagnostics_report,
    build_core_risk_off_floor_v3_report,
    build_core_risk_off_floor_v5_bucket_rows,
    build_core_risk_off_floor_v5_diagnostic_rows,
    build_core_risk_off_floor_v5_diagnostics_report,
    build_core_risk_off_floor_v5_report,
    build_core_risk_off_topk_projection_rows,
    build_shadow_experiment_rows,
    build_trigger_proxy_aggregate_items,
    build_watch_projection_shadow_rows,
    calculate_trigger_proxy_metrics,
    explode_eligibility_reason_rows,
)


def test_calculate_trigger_proxy_metrics_returns_forward_return_mfe_mae() -> None:
    bars = [
        DailyPriceBar("20260701", close_price=100.0, high_price=101.0, low_price=99.0),
        DailyPriceBar("20260702", close_price=103.0, high_price=105.0, low_price=98.0),
        DailyPriceBar("20260703", close_price=102.0, high_price=106.0, low_price=97.0),
        DailyPriceBar("20260704", close_price=108.0, high_price=110.0, low_price=101.0),
        DailyPriceBar("20260705", close_price=107.0, high_price=109.0, low_price=100.0),
        DailyPriceBar("20260706", close_price=111.0, high_price=112.0, low_price=102.0),
    ]

    result = calculate_trigger_proxy_metrics(bars)

    assert result.forward_return_pct_by_horizon[1] == pytest.approx(3.0)
    assert result.forward_return_pct_by_horizon[3] == pytest.approx(8.0)
    assert result.forward_return_pct_by_horizon[5] == pytest.approx(11.0)
    assert result.mfe_pct_by_horizon[3] == pytest.approx(10.0)
    assert result.mae_pct_by_horizon[3] == pytest.approx(-3.0)
    assert result.mfe_pct_by_horizon[5] == pytest.approx(12.0)
    assert result.mae_pct_by_horizon[5] == pytest.approx(-3.0)


def test_calculate_trigger_proxy_metrics_returns_none_when_horizon_unavailable() -> None:
    bars = [
        DailyPriceBar("20260701", close_price=100.0, high_price=101.0, low_price=99.0),
        DailyPriceBar("20260702", close_price=101.0, high_price=102.0, low_price=98.0),
    ]

    result = calculate_trigger_proxy_metrics(bars)

    assert result.forward_return_pct_by_horizon[1] == pytest.approx(1.0)
    assert result.forward_return_pct_by_horizon[3] is None
    assert result.mfe_pct_by_horizon[5] is None
    assert result.mae_pct_by_horizon[5] is None


def test_build_trigger_proxy_aggregate_items_and_eligibility_explode() -> None:
    rows = [
        {
            "primary_candidate": "WATCH",
            "source_type": "core",
            "eligibility_reasons": ["eligibility_core_risk_off_ranking_blocked"],
            "t1_return_pct": 1.0,
            "t3_return_pct": 2.0,
            "t5_return_pct": 3.0,
            "t3_mfe_pct": 4.0,
            "t3_mae_pct": -1.0,
            "t5_mfe_pct": 5.0,
            "t5_mae_pct": -2.0,
        },
        {
            "primary_candidate": "WATCH",
            "source_type": "core",
            "eligibility_reasons": [],
            "t1_return_pct": -1.0,
            "t3_return_pct": None,
            "t5_return_pct": 1.0,
            "t3_mfe_pct": None,
            "t3_mae_pct": None,
            "t5_mfe_pct": 2.0,
            "t5_mae_pct": -3.0,
        },
    ]

    candidate_items = build_trigger_proxy_aggregate_items(
        rows,
        bucket_key="primary_candidate",
    )
    exploded = explode_eligibility_reason_rows(rows)
    eligibility_items = build_trigger_proxy_aggregate_items(
        exploded,
        bucket_key="eligibility_reason",
    )

    assert candidate_items[0].bucket == "WATCH"
    assert candidate_items[0].sample_count == 2
    assert candidate_items[0].t1_return_pct_avg == 0.0
    assert candidate_items[0].t3_return_pct_avg == 2.0
    assert candidate_items[0].positive_t3_hit_count == 1
    assert candidate_items[0].positive_t3_hit_rate == 1.0

    assert eligibility_items[0].bucket == "eligibility_core_risk_off_ranking_blocked"
    assert eligibility_items[0].sample_count == 1
    assert eligibility_items[1].bucket == "none"


def test_classify_pre_buy_boundary_activity_buy_shape_detail_returns_reason_and_gap_band() -> None:
    assert (
        _classify_pre_buy_boundary_activity_buy_shape_detail(
            pre_buy_boundary_activity_counterfactual_next_gate="buy_shape_after_activity_small_entry_gap",
            deterministic_buy_shape_block_reason="watch_from_exit_setup",
            effective_buy_candidate_threshold_gap_band="small_entry_gap",
        )
        == "watch_from_exit_setup|small_entry_gap"
    )
    assert (
        _classify_pre_buy_boundary_activity_buy_shape_detail(
            pre_buy_boundary_activity_counterfactual_next_gate="buy_shape_after_activity_moderate_entry_gap",
            deterministic_buy_shape_block_reason="watch_from_entry_setup",
            effective_buy_candidate_threshold_gap_band="moderate_entry_gap",
        )
        == "watch_from_entry_setup|moderate_entry_gap"
    )
    assert (
        _classify_pre_buy_boundary_activity_buy_shape_detail(
            pre_buy_boundary_activity_counterfactual_next_gate="signal_before_activity_release",
            deterministic_buy_shape_block_reason="watch_from_exit_setup",
            effective_buy_candidate_threshold_gap_band="small_entry_gap",
        )
        == "non_buy_shape_after_activity"
    )


def test_build_watch_projection_shadow_rows_marks_topk_and_overlap() -> None:
    rows = [
        {
            "trade_date": "2026-07-01",
            "symbol": "AAA",
            "source_type": "core",
            "eligibility_passed": True,
            "watch_candidate": True,
            "entry_score": 0.70,
            "ranking_score": 0.80,
        },
        {
            "trade_date": "2026-07-01",
            "symbol": "BBB",
            "source_type": "core",
            "eligibility_passed": True,
            "watch_candidate": True,
            "entry_score": 0.61,
            "ranking_score": 0.54,
        },
        {
            "trade_date": "2026-07-01",
            "symbol": "CCC",
            "source_type": "event_overlay",
            "eligibility_passed": True,
            "watch_candidate": False,
            "entry_score": 0.59,
            "ranking_score": 0.53,
        },
        {
            "trade_date": "2026-07-01",
            "symbol": "EEE",
            "source_type": "market_overlay",
            "eligibility_passed": True,
            "watch_candidate": False,
            "entry_score": 0.53,
            "ranking_score": 0.51,
        },
        {
            "trade_date": "2026-07-01",
            "symbol": "FFF",
            "source_type": "core",
            "eligibility_passed": True,
            "watch_candidate": False,
            "entry_score": 0.52,
            "ranking_score": 0.50,
        },
        {
            "trade_date": "2026-07-01",
            "symbol": "GGG",
            "source_type": "core",
            "eligibility_passed": True,
            "watch_candidate": False,
            "entry_score": 0.51,
            "ranking_score": 0.49,
        },
        {
            "trade_date": "2026-07-01",
            "symbol": "DDD",
            "source_type": "core",
            "eligibility_passed": False,
            "watch_candidate": True,
            "entry_score": 0.40,
            "ranking_score": 0.30,
        },
    ]

    result = build_watch_projection_shadow_rows(rows)
    by_symbol = {row["symbol"]: row for row in result}

    assert by_symbol["AAA"]["shadow_buy_topk"] is True
    assert by_symbol["AAA"]["shadow_watch_topk"] is False
    assert by_symbol["AAA"]["watch_projection_bucket"] == "legacy_watch_only"

    assert by_symbol["BBB"]["shadow_buy_topk"] is False
    assert by_symbol["BBB"]["shadow_watch_topk"] is True
    assert by_symbol["BBB"]["watch_projection_bucket"] == "legacy_and_shadow_watch"
    assert by_symbol["BBB"]["shadow_watch_rank"] == 1

    assert by_symbol["CCC"]["shadow_watch_topk"] is True
    assert by_symbol["CCC"]["watch_projection_bucket"] == "shadow_watch_only"

    assert by_symbol["DDD"]["shadow_watch_topk"] is False
    assert by_symbol["DDD"]["watch_projection_bucket"] == "legacy_watch_only"


def test_build_shadow_experiment_rows_buckets_active_and_inactive() -> None:
    rows = [
        {
            "symbol": "AAA",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_would_pass": True,
            },
        },
        {
            "symbol": "BBB",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_would_pass": False,
            },
        },
        {
            "symbol": "CCC",
            "core_risk_off_experiment": {
                "active": False,
                "shadow_would_pass": False,
            },
        },
    ]

    result = build_shadow_experiment_rows(
        rows,
        experiment_key="core_risk_off_experiment",
        bucket_key="core_risk_off_shadow_bucket",
    )
    by_symbol = {row["symbol"]: row for row in result}

    assert by_symbol["AAA"]["core_risk_off_shadow_bucket"] == "shadow_would_pass"
    assert by_symbol["BBB"]["core_risk_off_shadow_bucket"] == "shadow_blocked"
    assert by_symbol["CCC"]["core_risk_off_shadow_bucket"] == "inactive"


def test_build_core_risk_off_topk_projection_rows_buckets_selected_candidate_inactive() -> None:
    rows = [
        {
            "symbol": "AAA",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_topk_candidate": True,
                "shadow_topk_selected": True,
            },
        },
        {
            "symbol": "BBB",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_topk_candidate": True,
                "shadow_topk_selected": False,
            },
        },
        {
            "symbol": "CCC",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
        },
        {
            "symbol": "DDD",
            "core_risk_off_experiment": {
                "active": False,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
        },
    ]

    result = build_core_risk_off_topk_projection_rows(rows)
    by_symbol = {row["symbol"]: row for row in result}

    assert by_symbol["AAA"]["core_risk_off_topk_bucket"] == "shadow_topk_selected"
    assert by_symbol["BBB"]["core_risk_off_topk_bucket"] == "shadow_topk_candidate_only"
    assert by_symbol["CCC"]["core_risk_off_topk_bucket"] == "shadow_not_candidate"
    assert by_symbol["DDD"]["core_risk_off_topk_bucket"] == "inactive"


def test_build_core_risk_off_floor_bucket_rows_marks_bucket_and_inactive() -> None:
    rows = [
        {
            "symbol": "AAA",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_bucket": "strict_pass",
            },
        },
        {
            "symbol": "BBB",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_bucket": "mild_relax",
            },
        },
        {
            "symbol": "CCC",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_bucket": "deep_negative",
            },
        },
        {
            "symbol": "DDD",
            "core_risk_off_experiment": {
                "active": False,
            },
        },
    ]

    result = build_core_risk_off_floor_bucket_rows(rows)
    by_symbol = {row["symbol"]: row for row in result}

    assert by_symbol["AAA"]["core_risk_off_floor_bucket"] == "strict_pass"
    assert by_symbol["BBB"]["core_risk_off_floor_bucket"] == "mild_relax"
    assert by_symbol["CCC"]["core_risk_off_floor_bucket"] == "deep_negative"
    assert by_symbol["DDD"]["core_risk_off_floor_bucket"] == "inactive"


def test_build_core_risk_off_floor_report_includes_bucket_counts_and_proxy_readiness() -> None:
    rows = [
        {
            "symbol": "AAA",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_bucket": "mild_relax",
            },
            "t1_return_pct": 1.2,
            "t3_return_pct": None,
            "t5_return_pct": None,
        },
        {
            "symbol": "BBB",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_bucket": "deep_negative",
            },
            "t1_return_pct": -0.5,
            "t3_return_pct": 2.0,
            "t5_return_pct": None,
        },
        {
            "symbol": "CCC",
            "core_risk_off_experiment": {
                "active": False,
            },
            "t1_return_pct": None,
            "t3_return_pct": None,
            "t5_return_pct": None,
        },
    ]

    report = build_core_risk_off_floor_report(rows)
    items = {item["bucket"]: item for item in report["items"]}

    assert report["active_sample_count"] == 2
    assert report["non_inactive_bucket_count"] == 2
    assert report["proxy_availability"]["t1_ready_count"] == 2
    assert report["proxy_availability"]["t3_ready_count"] == 1
    assert report["proxy_availability"]["t5_ready_count"] == 0
    assert items["mild_relax"]["sample_count"] == 1
    assert items["deep_negative"]["sample_count"] == 1
    assert items["inactive"]["sample_count"] == 1


def test_build_core_risk_off_floor_report_keeps_unknown_active_bucket_visible() -> None:
    rows = [
        {
            "symbol": "AAA",
            "core_risk_off_experiment": {
                "active": True,
            },
            "t1_return_pct": 0.4,
            "t3_return_pct": 0.8,
            "t5_return_pct": None,
        },
        {
            "symbol": "BBB",
            "core_risk_off_experiment": {
                "active": False,
            },
            "t1_return_pct": None,
            "t3_return_pct": None,
            "t5_return_pct": None,
        },
    ]

    report = build_core_risk_off_floor_report(rows)
    items = {item["bucket"]: item for item in report["items"]}

    assert report["active_sample_count"] == 1
    assert report["non_inactive_bucket_count"] == 1
    assert items["unknown"]["sample_count"] == 1
    assert items["unknown"]["t1_return_pct_avg"] == 0.4
    assert items["unknown"]["t3_return_pct_avg"] == 0.8


def test_build_core_risk_off_floor_diagnostic_rows_classifies_bands_and_gate() -> None:
    rows = [
        {
            "symbol": "AAA",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_bucket": "mild_relax",
                "shadow_overall_score": -0.04,
                "shadow_slow_score": -0.10,
                "shadow_entry_score": 0.30,
                "shadow_rank_candidate_score": 0.33,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": False,
                "shadow_slow_pass": False,
                "shadow_signal_pass": False,
                "shadow_entry_observe_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
        },
        {
            "symbol": "BBB",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_bucket": "deep_negative",
                "shadow_overall_score": -0.20,
                "shadow_slow_score": -0.20,
                "shadow_entry_score": 0.20,
                "shadow_rank_candidate_score": 0.35,
                "shadow_activity_pass": False,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": False,
                "shadow_slow_pass": False,
                "shadow_signal_pass": False,
                "shadow_entry_observe_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
        },
        {
            "symbol": "CCC",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_bucket": "deep_negative",
                "shadow_overall_score": -0.30,
                "shadow_slow_score": -0.10,
                "shadow_entry_score": 0.30,
                "shadow_rank_candidate_score": 0.40,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": False,
                "shadow_slow_pass": False,
                "shadow_signal_pass": False,
                "shadow_entry_observe_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
        },
        {
            "symbol": "DDD",
            "core_risk_off_experiment": {
                "active": False,
            },
        },
    ]

    result = build_core_risk_off_floor_diagnostic_rows(rows)
    by_symbol = {row["symbol"]: row for row in result}

    assert by_symbol["AAA"]["overall_band"] == "mild_window"
    assert by_symbol["AAA"]["slow_band"] == "mild_window"
    assert by_symbol["AAA"]["moderate_gate_bucket"] == "moderate_ready"
    assert by_symbol["AAA"]["blocking_reason"] == "mild_relax_pass"

    assert by_symbol["BBB"]["overall_band"] == "moderate_window"
    assert by_symbol["BBB"]["slow_band"] == "moderate_window"
    assert by_symbol["BBB"]["moderate_gate_bucket"] == "activity_blocked"
    assert by_symbol["BBB"]["blocking_reason"] == "overall_below_mild_floor"

    assert by_symbol["CCC"]["overall_band"] == "deep_negative"
    assert by_symbol["CCC"]["moderate_gate_bucket"] == "signal_window_miss"
    assert by_symbol["CCC"]["blocking_reason"] == "overall_below_mild_floor"

    assert by_symbol["DDD"]["core_risk_off_floor_bucket"] == "inactive"
    assert by_symbol["DDD"]["moderate_gate_bucket"] == "inactive"
    assert by_symbol["DDD"]["blocking_reason"] == "inactive"


def test_build_core_risk_off_floor_diagnostics_report_aggregates_reason_and_gate() -> None:
    rows = [
        {
            "symbol": "AAA",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_bucket": "mild_relax",
                "shadow_overall_score": -0.02,
                "shadow_slow_score": -0.10,
                "shadow_entry_score": 0.18,
                "shadow_rank_candidate_score": 0.31,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": False,
                "shadow_slow_pass": False,
                "shadow_signal_pass": False,
                "shadow_entry_observe_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "t1_return_pct": 1.0,
            "t3_return_pct": 2.0,
            "t5_return_pct": None,
            "t3_mfe_pct": 2.5,
            "t3_mae_pct": -0.5,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
        {
            "symbol": "BBB",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_bucket": "deep_negative",
                "shadow_overall_score": -0.18,
                "shadow_slow_score": -0.19,
                "shadow_entry_score": 0.20,
                "shadow_rank_candidate_score": 0.33,
                "shadow_activity_pass": False,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": False,
                "shadow_slow_pass": False,
                "shadow_signal_pass": False,
                "shadow_entry_observe_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "t1_return_pct": -1.0,
            "t3_return_pct": -0.4,
            "t5_return_pct": None,
            "t3_mfe_pct": 0.6,
            "t3_mae_pct": -1.4,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
        {
            "symbol": "CCC",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "core_risk_off_experiment": {
                "active": False,
            },
            "t1_return_pct": 0.0,
            "t3_return_pct": None,
            "t5_return_pct": None,
            "t3_mfe_pct": None,
            "t3_mae_pct": None,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
    ]

    report = build_core_risk_off_floor_diagnostics_report(rows, sample_limit=2)
    gate_items = {item["bucket"]: item for item in report["moderate_gate_items"]}
    reason_items = {item["bucket"]: item for item in report["blocking_reason_items"]}

    assert report["sample_count"] == 3
    assert report["active_sample_count"] == 2
    assert report["bucket_counts"]["mild_relax"] == 1
    assert report["bucket_counts"]["deep_negative"] == 1
    assert report["bucket_counts"]["inactive"] == 1
    assert gate_items["moderate_ready"]["sample_count"] == 1
    assert gate_items["activity_blocked"]["sample_count"] == 1
    assert reason_items["mild_relax_pass"]["sample_count"] == 1
    assert reason_items["overall_below_mild_floor"]["sample_count"] == 1
    assert len(report["samples"]) == 2


def test_build_core_risk_off_floor_v2_bucket_rows_and_report() -> None:
    rows = [
        {
            "symbol": "AAA",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v2_bucket": "mild_relax",
            },
            "t1_return_pct": 1.2,
            "t3_return_pct": 0.5,
            "t5_return_pct": None,
        },
        {
            "symbol": "BBB",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v2_bucket": "moderate_relax",
            },
            "t1_return_pct": -0.5,
            "t3_return_pct": 2.0,
            "t5_return_pct": None,
        },
        {
            "symbol": "CCC",
            "core_risk_off_experiment": {
                "active": False,
            },
            "t1_return_pct": None,
            "t3_return_pct": None,
            "t5_return_pct": None,
        },
    ]

    result = build_core_risk_off_floor_v2_bucket_rows(rows)
    by_symbol = {row["symbol"]: row for row in result}
    report = build_core_risk_off_floor_v2_report(rows)
    items = {item["bucket"]: item for item in report["items"]}

    assert by_symbol["AAA"]["core_risk_off_floor_v2_bucket"] == "mild_relax"
    assert by_symbol["BBB"]["core_risk_off_floor_v2_bucket"] == "moderate_relax"
    assert by_symbol["CCC"]["core_risk_off_floor_v2_bucket"] == "inactive"
    assert report["active_sample_count"] == 2
    assert items["mild_relax"]["sample_count"] == 1
    assert items["moderate_relax"]["sample_count"] == 1
    assert items["inactive"]["sample_count"] == 1


def test_build_core_risk_off_floor_v2_diagnostics_report_uses_v2_thresholds() -> None:
    rows = [
        {
            "symbol": "AAA",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v2_bucket": "moderate_relax",
                "shadow_overall_score": -0.18,
                "shadow_slow_score": -0.20,
                "shadow_entry_score": 0.19,
                "shadow_rank_candidate_score": 0.31,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "t1_return_pct": 0.7,
            "t3_return_pct": 1.2,
            "t5_return_pct": None,
            "t3_mfe_pct": 1.8,
            "t3_mae_pct": -0.4,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
        {
            "symbol": "BBB",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v2_bucket": "deep_negative",
                "shadow_overall_score": -0.23,
                "shadow_slow_score": -0.20,
                "shadow_entry_score": 0.19,
                "shadow_rank_candidate_score": 0.31,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "t1_return_pct": -0.6,
            "t3_return_pct": -0.3,
            "t5_return_pct": None,
            "t3_mfe_pct": 0.4,
            "t3_mae_pct": -0.8,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
    ]

    diagnostic_rows = build_core_risk_off_floor_v2_diagnostic_rows(rows)
    by_symbol = {row["symbol"]: row for row in diagnostic_rows}
    report = build_core_risk_off_floor_v2_diagnostics_report(rows, sample_limit=5)
    gate_items = {item["bucket"]: item for item in report["moderate_gate_items"]}
    reason_items = {item["bucket"]: item for item in report["blocking_reason_items"]}

    assert by_symbol["AAA"]["core_risk_off_floor_v2_bucket"] == "moderate_relax"
    assert by_symbol["AAA"]["moderate_gate_bucket"] == "moderate_ready"
    assert by_symbol["AAA"]["blocking_reason"] == "moderate_relax_pass"
    assert by_symbol["BBB"]["moderate_gate_bucket"] == "signal_window_miss"
    assert by_symbol["BBB"]["blocking_reason"] == "overall_below_mild_floor"
    assert report["bucket_counts"]["moderate_relax"] == 1
    assert report["bucket_counts"]["deep_negative"] == 1
    assert gate_items["moderate_ready"]["sample_count"] == 1
    assert gate_items["signal_window_miss"]["sample_count"] == 1
    assert reason_items["moderate_relax_pass"]["sample_count"] == 1
    assert reason_items["overall_below_mild_floor"]["sample_count"] == 1


def test_build_core_risk_off_floor_v2_backfills_bucket_when_metadata_missing() -> None:
    rows = [
        {
            "symbol": "AAA",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_overall_score": -0.12,
                "shadow_slow_score": -0.10,
                "shadow_entry_score": 0.08,
                "shadow_rank_candidate_score": 0.24,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
            },
            "t1_return_pct": 0.3,
            "t3_return_pct": 0.4,
            "t5_return_pct": None,
            "t3_mfe_pct": 0.8,
            "t3_mae_pct": -0.2,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        }
    ]

    rows_v2 = build_core_risk_off_floor_v2_bucket_rows(rows)
    report_v2 = build_core_risk_off_floor_v2_report(rows)
    diagnostics_v2 = build_core_risk_off_floor_v2_diagnostics_report(rows, sample_limit=5)

    assert rows_v2[0]["core_risk_off_floor_v2_bucket"] == "mild_relax"
    items = {item["bucket"]: item for item in report_v2["items"]}
    assert items["mild_relax"]["sample_count"] == 1
    assert diagnostics_v2["bucket_counts"]["mild_relax"] == 1
    assert diagnostics_v2["samples"][0]["core_risk_off_floor_v2_bucket"] == "mild_relax"


def test_build_core_risk_off_floor_v3_bucket_rows_and_report() -> None:
    rows = [
        {
            "symbol": "AAA",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v3_bucket": "mild_relax",
            },
            "t1_return_pct": 0.9,
            "t3_return_pct": 1.3,
            "t5_return_pct": None,
        },
        {
            "symbol": "BBB",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v3_bucket": "deep_negative",
            },
            "t1_return_pct": -0.4,
            "t3_return_pct": -0.2,
            "t5_return_pct": None,
        },
        {
            "symbol": "CCC",
            "core_risk_off_experiment": {
                "active": False,
            },
            "t1_return_pct": None,
            "t3_return_pct": None,
            "t5_return_pct": None,
        },
    ]

    result = build_core_risk_off_floor_v3_bucket_rows(rows)
    by_symbol = {row["symbol"]: row for row in result}
    report = build_core_risk_off_floor_v3_report(rows)
    items = {item["bucket"]: item for item in report["items"]}

    assert by_symbol["AAA"]["core_risk_off_floor_v3_bucket"] == "mild_relax"
    assert by_symbol["BBB"]["core_risk_off_floor_v3_bucket"] == "deep_negative"
    assert by_symbol["CCC"]["core_risk_off_floor_v3_bucket"] == "inactive"
    assert report["active_sample_count"] == 2
    assert items["mild_relax"]["sample_count"] == 1
    assert items["deep_negative"]["sample_count"] == 1
    assert items["inactive"]["sample_count"] == 1


def test_build_core_risk_off_floor_v3_diagnostics_report_uses_v3_thresholds() -> None:
    rows = [
        {
            "symbol": "AAA",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v3_bucket": "mild_relax",
                "shadow_overall_score": -0.18,
                "shadow_slow_score": -0.10,
                "shadow_entry_score": 0.10,
                "shadow_rank_candidate_score": 0.24,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "t1_return_pct": 0.4,
            "t3_return_pct": 0.8,
            "t5_return_pct": None,
            "t3_mfe_pct": 1.2,
            "t3_mae_pct": -0.3,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
        {
            "symbol": "BBB",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v3_bucket": "deep_negative",
                "shadow_overall_score": -0.23,
                "shadow_slow_score": -0.16,
                "shadow_entry_score": 0.18,
                "shadow_rank_candidate_score": 0.30,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "t1_return_pct": -0.5,
            "t3_return_pct": -0.1,
            "t5_return_pct": None,
            "t3_mfe_pct": 0.3,
            "t3_mae_pct": -0.7,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
    ]

    diagnostic_rows = build_core_risk_off_floor_v3_diagnostic_rows(rows)
    by_symbol = {row["symbol"]: row for row in diagnostic_rows}
    report = build_core_risk_off_floor_v3_diagnostics_report(rows, sample_limit=5)
    gate_items = {item["bucket"]: item for item in report["moderate_gate_items"]}
    reason_items = {item["bucket"]: item for item in report["blocking_reason_items"]}

    assert by_symbol["AAA"]["core_risk_off_floor_v3_bucket"] == "mild_relax"
    assert by_symbol["AAA"]["blocking_reason"] == "mild_relax_pass"
    assert by_symbol["AAA"]["moderate_gate_bucket"] == "entry_below_0_12"
    assert by_symbol["BBB"]["blocking_reason"] == "overall_below_mild_floor"
    assert by_symbol["BBB"]["moderate_gate_bucket"] == "moderate_ready"
    assert report["bucket_counts"]["mild_relax"] == 1
    assert report["bucket_counts"]["deep_negative"] == 1
    assert gate_items["entry_below_0_12"]["sample_count"] == 1
    assert gate_items["moderate_ready"]["sample_count"] == 1
    assert reason_items["mild_relax_pass"]["sample_count"] == 1
    assert reason_items["overall_below_mild_floor"]["sample_count"] == 1


def test_build_core_risk_off_floor_v3_backfills_bucket_when_metadata_missing() -> None:
    rows = [
        {
            "symbol": "AAA",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_overall_score": -0.18,
                "shadow_slow_score": -0.10,
                "shadow_entry_score": 0.08,
                "shadow_rank_candidate_score": 0.24,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
            },
            "t1_return_pct": 0.2,
            "t3_return_pct": 0.5,
            "t5_return_pct": None,
            "t3_mfe_pct": 0.6,
            "t3_mae_pct": -0.2,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        }
    ]

    rows_v3 = build_core_risk_off_floor_v3_bucket_rows(rows)
    report_v3 = build_core_risk_off_floor_v3_report(rows)
    diagnostics_v3 = build_core_risk_off_floor_v3_diagnostics_report(rows, sample_limit=5)

    assert rows_v3[0]["core_risk_off_floor_v3_bucket"] == "mild_relax"
    items = {item["bucket"]: item for item in report_v3["items"]}
    assert items["mild_relax"]["sample_count"] == 1
    assert diagnostics_v3["bucket_counts"]["mild_relax"] == 1
    assert diagnostics_v3["samples"][0]["core_risk_off_floor_v3_bucket"] == "mild_relax"


def test_build_core_risk_off_floor_v5_bucket_rows_and_report_use_v5_scores() -> None:
    rows = [
        {
            "symbol": "AAA",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_overall_score_v5": -0.18,
                "shadow_slow_score_v5": -0.10,
                "shadow_entry_score": 0.10,
                "shadow_rank_candidate_score": 0.24,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
            },
            "t1_return_pct": 0.8,
            "t3_return_pct": 1.1,
            "t5_return_pct": None,
        },
        {
            "symbol": "BBB",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_overall_score_v5": -0.32,
                "shadow_slow_score_v5": -0.30,
                "shadow_entry_score": 0.18,
                "shadow_rank_candidate_score": 0.31,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
            },
            "t1_return_pct": -0.4,
            "t3_return_pct": -0.2,
            "t5_return_pct": None,
        },
        {
            "symbol": "CCC",
            "core_risk_off_experiment": {
                "active": False,
            },
            "t1_return_pct": None,
            "t3_return_pct": None,
            "t5_return_pct": None,
        },
    ]

    result = build_core_risk_off_floor_v5_bucket_rows(rows)
    by_symbol = {row["symbol"]: row for row in result}
    report = build_core_risk_off_floor_v5_report(rows)
    items = {item["bucket"]: item for item in report["items"]}

    assert by_symbol["AAA"]["core_risk_off_floor_v5_bucket"] == "mild_relax"
    assert by_symbol["BBB"]["core_risk_off_floor_v5_bucket"] == "deep_negative"
    assert by_symbol["CCC"]["core_risk_off_floor_v5_bucket"] == "inactive"
    assert report["active_sample_count"] == 2
    assert items["mild_relax"]["sample_count"] == 1
    assert items["deep_negative"]["sample_count"] == 1
    assert items["inactive"]["sample_count"] == 1


def test_build_core_risk_off_floor_v5_diagnostics_report_uses_v5_score_fields() -> None:
    rows = [
        {
            "symbol": "AAA",
            "trade_date": "2026-07-08",
            "price_vs_sma_60_pct": -1.2,
            "return_3m_pct": -4.0,
            "source_type": "core",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_overall_score_v5": -0.18,
                "shadow_slow_score_v5": -0.14,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.15,
                    "slow_trend": -0.10,
                },
                "shadow_entry_score": 0.10,
                "shadow_rank_candidate_score": 0.24,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "t1_return_pct": 0.4,
            "t3_return_pct": 0.8,
            "t5_return_pct": None,
            "t3_mfe_pct": 1.2,
            "t3_mae_pct": -0.3,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
        {
            "symbol": "BBB",
            "trade_date": "2026-07-08",
            "price_vs_sma_60_pct": -4.0,
            "return_3m_pct": -12.0,
            "source_type": "core",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_overall_score_v5": -0.24,
                "shadow_slow_score_v5": -0.20,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.55,
                    "slow_trend": -0.25,
                },
                "shadow_entry_score": 0.18,
                "shadow_rank_candidate_score": 0.31,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "t1_return_pct": -0.5,
            "t3_return_pct": -0.1,
            "t5_return_pct": None,
            "t3_mfe_pct": 0.3,
            "t3_mae_pct": -0.7,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
    ]

    diagnostic_rows = build_core_risk_off_floor_v5_diagnostic_rows(rows)
    by_symbol = {row["symbol"]: row for row in diagnostic_rows}
    report = build_core_risk_off_floor_v5_diagnostics_report(rows, sample_limit=5)
    gate_items = {item["bucket"]: item for item in report["moderate_gate_items"]}
    reason_items = {item["bucket"]: item for item in report["blocking_reason_items"]}
    slow_candidate_items = {
        item["bucket"]: item for item in report["slow_relax_candidate_items"]
    }
    slow_momentum_items = {
        item["bucket"]: item for item in report["slow_momentum_band_items"]
    }
    slow_trend_items = {
        item["bucket"]: item for item in report["slow_trend_band_items"]
    }
    slow_trend_candidate_items = {
        item["bucket"]: item for item in report["slow_trend_relax_candidate_items"]
    }
    slow_trend_candidate_report_items = {
        item["bucket"]: item
        for item in report["slow_trend_relax_candidate_report"]["items"]
    }
    active_slow_trend_candidate_report_items = {
        item["bucket"]: item
        for item in report["active_slow_trend_relax_candidate_report"]["items"]
    }
    active_slow_trend_projection_items = {
        item["bucket"]: item
        for item in report["active_slow_trend_projection_items"]
    }
    active_slow_trend_trade_date_projection_items = {
        item["bucket"]: item
        for item in report["active_slow_trend_trade_date_projection_items"]
    }
    slow_trend_path_items = {
        item["bucket"]: item for item in report["slow_trend_path_items"]
    }
    projection_reason_items = {
        item["bucket"]: item
        for item in report["shadow_relax_projection_block_reason_items"]
    }
    topk_gate_reason_items = {
        item["bucket"]: item
        for item in report["shadow_topk_candidate_gate_reason_items"]
    }
    eligibility_block_items = {
        item["bucket"]: item
        for item in report["eligibility_block_reason_primary_items"]
    }
    signal_floor_path_items = {
        item["bucket"]: item
        for item in report["shadow_signal_floor_block_path_items"]
    }
    signal_floor_miss_detail_items = {
        item["bucket"]: item
        for item in report["shadow_signal_floor_miss_detail_items"]
    }
    slow_floor_shadow_relax_path_items = {
        item["bucket"]: item
        for item in report["slow_floor_shadow_relax_path_items"]
    }

    assert by_symbol["AAA"]["core_risk_off_floor_v5_bucket"] == "mild_relax"
    assert by_symbol["AAA"]["blocking_reason"] == "mild_relax_pass"
    assert by_symbol["AAA"]["slow_relax_candidate_band"] == "mild_candidate"
    assert by_symbol["AAA"]["slow_trend_relax_candidate_band"] == "trend_mild_candidate"
    assert by_symbol["AAA"]["slow_component_path"] == "micro_negative|micro_negative"
    assert by_symbol["AAA"]["slow_trend_path"] == "trend_mild_candidate|micro_negative"
    assert by_symbol["AAA"]["price_vs_sma_60_pct"] == -1.2
    assert by_symbol["AAA"]["return_3m_pct"] == -4.0
    assert by_symbol["BBB"]["core_risk_off_floor_v5_bucket"] == "moderate_relax"
    assert by_symbol["BBB"]["blocking_reason"] == "moderate_relax_pass"
    assert by_symbol["BBB"]["slow_relax_candidate_band"] == "moderate_candidate"
    assert by_symbol["BBB"]["slow_trend_relax_candidate_band"] == "trend_moderate_candidate"
    assert by_symbol["BBB"]["slow_component_path"] == "moderate_negative|micro_negative"
    assert by_symbol["BBB"]["slow_trend_path"] == "trend_moderate_candidate|micro_negative"
    assert gate_items["entry_below_0_12"]["sample_count"] == 1
    assert gate_items["moderate_ready"]["sample_count"] == 1
    assert reason_items["mild_relax_pass"]["sample_count"] == 1
    assert reason_items["moderate_relax_pass"]["sample_count"] == 1
    assert slow_candidate_items["mild_candidate"]["sample_count"] == 1
    assert slow_candidate_items["moderate_candidate"]["sample_count"] == 1
    assert slow_momentum_items["micro_negative"]["sample_count"] == 1
    assert slow_momentum_items["moderate_negative"]["sample_count"] == 1
    assert slow_trend_items["micro_negative"]["sample_count"] == 2
    assert slow_trend_candidate_items["trend_mild_candidate"]["sample_count"] == 1
    assert slow_trend_candidate_items["trend_moderate_candidate"]["sample_count"] == 1
    assert slow_trend_candidate_report_items["trend_mild_candidate"]["sample_count"] == 1
    assert slow_trend_candidate_report_items["trend_moderate_candidate"]["sample_count"] == 1
    assert active_slow_trend_candidate_report_items["trend_mild_candidate"]["sample_count"] == 1
    assert active_slow_trend_candidate_report_items["trend_moderate_candidate"]["sample_count"] == 1
    assert active_slow_trend_projection_items["trend_mild_candidate"]["candidate_count"] == 0
    assert active_slow_trend_projection_items["trend_moderate_candidate"]["candidate_count"] == 0
    assert active_slow_trend_trade_date_projection_items["2026-07-08|trend_mild_candidate"]["sample_count"] == 1
    assert active_slow_trend_trade_date_projection_items["2026-07-08|trend_moderate_candidate"]["sample_count"] == 1
    assert slow_trend_path_items["trend_mild_candidate|micro_negative"]["sample_count"] == 1
    assert slow_trend_path_items["trend_moderate_candidate|micro_negative"]["sample_count"] == 1
    assert projection_reason_items["non_deep_negative_bucket"]["sample_count"] == 2
    assert topk_gate_reason_items["signal_both_floor_miss"]["sample_count"] == 2
    assert eligibility_block_items["none"]["sample_count"] == 2
    assert signal_floor_path_items["overall_fail|slow_fail|moderate_window|mild_window|micro_negative|micro_negative"]["sample_count"] == 1
    assert signal_floor_path_items["overall_fail|slow_fail|moderate_window|moderate_window|moderate_negative|micro_negative"]["sample_count"] == 1
    assert signal_floor_miss_detail_items["double_near_miss"]["sample_count"] == 2
    assert slow_floor_shadow_relax_path_items["non_target_band"]["sample_count"] == 1
    assert slow_floor_shadow_relax_path_items["non_target_miss_detail:double_near_miss"]["sample_count"] == 1


def test_build_core_risk_off_floor_v5_diagnostics_report_trend_band_boundaries() -> None:
    rows = [
        {
            "symbol": "A",
            "trade_date": "2026-07-08",
            "price_vs_sma_60_pct": -0.5,
            "source_type": "core",
            "core_risk_off_experiment": {"active": True},
        },
        {
            "symbol": "B",
            "trade_date": "2026-07-08",
            "price_vs_sma_60_pct": -2.5,
            "source_type": "core",
            "core_risk_off_experiment": {"active": True},
        },
        {
            "symbol": "C",
            "trade_date": "2026-07-08",
            "price_vs_sma_60_pct": -6.0,
            "source_type": "core",
            "core_risk_off_experiment": {"active": True},
        },
        {
            "symbol": "D",
            "trade_date": "2026-07-08",
            "price_vs_sma_60_pct": -12.0,
            "source_type": "core",
            "core_risk_off_experiment": {"active": True},
        },
        {
            "symbol": "E",
            "trade_date": "2026-07-08",
            "price_vs_sma_60_pct": None,
            "source_type": "core",
            "core_risk_off_experiment": {"active": True},
        },
    ]

    diagnostic_rows = build_core_risk_off_floor_v5_diagnostic_rows(rows)
    by_symbol = {row["symbol"]: row for row in diagnostic_rows}

    assert by_symbol["A"]["slow_trend_relax_candidate_band"] == "trend_strict_ready"
    assert by_symbol["B"]["slow_trend_relax_candidate_band"] == "trend_moderate_candidate"
    assert by_symbol["C"]["slow_trend_relax_candidate_band"] == "trend_edge_deep"
    assert by_symbol["D"]["slow_trend_relax_candidate_band"] == "trend_deep_tail"
    assert by_symbol["E"]["slow_trend_relax_candidate_band"] == "missing"


def test_build_core_risk_off_floor_v5_projection_fields_distinguish_buy_and_watch_paths() -> None:
    rows = [
        {
            "symbol": "AAA",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "primary_candidate": "buy_candidate",
            "candidate_intent": "buy",
            "final_decision_type": "approve",
            "price_vs_sma_60_pct": -4.2,
            "return_3m_pct": -8.0,
            "order_request_id": "11111111-1111-1111-1111-111111111111",
            "order_status": "filled",
            "execution_status": "submitted",
            "execution_stop_reason": "order_submitted",
            "submission_accepted": True,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.30,
                "shadow_slow_score_v5": -0.28,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.40,
                    "slow_trend": -0.30,
                },
                "shadow_entry_score": 0.22,
                "shadow_rank_candidate_score": 0.41,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_topk_candidate": True,
                "shadow_topk_selected": True,
            },
            "t1_return_pct": 0.8,
            "t3_return_pct": 1.4,
            "t5_return_pct": None,
            "t3_mfe_pct": 1.8,
            "t3_mae_pct": -0.4,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
        {
            "symbol": "BBB",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "primary_candidate": "watch",
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "price_vs_sma_60_pct": -1.2,
            "return_3m_pct": -3.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.28,
                "shadow_slow_score_v5": -0.26,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.20,
                    "slow_trend": -0.10,
                },
                "shadow_entry_score": 0.19,
                "shadow_rank_candidate_score": 0.33,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_topk_candidate": True,
                "shadow_topk_selected": True,
            },
            "t1_return_pct": 0.1,
            "t3_return_pct": 0.2,
            "t5_return_pct": None,
            "t3_mfe_pct": 0.7,
            "t3_mae_pct": -0.5,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
        {
            "symbol": "CCC",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "primary_candidate": "buy_candidate",
            "candidate_intent": "buy",
            "final_decision_type": "hold",
            "price_vs_sma_60_pct": -3.5,
            "return_3m_pct": -6.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "submit_budget_consumed_core",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.27,
                "shadow_slow_score_v5": -0.25,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.22,
                    "slow_trend": -0.20,
                },
                "shadow_entry_score": 0.21,
                "shadow_rank_candidate_score": 0.36,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_topk_candidate": True,
                "shadow_topk_selected": False,
            },
            "t1_return_pct": -0.2,
            "t3_return_pct": 0.1,
            "t5_return_pct": None,
            "t3_mfe_pct": 0.4,
            "t3_mae_pct": -0.8,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
        {
            "symbol": "DDD",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "primary_candidate": "buy_candidate",
            "candidate_intent": "buy",
            "final_decision_type": "approve",
            "price_vs_sma_60_pct": -3.2,
            "return_3m_pct": -5.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "submit_budget_consumed_core",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.29,
                "shadow_slow_score_v5": -0.27,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.30,
                    "slow_trend": -0.18,
                },
                "shadow_entry_score": 0.18,
                "shadow_rank_candidate_score": 0.34,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_topk_candidate": True,
                "shadow_topk_selected": True,
            },
            "t1_return_pct": -0.4,
            "t3_return_pct": -0.1,
            "t5_return_pct": None,
            "t3_mfe_pct": 0.2,
            "t3_mae_pct": -1.0,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
        {
            "symbol": "EEE",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "primary_candidate": "buy_candidate",
            "candidate_intent": "buy",
            "final_decision_type": "approve",
            "price_vs_sma_60_pct": -4.4,
            "return_3m_pct": -9.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.31,
                "shadow_slow_score_v5": -0.29,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.70,
                    "slow_trend": -0.22,
                },
                "shadow_entry_score": 0.24,
                "shadow_rank_candidate_score": 0.38,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_topk_candidate": True,
                "shadow_topk_selected": True,
            },
            "t1_return_pct": -0.9,
            "t3_return_pct": -1.2,
            "t5_return_pct": None,
            "t3_mfe_pct": 0.1,
            "t3_mae_pct": -1.5,
            "t5_mfe_pct": None,
            "t5_mae_pct": None,
        },
    ]

    diagnostic_rows = build_core_risk_off_floor_v5_diagnostic_rows(rows)
    by_symbol = {row["symbol"]: row for row in diagnostic_rows}
    report = build_core_risk_off_floor_v5_diagnostics_report(rows, sample_limit=10)
    projection_summary = report["shadow_relax_projection_summary"]
    projection_reason_items = {
        item["bucket"]: item
        for item in report["shadow_relax_projection_block_reason_items"]
    }
    active_slow_trend_projection_items = {
        item["bucket"]: item
        for item in report["active_slow_trend_projection_items"]
    }
    active_slow_trend_trade_date_projection_items = {
        item["bucket"]: item
        for item in report["active_slow_trend_trade_date_projection_items"]
    }
    active_trend_moderate_gate_reason_items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_gate_reason_items"]
    }
    active_trend_moderate_projection_block_reason_items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_projection_block_reason_items"]
    }
    active_trend_moderate_deterministic_buy_shape_block_reason_items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_deterministic_buy_shape_block_reason_items"]
    }
    active_trend_moderate_signal_floor_miss_detail_items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_signal_floor_miss_detail_items"]
    }
    active_trend_moderate_slow_floor_shadow_relax_path_items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_slow_floor_shadow_relax_path_items"]
    }
    active_trend_moderate_eligibility_block_reason_items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_eligibility_block_reason_items"]
    }
    topk_gate_reason_items = {
        item["bucket"]: item
        for item in report["shadow_topk_candidate_gate_reason_items"]
    }
    watch_reason_items = {
        item["bucket"]: item
        for item in report["watch_primary_candidate_reason_items"]
    }

    assert by_symbol["AAA"]["shadow_relax_projection_candidate"] is True
    assert by_symbol["AAA"]["shadow_relax_projection_selected"] is True
    assert by_symbol["AAA"]["shadow_relax_projection_would_buy"] is True
    assert by_symbol["AAA"]["shadow_relax_projection_submitted"] is True
    assert by_symbol["AAA"]["shadow_relax_projection_block_reason"] == "actual_submitted"
    assert by_symbol["AAA"]["shadow_topk_candidate_gate_reason"] == "shadow_topk_candidate_pass"
    assert by_symbol["AAA"]["watch_primary_candidate_reason"] == "non_watch_primary"

    assert by_symbol["BBB"]["shadow_relax_projection_candidate"] is True
    assert by_symbol["BBB"]["shadow_relax_projection_selected"] is True
    assert by_symbol["BBB"]["shadow_relax_projection_would_buy"] is False
    assert (
        by_symbol["BBB"]["shadow_relax_projection_block_reason"]
        == "watch_only_or_non_buy_shape"
    )
    assert by_symbol["BBB"]["watch_primary_candidate_reason"] == "watch_below_buy_threshold"

    assert by_symbol["CCC"]["shadow_relax_projection_candidate"] is True
    assert by_symbol["CCC"]["shadow_relax_projection_selected"] is False
    assert by_symbol["CCC"]["shadow_relax_projection_block_reason"] == "shadow_topk_not_selected"
    assert by_symbol["CCC"]["shadow_topk_candidate_gate_reason"] == "shadow_topk_candidate_pass"

    assert by_symbol["DDD"]["shadow_relax_projection_candidate"] is True
    assert by_symbol["DDD"]["shadow_relax_projection_selected"] is True
    assert by_symbol["DDD"]["shadow_relax_projection_would_buy"] is True
    assert (
        by_symbol["DDD"]["shadow_relax_projection_block_reason"]
        == "downstream_blocked:submit_budget_consumed_core"
    )
    assert by_symbol["DDD"]["shadow_topk_candidate_gate_reason"] == "shadow_topk_candidate_pass"

    assert by_symbol["EEE"]["shadow_relax_projection_candidate"] is False
    assert (
        by_symbol["EEE"]["shadow_relax_projection_block_reason"]
        == "momentum_deep_negative_guard"
    )
    assert by_symbol["EEE"]["shadow_topk_candidate_gate_reason"] == "shadow_topk_candidate_pass"

    assert projection_summary["candidate_count"] == 4
    assert projection_summary["selected_count"] == 3
    assert projection_summary["would_buy_count"] == 2
    assert projection_summary["submitted_count"] == 1
    assert active_slow_trend_projection_items["trend_mild_candidate"]["candidate_count"] == 1
    assert active_slow_trend_projection_items["trend_mild_candidate"]["selected_count"] == 1
    assert active_slow_trend_projection_items["trend_mild_candidate"]["would_buy_count"] == 0
    assert active_slow_trend_projection_items["trend_moderate_candidate"]["candidate_count"] == 3
    assert active_slow_trend_projection_items["trend_moderate_candidate"]["selected_count"] == 2
    assert active_slow_trend_projection_items["trend_moderate_candidate"]["would_buy_count"] == 2
    assert active_slow_trend_projection_items["trend_moderate_candidate"]["submitted_count"] == 1
    assert active_slow_trend_trade_date_projection_items["2026-07-08|trend_mild_candidate"]["candidate_count"] == 1
    assert active_slow_trend_trade_date_projection_items["2026-07-08|trend_moderate_candidate"]["candidate_count"] == 3
    assert active_slow_trend_trade_date_projection_items["2026-07-08|trend_moderate_candidate"]["submitted_count"] == 1
    assert active_trend_moderate_gate_reason_items["shadow_topk_candidate_pass"]["sample_count"] == 4
    assert (
        active_trend_moderate_projection_block_reason_items["shadow_topk_not_selected"]["sample_count"]
        == 1
    )
    assert active_trend_moderate_signal_floor_miss_detail_items["signal_gate_not_primary"]["sample_count"] == 4
    assert active_trend_moderate_slow_floor_shadow_relax_path_items["non_target_miss_detail:signal_gate_not_primary"]["sample_count"] == 4
    assert (
        active_trend_moderate_eligibility_block_reason_items["eligibility_negative_overall_floor"]["sample_count"]
        == 4
    )
    assert projection_reason_items["actual_submitted"]["sample_count"] == 1
    assert projection_reason_items["watch_only_or_non_buy_shape"]["sample_count"] == 1
    assert projection_reason_items["shadow_topk_not_selected"]["sample_count"] == 1
    assert projection_reason_items["momentum_deep_negative_guard"]["sample_count"] == 1
    assert topk_gate_reason_items["shadow_topk_candidate_pass"]["sample_count"] == 5
    assert watch_reason_items["watch_below_buy_threshold"]["sample_count"] == 1


def test_build_core_risk_off_floor_v5_report_tracks_topk_gate_and_momentum_daily_buckets() -> None:
    rows = [
        {
            "symbol": "AAA",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.52,
            "entry_score": 0.52,
            "eligibility_passed": False,
            "trigger_reason_codes": [
                "trigger_watch_from_entry_setup",
                "momentum_3m_soft_negative_shadow_v5",
            ],
            "price_vs_sma_60_pct": -4.0,
            "return_3m_pct": -7.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.27,
                "shadow_slow_score_v5": -0.22,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.35,
                    "slow_trend": -0.25,
                },
                "shadow_reason_codes_v5": [
                    "momentum_3m_soft_negative_shadow_v5",
                ],
                "shadow_entry_score": 0.18,
                "shadow_rank_candidate_score": 0.20,
                "shadow_min_score": 0.22,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": True,
                "shadow_slow_pass": True,
                "shadow_signal_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "t1_return_pct": 0.4,
            "t3_return_pct": 0.7,
            "t5_return_pct": None,
        },
        {
            "symbol": "BBB",
            "trade_date": "2026-07-09",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.45,
            "entry_score": 0.33,
            "eligibility_passed": False,
            "trigger_reason_codes": [
                "trigger_core_watch_path",
                "momentum_3m_negative",
            ],
            "price_vs_sma_60_pct": -7.0,
            "return_3m_pct": -15.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.18,
                "shadow_slow_score_v5": -0.12,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.55,
                    "slow_trend": -0.25,
                },
                "shadow_reason_codes_v5": [
                    "momentum_3m_negative",
                ],
                "shadow_entry_score": 0.12,
                "shadow_rank_candidate_score": 0.30,
                "shadow_min_score": 0.22,
                "shadow_activity_pass": False,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": True,
                "shadow_slow_pass": True,
                "shadow_signal_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "t1_return_pct": -0.2,
            "t3_return_pct": -0.3,
            "t5_return_pct": None,
        },
    ]

    report = build_core_risk_off_floor_v5_diagnostics_report(rows, sample_limit=10)
    momentum_reason_items = {
        item["bucket"]: item for item in report["momentum_reason_code_items"]
    }
    topk_gate_items = {
        item["bucket"]: item for item in report["shadow_topk_candidate_gate_reason_items"]
    }
    watch_reason_items = {
        item["bucket"]: item for item in report["watch_primary_candidate_reason_items"]
    }
    eligibility_block_items = {
        item["bucket"]: item for item in report["eligibility_block_reason_primary_items"]
    }
    signal_floor_path_items = {
        item["bucket"]: item for item in report["shadow_signal_floor_block_path_items"]
    }
    signal_floor_miss_detail_items = {
        item["bucket"]: item for item in report["shadow_signal_floor_miss_detail_items"]
    }
    slow_floor_shadow_relax_path_items = {
        item["bucket"]: item for item in report["slow_floor_shadow_relax_path_items"]
    }
    watch_eligibility_path_items = {
        item["bucket"]: item for item in report["watch_eligibility_block_path_items"]
    }
    slow_momentum_date_items = {
        item["bucket"]: item for item in report["slow_momentum_band_trade_date_items"]
    }
    active_trend_moderate_gate_reason_items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_gate_reason_items"]
    }
    active_trend_moderate_projection_block_reason_items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_projection_block_reason_items"]
    }
    active_trend_moderate_deterministic_buy_shape_block_reason_items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_deterministic_buy_shape_block_reason_items"]
    }
    active_trend_moderate_signal_floor_miss_detail_items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_signal_floor_miss_detail_items"]
    }
    active_trend_moderate_slow_floor_shadow_relax_path_items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_slow_floor_shadow_relax_path_items"]
    }
    active_trend_moderate_eligibility_block_reason_items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_eligibility_block_reason_items"]
    }

    assert momentum_reason_items["momentum_3m_soft_negative_shadow_v5"]["sample_count"] == 1
    assert momentum_reason_items["momentum_3m_negative"]["sample_count"] == 1
    assert topk_gate_items["ranking_floor_miss"]["sample_count"] == 1
    assert topk_gate_items["activity_floor_miss"]["sample_count"] == 1
    assert eligibility_block_items["eligibility_negative_overall_floor"]["sample_count"] == 1
    assert eligibility_block_items["eligibility_low_relative_activity"]["sample_count"] == 1
    assert watch_reason_items["watch_setup_but_ineligible"]["sample_count"] == 1
    assert watch_reason_items["core_watch_path_only"]["sample_count"] == 1
    assert signal_floor_path_items["signal_gate_not_primary"]["sample_count"] == 2
    assert watch_eligibility_path_items["watch_setup_but_ineligible|eligibility_negative_overall_floor"]["sample_count"] == 1
    assert watch_eligibility_path_items["core_watch_path_only|eligibility_low_relative_activity"]["sample_count"] == 1
    assert slow_momentum_date_items["2026-07-08|moderate_negative"]["sample_count"] == 1
    assert slow_momentum_date_items["2026-07-09|moderate_negative"]["sample_count"] == 1
    assert signal_floor_miss_detail_items["signal_gate_not_primary"]["sample_count"] == 2
    assert slow_floor_shadow_relax_path_items["non_target_band"]["sample_count"] == 1
    assert slow_floor_shadow_relax_path_items["non_target_miss_detail:signal_gate_not_primary"]["sample_count"] == 1
    assert active_trend_moderate_gate_reason_items["ranking_floor_miss"]["sample_count"] == 1
    assert active_trend_moderate_projection_block_reason_items["shadow_topk_candidate_miss"]["sample_count"] == 1
    assert (
        active_trend_moderate_deterministic_buy_shape_block_reason_items["watch_from_entry_setup"]["sample_count"]
        == 1
    )
    assert active_trend_moderate_signal_floor_miss_detail_items["signal_gate_not_primary"]["sample_count"] == 1
    assert active_trend_moderate_slow_floor_shadow_relax_path_items["non_target_miss_detail:signal_gate_not_primary"]["sample_count"] == 1
    assert (
        active_trend_moderate_eligibility_block_reason_items["eligibility_negative_overall_floor"]["sample_count"]
        == 1
    )


def test_build_core_risk_off_floor_v5_report_tracks_slow_floor_shadow_relax_paths() -> None:
    rows = [
        {
            "symbol": "AAA",
            "trade_date": "2026-07-10",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.47,
            "entry_score": 0.18,
            "eligibility_passed": False,
            "trigger_reason_codes": ["trigger_core_watch_path"],
            "price_vs_sma_60_pct": -4.0,
            "return_3m_pct": -10.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.20,
                "shadow_slow_score_v5": -0.40,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.30,
                    "slow_trend": -0.25,
                },
                "shadow_entry_score": 0.18,
                "shadow_rank_candidate_score": 0.31,
                "shadow_min_score": 0.22,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": False,
                "shadow_slow_pass": False,
                "shadow_signal_pass": False,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "eligibility_reasons": ["eligibility_core_risk_off_ranking_blocked"],
            "t1_return_pct": 0.5,
            "t3_return_pct": 1.1,
        },
        {
            "symbol": "BBB",
            "trade_date": "2026-07-10",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.47,
            "entry_score": 0.18,
            "eligibility_passed": False,
            "trigger_reason_codes": ["trigger_core_watch_path"],
            "price_vs_sma_60_pct": -4.5,
            "return_3m_pct": -11.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.18,
                "shadow_slow_score_v5": -0.40,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.35,
                    "slow_trend": -0.25,
                },
                "shadow_entry_score": 0.18,
                "shadow_rank_candidate_score": 0.31,
                "shadow_min_score": 0.22,
                "shadow_activity_pass": False,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": False,
                "shadow_slow_pass": False,
                "shadow_signal_pass": False,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "eligibility_reasons": ["eligibility_core_risk_off_ranking_blocked"],
            "t1_return_pct": 0.3,
            "t3_return_pct": 0.8,
        },
        {
            "symbol": "CCC",
            "trade_date": "2026-07-10",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.47,
            "entry_score": 0.18,
            "eligibility_passed": False,
            "trigger_reason_codes": ["trigger_core_watch_path"],
            "price_vs_sma_60_pct": -3.8,
            "return_3m_pct": -9.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.35,
                "shadow_slow_score_v5": -0.20,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.20,
                    "slow_trend": -0.15,
                },
                "shadow_entry_score": 0.18,
                "shadow_rank_candidate_score": 0.31,
                "shadow_min_score": 0.22,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": False,
                "shadow_slow_pass": False,
                "shadow_signal_pass": False,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "eligibility_reasons": ["eligibility_core_risk_off_ranking_blocked"],
            "t1_return_pct": 0.1,
            "t3_return_pct": 0.2,
        },
    ]

    report = build_core_risk_off_floor_v5_diagnostics_report(rows, sample_limit=10)
    items = {
        item["bucket"]: item
        for item in report["active_trend_moderate_slow_floor_shadow_relax_path_items"]
    }
    trade_date_band_items = {
        item["bucket"]: item
        for item in report["active_slow_floor_relax_ready_trade_date_band_items"]
    }
    trade_date_projection_items = {
        item["bucket"]: item
        for item in report["active_slow_floor_relax_ready_trade_date_projection_items"]
    }
    projection_block_reason_items = {
        item["bucket"]: item
        for item in report["active_slow_floor_relax_ready_projection_block_reason_items"]
    }
    gate_reason_items = {
        item["bucket"]: item
        for item in report["active_slow_floor_relax_ready_gate_reason_items"]
    }
    watch_reason_items = {
        item["bucket"]: item
        for item in report["active_slow_floor_relax_ready_watch_reason_items"]
    }
    deterministic_buy_shape_block_reason_items = {
        item["bucket"]: item
        for item in report["active_slow_floor_relax_ready_deterministic_buy_shape_block_reason_items"]
    }
    transition_stage_items = {
        item["bucket"]: item
        for item in report["active_slow_floor_relax_ready_transition_stage_items"]
    }
    trade_date_transition_stage_items = {
        item["bucket"]: item
        for item in report["active_slow_floor_relax_ready_trade_date_transition_stage_items"]
    }
    ready_samples = report["active_slow_floor_relax_ready_samples"]

    assert items["slow_floor_relax_ready"]["sample_count"] == 1
    assert items["slow_floor_relax_activity_blocked"]["sample_count"] == 1
    assert items["overall_floor_first"]["sample_count"] == 1
    assert trade_date_band_items["2026-07-10"]["sample_count"] == 1
    assert trade_date_projection_items["2026-07-10|slow_floor_relax_ready"]["sample_count"] == 1
    assert trade_date_projection_items["2026-07-10|slow_floor_relax_ready"]["candidate_count"] == 1
    assert trade_date_projection_items["2026-07-10|slow_floor_relax_ready"]["selected_count"] == 0
    assert projection_block_reason_items["shadow_topk_candidate_miss"]["sample_count"] == 1
    assert gate_reason_items["signal_both_floor_miss"]["sample_count"] == 1
    assert watch_reason_items["core_watch_path_only"]["sample_count"] == 1
    assert deterministic_buy_shape_block_reason_items["core_watch_gap_bridge"]["sample_count"] == 1
    assert transition_stage_items["watch_only_core_path"]["sample_count"] == 1
    assert trade_date_transition_stage_items["2026-07-10|watch_only_core_path"]["sample_count"] == 1
    assert len(ready_samples) == 1
    assert ready_samples[0]["symbol"] == "AAA"
    assert ready_samples[0]["trade_date"] == "2026-07-10"
    assert ready_samples[0]["slow_floor_shadow_relax_path"] == "slow_floor_relax_ready"
    assert ready_samples[0]["shadow_relax_projection_block_reason"] == "shadow_topk_candidate_miss"
    assert ready_samples[0]["watch_primary_candidate_reason"] == "core_watch_path_only"
    assert ready_samples[0]["deterministic_buy_shape_block_reason"] == "core_watch_gap_bridge"
    assert ready_samples[0]["buy_candidate_threshold_gap"] == pytest.approx(0.47)
    assert ready_samples[0]["watch_candidate_threshold_gap"] == pytest.approx(0.0)
    assert ready_samples[0]["core_risk_off_ranking_min_gap"] == pytest.approx(0.17)
    assert ready_samples[0]["shadow_topk_ranking_min_gap"] == pytest.approx(0.0)


def test_build_core_risk_off_floor_v5_report_tracks_active_watch_shape_cohorts() -> None:
    rows = [
        {
            "symbol": "AAA",
            "trade_date": "2026-07-10",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.55,
            "entry_score": 0.21,
            "eligibility_passed": False,
            "trigger_reason_codes": ["trigger_watch_from_exit_setup", "trigger_core_watch_path"],
            "price_vs_sma_60_pct": -4.5,
            "return_3m_pct": -9.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.16,
                "shadow_slow_score_v5": -0.21,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.28,
                    "slow_trend": -0.21,
                },
                "shadow_entry_score": 0.21,
                "shadow_rank_candidate_score": 0.41,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": True,
                "shadow_slow_pass": True,
                "shadow_signal_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "eligibility_reasons": ["eligibility_core_risk_off_ranking_blocked"],
            "t1_return_pct": 1.0,
            "t3_return_pct": 2.0,
        },
        {
            "symbol": "BBB",
            "trade_date": "2026-07-10",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.53,
            "entry_score": 0.19,
            "eligibility_passed": False,
            "trigger_reason_codes": ["trigger_watch_from_entry_setup"],
            "price_vs_sma_60_pct": -4.2,
            "return_3m_pct": -8.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.17,
                "shadow_slow_score_v5": -0.22,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.30,
                    "slow_trend": -0.22,
                },
                "shadow_entry_score": 0.19,
                "shadow_rank_candidate_score": 0.39,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": True,
                "shadow_slow_pass": True,
                "shadow_signal_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "eligibility_reasons": ["eligibility_core_risk_off_ranking_blocked"],
            "t1_return_pct": 0.5,
            "t3_return_pct": 1.5,
        },
        {
            "symbol": "CCC",
            "trade_date": "2026-07-10",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.50,
            "entry_score": 0.14,
            "eligibility_passed": False,
            "trigger_reason_codes": ["trigger_core_watch_path"],
            "price_vs_sma_60_pct": -4.8,
            "return_3m_pct": -11.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.18,
                "shadow_slow_score_v5": -0.23,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.32,
                    "slow_trend": -0.23,
                },
                "shadow_entry_score": 0.14,
                "shadow_rank_candidate_score": 0.30,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": True,
                "shadow_slow_pass": True,
                "shadow_signal_pass": True,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "eligibility_reasons": ["eligibility_core_risk_off_ranking_blocked"],
            "t1_return_pct": 0.2,
            "t3_return_pct": 0.8,
        },
    ]

    report = build_core_risk_off_floor_v5_diagnostics_report(rows, sample_limit=10)
    active_watch_reason_items = {
        item["bucket"]: item for item in report["active_watch_primary_candidate_reason_items"]
    }
    active_buy_shape_items = {
        item["bucket"]: item
        for item in report["active_deterministic_buy_shape_block_reason_items"]
    }
    active_watch_reason_buy_shape_matrix_items = {
        item["bucket"]: item
        for item in report["active_watch_reason_buy_shape_matrix_items"]
    }
    active_watch_reason_projection_items = {
        item["bucket"]: item for item in report["active_watch_reason_projection_items"]
    }
    active_buy_shape_projection_items = {
        item["bucket"]: item for item in report["active_buy_shape_projection_items"]
    }
    active_core_watch_exit_projection_block_reason_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_projection_block_reason_items"]
    }
    active_core_watch_exit_gate_reason_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_gate_reason_items"]
    }
    active_core_watch_exit_eligibility_block_reason_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_eligibility_block_reason_items"]
    }
    active_core_watch_exit_trade_date_projection_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trade_date_projection_items"]
    }
    active_core_watch_exit_samples = report["active_core_watch_exit_samples"]
    active_core_watch_exit_trend_moderate_projection_block_reason_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_projection_block_reason_items"]
    }
    active_core_watch_exit_trend_moderate_gate_reason_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_gate_reason_items"]
    }
    active_core_watch_exit_trend_moderate_eligibility_block_reason_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_eligibility_block_reason_items"]
    }
    active_core_watch_exit_trend_moderate_slow_floor_shadow_relax_path_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_slow_floor_shadow_relax_path_items"]
    }
    active_core_watch_exit_trend_moderate_limited_slow_floor_path_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_limited_slow_floor_path_items"]
    }
    active_core_watch_exit_trend_moderate_limited_slow_floor_transition_stage_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_limited_slow_floor_transition_stage_items"]
    }
    active_core_watch_exit_trend_moderate_signal_floor_miss_detail_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_signal_floor_miss_detail_items"]
    }
    active_core_watch_exit_trend_moderate_trade_date_projection_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_trade_date_projection_items"]
    }
    active_core_watch_exit_trend_moderate_samples = report["active_core_watch_exit_trend_moderate_samples"]

    assert active_watch_reason_items["core_watch_path_only"]["sample_count"] == 2
    assert active_watch_reason_items["watch_setup_but_ineligible"]["sample_count"] == 1
    assert active_buy_shape_items["watch_from_exit_setup"]["sample_count"] == 1
    assert active_buy_shape_items["watch_from_entry_setup"]["sample_count"] == 1
    assert active_buy_shape_items["core_watch_gap_bridge"]["sample_count"] == 1
    assert (
        active_watch_reason_buy_shape_matrix_items["core_watch_path_only|watch_from_exit_setup"]["sample_count"]
        == 1
    )
    assert (
        active_watch_reason_buy_shape_matrix_items["watch_setup_but_ineligible|watch_from_entry_setup"]["sample_count"]
        == 1
    )
    assert (
        active_watch_reason_buy_shape_matrix_items["core_watch_path_only|core_watch_gap_bridge"]["sample_count"]
        == 1
    )
    assert active_watch_reason_projection_items["core_watch_path_only"]["candidate_count"] == 2
    assert active_watch_reason_projection_items["watch_setup_but_ineligible"]["candidate_count"] == 1
    assert active_buy_shape_projection_items["watch_from_exit_setup"]["candidate_count"] == 1
    assert active_buy_shape_projection_items["watch_from_entry_setup"]["candidate_count"] == 1
    assert active_buy_shape_projection_items["core_watch_gap_bridge"]["candidate_count"] == 1
    assert active_core_watch_exit_projection_block_reason_items["shadow_topk_candidate_miss"]["sample_count"] == 1
    assert active_core_watch_exit_gate_reason_items["shadow_topk_candidate_unknown_miss"]["sample_count"] == 1
    assert (
        active_core_watch_exit_eligibility_block_reason_items["eligibility_core_risk_off_ranking_blocked"]["sample_count"]
        == 1
    )
    assert (
        active_core_watch_exit_trade_date_projection_items["2026-07-10|core_watch_path_only|watch_from_exit_setup"]["candidate_count"]
        == 1
    )
    assert len(active_core_watch_exit_samples) == 1
    assert active_core_watch_exit_samples[0]["symbol"] == "AAA"
    assert (
        active_core_watch_exit_trend_moderate_projection_block_reason_items["shadow_topk_candidate_miss"]["sample_count"]
        == 1
    )
    assert (
        active_core_watch_exit_trend_moderate_gate_reason_items["shadow_topk_candidate_unknown_miss"]["sample_count"]
        == 1
    )
    assert (
        active_core_watch_exit_trend_moderate_eligibility_block_reason_items["eligibility_core_risk_off_ranking_blocked"]["sample_count"]
        == 1
    )
    assert (
        active_core_watch_exit_trend_moderate_slow_floor_shadow_relax_path_items["non_target_miss_detail:signal_gate_not_primary"]["sample_count"]
        == 1
    )
    assert (
        active_core_watch_exit_trend_moderate_limited_slow_floor_path_items["non_target_miss_detail:signal_gate_not_primary"]["sample_count"]
        == 1
    )
    assert (
        active_core_watch_exit_trend_moderate_limited_slow_floor_transition_stage_items[
            "non_target_miss_detail:signal_gate_not_primary"
        ]["sample_count"]
        == 1
    )
    assert (
        active_core_watch_exit_trend_moderate_signal_floor_miss_detail_items["signal_gate_not_primary"]["sample_count"]
        == 1
    )
    assert (
        active_core_watch_exit_trend_moderate_trade_date_projection_items[
            "2026-07-10|core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate"
        ]["candidate_count"]
        == 1
    )
    assert len(active_core_watch_exit_trend_moderate_samples) == 1
    assert active_core_watch_exit_trend_moderate_samples[0]["symbol"] == "AAA"


def test_build_core_risk_off_floor_v5_report_tracks_watch_only_core_path_shadow_reason() -> None:
    rows = [
        {
            "symbol": "AAA",
            "trade_date": "2026-07-03",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.601,
            "entry_score": 0.2479,
            "eligibility_passed": False,
            "trigger_reason_codes": ["trigger_watch_from_exit_setup", "trigger_core_watch_path"],
            "price_vs_sma_60_pct": -5.53,
            "return_3m_pct": -15.31,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.1274,
                "shadow_slow_score_v5": -0.43,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.55,
                    "slow_trend": -0.25,
                },
                "shadow_entry_score": 0.247889065,
                "shadow_rank_candidate_score": 0.4166,
                "shadow_min_score": 0.22,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": False,
                "shadow_slow_pass": False,
                "shadow_signal_pass": False,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "eligibility_reasons": ["eligibility_core_risk_off_ranking_blocked"],
            "t1_return_pct": 1.4583,
            "t3_return_pct": 3.3333,
        }
    ]

    report = build_core_risk_off_floor_v5_diagnostics_report(rows, sample_limit=10)
    reason_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_watch_only_core_path_shadow_reason_items"]
    }
    buy_gap_band_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_buy_gap_band_items"]
    }
    transition_stage_buy_gap_band_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_transition_stage_buy_gap_band_items"]
    }
    trade_date_buy_gap_band_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_trade_date_buy_gap_band_items"]
    }
    buy_gap_projection_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_buy_gap_projection_items"]
    }
    entry_gap_band_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_band_items"]
    }
    trade_date_entry_gap_band_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_watch_only_core_path_trade_date_entry_gap_band_items"]
    }
    entry_gap_projection_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items"]
    }
    trade_date_entry_gap_projection_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_watch_only_core_path_trade_date_entry_gap_projection_items"]
    }
    samples = report["active_core_watch_exit_trend_moderate_samples"]

    assert reason_items["exit_setup_large_entry_gap"]["sample_count"] == 1
    assert buy_gap_band_items["large_entry_gap"]["sample_count"] == 1
    assert transition_stage_buy_gap_band_items["candidate_ready_watch_only_core_path|large_entry_gap"]["sample_count"] == 1
    assert trade_date_buy_gap_band_items["2026-07-03|large_entry_gap"]["sample_count"] == 1
    assert buy_gap_projection_items["large_entry_gap"]["candidate_count"] == 1
    assert buy_gap_projection_items["large_entry_gap"]["selected_count"] == 0
    assert buy_gap_projection_items["moderate_entry_gap"]["sample_count"] == 0
    assert entry_gap_band_items["large_entry_gap"]["sample_count"] == 1
    assert trade_date_entry_gap_band_items["2026-07-03|large_entry_gap"]["sample_count"] == 1
    assert entry_gap_projection_items["large_entry_gap"]["candidate_count"] == 1
    assert entry_gap_projection_items["large_entry_gap"]["selected_count"] == 0
    assert entry_gap_projection_items["large_entry_gap"]["would_buy_count"] == 0
    assert entry_gap_projection_items["large_entry_gap"]["submitted_count"] == 0
    assert (
        trade_date_entry_gap_projection_items[
            "2026-07-03|core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate|candidate_ready_watch_only_core_path|large_entry_gap"
        ]["candidate_count"]
        == 1
    )
    assert len(samples) == 1
    assert samples[0]["limited_slow_floor_shadow_path"] == "candidate_ready"
    assert samples[0]["limited_slow_floor_transition_stage"] == "candidate_ready_watch_only_core_path"
    assert samples[0]["watch_only_core_path_shadow_reason"] == "exit_setup_large_entry_gap"
    assert samples[0]["buy_candidate_threshold_gap_band"] == "large_entry_gap"
    assert samples[0]["watch_only_core_path_entry_gap_band"] == "large_entry_gap"
    assert samples[0]["buy_candidate_threshold_gap"] == pytest.approx(0.402110935)
    assert samples[0]["core_risk_off_ranking_min_gap"] == pytest.approx(0.0634)


def test_build_core_risk_off_floor_v5_report_compares_target_cohort_to_authoritative_buy_path() -> None:
    rows = [
        {
            "symbol": "TGT",
            "trade_date": "2026-07-03",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.60,
            "entry_score": 0.2479,
            "ranking_score": 0.4166,
            "eligibility_passed": False,
            "trigger_reason_codes": ["trigger_watch_from_exit_setup", "trigger_core_watch_path"],
            "price_vs_sma_60_pct": -3.88,
            "return_3m_pct": -11.37,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_floor_relax_v5_bucket": "deep_negative",
                "shadow_overall_score_v5": -0.1274,
                "shadow_slow_score_v5": -0.43,
                "shadow_component_scores_v5": {
                    "slow_momentum": -0.55,
                    "slow_trend": -0.25,
                },
                "shadow_entry_score": 0.247889065,
                "shadow_rank_candidate_score": 0.4166,
                "shadow_activity_pass": True,
                "shadow_strategy_pass": True,
                "shadow_overall_pass": False,
                "shadow_slow_pass": False,
                "shadow_signal_pass": False,
                "shadow_topk_candidate": False,
                "shadow_topk_selected": False,
            },
            "eligibility_reasons": ["eligibility_core_risk_off_ranking_blocked"],
            "t1_return_pct": 1.45,
            "t3_return_pct": 3.33,
        },
        {
            "symbol": "BUY",
            "trade_date": "2026-07-04",
            "source_type": "core",
            "primary_candidate": "buy_candidate",
            "buy_candidate": True,
            "candidate_intent": "buy",
            "final_decision_type": "approve",
            "watch_score": 0.70,
            "entry_score": 0.68,
            "ranking_score": 0.61,
            "eligibility_passed": True,
            "trigger_reason_codes": ["trigger_buy_candidate"],
            "price_vs_sma_60_pct": 1.5,
            "return_3m_pct": 8.0,
            "order_request_id": "ord-1",
            "order_status": "validated",
            "execution_status": "submitted",
            "execution_stop_reason": "order_submitted",
            "submission_accepted": True,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": False,
                "shadow_mode": "shadow_topk_exception_v2",
            },
            "eligibility_reasons": ["eligibility_signal_floor_pass"],
            "t1_return_pct": 0.8,
            "t3_return_pct": 2.4,
        },
        {
            "symbol": "ENT",
            "trade_date": "2026-07-05",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.61,
            "entry_score": 0.58,
            "ranking_score": 0.57,
            "eligibility_passed": True,
            "trigger_reason_codes": ["trigger_watch_from_entry_setup"],
            "price_vs_sma_60_pct": -0.2,
            "return_3m_pct": 4.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": False,
            },
            "eligibility_reasons": ["eligibility_signal_floor_pass"],
            "t1_return_pct": 0.4,
            "t3_return_pct": 1.6,
        },
        {
            "symbol": "GE52",
            "trade_date": "2026-07-06",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.55,
            "entry_score": 0.53,
            "ranking_score": 0.54,
            "eligibility_passed": True,
            "trigger_reason_codes": ["trigger_watch_from_exit_setup", "trigger_core_watch_path"],
            "price_vs_sma_60_pct": -0.8,
            "return_3m_pct": 2.0,
            "volume_surge_ratio": 1.02,
            "turnover_surge_ratio": 0.88,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": False,
            },
            "eligibility_reasons": ["eligibility_low_relative_activity"],
            "t1_return_pct": 0.2,
            "t3_return_pct": 0.9,
        },
        {
            "symbol": "MID",
            "trade_date": "2026-07-07",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.57,
            "entry_score": 0.57,
            "ranking_score": 0.56,
            "eligibility_passed": True,
            "trigger_reason_codes": ["trigger_watch_from_exit_setup", "trigger_core_watch_path"],
            "price_vs_sma_60_pct": -0.4,
            "return_3m_pct": 2.6,
            "average_turnover_20d": 30_000_000.0,
            "recommended_max_order_value": 2_400_000.0,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": False,
            },
            "eligibility_reasons": ["eligibility_participation_rate_blocked"],
            "t1_return_pct": 0.3,
            "t3_return_pct": 1.1,
        },
        {
            "symbol": "BND",
            "trade_date": "2026-07-08",
            "source_type": "core",
            "primary_candidate": "watch",
            "buy_candidate": False,
            "candidate_intent": "watch",
            "final_decision_type": "watch",
            "watch_score": 0.58,
            "entry_score": 0.58,
            "ranking_score": 0.57,
            "eligibility_passed": True,
            "trigger_reason_codes": ["trigger_watch_from_exit_setup", "trigger_core_watch_path"],
            "price_vs_sma_60_pct": 0.2,
            "return_3m_pct": 3.1,
            "volume_surge_ratio": 1.01,
            "turnover_surge_ratio": 0.99,
            "order_request_id": None,
            "order_status": "unknown",
            "execution_status": "non_trade",
            "execution_stop_reason": "decision_watch",
            "submission_accepted": False,
            "submission_error_type": "",
            "core_risk_off_experiment": {
                "active": False,
            },
            "eligibility_reasons": ["eligibility_low_relative_activity"],
            "t1_return_pct": 0.35,
            "t3_return_pct": 1.2,
        },
    ]

    report = build_core_risk_off_floor_v5_diagnostics_report(rows, sample_limit=10)
    target_entry_band_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_effective_entry_score_band_items"]
    }
    target_ranking_gap_items = {
        item["bucket"]: item
        for item in report["active_core_watch_exit_trend_moderate_effective_buy_ranking_gap_band_items"]
    }
    authoritative_buy_entry_items = {
        item["bucket"]: item
        for item in report["authoritative_core_buy_path_entry_score_band_items"]
    }
    authoritative_buy_gap_items = {
        item["bucket"]: item
        for item in report["authoritative_core_buy_path_buy_gap_band_items"]
    }
    authoritative_buy_ranking_items = {
        item["bucket"]: item
        for item in report["authoritative_core_buy_path_buy_ranking_gap_band_items"]
    }
    authoritative_submitted_entry_items = {
        item["bucket"]: item
        for item in report["authoritative_core_submitted_path_entry_score_band_items"]
    }
    watch_from_entry_setup_report = report["pre_buy_staging_watch_from_entry_setup_report"]
    watch_from_entry_setup_entry_items = {
        item["bucket"]: item
        for item in watch_from_entry_setup_report["entry_score_band_items"]
    }
    entry_score_ge_0_52_report = report["pre_buy_staging_entry_score_ge_0_52_report"]
    entry_score_ge_0_52_entry_items = {
        item["bucket"]: item
        for item in entry_score_ge_0_52_report["entry_score_band_items"]
    }
    entry_score_ge_0_52_activity_items = {
        item["bucket"]: item
        for item in entry_score_ge_0_52_report["activity_gate_items"]
    }
    entry_score_ge_0_52_activity_detail_items = {
        item["bucket"]: item
        for item in entry_score_ge_0_52_report["activity_detail_items"]
    }
    entry_score_0_55_to_0_65_report = report["pre_buy_staging_entry_score_0_55_to_0_65_report"]
    entry_score_0_55_to_0_65_entry_items = {
        item["bucket"]: item
        for item in entry_score_0_55_to_0_65_report["entry_score_band_items"]
    }
    entry_score_0_55_to_0_65_activity_items = {
        item["bucket"]: item
        for item in entry_score_0_55_to_0_65_report["activity_gate_items"]
    }
    entry_score_0_55_to_0_65_activity_detail_items = {
        item["bucket"]: item
        for item in entry_score_0_55_to_0_65_report["activity_detail_items"]
    }
    low_relative_activity_boundary_report = report[
        "pre_buy_staging_low_relative_activity_boundary_report"
    ]
    small_entry_gap_report = report[
        "pre_buy_boundary_watch_from_entry_setup_small_entry_gap_report"
    ]
    moderate_entry_gap_report = report[
        "pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_report"
    ]
    low_relative_activity_boundary_cohort_items = {
        item["bucket"]: item
        for item in low_relative_activity_boundary_report["cohort_items"]
    }
    low_relative_activity_boundary_projection_items = {
        item["bucket"]: item
        for item in low_relative_activity_boundary_report["cohort_projection_items"]
    }
    low_relative_activity_boundary_bottleneck_items = {
        item["bucket"]: item
        for item in low_relative_activity_boundary_report["first_order_bottleneck_items"]
    }
    low_relative_activity_boundary_bottleneck_projection_items = {
        item["bucket"]: item
        for item in low_relative_activity_boundary_report["first_order_bottleneck_projection_items"]
    }
    low_relative_activity_boundary_counterfactual_items = {
        item["bucket"]: item
        for item in low_relative_activity_boundary_report["activity_counterfactual_next_gate_items"]
    }
    low_relative_activity_boundary_counterfactual_projection_items = {
        item["bucket"]: item
        for item in low_relative_activity_boundary_report["activity_counterfactual_next_gate_projection_items"]
    }
    low_relative_activity_boundary_buy_shape_detail_items = {
        item["bucket"]: item
        for item in low_relative_activity_boundary_report["activity_buy_shape_detail_items"]
    }
    small_entry_gap_cohort_items = {
        item["bucket"]: item
        for item in small_entry_gap_report["cohort_items"]
    }
    small_entry_gap_projection_items = {
        item["bucket"]: item
        for item in small_entry_gap_report["projection_items"]
    }
    moderate_entry_gap_cohort_items = {
        item["bucket"]: item
        for item in moderate_entry_gap_report["cohort_items"]
    }
    moderate_entry_gap_projection_items = {
        item["bucket"]: item
        for item in moderate_entry_gap_report["projection_items"]
    }
    authoritative_buy_samples = report["authoritative_core_buy_path_samples"]
    authoritative_submitted_samples = report["authoritative_core_submitted_path_samples"]

    assert target_entry_band_items["observe_band"]["sample_count"] == 1
    assert target_ranking_gap_items["moderate_ranking_gap"]["sample_count"] == 1
    assert authoritative_buy_entry_items["buy_ready"]["sample_count"] == 1
    assert authoritative_buy_gap_items["entry_ready"]["sample_count"] == 1
    assert authoritative_buy_ranking_items["ranking_ready"]["sample_count"] == 1
    assert authoritative_submitted_entry_items["buy_ready"]["sample_count"] == 1
    assert len(authoritative_buy_samples) == 1
    assert authoritative_buy_samples[0]["symbol"] == "BUY"
    assert authoritative_buy_samples[0]["authoritative_buy_path"] is True
    assert authoritative_buy_samples[0]["effective_entry_score"] == pytest.approx(0.68)
    assert authoritative_buy_samples[0]["effective_buy_candidate_threshold_gap_band"] == "entry_ready"
    assert len(authoritative_submitted_samples) == 1
    assert authoritative_submitted_samples[0]["symbol"] == "BUY"
    assert authoritative_submitted_samples[0]["authoritative_submitted_path"] is True
    assert authoritative_submitted_samples[0]["actual_submitted"] is True
    assert watch_from_entry_setup_entry_items["near_buy_floor"]["sample_count"] == 1
    assert {sample["symbol"] for sample in watch_from_entry_setup_report["samples"]} == {"ENT"}
    assert entry_score_ge_0_52_entry_items["watch_band"]["sample_count"] == 1
    assert {sample["symbol"] for sample in entry_score_ge_0_52_report["samples"]} == {"BUY", "GE52"}
    assert entry_score_ge_0_52_activity_items["eligibility_low_relative_activity"]["sample_count"] == 1
    assert (
        entry_score_ge_0_52_activity_detail_items["low_relative_activity_max_0_95_to_1_10"]["sample_count"]
        == 1
    )
    assert entry_score_0_55_to_0_65_entry_items["near_buy_floor"]["sample_count"] == 2
    assert {sample["symbol"] for sample in entry_score_0_55_to_0_65_report["samples"]} == {"BND", "MID"}
    assert (
        entry_score_0_55_to_0_65_activity_items["eligibility_participation_rate_blocked"]["sample_count"]
        == 1
    )
    assert (
        entry_score_0_55_to_0_65_activity_items["eligibility_low_relative_activity"]["sample_count"]
        == 1
    )
    assert (
        entry_score_0_55_to_0_65_activity_detail_items["participation_rate_5_to_10pct"]["sample_count"]
        == 1
    )
    assert (
        entry_score_0_55_to_0_65_activity_detail_items["low_relative_activity_max_0_95_to_1_10"]["sample_count"]
        == 1
    )
    assert (
        low_relative_activity_boundary_cohort_items["entry_score_0_55_to_0_65"]["sample_count"]
        == 1
    )
    assert (
        low_relative_activity_boundary_cohort_items["entry_score_ge_0_52"]["sample_count"]
        == 1
    )
    assert (
        low_relative_activity_boundary_projection_items["entry_score_0_55_to_0_65"]["sample_count"]
        == 1
    )
    assert (
        low_relative_activity_boundary_projection_items["entry_score_0_55_to_0_65"]["candidate_count"]
        == 0
    )
    assert (
        low_relative_activity_boundary_projection_items["entry_score_ge_0_52"]["sample_count"]
        == 1
    )
    assert (
        low_relative_activity_boundary_bottleneck_items["activity_first_small_entry_gap"]["sample_count"]
        == 1
    )
    assert (
        low_relative_activity_boundary_bottleneck_items["activity_first_moderate_entry_gap"]["sample_count"]
        == 1
    )
    assert (
        low_relative_activity_boundary_bottleneck_projection_items["activity_first_small_entry_gap"]["candidate_count"]
        == 0
    )
    assert (
        low_relative_activity_boundary_bottleneck_projection_items["activity_first_moderate_entry_gap"]["candidate_count"]
        == 0
    )
    assert (
        low_relative_activity_boundary_counterfactual_items["signal_before_activity_release"]["sample_count"]
        == 2
    )
    assert (
        low_relative_activity_boundary_counterfactual_projection_items["signal_before_activity_release"]["candidate_count"]
        == 0
    )
    assert (
        low_relative_activity_boundary_buy_shape_detail_items["non_buy_shape_after_activity"]["sample_count"]
        == 2
    )
    assert small_entry_gap_cohort_items == {}
    assert moderate_entry_gap_cohort_items == {}
    assert (
        small_entry_gap_projection_items["watch_from_entry_setup|small_entry_gap"]["sample_count"]
        == 0
    )
    assert (
        moderate_entry_gap_projection_items["watch_from_entry_setup|moderate_entry_gap"]["sample_count"]
        == 0
    )
    assert small_entry_gap_report["samples"] == []
    assert moderate_entry_gap_report["samples"] == []
    assert {sample["symbol"] for sample in low_relative_activity_boundary_report["samples"]} == {
        "BND",
        "GE52",
    }
