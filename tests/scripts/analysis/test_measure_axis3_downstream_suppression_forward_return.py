"""단위 테스트 — 축 3 재현 분석 도구의 순수 함수 부분(DB 미사용).

이 테스트는 실제 DB에 연결하지 않는다 — ``classify_and_dedupe``/
``build_close_index``/``compute_forward_return``/``run_analysis``는 전부
순수 함수이며, DB에서 가져온 결과를 흉내 낸 dict/리스트만으로 검증한다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from scripts.analysis.measure_axis3_downstream_suppression_forward_return import (
    KNOWN_NON_PRIMARY_STATUSES,
    PRIMARY_STATUSES,
    build_close_index,
    classify_and_dedupe,
    compute_forward_return,
    run_analysis,
)

KST = timezone(timedelta(hours=9))


def _raw_row(
    instrument_id: str,
    symbol: str,
    kst_date: date,
    alignment_status: str,
    hour: int,
    risk_tone: str | None = "risk_off",
    regime_label: str | None = "bullish_trend",
    source_type: str | None = "core",
    policy_git_sha: str | None = None,
) -> dict:
    return {
        "trade_decision_id": f"{instrument_id}-{kst_date}-{hour}",
        "instrument_id": instrument_id,
        "symbol": symbol,
        "kst_date": kst_date,
        "created_at": datetime(kst_date.year, kst_date.month, kst_date.day, hour, 0, tzinfo=KST),
        "alignment_status": alignment_status,
        "regime_label": regime_label,
        "risk_tone": risk_tone,
        "source_type": source_type,
        "policy_git_sha": policy_git_sha,
    }


def _close_row(instrument_id: str, trade_date: date, close_price: float, price_source: str) -> dict:
    return {
        "instrument_id": instrument_id,
        "trade_date": trade_date,
        "close_price": close_price,
        "price_source": price_source,
    }


class TestClassifyAndDedupe:
    def test_dominant_label_and_contamination_computed_correctly(self):
        d1 = date(2026, 8, 7)
        rows = [
            _raw_row("i1", "007340", d1, "downgraded", 9),
            _raw_row("i1", "007340", d1, "downgraded", 9, 10),
            _raw_row("i1", "007340", d1, "downgraded", 9, 20),
            _raw_row("i1", "007340", d1, "matched", 9, 30),
        ]
        units = classify_and_dedupe(rows)
        assert len(units) == 1
        u = units[0]
        assert u.final_status == "downgraded"
        assert u.dominant_status == "downgraded"
        assert u.dominant_n == 3
        assert u.total_n == 4
        assert u.contamination_rate == 0.25

    def test_exact_50_50_tie_becomes_mixed_tie_not_arbitrary_label(self):
        d1 = date(2026, 8, 10)
        rows = [
            _raw_row("i2", "004370", d1, "downgraded", 9),
            _raw_row("i2", "004370", d1, "matched", 10),
        ]
        units = classify_and_dedupe(rows)
        assert len(units) == 1
        assert units[0].final_status == "mixed_tie"

    def test_representative_stratification_fields_taken_from_earliest_cycle(self):
        d1 = date(2026, 8, 7)
        rows = [
            _raw_row("i1", "007340", d1, "downgraded", 9, risk_tone="risk_off"),
            _raw_row("i1", "007340", d1, "downgraded", 15, risk_tone="risk_on"),
        ]
        units = classify_and_dedupe(rows)
        assert units[0].risk_tone == "risk_off"

    def test_null_policy_git_sha_kept_distinct_from_real_sha(self):
        d1 = date(2026, 8, 7)
        d2 = date(2026, 8, 21)
        rows = [
            _raw_row("i1", "007340", d1, "matched", 9, policy_git_sha=None),
            _raw_row("i2", "005930", d2, "matched", 9, policy_git_sha="a" * 40),
        ]
        units = classify_and_dedupe(rows)
        by_symbol = {u.symbol: u for u in units}
        assert by_symbol["007340"].policy_git_sha is None
        assert by_symbol["005930"].policy_git_sha == "a" * 40


class TestComputeForwardReturn:
    def test_horizon_uses_trading_day_order_not_calendar_days(self):
        # 금요일 종가 다음 "거래일"은 (주말을 건너) 다음 월요일이다 — 달력상
        # 3일 차이지만 거래일 순서로는 T+1이어야 한다.
        fri = date(2026, 8, 7)
        mon = date(2026, 8, 10)
        tue = date(2026, 8, 11)
        close_rows = [
            _close_row("i1", fri, 104.0, "kis_stock_basic_info"),
            _close_row("i1", mon, 105.0, "kis_stock_basic_info"),
            _close_row("i1", tue, 106.0, "kis_stock_basic_info"),
        ]
        idx = build_close_index(close_rows)
        r1 = compute_forward_return(idx, "i1", fri, 1)
        assert r1.exclusion_reason is None
        assert r1.target_trade_date == mon.isoformat()
        assert r1.return_pct == round((105.0 / 104.0 - 1.0) * 100.0, 4)

        r2 = compute_forward_return(idx, "i1", fri, 2)
        assert r2.target_trade_date == tue.isoformat()

    def test_missing_decision_close_is_price_source_missing_not_zero(self):
        idx = build_close_index([_close_row("i1", date(2026, 8, 10), 100.0, "kis_stock_basic_info")])
        r = compute_forward_return(idx, "i1", date(2026, 8, 7), 1)
        assert r.exclusion_reason == "price_source_missing"
        assert r.return_pct is None
        assert r.decision_close is None

    def test_horizon_not_yet_arrived_is_not_zero_return(self):
        idx = build_close_index(
            [
                _close_row("i1", date(2026, 8, 7), 100.0, "kis_stock_basic_info"),
                _close_row("i1", date(2026, 8, 10), 101.0, "kis_stock_basic_info"),
            ]
        )
        r = compute_forward_return(idx, "i1", date(2026, 8, 7), 20)
        assert r.exclusion_reason == "horizon_not_arrived"
        assert r.return_pct is None
        # 결정일 종가 자체는 있으므로 decision_close는 채워져 있어야 한다
        # (가격 소스 공백과 horizon 미도래를 구분하는 지점).
        assert r.decision_close == 100.0

    def test_fallback_price_source_used_only_when_primary_absent(self):
        idx = build_close_index(
            [
                _close_row("i1", date(2026, 8, 7), 100.0, "kis_stock_basic_info"),
                _close_row("i1", date(2026, 8, 10), 999.0, "signal_feature_snapshots_derived"),
            ]
        )
        r = compute_forward_return(idx, "i1", date(2026, 8, 7), 1)
        assert r.target_close_source == "signal_feature_snapshots_derived"


class TestRunAnalysisPopulationSelection:
    def test_only_matched_and_downgraded_are_primary_population(self):
        d1 = date(2026, 8, 7)
        raw_rows = [
            _raw_row("i1", "007340", d1, "matched", 9),
            _raw_row("i2", "005930", d1, "downgraded", 9),
            _raw_row("i3", "003550", d1, "diverged", 9),
        ]
        close_rows = [
            _close_row("i1", d1, 100.0, "kis_stock_basic_info"),
            _close_row("i2", d1, 100.0, "kis_stock_basic_info"),
            _close_row("i3", d1, 100.0, "kis_stock_basic_info"),
        ]
        result = run_analysis(raw_rows, close_rows, horizons=[1])

        assert result["primary_population_unit_count"] == 2
        statuses_in_summary = {s["final_status"] for s in result["horizon_summaries"]}
        assert statuses_in_summary == set(PRIMARY_STATUSES)
        assert result["exclusion_counts"]["diverged"] == 1

    def test_known_non_primary_statuses_reported_even_when_zero(self):
        raw_rows = [_raw_row("i1", "007340", date(2026, 8, 7), "matched", 9)]
        close_rows = [_close_row("i1", date(2026, 8, 7), 100.0, "kis_stock_basic_info")]
        result = run_analysis(raw_rows, close_rows, horizons=[1])
        for status in KNOWN_NON_PRIMARY_STATUSES:
            assert status in result["exclusion_counts"]

    def test_mixed_tie_excluded_from_primary_population_and_counted(self):
        d1 = date(2026, 8, 10)
        raw_rows = [
            _raw_row("i1", "004370", d1, "downgraded", 9),
            _raw_row("i1", "004370", d1, "matched", 10),
        ]
        close_rows = [_close_row("i1", d1, 100.0, "kis_stock_basic_info")]
        result = run_analysis(raw_rows, close_rows, horizons=[1])
        assert result["primary_population_unit_count"] == 0
        assert result["exclusion_counts"]["mixed_tie"] == 1

    def test_output_contains_price_missing_and_horizon_not_arrived_exclusions(self):
        d1 = date(2026, 8, 7)
        raw_rows = [
            _raw_row("i1", "007340", d1, "downgraded", 9),  # 가격 소스 없음
            _raw_row("i2", "005930", d1, "matched", 9),  # horizon 미도래
        ]
        close_rows = [_close_row("i2", d1, 100.0, "kis_stock_basic_info")]
        result = run_analysis(raw_rows, close_rows, horizons=[20])

        downgraded_summary = next(
            s for s in result["horizon_summaries"] if s["final_status"] == "downgraded"
        )
        matched_summary = next(
            s for s in result["horizon_summaries"] if s["final_status"] == "matched"
        )
        assert downgraded_summary["excluded_price_source_missing"] == 1
        assert matched_summary["excluded_horizon_not_arrived"] == 1
        # 둘 다 실제 수익률로 잡히면 안 된다.
        assert downgraded_summary["n_with_return"] == 0
        assert matched_summary["n_with_return"] == 0
