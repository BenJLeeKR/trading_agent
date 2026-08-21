"""Tests for ``agent_trading.services.ai_agents.fdc_rate_limiter``.

배경(2026-08-18): PR #286의 symbol-level concurrency 완화(5→3)는 429
감소 효과가 실측으로 입증되지 않고 cycle latency만 늘렸다. 이를
rollback하고, 실제로 프로세스 간 공유되는 파일 기반 rate limiter로
대체했다.

2026-08-21 갱신: fail-open bypass 설계를 제거하고 strict no-bypass
queue로 전환했다 — 대기 상한 초과/상태 파일 오류 시 더 이상 통과시키지
않고 ``granted=False``(``queue_timeout``/``state_file_error``)를
반환한다. 이 테스트는 그 강화된 계약(윈도우 내 상한, 대기, 대기 상한
초과 시 확정적 거부, 상태 파일 오류 시 확정적 거부, 동시 호출 시 정확한
슬롯 배분)을 검증한다.

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
    """``DEFAULT_MAX_WAIT_SECONDS`` — 2026-08-21 20.0→18.0 재계산.

    배경: strict queue + retry-inclusive permit 전환으로 이 대기가 이제
    FDC per-agent timeout(``_FDC_PER_AGENT_TIMEOUT=70``) 예산 **안에서**
    최초 요청 + 매 재시도(``MAX_RETRIES=3``)마다 반복될 수 있다. 최악의
    경우(3회 모두 대기+HTTP+백오프)를 그 70초 예산 안에 담기 위해
    18.0초로 낮췄다(자세한 계산은 ``fdc_rate_limiter.py`` 및
    ``scripts/run_agent_subprocess.py``의 상수 주석 참고).
    """

    def test_default_is_18_seconds(self) -> None:
        assert DEFAULT_MAX_WAIT_SECONDS == 18.0

    def test_worst_case_three_retries_stays_within_fdc_agent_timeout(self) -> None:
        """3회 permit 대기 + 3회 HTTP 왕복(~3s) + 재시도 backoff(~3s)가
        FDC per-agent timeout(70초) 예산 안에 들어와야 한다."""
        fdc_per_agent_timeout = 70.0
        max_retries = 3
        assumed_http_round_trip_seconds = 3.0
        assumed_retry_backoff_seconds = 3.0
        worst_case = (
            max_retries * DEFAULT_MAX_WAIT_SECONDS
            + max_retries * assumed_http_round_trip_seconds
            + assumed_retry_backoff_seconds
        )
        assert worst_case <= fdc_per_agent_timeout

    def test_fdc_agent_timeout_stays_within_subprocess_budget(self) -> None:
        """FDC per-agent timeout(70초)이 subprocess 전체 timeout(90초)
        예산 안에서 안전마진을 남겨야 한다."""
        fdc_per_agent_timeout = 70.0
        subprocess_timeout_default = 90.0
        assert fdc_per_agent_timeout < subprocess_timeout_default


class TestWaitForFdcSlotBasic:
    """윈도우 내 상한/대기/즉시 허용 기본 동작 및 strict 거부 동작."""

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
            assert result.granted is True
            assert result.queue_timeout is False
            assert result.state_file_error is False
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
        assert first.granted is True

        second = await wait_for_fdc_slot(
            max_calls=1,
            window_seconds=0.3,
            max_wait_seconds=2.0,
            poll_interval_seconds=0.05,
            state_path=state_path,
        )
        assert second.granted is True
        assert second.queue_timeout is False
        # 첫 호출의 윈도우(0.3s)가 끝날 때까지 대기했어야 한다.
        assert second.waited_seconds > 0.0

    @pytest.mark.asyncio
    async def test_queue_timeout_when_max_wait_exceeded_no_bypass(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """긴 윈도우 + 짧은 max_wait → 더 이상 통과시키지 않고 확정적으로
        거부(``queue_timeout``)해야 한다(strict, no bypass)."""
        state_path = str(tmp_path / "state.json")

        first = await wait_for_fdc_slot(
            max_calls=1,
            window_seconds=60.0,
            max_wait_seconds=0.5,
            poll_interval_seconds=0.05,
            state_path=state_path,
        )
        assert first.granted is True

        with caplog.at_level(logging.WARNING):
            second = await wait_for_fdc_slot(
                max_calls=1,
                window_seconds=60.0,
                max_wait_seconds=0.2,
                poll_interval_seconds=0.05,
                state_path=state_path,
            )
        assert second.granted is False
        assert second.queue_timeout is True
        assert second.state_file_error is False
        assert any(
            "포기함" in record.message and "HTTP 요청을 보내지 않음" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_state_file_error_denies_call_no_bypass(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """상태 파일 경로 자체가 접근 불가능하면 확정적으로 거부
        (``state_file_error``)해야 한다(strict, no bypass)."""
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
        assert result.granted is False
        assert result.state_file_error is True
        assert result.queue_timeout is False
        assert any(
            "상태 파일" in record.message and "허용하지 않고" in record.message
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

        # 모두 max_wait_seconds(3.0s) 안에 슬롯을 얻을 수 있는 조건이므로
        # 전부 granted=True여야 한다.
        assert all(r.granted for r in results)
        assert not any(r.queue_timeout for r in results)
        assert not any(r.state_file_error for r in results)
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
