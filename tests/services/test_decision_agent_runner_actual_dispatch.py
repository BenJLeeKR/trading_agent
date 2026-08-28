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

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_trading.repositories.contracts import AttemptHttpLifecycle
from agent_trading.repositories.memory import InMemoryFdcQuotaRepository
from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.recorder import AgentRunRecorder
from agent_trading.services.common_types import AIPolicyContextView, dataclass_to_dict
from agent_trading.services.decision_agent_runner import (
    DecisionAgentRunner,
    FdcActualDispatchPendingError,
    FdcDispatchDeferredError,
)
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
    async def test_fdc_ready_registers_job_and_raises_pending_without_waiting(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """2026-08-27 2차 리뷰 보정 — FDC-ready면 quota reservation을
        기다리지 않고 즉시 ``FdcActualDispatchPendingError``를 던진다
        (asyncio.gather()를 막지 않기 위함). fdc_only는 전혀 스폰되지
        않는다 — reservation 대기/HTTP는 post-gather dispatcher
        (``complete_fdc_actual_dispatch()``)의 책임이다."""
        repo = InMemoryFdcQuotaRepository()
        runner = _make_runner(fdc_actual_dispatch_enabled=True, repo=repo)

        spawn_calls: list[str] = []

        async def _fake_spawn(input_bytes, *, request):
            import json as _json
            payload = _json.loads(input_bytes)
            spawn_calls.append(payload["mode"])
            assert payload["mode"] == "pre_fdc"  # fdc_only는 절대 스폰되면 안 됨
            return _pre_fdc_ready_result(), b"{}"

        monkeypatch.setattr(runner, "_spawn_agent_subprocess", _fake_spawn)

        with pytest.raises(FdcActualDispatchPendingError) as exc_info:
            await runner._run_agents_in_subprocess_with_actual_dispatch(
                _make_request(), _held_position_context(),
            )

        assert spawn_calls == ["pre_fdc"]
        job_id = exc_info.value.job_id
        assert job_id in repo._jobs  # type: ignore[attr-defined]
        assert repo._jobs[job_id]["status"] == "QUEUED"  # type: ignore[attr-defined]
        assert exc_info.value.pre_fdc_result == _pre_fdc_ready_result()


class TestCompleteFdcActualDispatch:
    """post-gather dispatcher가 호출하는 모듈 레벨
    ``complete_fdc_actual_dispatch()`` — reservation 대기(FIFO, deadline
    없음)/coordinator 오류 backoff/provider 재시도(새 reservation)/
    job 종결 표시를 검증한다(2026-08-27 2차 리뷰 보정 — PR #359, 이전
    ``DecisionAgentRunner`` 인스턴스 메서드가 담당하던 로직의 이관)."""

    def _provider_runtime(self) -> dict[str, Any]:
        return {
            "llm_provider": "gemini", "provider_api_key": "fake-key",
            "provider_base_url": "https://fake.example",
            "provider_model_id": "fake-model", "provider_timeout_seconds": 30,
        }

    @pytest.mark.asyncio
    async def test_immediate_grant_spawns_fdc_only_once_and_marks_succeeded(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        spawn_calls: list[str] = []

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            import json as _json
            payload = _json.loads(input_bytes)
            spawn_calls.append(payload["mode"])
            return _fdc_only_success_result(), b"{}"

        import agent_trading.services.decision_agent_runner as runner_module
        monkeypatch.setattr(
            runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl,
        )

        result = await runner_module.complete_fdc_actual_dispatch(
            fdc_quota_repo=repo, provider_runtime=self._provider_runtime(),
            subprocess_timeout=90, job_id=job_id,
            pre_fdc_result=_pre_fdc_ready_result(),
            correlation_id="test-corr", decision_context_id=None,
            worker_semaphore=asyncio.Semaphore(5),
        )

        assert spawn_calls == ["fdc_only"]
        assert result.ai_inputs.decision_type == "REDUCE"
        assert repo._jobs[job_id]["status"] == "FDC_SUCCEEDED"  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_fifo_denied_then_granted_waits_and_succeeds(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """quota가 가득 찼거나 FIFO 순번이 아니면 fallback HOLD로 즉시
        포기하지 않고 대기 후 재시도한다."""
        repo = InMemoryFdcQuotaRepository()
        earlier_job = await repo.register_real_job(
            decision_cycle_id="c0", decision_context_id=None, symbol="OTHER",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        spawn_calls: list[str] = []

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            import json as _json
            payload = _json.loads(input_bytes)
            spawn_calls.append(payload["mode"])
            return _fdc_only_success_result(), b"{}"

        import agent_trading.services.decision_agent_runner as runner_module
        monkeypatch.setattr(
            runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl,
        )

        sleep_calls: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)
            await repo.mark_job_terminal(job_id=earlier_job, status="FDC_SUCCEEDED")

        result = await runner_module.complete_fdc_actual_dispatch(
            fdc_quota_repo=repo, provider_runtime=self._provider_runtime(),
            subprocess_timeout=90, job_id=job_id,
            pre_fdc_result=_pre_fdc_ready_result(),
            correlation_id="test-corr", decision_context_id=None,
            sleep_fn=_fake_sleep,
            worker_semaphore=asyncio.Semaphore(5),
        )

        assert len(sleep_calls) == 1  # 정확히 1번 대기 후 성공
        assert spawn_calls == ["fdc_only"]
        assert result.ai_inputs.decision_type == "REDUCE"

    @pytest.mark.asyncio
    async def test_provider_retryable_failure_gets_new_reservation_new_subprocess(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        fdc_only_results = [
            _fdc_only_retryable_failure_result(),
            _fdc_only_success_result(),
        ]
        spawn_calls: list[str] = []
        reservation_ids_used: list[str] = []

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            import json as _json
            payload = _json.loads(input_bytes)
            spawn_calls.append(payload["mode"])
            reservation_ids_used.append(payload["reservation_id"])
            return fdc_only_results.pop(0), b"{}"

        import agent_trading.services.decision_agent_runner as runner_module
        monkeypatch.setattr(
            runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl,
        )

        result = await runner_module.complete_fdc_actual_dispatch(
            fdc_quota_repo=repo, provider_runtime=self._provider_runtime(),
            subprocess_timeout=90, job_id=job_id,
            pre_fdc_result=_pre_fdc_ready_result(),
            correlation_id="test-corr", decision_context_id=None,
            worker_semaphore=asyncio.Semaphore(5),
        )

        assert spawn_calls == ["fdc_only", "fdc_only"]
        assert len(set(reservation_ids_used)) == 2  # 새 reservation 사용
        assert result.ai_inputs.decision_type == "REDUCE"
        assert repo._jobs[job_id]["status"] == "FDC_SUCCEEDED"  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_provider_exhausted_marks_job_failed_final_and_returns_fallback(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            return _fdc_only_retryable_failure_result(), b"{}"

        import agent_trading.services.decision_agent_runner as runner_module
        monkeypatch.setattr(
            runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl,
        )

        result = await runner_module.complete_fdc_actual_dispatch(
            fdc_quota_repo=repo, provider_runtime=self._provider_runtime(),
            subprocess_timeout=90, job_id=job_id,
            pre_fdc_result=_pre_fdc_ready_result(),
            correlation_id="test-corr", decision_context_id=None,
            worker_semaphore=asyncio.Semaphore(5),
        )

        assert repo._jobs[job_id]["status"] == "FDC_FAILED_FINAL"  # type: ignore[attr-defined]
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
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            return _fdc_only_success_result(), b"{}"

        import agent_trading.services.decision_agent_runner as runner_module
        monkeypatch.setattr(
            runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl,
        )

        sleep_calls: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

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

        result = await runner_module.complete_fdc_actual_dispatch(
            fdc_quota_repo=repo, provider_runtime=self._provider_runtime(),
            subprocess_timeout=90, job_id=job_id,
            pre_fdc_result=_pre_fdc_ready_result(),
            correlation_id="test-corr", decision_context_id=None,
            sleep_fn=_fake_sleep,
            worker_semaphore=asyncio.Semaphore(5),
        )

        assert sleep_calls == [1.0]  # coordinator 오류 1회 → 초기 backoff 1초
        assert result.ai_inputs.decision_type == "REDUCE"

    @pytest.mark.asyncio
    async def test_crash_before_http_start_is_retryable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """2026-08-27 2차 리뷰 보정 — fdc_only subprocess가 결과 없이
        죽었지만 http_started_at이 없으면(HTTP 시작 전) 안전하게 새
        reservation으로 재시도한다."""
        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        call_count = {"n": 0}

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return None, b""  # crash — http_started_at은 여전히 None
            return _fdc_only_success_result(), b"{}"

        import agent_trading.services.decision_agent_runner as runner_module
        monkeypatch.setattr(
            runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl,
        )

        result = await runner_module.complete_fdc_actual_dispatch(
            fdc_quota_repo=repo, provider_runtime=self._provider_runtime(),
            subprocess_timeout=90, job_id=job_id,
            pre_fdc_result=_pre_fdc_ready_result(),
            correlation_id="test-corr", decision_context_id=None,
            worker_semaphore=asyncio.Semaphore(5),
        )

        assert call_count["n"] == 2  # 재시도돼 성공
        assert result.ai_inputs.decision_type == "REDUCE"
        assert repo._jobs[job_id]["status"] == "FDC_SUCCEEDED"  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_crash_after_http_start_does_not_auto_retry(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """2026-08-27 2차 리뷰 보정 — fdc_only subprocess가 결과 없이
        죽었는데 http_started_at이 이미 기록돼 있으면(HTTP가 실제로
        시작된 뒤 결과를 회수하지 못함) 중복 호출 위험 때문에 자동
        재시도하지 않고 fail-closed로 job을 종결한다."""
        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        call_count = {"n": 0}

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            import json as _json
            call_count["n"] += 1
            # 실제 child가 http_started를 기록한 뒤 완료 결과를 쓰지
            # 못하고 죽은 상황을 재현한다 — reservation_id는 payload에서
            # 꺼낸다(실제로도 부모가 grant를 통해 이미 아는 값).
            payload = _json.loads(input_bytes)
            from uuid import UUID as _UUID
            await repo.record_attempt_outcome(
                reservation_id=_UUID(payload["reservation_id"]),
                outcome="http_started",
                http_started_at=datetime.now(timezone.utc),
            )
            return None, b""  # crash — 결과를 회수하지 못함

        import agent_trading.services.decision_agent_runner as runner_module
        monkeypatch.setattr(
            runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl,
        )

        result = await runner_module.complete_fdc_actual_dispatch(
            fdc_quota_repo=repo, provider_runtime=self._provider_runtime(),
            subprocess_timeout=90, job_id=job_id,
            pre_fdc_result=_pre_fdc_ready_result(),
            correlation_id="test-corr", decision_context_id=None,
            worker_semaphore=asyncio.Semaphore(5),
        )

        assert call_count["n"] == 1  # 재시도 없이 즉시 종결
        assert repo._jobs[job_id]["status"] == "FDC_FAILED_FINAL"  # type: ignore[attr-defined]
        assert repo._jobs[job_id]["failure_or_cancel_reason"] == (  # type: ignore[attr-defined]
            "fdc_only_subprocess_crashed_after_http_start_result_unknown"
        )
        # fail-closed 결과는 안전한 fallback(HOLD)을 쓴다 — 결과를 모르는
        # 실제 HTTP 시도를 성공으로 위장하지 않는다.
        assert result is not None


class TestPhaseDeadlineDoesNotCancelLiveProcess:
    """2026-08-27 3차 리뷰 보정 — cycle deadline에 도달해도 살아 있는
    프로세스는 job을 ``CANCELLED``로 표시하지 않는다. 대신
    ``FdcDispatchDeferredError``를 던지고 job 상태(DB)는 전혀 건드리지
    않는다 — 다음 cycle(같은 프로세스)의 carryover가 재시도한다."""

    @pytest.mark.asyncio
    async def test_deadline_before_reservation_raises_deferred_without_touching_job(
        self,
    ) -> None:
        import agent_trading.services.decision_agent_runner as runner_module

        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        spawn_calls = []

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            spawn_calls.append("fdc_only")
            return None, b""

        import agent_trading.services.decision_agent_runner as _rm
        _rm._spawn_agent_subprocess_impl = _fake_spawn_impl
        try:
            with pytest.raises(runner_module.FdcDispatchDeferredError) as exc_info:
                await runner_module.complete_fdc_actual_dispatch(
                    fdc_quota_repo=repo, provider_runtime={},
                    subprocess_timeout=90, job_id=job_id,
                    pre_fdc_result=_pre_fdc_ready_result(),
                    correlation_id="test-corr", decision_context_id=None,
                    worker_semaphore=asyncio.Semaphore(5),
                    # 이미 지난 데드라인 — 첫 iteration에서 즉시 defer.
                    deadline_monotonic=0.0,
                )
        finally:
            pass

        assert exc_info.value.job_id == job_id
        # fdc_only가 전혀 스폰되지 않았다 — reservation 자체를 시도하지 않았다.
        assert spawn_calls == []
        # job은 여전히 QUEUED다 — CANCELLED로 잘못 표시되지 않았다.
        assert repo._jobs[job_id]["status"] == "QUEUED"  # type: ignore[attr-defined]
        assert repo._jobs[job_id]["failure_or_cancel_reason"] is None  # type: ignore[attr-defined]


class TestReservationWaitDoesNotHoldWorkerSlot:
    """2026-08-27 3차 리뷰 보정 — reservation 대기(FIFO 거부 폴링)는
    worker semaphore를 점유하지 않는다. worker semaphore 용량이 1이어도
    reservation을 기다리는 job과 무관하게 다른 job의 fdc_only 실행이
    진행될 수 있어야 한다."""

    @pytest.mark.asyncio
    async def test_denied_job_does_not_block_another_jobs_worker_slot(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import agent_trading.services.decision_agent_runner as runner_module
        from agent_trading.services.fdc_quota_coordinator import FdcQuotaCoordinator

        repo = InMemoryFdcQuotaRepository()
        # job_b를 먼저 등록해 enqueue_sequence를 job_a보다 작게 만든다 —
        # job_a가 (아래 patch로) 영원히 QUEUED로 남아도, 기존 FIFO
        # admission rule("나보다 먼저 등록된 QUEUED job이 있으면 양보")이
        # job_b를 막지 않는다. 이 테스트가 검증하려는 것은 FIFO 규칙
        # 자체가 아니라 "reservation 대기가 worker semaphore를 점유하지
        # 않는다"는 별개의 계약이다.
        job_b = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="BBB",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )
        job_a = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="AAA",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        # job_a는 항상 ReservationDenied — job_b의 진행에 영향을 주면
        # 안 된다(worker semaphore를 점유하지 않아야 하므로).
        original_try_reserve = FdcQuotaCoordinator.try_reserve

        async def _patched_try_reserve(self, *, job_id, **kwargs):
            if job_id == job_a:
                from agent_trading.repositories.contracts import ReservationDenied
                return ReservationDenied(quota_scope=self._quota_scope, window_count=0)
            return await original_try_reserve(self, job_id=job_id, **kwargs)

        monkeypatch.setattr(FdcQuotaCoordinator, "try_reserve", _patched_try_reserve)

        b_spawned = asyncio.Event()

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            b_spawned.set()
            return _fdc_only_success_result(), b"{}"

        monkeypatch.setattr(runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl)

        worker_semaphore = asyncio.Semaphore(1)

        task_a = asyncio.create_task(
            runner_module.complete_fdc_actual_dispatch(
                fdc_quota_repo=repo, provider_runtime={},
                subprocess_timeout=90, job_id=job_a,
                pre_fdc_result=_pre_fdc_ready_result(),
                correlation_id="test-corr-a", decision_context_id=None,
                worker_semaphore=worker_semaphore,
                sleep_fn=lambda _s: asyncio.sleep(0),
            )
        )
        task_b = asyncio.create_task(
            runner_module.complete_fdc_actual_dispatch(
                fdc_quota_repo=repo, provider_runtime={},
                subprocess_timeout=90, job_id=job_b,
                pre_fdc_result=_pre_fdc_ready_result(),
                correlation_id="test-corr-b", decision_context_id=None,
                worker_semaphore=worker_semaphore,
            )
        )

        # job_b는 job_a가 영원히 대기 중이어도 완결돼야 한다 — worker
        # semaphore가 job_a의 무한 대기에 점유되지 않았다는 증거.
        result_b = await asyncio.wait_for(task_b, timeout=2.0)
        assert result_b is not None
        assert b_spawned.is_set()

        task_a.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task_a


class TestConcurrentJobsRespectFifoAndWorkerConcurrency:
    """2026-08-27 3차 리뷰 보정 — 여러 job이 동시에 ``complete_fdc_
    actual_dispatch()``를 통해 처리될 때, FIFO 순서(먼저 등록된 job이
    먼저 grant됨)와 worker semaphore(동시 fdc_only 실행 수 제한)가
    지켜지고, 같은 job이 중복 reservation/중복 fdc_only 호출을 만들지
    않는다."""

    @pytest.mark.asyncio
    async def test_three_jobs_fifo_order_bounded_concurrency_no_duplicates(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import agent_trading.services.decision_agent_runner as runner_module

        repo = InMemoryFdcQuotaRepository()
        job_ids = []
        for symbol in ("AAA", "BBB", "CCC"):
            job_id = await repo.register_real_job(
                decision_cycle_id="c1", decision_context_id=None, symbol=symbol,
                source_type="held_position", quota_scope="gemini:shared-operational",
                fdc_ready_at=datetime.now(timezone.utc),
            )
            job_ids.append(job_id)

        spawn_order: list[str] = []
        concurrent_count = {"current": 0, "max": 0}
        call_count_by_reservation: dict[str, int] = {}

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            import json as _json
            payload = _json.loads(input_bytes)
            reservation_id = payload["reservation_id"]
            call_count_by_reservation[reservation_id] = (
                call_count_by_reservation.get(reservation_id, 0) + 1
            )
            spawn_order.append(payload["reservation_job_id"])
            concurrent_count["current"] += 1
            concurrent_count["max"] = max(
                concurrent_count["max"], concurrent_count["current"],
            )
            await asyncio.sleep(0.01)  # 동시 실행 창을 넓혀 경쟁을 드러낸다
            concurrent_count["current"] -= 1
            return _fdc_only_success_result(), b"{}"

        monkeypatch.setattr(runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl)

        worker_semaphore = asyncio.Semaphore(1)
        results = await asyncio.gather(*[
            runner_module.complete_fdc_actual_dispatch(
                fdc_quota_repo=repo, provider_runtime={},
                subprocess_timeout=90, job_id=job_id,
                pre_fdc_result=_pre_fdc_ready_result(),
                correlation_id=f"test-corr-{i}", decision_context_id=None,
                worker_semaphore=worker_semaphore,
            )
            for i, job_id in enumerate(job_ids)
        ])

        assert all(r is not None for r in results)
        # FIFO — 먼저 등록된 job이 먼저 fdc_only를 스폰했다.
        assert spawn_order == [str(job_id) for job_id in job_ids]
        # worker semaphore(용량 1) — 동시에 1개만 fdc_only를 실행했다.
        assert concurrent_count["max"] == 1
        # 각 job의 reservation마다 fdc_only는 정확히 1번만 호출됐다
        # (중복 호출 없음).
        assert all(n == 1 for n in call_count_by_reservation.values())
        for job_id in job_ids:
            assert repo._jobs[job_id]["status"] == "FDC_SUCCEEDED"  # type: ignore[attr-defined]


class TestAttemptRowMissingIsFailClosed:
    """2026-08-27 3차 리뷰 보정 — attempt 행 자체가 없는 상태(데이터
    정합성 이상)는 ``NOT_STARTED``와 같은 방식(자동 재시도)으로
    처리하지 않는다. fail-closed로 즉시 종결하고 감사 가능한 reason을
    남긴다."""

    @pytest.mark.asyncio
    async def test_attempt_row_missing_fails_closed_without_retry(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import agent_trading.services.decision_agent_runner as runner_module
        from uuid import UUID as _UUID

        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        call_count = {"n": 0}

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            import json as _json
            call_count["n"] += 1
            payload = _json.loads(input_bytes)
            # attempt 행이 (예: 데이터 정합성 이상으로) 사라진 상황을
            # 재현한다 — try_reserve()의 원자적 grant+attempt 생성
            # 계약(§6)이 정상이라면 실제로는 발생할 수 없어야 하는
            # 상태지만, 방어적으로 fail-closed 처리가 되는지 검증한다.
            del repo._attempts_by_id[_UUID(payload["reservation_id"])]  # type: ignore[attr-defined]
            return None, b""

        monkeypatch.setattr(runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl)

        result = await runner_module.complete_fdc_actual_dispatch(
            fdc_quota_repo=repo, provider_runtime={},
            subprocess_timeout=90, job_id=job_id,
            pre_fdc_result=_pre_fdc_ready_result(),
            correlation_id="test-corr", decision_context_id=None,
            worker_semaphore=asyncio.Semaphore(5),
        )

        assert call_count["n"] == 1  # 재시도 없음 — NOT_STARTED와 다르게 취급
        assert repo._jobs[job_id]["status"] == "FDC_FAILED_FINAL"  # type: ignore[attr-defined]
        assert repo._jobs[job_id]["failure_or_cancel_reason"] == (  # type: ignore[attr-defined]
            "fdc_provider_attempt_row_missing_data_integrity_error"
        )
        assert result is not None
        assert result.ai_inputs.decision_type == "HOLD"  # fail-closed fallback


class TestOperationalDispatchNeverSetsManualRunId:
    """2026-08-27 3차 리뷰 보정 회귀 — 운영(job_id 기반) 실제 dispatch는
    ``manual_run_id``를 절대 채우지 않는다. 수동 스크립트 전용 필드
    계약을 보존한다."""

    @pytest.mark.asyncio
    async def test_try_reserve_always_called_with_manual_run_id_none(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import agent_trading.services.decision_agent_runner as runner_module
        from agent_trading.services.fdc_quota_coordinator import FdcQuotaCoordinator

        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        observed_manual_run_ids: list[Any] = []
        original_try_reserve = FdcQuotaCoordinator.try_reserve

        async def _spying_try_reserve(self, *, manual_run_id, **kwargs):
            observed_manual_run_ids.append(manual_run_id)
            return await original_try_reserve(self, manual_run_id=manual_run_id, **kwargs)

        monkeypatch.setattr(FdcQuotaCoordinator, "try_reserve", _spying_try_reserve)

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            return _fdc_only_success_result(), b"{}"

        monkeypatch.setattr(runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl)

        await runner_module.complete_fdc_actual_dispatch(
            fdc_quota_repo=repo, provider_runtime={},
            subprocess_timeout=90, job_id=job_id,
            pre_fdc_result=_pre_fdc_ready_result(),
            correlation_id="test-corr", decision_context_id=None,
            worker_semaphore=asyncio.Semaphore(5),
        )

        assert observed_manual_run_ids
        assert all(v is None for v in observed_manual_run_ids)


class TestDurableResumeAcrossProcessRestart:
    """2026-08-28 4차 리뷰 보정 — ops-scheduler는 항상 ``--count 1``
    단발 프로세스를 spawn한다. deadline defer로 완결되지 못한 job이
    ``list_resumable_real_jobs()``를 통해 (같은 repo로 시뮬레이션한)
    "다음 프로세스"에서 agent(EI/AR/AC)를 다시 호출하지 않고 안전하게
    재개되는지 검증한다."""

    @pytest.mark.asyncio
    async def test_deadline_deferred_job_resumes_via_list_resumable_without_recalling_agents(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import agent_trading.services.decision_agent_runner as runner_module

        repo = InMemoryFdcQuotaRepository()
        pre_fdc_result = _pre_fdc_ready_result()
        # register_real_job()이 pre_fdc_result/correlation_id를 함께
        # 저장한다 — DecisionAgentRunner._run_agents_in_subprocess_with_
        # actual_dispatch()가 실제로 하는 것과 동일하다.
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
            pre_fdc_result=pre_fdc_result, correlation_id="orig-corr",
        )

        pre_fdc_spawn_calls = {"n": 0}
        fdc_only_spawn_calls = {"n": 0}

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            import json as _json
            payload = _json.loads(input_bytes)
            if payload.get("mode") == "pre_fdc":
                pre_fdc_spawn_calls["n"] += 1
                raise AssertionError("resume 경로에서 pre_fdc를 다시 호출했다")
            fdc_only_spawn_calls["n"] += 1
            return _fdc_only_success_result(), b"{}"

        monkeypatch.setattr(runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl)

        # ── "이전 프로세스" — deadline이 이미 지나 있어 즉시 defer된다.
        with pytest.raises(runner_module.FdcDispatchDeferredError):
            await runner_module.complete_fdc_actual_dispatch(
                fdc_quota_repo=repo, provider_runtime={},
                subprocess_timeout=90, job_id=job_id,
                pre_fdc_result=pre_fdc_result,
                correlation_id="orig-corr", decision_context_id=None,
                worker_semaphore=asyncio.Semaphore(5),
                deadline_monotonic=0.0,
            )
        assert fdc_only_spawn_calls["n"] == 0
        assert repo._jobs[job_id]["status"] == "QUEUED"  # type: ignore[attr-defined]

        # ── "다음 프로세스"(같은 repo — durable 저장을 시뮬레이션) —
        # list_resumable_real_jobs()로 발견하고 pre_fdc_result를 그대로
        # 재사용해 완결한다.
        resumable = await repo.list_resumable_real_jobs(
            quota_scope="gemini:shared-operational",
        )
        assert len(resumable) == 1
        assert resumable[0].job_id == job_id
        assert resumable[0].pre_fdc_result == pre_fdc_result
        assert resumable[0].correlation_id == "orig-corr"

        result = await runner_module.complete_fdc_actual_dispatch(
            fdc_quota_repo=repo, provider_runtime={},
            subprocess_timeout=90, job_id=resumable[0].job_id,
            pre_fdc_result=resumable[0].pre_fdc_result,
            correlation_id=resumable[0].correlation_id,
            decision_context_id=resumable[0].decision_context_id,
            worker_semaphore=asyncio.Semaphore(5),
        )

        assert result is not None
        assert pre_fdc_spawn_calls["n"] == 0  # agent를 다시 호출하지 않았다
        assert fdc_only_spawn_calls["n"] == 1  # fdc_only만 정확히 1회
        assert repo._jobs[job_id]["status"] == "FDC_SUCCEEDED"  # type: ignore[attr-defined]
        # 재개 후에는 더 이상 QUEUED가 아니므로 목록에서 사라진다.
        assert await repo.list_resumable_real_jobs(
            quota_scope="gemini:shared-operational",
        ) == []

    @pytest.mark.asyncio
    async def test_cancel_stale_real_jobs_no_longer_touches_queued(self) -> None:
        """2026-08-28 4차 리뷰 보정 — QUEUED job은 이제
        list_resumable_real_jobs()가 재개하므로, cancel_stale_real_jobs()
        (recovery scan)는 더 이상 QUEUED를 건드리지 않는다."""
        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
            pre_fdc_result=_pre_fdc_ready_result(), correlation_id="orig-corr",
        )

        affected = await repo.cancel_stale_real_jobs(
            quota_scope="gemini:shared-operational",
        )

        assert affected == 0
        assert repo._jobs[job_id]["status"] == "QUEUED"  # type: ignore[attr-defined]
        resumable = await repo.list_resumable_real_jobs(
            quota_scope="gemini:shared-operational",
        )
        assert len(resumable) == 1
        assert resumable[0].job_id == job_id


class TestWorkerSlotAcquiredBeforeReservation:
    """2026-08-28 4차 리뷰 보정 — worker slot을 먼저 확보한 뒤에만
    reservation을 시도한다(설계 문서 §7 순서). slot이 이미 다른 곳에서
    점유돼 있으면 slot이 빌 때까지 ``try_reserve()`` 자체를 호출하지
    않는다."""

    @pytest.mark.asyncio
    async def test_reservation_not_attempted_until_worker_slot_available(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import agent_trading.services.decision_agent_runner as runner_module
        from agent_trading.services.fdc_quota_coordinator import FdcQuotaCoordinator

        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        try_reserve_calls = {"n": 0}
        original_try_reserve = FdcQuotaCoordinator.try_reserve

        async def _counting_try_reserve(self, **kwargs):
            try_reserve_calls["n"] += 1
            return await original_try_reserve(self, **kwargs)

        monkeypatch.setattr(FdcQuotaCoordinator, "try_reserve", _counting_try_reserve)

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            return _fdc_only_success_result(), b"{}"

        monkeypatch.setattr(runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl)

        worker_semaphore = asyncio.Semaphore(1)
        # slot을 미리 점유해 둔다 — dispatch가 이 slot을 얻을 때까지
        # try_reserve()를 호출해서는 안 된다.
        await worker_semaphore.acquire()

        task = asyncio.create_task(
            runner_module.complete_fdc_actual_dispatch(
                fdc_quota_repo=repo, provider_runtime={},
                subprocess_timeout=90, job_id=job_id,
                pre_fdc_result=_pre_fdc_ready_result(),
                correlation_id="test-corr", decision_context_id=None,
                worker_semaphore=worker_semaphore,
            )
        )
        await asyncio.sleep(0.05)  # dispatch가 slot 대기 상태에 들어갈 시간을 준다
        assert try_reserve_calls["n"] == 0  # slot을 못 얻었으므로 아직 시도조차 안 함

        worker_semaphore.release()  # slot을 반환 — 이제 dispatch가 진행된다
        result = await asyncio.wait_for(task, timeout=2.0)

        assert result is not None
        assert try_reserve_calls["n"] == 1


class TestRecordAttemptOutcomeRaceIsFailClosed:
    """2026-08-28 4차 리뷰 보정 — lifecycle 조회 직후
    ``record_attempt_outcome()``이 ``ValueError``를 내는 race(그 사이
    attempt 행이 사라짐)를 더 이상 조용히 무시하지 않는다. 재시도 없이
    fail-closed로 종결한다."""

    @pytest.mark.asyncio
    async def test_value_error_race_after_not_started_lifecycle_fails_closed_no_retry(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import agent_trading.services.decision_agent_runner as runner_module

        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope="gemini:shared-operational",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        spawn_call_count = {"n": 0}

        async def _fake_spawn_impl(input_bytes, *, subprocess_timeout, decision_context_id, correlation_id):
            spawn_call_count["n"] += 1
            return None, b""  # crash — http_started_at 없음(NOT_STARTED)

        monkeypatch.setattr(runner_module, "_spawn_agent_subprocess_impl", _fake_spawn_impl)

        # record_attempt_outcome()을 클래스 레벨에서 패치해, lifecycle이
        # NOT_STARTED로 확인된 *직후* 그 사이 행이 사라진 race를
        # 재현한다(실제로는 다른 프로세스의 동시 접근 등으로 발생할 수
        # 있는 상황).
        async def _racy_record_attempt_outcome(self, *, reservation_id, **kwargs):
            raise ValueError(
                f"record_attempt_outcome: no fdc_provider_attempts row "
                f"for attempt_id={reservation_id!r} (simulated race)"
            )

        monkeypatch.setattr(
            InMemoryFdcQuotaRepository, "record_attempt_outcome",
            _racy_record_attempt_outcome,
        )

        result = await runner_module.complete_fdc_actual_dispatch(
            fdc_quota_repo=repo, provider_runtime={},
            subprocess_timeout=90, job_id=job_id,
            pre_fdc_result=_pre_fdc_ready_result(),
            correlation_id="test-corr", decision_context_id=None,
            worker_semaphore=asyncio.Semaphore(5),
        )

        assert spawn_call_count["n"] == 1  # 재시도 없음
        assert repo._jobs[job_id]["status"] == "FDC_FAILED_FINAL"  # type: ignore[attr-defined]
        assert repo._jobs[job_id]["failure_or_cancel_reason"] == (  # type: ignore[attr-defined]
            "fdc_provider_attempt_outcome_write_race_data_integrity_error"
        )
        assert result is not None
        assert result.ai_inputs.decision_type == "HOLD"  # fail-closed fallback
