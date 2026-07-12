"""Tests for ``agent_trading.services.index_membership_staleness`` — UNIV-4 축소안."""

from __future__ import annotations

from datetime import date

from agent_trading.services.index_membership_staleness import (
    DEFAULT_STALENESS_THRESHOLD_DAYS,
    evaluate_index_membership_staleness,
)


def test_no_data_is_always_stale() -> None:
    report = evaluate_index_membership_staleness(None, as_of=date(2026, 7, 12))

    assert report.is_stale is True
    assert report.age_days is None
    assert report.latest_effective_from is None


def test_within_threshold_is_not_stale() -> None:
    report = evaluate_index_membership_staleness(
        date(2026, 7, 1),
        as_of=date(2026, 7, 12),
        threshold_days=21,
    )

    assert report.age_days == 11
    assert report.is_stale is False


def test_exceeding_threshold_is_stale() -> None:
    report = evaluate_index_membership_staleness(
        date(2026, 6, 1),
        as_of=date(2026, 7, 12),
        threshold_days=21,
    )

    assert report.age_days == 41
    assert report.is_stale is True


def test_exactly_at_threshold_is_not_stale() -> None:
    """경계값은 "초과"만 stale로 본다(설계 문서 "21일 초과" 문구와 일치)."""
    report = evaluate_index_membership_staleness(
        date(2026, 6, 21),
        as_of=date(2026, 7, 12),  # 정확히 21일 경과
        threshold_days=21,
    )

    assert report.age_days == 21
    assert report.is_stale is False


def test_default_threshold_is_21_days() -> None:
    assert DEFAULT_STALENESS_THRESHOLD_DAYS == 21
