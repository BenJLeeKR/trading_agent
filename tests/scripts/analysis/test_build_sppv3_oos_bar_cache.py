"""단위 테스트 — SPPV-3 OOS bar cache 수집 스크립트의 순수 함수(DB/네트워크 미사용).

전부 인메모리 dict/임시 파일만으로 검증한다. 실제 KIS API, DB, 외부
네트워크는 전혀 건드리지 않는다.
"""

from __future__ import annotations

import json
import os

from scripts.analysis.build_sppv3_oos_bar_cache import (
    BASE_CACHE_ID,
    BASE_CACHE_RELATIVE_PATH,
    OOS_START_DATE,
    build_manifest,
    build_symbol_cache_entry,
    determine_ready_for_oos,
    merge_kis_windows,
    summarize_symbol_bars,
    SymbolCollectionResult,
    MergeStats,
)


def _raw(date_str: str, close: str = "10000") -> dict:
    return {"stck_bsop_date": date_str, "stck_clpr": close}


class TestMergeKisWindows:
    def test_no_overlap_no_duplicates(self):
        window_a = [_raw("20260715"), _raw("20260716")]
        window_b = [_raw("20260717"), _raw("20260718")]
        merged, dup = merge_kis_windows([window_a, window_b])
        assert set(merged.keys()) == {"20260715", "20260716", "20260717", "20260718"}
        assert dup == 0

    def test_overlapping_dates_counted_and_last_window_wins(self):
        window_a = [_raw("20260715", close="100"), _raw("20260716", close="101")]
        window_b = [_raw("20260716", close="999"), _raw("20260717", close="102")]
        merged, dup = merge_kis_windows([window_a, window_b])
        assert dup == 1
        assert merged["20260716"]["stck_clpr"] == "999"  # 나중 윈도(윈도 b)가 이김

    def test_rows_without_date_key_are_skipped(self):
        merged, dup = merge_kis_windows([[{"stck_clpr": "100"}]])
        assert merged == {}
        assert dup == 0


class TestBuildSymbolCacheEntry:
    def test_base_bars_are_preserved_unchanged(self):
        base = {"20260710": _raw("20260710", close="500")}
        new = {}
        combined, stats = build_symbol_cache_entry(base, new, OOS_START_DATE, "2026-08-24T10:00:00+09:00")
        assert combined["20260710"]["stck_clpr"] == "500"
        assert combined["20260710"]["_cache_provenance"] == "base_cache"
        assert combined["20260710"]["_collected_at_kst"] is None
        assert stats.base_bar_count == 1

    def test_only_dates_on_or_after_oos_start_are_added(self):
        # base cache에 방어적으로 "이미 oos_start 이후 날짜"가 들어있는
        # 비정상 케이스도 함께 검증한다(정상 운영에서는 발생하지 않아야
        # 하지만, 발생해도 base가 항상 이긴다는 것을 보장해야 한다).
        base = {"20260716": _raw("20260716", close="500")}
        new = {
            "20260716": _raw("20260716", close="999"),  # base와 겹침(방어적 케이스)
            "20260714": _raw("20260714"),  # oos_start 이전
            "20260715": _raw("20260715"),  # oos_start 당일 -> 포함
            "20260717": _raw("20260717"),
        }
        combined, stats = build_symbol_cache_entry(base, new, OOS_START_DATE, "2026-08-24T10:00:00+09:00")

        # base 값은 그대로(999로 덮어써지지 않음)
        assert combined["20260716"]["stck_clpr"] == base["20260716"]["stck_clpr"]
        assert combined["20260716"]["_cache_provenance"] == "base_cache"
        assert "20260714" not in combined
        assert combined["20260715"]["_cache_provenance"] == "oos_new"
        assert combined["20260715"]["_collected_at_kst"] == "2026-08-24T10:00:00+09:00"
        assert combined["20260717"]["_cache_provenance"] == "oos_new"

        assert stats.new_bar_added_count == 2  # 20260715, 20260717
        assert stats.new_bar_discarded_pre_oos_count == 1  # 20260714
        assert stats.overlap_with_base_discarded_count == 1  # 20260716

    def test_warm_up_and_oos_labels_are_mutually_exclusive(self):
        base = {"20260710": _raw("20260710")}
        new = {"20260715": _raw("20260715")}
        combined, _ = build_symbol_cache_entry(base, new, OOS_START_DATE, "2026-08-24T10:00:00+09:00")
        provenances = {d: r["_cache_provenance"] for d, r in combined.items()}
        assert provenances["20260710"] == "base_cache"
        assert provenances["20260715"] == "oos_new"
        assert provenances["20260710"] != provenances["20260715"]


