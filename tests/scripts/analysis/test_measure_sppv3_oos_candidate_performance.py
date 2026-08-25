"""단위 테스트 — SPPV-3 독립 OOS 성과 계산 도구(DB/네트워크 미사용).

전부 순수 함수 또는 인메모리 합성(synthetic) 데이터로 검증한다. 실제
KIS API, DB, OOS bar cache 파일은 건드리지 않는다(파일 I/O가 필요한
로더 함수는 별도 통합 실행에서만 다룬다).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.analysis.measure_sppv3_oos_candidate_performance import (
    EXPECTED_BASE_CACHE_AS_OF_DATE,
    EXPECTED_BASE_CACHE_ID,
    EXPECTED_BASE_CACHE_RELATIVE_PATH,
    EXPECTED_OOS_START_DATE_COMPACT,
    MIN_OOS_TRADING_DAYS_FOR_VERDICT,
    OOS_START_DATE_ISO,
    attach_reversal_candidates,
    build_benchmark_regime_and_risk_tone_by_date_full_range,
    build_provenance_by_date,
    classify_verdict_from_t_stat,
    collect_oos_samples_for_symbol,
    determine_oos_analysis_status,
    validate_oos_manifest,
)
from scripts.validate_signal_predictive_power_v11_candidate_bc_freeze import StrictBar

from agent_trading.services.signal_backbone import PriceBar

KST = timezone(timedelta(hours=9))


def _valid_manifest() -> dict:
    return {
        "base_cache_id": EXPECTED_BASE_CACHE_ID,
        "base_cache_relative_path": EXPECTED_BASE_CACHE_RELATIVE_PATH,
        "base_cache_as_of_date": EXPECTED_BASE_CACHE_AS_OF_DATE,
        "oos_collection_window": {"start_date": EXPECTED_OOS_START_DATE_COMPACT, "end_date": "20260824"},
        "ready_for_oos": True,
    }


class TestValidateOosManifest:
    def test_valid_manifest_passes(self):
        validate_oos_manifest(_valid_manifest())  # 예외 없이 통과해야 함

    def test_ready_for_oos_false_is_rejected(self):
        manifest = _valid_manifest()
        manifest["ready_for_oos"] = False
        with pytest.raises(ValueError, match="ready_for_oos"):
            validate_oos_manifest(manifest)

    def test_wrong_base_cache_id_is_rejected(self):
        manifest = _valid_manifest()
        manifest["base_cache_id"] = "_bars_cache_core87_3y_2099-01-01"
        with pytest.raises(ValueError, match="base_cache_id"):
            validate_oos_manifest(manifest)

    def test_wrong_oos_start_date_is_rejected(self):
        manifest = _valid_manifest()
        manifest["oos_collection_window"] = {"start_date": "20260101", "end_date": "20260824"}
        with pytest.raises(ValueError, match="oos_collection_window"):
            validate_oos_manifest(manifest)

    def test_missing_ready_for_oos_key_is_rejected(self):
        manifest = _valid_manifest()
        del manifest["ready_for_oos"]
        with pytest.raises(ValueError, match="ready_for_oos"):
            validate_oos_manifest(manifest)


class TestBuildProvenanceByDate:
    def test_maps_compact_date_to_iso_with_provenance(self):
        raw = {
            "20260710": {"_cache_provenance": "base_cache"},
            "20260715": {"_cache_provenance": "oos_new"},
        }
        prov = build_provenance_by_date(raw)
        assert prov == {"2026-07-10": "base_cache", "2026-07-15": "oos_new"}

    def test_unknown_provenance_value_raises(self):
        raw = {"20260710": {"_cache_provenance": "something_else"}}
        with pytest.raises(ValueError, match="알 수 없는"):
            build_provenance_by_date(raw)

    def test_missing_provenance_key_raises(self):
        raw = {"20260710": {}}
        with pytest.raises(ValueError, match="알 수 없는"):
            build_provenance_by_date(raw)


def _make_synthetic_strict_bars(n: int, start: str = "20260501") -> list[StrictBar]:
    # 기본 시작일을 2026-05-01로 고정한다 — OOS_START_DATE_ISO(2026-07-15)를
    # 실제로 넘어서는 날짜가 나오도록(2026-01-01 시작이면 90일로는 3월 말
    # 밖에 안 되어, "OOS 이후" 관련 assert가 표본이 텅 빈 채로 공허하게
    # 통과하는 은폐된 실패가 생겼던 적이 있다 — 그 재발을 막기 위한 주석).
    start_date = datetime.strptime(start, "%Y%m%d")
    bars = []
    for i in range(n):
        d = (start_date + timedelta(days=i)).strftime("%Y%m%d")
        close = 10000.0 + i * 5.0
        bars.append(
            StrictBar(
                trade_date=d,
                close=close,
                open=close - 3.0,
                high=close + 5.0,
                low=close - 8.0,
                open_valid=True,
            )
        )
    return bars


def _iso(compact: str) -> str:
    return f"{compact[0:4]}-{compact[4:6]}-{compact[6:8]}"


class TestCollectOosSamplesForSymbol:
    """base cache 행이 성과 표본에 섞이지 않고, oos_new 행만 쓰인다."""

    def _provenance_and_regime(self, bars: list[StrictBar], oos_start_index: int):
        provenance = {}
        regime = {}
        for i, b in enumerate(bars):
            iso = _iso(b.trade_date)
            provenance[iso] = "oos_new" if i >= oos_start_index else "base_cache"
            regime[iso] = {"regime_label": "bullish_trend", "risk_tone": "risk_on"}
        return provenance, regime

    def test_only_oos_new_dates_on_or_after_start_produce_samples(self):
        bars = _make_synthetic_strict_bars(90)
        oos_start_index = 75  # 2026-05-01 시작 기준 index75 = 2026-07-15(OOS 시작일)
        provenance, regime = self._provenance_and_regime(bars, oos_start_index)

        samples, _exclusions = collect_oos_samples_for_symbol("TEST", bars, provenance, regime)

        sample_dates = {row["trade_date"] for row in samples}
        base_dates = {_iso(b.trade_date) for b in bars[:oos_start_index]}
        oos_dates = {_iso(b.trade_date) for b in bars[oos_start_index:]}

        assert len(samples) > 0  # 표본이 비어 있으면 아래 두 assert가 공허하게 통과해버림
        assert sample_dates.issubset(oos_dates)
        assert not (sample_dates & base_dates)  # base cache 날짜가 하나도 섞이지 않음

    def test_dates_before_oos_start_iso_are_excluded_even_if_tagged_oos_new(self):
        bars = _make_synthetic_strict_bars(90)
        provenance = {_iso(b.trade_date): "oos_new" for b in bars}  # 방어적 케이스: 전부 oos_new로 오염
        regime = {_iso(b.trade_date): {"regime_label": "bullish_trend", "risk_tone": "risk_on"} for b in bars}

        samples, _ = collect_oos_samples_for_symbol("TEST", bars, provenance, regime)
        assert len(samples) > 0  # 표본이 비어 있으면 아래 assert가 공허하게 통과해버림
        assert all(row["trade_date"] >= OOS_START_DATE_ISO for row in samples)

    def test_horizon_not_arrived_is_tracked_per_horizon_not_whole_row_dropped(self):
        bars = _make_synthetic_strict_bars(90)
        oos_start_index = 85  # 끝에서 5개만 oos_new -> T+20은 절대 도래 못 함
        provenance, regime = self._provenance_and_regime(bars, oos_start_index)

        samples, exclusions = collect_oos_samples_for_symbol("TEST", bars, provenance, regime)

        assert len(samples) > 0  # 행 자체는 생성됨(T+20 미도래와 무관하게)
        assert any(row["fwd_1"] is not None for row in samples)
        assert all(row["fwd_20"] is None for row in samples)  # T+20은 전부 미도래
        assert exclusions.get("fwd_20_horizon_not_arrived", 0) > 0

    def test_no_lookahead_appending_future_bars_does_not_change_past_signal_values(self):
        bars_a = _make_synthetic_strict_bars(90)
        oos_start_index = 75  # 2026-05-01 시작 기준 index75 = 2026-07-15(OOS 시작일)
        provenance_a, regime_a = self._provenance_and_regime(bars_a, oos_start_index)
        samples_a, _ = collect_oos_samples_for_symbol("TEST", bars_a, provenance_a, regime_a)
        assert len(samples_a) > 0  # 표본이 비어 있으면 아래 비교 자체가 공허하게 통과해버림

        # 미래에 bar를 더 추가(값도 완전히 다르게) — 과거 날짜의 신호값/이미
        # 계산된 forward return은 전혀 바뀌면 안 된다.
        extra = _make_synthetic_strict_bars(10, start="20260801")
        for e in extra:
            e_mutated = StrictBar(
                trade_date=e.trade_date, close=999999.0, open=999999.0, high=999999.0, low=999999.0, open_valid=True
            )
            bars_a.append(e_mutated)
        provenance_b = dict(provenance_a)
        regime_b = dict(regime_a)
        for e in bars_a[90:]:
            provenance_b[_iso(e.trade_date)] = "oos_new"
            regime_b[_iso(e.trade_date)] = {"regime_label": "bullish_trend", "risk_tone": "risk_on"}

        samples_b, _ = collect_oos_samples_for_symbol("TEST", bars_a, provenance_b, regime_b)
        by_date_b = {row["trade_date"]: row for row in samples_b}

        for row_a in samples_a:
            row_b = by_date_b[row_a["trade_date"]]
            assert row_a["overnight_ret_5d"] == row_b["overnight_ret_5d"]
            assert row_a["intraday_ret_5d"] == row_b["intraday_ret_5d"]
            for h in (1, 5, 20):
                # 이미 도래해 있던 forward return은 미래 bar 추가로 바뀌면 안 된다.
                if row_a[f"fwd_{h}"] is not None:
                    assert row_a[f"fwd_{h}"] == row_b[f"fwd_{h}"]


class TestAttachReversalCandidates:
    def test_sign_is_flipped(self):
        samples = [{"overnight_ret_5d": 0.02, "intraday_ret_5d": -0.01}]
        attach_reversal_candidates(samples)
        assert samples[0]["overnight_reversal_v1"] == -0.02
        assert samples[0]["intraday_reversal_v1"] == 0.01

    def test_missing_raw_signal_stays_missing_not_zero(self):
        samples = [{"overnight_ret_5d": None, "intraday_ret_5d": None}]
        attach_reversal_candidates(samples)
        assert samples[0]["overnight_reversal_v1"] is None
        assert samples[0]["intraday_reversal_v1"] is None


class TestClassifyVerdictFromTStat:
    def test_significant_correct_sign_is_go(self):
        assert classify_verdict_from_t_stat(2.5, expected_ic_sign=1) == "Go"

    def test_significant_wrong_sign_is_no_go(self):
        assert classify_verdict_from_t_stat(-2.5, expected_ic_sign=1) == "No-Go"

    def test_marginal_correct_sign_is_watch(self):
        assert classify_verdict_from_t_stat(1.7, expected_ic_sign=1) == "Watch"

    def test_weak_signal_is_hold(self):
        assert classify_verdict_from_t_stat(0.5, expected_ic_sign=1) == "Hold"

    def test_none_t_stat_is_hold(self):
        assert classify_verdict_from_t_stat(None, expected_ic_sign=1) == "Hold"


class TestDetermineOosAnalysisStatus:
    def test_insufficient_total_days_yields_pending(self):
        status = determine_oos_analysis_status(
            total_oos_trading_days=27,
            per_horizon_valid_counts={1: 27, 5: 20, 20: 0},
            regime_gate={"bullish_trend": {"trading_day_count": 27, "meets_min_sample": False}},
        )
        assert status["status"] == "PENDING_INSUFFICIENT_OOS_SAMPLE"
        assert any("전체 OOS 거래일 수 부족" in r for r in status["reasons"])
        assert any("T+20 유효 표본 부족" in r for r in status["reasons"])
        assert any("국면별 최소 표본" in r for r in status["reasons"])

    def test_current_sppv3_oos_sample_size_is_explicitly_pending(self):
        # 2026-08-24 실제 수집(§42/§43)의 대략적 표본 규모를 그대로 재현 —
        # 이 조건에서는 T+1조차 공식 판정을 낼 수 없어야 한다.
        status = determine_oos_analysis_status(
            total_oos_trading_days=27,
            per_horizon_valid_counts={1: 26, 5: 22, 20: 7},
            regime_gate={"bullish_trend": {"trading_day_count": 27, "meets_min_sample": False}},
        )
        assert status["status"] == "PENDING_INSUFFICIENT_OOS_SAMPLE"

    def test_sufficient_sample_delegates_to_classify_verdict(self):
        per_horizon = {1: 40, 5: 35, 20: 30}
        regime_gate = {"bullish_trend": {"trading_day_count": 40, "meets_min_sample": True}}
        status = determine_oos_analysis_status(
            total_oos_trading_days=40,
            per_horizon_valid_counts=per_horizon,
            regime_gate=regime_gate,
            primary_t_stat=2.3,
            expected_ic_sign=1,
        )
        assert status["status"] == classify_verdict_from_t_stat(2.3, expected_ic_sign=1)
        assert status["status"] == "Go"
        assert status["reasons"] == []

    def test_min_oos_trading_days_constant_matches_documented_threshold(self):
        assert MIN_OOS_TRADING_DAYS_FOR_VERDICT == 30


class TestBuildBenchmarkRegimeFullRange:
    """v11의 절단된 버전과 달리, 최근 거래일까지 국면 라벨이 빠지지
    않아야 한다(실제 실행에서 이 절단 때문에 OOS 최근 20일의 국면
    라벨이 통째로 사라지는 결함이 발견됐다)."""

    def test_covers_dates_up_to_the_very_last_bar_not_truncated_by_forward_horizon(self):
        n = 90
        start_date = datetime(2026, 5, 1)
        bars = [
            PriceBar(
                timestamp=(start_date + timedelta(days=i)).replace(tzinfo=KST),
                open_price=10000.0 + i * 5.0,
                high_price=10010.0 + i * 5.0,
                low_price=9990.0 + i * 5.0,
                close_price=10000.0 + i * 5.0,
                volume=0.0,
                turnover=None,
            )
            for i in range(n)
        ]
        regime_by_date = build_benchmark_regime_and_risk_tone_by_date_full_range(bars, "069500")

        last_date = bars[-1].timestamp.strftime("%Y-%m-%d")
        # v11의 절단 버전이라면 max(FORWARD_HORIZONS)=20일만큼 마지막
        # 20거래일이 통째로 빠졌을 것 — 이 함수는 그러지 않아야 한다.
        assert last_date in regime_by_date
        near_end_date = (bars[-3].timestamp).strftime("%Y-%m-%d")
        assert near_end_date in regime_by_date
