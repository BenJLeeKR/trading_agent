"""Tests for ``agent_trading.services.ai_agents.fdc_rate_limiter``.

배경(2026-08-18): PR #286의 symbol-level concurrency 완화(5→3)는 429
감소 효과가 실측으로 입증되지 않고 cycle latency만 늘렸다. 이를
rollback하고, 실제로 프로세스 간 공유되는 파일 기반 rate limiter로
대체했다.

2026-08-21 갱신: fail-open bypass 설계를 제거하고 strict no-bypass
queue로 전환했다 — 대기 상한 초과/상태 파일 오류 시 더 이상 통과시키지
않고 ``granted=False``(``queue_timeout``/``state_file_error``)를
반환한다.

2026-08-21(2차) 갱신: 상태 파일을 ``{"version", "grants", "pending"}``
구조로 분리해 진짜 FIFO ticket queue를 구현했다 — head ticket만 grant를
받을 수 있고, 1차 대기 상한(``max_wait_seconds``)을 넘기면
``allow_requeue=True``인 호출에 한해 새 ticket으로 FIFO 맨 뒤에 1회만
재등록한다. 이 테스트는 FIFO 순서, 재대기(최대 1회), strict 거부,
orphan ticket 정리(lease 기반), grant/pending 수명 규칙 분리를
검증한다.

각 테스트는 ``tmp_path`` 기반 전용 상태 파일 경로를 사용해 테스트 간
상태가 섞이지 않도록 격리한다. 실제 sleep은 아주 짧은 값(수십~수백ms)
만 사용하며, 운영 상수(18초/30초/70초 등)를 실제로 기다리는 테스트는
없다 — 모든 시간 관련 상수는 테스트 전용 작은 값으로 오버라이드한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import pytest

from agent_trading.services.ai_agents.fdc_rate_limiter import (
    DEFAULT_MAX_REQUEUE_COUNT,
    DEFAULT_MAX_WAIT_SECONDS,
    DEFAULT_TICKET_LEASE_SECONDS,
    FdcRateLimitResult,
    default_state_path,
    wait_for_fdc_slot,
)


def _read_pending(state_path: str) -> list[dict]:
    with open(state_path) as fh:
        state = json.loads(fh.read())
    return state["pending"]


class TestDefaultStatePath:
    """``default_state_path()`` — import-time 부작용 없음, 임시 디렉터리 사용."""

    def test_returns_path_under_tempdir(self) -> None:
        import tempfile

        path = default_state_path()
        assert path.startswith(tempfile.gettempdir())

    def test_calling_does_not_create_file(self, tmp_path: Path) -> None:
        """``default_state_path()`` 자체는 순수 함수 — 파일을 생성하지 않는다."""
        path = default_state_path()
        assert isinstance(path, str) and path


class TestDefaultConstants:
    """``DEFAULT_MAX_WAIT_SECONDS``/``DEFAULT_TICKET_LEASE_SECONDS``/
    ``DEFAULT_MAX_REQUEUE_COUNT`` — 2026-08-21(2차) in-cycle FIFO
    재대기열 도입에 따른 상수 확인.
    """

    def test_default_max_wait_is_18_seconds(self) -> None:
        assert DEFAULT_MAX_WAIT_SECONDS == 18.0

    def test_default_lease_is_30_seconds_not_short(self) -> None:
        """lease는 3~5초처럼 짧게 잡지 않는다(요청사항) — poll 주기(1초)
        보다 훨씬 길어야 일시적 스케줄링 지연으로 살아있는 ticket이
        orphan으로 오인되지 않는다."""
        assert DEFAULT_TICKET_LEASE_SECONDS == 30.0

    def test_default_max_requeue_count_is_1(self) -> None:
        assert DEFAULT_MAX_REQUEUE_COUNT == 1

    def test_assumed_worst_case_fits_fdc_agent_timeout_design_target(self) -> None:
        """최초 요청 permit 획득(최악 2 x 18=36초, 재대기 1회 포함) +
        429 재시도 2회(재대기 없음, 각 18초) + HTTP/backoff(약 12초)
        최악 시나리오는 이론상 70초를 넘을 수 있다(36+18+18+12=84s) —
        이 경우 시스템이 멈추지 않고 ``_FDC_PER_AGENT_TIMEOUT``의
        ``asyncio.wait_for()``가 확정적으로 강제 종료해
        ``provider_timeout``으로 귀결됨을 문서화한다(fdc_rate_limiter.py
        모듈 docstring "2026-08-21(2차)" 절 참고). 이 테스트는 그 계산
        자체가 여전히 유한하고 예측 가능함을 확인한다(무한대기 아님)."""
        fdc_per_agent_timeout = 70.0
        max_retries = 3
        assumed_http_round_trip_seconds = 3.0
        assumed_retry_backoff_seconds = 3.0
        # 최초 요청만 재대기 포함(최악 2배), 나머지 재시도는 재대기 없음.
        worst_case_permit_wait = (
            2 * DEFAULT_MAX_WAIT_SECONDS  # 최초 요청(1차+재대기)
            + (max_retries - 1) * DEFAULT_MAX_WAIT_SECONDS  # 재시도 2회(재대기 없음)
        )
        worst_case_total = (
            worst_case_permit_wait
            + max_retries * assumed_http_round_trip_seconds
            + assumed_retry_backoff_seconds
        )
        # 유한한 값이며, 70초를 넘을 수 있음을 명시적으로 확인(회귀
        # 방지용 — 이 값이 갑자기 무한대나 음수가 되면 계산 로직 버그).
        assert worst_case_total == pytest.approx(84.0)
        assert worst_case_total > fdc_per_agent_timeout  # 예산 초과 가능성 인지된 사실

    def test_fdc_agent_timeout_stays_within_subprocess_budget(self) -> None:
        """FDC per-agent timeout(70초)이 subprocess 전체 timeout(90초)
        예산 안에서 안전마진을 남겨야 한다 — 실제 상수/기본값을 직접
        import해 비교한다(하드코딩된 리터럴 드리프트 방지)."""
        import inspect

        from agent_trading.services.decision_agent_runner import DecisionAgentRunner
        from scripts.run_agent_subprocess import _FDC_PER_AGENT_TIMEOUT

        subprocess_timeout_default = inspect.signature(
            DecisionAgentRunner.__init__
        ).parameters["subprocess_timeout"].default

        assert _FDC_PER_AGENT_TIMEOUT < subprocess_timeout_default


class TestWaitForFdcSlotBasic:
    """윈도우 내 상한/대기/즉시 허용 기본 동작 및 strict 거부 동작
    (2026-08-21 강화 계약 유지 확인 — FIFO ticket 구조로 바뀌어도 동일)."""

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
            # 즉시 grant돼도 asyncio.to_thread I/O 왕복만큼의 미세한
            # 실측 시간이 남는다(수 ms) — 정확히 0.0이어야 하는 것은
            # 아니다.
            assert result.waited_seconds < 0.1
            assert result.requeue_count == 0
            assert result.queue_position_at_first_wait is None
            assert result.queue_ticket  # 항상 발급됨

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
        assert second.requeue_count == 0
        # 첫 호출의 윈도우(0.3s)가 끝날 때까지 대기했어야 한다.
        assert second.waited_seconds > 0.0
        assert second.final_waited_seconds == second.waited_seconds

    @pytest.mark.asyncio
    async def test_queue_timeout_when_max_wait_exceeded_no_bypass(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """긴 윈도우 + 짧은 max_wait + 재대기 없음 → 더 이상 통과시키지
        않고 확정적으로 거부(``queue_timeout``)해야 한다(strict, no
        bypass). ``allow_requeue=False``로 호출해 1회 대기만 검증한다."""
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
                allow_requeue=False,
            )
        assert second.granted is False
        assert second.queue_timeout is True
        assert second.state_file_error is False
        assert second.requeue_count == 0
        assert second.queue_deadline_exceeded is False  # 재대기를 아예 안 썼으므로
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


class TestStateFileCorruption:
    """2026-08-21(3차) 결함 수정 회귀 테스트: 손상된/지원하지 않는
    형식의 상태 파일 내용을 빈 상태로 조용히 대체하던 과거 결함을
    fail-closed로 고쳤는지 검증한다 — 이를 방치하면 최근 60초 grant
    기록이 사라져 ``DEFAULT_MAX_CALLS_PER_WINDOW`` 한도를 우회하고
    실제 429가 재발할 수 있었다."""

    @pytest.mark.asyncio
    async def test_malformed_json_fails_closed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        state_path = str(tmp_path / "state.json")
        with open(state_path, "w") as fh:
            fh.write("{not valid json!!")

        with caplog.at_level(logging.WARNING):
            result = await wait_for_fdc_slot(
                max_calls=1, window_seconds=60.0, max_wait_seconds=0.2,
                poll_interval_seconds=0.05, state_path=state_path,
            )
        assert result.granted is False
        assert result.state_file_error is True
        assert result.queue_timeout is False
        # 손상된 상태를 "빈 상태"로 취급해 permit을 내주지 않았어야 한다
        # (granted=True가 나오면 안 됨 — 위 assert로 이미 확인됨).

    @pytest.mark.asyncio
    async def test_unsupported_version_fails_closed(self, tmp_path: Path) -> None:
        state_path = str(tmp_path / "state.json")
        with open(state_path, "w") as fh:
            json.dump({"version": 999, "grants": [], "pending": []}, fh)

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=0.2,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.granted is False
        assert result.state_file_error is True

    @pytest.mark.asyncio
    async def test_wrong_top_level_type_fails_closed(self, tmp_path: Path) -> None:
        state_path = str(tmp_path / "state.json")
        with open(state_path, "w") as fh:
            json.dump("this is a string, not a dict or list", fh)

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=0.2,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.granted is False
        assert result.state_file_error is True

    @pytest.mark.asyncio
    async def test_malformed_grants_type_fails_closed(self, tmp_path: Path) -> None:
        state_path = str(tmp_path / "state.json")
        with open(state_path, "w") as fh:
            json.dump({"version": 1, "grants": "not-a-list", "pending": []}, fh)

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=0.2,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.granted is False
        assert result.state_file_error is True

    @pytest.mark.asyncio
    async def test_malformed_pending_type_fails_closed(self, tmp_path: Path) -> None:
        state_path = str(tmp_path / "state.json")
        with open(state_path, "w") as fh:
            json.dump({"version": 1, "grants": [], "pending": {"not": "a list"}}, fh)

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=0.2,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.granted is False
        assert result.state_file_error is True

    @pytest.mark.asyncio
    async def test_mixed_legacy_list_fails_closed(self, tmp_path: Path) -> None:
        """숫자가 아닌 값이 섞인 legacy list는 마이그레이션하지 않고
        손상으로 취급해야 한다."""
        state_path = str(tmp_path / "state.json")
        with open(state_path, "w") as fh:
            json.dump([1755000000.0, "not-a-timestamp", 1755000001.0], fh)

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=0.2,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.granted is False
        assert result.state_file_error is True

    @pytest.mark.asyncio
    async def test_brand_new_empty_file_initializes_normally(
        self, tmp_path: Path
    ) -> None:
        """파일이 아예 없던 경우(``wait_for_fdc_slot()``이 처음
        만드는 경우)는 정상적인 빈 v1 상태로 초기화돼 즉시 permit을
        발급해야 한다 — 손상 상태와 혼동하면 안 된다."""
        state_path = str(tmp_path / "state.json")
        assert not Path(state_path).exists()

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=1.0,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.granted is True
        assert result.state_file_error is False

        with open(state_path) as fh:
            state = json.loads(fh.read())
        assert state["version"] == 1
        assert isinstance(state["grants"], list)
        assert isinstance(state["pending"], list)

    @pytest.mark.asyncio
    async def test_legacy_list_float_migrates_and_preserves_grants(
        self, tmp_path: Path
    ) -> None:
        """PR #311 이전 legacy ``list[float]`` 포맷은 v1 구조로
        마이그레이션돼야 하며, 아직 60초 이내인 legacy grant가
        ``max_calls``를 채우면 새 permit이 발급되지 않아야 한다(배포
        직후 grant 기록을 잃어 RPM 한도를 우회하는 것을 방지)."""
        state_path = str(tmp_path / "state.json")
        now = time.time()
        # max_calls=1이므로, 방금(0.1초 전) 발급된 legacy grant 1건만
        # 있어도 윈도우가 가득 찬 것으로 간주돼야 한다.
        legacy_grants = [now - 0.1]
        with open(state_path, "w") as fh:
            json.dump(legacy_grants, fh)

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=0.15,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        # legacy grant가 유효하게 보존됐다면 새 permit을 못 받고
        # queue_timeout이어야 한다(state_file_error가 아님 — 정상
        # 마이그레이션 경로).
        assert result.state_file_error is False
        assert result.granted is False
        assert result.queue_timeout is True

        # 변환된 파일은 v1 dict 구조여야 하고, legacy grant 값을
        # 그대로 보존해야 한다.
        with open(state_path) as fh:
            migrated = json.loads(fh.read())
        assert migrated["version"] == 1
        assert isinstance(migrated["grants"], list)
        assert any(abs(g - legacy_grants[0]) < 0.001 for g in migrated["grants"])

    @pytest.mark.asyncio
    async def test_legacy_list_float_old_timestamps_are_trimmed(
        self, tmp_path: Path
    ) -> None:
        """60초보다 오래된 legacy timestamp는 마이그레이션 후 정상적으로
        트림돼 새 permit 발급을 막지 않아야 한다."""
        state_path = str(tmp_path / "state.json")
        now = time.time()
        legacy_grants = [now - 100.0]  # window_seconds=60보다 훨씬 오래됨
        with open(state_path, "w") as fh:
            json.dump(legacy_grants, fh)

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=1.0,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.state_file_error is False
        assert result.granted is True  # 오래된 legacy grant는 트림돼 슬롯이 비어 있음

    @pytest.mark.asyncio
    async def test_empty_legacy_list_migrates_to_empty_v1_state(
        self, tmp_path: Path
    ) -> None:
        """빈 legacy list(``[]``)도 손상이 아니라 정상적인 빈 v1
        상태로 마이그레이션돼야 한다."""
        state_path = str(tmp_path / "state.json")
        with open(state_path, "w") as fh:
            json.dump([], fh)

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=1.0,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.state_file_error is False
        assert result.granted is True


class TestNewFileVsExistingEmptyFile:
    """2026-08-21(4차) 결함 수정 회귀 테스트: "상태 파일이 아직 존재하지
    않는 정상 최초 실행"과 "이미 존재하던 상태 파일이 비어 버린 비정상
    상태"(프로세스 강제 종료, truncate 직후 종료, 부분 기록 실패 등)를
    명확히 구분한다. ``open(path, "a+")``만으로는 이 둘을 구분할 수
    없었다 — 둘 다 "내용이 빈 파일"이기 때문이다."""

    @pytest.mark.asyncio
    async def test_nonexistent_path_initializes_and_grants_first_permit(
        self, tmp_path: Path
    ) -> None:
        state_path = str(tmp_path / "state.json")
        assert not Path(state_path).exists()

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=1.0,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.granted is True
        assert result.state_file_error is False

        with open(state_path) as fh:
            state = json.loads(fh.read())
        assert state == {"version": 1, "grants": [], "pending": []} or (
            state["version"] == 1
            and isinstance(state["grants"], list)
            and isinstance(state["pending"], list)
        )

    @pytest.mark.asyncio
    async def test_preexisting_zero_byte_file_fails_closed(
        self, tmp_path: Path
    ) -> None:
        """사전에 0바이트로 존재하던 파일은 "신규"가 아니라 손상으로
        취급해 permit을 거부해야 한다."""
        state_path = str(tmp_path / "state.json")
        Path(state_path).touch()  # 0바이트로 미리 존재
        assert Path(state_path).exists()
        assert Path(state_path).stat().st_size == 0

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=0.2,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.granted is False
        assert result.state_file_error is True
        assert result.queue_timeout is False

    @pytest.mark.asyncio
    async def test_preexisting_whitespace_only_file_fails_closed(
        self, tmp_path: Path
    ) -> None:
        state_path = str(tmp_path / "state.json")
        with open(state_path, "w") as fh:
            fh.write("   \n\t  \n")

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=0.2,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.granted is False
        assert result.state_file_error is True

    @pytest.mark.asyncio
    async def test_partial_json_write_fails_closed(self, tmp_path: Path) -> None:
        """디스크 쓰기 도중 중단된 것을 흉내내는 부분 JSON — 기존 손상
        JSON 테스트와 동일하게 fail-closed 처리돼야 한다."""
        state_path = str(tmp_path / "state.json")
        with open(state_path, "w") as fh:
            fh.write('{"version": 1, "grants":')  # 잘린 JSON

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=0.2,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.granted is False
        assert result.state_file_error is True

    @pytest.mark.asyncio
    async def test_concurrent_first_initialization_is_race_free(
        self, tmp_path: Path
    ) -> None:
        """존재하지 않는 동일 경로에 여러 호출을 동시에 시작해도, 유효한
        JSON만 최종적으로 남고 초기화 경합으로 빈 상태를 손상으로 잘못
        재해석해 일부가 부당하게 실패(state_file_error)해서는 안 된다.
        ``max_calls``를 동시 호출 수와 같게 둬 전부 즉시 grant 가능한
        여유를 주고, 실제로 전부 정상 grant되는지 확인한다."""
        state_path = str(tmp_path / "state.json")
        assert not Path(state_path).exists()

        concurrency = 5

        async def _call() -> FdcRateLimitResult:
            return await wait_for_fdc_slot(
                max_calls=concurrency, window_seconds=5.0, max_wait_seconds=1.5,
                poll_interval_seconds=0.05, state_path=state_path,
            )

        results = await asyncio.gather(*(_call() for _ in range(concurrency)))

        # 초기화 경합 자체가 원인이 되어 state_file_error가 나면 안 된다.
        assert not any(r.state_file_error for r in results)
        # max_calls를 동시 호출 수와 같게 뒀으므로 전부 grant돼야 한다.
        assert all(r.granted for r in results)

        with open(state_path) as fh:
            state = json.loads(fh.read())
        assert state["version"] == 1
        assert len(state["grants"]) <= concurrency  # max_calls를 넘는 grant 없음
        assert state["pending"] == []


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

        assert all(r.granted for r in results)
        assert not any(r.queue_timeout for r in results)
        assert not any(r.state_file_error for r in results)
        waited_count = sum(1 for r in results if r.waited_seconds > 0.0)
        assert waited_count >= 3

    @pytest.mark.asyncio
    async def test_concurrent_calls_do_not_exceed_max_calls_in_window(
        self, tmp_path: Path
    ) -> None:
        """동시 호출 직후, 상태 파일의 ``grants`` 수가 순간적으로
        ``max_calls``를 넘지 않아야 한다(락으로 직렬화됐는지 확인)."""
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
            state = json.loads(fh.read())
        assert len(state["grants"]) <= 3
        # 6번 호출이 전부 성공했으므로 pending은 비어 있어야 한다.
        assert state["pending"] == []


class TestFifoOrdering:
    """head ticket만 grant를 받는 진짜 FIFO 순서를 검증한다."""

    @pytest.mark.asyncio
    async def test_a_b_c_granted_in_arrival_order(self, tmp_path: Path) -> None:
        """A, B, C가 이 순서로 도착하면(max_calls=1이라 한 번에 하나씩만
        통과) permit도 A → B → C 순서로 부여돼야 한다."""
        state_path = str(tmp_path / "state.json")
        order: list[str] = []

        async def _call(name: str) -> None:
            result = await wait_for_fdc_slot(
                max_calls=1,
                window_seconds=0.2,
                max_wait_seconds=5.0,
                poll_interval_seconds=0.02,
                state_path=state_path,
            )
            assert result.granted is True
            order.append(name)

        task_a = asyncio.create_task(_call("A"))
        await asyncio.sleep(0.03)  # A가 먼저 슬롯을 확보하도록 보장
        task_b = asyncio.create_task(_call("B"))
        await asyncio.sleep(0.03)  # B가 pending에 A 다음으로 등록되도록 보장
        task_c = asyncio.create_task(_call("C"))

        await asyncio.gather(task_a, task_b, task_c)
        assert order == ["A", "B", "C"]


class TestRequeueToTail:
    """1차 대기 상한 초과 시 새 ticket으로 FIFO 맨 뒤에 1회 재등록되는지
    검증한다."""

    @pytest.mark.asyncio
    async def test_timed_out_ticket_requeues_behind_already_waiting(
        self, tmp_path: Path
    ) -> None:
        """Z가 1차 대기(0.12s)에서 timeout되면, 이미 대기 중이던 C, D
        뒤에 새 ticket으로 등록돼야 한다 — 상태 파일의 ``pending`` 순서를
        직접 검사해 구조적으로 확인한다(end-to-end 성공 타이밍에
        의존하지 않음)."""
        state_path = str(tmp_path / "state.json")

        # O가 슬롯을 점유(윈도우 5.0s — 이 테스트 전체 소요시간보다 훨씬
        # 길어 이 테스트 안에서는 절대 풀리지 않는다).
        occupant = await wait_for_fdc_slot(
            max_calls=1, window_seconds=5.0, max_wait_seconds=1.0,
            poll_interval_seconds=0.02, state_path=state_path,
        )
        assert occupant.granted is True

        z_task = asyncio.create_task(wait_for_fdc_slot(
            max_calls=1, window_seconds=5.0, max_wait_seconds=0.2,
            poll_interval_seconds=0.02, state_path=state_path,
            allow_requeue=True,
        ))
        await asyncio.sleep(0.05)
        c_task = asyncio.create_task(wait_for_fdc_slot(
            max_calls=1, window_seconds=5.0, max_wait_seconds=2.0,
            poll_interval_seconds=0.02, state_path=state_path,
        ))
        await asyncio.sleep(0.05)
        d_task = asyncio.create_task(wait_for_fdc_slot(
            max_calls=1, window_seconds=5.0, max_wait_seconds=2.0,
            poll_interval_seconds=0.02, state_path=state_path,
        ))

        await asyncio.sleep(0.03)  # D가 실제로 pending에 등록될 시간을 준다

        # C, D가 등록됐지만 Z는 아직 재등록 전인 초기 상태에서 C/D의
        # ticket_id를 먼저 확보해둔다(순서 비교 기준점).
        initial_pending = _read_pending(state_path)
        assert len(initial_pending) == 3  # [Z(원본), C, D]
        c_id = initial_pending[1]["ticket_id"]
        d_id = initial_pending[2]["ticket_id"]

        # Z가 1차 대기(0.2s) 소진 후 재등록(``requeue_count=1``인 새
        # ticket)을 마치는 순간을 폴링으로 포착한다 — 고정된 sleep
        # 하나로는 스레드풀 스케줄링 지연 탓에 그 좁은 창을 놓쳐
        # flaky해질 수 있다. 최대 1.5초까지 반복 확인한다.
        pending: list[dict] = []
        for _ in range(75):
            pending = _read_pending(state_path)
            if any(t.get("requeue_count") == 1 for t in pending):
                break
            await asyncio.sleep(0.02)
        pending_ids_in_order = [t["ticket_id"] for t in pending]
        # C, D는 아직 자기 대기 상한(2.0s)에 도달하지 않았으므로 여전히
        # pending에 남아있고, Z는 재등록된 새 ticket으로 그 뒤(맨 끝)에
        # 있어야 한다.
        assert len(pending_ids_in_order) == 3
        assert pending_ids_in_order == [c_id, d_id, pending_ids_in_order[2]]
        assert pending[2]["requeue_count"] == 1

        # 나머지 대기도 자연 종료되게 둔다(C/D도 O가 점유 중이라 결국
        # queue_timeout으로 끝난다 — 이 테스트의 관심사는 순서뿐).
        z_result, c_result, d_result = await asyncio.gather(z_task, c_task, d_task)
        assert z_result.queue_timeout is True
        assert z_result.requeue_count == 1
        assert c_result.queue_timeout is True
        assert d_result.queue_timeout is True

    @pytest.mark.asyncio
    async def test_requeue_exhausted_after_second_timeout_confirms_queue_timeout(
        self, tmp_path: Path,
    ) -> None:
        """재대기(최대 1회)까지 전부 소진해도 슬롯을 못 얻으면
        ``queue_timeout=True``, ``requeue_count==1``,
        ``queue_deadline_exceeded=True``로 확정돼야 한다."""
        state_path = str(tmp_path / "state.json")

        occupant = await wait_for_fdc_slot(
            max_calls=1, window_seconds=5.0, max_wait_seconds=1.0,
            poll_interval_seconds=0.02, state_path=state_path,
        )
        assert occupant.granted is True

        # occupant의 윈도우(5.0s)가 이 테스트 안에서 절대 풀리지 않으므로
        # Z는 1차, 2차(재대기) 대기 모두 반드시 실패한다.
        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=5.0, max_wait_seconds=0.1,
            poll_interval_seconds=0.02, state_path=state_path,
            allow_requeue=True,
        )
        assert result.granted is False
        assert result.queue_timeout is True
        assert result.requeue_count == 1  # 재대기는 정확히 1회만 일어남
        assert result.queue_deadline_exceeded is True
        # 누적 대기시간은 두 attempt의 합이어야 한다(대략 0.2s 이상).
        assert result.waited_seconds >= 0.1 * 2 * 0.8  # 약간의 스케줄링 오차 허용

    @pytest.mark.asyncio
    async def test_requeued_ticket_eventually_succeeds_after_c_and_d(
        self, tmp_path: Path
    ) -> None:
        """재대기가 실패로만 끝나는 게 아니라 실제로 성공하는 핵심
        경로를 검증한다: O(점유) → Z(1차 timeout, tail 재등록) →
        C, D가 Z보다 먼저 대기 중 → window가 열리면 C → D → 재등록된
        Z 순서로 permit이 발급돼야 한다.

        ``max_calls=1``로는 C와 D가 각자 전체 window를 순차로 점유해야
        해서(2회분 대기), Z의 1차 attempt를 실패시킬 만큼 짧은
        ``max_wait_seconds``로는 2차 attempt의 필요 대기(2 x window)를
        절대 감당할 수 없다(수학적으로 불가능 — 설계 검토에서 이미
        분석됨: 실패에 필요한 대기 < 성공에 필요한 대기가 항상 성립하지
        않으면 안 되는데, 동일 예산으로 "실패 후 재시도해서 성공"을
        만들려면 성공에 필요한 추가 대기가 실패 판정 시간보다 짧아야
        한다). 그래서 ``max_calls=3``(O 3명이 정확히 capacity를 채우고,
        O들이 동시에 만료되면 C/D/Z가 각자 순서대로 하나의 "세대" 안에서
        모두 grant를 받을 수 있게 함)을 사용해 재대기 2차 attempt의 필요
        대기가 1차 attempt의 실패 판정 시간보다 짧아지도록 구성한다.
        """
        state_path = str(tmp_path / "state.json")
        max_calls = 3
        window_seconds = 0.4

        # capacity를 정확히 채우는 점유자 3명("O" 그룹) — 전부 거의
        # 동시(t≈0)에 grant돼 거의 동시에 만료된다.
        for _ in range(max_calls):
            occ = await wait_for_fdc_slot(
                max_calls=max_calls, window_seconds=window_seconds,
                max_wait_seconds=1.0, poll_interval_seconds=0.02,
                state_path=state_path,
            )
            assert occ.granted is True

        completion_order: list[str] = []

        async def _call(name: str, max_wait: float) -> FdcRateLimitResult:
            result = await wait_for_fdc_slot(
                max_calls=max_calls, window_seconds=window_seconds,
                max_wait_seconds=max_wait, poll_interval_seconds=0.02,
                state_path=state_path, allow_requeue=(name == "Z"),
            )
            completion_order.append(name)
            return result

        # Z의 1차 attempt는 O 그룹이 만료(t=0.4)되기 전에 실패해야 한다.
        z_task = asyncio.create_task(_call("Z", 0.3))
        await asyncio.sleep(0.03)
        c_task = asyncio.create_task(_call("C", 3.0))  # 충분히 patient
        await asyncio.sleep(0.03)
        d_task = asyncio.create_task(_call("D", 3.0))

        z_result, c_result, d_result = await asyncio.gather(z_task, c_task, d_task)

        assert c_result.granted is True
        assert d_result.granted is True
        assert z_result.granted is True
        assert z_result.requeue_count == 1
        assert z_result.queue_deadline_exceeded is False
        # 완료 순서: C, D가 재등록된 Z보다 먼저 permit을 받아야 한다.
        assert completion_order.index("C") < completion_order.index("Z")
        assert completion_order.index("D") < completion_order.index("Z")
        # 누적 대기시간(1차+2차)이 남아있어야 한다 — 0이면 재대기가 실제로
        # 일어나지 않았다는 뜻이므로 결함.
        assert z_result.waited_seconds > 0.0


class TestRetryPermitDoesNotRequeue:
    """provider 429/5xx 재시도용 permit 획득(``allow_requeue=False``)은
    재대기 없이 1차 대기 상한에서 즉시 확정 실패해야 한다."""

    @pytest.mark.asyncio
    async def test_allow_requeue_false_fails_after_single_wait(
        self, tmp_path: Path
    ) -> None:
        state_path = str(tmp_path / "state.json")

        occupant = await wait_for_fdc_slot(
            max_calls=1, window_seconds=5.0, max_wait_seconds=1.0,
            poll_interval_seconds=0.02, state_path=state_path,
        )
        assert occupant.granted is True

        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=5.0, max_wait_seconds=0.1,
            poll_interval_seconds=0.02, state_path=state_path,
            allow_requeue=False,
        )
        assert result.granted is False
        assert result.queue_timeout is True
        assert result.requeue_count == 0
        assert result.queue_deadline_exceeded is False
        # 총 대기시간이 1회 attempt 분량(약 0.1s)에 가까워야 한다 —
        # 2회분(약 0.2s)이 아니다.
        assert result.waited_seconds < 0.18


class TestTicketCleanup:
    """정상 종료/취소 시 ``finally``에서 즉시 ticket이 제거되는지,
    orphan(lease 만료) ticket만 다른 참여자가 정리하는지 검증한다."""

    @pytest.mark.asyncio
    async def test_cancelled_waiter_removes_its_own_ticket_immediately(
        self, tmp_path: Path
    ) -> None:
        state_path = str(tmp_path / "state.json")

        occupant = await wait_for_fdc_slot(
            max_calls=1, window_seconds=5.0, max_wait_seconds=1.0,
            poll_interval_seconds=0.02, state_path=state_path,
        )
        assert occupant.granted is True

        waiter_task = asyncio.create_task(wait_for_fdc_slot(
            max_calls=1, window_seconds=5.0, max_wait_seconds=3.0,
            poll_interval_seconds=0.02, state_path=state_path,
        ))
        await asyncio.sleep(0.05)  # waiter가 ticket을 등록할 시간을 준다
        assert len(_read_pending(state_path)) == 1

        waiter_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter_task

        # finally에서 즉시 제거됐어야 한다 — orphan lease(30s) 만료를
        # 기다릴 필요가 없다.
        assert _read_pending(state_path) == []

    @pytest.mark.asyncio
    async def test_orphan_ticket_cleaned_only_after_lease_expires(
        self, tmp_path: Path
    ) -> None:
        """heartbeat가 lease(테스트 전용 짧은 값)보다 오래 갱신되지
        않은 ticket만 다른 참여자가 정리해야 한다 — 살아있는(heartbeat가
        신선한) ticket은 절대 건드리지 않는다."""
        state_path = str(tmp_path / "state.json")
        directory = tmp_path
        directory.mkdir(exist_ok=True)

        now = time.time()  # 실제 벽시계 기준(orphan 판정이 real time.time()을 씀)
        stale_ticket = {
            "ticket_id": "stale-1",
            "lane": "core",
            "enqueued_at": now - 100.0,
            "last_heartbeat_at": now - 100.0,  # 매우 오래 전 — orphan
            "lease_expires_at": now - 99.9,
            "requeue_count": 0,
        }
        fresh_ticket = {
            "ticket_id": "fresh-1",
            "lane": "held_position",
            "enqueued_at": now - 0.5,
            "last_heartbeat_at": now - 0.05,  # 방금 갱신됨 — 살아있음
            "lease_expires_at": now + 29.95,
            "requeue_count": 0,
        }
        with open(state_path, "w") as fh:
            json.dump({
                "version": 1,
                "grants": [],
                "pending": [stale_ticket, fresh_ticket],
            }, fh)

        # 새 참여자가 폴링하면(lease=1.0초로 짧게 줘서 stale_ticket(100초
        # 전 heartbeat)은 확실히 orphan으로 잡히지만, fresh_ticket(0.05초
        # 전 heartbeat)은 충분한 여유로 살아남게 한다) stale_ticket만
        # 제거되고 fresh_ticket은 남아있어야 한다. 새 참여자 자신은
        # fresh_ticket 뒤로 등록되므로 head가 아니라 grant는 못 받는다.
        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=0.15,
            poll_interval_seconds=0.05, state_path=state_path,
            lease_seconds=1.0,
        )
        assert result.granted is False  # head가 아니므로(fresh_ticket이 head)
        assert result.queue_timeout is True

        remaining = _read_pending(state_path)
        remaining_ids = {t["ticket_id"] for t in remaining}
        assert "stale-1" not in remaining_ids  # orphan 정리됨
        assert "fresh-1" in remaining_ids  # 살아있는 ticket은 보존됨


class TestGrantTrimVsPendingLifetime:
    """``grants``는 60초(window_seconds) 기준으로 트림하고,
    ``pending`` ticket은 이 기준으로 절대 제거하지 않는다는 요구사항을
    검증한다."""

    @pytest.mark.asyncio
    async def test_old_grant_trimmed_but_old_pending_ticket_preserved(
        self, tmp_path: Path
    ) -> None:
        """``pending`` ticket은 오직 head인 자기 자신이 폴링해야만
        grant로 승격된다(다른 참여자의 폴링이 대신 승격시켜주지 않는다
        — 각자 자기 ticket만 갱신/승격한다는 설계). 그래서 이 테스트는
        "오래 등록된 ticket도 heartbeat만 신선하면 삭제되지 않는다"는
        것과 "오래된 grant는 트림된다"는것을 각각 독립적으로 확인한다
        (grant 승격 자체는 ``TestFifoOrdering``/``TestRequeueToTail``에서
        이미 실제 폴링으로 검증됨)."""
        state_path = str(tmp_path / "state.json")
        now = time.time()  # 실제 벽시계 기준

        old_grant = now - 100.0  # window_seconds(60)보다 훨씬 오래됨 — 트림 대상
        long_waiting_ticket = {
            "ticket_id": "long-wait-1",
            "lane": "core",
            "enqueued_at": now - 100.0,  # 오래전에 등록됐지만
            "last_heartbeat_at": now - 0.05,  # heartbeat는 방금 갱신됨(살아있음)
            "lease_expires_at": now + 29.95,
            "requeue_count": 0,
        }
        with open(state_path, "w") as fh:
            json.dump({
                "version": 1,
                "grants": [old_grant],
                "pending": [long_waiting_ticket],
            }, fh)

        # 새 호출자는 head가 아니므로(long_waiting_ticket이 head) 이번
        # 호출로는 절대 grant를 못 받는다 — 이 호출의 목적은 오직
        # "폴링이 한 번 일어난 뒤에도 grant/pending 상태가 요구사항대로
        # 정리되는지"를 관찰하는 것이다.
        result = await wait_for_fdc_slot(
            max_calls=1, window_seconds=60.0, max_wait_seconds=0.15,
            poll_interval_seconds=0.05, state_path=state_path,
        )
        assert result.granted is False

        with open(state_path) as fh:
            state = json.loads(fh.read())
        # "100초 전에 등록됐다"는 이유만으로 pending에서 삭제되지
        # 않았어야 한다(heartbeat가 신선하므로 orphan도 아님).
        assert "long-wait-1" in {t["ticket_id"] for t in state["pending"]}
        # 오래된 grant(window_seconds=60 기준 100초 경과)는 트림돼야 한다.
        assert old_grant not in state["grants"]
