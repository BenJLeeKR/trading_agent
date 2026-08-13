"""``normalize_kis_fill_observation()`` 단위 테스트.

시장가/지정가를 구분하는 분기가 없다는 것을 검증하는 것이 이 테스트
스위트의 핵심 취지다 — 어떤 표본이든 같은 정규화 함수를 거친다.
"""

from __future__ import annotations

from decimal import Decimal

from agent_trading.brokers.koreainvestment.kis_fill_normalization import (
    normalize_kis_fill_observation,
)
from agent_trading.domain.enums import OrderSide

# 실제 paper 응답으로 확인된 형태(read-only 운영 조사, 설계 문서 14번
# 1.2절) — 소문자 키, tot_ccld_qty/avg_prvs, ccld_qty/ccld_unpr 없음.
_REAL_PAPER_RESPONSE_ITEM = {
    "odno": "0000008019",
    "pdno": "007070",
    "ord_qty": "70",
    "ord_unpr": "0",
    "sll_buy_dvsn_cd": "01",
    "ord_dvsn_cd": "01",
    "tot_ccld_qty": "70",
    "tot_ccld_amt": "1865500",
    "avg_prvs": "26650",
    "ord_tmd": "091551",
    "infm_tmd": "091551",
    "cncl_yn": "N",
    "rmn_qty": "0",
}


def test_normalize_real_paper_response_extracts_cumulative_and_price() -> None:
    obs = normalize_kis_fill_observation(_REAL_PAPER_RESPONSE_ITEM)

    assert obs.is_parseable is True
    assert obs.broker_native_order_id == "0000008019"
    assert obs.symbol == "007070"
    assert obs.side == OrderSide.SELL
    assert obs.cumulative_filled_quantity == Decimal("70")
    assert obs.average_fill_price == Decimal("26650")
    assert obs.cancel_yn == "N"
    assert obs.rvse_yn is None


def test_normalize_uppercase_legacy_field_names_still_works() -> None:
    """live에서 가정하는 기존 대문자 필드명(CCLD_QTY/CCLD_UNPR)도 여전히
    지원한다 — 후보 목록의 두 번째 순위."""
    item = {
        "ODNO": "0000099999",
        "PDNO": "005930",
        "SLL_BUY_DVSN_CD": "02",
        "CCLD_QTY": "10",
        "CCLD_UNPR": "70000",
        "CCLD_TMD": "093000",
    }
    obs = normalize_kis_fill_observation(item)

    assert obs.is_parseable is True
    assert obs.side == OrderSide.BUY
    assert obs.cumulative_filled_quantity == Decimal("10")
    assert obs.average_fill_price == Decimal("70000")
    assert obs.fill_time_candidate == "093000"


def test_normalize_missing_odno_is_unparseable() -> None:
    item = {"pdno": "007070", "tot_ccld_qty": "10"}
    obs = normalize_kis_fill_observation(item)
    assert obs.is_parseable is False


def test_normalize_missing_pdno_is_unparseable() -> None:
    item = {"odno": "0000000001", "tot_ccld_qty": "10"}
    obs = normalize_kis_fill_observation(item)
    assert obs.is_parseable is False


def test_normalize_revision_flag_is_surfaced() -> None:
    item = {**_REAL_PAPER_RESPONSE_ITEM, "rvse_yn": "Y"}
    obs = normalize_kis_fill_observation(item)
    assert obs.rvse_yn == "Y"


def test_normalize_cancel_flag_is_surfaced() -> None:
    item = {**_REAL_PAPER_RESPONSE_ITEM, "cncl_yn": "Y"}
    obs = normalize_kis_fill_observation(item)
    assert obs.cancel_yn == "Y"


def test_normalize_missing_cumulative_quantity_is_none_not_zero() -> None:
    """체결수량 필드 자체가 없으면 0으로 추측하지 않고 None으로 남긴다."""
    item = {"odno": "0000000001", "pdno": "007070", "sll_buy_dvsn_cd": "01"}
    obs = normalize_kis_fill_observation(item)
    assert obs.is_parseable is True
    assert obs.cumulative_filled_quantity is None


def test_normalize_fingerprint_changes_when_field_set_changes() -> None:
    """원문 값이 아니라 키 구성이 바뀌면 fingerprint도 바뀐다(로그에 원문을
    남기지 않으면서 응답 스키마 변화를 관측하기 위한 용도)."""
    obs_a = normalize_kis_fill_observation(_REAL_PAPER_RESPONSE_ITEM)
    obs_b = normalize_kis_fill_observation(
        {**_REAL_PAPER_RESPONSE_ITEM, "extra_field": "x"},
    )
    assert obs_a.raw_field_fingerprint != obs_b.raw_field_fingerprint
