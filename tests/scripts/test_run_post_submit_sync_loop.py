"""Tests for ``scripts.run_post_submit_sync_loop`` — post-submit sync scheduler.

Test coverage
-------------
* ``_parse_args()`` — ``--after-hours`` CLI 플래그 파싱 검증 (2 tests)
"""

from __future__ import annotations

from scripts.run_post_submit_sync_loop import _parse_args


class TestParseArgsAfterHours:
    """``--after-hours`` CLI 플래그 파싱 테스트."""

    def test_parse_args_after_hours_default(self) -> None:
        """``--after-hours`` 기본값이 False인지 검증."""
        args = _parse_args([])
        assert args.after_hours is False

    def test_parse_args_after_hours_enabled(self) -> None:
        """``--after-hours`` 플래그가 True로 파싱되는지 검증."""
        args = _parse_args(["--after-hours"])
        assert args.after_hours is True
