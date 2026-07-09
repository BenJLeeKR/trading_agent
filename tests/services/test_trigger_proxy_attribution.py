from __future__ import annotations

import pytest

from agent_trading.services.trigger_proxy_attribution import (
    DailyPriceBar,
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
            "source_type": "core",
            "core_risk_off_experiment": {
                "active": True,
                "shadow_overall_score_v5": -0.18,
                "shadow_slow_score_v5": -0.14,
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
                "shadow_overall_score_v5": -0.24,
                "shadow_slow_score_v5": -0.20,
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

    assert by_symbol["AAA"]["core_risk_off_floor_v5_bucket"] == "mild_relax"
    assert by_symbol["AAA"]["blocking_reason"] == "mild_relax_pass"
    assert by_symbol["BBB"]["core_risk_off_floor_v5_bucket"] == "moderate_relax"
    assert by_symbol["BBB"]["blocking_reason"] == "moderate_relax_pass"
    assert gate_items["entry_below_0_12"]["sample_count"] == 1
    assert gate_items["moderate_ready"]["sample_count"] == 1
    assert reason_items["mild_relax_pass"]["sample_count"] == 1
    assert reason_items["moderate_relax_pass"]["sample_count"] == 1
