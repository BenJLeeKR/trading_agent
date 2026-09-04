"""Tests for ``scripts/fdc_manual_provider_gate.py``(2026-08-27 PR A 신설).

fake clock/fake repository/fake session provider만 사용한다 — 실제
sleep, 실제 DB, 실제 Gemini/KIS 호출은 전혀 하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from agent_trading.repositories.contracts import ReservationGrant
from agent_trading.repositories.memory import InMemoryFdcQuotaRepository
from agent_trading.services.ai_agents.base import RawProviderResponse
from agent_trading.services.fdc_provider_global_gate import FdcProviderGlobalGate
from agent_trading.services.fdc_quota_coordinator import FdcQuotaCoordinator
from agent_trading.services.market_session import SessionInfo
from scripts import fdc_manual_provider_gate as gate


@dataclass(slots=True, frozen=True)
class _FakeOutput:
    symbol: str = ""


async def _always_allow_manual_call_policy() -> bool:
    return True


def _make_coordinator(*, target_rpm: int = 13) -> FdcQuotaCoordinator:
    """이 헬퍼가 만드는 coordinator는 ``manual:`` caller를 항상 허용하는
    정책을 기본 주입한다 — 이 파일의 기존 테스트들은 quota/lifecycle
    메커니즘 자체를 검증하는 것이 목적이며, 2026-08-27 3차 리뷰 보정으로
    신설된 운영 시간 중앙 fail-closed 경계(``TestManualCallPolicy``,
    ``test_fdc_quota_coordinator.py`` 참고)는 별도로 검증한다."""
    return FdcQuotaCoordinator(
        repo=InMemoryFdcQuotaRepository(),
        target_rpm=target_rpm,
        quota_scope="test:manual-gate",
        manual_call_policy=_always_allow_manual_call_policy,
    )


class _FakeClient:
    """``call_with_coordinator()``가 요구하는 최소 duck-typed 인터페이스
    (``generate_structured_once()``)만 흉내낸다 — 실제 HTTP 없음.

    ``on_http_start`` 훅을 실제 ``LiveGeminiProviderClient``와 동일한
    계약으로 시뮬레이션한다: ``client.post()``에 해당하는 "실행"
    직전에 정확히 1회 호출하고, 훅이 예외를 던지면 그 "실행"(=이번
    테스트에서는 ``outcomes``에서 결과를 꺼내는 것) 자체를 하지 않는다
    (2026-08-27 2차 리뷰 보정)."""

    def __init__(
        self,
        outcomes: list[Any],
        *,
        on_http_start_failures: list[Exception | None] | None = None,
    ) -> None:
        # 각 원소가 예외 인스턴스면 raise, 아니면 RawProviderResponse로 반환.
        self._outcomes = list(outcomes)
        # outcomes와 병렬로 소비된다 — None이면 훅이 정상 실행됨.
        self._on_http_start_failures = list(on_http_start_failures or [])
        self.calls: list[tuple[ReservationGrant, int]] = []
        self.http_started_count = 0

    async def generate_structured_once(
        self, grant: ReservationGrant, *, expected_job_id, expected_attempt_no,
        on_http_start=None, **kwargs,
    ) -> RawProviderResponse:
        hook_failure = (
            self._on_http_start_failures.pop(0) if self._on_http_start_failures else None
        )
        if on_http_start is not None:
            if hook_failure is not None:
                raise hook_failure
            await on_http_start()
            self.http_started_count += 1

        self.calls.append((grant, expected_attempt_no))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _success_response() -> RawProviderResponse:
    return RawProviderResponse(
        parsed=_FakeOutput(symbol="AAPL"), raw_content="{}",
        http_attempt_count=1, http_429_count=0,
    )


def _retryable_429() -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://x/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    exc = httpx.HTTPStatusError("429", request=req, response=resp)
    exc.http_attempt_count = 1  # type: ignore[attr-defined]
    exc.http_429_count = 1  # type: ignore[attr-defined]
    return exc


def _non_retryable_400() -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://x/v1/chat/completions")
    resp = httpx.Response(400, request=req)
    exc = httpx.HTTPStatusError("400", request=req, response=resp)
    exc.http_attempt_count = 1  # type: ignore[attr-defined]
    exc.http_429_count = 0  # type: ignore[attr-defined]
    return exc


def _attempt_outcome(coordinator: FdcQuotaCoordinator, reservation_id: UUID) -> str:
    """InMemory 내부를 직접 들여다봐서 기록된 outcome을 확인한다(테스트 전용)."""
    return coordinator._repo._attempts_by_id[reservation_id].outcome  # type: ignore[attr-defined]


def _attempt_http_started_at(coordinator: FdcQuotaCoordinator, reservation_id: UUID):
    """InMemory 내부의 ``http_started_at``을 직접 조회한다(테스트 전용)."""
    return coordinator._repo._attempts_by_id[reservation_id].http_started_at  # type: ignore[attr-defined]


class TestCallWithCoordinator:
    @pytest.mark.asyncio
    async def test_success_records_http_succeeded(self) -> None:
        coordinator = _make_coordinator()
        client = _FakeClient([_success_response()])

        result = await gate.call_with_coordinator(
            coordinator=coordinator, client=client, caller_id="manual:test",
            manual_run_id="run-1", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_FakeOutput,
        )

        assert result.parsed.symbol == "AAPL"
        assert len(client.calls) == 1
        grant, attempt_no = client.calls[0]
        assert attempt_no == 1
        assert _attempt_outcome(coordinator, grant.reservation_id) == "http_succeeded"

    @pytest.mark.asyncio
    async def test_quota_denied_sends_no_http(self) -> None:
        coordinator = _make_coordinator(target_rpm=1)
        client = _FakeClient([_success_response()])
        # 첫 reservation으로 window를 가득 채운다(target_rpm=1).
        first = await coordinator.try_reserve(job_id=None, caller_id="filler")
        assert isinstance(first, ReservationGrant)

        with pytest.raises(gate.QuotaUnavailableError):
            await gate.call_with_coordinator(
                coordinator=coordinator, client=client, caller_id="manual:test",
                manual_run_id="run-2", model_id="m", system_prompt="s",
                user_prompt="u", response_format=_FakeOutput,
            )

        assert client.calls == []  # HTTP 0회

    @pytest.mark.asyncio
    async def test_retryable_failure_gets_new_reservation_then_succeeds(self) -> None:
        coordinator = _make_coordinator()
        client = _FakeClient([_retryable_429(), _success_response()])

        result = await gate.call_with_coordinator(
            coordinator=coordinator, client=client, caller_id="manual:test",
            manual_run_id="run-3", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_FakeOutput, max_attempts=3,
        )

        assert result.parsed.symbol == "AAPL"
        assert len(client.calls) == 2
        first_grant, first_attempt = client.calls[0]
        second_grant, second_attempt = client.calls[1]
        assert first_attempt == 1
        assert second_attempt == 2
        assert first_grant.reservation_id != second_grant.reservation_id  # 새 reservation
        assert _attempt_outcome(coordinator, first_grant.reservation_id) == "http_failed_retryable"
        assert _attempt_outcome(coordinator, second_grant.reservation_id) == "http_succeeded"

    @pytest.mark.asyncio
    async def test_non_retryable_failure_raises_immediately(self) -> None:
        coordinator = _make_coordinator()
        client = _FakeClient([_non_retryable_400(), _success_response()])

        with pytest.raises(httpx.HTTPStatusError):
            await gate.call_with_coordinator(
                coordinator=coordinator, client=client, caller_id="manual:test",
                manual_run_id="run-4", model_id="m", system_prompt="s",
                user_prompt="u", response_format=_FakeOutput, max_attempts=3,
            )

        assert len(client.calls) == 1  # 재시도하지 않음
        grant, _ = client.calls[0]
        assert _attempt_outcome(coordinator, grant.reservation_id) == "http_failed_final"

    @pytest.mark.asyncio
    async def test_success_records_http_started_at_before_completion(self) -> None:
        """2026-08-27 2차 리뷰 보정: 성공 시 ``http_started_at``이
        실제로 기록되는지(이전에는 전혀 기록되지 않는 경로가 있었다)."""
        coordinator = _make_coordinator()
        client = _FakeClient([_success_response()])

        await gate.call_with_coordinator(
            coordinator=coordinator, client=client, caller_id="manual:test",
            manual_run_id="run-5", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_FakeOutput,
        )

        grant, _ = client.calls[0]
        assert _attempt_http_started_at(coordinator, grant.reservation_id) is not None
        assert client.http_started_count == 1

    @pytest.mark.asyncio
    async def test_pre_http_failure_records_reserved_but_http_not_started_and_retries(
        self,
    ) -> None:
        """HTTP 시작 훅(client.post() 직전) 자체가 실패하면(예: 감사
        기록 DB 오류) client.post()에 해당하는 실행이 전혀 일어나지
        않아야 하고, 그 attempt는 ``reserved_but_http_not_started``로
        기록돼야 하며, ``http_started_at``은 그대로 NULL이어야 한다.
        새 reservation으로 재시도한다."""
        coordinator = _make_coordinator()
        client = _FakeClient(
            [_success_response()],
            on_http_start_failures=[RuntimeError("hook db write failed")],
        )

        result = await gate.call_with_coordinator(
            coordinator=coordinator, client=client, caller_id="manual:test",
            manual_run_id="run-6", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_FakeOutput, max_attempts=3,
        )

        assert result.parsed.symbol == "AAPL"
        # 훅이 실패한 첫 attempt는 client.calls에 기록되지 않는다(실행 자체가
        # 없었다는 뜻 — 이 fake의 "실행"은 outcome을 꺼내 반환/raise하는 것).
        assert len(client.calls) == 1
        assert client.http_started_count == 1  # 두 번째(성공) attempt만 훅 성공

        # 첫 reservation(실패한 것)은 client.calls에 없으므로 별도로 조회해야
        # 한다 — coordinator 내부 전체 attempt 목록에서 찾는다.
        all_attempts = list(
            coordinator._repo._attempts["test:manual-gate"]  # type: ignore[attr-defined]
        )
        assert len(all_attempts) == 2  # 실패 1건 + 성공 1건 = 별도 reservation 2개
        failed_entry = next(a for a in all_attempts if a.outcome != "http_succeeded")
        assert failed_entry.outcome == "reserved_but_http_not_started"
        assert failed_entry.http_started_at is None  # HTTP가 실제로 시작되지 않았다

    @pytest.mark.asyncio
    async def test_pre_http_failure_all_attempts_exhausted_raises(self) -> None:
        coordinator = _make_coordinator()
        client = _FakeClient(
            [_success_response(), _success_response()],
            on_http_start_failures=[
                RuntimeError("fail-1"), RuntimeError("fail-2"),
            ],
        )

        with pytest.raises(RuntimeError, match="fail-2"):
            await gate.call_with_coordinator(
                coordinator=coordinator, client=client, caller_id="manual:test",
                manual_run_id="run-6b", model_id="m", system_prompt="s",
                user_prompt="u", response_format=_FakeOutput, max_attempts=2,
            )

        assert client.calls == []  # client.post()에 해당하는 실행이 단 한 번도 없었다

    @pytest.mark.asyncio
    async def test_duplicate_http_started_recording_is_fail_closed(self) -> None:
        """같은 reservation에 ``outcome="http_started"``를 두 번 기록하려
        하면 명시적으로 실패한다(하나의 reservation은 하나의 실제
        실행 기회에만 대응해야 한다는 계약)."""
        coordinator = _make_coordinator()
        grant = await coordinator.try_reserve(job_id=None, caller_id="manual:test")
        assert isinstance(grant, ReservationGrant)

        from datetime import datetime, timezone

        await coordinator.record_attempt_outcome(
            reservation_id=grant.reservation_id, outcome="http_started",
            http_started_at=datetime.now(timezone.utc),
        )

        with pytest.raises(ValueError, match="already has http_started_at"):
            await coordinator.record_attempt_outcome(
                reservation_id=grant.reservation_id, outcome="http_started",
                http_started_at=datetime.now(timezone.utc),
            )


async def _grant_only(coordinator: FdcQuotaCoordinator) -> ReservationGrant:
    result = await coordinator.try_reserve(job_id=None, caller_id="manual:test")
    assert isinstance(result, ReservationGrant)
    return result


class TestExecuteFdcOneShotAttemptGlobalGate:
    """PR D(2026-09-03) — ``execute_fdc_one_shot_attempt()``의
    ``global_gate`` 주입 지점. gate 호출은 ``record_attempt_outcome
    (outcome="http_started")`` 직전(=``client.post()`` 전)에 일어나므로,
    gate가 거부하면 ``_FakeClient.calls``(=실제 HTTP에 해당)가 전혀
    늘어나지 않는다는 것으로 "실제 HTTP 0회"를 직접 증명한다."""

    @pytest.mark.asyncio
    async def test_gate_granted_allows_http_normally(self) -> None:
        coordinator = _make_coordinator()
        global_gate = FdcProviderGlobalGate(
            repo=InMemoryFdcQuotaRepository(), target_rpm=13, window_seconds=60,
        )
        client = _FakeClient([_success_response()])

        result = await gate.execute_fdc_one_shot_attempt(
            coordinator=coordinator, client=client,
            grant=await _grant_only(coordinator),
            job_id=None, attempt_no=1, model_id="m", system_prompt="s",
            user_prompt="u", response_format=_FakeOutput,
            temperature=0.0, seed=None, global_gate=global_gate,
        )

        assert result.parsed.symbol == "AAPL"
        assert len(client.calls) == 1, "gate가 grant했으므로 실제 HTTP가 1회 나가야 한다"

    @pytest.mark.asyncio
    async def test_gate_denied_window_full_sends_zero_http_and_records_reserved_but_not_started(
        self,
    ) -> None:
        coordinator = _make_coordinator()
        global_gate = FdcProviderGlobalGate(
            repo=InMemoryFdcQuotaRepository(), target_rpm=1, window_seconds=60,
        )
        # target_rpm=1인 정상 설정에서 첫 grant로 window를 채워 포화
        # 상태를 만든다(invalid config에 의존하지 않는다).
        prefill = await global_gate.acquire(caller_lane="legacy", caller_id="prefill")
        assert prefill.granted is True
        client = _FakeClient([_success_response()])
        grant = await _grant_only(coordinator)

        with pytest.raises(gate._RetryableAttemptError) as exc_info:
            await gate.execute_fdc_one_shot_attempt(
                coordinator=coordinator, client=client, grant=grant,
                job_id=None, attempt_no=1, model_id="m", system_prompt="s",
                user_prompt="u", response_format=_FakeOutput,
                temperature=0.0, seed=None, global_gate=global_gate,
            )

        cause = exc_info.value.__cause__
        assert isinstance(cause, gate.PermitDeniedError)
        assert cause.result.denial_reason == "global_gate_timeout"
        assert client.calls == [], "gate가 거부했으므로 실제 HTTP는 0회여야 한다"
        assert client.http_started_count == 0
        assert _attempt_outcome(coordinator, grant.reservation_id) == (
            "reserved_but_http_not_started"
        )

    @pytest.mark.asyncio
    async def test_gate_error_sends_zero_http_and_denial_reason_is_global_gate_error(
        self,
    ) -> None:
        coordinator = _make_coordinator()

        class _FailingGateRepo:
            async def try_acquire_provider_global_gate_permit(self, **kwargs: Any):
                from agent_trading.repositories.contracts import (
                    CoordinatorError,
                    CoordinatorErrorClass,
                )
                return CoordinatorError(
                    CoordinatorErrorClass.COORDINATOR_UNAVAILABLE, "db down",
                )

        global_gate = FdcProviderGlobalGate(
            repo=_FailingGateRepo(), target_rpm=13, window_seconds=60,
        )
        client = _FakeClient([_success_response()])
        grant = await _grant_only(coordinator)

        with pytest.raises(gate._RetryableAttemptError) as exc_info:
            await gate.execute_fdc_one_shot_attempt(
                coordinator=coordinator, client=client, grant=grant,
                job_id=None, attempt_no=1, model_id="m", system_prompt="s",
                user_prompt="u", response_format=_FakeOutput,
                temperature=0.0, seed=None, global_gate=global_gate,
            )

        cause = exc_info.value.__cause__
        assert isinstance(cause, gate.PermitDeniedError)
        assert cause.result.denial_reason == "global_gate_error"
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_gate_none_is_full_noop_regression(self) -> None:
        """``global_gate`` 기본값(``None``)은 gate 호출 자체가 없다 —
        기존(PR D 이전) 동작과 100% 동일하다(회귀 방지)."""
        coordinator = _make_coordinator()
        client = _FakeClient([_success_response()])

        result = await gate.execute_fdc_one_shot_attempt(
            coordinator=coordinator, client=client,
            grant=await _grant_only(coordinator),
            job_id=None, attempt_no=1, model_id="m", system_prompt="s",
            user_prompt="u", response_format=_FakeOutput,
            temperature=0.0, seed=None,
        )
        assert result.parsed.symbol == "AAPL"
        assert len(client.calls) == 1

    @pytest.mark.asyncio
    async def test_429_retry_calls_gate_exactly_once_per_attempt(self) -> None:
        """429 재시도 2회 시나리오 — global gate는 attempt마다(=재시도
        포함) 정확히 1회씩 통과해야 한다(이중 계산/누락 없음). attempt 1은
        429(post-HTTP retryable)로 실패, 호출자(여기서는 테스트가 직접
        dispatcher 재시도 루프를 흉내낸다)가 새 grant로 attempt 2를
        시도해 성공한다."""
        coordinator = _make_coordinator()
        call_count = {"n": 0}
        inner_repo = InMemoryFdcQuotaRepository()

        class _CountingGateRepo:
            async def try_acquire_provider_global_gate_permit(self, **kwargs: Any):
                call_count["n"] += 1
                return await inner_repo.try_acquire_provider_global_gate_permit(**kwargs)

        global_gate = FdcProviderGlobalGate(
            repo=_CountingGateRepo(), target_rpm=13, window_seconds=60,
        )

        client = _FakeClient([_retryable_429(), _success_response()])
        result = None
        for attempt_no in (1, 2):
            grant = await _grant_only(coordinator)
            try:
                result = await gate.execute_fdc_one_shot_attempt(
                    coordinator=coordinator, client=client, grant=grant,
                    job_id=None, attempt_no=attempt_no, model_id="m",
                    system_prompt="s", user_prompt="u",
                    response_format=_FakeOutput, temperature=0.0, seed=None,
                    global_gate=global_gate,
                )
                break
            except gate._RetryableAttemptError:
                continue
        assert call_count["n"] == 2, "attempt마다 gate가 정확히 1회씩 호출돼야 한다"
        assert result is not None and result.parsed.symbol == "AAPL"


class TestCoordinatedFdcProviderClient:
    """2026-08-27 리뷰 보정으로 신설 — ``make_coordinator_permit_adapter()``
    /``finalize_permit_adapter_outcomes()``(부정확한 사후 일괄 기록)를
    대체한다. ``AIProviderClient`` Protocol을 만족하는 wrapper이며,
    내부적으로 이미 검증된 ``call_with_coordinator()``만 위임 호출한다
    (중복 구현 없음 — 정확성은 ``TestCallWithCoordinator``가 이미 증명)."""

    @pytest.mark.asyncio
    async def test_delegates_to_call_with_coordinator(self) -> None:
        coordinator = _make_coordinator()
        fake_live_client = _FakeClient([_success_response()])
        wrapper = gate.CoordinatedFdcProviderClient(
            coordinator=coordinator, live_client=fake_live_client,
            caller_id="manual:test", manual_run_id="run-7",
        )

        result = await wrapper.generate_structured(
            model_id="m", system_prompt="s", user_prompt="u",
            response_format=_FakeOutput,
        )

        assert result.parsed.symbol == "AAPL"
        assert len(fake_live_client.calls) == 1
        grant, _ = fake_live_client.calls[0]
        assert _attempt_outcome(coordinator, grant.reservation_id) == "http_succeeded"

    @pytest.mark.asyncio
    async def test_rejects_acquire_permit_argument(self) -> None:
        """레거시 permit 어댑터를 실수로 다시 연결하려는 시도를 방어적으로
        막는다 — coordinator가 매 HTTP 시도를 전담하므로 별도 permit
        콜백이 끼어들면 안 된다."""
        coordinator = _make_coordinator()
        wrapper = gate.CoordinatedFdcProviderClient(
            coordinator=coordinator, live_client=_FakeClient([_success_response()]),
            caller_id="manual:test", manual_run_id="run-8",
        )

        async def _dummy_permit():
            raise AssertionError("호출되면 안 된다")

        with pytest.raises(ValueError, match="acquire_permit"):
            await wrapper.generate_structured(
                model_id="m", system_prompt="s", user_prompt="u",
                response_format=_FakeOutput, acquire_permit=_dummy_permit,
            )

    @pytest.mark.asyncio
    async def test_quota_denied_propagates_and_sends_no_http(self) -> None:
        coordinator = _make_coordinator(target_rpm=1)
        filler = await coordinator.try_reserve(job_id=None, caller_id="filler")
        assert isinstance(filler, ReservationGrant)
        fake_live_client = _FakeClient([_success_response()])
        wrapper = gate.CoordinatedFdcProviderClient(
            coordinator=coordinator, live_client=fake_live_client,
            caller_id="manual:test", manual_run_id="run-9",
        )

        with pytest.raises(gate.QuotaUnavailableError):
            await wrapper.generate_structured(
                model_id="m", system_prompt="s", user_prompt="u",
                response_format=_FakeOutput,
            )

        assert fake_live_client.calls == []


class TestAssertNotMarketHours:
    @pytest.mark.asyncio
    async def test_blocks_on_trading_day(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_provider = AsyncMock()
        fake_provider.get_session_info = AsyncMock(
            return_value=SessionInfo(is_trading_day=True, source="fallback")
        )

        async def _fake_create_session_provider():
            return fake_provider

        monkeypatch.setattr(gate, "create_session_provider", _fake_create_session_provider)

        with pytest.raises(gate.MarketHoursBlockedError):
            await gate.assert_not_market_hours(script_name="test_script")

    @pytest.mark.asyncio
    async def test_allows_on_non_trading_day(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_provider = AsyncMock()
        fake_provider.get_session_info = AsyncMock(
            return_value=SessionInfo(is_trading_day=False, source="fallback")
        )

        async def _fake_create_session_provider():
            return fake_provider

        monkeypatch.setattr(gate, "create_session_provider", _fake_create_session_provider)

        # 예외 없이 정상 반환돼야 한다.
        await gate.assert_not_market_hours(script_name="test_script")


class TestBuildManualCallPolicy:
    """``build_manual_call_policy()``(2026-08-27 3차 리뷰 보정 신설) —
    ``assert_not_market_hours()``를 coordinator가 요구하는
    ``Callable[[], Awaitable[bool]]`` 모양으로 감싼다."""

    @pytest.mark.asyncio
    async def test_returns_false_on_trading_day(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_provider = AsyncMock()
        fake_provider.get_session_info = AsyncMock(
            return_value=SessionInfo(is_trading_day=True, source="fallback")
        )

        async def _fake_create_session_provider():
            return fake_provider

        monkeypatch.setattr(gate, "create_session_provider", _fake_create_session_provider)

        policy = gate.build_manual_call_policy(script_name="test_script")
        allowed = await policy()

        assert allowed is False

    @pytest.mark.asyncio
    async def test_returns_true_on_non_trading_day(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_provider = AsyncMock()
        fake_provider.get_session_info = AsyncMock(
            return_value=SessionInfo(is_trading_day=False, source="fallback")
        )

        async def _fake_create_session_provider():
            return fake_provider

        monkeypatch.setattr(gate, "create_session_provider", _fake_create_session_provider)

        policy = gate.build_manual_call_policy(script_name="test_script")
        allowed = await policy()

        assert allowed is True

    @pytest.mark.asyncio
    async def test_policy_wired_into_coordinator_blocks_on_trading_day(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """이 정책을 실제로 ``FdcQuotaCoordinator``에 주입했을 때
        거래일이면 reservation이 거부되고, 비거래일이면 승인되는지
        end-to-end로 확인한다."""
        fake_provider = AsyncMock()
        fake_provider.get_session_info = AsyncMock(
            return_value=SessionInfo(is_trading_day=True, source="fallback")
        )

        async def _fake_create_session_provider():
            return fake_provider

        monkeypatch.setattr(gate, "create_session_provider", _fake_create_session_provider)

        coordinator = FdcQuotaCoordinator(
            repo=InMemoryFdcQuotaRepository(),
            target_rpm=13,
            quota_scope="test:manual-policy-e2e",
            manual_call_policy=gate.build_manual_call_policy(script_name="test_script"),
        )

        result = await coordinator.try_reserve(job_id=None, caller_id="manual:test_script")

        from agent_trading.repositories.contracts import CoordinatorError
        assert isinstance(result, CoordinatorError)


class TestBuildManualRunId:
    def test_contains_script_name_and_is_unique(self) -> None:
        id1 = gate.build_manual_run_id(script_name="ar_fdc_provider_validation")
        id2 = gate.build_manual_run_id(script_name="ar_fdc_provider_validation")

        assert id1.startswith("ar_fdc_provider_validation:")
        assert id1 != id2  # 재실행마다 충돌하지 않아야 한다

    def test_different_scripts_produce_distinguishable_ids(self) -> None:
        id1 = gate.build_manual_run_id(script_name="ar_fdc_provider_validation")
        id2 = gate.build_manual_run_id(script_name="ar_fdc_output_measurement")

        assert id1.split(":")[0] != id2.split(":")[0]


class _RecordingSleep:
    """실제 sleep 없이 대기 호출 횟수/인자를 기록하는 fake clock. 특정
    호출 시점에 side effect(quota 회복 시뮬레이션 등)를 실행할 수 있다."""

    def __init__(self, *, on_call: Any = None) -> None:
        self.calls: list[float] = []
        self._on_call = on_call

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self._on_call is not None:
            self._on_call(len(self.calls))


class TestRunRealDispatchJob:
    """``run_real_dispatch_job()``(2026-08-27 신설, PR #359 리뷰 보정) —
    실제 dispatcher job 하나의 FIFO 대기 + provider one-shot 실행을
    검증한다. fake clock(``sleep_fn``)만 쓰고 실제 sleep은 전혀 하지
    않는다."""

    @pytest.mark.asyncio
    async def test_immediate_grant_succeeds_without_waiting(self) -> None:
        coordinator = _make_coordinator(target_rpm=13)
        job_id = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="test:manual-gate",
            fdc_ready_at=datetime.now(
                timezone.utc
            ),
        )
        client = _FakeClient([_success_response()])
        sleep = _RecordingSleep()

        result = await gate.run_real_dispatch_job(
            coordinator=coordinator, client=client, job_id=job_id,
            caller_id="ops-scheduler:held_position_reduce_sell",
            manual_run_id="cycle-1", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_FakeOutput, sleep_fn=sleep,
        )

        assert result.parsed.symbol == "AAPL"
        assert len(client.calls) == 1
        assert sleep.calls == []  # 대기 없이 즉시 grant

    @pytest.mark.asyncio
    async def test_quota_full_waits_then_succeeds_after_capacity_frees(self) -> None:
        """quota가 가득 차면 fallback HOLD로 즉시 포기하지 않고, 대기
        후 재시도해 결국 승인·성공한다(§4 "순번 탈락 금지" 핵심 검증)."""
        coordinator = _make_coordinator(target_rpm=1)
        # window를 가득 채운다.
        filler = await coordinator.try_reserve(job_id=None, caller_id="filler")
        assert isinstance(filler, ReservationGrant)

        job_id = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="test:manual-gate",
            fdc_ready_at=datetime.now(
                timezone.utc
            ),
        )
        client = _FakeClient([_success_response()])

        def _free_capacity_on_first_wait(call_count: int) -> None:
            if call_count == 1:
                # "60초 창이 지나 slot이 회복됐다"를 시뮬레이션 —
                # filler attempt를 window 밖으로 밀어낸다.
                coordinator._repo._attempts["test:manual-gate"].clear()  # type: ignore[attr-defined]

        sleep = _RecordingSleep(on_call=_free_capacity_on_first_wait)

        result = await gate.run_real_dispatch_job(
            coordinator=coordinator, client=client, job_id=job_id,
            caller_id="ops-scheduler:held_position_reduce_sell",
            manual_run_id="cycle-1", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_FakeOutput, sleep_fn=sleep,
            poll_interval_seconds=1.0,
        )

        assert result.parsed.symbol == "AAPL"
        assert len(sleep.calls) == 1  # 정확히 1번 대기 후 성공
        assert len(client.calls) == 1  # HTTP는 승인된 뒤 정확히 1회

    @pytest.mark.asyncio
    async def test_later_job_waits_for_earlier_job_fifo(self) -> None:
        """14번째 이후 job이 fallback HOLD로 끝나지 않고 FIFO 순서로
        대기하다가, 앞선 job이 종결되면 승인·성공하는지 검증한다."""
        coordinator = _make_coordinator(target_rpm=13)
        job_a = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope="test:manual-gate",
            fdc_ready_at=datetime.now(
                timezone.utc
            ),
        )
        job_b = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="B",
            source_type="held_position", quota_scope="test:manual-gate",
            fdc_ready_at=datetime.now(
                timezone.utc
            ),
        )
        client_b = _FakeClient([_success_response()])

        def _resolve_job_a_on_first_wait(call_count: int) -> None:
            if call_count == 1:
                # job A가 처리 완료돼 더 이상 QUEUED가 아니게 됐다고
                # 가정한다 — B의 순번이 돌아온다.
                coordinator._repo._jobs[job_a]["status"] = "FDC_SUCCEEDED"  # type: ignore[attr-defined]

        sleep = _RecordingSleep(on_call=_resolve_job_a_on_first_wait)

        result = await gate.run_real_dispatch_job(
            coordinator=coordinator, client=client_b, job_id=job_b,
            caller_id="ops-scheduler:held_position_reduce_sell",
            manual_run_id="cycle-1", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_FakeOutput, sleep_fn=sleep,
            poll_interval_seconds=1.0,
        )

        assert result.parsed.symbol == "AAPL"
        assert len(sleep.calls) == 1  # A가 해소될 때까지 정확히 1번 대기
        assert len(client_b.calls) == 1

    @pytest.mark.asyncio
    async def test_coordinator_error_backs_off_then_recovers(self) -> None:
        """coordinator 오류(DB unavailable 등)는 HTTP 0회로 fail-closed
        하고, 지수 backoff 후 재시도해 DB가 복구되면 즉시 정상 재개된다."""
        coordinator = _make_coordinator(target_rpm=13)
        job_id = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="test:manual-gate",
            fdc_ready_at=datetime.now(
                timezone.utc
            ),
        )
        client = _FakeClient([_success_response()])

        real_try_reserve = coordinator.try_reserve
        call_count = 0

        async def _flaky_try_reserve(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                from agent_trading.repositories.contracts import (
                    CoordinatorError,
                    CoordinatorErrorClass,
                )
                return CoordinatorError(
                    CoordinatorErrorClass.COORDINATOR_UNAVAILABLE, "simulated DB down"
                )
            return await real_try_reserve(**kwargs)

        coordinator.try_reserve = _flaky_try_reserve  # type: ignore[method-assign]

        sleep = _RecordingSleep()

        result = await gate.run_real_dispatch_job(
            coordinator=coordinator, client=client, job_id=job_id,
            caller_id="ops-scheduler:held_position_reduce_sell",
            manual_run_id="cycle-1", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_FakeOutput, sleep_fn=sleep,
            coordinator_error_backoff_initial_seconds=1.0,
            coordinator_error_backoff_max_seconds=30.0,
        )

        assert result.parsed.symbol == "AAPL"
        assert len(client.calls) == 1  # coordinator 오류 동안 HTTP 0회
        # 2번의 coordinator 오류 → backoff 1초, 2초(지수 증가)로 대기.
        assert sleep.calls == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_provider_retryable_failure_uses_new_reservation(self) -> None:
        coordinator = _make_coordinator(target_rpm=13)
        job_id = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="test:manual-gate",
            fdc_ready_at=datetime.now(
                timezone.utc
            ),
        )
        client = _FakeClient([_retryable_429(), _success_response()])
        sleep = _RecordingSleep()

        result = await gate.run_real_dispatch_job(
            coordinator=coordinator, client=client, job_id=job_id,
            caller_id="ops-scheduler:held_position_reduce_sell",
            manual_run_id="cycle-1", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_FakeOutput, sleep_fn=sleep,
        )

        assert result.parsed.symbol == "AAPL"
        assert len(client.calls) == 2
        grant1, _ = client.calls[0]
        grant2, _ = client.calls[1]
        assert grant1.reservation_id != grant2.reservation_id  # 새 reservation

    @pytest.mark.asyncio
    async def test_provider_exhausted_raises_original_exception(self) -> None:
        coordinator = _make_coordinator(target_rpm=13)
        job_id = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="test:manual-gate",
            fdc_ready_at=datetime.now(
                timezone.utc
            ),
        )
        client = _FakeClient([_retryable_429(), _retryable_429(), _retryable_429()])
        sleep = _RecordingSleep()

        with pytest.raises(httpx.HTTPStatusError):
            await gate.run_real_dispatch_job(
                coordinator=coordinator, client=client, job_id=job_id,
                caller_id="ops-scheduler:held_position_reduce_sell",
                manual_run_id="cycle-1", model_id="m", system_prompt="s",
                user_prompt="u", response_format=_FakeOutput, sleep_fn=sleep,
                max_provider_attempts=3,
            )

        assert len(client.calls) == 3

    @pytest.mark.asyncio
    async def test_non_retryable_failure_raises_immediately_no_wait(self) -> None:
        coordinator = _make_coordinator(target_rpm=13)
        job_id = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="test:manual-gate",
            fdc_ready_at=datetime.now(
                timezone.utc
            ),
        )
        client = _FakeClient([_non_retryable_400()])
        sleep = _RecordingSleep()

        with pytest.raises(httpx.HTTPStatusError):
            await gate.run_real_dispatch_job(
                coordinator=coordinator, client=client, job_id=job_id,
                caller_id="ops-scheduler:held_position_reduce_sell",
                manual_run_id="cycle-1", model_id="m", system_prompt="s",
                user_prompt="u", response_format=_FakeOutput, sleep_fn=sleep,
            )

        assert len(client.calls) == 1
        assert sleep.calls == []
