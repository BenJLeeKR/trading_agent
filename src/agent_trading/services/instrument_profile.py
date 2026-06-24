"""국내주식 instrument profile 해석 공통 유틸."""

from __future__ import annotations

from collections.abc import Sequence

_INDEX_MEMBERSHIP_PRIORITY: tuple[str, ...] = (
    "KOSPI100",
    "KOSPI_100",
    "KOSDAQ50",
    "KOSDAQ_50",
    "KOSPI200",
    "KOSPI_200",
    "KOSDAQ150",
    "KOSDAQ_150",
    "KOSPI_LARGE",
    "KOSDAQ_GROWTH",
)

_INDEX_MEMBERSHIP_PRIORITY_RANK = {
    code: index for index, code in enumerate(_INDEX_MEMBERSHIP_PRIORITY)
}


def normalize_index_memberships(
    values: Sequence[str] | frozenset[str],
) -> tuple[str, ...]:
    """membership 집합을 deterministic 순서로 정규화한다."""
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    normalized.sort(
        key=lambda value: (
            _INDEX_MEMBERSHIP_PRIORITY_RANK.get(value, len(_INDEX_MEMBERSHIP_PRIORITY)),
            value,
        )
    )
    return tuple(normalized)


def derive_primary_index_membership(
    values: Sequence[str] | frozenset[str],
) -> str | None:
    """중첩 membership 집합에서 대표 membership 하나를 뽑는다."""
    normalized = normalize_index_memberships(values)
    if not normalized:
        return None
    return normalized[0]
