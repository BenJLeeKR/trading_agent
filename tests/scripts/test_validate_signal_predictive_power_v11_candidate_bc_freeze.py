"""단위 테스트 — SPPV-3 §36.2 동결 후보 B/C 계산 함수(DB/네트워크 미사용).

전부 순수 함수 또는 로컬 임시 파일만으로 검증한다. 실제 bar cache나
DB, KIS API를 전혀 건드리지 않는다.
"""

from __future__ import annotations

import json
import math
import os

from scripts.validate_signal_predictive_power_v11_candidate_bc_freeze import (
    StrictBar,
    _rows_with_valid_signal_and_return,
    compute_overnight_intraday_split_momentum,
    load_strict_bars,
    rank_low_volatility_cross_sectional,
    summarize_signal_window,
)


def _bar(trade_date: str, close: float, open_: float | None) -> StrictBar:
    return StrictBar(
        trade_date=trade_date,
        close=close,
        open=open_,
        high=close,
        low=close,
        open_valid=open_ is not None and open_ > 0,
    )


class TestComputeOvernightIntradaySplitMomentum:
    def test_formula_matches_frozen_definition(self):
        # 6개 bar(인덱스 0..5), t=5, n=5 -> window은 인덱스 0..5 전부.
        bars = [
            _bar("20260101", 100.0, 100.0),
            _bar("20260102", 102.0, 101.0),
            _bar("20260103", 101.0, 102.5),
            _bar("20260104", 103.0, 101.5),
            _bar("20260105", 105.0, 103.5),
            _bar("20260106", 107.0, 105.5),
        ]
        result = compute_overnight_intraday_split_momentum(bars, t=5, n=5)
        assert result["exclusion_reason"] is None

        expected_overnight = sum(
            math.log(bars[i].open / bars[i - 1].close) for i in range(1, 6)
        )
        expected_intraday = sum(
            math.log(bars[i].close / bars[i].open) for i in range(1, 6)
        )
        assert math.isclose(result["overnight_ret_Nd"], expected_overnight, rel_tol=1e-9)
        assert math.isclose(result["intraday_ret_Nd"], expected_intraday, rel_tol=1e-9)
        assert math.isclose(
            result["divergence"], expected_overnight - expected_intraday, rel_tol=1e-9
        )

    def test_lookback_insufficient_when_not_enough_history(self):
        bars = [_bar("20260101", 100.0, 100.0), _bar("20260102", 101.0, 100.5)]
        result = compute_overnight_intraday_split_momentum(bars, t=1, n=5)
        assert result["exclusion_reason"] == "lookback_insufficient"
        assert result["overnight_ret_Nd"] is None
        assert result["intraday_ret_Nd"] is None

    def test_missing_open_in_window_is_excluded_not_defaulted_to_close(self):
        bars = [
            _bar("20260101", 100.0, 100.0),
            _bar("20260102", 101.0, None),  # open 결측
            _bar("20260103", 102.0, 101.5),
            _bar("20260104", 103.0, 102.5),
            _bar("20260105", 104.0, 103.5),
            _bar("20260106", 105.0, 104.5),
        ]
        result = compute_overnight_intraday_split_momentum(bars, t=5, n=5)
        assert result["exclusion_reason"] == "open_missing_or_nonpositive_in_window"
        assert result["overnight_ret_Nd"] is None

    def test_no_lookahead_future_bars_do_not_affect_signal_at_t(self):
        bars_a = [
            _bar("20260101", 100.0, 100.0),
            _bar("20260102", 102.0, 101.0),
            _bar("20260103", 101.0, 102.5),
            _bar("20260104", 103.0, 101.5),
            _bar("20260105", 105.0, 103.5),
            _bar("20260106", 107.0, 105.5),
            _bar("20260107", 999.0, 999.0),  # t=6 이후, t=5 계산에 영향 없어야 함
        ]
        bars_b = list(bars_a)
        bars_b[6] = _bar("20260107", 1.0, 1.0)  # 미래 값만 다르게 변조

        result_a = compute_overnight_intraday_split_momentum(bars_a, t=5, n=5)
        result_b = compute_overnight_intraday_split_momentum(bars_b, t=5, n=5)
        assert result_a == result_b

    def test_prior_close_missing_excludes_window(self):
        bars = [
            _bar("20260101", 0.0, 100.0),  # close<=0 (t-n 위치의 종가 결측)
            _bar("20260102", 101.0, 100.5),
            _bar("20260103", 102.0, 101.5),
            _bar("20260104", 103.0, 102.5),
            _bar("20260105", 104.0, 103.5),
            _bar("20260106", 105.0, 104.5),
        ]
        result = compute_overnight_intraday_split_momentum(bars, t=5, n=5)
        assert result["exclusion_reason"] == "close_missing_or_nonpositive_in_window"