class TestExistingCacheImmutability:
    def test_build_symbol_cache_entry_does_not_mutate_input_base_dict(self):
        base = {"20260710": _raw("20260710", close="500")}
        base_snapshot = json.loads(json.dumps(base))
        new = {"20260715": _raw("20260715")}
        build_symbol_cache_entry(base, new, OOS_START_DATE, "2026-08-24T10:00:00+09:00")
        assert base == base_snapshot  # 입력 base dict 자체가 변형되지 않았어야 함


def _result(
    symbol: str,
    fetch_status: str = "ok",
    new_bar_added_count: int = 5,
) -> SymbolCollectionResult:
    return SymbolCollectionResult(
        symbol=symbol,
        fetch_status=fetch_status,
        error_summary=None if fetch_status == "ok" else "TimeoutError",
        base_last_trade_date="20260714",
        new_first_trade_date="20260715" if new_bar_added_count else None,
        new_last_trade_date="20260810" if new_bar_added_count else None,
        merge_stats=MergeStats(
            base_bar_count=700,
            new_bar_added_count=new_bar_added_count,
            new_bar_discarded_pre_oos_count=0,
            overlap_with_base_discarded_count=0,
        ),
        duplicate_within_new_fetch_count=0,
        file_sha256="deadbeef" if fetch_status == "ok" else None,
    )


class TestReadyForOos:
    def test_all_symbols_ok_is_ready(self):
        results = [_result("A"), _result("B")]
        ready, notes = determine_ready_for_oos(results, {"A", "B"})
        assert ready is True

    def test_one_failed_symbol_blocks_ready(self):
        results = [_result("A"), _result("B", fetch_status="failed")]
        ready, notes = determine_ready_for_oos(results, {"A", "B"})
        assert ready is False
        assert "B" in notes

    def test_missing_required_symbol_blocks_ready(self):
        results = [_result("A")]
        ready, notes = determine_ready_for_oos(results, {"A", "B"})
        assert ready is False
        assert "B" in notes

    def test_zero_new_bars_does_not_block_ready_but_is_flagged(self):
        results = [_result("A"), _result("B", new_bar_added_count=0)]
        ready, notes = determine_ready_for_oos(results, {"A", "B"})
        assert ready is True
        assert "B" in notes  # 경고 목록에는 남지만 실패로 취급하지 않음


class TestBuildManifest:
    def test_manifest_contains_required_audit_fields(self):
        results = [_result("A"), _result("B")]
        manifest = build_manifest(
            cache_id="sppv3_oos_bar_cache_2026-08-24",
            generated_at_kst_iso="2026-08-24T16:00:00+09:00",
            generated_at_utc_iso="2026-08-24T07:00:00+00:00",
            base_cache_id=BASE_CACHE_ID,
            base_cache_relative_path=BASE_CACHE_RELATIVE_PATH,
            base_cache_as_of_date="2026-07-14",
            oos_start_date=OOS_START_DATE,
            oos_end_date="20260824",
            universe_symbols=["A", "B"],
            benchmark_symbol="069500",
            results=results,
            ready_for_oos=True,
            ready_for_oos_notes=[],
        )
        required_keys = {
            "cache_id",
            "generated_at_kst",
            "generated_at_utc",
            "manifest_regenerated_from_existing_cache",
            "base_cache_id",
            "base_cache_relative_path",
            "base_cache_as_of_date",
            "oos_collection_window",
            "universe_symbol_count",
            "benchmark_symbol",
            "kis_call_kind",
            "totals",
            "symbols",
            "ready_for_oos",
            "ready_for_oos_meaning_note",
            "ready_for_oos_notes",
            "oos_label_boundary_note",
            "no_signal_or_verdict_note",
        }
        assert required_keys.issubset(manifest.keys())
        assert manifest["ready_for_oos"] is True
        assert len(manifest["symbols"]) == 2
        assert manifest["no_signal_or_verdict_note"]  # 판정/성과 계산 미수행 표시 존재
        assert manifest["manifest_regenerated_from_existing_cache"] is False

    def test_manifest_contains_no_secret_looking_fields(self):
        manifest = build_manifest(
            cache_id="x",
            generated_at_kst_iso="2026-08-24T16:00:00+09:00",
            generated_at_utc_iso="2026-08-24T07:00:00+00:00",
            base_cache_id=BASE_CACHE_ID,
            base_cache_relative_path=BASE_CACHE_RELATIVE_PATH,
            base_cache_as_of_date="2026-07-14",
            oos_start_date=OOS_START_DATE,
            oos_end_date="20260824",
            universe_symbols=["A"],
            benchmark_symbol="069500",
            results=[_result("A")],
            ready_for_oos=True,
            ready_for_oos_notes=[],
        )
        serialized = json.dumps(manifest).lower()
        for forbidden in ("appkey", "app_secret", "app_key", "bearer "):
            assert forbidden not in serialized

    def test_manifest_stores_repo_relative_path_not_a_temp_staging_absolute_path(self):
        # 실행 환경마다 달라지는 임시 staging 절대경로(예: /tmp/oos_repo/...)를
        # 그대로 흉내 낸 값을 넣어도, canonical 필드는 base_cache_relative_path
        # 하나뿐이고 그 값 자체가 절대경로 접두어를 갖지 않아야 한다.
        manifest = build_manifest(
            cache_id="x",
            generated_at_kst_iso="2026-08-24T16:00:00+09:00",
            generated_at_utc_iso="2026-08-24T07:00:00+00:00",
            base_cache_id=BASE_CACHE_ID,
            base_cache_relative_path=BASE_CACHE_RELATIVE_PATH,
            base_cache_as_of_date="2026-07-14",
            oos_start_date=OOS_START_DATE,
            oos_end_date="20260824",
            universe_symbols=["A"],
            benchmark_symbol="069500",
            results=[_result("A")],
            ready_for_oos=True,
            ready_for_oos_notes=[],
        )
        assert "base_cache_path" not in manifest  # 옛 필드명이 남아있지 않아야 함
        assert manifest["base_cache_relative_path"] == BASE_CACHE_RELATIVE_PATH
        assert not manifest["base_cache_relative_path"].startswith("/")
        assert "/tmp/" not in manifest["base_cache_relative_path"]

    def test_base_cache_identifiers_are_deterministic_constants(self):
        # 모듈을 다시 import해도(=다른 프로세스/환경에서 실행해도) 항상 같은
        # 값이어야 재현성이 성립한다 — 실행 시점 staging 경로에 의존하지 않음.
        assert BASE_CACHE_ID == "_bars_cache_core87_3y_2026-07-14"
        assert BASE_CACHE_RELATIVE_PATH == os.path.join("logs", BASE_CACHE_ID)


