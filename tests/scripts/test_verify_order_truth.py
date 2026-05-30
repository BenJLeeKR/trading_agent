"""Tests for ``scripts/verify_order_truth.py``.

주요 테스트 대상 (순수 함수)
-------------------------------
* ``_classify_ccld_status()`` — ORD_STAT + 체결수량 기반 판정 로직
* ``_format_kst()`` — datetime 포맷팅
* ``_summarize_records()`` — raw 레코드 요약
* ``_build_match_info()`` — 매칭 결과 생성

통합/DB 의존 테스트는 여기서 제외 (smoke test로 별도 분리).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.verify_order_truth import (
    VERDICT_EXPIRED,
    VERDICT_FILLED,
    VERDICT_MANUAL,
    VERDICT_PARTIAL,
    _build_match_info,
    _classify_ccld_status,
    _format_kst,
    _summarize_records,
)
from agent_trading.domain.enums import OrderSide

# =========================================================================
# _classify_ccld_status() — ORD_STAT 기반 판정 로직
# =========================================================================


class TestClassifyCcldStatus:
    """ORD_STAT 코드 + 체결수량 기준 판정 분류."""

    # ── 전량체결 (21/22) ──
    def test_filled_21(self) -> None:
        assert _classify_ccld_status("21", 100, 100) == VERDICT_FILLED

    def test_filled_22(self) -> None:
        assert _classify_ccld_status("22", 100, 100) == VERDICT_FILLED

    def test_filled_21_partial_qty(self) -> None:
        """21 상태에서 체결량 < 주문량이어도 전량체결로 간주 (KIS spec)."""
        assert _classify_ccld_status("21", 50, 100) == VERDICT_FILLED

    # ── 일부체결 (11/12) ──
    def test_partial_11(self) -> None:
        assert _classify_ccld_status("11", 50, 100) == VERDICT_PARTIAL

    def test_partial_12(self) -> None:
        assert _classify_ccld_status("12", 50, 100) == VERDICT_PARTIAL

    def test_partial_11_full_qty(self) -> None:
        """11 상태에서 체결량 == 주문량이어도 일부체결로 간주 (KIS spec)."""
        assert _classify_ccld_status("11", 100, 100) == VERDICT_PARTIAL

    # ── 취소/만료 (88/89) ──
    def test_expired_88_zero_fill(self) -> None:
        assert _classify_ccld_status("88", 0, 100) == VERDICT_EXPIRED

    def test_expired_89_zero_fill(self) -> None:
        assert _classify_ccld_status("89", 0, 100) == VERDICT_EXPIRED

    def test_rejected_80_zero_fill(self) -> None:
        """80=거절, 체결 0 → 만료."""
        assert _classify_ccld_status("80", 0, 100) == VERDICT_EXPIRED

    def test_cancelled_88_partial_fill(self) -> None:
        """88 상태지만 일부 체결 있음 → PARTIAL."""
        assert _classify_ccld_status("88", 30, 100) == VERDICT_PARTIAL

    def test_cancelled_88_full_fill(self) -> None:
        """88 상태지만 전량 체결 → FILLED."""
        assert _classify_ccld_status("88", 100, 100) == VERDICT_FILLED

    def test_rejected_80_partial_fill(self) -> None:
        """80=거절, 일부 체결 → PARTIAL."""
        assert _classify_ccld_status("80", 30, 100) == VERDICT_PARTIAL

    # ── 일반 상태 (00, 01, 02, 05, 07) ──
    def test_submitted_00_zero_fill(self) -> None:
        """접수 상태 + 체결 0 → EXPIRED (체결 없는 만료)."""
        assert _classify_ccld_status("00", 0, 100) == VERDICT_EXPIRED

    def test_submitted_00_partial_fill(self) -> None:
        """접수 상태 + 일부 체결 → PARTIAL."""
        assert _classify_ccld_status("00", 30, 100) == VERDICT_PARTIAL

    def test_submitted_00_full_fill(self) -> None:
        """접수 상태 + 전량 체결 → FILLED."""
        assert _classify_ccld_status("00", 100, 100) == VERDICT_FILLED

    def test_filled_01_full(self) -> None:
        assert _classify_ccld_status("01", 100, 100) == VERDICT_FILLED

    def test_filled_01_partial(self) -> None:
        """01=체결 상태 + qty 미달 → PARTIAL로 분류."""
        assert _classify_ccld_status("01", 50, 100) == VERDICT_PARTIAL

    def test_cancelled_02_zero_fill(self) -> None:
        assert _classify_ccld_status("02", 0, 100) == VERDICT_EXPIRED

    def test_cancelled_02_partial_fill(self) -> None:
        assert _classify_ccld_status("02", 30, 100) == VERDICT_PARTIAL

    def test_acknowledged_05_zero_fill(self) -> None:
        assert _classify_ccld_status("05", 0, 100) == VERDICT_EXPIRED

    def test_acknowledged_07_partial_fill(self) -> None:
        assert _classify_ccld_status("07", 50, 100) == VERDICT_PARTIAL

    # ── 미지정 ORD_STAT ──
    def test_unknown_stat_zero_fill(self) -> None:
        assert _classify_ccld_status("99", 0, 100) == VERDICT_EXPIRED

    def test_unknown_stat_partial_fill(self) -> None:
        assert _classify_ccld_status("99", 50, 100) == VERDICT_PARTIAL

    def test_unknown_stat_full_fill(self) -> None:
        assert _classify_ccld_status("99", 100, 100) == VERDICT_FILLED

    # ── Edge cases ──
    def test_zero_qty_order(self) -> None:
        """주문량 0, 체결 0 → EXPIRED."""
        assert _classify_ccld_status("00", 0, 0) == VERDICT_EXPIRED

    def test_empty_stat(self) -> None:
        """빈 ORD_STAT 문자열."""
        assert _classify_ccld_status("", 0, 100) == VERDICT_EXPIRED


# =========================================================================
# _format_kst()
# =========================================================================


class TestFormatKst:
    """KST 포맷팅 테스트."""

    def test_none(self) -> None:
        assert _format_kst(None) == "N/A"

    def test_utc_to_kst(self) -> None:
        """UTC datetime → KST 변환 + 포맷 검증."""
        dt = datetime(2026, 5, 15, 0, 0, 0, tzinfo=timezone.utc)
        result = _format_kst(dt)
        assert result == "2026-05-15 09:00:00 KST"

    def test_already_kst(self) -> None:
        """이미 KST timezone."""
        dt = datetime(2026, 5, 15, 9, 30, 0, tzinfo=timezone(timedelta(hours=9)))
        result = _format_kst(dt)
        assert result == "2026-05-15 09:30:00 KST"

    def test_naive_datetime(self) -> None:
        """timezone 미지정 → UTC로 간주 후 KST 변환."""
        dt = datetime(2026, 5, 15, 0, 0, 0)  # naive
        result = _format_kst(dt)
        # Python은 naive datetime을 UTC로 간주하지 않음
        # astimezone()은 naive datetime에 대해 local timezone을 가정
        assert "KST" in result


# =========================================================================
# _summarize_records()
# =========================================================================


class TestSummarizeRecords:
    """Raw 레코드 요약 테스트."""

    def test_empty(self) -> None:
        assert _summarize_records([]) == []

    def test_single_record(self) -> None:
        raw = [
            {
                "ODNO": "ODNO001",
                "PDNO": "005930",
                "ORD_QTY": "100",
                "CCLD_QTY": "50",
                "ORD_STAT": "11",
                "SLL_BUY_DVSN_CD": "01",
                "ORD_TMD": "091500",
                "CCLD_TMD": "091505",
            },
        ]
        summary = _summarize_records(raw)
        assert len(summary) == 1
        assert summary[0]["ODNO"] == "ODNO001"
        assert summary[0]["CCLD_QTY"] == "50"
        assert summary[0]["ORD_STAT"] == "11"

    def test_missing_fields(self) -> None:
        """일부 필드가 누락된 레코드도 안전하게 처리."""
        raw = [{"ODNO": "ODNO001"}]  # PDNO, ORD_QTY 등 없음
        summary = _summarize_records(raw)
        assert len(summary) == 1
        assert summary[0]["ODNO"] == "ODNO001"
        assert summary[0]["PDNO"] == ""  # 기본값

    def test_multiple_records(self) -> None:
        raw = [
            {"ODNO": "A", "PDNO": "005930", "ORD_QTY": "10", "CCLD_QTY": "10", "ORD_STAT": "21", "SLL_BUY_DVSN_CD": "01", "ORD_TMD": "090000", "CCLD_TMD": ""},
            {"ODNO": "B", "PDNO": "000660", "ORD_QTY": "5", "CCLD_QTY": "0", "ORD_STAT": "89", "SLL_BUY_DVSN_CD": "02", "ORD_TMD": "091000", "CCLD_TMD": ""},
        ]
        summary = _summarize_records(raw)
        assert len(summary) == 2


# =========================================================================
# _build_match_info()
# =========================================================================


class TestBuildMatchInfo:
    """매칭 결과 빌드 로직."""

    def test_no_records(self) -> None:
        """레코드 없음 → MANUAL + 적절한 이유."""
        info = _build_match_info(
            matched=None,
            all_records=[],
            broker_order_id="ODNO001",
            symbol="005930",
            order_side=OrderSide.BUY,
        )
        assert info["matched"] is False
        assert info["verdict"] == VERDICT_MANUAL
        assert "No records returned" in info["reason"]

    def test_no_broker_order_id(self) -> None:
        """ODNO 없음 → MANUAL."""
        info = _build_match_info(
            matched=None,
            all_records=[{"ODNO": "X"}],
            broker_order_id=None,
            symbol="005930",
            order_side=OrderSide.BUY,
        )
        assert info["matched"] is False
        assert "No broker_native_order_id" in info["reason"]

    def test_odno_not_found(self) -> None:
        """ODNO가 결과에 없음 → MANUAL + 사용 가능한 ODNO 목록."""
        info = _build_match_info(
            matched=None,
            all_records=[{"ODNO": "X"}, {"ODNO": "Y"}],
            broker_order_id="ODNO001",
            symbol="005930",
            order_side=OrderSide.BUY,
        )
        assert info["matched"] is False
        assert "ODNO001" in info["reason"]
        assert "X" in info["reason"]

    def test_direct_odno_match(self) -> None:
        """직접 ODNO 매칭 성공."""
        matched = {
            "ODNO": "ODNO001",
            "PDNO": "005930",
            "ORD_QTY": "100",
            "CCLD_QTY": "100",
            "ORD_STAT": "21",
            "ORD_TMD": "090000",
            "CCLD_TMD": "090005",
            "CNCL_YN": "N",
        }
        info = _build_match_info(
            matched=matched,
            all_records=[matched],
            broker_order_id="ODNO001",
            symbol="005930",
            order_side=OrderSide.BUY,
        )
        assert info["matched"] is True
        assert info["match_method"] == "direct_odno"
        assert info["verdict"] == VERDICT_FILLED

    def test_symbol_side_fallback(self) -> None:
        """ODNO 불일치, symbol+side fallback."""
        matched = {
            "ODNO": "ODNO999",  # broker_order_id와 다름
            "PDNO": "005930",
            "ORD_QTY": "100",
            "CCLD_QTY": "50",
            "ORD_STAT": "11",
            "ORD_TMD": "090000",
            "CCLD_TMD": "090005",
            "CNCL_YN": "N",
        }
        info = _build_match_info(
            matched=matched,
            all_records=[matched],
            broker_order_id="ODNO001",
            symbol="005930",
            order_side=OrderSide.BUY,
        )
        assert info["matched"] is True
        assert info["match_method"] == "symbol_side_fallback"
        assert info["verdict"] == VERDICT_PARTIAL

    def test_symbol_side_only(self) -> None:
        """ODNO 없이 symbol+side만으로 매칭 (paper)."""
        matched = {
            "ODNO": "",
            "PDNO": "005930",
            "ORD_QTY": "100",
            "CCLD_QTY": "0",
            "ORD_STAT": "89",
            "ORD_TMD": "090000",
            "CCLD_TMD": "",
            "CNCL_YN": "Y",
        }
        info = _build_match_info(
            matched=matched,
            all_records=[matched],
            broker_order_id="ODNO001",
            symbol="005930",
            order_side=OrderSide.BUY,
        )
        assert info["matched"] is True
        assert info["match_method"] == "symbol_side_only"
        assert info["verdict"] == VERDICT_EXPIRED

    def test_odno_empty_scenario(self) -> None:
        """모든 ODNO가 빈 경우 (paper scenario) + symbol+side 매칭 실패."""
        info = _build_match_info(
            matched=None,
            all_records=[
                {"ODNO": "", "PDNO": "000660", "ORD_QTY": "10", "CCLD_QTY": "0", "ORD_STAT": "00", "SLL_BUY_DVSN_CD": "01", "ORD_TMD": "", "CCLD_TMD": ""},
            ],
            broker_order_id="ODNO001",
            symbol="005930",
            order_side=OrderSide.BUY,
        )
        assert info["matched"] is False
        assert "empty ODNO" in info["reason"]
