"""Tests for ``agent_trading.services.index_membership_staleness`` — UNIV-4 축소안.

기본 정책은 2026-08-22부터 "달력 기준 6개월 초과"다(지수 정기 변경이
상·하반기 기준이므로). ``threshold_days``는 운영 진단용 override로만 남아있다.
"""

from __future__ import annotations

from datetime import date

from agent_trading.services.index_membership_staleness import (
    DEFAULT_STALENESS_THRESHOLD_DAYS,
    DEFAULT_STALENESS_THRESHOLD_MONTHS,
    evaluate_index_membership_staleness,
)


def test_no_data_is_always_stale() -> None:
    report = evaluate_index_membership_staleness(None, as_of=date(2026, 7, 12))

    assert report.is_stale is True
    assert report.age_days is None
    assert report.latest_effective_from is None
    assert report.stale_after is None
    assert report.threshold_months == DEFAULT_STALENESS_THRESHOLD_MONTHS
    assert report.threshold_days is None


def test_no_data_is_always_stale_even_with_days_override() -> None:
    report = evaluate_index_membership_staleness(
        None, as_of=date(2026, 7, 12), threshold_days=7
    )

    assert report.is_stale is True
    assert report.threshold_days == 7
    assert report.threshold_months is None


class TestDefaultCalendarMonthPolicy:
    """기본 정책 — threshold_days를 넘기지 않으면 달력 기준 개월수로 판정한다."""

    def test_exactly_six_months_is_not_stale(self) -> None:
        """예시: 기준일 2026-01-31, 평가일 2026-07-31 → 정상."""
        report = evaluate_index_membership_staleness(
            date(2026, 1, 31), as_of=date(2026, 7, 31)
        )

        assert report.threshold_months == 6
        assert report.threshold_days is None
        assert report.stale_after == date(2026, 7, 31)
        assert report.is_stale is False

    def test_one_day_past_six_months_is_stale(self) -> None:
        """예시: 기준일 2026-01-31, 평가일 2026-08-01 → 오래됨."""
        report = evaluate_index_membership_staleness(
            date(2026, 1, 31), as_of=date(2026, 8, 1)
        )

        assert report.stale_after == date(2026, 7, 31)
        assert report.is_stale is True

    def test_well_within_six_months_is_not_stale(self) -> None:
        report = evaluate_index_membership_staleness(
            date(2026, 6, 27), as_of=date(2026, 7, 31)
        )

        assert report.is_stale is False

    def test_month_end_clamps_to_last_day_of_target_month(self) -> None:
        """2026-08-31 + 6개월 → 2027-02(28일, 평년)로 clamp."""
        report = evaluate_index_membership_staleness(
            date(2026, 8, 31), as_of=date(2027, 2, 28)
        )

        assert report.stale_after == date(2027, 2, 28)
        assert report.is_stale is False

        report_next_day = evaluate_index_membership_staleness(
            date(2026, 8, 31), as_of=date(2027, 3, 1)
        )
        assert report_next_day.is_stale is True

    def test_leap_year_february_start_clamps_correctly(self) -> None:
        """윤년 2월 29일 기준 + 6개월 → 2024-08-29(윤년이 아닌 target month는
        영향 없음, day 자체가 8월 말일 이내이므로 clamp 불필요)."""
        report = evaluate_index_membership_staleness(
            date(2024, 2, 29), as_of=date(2024, 8, 29)
        )

        assert report.stale_after == date(2024, 8, 29)
        assert report.is_stale is False

    def test_custom_threshold_months_override(self) -> None:
        report = evaluate_index_membership_staleness(
            date(2026, 1, 1), as_of=date(2026, 4, 1), threshold_months=3
        )

        assert report.threshold_months == 3
        assert report.stale_after == date(2026, 4, 1)
        assert report.is_stale is False


class TestThresholdDaysOverride:
    """``threshold_days``를 명시하면 운영 진단용 고정 일수 override로 동작한다
    (기존 21일 고정 정책과 동일한 산술을 그대로 보존)."""

    def test_within_threshold_is_not_stale(self) -> None:
        report = evaluate_index_membership_staleness(
            date(2026, 7, 1),
            as_of=date(2026, 7, 12),
            threshold_days=21,
        )

        assert report.age_days == 11
        assert report.is_stale is False
        assert report.threshold_days == 21
        assert report.threshold_months is None

    def test_exceeding_threshold_is_stale(self) -> None:
        report = evaluate_index_membership_staleness(
            date(2026, 6, 1),
            as_of=date(2026, 7, 12),
            threshold_days=21,
        )

        assert report.age_days == 41
        assert report.is_stale is True

    def test_exactly_at_threshold_is_not_stale(self) -> None:
        """경계값은 "초과"만 stale로 본다."""
        report = evaluate_index_membership_staleness(
            date(2026, 6, 21),
            as_of=date(2026, 7, 12),  # 정확히 21일 경과
            threshold_days=21,
        )

        assert report.age_days == 21
        assert report.is_stale is False


def test_default_threshold_months_is_6() -> None:
    assert DEFAULT_STALENESS_THRESHOLD_MONTHS == 6


def test_legacy_default_days_constant_still_21_for_reference() -> None:
    """더 이상 기본 정책이 아니지만, override 참고용 상수 값 자체는 유지된다."""
    assert DEFAULT_STALENESS_THRESHOLD_DAYS == 21