class TestSummarizeSymbolBars:
    def test_ok_status_when_bars_present(self):
        bars = {
            "20260710": {"_cache_provenance": "base_cache"},
            "20260715": {"_cache_provenance": "oos_new"},
            "20260716": {"_cache_provenance": "oos_new"},
        }
        result = summarize_symbol_bars("005930", bars, OOS_START_DATE)
        assert result.fetch_status == "ok"
        assert result.merge_stats.base_bar_count == 1
        assert result.merge_stats.new_bar_added_count == 2
        assert result.new_first_trade_date == "20260715"
        assert result.new_last_trade_date == "20260716"
        assert result.duplicate_within_new_fetch_count is None  # 재수집 없이는 알 수 없음

    def test_failed_status_when_bars_empty(self):
        result = summarize_symbol_bars("005930", {}, OOS_START_DATE)
        assert result.fetch_status == "failed"
        assert result.error_summary is not None

    def test_manifest_regenerated_flag_and_ready_for_oos_contract_preserved(self):
        results = [
            summarize_symbol_bars(
                "A", {"20260715": {"_cache_provenance": "oos_new"}}, OOS_START_DATE
            ),
            summarize_symbol_bars("B", {}, OOS_START_DATE),  # 실패
        ]
        ready, notes = determine_ready_for_oos(results, {"A", "B"})
        assert ready is False
        assert "B" in notes

        manifest = build_manifest(
            cache_id="x",
            generated_at_kst_iso="2026-08-24T16:00:00+09:00",
            generated_at_utc_iso="2026-08-24T07:00:00+00:00",
            base_cache_id=BASE_CACHE_ID,
            base_cache_relative_path=BASE_CACHE_RELATIVE_PATH,
            base_cache_as_of_date="2026-07-14",
            oos_start_date=OOS_START_DATE,
            oos_end_date="20260824",
            universe_symbols=["A", "B"],
            benchmark_symbol="069500",
            results=results,
            ready_for_oos=ready,
            ready_for_oos_notes=notes,
            manifest_regenerated_from_existing_cache=True,
        )
        assert manifest["manifest_regenerated_from_existing_cache"] is True
        assert manifest["ready_for_oos"] is False
        assert manifest["kis_call_kind"] == (
            "no_kis_call (이 manifest는 기존 수집 결과 파일만 다시 읽어 "
            "재생성됐다 — KIS를 재호출하지 않았다)"
        )
        assert manifest["totals"]["duplicate_within_new_fetch_count_unavailable_for_some_symbols"] is True
