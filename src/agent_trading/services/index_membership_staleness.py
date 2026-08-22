"""UNIV-4: 지수 편입(index membership) 데이터 staleness 감시.

``[DESIGN] universe_sourcing_momentum_overlay_enablement_v1.md`` §2.3의
축소안 — KIS에 지수 구성종목(constituents) 전체 목록 API가 확인되지 않아
(현재 ``inquire_index_category_price``는 업종별 시세만 제공, 종목 리스트가
아니다) 자동 갱신 파이프라인 대신, 기존 수동 업로드 절차
(``[RUNBOOK] index_membership_source_package_apply.md``)의 마지막 반영
시각이 오래됐는지 **읽기 전용으로 감시만** 한다. 주문 경로/게이트 로직에는
어떤 영향도 주지 않는다.

기본 정책(2026-08-22 갱신): KOSPI100/KOSPI200/KOSDAQ150/KOSDAQ50 지수
구성종목은 상반기·하반기 정기 변경이 기본 주기이므로, 기존 21일 고정
임계값은 운영 주기와 맞지 않는다. 기본 신선도 경고 기준은 "활성 membership의
최신 as_of_date가 기준일로부터 달력 기준 6개월을 초과해 오래된 경우"로
변경한다. ``threshold_days``는 운영 진단용 override로만 유지한다.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

DEFAULT_STALENESS_THRESHOLD_MONTHS = 6
"""기본 정책 — 지수 정기 변경은 상·하반기 기준이므로 6개월을 기본 임계값으로 둔다."""

DEFAULT_STALENESS_THRESHOLD_DAYS = 21
"""과거 기본값(더 이상 기본 정책이 아님). ``threshold_days``를 명시적으로 넘긴
운영 진단용 override 호출에서만 참고용으로 남겨둔다."""


def _add_months(base: date, months: int) -> date:
    """``base``에 달력 기준으로 ``months``개월을 더한다.

    일(day)이 대상 월의 말일을 넘으면 그 달의 말일로 clamp한다
    (예: 2026-08-31 + 6개월 → 말일 clamp로 2027-02-28).
    """
    total_month_index = base.month - 1 + months
    year = base.year + total_month_index // 12
    month = total_month_index % 12 + 1
    last_day_of_month = calendar.monthrange(year, month)[1]
    day = min(base.day, last_day_of_month)
    return date(year, month, day)


@dataclass(frozen=True, slots=True)
class IndexMembershipStalenessReport:
    """지수 편입 데이터의 신선도 평가 결과 (관측 전용)."""

    latest_effective_from: date | None
    as_of: date
    age_days: int | None
    is_stale: bool
    threshold_months: int | None
    """기본 정책(달력 기준 개월) 사용 시에만 값이 있다. override 사용 시 ``None``."""
    threshold_days: int | None
    """``threshold_days`` override 사용 시에만 값이 있다. 기본 정책 사용 시 ``None``."""
    stale_after: date | None
    """이 날짜까지는 정상, 다음날부터 오래됨으로 판정하는 경계일."""


def evaluate_index_membership_staleness(
    latest_effective_from: date | None,
    *,
    as_of: date,
    threshold_days: int | None = None,
    threshold_months: int = DEFAULT_STALENESS_THRESHOLD_MONTHS,
) -> IndexMembershipStalenessReport:
    """가장 최근 membership 반영 시각을 기준으로 staleness를 평가한다.

    ``latest_effective_from``이 ``None``이면(데이터 자체가 없음) 무조건
    stale로 판정한다 — "데이터 없음"과 "오래된 데이터"를 구분하지 않고
    둘 다 감시 대상으로 취급하는 보수적 규칙이다.

    ``threshold_days``를 명시적으로 넘기면(운영 진단용 override) 기존과 동일한
    고정 일수 규칙을 쓴다. 넘기지 않으면 ``threshold_months``(기본 6) 달력
    기준 규칙을 쓴다 — 경계는 "정확히 그 개월수가 되는 날까지는 정상, 다음날부터
    오래됨"이다.
    """
    if latest_effective_from is None:
        return IndexMembershipStalenessReport(
            latest_effective_from=None,
            as_of=as_of,
            age_days=None,
            is_stale=True,
            threshold_months=None if threshold_days is not None else threshold_months,
            threshold_days=threshold_days,
            stale_after=None,
        )

    age_days = (as_of - latest_effective_from).days

    if threshold_days is not None:
        stale_after = latest_effective_from + timedelta(days=threshold_days)
        return IndexMembershipStalenessReport(
            latest_effective_from=latest_effective_from,
            as_of=as_of,
            age_days=age_days,
            is_stale=as_of > stale_after,
            threshold_months=None,
            threshold_days=threshold_days,
            stale_after=stale_after,
        )

    stale_after = _add_months(latest_effective_from, threshold_months)
    return IndexMembershipStalenessReport(
        latest_effective_from=latest_effective_from,
        as_of=as_of,
        age_days=age_days,
        is_stale=as_of > stale_after,
        threshold_months=threshold_months,
        threshold_days=None,
        stale_after=stale_after,
    )
