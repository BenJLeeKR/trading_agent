"""KIS ``inquire-daily-ccld`` raw row → 범용 정규화 모델.

설계 근거: docs/00_foundational_design/detailed_design/14_kis_fill_
normalization_and_incremental_interpretation_design.md 3.1절.

이 모듈은 순수(stateless) 변환만 수행한다 — repository/DB 접근이 없다
(``brokers/`` 계층은 ``services/``/``repositories/``를 import하지 않는다,
`src/AGENTS.md` 계층 경계). 시장가/지정가, 부분체결/전체체결을 구분하는
분기는 두지 않는다 — 어떤 주문에서 왔든 같은 필드 후보 목록으로 정규화한다.

``cumulative_filled_quantity``라는 이름 자체가 이 값의 성격을 명시한다 —
KIS `TOT_CCLD_QTY`는 "이번 체결분"이 아니라 "이 주문이 지금까지 누적으로
체결된 수량"이다(read-only 운영 조사로 실증 확인, 설계 문서 1.2절). 이
값을 증분(fill)으로 바꾸는 책임은 이 모듈이 아니라 누적→증분 해석 계층
(``agent_trading.services.kis_fill_incremental_resolver``)에 있다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from agent_trading.brokers.koreainvestment.kis_field_mapping import (
    AVERAGE_PRICE_FIELDS,
    CUMULATIVE_QTY_FIELDS,
    FILL_TIME_FIELDS,
    ORDER_STATUS_FIELDS,
    get_kis_field,
    get_kis_value,
)
from agent_trading.domain.enums import OrderSide

# ── side 코드 매핑 (KIS SLL_BUY_DVSN_CD: 01=매도, 02=매수) ──────────────
_SELL_CODE = "01"
_BUY_CODE = "02"


@dataclass(slots=True, frozen=True)
class NormalizedKisFillObservation:
    """``inquire-daily-ccld`` raw item 1건을 정규화한 결과."""

    broker_native_order_id: str
    symbol: str
    side: OrderSide | None
    ordered_quantity: Decimal | None
    cumulative_filled_quantity: Decimal | None
    average_fill_price: Decimal | None
    fill_time_candidate: str | None
    order_status_raw: str | None
    cancel_yn: str | None
    rvse_yn: str | None
    broker_fill_id_candidate: str | None
    raw_field_fingerprint: str
    is_parseable: bool


def _to_decimal(raw: Any) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _side_from_code(code: str | None) -> OrderSide | None:
    if code == _SELL_CODE:
        return OrderSide.SELL
    if code == _BUY_CODE:
        return OrderSide.BUY
    return None


def _build_fingerprint(item: dict[str, Any]) -> str:
    """원문 값이 아니라 "키 존재 여부"만 해시한다 — 로그에 원문을 남기지
    않으면서, 이번 응답의 필드 구성이 이전과 달라졌는지 관측하기 위함."""
    present_keys = sorted(k for k, v in item.items() if v not in (None, ""))
    digest = hashlib.sha256("|".join(present_keys).encode("utf-8")).hexdigest()
    return digest[:16]


def normalize_kis_fill_observation(item: dict[str, Any]) -> NormalizedKisFillObservation:
    """KIS raw row 1건을 :class:`NormalizedKisFillObservation`으로 변환한다.

    필드 조회는 대소문자 무관 + 후보 키 fallback으로 통일한다(paper가
    ``tot_ccld_qty``를 주든 live가 ``CCLD_QTY``를 주든 같은 코드로 처리).
    필수 필드(주문번호/종목코드)가 없으면 ``is_parseable=False``로
    표시한다 — 추측으로 채우지 않는다.
    """
    odno = str(get_kis_field(item, "ODNO", "")).strip()
    pdno = str(get_kis_field(item, "PDNO", "")).strip()
    side_code = str(get_kis_field(item, "SLL_BUY_DVSN_CD", "")).strip()

    is_parseable = bool(odno) and bool(pdno)

    return NormalizedKisFillObservation(
        broker_native_order_id=odno,
        symbol=pdno,
        side=_side_from_code(side_code),
        ordered_quantity=_to_decimal(get_kis_field(item, "ORD_QTY", None)),
        cumulative_filled_quantity=_to_decimal(
            get_kis_value(item, *CUMULATIVE_QTY_FIELDS, default=None),
        ),
        average_fill_price=_to_decimal(
            get_kis_value(item, *AVERAGE_PRICE_FIELDS, default=None),
        ),
        fill_time_candidate=(
            str(get_kis_value(item, *FILL_TIME_FIELDS, default="")).strip() or None
        ),
        order_status_raw=(
            str(get_kis_value(item, *ORDER_STATUS_FIELDS, default="")).strip() or None
        ),
        cancel_yn=str(get_kis_field(item, "CNCL_YN", "")).strip() or None,
        rvse_yn=str(get_kis_field(item, "RVSE_YN", "")).strip() or None,
        broker_fill_id_candidate=str(get_kis_field(item, "CCLD_NUM", "")).strip() or None,
        raw_field_fingerprint=_build_fingerprint(item),
        is_parseable=is_parseable,
    )
