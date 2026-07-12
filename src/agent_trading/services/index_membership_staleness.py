"""UNIV-4: 지수 편입(index membership) 데이터 staleness 감시.

``[DESIGN] universe_sourcing_momentum_overlay_enablement_v1.md`` §2.3의
축소안 — KIS에 지수 구성종목(constituents) 전체 목록 API가 확인되지 않아
(현재 ``inquire_index_category_price``는 업종별 시세만 제공, 종목 리스트가
아니다) 자동 갱신 파이프라인 대신, 기존 수동 업로드 절차
(``[RUNBOOK] index_membership_source_package_apply.md``)의 마지막 반영
시각이 오래됐는지 **읽기 전용으로 감시만** 한다. 주문 경로/게이트 로직에는
어떤 영향도 주지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

DEFAULT_STALENESS_THRESHOLD_DAYS = 21
"""설계 문서 §2.3 — 지수 리밸런싱은 분기 단위이므로 21일을 기본 임계값으로 둔다."""


@dataclass(frozen=True, slots=True)
class IndexMembershipStalenessReport:
    """지수 편입 데이터의 신선도 평가 결과 (관측 전용)."""

    latest_effective_from: date | None
    as_of: date
    age_days: int | None
    threshold_days: int
    is_stale: bool


def evaluate_index_membership_staleness(
    latest_effective_from: date | None,
    *,
    as_of: date,
    threshold_days: int = DEFAULT_STALENESS_THRESHOLD_DAYS,
) -> IndexMembershipStalenessReport:
    """가장 최근 membership 반영 시각을 기준으로 staleness를 평가한다.

    ``latest_effective_from``이 ``None``이면(데이터 자체가 없음) 무조건
    stale로 판정한다 — "데이터 없음"과 "오래된 데이터"를 구분하지 않고
    둘 다 감시 대상으로 취급하는 보수적 규칙이다.
    """
    if latest_effective_from is None:
        return IndexMembershipStalenessReport(
            latest_effective_from=None,
            as_of=as_of,
            age_days=None,
            threshold_days=threshold_days,
            is_stale=True,
        )

    age_days = (as_of - latest_effective_from).days
    return IndexMembershipStalenessReport(
        latest_effective_from=latest_effective_from,
        as_of=as_of,
        age_days=age_days,
        threshold_days=threshold_days,
        is_stale=age_days > threshold_days,
    )
