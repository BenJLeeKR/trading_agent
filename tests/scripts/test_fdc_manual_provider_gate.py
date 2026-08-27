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


def _make_coordinator(*, target_rpm: int = 13) -> FdcQuotaCoordinator:
    return FdcQuotaCoordinator(
        repo=InMemoryFdcQuotaRepository(),
        target_rpm=target_rpm,
        quota_scope="test:manual-gate",
    )


class _FakeClient:
    """``call_with_coordinator()``가 요구하는 최소 duck-typed 인터페이스
    (``generate_structured_once()``)만 흉내낸다 — 실제 HTTP 없음."""

    def __init__(self, outcomes: list[Any]) -> None:
        # 각 원소가 예외 인스턴스면 raise, 아니면 RawProviderResponse로 반환.
        self._outcomes = list(outcomes)
        self.calls: list[tuple[ReservationGrant, int]] = []

    async def generate_structured_once(
        self, grant: ReservationGrant, *, expected_job_id, expected_attempt_no, **kwargs
    ) -> RawProviderResponse:
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


class TestMakeCoordinatorPermitAdapter:
    @pytest.mark.asyncio
    async def test_grants_permit_and_tracks_reservation(self) -> None:
        coordinator = _make_coordinator()
        adapter, reservations = gate.make_coordinator_permit_adapter(
            coordinator=coordinator, caller_id="manual:test", manual_run_id="run-5",
        )

        permit = await adapter()

        assert permit.granted is True
        assert len(reservations) == 1

    @pytest.mark.asyncio
    async def test_denied_returns_not_granted_and_untracked(self) -> None:
        coordinator = _make_coordinator(target_rpm=1)
        filler = await coordinator.try_reserve(job_id=None, caller_id="filler")
        assert isinstance(filler, ReservationGrant)

        adapter, reservations = gate.make_coordinator_permit_adapter(
            coordinator=coordinator, caller_id="manual:test", manual_run_id="run-6",
        )
        permit = await adapter()

        assert permit.granted is False
        assert permit.denial_reason == "quota_denied"
        assert reservations == []


class TestFinalizePermitAdapterOutcomes:
    @pytest.mark.asyncio
    async def test_marks_last_success_others_retryable(self) -> None:
        coordinator = _make_coordinator()
        ids = []
        for i in range(3):
            r = await coordinator.try_reserve(
                job_id=None, caller_id="manual:test", attempt_no=i + 1,
            )
            assert isinstance(r, ReservationGrant)
            ids.append(r.reservation_id)

        await gate.finalize_permit_adapter_outcomes(
            coordinator=coordinator, reservation_ids=ids, succeeded=True,
        )

        assert _attempt_outcome(coordinator, ids[0]) == "http_failed_retryable"
        assert _attempt_outcome(coordinator, ids[1]) == "http_failed_retryable"
        assert _attempt_outcome(coordinator, ids[2]) == "http_succeeded"

    @pytest.mark.asyncio
    async def test_marks_last_failed_final_on_failure(self) -> None:
        coordinator = _make_coordinator()
        r = await coordinator.try_reserve(job_id=None, caller_id="manual:test")
        assert isinstance(r, ReservationGrant)

        await gate.finalize_permit_adapter_outcomes(
            coordinator=coordinator, reservation_ids=[r.reservation_id], succeeded=False,
        )

        assert _attempt_outcome(coordinator, r.reservation_id) == "http_failed_final"

    @pytest.mark.asyncio
    async def test_empty_list_is_a_noop(self) -> None:
        coordinator = _make_coordinator()
        # 예외 없이 조용히 반환돼야 한다.
        await gate.finalize_permit_adapter_outcomes(
            coordinator=coordinator, reservation_ids=[], succeeded=True,
        )


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
