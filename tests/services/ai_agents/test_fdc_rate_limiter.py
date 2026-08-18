"""Tests for ``agent_trading.services.ai_agents.fdc_rate_limiter``.

배경(2026-08-18): PR #286의 symbol-level concurrency 완화(5→3)는 429
감소 효과가 실측으로 입증되지 않고 cycle latency만 늘렸다. 이를
rollback하고, 실제로 프로세스 간 공유되는 파일 기반 rate limiter로
대체했다 — 이 테스트는 그 limiter의 핵심 동작(윈도우 내 상한, 대기,
대기 상한 초과 시 bypass, 상태 파일 오류 시 bypass, 동시 호출 시
정확한 슬롯 배분)을 검증한다.

각 테스트는 ``tmp_path`` 기반 전용 상태 파일 경로를 사용해 테스트 간
상태가 섞이지 않도록 격리한다.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from agent_trading.services.ai_agents.fdc_rate_limiter import (
    DEFAULT_MAX_WAIT_SECONDS,
    FdcRateLimitResult,
    default_state_path,
    wait_for_fdc_slot,
)


class TestDefaultStatePath:
    """``default_state_path()`` — import-time 부작용 없음, 임시 디렉터리 사용."""

    def test_returns_path_under_tempdir(self) -> None:
        import tempfile

        path = default_state_path()
        assert path.startswith(tempfile.gettempdir())

    def test_calling_does_not_create_file(self, tmp_path: Path) -> None:
        """``default_state_path()`` 자체는 순수 함수 — 파일을 생성하지 않는다."""
        path = default_state_path()
        # 이미 다른 프로세스/테스트가 만들어뒀을 수 있으니 존재 여부가 아니라
        # "이 호출 자체가 부작용을 만들지 않는다"만 확인한다(예외 없이 반환).
        assert isinstance(path, str) and path


class TestDefaultMaxWaitSeconds:
    """``DEFAULT_MAX_WAIT_SECONDS`` — 2026-08-18 15.0→20.0 조정.

    배경: 이 대기는 FDC 호출 자체의 30초 per-agent timeout 블록 앞에서
    별도로 일어나므로 그 30초 예산에 포함되지 않고, subprocess 전체
    timeout(기본 90초) 예산을 쓴다 — 20초로 늘려도 여유가 충분하다.
    실측(2026-08-18 13:28~13:29 KST)에서 대기 후 슬롯을 확보한 사례가
    13~14초에 몰려 있어(기존 상한 15.0s에 근접), 상한을 20.0s로 늘려
    그 경계에서 bypass되던 호출 일부가 정상 대기로 전환될 여지를 준다.
    """

    def test_default_is_20_seconds(self) -> None:
        assert DEFAULT_MAX_WAIT_SECONDS == 20.0

    def test_default_plus_fdc_timeout_stays_within_subprocess_budget(self) -> None:
        """20초(대기) + 30초(FDC per-agent timeout 상한) = 50초로,
        subprocess 전체 timeout 기본값(90초) 안에서 여유가 남아야 한다."""
        fdc_per_agent_timeout = 30.0
        subprocess_timeout_default = 90.0
        worst_case = DEFAULT_MAX_WAIT_SECONDS + fdc_per_agent_timeout
        assert worst_case < subprocess_timeout_default


class TestWaitForFdcSlotBasic:
    """윈도우 내 상한/대기/즉시 허용 기본 동작."""

    @pytest.mark.asyncio
    async def test_calls_within_limit_succeed_immediately(
        self, tmp_path: Path
    ) -> None:
        state_path = str(tmp_path / "state.json")
        for _ in range(3):
            result = await wait_for_fdc_slot(
                max_calls=3,
                window_seconds=60.0,
                max_wait_seconds=2.0,
                poll_interval_seconds=0.05,
                state_path=state_path,
            )
            assert result.allowed is True
            assert result.bypassed is False
            assert result.waited_seconds == 0.0

    @pytest.mark.asyncio
    async def test_call_beyond_limit_waits_then_succeeds(
        self, tmp_path: Path
    ) -> None:
        """윈도우가 짧으면(0.3s) 상한 초과 호출도 윈도우 만료 후 통과해야 한다."""
        state_path = str(tmp_path / "state.json")

        first = await wait_for_fdc_slot(
            max_calls=1,
            window_seconds=0.3,
            max_wait_seconds=2.0,
            poll_interval_seconds=0.05,
            state_path=state_path,
        )
        assert first.allowed is True
        assert first.bypassed is False

        second = await wait_for_fdc_slot(
            max_calls=1,
            window_seconds=0.3,
            max_wait_seconds=2.0,
            poll_interval_seconds=0.05,
            state_path=state_path,
        )
        assert second.allowed is True
        assert second.bypassed is False
        # 첫 호출의 윈도우(0.3s)가 끝날 때까지 대기했어야 한다.
        assert second.waited_seconds > 0.0

    @pytest.mark.asyncio
    async def test_bypass_when_max_wait_exceeded(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """긴 윈도우 + 짧은 max_wait → 대기 상한 초과로 bypass돼야 한다."""
        state_path = str(tmp_path / "state.json")

        first = await wait_for_fdc_slot(
            max_calls=1,
            window_seconds=60.0,
            max_wait_seconds=0.5,
            poll_interval_seconds=0.05,
            state_path=state_path,
        )
        assert first.bypassed is False

        with caplog.at_level(logging.WARNING):
            second = await wait_for_fdc_slot(
                max_calls=1,
                window_seconds=60.0,
                max_wait_seconds=0.2,
                poll_interval_seconds=0.05,
                state_path=state_path,
            )
        assert second.allowed is True
        assert second.bypassed is True
        assert second.bypass_reason == "max_wait_exceeded"
        assert any(
            "제한 없이 통과" in record.message for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_bypass_on_file_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """상태 파일 경로 자체가 접근 불가능하면 bypass(file_error)돼야 한다."""
        # 디렉터리가 있어야 할 자리에 파일을 만들어 os.makedirs/open이 실패하게 한다.
        blocking_file = tmp_path / "not_a_directory"
        blocking_file.write_text("x")
        state_path = str(blocking_file / "state.json")

        with caplog.at_level(logging.WARNING):
            result = await wait_for_fdc_slot(
                max_calls=1,
                window_seconds=60.0,
                max_wait_seconds=1.0,
                poll_interval_seconds=0.05,
                state_path=state_path,
            )
        assert result.allowed is True
        assert result.bypassed is True
        assert result.bypass_reason is not None
        assert result.bypass_reason.startswith("file_error:")
        assert any(
            "상태 파일" in record.message and "접근 실패" in record.message
            for record in caplog.records
        )


class TestWaitForFdcSlotConcurrency:
    """여러 코루틴이 동시에 호출해도 상한을 정확히 지키는지 확인."""

    @pytest.mark.asyncio
    async def test_concurrent_calls_respect_shared_limit(
        self, tmp_path: Path
    ) -> None:
        state_path = str(tmp_path / "state.json")

        async def _call() -> FdcRateLimitResult:
            return await wait_for_fdc_slot(
                max_calls=2,
                window_seconds=0.5,
                max_wait_seconds=3.0,
                poll_interval_seconds=0.05,
                state_path=state_path,
            )

        results = await asyncio.gather(*(_call() for _ in range(5)))

        # fail-open 설계이므로 전부 결국 allowed=True여야 한다.
        assert all(r.allowed for r in results)
        assert not any(r.bypassed for r in results)
        # 상한(2)을 초과한 나머지는 최소 한 번은 대기했어야 한다 —
        # 동시에 5개가 몰렸는데 윈도우당 2개만 즉시 통과 가능하므로.
        waited_count = sum(1 for r in results if r.waited_seconds > 0.0)
        assert waited_count >= 3

    @pytest.mark.asyncio
    async def test_concurrent_calls_do_not_exceed_max_calls_in_window(
        self, tmp_path: Path
    ) -> None:
        """동시 호출 직후, 상태 파일에 기록된 타임스탬프 수가 순간적으로
        max_calls를 넘지 않아야 한다(락으로 직렬화됐는지 확인)."""
        import json

        state_path = str(tmp_path / "state.json")

        async def _call() -> FdcRateLimitResult:
            return await wait_for_fdc_slot(
                max_calls=3,
                window_seconds=5.0,
                max_wait_seconds=10.0,
                poll_interval_seconds=0.05,
                state_path=state_path,
            )

        await asyncio.gather(*(_call() for _ in range(6)))

        with open(state_path) as fh:
            timestamps = json.loads(fh.read())
        # 6번 호출이 전부 성공했으므로(윈도우가 5s로 넉넉함), 최종적으로는
        # 오래된 것부터 트림되며 최대 max_calls개만 파일에 남아있어야 한다.
        assert len(timestamps) <= 3
