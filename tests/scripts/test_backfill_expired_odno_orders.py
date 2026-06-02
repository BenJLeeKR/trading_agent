"""Tests for ``scripts.backfill_expired_odno_orders``.

검증 범위
---------
1. ``_parse_args()`` — CLI 인자 파싱 정확성
2. ``_classify()`` — verify_order_truth 결과 분류 로직:
   - auto_fix_safe: direct_odno + filled_confirmed/partially_filled_suspected
   - truth_probe_conflict: position-delta verdict / qty mismatch / non-fill ord_stat
   - manual: needs_manual_reconciliation / ODNO 매칭 실패 / error
3. ``_parse_qty()`` — 수량 파싱 헬퍼
"""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from scripts.backfill_expired_odno_orders import (
    CLASS_AUTO_FIX_SAFE,
    CLASS_MANUAL,
    CLASS_TRUTH_PROBE_CONFLICT,
    KIS_FILL_CODES,
    VERDICT_EXPIRED,
    VERDICT_FILLED,
    VERDICT_MANUAL,
    VERDICT_PAPER_MISSING,
    VERDICT_PARTIAL,
    VERDICT_POSITION_DELTA_FILLED,
    VERDICT_POSITION_DELTA_PARTIAL,
    _classify,
    _parse_args,
    _parse_qty,
)


# ---------------------------------------------------------------------------
# _parse_qty 테스트
# ---------------------------------------------------------------------------


class TestParseQty:
    def test_int(self):
        assert _parse_qty(10) == 10

    def test_float_string(self):
        assert _parse_qty("10.0") == 10

    def test_none(self):
        assert _parse_qty(None) is None

    def test_empty_string(self):
        assert _parse_qty("") is None

    def test_negative(self):
        assert _parse_qty(-5) == -5

    def test_zero(self):
        assert _parse_qty(0) == 0


# ---------------------------------------------------------------------------
# _parse_args 테스트
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_defaults(self):
        """기본값 확인."""
        args = _parse_args([])
        assert args.from_date == "2026-05-28"
        assert args.to_date == "2026-05-29"
        assert args.dry_run is False
        assert args.json is False
        assert args.order_ids is None
        assert args.log_file is not None

    def test_dry_run(self):
        """--dry-run 플래그."""
        args = _parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_json(self):
        """--json 플래그."""
        args = _parse_args(["--json"])
        assert args.json is True

    def test_from_date(self):
        """--from-date 인자."""
        args = _parse_args(["--from-date", "2026-06-01"])
        assert args.from_date == "2026-06-01"

    def test_to_date(self):
        """--to-date 인자."""
        args = _parse_args(["--to-date", "2026-06-02"])
        assert args.to_date == "2026-06-02"

    def test_order_ids(self):
        """--order-ids 인자 (공백 구분)."""
        uid1 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        uid2 = "ffffffff-gggg-hhhh-iiii-jjjjjjjjjjjj"
        args = _parse_args(["--order-ids", uid1, uid2])
        assert args.order_ids == [uid1, uid2]

    def test_log_file(self):
        """--log-file 인자."""
        args = _parse_args(["--log-file", "/tmp/test.log"])
        assert args.log_file == "/tmp/test.log"


# ---------------------------------------------------------------------------
# _classify 테스트 헬퍼
# ---------------------------------------------------------------------------


def _make_result(
    verdict: str = VERDICT_FILLED,
    matched: bool = True,
    match_method: str = "direct_odno",
    match_verdict: str | None = None,
    kis_ord_stat: str = "21",
    kis_ccld_qty: Any = 10,
    kis_order_qty: Any = 10,
    position_delta: Any = 0,
    position_verdict: str = "",
    position_reason: str = "",
    error: str | None = None,
) -> dict[str, Any]:
    """``verify_order_truth.py`` JSON 출력을 모방한 fixture."""
    match: dict[str, Any] = {
        "matched": matched,
        "match_method": match_method if matched else "",
        "kis_ord_stat": kis_ord_stat,
        "kis_ccld_qty": kis_ccld_qty,
        "kis_order_qty": kis_order_qty,
        "position_delta": position_delta,
        "position_verdict": position_verdict,
        "position_reason": position_reason,
    }
    if match_verdict is not None:
        match["verdict"] = match_verdict
    else:
        match["verdict"] = verdict

    result: dict[str, Any] = {
        "verdict": verdict,
        "match": match,
    }
    if error is not None:
        result["error"] = error
    return result


