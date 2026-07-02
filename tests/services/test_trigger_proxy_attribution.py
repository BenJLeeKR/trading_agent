from __future__ import annotations

import pytest

from agent_trading.services.trigger_proxy_attribution import (
    DailyPriceBar,
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
