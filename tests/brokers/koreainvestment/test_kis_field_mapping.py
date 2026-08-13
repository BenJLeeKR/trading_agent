"""``kis_field_mapping`` 공통 필드 조회 헬퍼 단위 테스트.

paper 환경에서 확인된 소문자 키 응답과 live에서 가정하는 대문자 키
응답을 모두 다뤄야 한다(설계 문서 14번 8절) — 환경별 분기가 아니라
후보 키 목록 + 대소문자 무관 조회로 흡수되는지 확인한다.
"""

from __future__ import annotations

from agent_trading.brokers.koreainvestment.kis_field_mapping import (
    AVERAGE_PRICE_FIELDS,
    CUMULATIVE_QTY_FIELDS,
    get_kis_field,
    get_kis_value,
    has_any_kis_field,
)


def test_get_kis_field_prefers_uppercase_when_present() -> None:
    item = {"ODNO": "0000015609", "odno": "should-not-be-used"}
    assert get_kis_field(item, "ODNO") == "0000015609"


def test_get_kis_field_falls_back_to_lowercase() -> None:
    item = {"odno": "0000015609"}
    assert get_kis_field(item, "ODNO") == "0000015609"


def test_get_kis_field_returns_default_when_absent() -> None:
    item: dict[str, str] = {}
    assert get_kis_field(item, "ODNO", "fallback") == "fallback"


def test_get_kis_value_tries_candidates_in_order_uppercase() -> None:
    item = {"CCLD_QTY": "5"}
    assert get_kis_value(item, "TOT_CCLD_QTY", "CCLD_QTY", default="0") == "5"


def test_get_kis_value_prefers_first_candidate_when_both_present() -> None:
    item = {"TOT_CCLD_QTY": "259", "CCLD_QTY": "11"}
    assert get_kis_value(item, "TOT_CCLD_QTY", "CCLD_QTY", default="0") == "259"


def test_get_kis_value_lowercase_paper_response_shape() -> None:
    """실제 paper 응답으로 확인된 형태 — tot_ccld_qty/avg_prvs(소문자),
    ccld_qty/ccld_unpr 키 자체가 없음(read-only 운영 조사, 설계 문서 1.2절)."""
    item = {
        "odno": "0000008019",
        "pdno": "007070",
        "tot_ccld_qty": "70",
        "avg_prvs": "26650",
        "sll_buy_dvsn_cd": "01",
    }
    assert get_kis_value(item, *CUMULATIVE_QTY_FIELDS, default="0") == "70"
    assert get_kis_value(item, *AVERAGE_PRICE_FIELDS, default="0") == "26650"


def test_get_kis_value_returns_default_when_no_candidate_present() -> None:
    item = {"unrelated": "x"}
    assert get_kis_value(item, "TOT_CCLD_QTY", "CCLD_QTY", default="0") == "0"


def test_has_any_kis_field_true_when_any_candidate_present() -> None:
    item = {"rvse_yn": "Y"}
    assert has_any_kis_field(item, "RVSE_YN") is True


def test_has_any_kis_field_false_when_absent() -> None:
    item: dict[str, str] = {}
    assert has_any_kis_field(item, "RVSE_YN") is False
