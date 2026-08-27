"""Tests for ``scripts/fdc_manual_provider_gate.py``(2026-08-27 PR A 신설).

fake clock/fake repository/fake session provider만 사용한다 — 실제
sleep, 실제 DB, 실제 Gemini/KIS 호출은 전혀 하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from agent_trading.repositories.contracts import ReservationGrant
from agent_trading.repositories.memory import InMemoryFdcQuotaRepository
from agent_trading.services.ai_agents.base import RawProviderResponse
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