# ---------------------------------------------------------------------------
# _classify — auto_fix_safe
# ---------------------------------------------------------------------------


class TestClassifyAutoFixSafe:
    def test_filled_confirmed_direct_odno(self):
        """filled_confirmed + direct_odno → auto_fix_safe → FILLED."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            kis_ccld_qty=10,
            kis_order_qty=10,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_AUTO_FIX_SAFE
        assert target_status == "filled"
        assert reason is None
        assert conflict_type is None  # auto_fix_safe는 conflict_type=None

    def test_partially_filled_suspected_direct_odno(self):
        """partially_filled_suspected + direct_odno → auto_fix_safe → PARTIALLY_FILLED."""
        result = _make_result(
            verdict=VERDICT_PARTIAL,
            match_method="direct_odno",
            kis_ccld_qty=5,
            kis_order_qty=10,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_AUTO_FIX_SAFE
        assert target_status == "partially_filled"
        assert reason is None
        assert conflict_type is None

    def test_expired_confirmed_direct_odno(self):
        """expired_confirmed + direct_odno → auto_fix_safe → target_status=None (already expired)."""
        result = _make_result(
            verdict=VERDICT_EXPIRED,
            match_method="direct_odno",
            kis_ccld_qty=0,
            kis_order_qty=10,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_AUTO_FIX_SAFE
        assert target_status is None
        assert reason is not None  # "Already expired confirmed"
        assert conflict_type is None

    def test_ccld_qty_none_matches_requested_quantity(self):
        """kis_ccld_qty=None + requested_quantity=10 → auto_fix_safe (None 처리 안전)."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            kis_ccld_qty=None,
            kis_order_qty=10,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_AUTO_FIX_SAFE
        assert target_status == "filled"
        assert conflict_type is None

    def test_requested_quantity_none_handled(self):
        """requested_quantity=None → auto_fix_safe (None 처리 안전)."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            kis_ccld_qty=10,
            kis_order_qty=10,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=None)
        assert classification == CLASS_AUTO_FIX_SAFE
        assert target_status == "filled"
        assert conflict_type is None


# ---------------------------------------------------------------------------
# _classify — truth_probe_conflict
# ---------------------------------------------------------------------------


class TestClassifyTruthProbeConflict:
    def test_position_delta_filled_verdict(self):
        """position_delta_filled + KIS cross-check 실패 → truth_probe_conflict."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            position_verdict=VERDICT_POSITION_DELTA_FILLED,
            position_delta=15,
            kis_ord_stat="00",   # KIS_FILL_CODES에 없음 → cross-check 실패
            kis_ccld_qty=0,      # 체결 0건
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_TRUTH_PROBE_CONFLICT
        assert target_status is None
        assert "position_verdict" in reason
        assert conflict_type == "position_delta_filled"

    def test_position_delta_filled_with_kis_confirm(self):
        """position_delta_filled + KIS cross-check 성공 → auto_fix_safe."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            position_verdict=VERDICT_POSITION_DELTA_FILLED,
            position_delta=15,
            kis_ord_stat="21",   # KIS_FILL_CODES에 포함
            kis_ccld_qty=10,     # req_qty=10과 같음 → 충족
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_AUTO_FIX_SAFE
        assert target_status is not None
        assert conflict_type is None  # cross-check 통과 → conflict 아님

    def test_position_delta_partial_verdict(self):
        """position_delta_partial → truth_probe_conflict."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            position_verdict=VERDICT_POSITION_DELTA_PARTIAL,
            position_delta=5,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_TRUTH_PROBE_CONFLICT
        assert target_status is None
        assert conflict_type == "position_delta_partial"

    def test_match_verdict_paper_missing(self):
        """match.verdict == paper_truth_missing → truth_probe_conflict."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            match_verdict=VERDICT_PAPER_MISSING,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_TRUTH_PROBE_CONFLICT
        assert target_status is None
        assert conflict_type == "paper_truth_missing"

    def test_match_verdict_position_delta_filled(self):
        """match.verdict == position_delta_filled → truth_probe_conflict."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            match_verdict=VERDICT_POSITION_DELTA_FILLED,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_TRUTH_PROBE_CONFLICT
        assert target_status is None
        assert conflict_type == "paper_truth_missing"  # match_verdict가 먼저 conflict_type 결정

    def test_kis_ccld_qty_mismatch(self):
        """kis_ccld_qty(5) != requested_quantity(10) → truth_probe_conflict."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            kis_ccld_qty=5,
            kis_order_qty=10,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_TRUTH_PROBE_CONFLICT
        assert target_status is None
        assert "qty mismatch" in (reason or "")
        assert conflict_type == "qty_mismatch"

    def test_non_fill_ord_stat_with_ccld_qty(self):
        """ORD_STAT non-fill(00) + ccld_qty>0 → truth_probe_conflict."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            kis_ord_stat="00",  # 접수 상태, fill code 아님
            kis_ccld_qty=5,
            kis_order_qty=10,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_TRUTH_PROBE_CONFLICT
        assert target_status is None
        assert conflict_type == "ord_stat_conflict"

    def test_position_delta_without_position_verdict(self):
        """position_delta>0 but position_verdict empty → truth_probe_conflict."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            position_delta=10,
            position_verdict="",  # no position verdict
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_TRUTH_PROBE_CONFLICT
        assert target_status is None
        assert conflict_type == "position_delta_no_verdict"

    def test_qty_mismatch_in_auto_fix_path(self):
        """auto_fix_safe 조건에 들어갔는데도 qty mismatch가 있으면 conflict."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            kis_ccld_qty=3,
            kis_order_qty=10,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        # 먼저 conflict 조건에 걸림 (2d: qty mismatch)
        assert classification == CLASS_TRUTH_PROBE_CONFLICT
        assert conflict_type == "qty_mismatch"

    def test_multiple_conflicts(self):
        """여러 conflict 조건이 동시에 있어도 정상 분류."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            match_verdict=VERDICT_PAPER_MISSING,
            position_verdict=VERDICT_POSITION_DELTA_PARTIAL,
            kis_ccld_qty=3,
            kis_order_qty=10,
            position_delta=5,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_TRUTH_PROBE_CONFLICT
        assert target_status is None
        assert reason is not None
        # 여러 사유가 모두 포함되어야 함
        assert VERDICT_PAPER_MISSING in (reason or "")
        assert VERDICT_POSITION_DELTA_PARTIAL in (reason or "")
        # conflict_type 결정 순서: 2a(position_verdict) → 2b(match_verdict) → ...
        # position_verdict=VERDICT_POSITION_DELTA_PARTIAL이 2a에서 먼저 conflict_type 설정
        assert conflict_type == "position_delta_partial"


# ---------------------------------------------------------------------------
# _classify — manual
# ---------------------------------------------------------------------------


class TestClassifyManual:
    def test_error_in_result(self):
        """error 필드가 있으면 manual."""
        result = _make_result(error="API call failed")
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_MANUAL
        assert target_status is None
        assert "Error" in (reason or "")
        assert conflict_type is None

    def test_needs_manual_reconciliation_verdict(self):
        """verdict=needs_manual_reconciliation → manual."""
        result = _make_result(
            verdict=VERDICT_MANUAL,
            matched=False,
            match_verdict=VERDICT_MANUAL,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_MANUAL
        assert target_status is None
        assert conflict_type is None

    def test_odno_not_matched(self):
        """ODNO 매칭 실패 (matched=False) → manual."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            matched=False,
            match_method="",
            match_verdict=VERDICT_MANUAL,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_MANUAL
        assert target_status is None
        assert conflict_type is None

    def test_not_direct_odno_match_method(self):
        """match_method != direct_odno → manual."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="symbol_side_fallback",
            match_verdict=VERDICT_FILLED,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_MANUAL
        assert target_status is None
        assert "symbol_side_fallback" in (reason or "")
        assert conflict_type is None

    def test_match_is_not_dict(self):
        """match 필드가 dict가 아니면 manual."""
        result: dict[str, Any] = {
            "verdict": VERDICT_FILLED,
            "match": "not a dict",
        }
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_MANUAL
        assert target_status is None
        assert conflict_type is None

    def test_unexpected_verdict(self):
        """예상치 못한 verdict + direct_odno → manual."""
        result = _make_result(
            verdict="some_unknown_verdict",
            match_method="direct_odno",
            match_verdict="some_unknown_verdict",
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
        assert classification == CLASS_MANUAL
        assert target_status is None
        assert conflict_type is None


# ---------------------------------------------------------------------------
# _classify — 경계 케이스
# ---------------------------------------------------------------------------


class TestClassifyEdgeCases:
    def test_ccld_qty_zero_ok_with_fill_code(self):
        """kis_ccld_qty=0 with fill code(21) → auto_fix_safe (매칭 성공, qty 일치)."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            kis_ord_stat="21",
            kis_ccld_qty=0,
            kis_order_qty=10,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=0)
        # fill code 21, ccld=0, req_qty=0 → qty match
        assert classification in (CLASS_AUTO_FIX_SAFE,)
        assert conflict_type is None

    def test_ccld_qty_string_number_parsing(self):
        """kis_ccld_qty가 문자열 숫자여도 정상 파싱."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            kis_ccld_qty="10",
            kis_order_qty="10",
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity="10")
        assert classification == CLASS_AUTO_FIX_SAFE
        assert conflict_type is None

    def test_float_quantity(self):
        """requested_quantity가 float여도 정상 처리."""
        result = _make_result(
            verdict=VERDICT_FILLED,
            match_method="direct_odno",
            kis_ccld_qty=10,
            kis_order_qty=10,
        )
        classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10.0)
        assert classification == CLASS_AUTO_FIX_SAFE
        assert conflict_type is None

    def test_all_kis_fill_codes_auto_fix(self):
        """모든 KIS fill 코드(21,22,11,12)에서 auto_fix_safe."""
        for fill_code in KIS_FILL_CODES:
            result = _make_result(
                verdict=VERDICT_FILLED,
                match_method="direct_odno",
                kis_ord_stat=fill_code,
                kis_ccld_qty=10,
                kis_order_qty=10,
            )
            classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
            assert classification == CLASS_AUTO_FIX_SAFE, f"fill_code={fill_code} should be auto_fix_safe"
            assert conflict_type is None

    def test_all_kis_fill_codes_conflict_with_mismatch(self):
        """모든 KIS fill 코드에서 qty mismatch → truth_probe_conflict."""
        for fill_code in KIS_FILL_CODES:
            result = _make_result(
                verdict=VERDICT_FILLED,
                match_method="direct_odno",
                kis_ord_stat=fill_code,
                kis_ccld_qty=5,
                kis_order_qty=10,
            )
            classification, target_status, reason, conflict_type = _classify(result, requested_quantity=10)
            assert classification == CLASS_TRUTH_PROBE_CONFLICT, f"fill_code={fill_code} with mismatch should be conflict"
            assert conflict_type == "qty_mismatch", f"fill_code={fill_code} conflict_type should be qty_mismatch"
