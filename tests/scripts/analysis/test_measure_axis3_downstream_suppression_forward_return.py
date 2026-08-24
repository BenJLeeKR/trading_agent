"""단위 테스트 — 축 3 재현 분석 도구의 순수 함수 부분(DB 미사용).

이 테스트는 실제 DB에 연결하지 않는다 — ``classify_and_dedupe``/
``build_close_index``/``compute_forward_return``/``run_analysis``는 전부
순수 함수이며, DB에서 가져온 결과를 흉내 낸 dict/리스트만으로 검증한다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from scripts.analysis.measure_axis3_downstream_suppression_forward_return import (
    BUY_RAW_SQL,
    CLOSE_SQL,
    KNOWN_NON_PRIMARY_STATUSES,
    PRIMARY_STATUSES,
    build_close_index,
    build_reproducibility_metadata,
    classify_and_dedupe,
    compute_forward_return,
    fetch_close_series,
    fetch_population,
    main,
    parse_as_of_at,
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


def _close_row(
    instrument_id: str,
    trade_date: date,
    close_price: float,
    price_source: str,
    snapshot_at: datetime | None = None,
    created_at: datetime | None = None,
    row_id: str | None = None,
) -> dict:
    return {
        "instrument_id": instrument_id,
        "trade_date": trade_date,
        "close_price": close_price,
        "price_source": price_source,
        "snapshot_at": snapshot_at,
        "created_at": created_at,
        "row_id": row_id,
    }


class _FakeFetchConn:
    """``conn.fetch(sql, *args)``만 기록하는 DB-free fake connection.

    ``fetch_population``/``fetch_close_series``에 같은 as-of 값이 실제로
    전달되는지, SQL 파라미터 순서가 계약과 일치하는지를 실제 DB 없이
    검증하기 위한 최소 구현이다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql: str, *args):
        self.calls.append((sql, args))
        return []


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
        idx, _ = build_close_index(close_rows)
        r1 = compute_forward_return(idx, "i1", fri, 1)
        assert r1.exclusion_reason is None
        assert r1.target_trade_date == mon.isoformat()
        assert r1.return_pct == round((105.0 / 104.0 - 1.0) * 100.0, 4)

        r2 = compute_forward_return(idx, "i1", fri, 2)
        assert r2.target_trade_date == tue.isoformat()

    def test_missing_decision_close_is_price_source_missing_not_zero(self):
        idx, _ = build_close_index(
            [_close_row("i1", date(2026, 8, 10), 100.0, "kis_stock_basic_info")]
        )
        r = compute_forward_return(idx, "i1", date(2026, 8, 7), 1)
        assert r.exclusion_reason == "price_source_missing"
        assert r.return_pct is None
        assert r.decision_close is None

    def test_horizon_not_yet_arrived_is_not_zero_return(self):
        idx, _ = build_close_index(
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
        idx, _ = build_close_index(
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


class TestParseAsOfAt:
    def test_timezone_aware_iso8601_parsed_correctly(self):
        dt = parse_as_of_at("2026-08-24T12:20:00+09:00")
        assert dt.tzinfo is not None
        assert dt.utcoffset() == timedelta(hours=9)
        assert dt.hour == 12 and dt.minute == 20

    def test_naive_timestamp_without_timezone_is_rejected(self):
        with pytest.raises(ValueError, match="timezone"):
            parse_as_of_at("2026-08-24T12:20:00")

    def test_malformed_timestamp_is_rejected(self):
        with pytest.raises(ValueError):
            parse_as_of_at("not-a-timestamp")


class TestEndDateAfterAsOfAtIsRejected:
    @pytest.mark.asyncio
    async def test_end_date_later_than_as_of_at_exits_with_error(self):
        with pytest.raises(SystemExit):
            await main(
                [
                    "--start-date",
                    "2026-08-01",
                    "--end-date",
                    "2026-08-30",
                    "--as-of-at",
                    "2026-08-24T12:20:00+09:00",
                ]
            )

    @pytest.mark.asyncio
    async def test_naive_as_of_at_exits_with_error_before_any_db_call(self):
        with pytest.raises(SystemExit):
            await main(
                [
                    "--start-date",
                    "2026-08-01",
                    "--end-date",
                    "2026-08-20",
                    "--as-of-at",
                    "2026-08-24T12:20:00",  # timezone 없음
                ]
            )

    @pytest.mark.asyncio
    async def test_as_of_at_and_as_of_date_together_exits_with_error(self):
        with pytest.raises(SystemExit):
            await main(
                [
                    "--start-date",
                    "2026-08-01",
                    "--end-date",
                    "2026-08-20",
                    "--as-of-at",
                    "2026-08-24T12:20:00+09:00",
                    "--as-of-date",
                    "2026-08-24",
                ]
            )


class TestSameAsOfPropagatedToPopulationAndPriceQueries:
    @pytest.mark.asyncio
    async def test_fetch_population_and_fetch_close_series_receive_same_as_of_at(self):
        as_of_at = datetime(2026, 8, 24, 12, 20, 0, tzinfo=KST)
        conn = _FakeFetchConn()

        await fetch_population(conn, date(2026, 8, 1), date(2026, 8, 20), as_of_at)
        await fetch_close_series(conn, as_of_at, date(2026, 8, 24))

        population_sql, population_args = conn.calls[0]
        close_sql, close_args = conn.calls[1]

        assert population_sql == BUY_RAW_SQL
        assert population_args[2] is as_of_at
        assert close_sql == CLOSE_SQL
        assert close_args[0] is as_of_at

    def test_close_sql_filters_on_created_at_not_only_trade_date_label(self):
        # availability cutoff는 created_at(적재 시각) 기준이어야 한다 —
        # clpr_chng_dt/trade_date 라벨만으로 제한하면 backfill된 과거
        # 라벨이 as-of 판정을 왜곡할 수 있다.
        assert "created_at <= $1" in CLOSE_SQL
        assert "trade_date <= $2" in CLOSE_SQL

    def test_buy_raw_sql_filters_decision_created_at_on_as_of_at(self):
        assert "td.created_at <= $3" in BUY_RAW_SQL


class TestPriceDuplicateHandling:
    def test_identical_duplicate_prices_are_collapsed_to_one_bar(self):
        rows = [
            _close_row("i1", date(2026, 8, 7), 100.0, "kis_stock_basic_info", row_id="a"),
            _close_row("i1", date(2026, 8, 7), 100.0, "kis_stock_basic_info", row_id="b"),
        ]
        idx, stats = build_close_index(rows)
        assert len(idx["i1"]) == 1
        assert idx["i1"][0].close_price == 100.0
        assert stats["duplicate_units_detected"] == 1
        assert stats["duplicate_rows_same_price_collapsed"] == 1
        assert stats["duplicate_rows_conflicting_price_resolved"] == 0

    def test_conflicting_duplicate_prices_resolved_by_latest_snapshot_at(self):
        older = _close_row(
            "i1",
            date(2026, 8, 7),
            100.0,
            "kis_stock_basic_info",
            snapshot_at=datetime(2026, 8, 7, 5, 5, tzinfo=KST),
            row_id="old",
        )
        newer = _close_row(
            "i1",
            date(2026, 8, 7),
            101.0,
            "kis_stock_basic_info",
            snapshot_at=datetime(2026, 8, 7, 18, 0, tzinfo=KST),
            row_id="new",
        )
        idx, stats = build_close_index([older, newer])
        assert len(idx["i1"]) == 1
        assert idx["i1"][0].close_price == 101.0  # 더 최신 snapshot_at이 이김
        assert stats["duplicate_rows_conflicting_price_resolved"] == 1
        assert stats["by_price_source"]["kis_stock_basic_info"]["conflict_resolved"] == 1
        assert stats["conflict_examples"][0]["chosen_close_price"] == 101.0
        assert stats["conflict_examples"][0]["dropped_close_prices"] == [100.0]

    def test_tie_break_falls_through_to_created_at_then_row_id(self):
        # snapshot_at이 같으면 created_at, 그것도 같으면 row_id로 끝맺는다.
        same_snapshot = datetime(2026, 8, 7, 5, 5, tzinfo=KST)
        row_a = _close_row(
            "i1",
            date(2026, 8, 7),
            100.0,
            "kis_stock_basic_info",
            snapshot_at=same_snapshot,
            created_at=datetime(2026, 8, 7, 5, 6, tzinfo=KST),
            row_id="a",
        )
        row_b = _close_row(
            "i1",
            date(2026, 8, 7),
            102.0,
            "kis_stock_basic_info",
            snapshot_at=same_snapshot,
            created_at=datetime(2026, 8, 7, 5, 7, tzinfo=KST),
            row_id="b",
        )
        idx, stats = build_close_index([row_a, row_b])
        assert idx["i1"][0].close_price == 102.0  # 더 최신 created_at이 이김

    def test_duplicate_does_not_double_count_trading_day_for_forward_return(self):
        # 같은 (종목, 거래일)에 중복이 있어도 T+1은 그 날을 두 번이 아니라
        # 한 번만 센 뒤 다음 실제 거래일로 넘어가야 한다.
        rows = [
            _close_row("i1", date(2026, 8, 7), 100.0, "kis_stock_basic_info", row_id="a"),
            _close_row("i1", date(2026, 8, 7), 100.0, "kis_stock_basic_info", row_id="b"),
            _close_row("i1", date(2026, 8, 10), 105.0, "kis_stock_basic_info", row_id="c"),
        ]
        idx, _ = build_close_index(rows)
        r = compute_forward_return(idx, "i1", date(2026, 8, 7), 1)
        assert r.exclusion_reason is None
        assert r.target_trade_date == date(2026, 8, 10).isoformat()
        assert r.return_pct == round((105.0 / 100.0 - 1.0) * 100.0, 4)

    def test_no_duplicates_reports_zero_counts(self):
        rows = [_close_row("i1", date(2026, 8, 7), 100.0, "kis_stock_basic_info", row_id="a")]
        _, stats = build_close_index(rows)
        assert stats["duplicate_units_detected"] == 0
        assert stats["duplicate_rows_same_price_collapsed"] == 0
        assert stats["duplicate_rows_conflicting_price_resolved"] == 0
        assert stats["conflict_examples"] == []


class TestReproducibilityMetadataAndOutputStructure:
    def test_metadata_includes_as_of_at_kst_and_cutoff_rule(self):
        metadata = build_reproducibility_metadata(
            query_executed_at_kst="2026-08-24T13:00:00+09:00",
            start_date=date(2026, 6, 18),
            end_date=date(2026, 8, 21),
            as_of_at=datetime(2026, 8, 24, 12, 20, 0, tzinfo=KST),
            as_of_precision="exact_timestamp",
            horizons=[1, 5, 20],
            script_git_sha="deadbeef",
        )
        assert metadata["as_of_at_kst"] == "2026-08-24T12:20:00+09:00"
        assert metadata["as_of_precision"] == "exact_timestamp"
        assert "created_at" in metadata["price_availability_cutoff_rule"]
        assert "look_ahead_caveat" in metadata
        assert "historical_snapshot_note" in metadata
        assert "as_of_date_legacy_warning" not in metadata

    def test_legacy_precision_adds_explicit_warning(self):
        metadata = build_reproducibility_metadata(
            query_executed_at_kst="2026-08-24T13:00:00+09:00",
            start_date=date(2026, 6, 18),
            end_date=date(2026, 8, 21),
            as_of_at=datetime(2026, 8, 24, 23, 59, 59, tzinfo=KST),
            as_of_precision="date_end_of_day_kst_legacy",
            horizons=[1],
            script_git_sha=None,
        )
        assert "as_of_date_legacy_warning" in metadata

    def test_run_analysis_output_includes_duplicate_handling_block(self):
        d1 = date(2026, 8, 7)
        raw_rows = [_raw_row("i1", "007340", d1, "matched", 9)]
        close_rows = [_close_row("i1", d1, 100.0, "kis_stock_basic_info", row_id="a")]
        result = run_analysis(raw_rows, close_rows, horizons=[1])
        assert "price_duplicate_handling" in result
        assert "duplicate_rows_conflicting_price_resolved" in result["price_duplicate_handling"]
