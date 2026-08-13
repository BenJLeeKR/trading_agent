"""KIS REST 응답 필드 조회 공통 헬퍼.

``inquire-daily-ccld``(VTTC0081R/TTTC0081R) 응답은 환경(paper/live)에 따라
키 대소문자가 혼용되고(``ODNO`` vs ``odno``), 체결수량/평균단가 필드명 자체가
달라질 수 있다(``CCLD_QTY``/``CCLD_UNPR``를 기대했지만 실제로는
``TOT_CCLD_QTY``/``AVG_PRVS``만 채워진 응답이 read-only 운영 조사로 확인됨 —
설계 근거: docs/00_foundational_design/detailed_design/14_kis_fill_
normalization_and_incremental_interpretation_design.md 1.2절).

이 모듈은 ``KISRestClient._get_kis_field()``와
``fill_history_sync._get_kis_value()``에 각각 따로 존재하던 동일한 로직을
공통화한 것이다 — 두 곳이 서로 다른 순서/규칙을 쓰게 되는 drift를 막는다.
후보 키 목록(``CUMULATIVE_QTY_FIELDS`` 등)은 ``fill_history_sync.py``가
이미 운영에서 쓰던 순서를 그대로 따른다(새로 순서를 정하지 않는다).
"""

from __future__ import annotations

from typing import Any

# ── 필드별 후보 키 목록(우선순위 순) ──────────────────────────────────────
# 환경별 `if paper/live` 분기가 아니라 "어떤 후보가 먼저 매칭되는가"로
# paper/live 차이를 흡수한다(설계 문서 8절).
CUMULATIVE_QTY_FIELDS: tuple[str, ...] = ("TOT_CCLD_QTY", "CCLD_QTY")
AVERAGE_PRICE_FIELDS: tuple[str, ...] = ("AVG_PRVS", "CCLD_UNPR")
FILL_TIME_FIELDS: tuple[str, ...] = ("CCLD_TMD", "INFM_TMD")
ORDER_STATUS_FIELDS: tuple[str, ...] = ("ORD_STAT", "CCLD_CNDT_NAME", "ORD_DVSN_NAME")


def get_kis_field(item: dict[str, Any], field: str, default: Any = "") -> Any:
    """KIS 응답 필드를 대소문자 무관하게 읽는다.

    KIS API는 응답 키를 대문자(``ODNO``) 또는 소문자(``odno``)로 혼용하여
    반환하므로, 두 케이스를 모두 시도한다.
    """
    value = item.get(field)
    if value is not None and value != "":
        return value
    return item.get(field.lower(), default)


def get_kis_value(item: dict[str, Any], *fields: str, default: Any = "") -> Any:
    """후보 키 목록을 순서대로 시도해 첫 매칭값을 반환한다(대소문자 무관).

    예: ``get_kis_value(item, "TOT_CCLD_QTY", "CCLD_QTY", default="0")``는
    ``tot_ccld_qty``/``TOT_CCLD_QTY``를 먼저 찾고, 없으면
    ``ccld_qty``/``CCLD_QTY``로 fallback한다.
    """
    for field_name in fields:
        value = get_kis_field(item, field_name, None)
        if value not in (None, ""):
            return value
    return default


def has_any_kis_field(item: dict[str, Any], *fields: str) -> bool:
    """후보 키 중 하나라도 값이 채워져 있으면 True."""
    return any(get_kis_field(item, f, None) not in (None, "") for f in fields)
