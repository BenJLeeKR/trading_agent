"""Tests for ``DecisionAgentRunner``의 FDC 실제 dispatch 오케스트레이션
(2026-08-27 신설 — PR #359 리뷰 보정, held_position lane REDUCE_CANDIDATE/
SELL_CANDIDATE 한정).

reservation/FIFO 순번 메커니즘 자체는 ``tests/scripts/test_fdc_manual_
provider_gate.py``(``run_real_dispatch_job()``)와 ``tests/services/
test_fdc_quota_coordinator.py``(FIFO 공정성)가 이미 검증했으므로, 여기서는
``DecisionAgentRunner`` 계층의 배선만 검증한다:

1. flag=false/비대상 lane이면 실제 dispatch 경로가 전혀 호출되지 않는다.
2. 대상 lane + flag=true면 pre_fdc → (reservation 대기) → fdc_only 순서로
   subprocess를 스폰하고, 결과를 병합해 하나의 ``AgentExecutionBundle``을
   만든다.
3. reservation이 즉시 grant되지 않아도(FIFO 순번 대기) fallback으로
   포기하지 않고 계속 재시도한다.
4. provider 재시도 실패는 새 reservation(=새 fdc_only subprocess spawn)을
   쓴다.
5. job 상태(``FDC_SUCCEEDED``/``FDC_FAILED_FINAL``)가 ``fdc_quota``
   repository에 정확히 기록된다.

fake만 사용 — 실제 subprocess/DB/HTTP/sleep 없음.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_trading.repositories.memory import InMemoryFdcQuotaRepository
from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.recorder import AgentRunRecorder
from agent_trading.services.common_types import AIPolicyContextView, dataclass_to_dict
from agent_trading.services.decision_agent_runner import DecisionAgentRunner
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)
from agent_trading.services.ai_agents.schemas import (
    AIComplianceOutput,
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)


def _make_runner(
    *, fdc_actual_dispatch_enabled: bool, repo: InMemoryFdcQuotaRepository | None = None,
) -> DecisionAgentRunner:
    mock_repos = MagicMock()
    mock_repos.fdc_quota = repo or InMemoryFdcQuotaRepository()
    return DecisionAgentRunner(
        repos=mock_repos,
        event_interpretation_agent=MagicMock(),
        ai_risk_agent=MagicMock(),
        ai_compliance_agent=MagicMock(),
        final_decision_composer_agent=MagicMock(),
        agent_run_recorder=MagicMock(spec=AgentRunRecorder),
        provider_api_key="fake-key",
        provider_base_url="https://fake.example",
        provider_model_id="fake-model",
        fdc_actual_dispatch_enabled=fdc_actual_dispatch_enabled,
    )


def _held_position_context(
    *, primary_candidate: str = "SELL_CANDIDATE", has_position: bool = True,
) -> AIPolicyContextView:
    from decimal import Decimal
    from types import SimpleNamespace

    return AIPolicyContextView(
        source_type="held_position",
        position_snapshot=(
            SimpleNamespace(quantity=Decimal("10")) if has_position else None
        ),
        deterministic_trigger=SimpleNamespace(primary_candidate=primary_candidate),
    )


def _core_context() -> AIPolicyContextView:
    return AIPolicyContextView(source_type="core")


def _make_request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        decision_context_id=None, correlation_id="test-corr",
        context=_held_position_context(), symbol="005930", market="KRX",
        source_type="held_position",
    )


def _pre_fdc_ready_result() -> dict[str, Any]:
    return {
        "success": True,
        "event_output": dataclass_to_dict(EventInterpretationOutput(symbol="005930")),
        "risk_output": dataclass_to_dict(AIRiskOutput(risk_opinion="allow")),
        "compliance_output": dataclass_to_dict(AIComplianceOutput(compliance_opinion="allow")),
        "composer_output": {},
        "fdc_skipped": False,
        "requires_fdc_dispatch": True,
        "fdc_ready_at": "2026-08-27T01:00:00+00:00",
        "skip_reason_codes": [],
        "duration_seconds": 0.1,
    }


def _fdc_only_success_result() -> dict[str, Any]:
    return {
        "success": True,
        "composer_output": dataclass_to_dict(
            FinalDecisionComposerOutput(symbol="005930", decision_type="REDUCE", confidence=0.7)
        ),
        "provider_final_status": "success",
        "provider_http_attempt_count": 1,
        "provider_http_429_count": 0,
        "provider_execution_seconds": 1.2,
    }


def _fdc_only_retryable_failure_result() -> dict[str, Any]:
    return {
        "success": True,
        "composer_output": dataclass_to_dict(
            FinalDecisionComposerOutput(symbol="005930", decision_type="HOLD", confidence=0.0)
        ),
        "provider_final_status": "provider_rate_limit",
        "provider_http_attempt_count": 1,
        "provider_http_429_count": 1,
        "provider_execution_seconds": 0.5,
    }


class TestFlagAndLaneGating:
    @pytest.mark.asyncio
    async def test_flag_false_never_calls_actual_dispatch(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = _make_runner(fdc_actual_dispatch_enabled=False)

        async def _should_not_be_called(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("flag=false에서 actual dispatch가 호출됐다")

        monkeypatch.setattr(
            runner, "_run_agents_in_subprocess_with_actual_dispatch",
            _should_not_be_called,
        )

        async def _fake_spawn(input_bytes, *, request):
            return {"success": True, "event_output": {}, "risk_output": {},
                    "compliance_output": {}, "composer_output": {},
                    "fdc_skipped": True}, b"{}"

        monkeypatch.setattr(runner, "_spawn_agent_subprocess", _fake_spawn)

        result = await runner.run_agents_in_subprocess(
            _make_request(), _held_position_context(),
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_non_target_lane_never_calls_actual_dispatch(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = _make_runner(fdc_actual_dispatch_enabled=True)

        async def _should_not_be_called(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("비대상 lane(core)에서 actual dispatch가 호출됐다")

        monkeypatch.setattr(
            runner, "_run_agents_in_subprocess_with_actual_dispatch",
            _should_not_be_called,
        )

        async def _fake_spawn(input_bytes, *, request):
            return {"success": True, "event_output": {}, "risk_output": {},
                    "compliance_output": {}, "composer_output": {},
                    "fdc_skipped": True}, b"{}"

        monkeypatch.setattr(runner, "_spawn_agent_subprocess", _fake_spawn)

        result = await runner.run_agents_in_subprocess(
            _make_request(), _core_context(),
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_target_lane_flag_true_delegates_to_actual_dispatch(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = _make_runner(fdc_actual_dispatch_enabled=True)

        sentinel = object()
        called = {"count": 0}

        async def _fake_actual_dispatch(request, assembled_context):
            called["count"] += 1
            return sentinel

        monkeypatch.setattr(
            runner, "_run_agents_in_subprocess_with_actual_dispatch",
            _fake_actual_dispatch,
        )

        result = await runner.run_agents_in_subprocess(
            _make_request(), _held_position_context(),
        )
        assert called["count"] == 1
        assert result is sentinel


class TestActualDispatchOrchestration:
    @pytest.mark.asyncio
    async def test_pre_fdc_skip_short_circuits_without_registering_job(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = InMemoryFdcQuotaRepository()
        runner = _make_runner(fdc_actual_dispatch_enabled=True, repo=repo)

        spawn_calls: list[str] = []

        async def _fake_spawn(input_bytes, *, request):
            spawn_calls.append("pre_fdc")
            return {
                "success": True,
                "event_output": dataclass_to_dict(EventInterpretationOutput()),
                "risk_output": dataclass_to_dict(AIRiskOutput()),
                "compliance_output": dataclass_to_dict(AIComplianceOutput()),
                "composer_output": dataclass_to_dict(FinalDecisionComposerOutput(decision_type="HOLD")),
                "fdc_skipped": True,
                "requires_fdc_dispatch": False,
                "skip_reason_codes": ["risk_reject"],
            }, b'{"success": true}'

        monkeypatch.setattr(runner, "_spawn_agent_subprocess", _fake_spawn)

        result = await runner._run_agents_in_subprocess_with_actual_dispatch(
            _make_request(), _held_position_context(),
        )

        assert spawn_calls == ["pre_fdc"]  # fdc_only는 스폰되지 않음
        assert result.ai_inputs.decision_type == "HOLD"
        assert repo._jobs == {}  # type: ignore[attr-defined]  # job 등록 없음

    @pytest.mark.asyncio
    async def test_immediate_grant_spawns_fdc_only_once_and_marks_succeeded(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = InMemoryFdcQuotaRepository()
        runner = _make_runner(fdc_actual_dispatch_enabled=True, repo=repo)

        spawn_calls: list[str] = []

        async def _fake_spawn(input_bytes, *, request):
            import json as _json
            payload = _json.loads(input_bytes)
            spawn_calls.append(payload["mode"])
            if payload["mode"] == "pre_fdc":
                return _pre_fdc_ready_result(), b"{}"
            return _fdc_only_success_result(), b"{}"

        monkeypatch.setattr(runner, "_spawn_agent_subprocess", _fake_spawn)

        result = await runner._run_agents_in_subprocess_with_actual_dispatch(
            _make_request(), _held_position_context(),
        )

        assert spawn_calls == ["pre_fdc", "fdc_only"]
        assert result.ai_inputs.decision_type == "REDUCE"
        job = next(iter(repo._jobs.values()))  # type: ignore[attr-defined]
        assert job["status"] == "FDC_SUCCEEDED"

    @pytest.mark.asyncio
    async def test_fifo_denied_then_granted_waits_and_succeeds(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """quota가 가득 찼거나 FIFO 순번이 아니면 fallback HOLD로 즉시
        포기하지 않고 대기 후 재시도한다."""
        repo = InMemoryFdcQuotaRepository()
        runner = _make_runner(fdc_actual_dispatch_enabled=True, repo=repo)

        # 먼저 등록된 job이 있어 SUT job이 첫 폴링에서 거부되게 만든다.
        earlier_job = await repo.register_real_job(
            decision_cycle_id="c0", decision_context_id=None, symbol="OTHER",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        spawn_calls: list[str] = []

        async def _fake_spawn(input_bytes, *, request):
            import json as _json
            payload = _json.loads(input_bytes)
            spawn_calls.append(payload["mode"])
            if payload["mode"] == "pre_fdc":
                return _pre_fdc_ready_result(), b"{}"
            return _fdc_only_success_result(), b"{}"

        monkeypatch.setattr(runner, "_spawn_agent_subprocess", _fake_spawn)

        sleep_calls: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)
            # 첫 대기 후 앞선 job을 종결 상태로 만들어 순번을 넘긴다.
            await repo.mark_job_terminal(job_id=earlier_job, status="FDC_SUCCEEDED")

        import agent_trading.services.decision_agent_runner as runner_module
        monkeypatch.setattr(runner_module.asyncio, "sleep", _fake_sleep)

        result = await runner._run_agents_in_subprocess_with_actual_dispatch(
            _make_request(), _held_position_context(),
        )

        assert len(sleep_calls) == 1  # 정확히 1번 대기 후 성공
        assert spawn_calls == ["pre_fdc", "fdc_only"]
        assert result.ai_inputs.decision_type == "REDUCE"

    @pytest.mark.asyncio
    async def test_provider_retryable_failure_gets_new_reservation_new_subprocess(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = InMemoryFdcQuotaRepository()
        runner = _make_runner(fdc_actual_dispatch_enabled=True, repo=repo)

        fdc_only_results = [
            _fdc_only_retryable_failure_result(),
            _fdc_only_success_result(),
        ]
        spawn_calls: list[str] = []
        reservation_ids_used: list[str] = []

        async def _fake_spawn(input_bytes, *, request):
            import json as _json
            payload = _json.loads(input_bytes)
            spawn_calls.append(payload["mode"])
            if payload["mode"] == "pre_fdc":
                return _pre_fdc_ready_result(), b"{}"
            reservation_ids_used.append(payload["reservation_id"])
            return fdc_only_results.pop(0), b"{}"

        monkeypatch.setattr(runner, "_spawn_agent_subprocess", _fake_spawn)

        result = await runner._run_agents_in_subprocess_with_actual_dispatch(
            _make_request(), _held_position_context(),
        )

        assert spawn_calls == ["pre_fdc", "fdc_only", "fdc_only"]
        assert len(set(reservation_ids_used)) == 2  # 새 reservation 사용
        assert result.ai_inputs.decision_type == "REDUCE"
        job = next(iter(repo._jobs.values()))  # type: ignore[attr-defined]
        assert job["status"] == "FDC_SUCCEEDED"

    @pytest.mark.asyncio
    async def test_provider_exhausted_marks_job_failed_final_and_returns_fallback(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = InMemoryFdcQuotaRepository()
        runner = _make_runner(fdc_actual_dispatch_enabled=True, repo=repo)

        async def _fake_spawn(input_bytes, *, request):
            import json as _json
            payload = _json.loads(input_bytes)
            if payload["mode"] == "pre_fdc":
                return _pre_fdc_ready_result(), b"{}"
            return _fdc_only_retryable_failure_result(), b"{}"

        monkeypatch.setattr(runner, "_spawn_agent_subprocess", _fake_spawn)

        result = await runner._run_agents_in_subprocess_with_actual_dispatch(
            _make_request(), _held_position_context(),
        )

        job = next(iter(repo._jobs.values()))  # type: ignore[attr-defined]
        assert job["status"] == "FDC_FAILED_FINAL"
        # HTTP는 실제로 나갔지만(fallback HOLD로 성공 위장하지 않음),
        # 최종 결과는 fallback bundle의 안전한 기본값을 쓴다.
        assert result is not None

    @pytest.mark.asyncio
    async def test_coordinator_error_backs_off_then_recovers(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """coordinator 오류(DB unavailable 등)는 fail-closed로 재시도하며,
        복구되면 정상 재개된다."""
        repo = InMemoryFdcQuotaRepository()
        runner = _make_runner(fdc_actual_dispatch_enabled=True, repo=repo)

        async def _fake_spawn(input_bytes, *, request):
            import json as _json
            payload = _json.loads(input_bytes)
            if payload["mode"] == "pre_fdc":
                return _pre_fdc_ready_result(), b"{}"
            return _fdc_only_success_result(), b"{}"

        monkeypatch.setattr(runner, "_spawn_agent_subprocess", _fake_spawn)

        sleep_calls: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        import agent_trading.services.decision_agent_runner as runner_module
        monkeypatch.setattr(runner_module.asyncio, "sleep", _fake_sleep)

        # coordinator 생성 직후 try_reserve()를 감싸 첫 호출만 오류를
        # 반환하도록 한다(그 이후는 실제 InMemory 구현으로 위임).
        import agent_trading.repositories.contracts as contracts_module
        import agent_trading.services.fdc_quota_coordinator as coordinator_module

        flaky_state = {"n": 0}
        original_init = coordinator_module.FdcQuotaCoordinator.__init__

        def _wrapped_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            original_try_reserve = self.try_reserve

            async def _flaky_try_reserve(**kwargs2):
                flaky_state["n"] += 1
                if flaky_state["n"] <= 1:
                    return contracts_module.CoordinatorError(
                        contracts_module.CoordinatorErrorClass.COORDINATOR_UNAVAILABLE,
                        "simulated DB down",
                    )
                return await original_try_reserve(**kwargs2)

            self.try_reserve = _flaky_try_reserve

        monkeypatch.setattr(coordinator_module.FdcQuotaCoordinator, "__init__", _wrapped_init)

        result = await runner._run_agents_in_subprocess_with_actual_dispatch(
            _make_request(), _held_position_context(),
        )

        assert sleep_calls == [1.0]  # coordinator 오류 1회 → 초기 backoff 1초
        assert result.ai_inputs.decision_type == "REDUCE"