class TestLoadStrictBars:
    def test_missing_close_row_dropped_and_counted(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        payload = {
            "20260101": {"stck_clpr": "10000", "stck_oprc": "9900"},
            "20260102": {"stck_clpr": "0", "stck_oprc": "9950"},  # close<=0
            "20260103": {"stck_clpr": "10100", "stck_oprc": ""},  # open 결측
        }
        (cache_dir / "005930.json").write_text(json.dumps(payload), encoding="utf-8")

        bars, exclusions = load_strict_bars("005930", cache_dir=str(cache_dir))

        assert [b.trade_date for b in bars] == ["20260101", "20260103"]
        assert exclusions["close_missing_or_nonpositive"] == 1
        assert exclusions["open_missing_or_nonpositive"] == 1
        assert bars[1].open_valid is False
        assert bars[1].open is None  # 임의로 종가를 채워 넣지 않는다

    def test_nonexistent_symbol_file_returns_empty(self, tmp_path):
        bars, exclusions = load_strict_bars("999999", cache_dir=str(tmp_path))
        assert bars == []
        assert exclusions["close_missing_or_nonpositive"] == 0


def _cross_sectional_rows(trade_date: str, signal_values: list[float | None]) -> list[dict]:
    """한 거래일에 대해 종목별 signal/fwd 값을 가진 표본 행을 만든다.

    ``_cross_sectional_ic_by_date``/``_quintile_spread_series``는 하루
    표본이 5개 미만이면 그 날을 건너뛰므로, 테스트는 항상 6개 이상의
    종목을 채운다.
    """
    rows = []
    for i, sig in enumerate(signal_values):
        rows.append(
            {
                "trade_date": trade_date,
                "symbol": f"SYM{i}",
                "sig": sig,
                "fwd_1": None if sig is None else 0.01 * (i + 1),
                "fwd_1_net": None if sig is None else 0.01 * (i + 1) - 0.003,
            }
        )
    return rows


class TestValidSignalReturnFiltering:
    def test_none_signal_row_excluded_from_valid_set_and_counted(self):
        rows = _cross_sectional_rows(
            "2026-01-02", [1.0, 2.0, 3.0, 4.0, 5.0, None]
        )
        valid, excluded = _rows_with_valid_signal_and_return(rows, "sig", "fwd_1")
        assert len(valid) == 5
        assert excluded == 1
        assert all(r["sig"] is not None for r in valid)

    def test_none_return_row_excluded_and_counted(self):
        rows = _cross_sectional_rows("2026-01-02", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        rows[0]["fwd_1"] = None  # 신호는 있으나 forward return이 결측
        valid, excluded = _rows_with_valid_signal_and_return(rows, "sig", "fwd_1")
        assert len(valid) == 5
        assert excluded == 1

    def test_nonfinite_signal_excluded(self):
        rows = _cross_sectional_rows(
            "2026-01-02", [1.0, 2.0, 3.0, 4.0, 5.0, float("nan")]
        )
        valid, excluded = _rows_with_valid_signal_and_return(rows, "sig", "fwd_1")
        assert len(valid) == 5
        assert excluded == 1

    def test_all_valid_rows_produce_zero_excluded_count(self):
        rows = _cross_sectional_rows("2026-01-02", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        valid, excluded = _rows_with_valid_signal_and_return(rows, "sig", "fwd_1")
        assert len(valid) == 6
        assert excluded == 0


class TestSummarizeSignalWindowHandlesMissingRows:
    def test_missing_signal_row_does_not_crash_and_is_excluded_from_summary(self):
        samples = _cross_sectional_rows(
            "2026-01-02", [1.0, 2.0, 3.0, 4.0, 5.0, None]
        ) + _cross_sectional_rows("2026-01-05", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        summary = summarize_signal_window(samples, "sig", [1])
        assert summary["T+1"]["excluded_row_count_for_ic"] == 1
        assert summary["T+1"]["valid_row_count_for_ic"] == 11

    def test_valid_only_samples_are_unaffected_by_filtering(self):
        # 결측이 전혀 없는 기존 사례 -> 필터를 거쳐도 결과가 동일해야 한다.
        samples_no_missing = _cross_sectional_rows(
            "2026-01-02", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        ) + _cross_sectional_rows("2026-01-05", [6.0, 5.0, 4.0, 3.0, 2.0, 1.0])

        filtered, excluded = _rows_with_valid_signal_and_return(samples_no_missing, "sig", "fwd_1")
        assert excluded == 0
        assert len(filtered) == len(samples_no_missing)

        summary = summarize_signal_window(samples_no_missing, "sig", [1])
        assert summary["T+1"]["excluded_row_count_for_ic"] == 0
        assert summary["T+1"]["valid_row_count_for_ic"] == len(samples_no_missing)


class TestRankLowVolatilityCrossSectional:
    def test_lowest_volatility_gets_highest_score(self):
        vols = {"A": 5.0, "B": 1.0, "C": 3.0}
        scores, meta = rank_low_volatility_cross_sectional(vols)
        assert scores["B"] > scores["C"] > scores["A"]
        assert scores["B"] == 1.0
        assert scores["A"] == -1.0
        assert meta["valid_symbol_count"] == 3
        assert meta["missing_symbol_count"] == 0

    def test_missing_values_excluded_and_counted(self):
        vols = {"A": 5.0, "B": None, "C": 3.0}
        scores, meta = rank_low_volatility_cross_sectional(vols)
        assert "B" not in scores
        assert meta["valid_symbol_count"] == 2
        assert meta["missing_symbol_count"] == 1

    def test_fewer_than_two_valid_symbols_scores_zero(self):
        scores, meta = rank_low_volatility_cross_sectional({"A": 5.0})
        assert scores["A"] == 0.0
        assert meta["valid_symbol_count"] == 1

    def test_tied_volatility_values_receive_identical_average_rank_score(self):
        # A, B가 동일 변동성(2.0) -> 평균 순위를 공유해 정확히 같은 점수.
        vols = {"A": 2.0, "B": 2.0, "C": 1.0}
        scores, meta = rank_low_volatility_cross_sectional(vols)
        assert scores["C"] == 1.0  # 유일한 최저 변동성 -> 최고 점수
        assert scores["A"] == scores["B"]
        assert meta["tie_break_rule"] == "average_rank_for_ties_input_order_independent"

    def test_tie_scores_independent_of_input_dict_order(self):
        vols_order_1 = {"A": 2.0, "B": 2.0, "C": 1.0}
        vols_order_2 = {"B": 2.0, "A": 2.0, "C": 1.0}
        scores_1, _ = rank_low_volatility_cross_sectional(vols_order_1)
        scores_2, _ = rank_low_volatility_cross_sectional(vols_order_2)
        assert scores_1 == scores_2

    def test_three_way_tie_average_rank_matches_manual_calculation(self):
        # 4개 종목, 3개가 동점(1.0) -> 그 3개는 순위 위치 0,1,2의 평균(=1)을
        # 공유, 나머지 하나(5.0, 위치3)는 단독 최저 점수를 받는다.
        vols = {"A": 1.0, "B": 1.0, "C": 1.0, "D": 5.0}
        scores, _ = rank_low_volatility_cross_sectional(vols)
        n = 4
        expected_tied_score = ((n - 1 - 1.0) / (n - 1)) * 2.0 - 1.0  # avg_position=1
        assert math.isclose(scores["A"], expected_tied_score)
        assert math.isclose(scores["B"], expected_tied_score)
        assert math.isclose(scores["C"], expected_tied_score)
        assert scores["D"] == -1.0

    def test_nonfinite_volatility_treated_as_missing(self):
        vols = {"A": 5.0, "B": float("nan"), "C": 3.0}
        scores, meta = rank_low_volatility_cross_sectional(vols)
        assert "B" not in scores
        assert meta["missing_symbol_count"] == 1
