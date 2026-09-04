"""Runs the v1 Provider AI Agents (EI → AR → AC → FDC) in sequence.

Extracted from DecisionOrchestratorService (Phase 5 refactoring).
Supports both in-process execution and subprocess-based execution
with SIGKILL-guaranteed timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess  # noqa: F401 — used by subprocess-based execution
import sys
import time as time_module
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    ProviderAIAgent,
)
from agent_trading.services.ai_agents.recorder import AgentRunRecorder
from agent_trading.services.ai_agents.schemas import (
    AIComplianceOutput,
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.common_types import (
    AgentExecutionBundle,
    AIDecisionInputs,
    AIPolicyContextView,
    ScoreCalculator,
    StubScoreCalculator,
    dataclass_to_dict,
)
from agent_trading.services.subprocess_helpers import (
    build_fallback_bundle,
    deserialize_agent_output,
    serialize_agent_input,
)
from agent_trading.services.expected_value_gate import (
    evaluate_expected_value_gate,
)
from agent_trading.services.translation import (
    is_missing_agent_symbol,
    normalize_decision_type,
)

logger = logging.getLogger(__name__)

# Per-agent timeout: each LLM call is capped at 30s so that a single
# hanging agent cannot stall the entire decision cycle beyond 90s.
_PER_AGENT_TIMEOUT = 30  # seconds per agent


def _should_skip_event_interpretation(
    assembled_context: AIPolicyContextView,
) -> bool:
    """이벤트가 없는 신규 BUY 경로에서는 EI를 생략한다."""
    source_type = (assembled_context.source_type or "core").strip().lower()
    if source_type != "core":
        return False
    if assembled_context.recent_events:
        return False
    if assembled_context.deterministic_trigger is None:
        return False

    position_snapshot = assembled_context.position_snapshot
    has_position = (
        position_snapshot is not None
        and position_snapshot.quantity is not None
        and position_snapshot.quantity > 0
    )
    if has_position:
        return False
    return True


def _is_fdc_actual_dispatch_target(assembled_context: AIPolicyContextView) -> bool:
    """held_position lane의 REDUCE_CANDIDATE/SELL_CANDIDATE(보유 포지션
    존재) 조건을 만족하는지만 판정한다(2026-08-27, held_position 실제
    dispatcher — PR #359 리뷰 보정). ``FDC_ACTUAL_DISPATCH_ENABLED``
    자체는 호출부가 별도로 AND 한다.

    ``deterministic_trigger_engine.py``의 후보 생성 로직상
    ``SELL_CANDIDATE``/``REDUCE_CANDIDATE``는 ``source_type ==
    "held_position"``일 때만 생성되므로, 별도 lane 식별자 없이
    ``primary_candidate`` 값 하나만으로 lane+후보 범위를 안전하게
    특정할 수 있다."""
    source_type = (assembled_context.source_type or "core").strip().lower()
    position_snapshot = assembled_context.position_snapshot
    has_position = (
        position_snapshot is not None
        and position_snapshot.quantity is not None
        and position_snapshot.quantity > 0
    )
    primary_candidate = (
        getattr(assembled_context.deterministic_trigger, "primary_candidate", "") or ""
    ).strip().upper()
    return (
        source_type == "held_position"
        and has_position
        and primary_candidate in ("REDUCE_CANDIDATE", "SELL_CANDIDATE")
    )


def _is_fdc_actual_dispatch_buy_target(assembled_context: AIPolicyContextView) -> bool:
    """core lane BUY_CANDIDATE 조건을 만족하는지만 판정하는 순수 함수
    (2026-09-02, BUY/core lane 확장 PR B — 설계 문서
    ``fdc_actual_dispatch_buy_core_lane_extension_design_2026-09-01.md``
    §5). ``FDC_ACTUAL_DISPATCH_BUY_ENABLED`` 자체는 이 함수의 관심사가
    아니다 — 호출부가 별도로 AND 한다. **이번 PR에서는 이 함수를 어떤
    runtime 분기에서도 호출하지 않는다** — 테스트 가능한 순수 함수로만
    존재하며, 실제 BUY dispatcher 경로 연결은 후속 PR(PR D 이후의
    PR E) 범위다.

    ``deterministic_trigger_engine.py``의 후보 생성 로직을 직접 확인한
    결과(assess_deterministic_triggers(), 266-297행), ``BUY_CANDIDATE``
    는 ``normalized_source_type != "held_position"``인 분기에서만
    ``entry_score >= buy_candidate_threshold`` 등 BUY eligibility를
    만족할 때 생성된다 — held_position 분기(SELL_CANDIDATE/
    REDUCE_CANDIDATE/WATCH만 생성)와는 서로 다른 코드 경로이므로
    이 함수와 ``_is_fdc_actual_dispatch_target()``(위)은 겹칠 수 없다.

    risk gate/eligibility/quote/sizing/submit-lane/reconciliation
    lock 같은 downstream 안전장치는 이 함수가 중복 구현하거나 우회하지
    않는다 — ``entry_score``/eligibility 판정 자체는 이미
    ``deterministic_trigger_engine.py``가 끝낸 뒤의 ``primary_
    candidate`` 값만 읽는다.
    """
    source_type = (assembled_context.source_type or "").strip().lower()
    primary_candidate = (
        getattr(assembled_context.deterministic_trigger, "primary_candidate", "") or ""
    ).strip().upper()
    return source_type == "core" and primary_candidate == "BUY_CANDIDATE"


def _should_skip_final_decision_composer(
    assembled_context: AIPolicyContextView,
    risk_output: AIRiskOutput,
) -> bool:
    """신규 BUY 경로에서 AR 고위험 결과면 FDC를 생략한다."""
    source_type = (assembled_context.source_type or "core").strip().lower()
    if source_type != "core":
        return False

    position_snapshot = assembled_context.position_snapshot
    has_position = (
        position_snapshot is not None
        and position_snapshot.quantity is not None
        and position_snapshot.quantity > 0
    )
    if has_position:
        return False

    if (risk_output.risk_opinion or "").strip().lower() == "reject":
        return True
    if risk_output.risk_score >= 0.85:
        return True
    return False


def _build_short_circuit_fdc_output(
    assembled_context: AIPolicyContextView,
    risk_output: AIRiskOutput,
) -> FinalDecisionComposerOutput:
    """AR 결과만으로 FDC를 생략할 때 사용할 synthetic composer output."""
    deterministic_trigger = assembled_context.deterministic_trigger
    decision_type = "HOLD"
    if (
        deterministic_trigger is not None
        and bool(deterministic_trigger.watch_candidate)
    ):
        decision_type = "WATCH"

    if (risk_output.risk_opinion or "").strip().lower() == "reject":
        detail = "risk_reject"
    else:
        detail = f"high_risk_score:{risk_output.risk_score:.2f}"

    return FinalDecisionComposerOutput(
        decision_type=decision_type,
        side="",
        reason_codes=("pre_ai_risk_short_circuit", detail),
        summary=(
            "[pre_ai_risk_short_circuit] 신규 진입 후보에서 "
            f"AR 결과({detail})로 FDC 호출을 생략하고 {decision_type}로 종료"
        ),
    )


class FdcActualDispatchPendingError(Exception):
    """FDC 실제 dispatch 대상 job이 quota reservation을 기다려야 해서
    이번 symbol coroutine 안에서 완결될 수 없음을 알리는 신호(2026-08-27
    2차 리뷰 보정 — PR #359).

    ``DecisionAgentRunner.run_agents_in_subprocess()``가 이 예외를 던지면
    ``assemble()``이 그대로 전파해 ``_run_decision_pipeline()``의 전용
    핸들러가 ``SubmitResult(status="FDC_ACTUAL_DISPATCH_PENDING", ...)``로
    변환한다 — ``asyncio.gather()``를 막지 않고 즉시 반환하기 위함이다.
    실제 reservation 대기/fdc_only 실행/병합은 호출자(``run_decision_
    loop.py``의 post-gather dispatcher)가 ``complete_fdc_actual_
    dispatch()``로 별도 수행한다.

    2026-08-28 4차 리뷰 보정(PR #359) — ``assembled_context``/
    ``provider_runtime``/``subprocess_timeout``을 더 이상 싣지 않는다.
    ``complete_fdc_actual_dispatch()``가 반환하는 bundle에는 이제 EV
    anchor를 적용하지 않는다(``DecisionOrchestratorService.assemble()``의
    ``precomputed_agent_bundle`` 분기가 자신이 이미 새로 만든 fresh
    context로 직접 적용한다) — 이 덕분에 ``pre_fdc_result``와 ``job_id``
    만으로 완전히 durable하게(DB에 저장 가능) carryover할 수 있다.
    ``provider_runtime``/``subprocess_timeout``도 decision 시점에 종속된
    값이 아니라 프로세스의 현재 설정값일 뿐이므로, 호출자가 필요할 때
    그때그때 새로 만든다.

    2026-08-31 리뷰 보정(운영 실측 결함) — ``decision_context_id``를
    명시적으로 싣는다. 이 예외는 ``assemble()`` 내부에서 이미 resolve된
    ``resolved_context_id``(``request.decision_context_id``로 전달됨,
    ``fdc_queue_jobs.decision_context_id``에 저장되는 값과 동일)를 담아
    호출자에게 전파한다 — 이전에는 이 값을 싣지 않아서, 이 예외를
    잡는 ``_run_decision_pipeline()``의 핸들러가 (아직 resolve되기
    전인) 바깥쪽 ``decision_context_id`` 인자(첫 호출에서는 ``None``)를
    그대로 ``SubmitResult``에 넣었고, 그 결과 durable resume/second
    pass가 항상 새 context를 만들어 ``fdc_queue_jobs``의 context와
    최종 ``trade_decisions``/``agent_runs`` context가 서로 어긋났다.
    """

    def __init__(
        self,
        *,
        job_id: uuid.UUID,
        pre_fdc_result: dict[str, Any],
        decision_context_id: uuid.UUID | None,
    ) -> None:
        super().__init__(f"FDC actual dispatch pending: job_id={job_id}")
        self.job_id = job_id
        self.pre_fdc_result = pre_fdc_result
        self.decision_context_id = decision_context_id


async def _spawn_agent_subprocess_impl(
    input_bytes: bytes,
    *,
    subprocess_timeout: int,
    decision_context_id: uuid.UUID | None,
    correlation_id: str,
) -> tuple[dict | None, bytes]:
    """subprocess를 스폰하고 timeout/SIGTERM/SIGKILL을 관리한다(2026-08-27
    모듈 레벨로 추출 — ``DecisionAgentRunner._spawn_agent_subprocess()``와
    post-gather dispatcher(``complete_fdc_actual_dispatch()``)가 인스턴스
    상태 없이 공유한다. 로직 변경 없음, 순수 이동).

    Returns
    -------
    (result, stdout)
        ``result``는 파싱된 stdout JSON dict — timeout이거나 파싱
        실패면 ``None``. ``stdout``은 원본 bytes(성공 시
        ``deserialize_agent_output()``에 그대로 재사용).
    """
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "scripts.run_agent_subprocess",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input_bytes),
            timeout=subprocess_timeout,
        )
    except asyncio.TimeoutError:
        stderr_hint = ""
        try:
            stderr_data = await asyncio.wait_for(
                proc.stderr.read(), timeout=2.0
            )
            if stderr_data:
                stderr_hint = stderr_data.decode("utf-8", errors="replace")[:2000]
        except (asyncio.TimeoutError, ProcessLookupError, Exception):
            pass

        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass

        logger.warning(
            "Agent subprocess timed out after %ds — "
            "using fallback output. decision_context_id=%s "
            "correlation_id=%s%s",
            subprocess_timeout,
            decision_context_id,
            correlation_id,
            f" stderr_hint={stderr_hint}" if stderr_hint else "",
        )
        return None, b""

    if stderr and stderr.strip():
        logger.info(
            "Agent subprocess stderr (decision_context_id=%s): %s",
            decision_context_id,
            stderr.decode("utf-8", errors="replace")[:2000],
        )

    try:
        result = json.loads(stdout)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error(
            "Failed to parse agent subprocess output: %s — "
            "using fallback output. decision_context_id=%s "
            "stdout_preview=%s",
            exc,
            decision_context_id,
            stdout[:500] if stdout else "(empty)",
        )
        return None, b""

    return result, stdout


def apply_expected_value_anchor(
    bundle: AgentExecutionBundle,
    *,
    assembled_context: AIPolicyContextView,
) -> AgentExecutionBundle:
    """EV anchor를 순수 함수로 계산해 적용한다(2026-08-27 모듈 레벨로
    추출 — ``DecisionAgentRunner._apply_expected_value_anchor()``와
    post-gather dispatcher가 인스턴스 상태 없이 공유한다. 로직 변경 없음)."""
    expected_value = evaluate_expected_value_gate(
        decision_type=bundle.ai_inputs.decision_type,
        confidence=bundle.ai_inputs.confidence,
        conviction=bundle.ai_inputs.conviction,
        risk_score=bundle.ai_inputs.risk_score,
        context=assembled_context,
    )
    return replace(
        bundle,
        ai_inputs=replace(
            bundle.ai_inputs,
            expected_return_bps=expected_value.expected_return_bps,
            expected_downside_bps=expected_value.expected_downside_bps,
            net_expected_value_bps=expected_value.net_expected_value_bps,
            final_trade_score=expected_value.final_trade_score,
            minimum_required_edge_bps=expected_value.minimum_required_edge_bps,
            edge_after_cost_bps=expected_value.edge_after_cost_bps,
            estimated_round_trip_cost_bps=expected_value.estimated_round_trip_cost_bps,
            slippage_buffer_bps=expected_value.slippage_buffer_bps,
            expected_value_gate_passed=expected_value.expected_value_gate_passed,
            expected_value_gate_reason_codes=expected_value.reason_codes,
        ),
    )


# PR D(2026-09-03) — global gate가 거부(timeout/DB 오류)해 실제 HTTP가
# 시작되지 않았을 때 fdc_only subprocess가 success=True로 남기는
# provider_final_status 값. final_decision_composer.py의
# _classify_provider_exception()이 PermitDeniedError.result.denial_reason
# ("global_gate_timeout"/"global_gate_error")을 이 두 문자열로 매핑한다.
_GLOBAL_GATE_DENIAL_STATUSES = frozenset({
    "provider_global_gate_timeout",
    "provider_global_gate_unavailable",
})


class FdcDispatchDeferredError(Exception):
    """post-gather dispatcher phase의 소프트 데드라인을 넘겨 이 job을
    시작(또는 재시도)할 시간이 없음을 알리는 신호(2026-08-27 3차 리뷰
    보정 — PR #359).

    이 예외가 발생하는 시점에는 **아직 소비되지 않은 reservation이 전혀
    없다** — ``complete_fdc_actual_dispatch()``의 루프는 매 iteration
    시작 시(=``try_reserve()`` 호출 직전) 데드라인을 확인하므로, 이미
    grant를 받은 뒤에는 항상 fdc_only 실행까지 같은 iteration 안에서
    끝까지 진행한다. 즉 이 예외는 job의 DB 상태(``QUEUED`` 또는 마지막
    attempt가 이미 종결된 채로 ``RESERVATION_GRANTED``)를 전혀 건드리지
    않고 던져진다 — 호출자(``run_decision_loop.py``)는 이 job을
    ``CANCELLED`` 처리하지 말고, 같은 프로세스의 다음 cycle에서 다시
    시도하도록 carryover 목록에 남겨야 한다(프로세스가 실제로 종료된
    경우에만 recovery scan이 정리한다).
    """

    def __init__(self, *, job_id: uuid.UUID) -> None:
        super().__init__(f"FDC actual dispatch deferred (deadline): job_id={job_id}")
        self.job_id = job_id


async def complete_fdc_actual_dispatch(
    *,
    fdc_quota_repo: Any,
    provider_runtime: dict[str, Any],
    subprocess_timeout: int,
    job_id: uuid.UUID,
    pre_fdc_result: dict[str, Any],
    correlation_id: str,
    decision_context_id: uuid.UUID | None,
    source_type: str,
    caller_id: str,
    worker_semaphore: asyncio.Semaphore,
    deadline_monotonic: float | None = None,
    sleep_fn: Any = None,
) -> AgentExecutionBundle:
    """FDC 실제 dispatch job 하나를 끝까지 처리한다(2026-08-28 4차 리뷰
    보정 — PR #359, post-gather dispatcher 전용).

    반환하는 bundle에는 EV anchor를 적용하지 **않는다**(4차 보정) —
    호출자(``DecisionOrchestratorService.assemble()``의 ``precomputed_
    agent_bundle`` 분기)가 자신이 새로 만든 fresh context로 직접
    적용한다. 이 함수는 ``pre_fdc_result``/``job_id``만으로 완전히
    durable하게(DB에 저장 가능) 동작해야 하므로 ``assembled_context``
    (position/cash/risk snapshot 등 낡을 수 있는 값을 포함)를 아예
    받지 않는다.

    **worker slot과 reservation의 실행 순서(4차 보정, 설계 문서 §7)** —
    이전 라운드는 ``try_reserve()``로 grant를 먼저 얻은 뒤 fdc_only
    실행 구간에만 ``worker_semaphore``를 걸었다. 이번 라운드는 순서를
    다음과 같이 바꿨다: **worker slot 확보 → atomic reservation →
    (grant면) 즉시 fdc_only 실행 → outcome 기록 → worker slot 반환.**
    ``ReservationDenied``/``CoordinatorError``면 slot을 즉시 반환한
    뒤(=``async with`` 블록을 빠져나온 뒤) poll/backoff ``sleep()``한다
    — semaphore를 잡은 채 sleep하지 않는다. FIFO 및 quota_scope 전역
    13 RPM sliding-window 판단(``try_reserve()`` 내부, anchor 행 잠금)은
    전혀 바뀌지 않았다 — anchor 잠금은 그 트랜잭션이 커밋되면 즉시
    풀리므로, worker slot 확보가 anchor 잠금과 겹쳐 있는 시간을 늘리지
    않는다.

    ``deadline_monotonic``이 주어지고 이미 지났다면, 루프 맨 앞(=worker
    slot을 잡기 전)에서 ``FdcDispatchDeferredError``를 던지고 **아무
    상태도 갱신하지 않는다** — grant를 받은 뒤에는 항상 fdc_only 실행
    까지 같은 iteration 안에서 끝까지 처리하므로, 이 예외가 발생했다는
    것은 "새로 소비된 reservation이 없다"는 뜻이다.

    ``job_id``에 대응하는 ``fdc_queue_jobs`` row는 이미 등록돼 있다는
    전제로 호출된다. 종결(성공/최종 실패)되면 job을 ``FDC_SUCCEEDED``/
    ``FDC_FAILED_FINAL``로 표시한다.

    2026-09-02 PR A 보정(BUY/core lane 확장 선행 작업) — ``source_type``/
    ``caller_id``는 호출부가 명시적으로 전달하는 keyword-only 인자다.
    이전에는 ``caller_id``가 ``"ops-scheduler:held_position_reduce_
    sell"``로, ``fdc_only`` payload의 ``source_type``이 ``"held_
    position"``으로 이 함수 내부에 고정돼 있었다 — 현재 유일한 호출부
    (``run_decision_loop.py``)는 여전히 이 두 값을 그대로 전달해야
    하며, 값 자체의 의미는 전혀 바뀌지 않는다(순수 파라미터화). 이
    함수는 ``source_type``이 무엇이어야 하는지 스스로 판단하지 않고
    호출부가 검증한 값을 그대로 신뢰한다 — 다만 빈 문자열처럼 명백히
    누락된 값은 ``"held_position"``으로 조용히 대입하지 않고 fail-
    closed로 종결한다(아래 참고).
    """
    from agent_trading.config.settings import (
        _resolve_fdc_provider_rate_window_seconds,
        _resolve_fdc_provider_target_rpm,
        _resolve_gemini_provider_declared_rpm_limit,
    )
    from agent_trading.repositories.contracts import (
        AttemptHttpLifecycle,
        CoordinatorError,
        ReservationDenied,
    )
    from agent_trading.services.fdc_quota_coordinator import (
        DEFAULT_QUOTA_SCOPE,
        FdcQuotaCoordinator,
    )

    if sleep_fn is None:
        sleep_fn = asyncio.sleep

    if not source_type or not source_type.strip():
        # 2026-09-02 PR A 보정 — source_type 누락을 "held_position"으로
        # 조용히 대입하지 않는다. durable resume이 불완전한 DB row를
        # 읽었거나 호출부 버그로 빈 값이 들어온 것이므로, 원인을 숨기지
        # 않고 fail-closed로 즉시 종결한다(불완전한 fdc_only payload를
        # 만들어 실제 HTTP를 내보내지 않는다).
        logger.error(
            "complete_fdc_actual_dispatch: job_id=%s source_type이 "
            "비어 있다 — 호출부 데이터 정합성 이상. 기본값으로 대체하지 "
            "않고 fail-closed로 종결한다.",
            job_id,
        )
        await fdc_quota_repo.mark_job_terminal(
            job_id=job_id, status="FDC_FAILED_FINAL",
            reason="fdc_actual_dispatch_source_type_missing_data_integrity_error",
        )
        return build_fallback_bundle()

    quota_scope = DEFAULT_QUOTA_SCOPE
    max_provider_attempts = 3
    poll_interval_seconds = 2.0
    coordinator_error_backoff_initial_seconds = 1.0
    coordinator_error_backoff_max_seconds = 30.0

    coordinator = FdcQuotaCoordinator(
        repo=fdc_quota_repo,
        target_rpm=_resolve_fdc_provider_target_rpm(),
        window_seconds=_resolve_fdc_provider_rate_window_seconds(),
        declared_rpm_limit=_resolve_gemini_provider_declared_rpm_limit(),
        quota_scope=quota_scope,
    )

    provider_attempt_no = 1
    coordinator_error_backoff = coordinator_error_backoff_initial_seconds

    while True:
        # ── 데드라인 확인(worker slot을 잡기 전) ─────────────────────────
        if (
            deadline_monotonic is not None
            and time_module.monotonic() >= deadline_monotonic
        ):
            raise FdcDispatchDeferredError(job_id=job_id)

        reservation_denied = False
        coordinator_error_hit = False

        # ── worker slot 확보 → atomic reservation → (grant면) 즉시
        # fdc_only 실행 → outcome 기록 → slot 반환(async with 종료) ──────
        async with worker_semaphore:
            result = await coordinator.try_reserve(
                job_id=job_id, caller_id=caller_id, mode="real",
                manual_run_id=None, attempt_no=provider_attempt_no,
            )
            if isinstance(result, ReservationDenied):
                reservation_denied = True
            elif isinstance(result, CoordinatorError):
                coordinator_error_hit = True
            else:
                coordinator_error_backoff = coordinator_error_backoff_initial_seconds
                grant = result

                fdc_only_payload = {
                    "decision_context_id": (
                        str(decision_context_id) if decision_context_id else None
                    ),
                    "correlation_id": correlation_id,
                    "symbol": pre_fdc_result.get("event_output", {}).get("symbol"),
                    "market": None,
                    "source_type": source_type,
                    "context": {},
                    "llm_provider": provider_runtime.get("llm_provider", ""),
                    "provider_api_key": provider_runtime.get("provider_api_key", ""),
                    "provider_base_url": provider_runtime.get("provider_base_url", ""),
                    "provider_model_id": provider_runtime.get("provider_model_id", ""),
                    "provider_timeout_seconds": provider_runtime.get(
                        "provider_timeout_seconds", 60,
                    ),
                    "mode": "fdc_only",
                    "event_interpretation_output": pre_fdc_result.get("event_output"),
                    "ai_risk_output": pre_fdc_result.get("risk_output"),
                    "ai_compliance_output": pre_fdc_result.get("compliance_output"),
                    "reservation_id": str(grant.reservation_id),
                    "reservation_job_id": str(job_id),
                    "reservation_attempt_no": grant.attempt_no,
                    "reservation_quota_scope": grant.quota_scope,
                    "reservation_window_count_before_grant": grant.window_count_before_grant,
                }
                fdc_only_result, fdc_only_stdout = await _spawn_agent_subprocess_impl(
                    json.dumps(fdc_only_payload).encode("utf-8"),
                    subprocess_timeout=subprocess_timeout,
                    decision_context_id=decision_context_id,
                    correlation_id=correlation_id,
                )

                if fdc_only_result is None or not fdc_only_result.get("success"):
                    # subprocess가 결과 없이 종료됐다(timeout/SIGKILL/JSON
                    # 파싱 실패/설정 단계 실패). tri-state lifecycle로
                    # "행이 없음"과 "행은 있으나 HTTP 미시작"을 구분한다.
                    lifecycle = await fdc_quota_repo.get_attempt_http_lifecycle(
                        reservation_id=grant.reservation_id,
                    )
                    if lifecycle == AttemptHttpLifecycle.NOT_FOUND:
                        logger.error(
                            "complete_fdc_actual_dispatch: job_id=%s "
                            "reservation_id=%s grant 직후인데 attempt 행이 "
                            "없다 — 데이터 정합성 이상. 재시도하지 않고 "
                            "fail-closed로 종결한다.",
                            job_id, grant.reservation_id,
                        )
                        await fdc_quota_repo.mark_job_terminal(
                            job_id=job_id, status="FDC_FAILED_FINAL",
                            reason="fdc_provider_attempt_row_missing_data_integrity_error",
                        )
                        return build_fallback_bundle()

                    if lifecycle == AttemptHttpLifecycle.NOT_STARTED:
                        # HTTP 시작 전 실패로 확인됨 — 안전하게 재시도할
                        # 수 있다. 2026-08-28 4차 리뷰 보정 — 직전에
                        # lifecycle을 NOT_STARTED로 확인했는데
                        # record_attempt_outcome()이 ValueError를 내면
                        # (그 사이 attempt 행이 사라진 race), 더 이상
                        # 조용히 무시하고 재시도하지 않는다 — 데이터
                        # 정합성 오류로 간주해 fail-closed 종결한다.
                        try:
                            await fdc_quota_repo.record_attempt_outcome(
                                reservation_id=grant.reservation_id,
                                outcome="reserved_but_http_not_started",
                                error_class="FdcOnlySubprocessCrashOrTimeout",
                            )
                        except ValueError:
                            logger.error(
                                "complete_fdc_actual_dispatch: job_id=%s "
                                "reservation_id=%s — lifecycle 조회 직후 "
                                "record_attempt_outcome()이 ValueError를 "
                                "냈다(attempt 행이 그 사이 사라진 race로 "
                                "추정). 재시도하지 않고 fail-closed로 "
                                "종결한다.",
                                job_id, grant.reservation_id,
                                exc_info=True,
                            )
                            await fdc_quota_repo.mark_job_terminal(
                                job_id=job_id, status="FDC_FAILED_FINAL",
                                reason="fdc_provider_attempt_outcome_write_race_data_integrity_error",
                            )
                            return build_fallback_bundle()

                        will_retry = provider_attempt_no < max_provider_attempts
                        # 2026-08-28 7차 리뷰 보정 — provider_retry_count/
                        # pre_http_execution_failure_count/queue_reenqueue_
                        # count는 will_retry=True(실제 FIFO tail 재등록)
                        # 일 때만 증가한다 — 소진으로 이어지는 마지막
                        # 실패는 재등록이 아니라 종결이므로 이 counter들을
                        # 과대 집계하지 않는다. will_retry=True면 같은
                        # 호출 안에서 job을 FIFO tail로 원자적으로
                        # 재등록한다(job_id는 그대로, enqueue_sequence만
                        # 새로 발급) — 이미 대기 중이던 다른 job의 순번을
                        # 침해하지 않는다.
                        await fdc_quota_repo.apply_retry_failure(
                            job_id=job_id, reason="pre_http_execution_failure",
                            will_retry=will_retry,
                        )
                        if will_retry:
                            provider_attempt_no += 1
                            continue
                        await fdc_quota_repo.mark_job_terminal(
                            job_id=job_id, status="FDC_FAILED_FINAL",
                            reason="fdc_only_subprocess_exhausted",
                        )
                        return build_fallback_bundle()

                    # STARTED — HTTP가 실제로 시작된 뒤 결과를 회수하지
                    # 못했다. 실제 Gemini 호출이 성공했는지 실패했는지
                    # 알 수 없으므로 자동 재시도(=중복 호출 위험)하지
                    # 않는다. 이미 기록된 "http_started" outcome을
                    # 덮어쓰거나 "HTTP 미시작"으로 잘못 기록하지 않는다.
                    # HTTP는 실제로 시작됐으므로 job 단위 http_attempt_
                    # count는 반영한다(429 여부는 알 수 없다).
                    await fdc_quota_repo.record_http_attempt_counters(
                        job_id=job_id, http_429_observed=False,
                    )
                    await fdc_quota_repo.mark_job_terminal(
                        job_id=job_id, status="FDC_FAILED_FINAL",
                        reason="fdc_only_subprocess_crashed_after_http_start_result_unknown",
                    )
                    return build_fallback_bundle()

                # 2026-09-03 PR D 보정 — success=True(=subprocess가
                # 결과 없이 죽지 않고 정상 종료)이지만 "HTTP가 실제로
                # 나갔다"는 6차 리뷰 보정의 전제가 깨지는 유일한 경우가
                # global gate 거부다. execute_fdc_one_shot_attempt()는
                # http_started를 기록하기 **직전**에 gate를 통과시키므로
                # (fdc_manual_provider_gate.py), 이 두 marker는 항상
                # pre-HTTP 실패이며 http_attempt_count를 건드리면 안
                # 된다 — record_http_attempt_counters() 호출보다 먼저
                # 갈라내, 기존 crash 경로(NOT_STARTED lifecycle)와 동일한
                # reason="pre_http_execution_failure"로 새 reservation
                # (새 try_reserve()/attempt_no)으로만 재시도한다(기존
                # reservation을 재사용하지 않는다).
                provider_final_status = fdc_only_result.get("provider_final_status", "")
                if provider_final_status in _GLOBAL_GATE_DENIAL_STATUSES:
                    will_retry = provider_attempt_no < max_provider_attempts
                    await fdc_quota_repo.apply_retry_failure(
                        job_id=job_id, reason="pre_http_execution_failure",
                        will_retry=will_retry,
                    )
                    if will_retry:
                        provider_attempt_no += 1
                        continue
                    await fdc_quota_repo.mark_job_terminal(
                        job_id=job_id, status="FDC_FAILED_FINAL",
                        reason=provider_final_status,
                    )
                    return build_fallback_bundle()

                # 2026-08-28 6차 리뷰 보정 — 이 시점에 fdc_only_result가
                # success=True이므로 HTTP가 실제로 나갔다(subprocess가
                # 결과 없이 죽은 경우는 위 branch에서 이미 처리됨). 성공/
                # provider 레벨 실패 여부와 무관하게 job 단위 http_
                # attempt_count/http_429_count를 정확히 1회 반영한다.
                await fdc_quota_repo.record_http_attempt_counters(
                    job_id=job_id,
                    http_429_observed=(
                        fdc_only_result.get("provider_http_429_count", 0) > 0
                    ),
                )

                retryable_statuses = {
                    "provider_rate_limit", "provider_error", "provider_timeout",
                }
                if provider_final_status in retryable_statuses:
                    will_retry = provider_attempt_no < max_provider_attempts
                    # HTTP가 실제로 시작된 뒤의 retryable 실패 —
                    # provider_retry_count/queue_reenqueue_count는
                    # will_retry=True(실제 FIFO tail 재등록)일 때만
                    # 증가한다(2026-08-28 7차 리뷰 보정). job_id는
                    # 유지한 채 재등록한다.
                    await fdc_quota_repo.apply_retry_failure(
                        job_id=job_id, reason="provider_retryable_failure",
                        will_retry=will_retry,
                    )
                    if will_retry:
                        provider_attempt_no += 1
                        continue
                    # 소진 — 아래 공통 terminal 처리로 넘어가
                    # FDC_FAILED_FINAL(reason=provider_final_status)로
                    # 종결된다.

                merged = dict(pre_fdc_result)
                merged["composer_output"] = fdc_only_result.get("composer_output", {})
                merged["provider_http_attempt_count"] = fdc_only_result.get(
                    "provider_http_attempt_count", 0
                )
                merged["provider_http_429_count"] = fdc_only_result.get(
                    "provider_http_429_count", 0
                )
                merged["provider_execution_seconds"] = fdc_only_result.get(
                    "provider_execution_seconds", 0.0
                )
                merged["provider_final_status"] = provider_final_status

                terminal_status = (
                    "FDC_SUCCEEDED"
                    if provider_final_status in ("", "success")
                    else "FDC_FAILED_FINAL"
                )
                await fdc_quota_repo.mark_job_terminal(
                    job_id=job_id, status=terminal_status,
                    reason=(
                        None if terminal_status == "FDC_SUCCEEDED"
                        else provider_final_status
                    ),
                )
                return deserialize_agent_output(json.dumps(merged).encode("utf-8"))

        # ── worker slot은 이미 반환됐다 — 여기서부터 poll/backoff sleep ──
        if reservation_denied:
            await sleep_fn(poll_interval_seconds)
            continue
        if coordinator_error_hit:
            await sleep_fn(coordinator_error_backoff)
            coordinator_error_backoff = min(
                coordinator_error_backoff * 2,
                coordinator_error_backoff_max_seconds,
            )
            continue


class DecisionAgentRunner:
    """Runs the three v1 Provider AI Agents (EI → AR → FDC) in sequence.

    Supports both in-process execution and subprocess-based execution
    with SIGKILL-guaranteed timeout.
    """

    def __init__(
        self,
        repos: RepositoryContainer,
        event_interpretation_agent: ProviderAIAgent,
        ai_risk_agent: ProviderAIAgent,
        ai_compliance_agent: ProviderAIAgent,
        final_decision_composer_agent: ProviderAIAgent,
        agent_run_recorder: AgentRunRecorder,
        score_calculator: ScoreCalculator | None = None,
        subprocess_timeout: int = 90,
        llm_provider: str = "",
        provider_api_key: str = "",
        provider_base_url: str = "",
        provider_model_id: str = "",
        provider_timeout_seconds: int = 60,
        fdc_actual_dispatch_enabled: bool = False,
    ) -> None:
        self._repos = repos
        self._ei_agent = event_interpretation_agent
        self._ar_agent = ai_risk_agent
        self._ac_agent = ai_compliance_agent
        self._fdc_agent = final_decision_composer_agent
        self._recorder = agent_run_recorder
        self._score_calculator = score_calculator or StubScoreCalculator()
        self._subprocess_timeout = subprocess_timeout
        self._provider_runtime = {
            "llm_provider": llm_provider,
            "provider_api_key": provider_api_key,
            "provider_base_url": provider_base_url,
            "provider_model_id": provider_model_id,
            "provider_timeout_seconds": provider_timeout_seconds,
        }
        # FDC 실제 dispatch 전환 스위치(2026-08-27, AppSettings.fdc_actual_
        # dispatch_enabled를 그대로 전달받음 — 다른 shadow 플래그와 동일한
        # constructor-injection 패턴). subprocess 경로에서만 의미가 있다
        # (in-process 경로 run_agents()는 이번 범위 밖, 변경 없음).
        self._fdc_actual_dispatch_enabled = fdc_actual_dispatch_enabled

    # ------------------------------------------------------------------
    # AI Agent execution — in-process
    # ------------------------------------------------------------------

    async def run_agents(
        self,
        request: AgentExecutionRequest,
        assembled_context: AIPolicyContextView,
    ) -> AgentExecutionBundle:
        """Execute the three v1 Provider AI Agents sequentially.

        Execution order
        ---------------
        1. Event Interpretation Agent
        2. AI Risk Agent
        3. AI Compliance Agent
        4. Final Decision Composer

        Each agent receives an ``AgentExecutionRequest`` built from the
        assembled context.  Individual outputs are kept as local variables
        and recorded via ``self._recorder``.

        Returns
        -------
        AgentExecutionBundle
            Normalised backend contract aggregating outputs from all three
            agents.  Always returned — even when every agent fails, a
            deterministic default ``AgentExecutionBundle()`` is provided.

        Safe-fallback policy
        --------------------
        If any agent raises an exception, a warning is logged and the
        agent's output defaults to an empty / safe structured output.
        The runner **always** proceeds — agent failures never
        block order assembly.

        Per-agent timeout
        -----------------
        Each agent call is wrapped with ``asyncio.wait_for()`` using
        ``_PER_AGENT_TIMEOUT`` (35s).  If an agent hangs beyond this
        limit, ``asyncio.TimeoutError`` is caught separately and the
        agent's output falls back to a safe default — the remaining
        agents still execute normally.
        """
        decision_context_id = request.decision_context_id
        correlation_id = request.correlation_id
        symbol = request.symbol

        # Log when no decision context is available — agent runs will be
        # recorded in-memory only (not persisted to Postgres) because
        # PostgresAgentRunRepository requires a valid FK reference.
        if decision_context_id is None:
            logger.info(
                "No active decision context — agent runs will be kept "
                "in-memory only (not persisted). correlation_id=%s",
                correlation_id,
            )

        # --- 1. Event Interpretation Agent ---
        event_output: EventInterpretationOutput
        ei_error_metadata: dict[str, object] | None = None
        ei_skipped = False
        fdc_skipped = False
        skip_reason_codes: list[str] = []
        if _should_skip_event_interpretation(assembled_context):
            from agent_trading.services.ai_agents.event_interpretation import (
                _finalize_ei_output,
            )
            event_output = EventInterpretationOutput()
            event_output = _finalize_ei_output(
                event_output,
                input_event_count=0,
                recent_events=(),
            )
            logger.info(
                "EI agent skipped: source_type=%s recent_events=0 "
                "decision_context_id=%s",
                assembled_context.source_type,
                decision_context_id,
            )
            ei_skipped = True
            skip_reason_codes.append("skip_ei_no_recent_events")
        else:
            _t0 = time_module.monotonic()
            try:
                event_output = await asyncio.wait_for(
                    self._ei_agent.run(request),
                    timeout=_PER_AGENT_TIMEOUT,
                )
                logger.info(
                    "EI agent completed in %.2fs — decision_context_id=%s",
                    time_module.monotonic() - _t0,
                    decision_context_id,
                )
                # ★ 성공 경로: agent가 내부적으로 예외를 catch한 경우
                #   _last_error_metadata에 분류된 error metadata가 있음.
                #   정상 성공 시에는 None이 보장됨.
                ei_error_metadata = self._ei_agent.last_error_metadata
            except asyncio.TimeoutError:
                logger.warning(
                    "Event Interpretation Agent timed out after %ds (actual %.2fs) — "
                    "using default output (safe fallback). decision_context_id=%s",
                    _PER_AGENT_TIMEOUT,
                    time_module.monotonic() - _t0,
                    decision_context_id,
                )
                event_output = EventInterpretationOutput()
                # ★ P0: timeout 시 degraded 플래그 설정
                degraded_av = replace(
                    event_output.aggregate_view,
                    interpretation_incomplete=True,
                    degraded_reason="timeout",
                )
                object.__setattr__(event_output, "aggregate_view", degraded_av)
                # ★ timeout fallback: _finalize_ei_output()로 interpreted_event_count, summary_basis, summary 설정
                from agent_trading.services.ai_agents.event_interpretation import (
                    _finalize_ei_output,
                )
                event_output = _finalize_ei_output(event_output)
                ei_error_metadata = {
                    "error_type": "timeout",
                    "error_message": f"asyncio.TimeoutError after {_PER_AGENT_TIMEOUT}s",
                    "http_status": None,
                    "retryable": True,
                    "timeout_source": "orchestrator",
                }
            except Exception:
                logger.warning(
                    "Event Interpretation Agent failed after %.2fs — using default "
                    "output (safe fallback). decision_context_id=%s",
                    time_module.monotonic() - _t0,
                    decision_context_id,
                    exc_info=True,
                )
                event_output = EventInterpretationOutput()
                # ★ P0: provider_error 시 degraded 플래그 설정
                degraded_av = replace(
                    event_output.aggregate_view,
                    interpretation_incomplete=True,
                    degraded_reason="provider_error",
                )
                object.__setattr__(event_output, "aggregate_view", degraded_av)
                # ★ exception fallback: _finalize_ei_output()로 interpreted_event_count, summary_basis, summary 설정
                from agent_trading.services.ai_agents.event_interpretation import (
                    _finalize_ei_output,
                )
                event_output = _finalize_ei_output(event_output)
                ei_error_metadata = {
                    "error_type": "provider_error",
                    "error_message": "Unexpected agent failure at orchestrator level",
                    "http_status": None,
                    "retryable": None,
                    "timeout_source": None,
                }

        if is_missing_agent_symbol(event_output.symbol) and symbol:
            event_output = replace(event_output, symbol=symbol)

        # ★ structured_output에 __error__ 메타데이터 포함 (실패 시에만)
        ei_structured_output: dict[str, object] = dataclass_to_dict(event_output)
        if ei_error_metadata is not None:
            ei_structured_output["__error__"] = ei_error_metadata  # type: ignore[typeddict-unknown-key]

        await self._recorder.record(
            decision_context_id=decision_context_id,
            agent_type=self._ei_agent.agent_name,
            structured_output=ei_structured_output,
        )

        # ── EI top_reason_codes empty detection ─────────────────────
        if (event_output.aggregate_view
                and not event_output.aggregate_view.top_reason_codes
                and event_output.detected_event_count > 0):
            logger.warning(
                "EI top_reason_codes is empty but detected_event_count=%d "
                "(symbol=%s) — LLM may have omitted the field in aggregation",
                event_output.detected_event_count, symbol,
            )

        # --- Build a new request with the EI output for downstream agents ---
        # AgentExecutionRequest is frozen, so we must create a new instance.
        # When EI fails, event_output is an empty EventInterpretationOutput(),
        # so downstream agents always receive a structured value (never None).
        request_with_ei = AgentExecutionRequest(
            decision_context_id=request.decision_context_id,
            correlation_id=request.correlation_id,
            context=request.context,
            symbol=request.symbol,
            market=request.market,
            event_interpretation_output=event_output,
            model_id=request.model_id,
            prompt_id=request.prompt_id,
            source_type=request.source_type,
        )

        # --- 2. AI Risk Agent ---
        risk_output: AIRiskOutput
        _t1 = time_module.monotonic()
        try:
            risk_output = await asyncio.wait_for(
                self._ar_agent.run(request_with_ei),
                timeout=_PER_AGENT_TIMEOUT,
            )
            logger.info(
                "AR agent completed in %.2fs — decision_context_id=%s",
                time_module.monotonic() - _t1,
                decision_context_id,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "AI Risk Agent timed out after %ds (actual %.2fs) — "
                "using default output (safe fallback). decision_context_id=%s",
                _PER_AGENT_TIMEOUT,
                time_module.monotonic() - _t1,
                decision_context_id,
            )
            risk_output = AIRiskOutput()
        except Exception:
            logger.warning(
                "AI Risk Agent failed after %.2fs — using default output "
                "(safe fallback). decision_context_id=%s",
                time_module.monotonic() - _t1,
                decision_context_id,
                exc_info=True,
            )
            risk_output = AIRiskOutput()

        if is_missing_agent_symbol(risk_output.symbol) and symbol:
            risk_output = replace(risk_output, symbol=symbol)

        await self._recorder.record(
            decision_context_id=decision_context_id,
            agent_type=self._ar_agent.agent_name,
            structured_output=dataclass_to_dict(risk_output),
        )

        # --- 3. AI Compliance Agent ---
        compliance_output: AIComplianceOutput
        request_with_ei_and_ar = AgentExecutionRequest(
            decision_context_id=request.decision_context_id,
            correlation_id=request.correlation_id,
            context=request.context,
            symbol=request.symbol,
            market=request.market,
            event_interpretation_output=event_output,
            ai_risk_output=risk_output,
            model_id=request.model_id,
            prompt_id=request.prompt_id,
            source_type=request.source_type,
        )
        _t1b = time_module.monotonic()
        try:
            compliance_output = await asyncio.wait_for(
                self._ac_agent.run(request_with_ei_and_ar),
                timeout=_PER_AGENT_TIMEOUT,
            )
            logger.info(
                "AC agent completed in %.2fs — decision_context_id=%s",
                time_module.monotonic() - _t1b,
                decision_context_id,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "AI Compliance Agent timed out after %ds (actual %.2fs) — "
                "using default output (safe fallback). decision_context_id=%s",
                _PER_AGENT_TIMEOUT,
                time_module.monotonic() - _t1b,
                decision_context_id,
            )
            compliance_output = AIComplianceOutput()
        except Exception:
            logger.warning(
                "AI Compliance Agent failed after %.2fs — using default output "
                "(safe fallback). decision_context_id=%s",
                time_module.monotonic() - _t1b,
                decision_context_id,
                exc_info=True,
            )
            compliance_output = AIComplianceOutput()

        if is_missing_agent_symbol(compliance_output.symbol) and symbol:
            compliance_output = replace(compliance_output, symbol=symbol)

        await self._recorder.record(
            decision_context_id=decision_context_id,
            agent_type=self._ac_agent.agent_name,
            structured_output=dataclass_to_dict(compliance_output),
        )

        # --- Build a new request with EI, AR, and AC output for FDC ---
        # AgentExecutionRequest is frozen, so we must create a new instance.
        # When AR/AC fail, fallback outputs keep FDC input structured.
        # receives a structured value (never None).
        request_with_ei_and_ar_ac = AgentExecutionRequest(
            decision_context_id=request.decision_context_id,
            correlation_id=request.correlation_id,
            context=request.context,
            symbol=request.symbol,
            market=request.market,
            event_interpretation_output=event_output,
            ai_risk_output=risk_output,
            ai_compliance_output=compliance_output,
            model_id=request.model_id,
            prompt_id=request.prompt_id,
            source_type=request.source_type,
        )

        # --- 4. Final Decision Composer Agent ---
        composer_output: FinalDecisionComposerOutput
        if _should_skip_final_decision_composer(assembled_context, risk_output):
            composer_output = _build_short_circuit_fdc_output(
                assembled_context,
                risk_output,
            )
            logger.info(
                "FDC agent skipped: source_type=%s risk_opinion=%s risk_score=%.2f "
                "decision_context_id=%s",
                assembled_context.source_type,
                risk_output.risk_opinion,
                risk_output.risk_score,
                decision_context_id,
            )
            fdc_skipped = True
            skip_reason_codes.append("skip_fdc_high_risk")
            fdc_ready_at = ""
        else:
            # FDC cycle-scoped batch queue lifecycle shadow(Phase 1) 전용 —
            # subprocess 경로(run_agent_subprocess.py)와 동일한 캡처
            # 지점: "FDC 호출이 필요하다"는 판정 직후, 실제 호출 직전.
            fdc_ready_at = datetime.now(timezone.utc).isoformat()
            _t2 = time_module.monotonic()
            try:
                composer_output = await asyncio.wait_for(
                    self._fdc_agent.run(request_with_ei_and_ar_ac),
                    timeout=_PER_AGENT_TIMEOUT,
                )
                logger.info(
                    "FDC agent completed in %.2fs — decision_context_id=%s",
                    time_module.monotonic() - _t2,
                    decision_context_id,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Final Decision Composer Agent timed out after %ds (actual %.2fs) — "
                    "using default output (safe fallback). decision_context_id=%s",
                    _PER_AGENT_TIMEOUT,
                    time_module.monotonic() - _t2,
                    decision_context_id,
                )
                composer_output = FinalDecisionComposerOutput()
            except Exception:
                logger.warning(
                    "Final Decision Composer Agent failed after %.2fs — using default "
                    "output (safe fallback). decision_context_id=%s",
                    time_module.monotonic() - _t2,
                    decision_context_id,
                    exc_info=True,
                )
                composer_output = FinalDecisionComposerOutput()

        if is_missing_agent_symbol(composer_output.symbol) and symbol:
            composer_output = replace(composer_output, symbol=symbol)

        await self._recorder.record(
            decision_context_id=decision_context_id,
            agent_type=self._fdc_agent.agent_name,
            structured_output=dataclass_to_dict(composer_output),
        )

        logger.info(
            "AI agents executed: decision_context_id=%s "
            "event=%s risk=%s compliance=%s composer=%s",
            decision_context_id,
            event_output.agent_name,
            risk_output.risk_opinion,
            compliance_output.compliance_opinion,
            composer_output.decision_type,
        )

        # --- 단일 정규화: composer raw output → canonical decision_type ---
        # recording 이후, AIDecisionInputs 조립 전에 한 번만 normalize.
        # 이후 모든 downstream (AIDecisionInputs, AgentExecutionBundle,
        # _ensure_trade_decision)은 normalized value만 사용.
        normalized_dt = normalize_decision_type(composer_output.decision_type)
        if normalized_dt != composer_output.decision_type:
            composer_output = replace(composer_output, decision_type=normalized_dt)
            logger.info(
                "Normalized decision_type: %s → %s",
                composer_output.decision_type,
                normalized_dt,
            )

        # --- Assemble AIDecisionInputs from all three agent outputs ---
        ai_inputs = AIDecisionInputs(
            # FDC-derived
            decision_type=composer_output.decision_type,
            confidence=composer_output.confidence,
            conviction=composer_output.conviction,
            reason_codes=composer_output.reason_codes,
            opposing_evidence=composer_output.opposing_evidence,
            execution_preferences=composer_output.execution_preferences,
            sizing_hint=composer_output.sizing_hint,
            side=composer_output.side if composer_output and hasattr(composer_output, 'side') else "",
            # AR-derived
            risk_opinion=risk_output.risk_opinion,
            risk_score=risk_output.risk_score,
            risk_confidence=risk_output.confidence,
            size_adjustment_factor=risk_output.size_adjustment_factor,
            risk_reason_codes=risk_output.reason_codes,
            risk_flags=risk_output.risk_flags,
            # AC-derived
            compliance_opinion=compliance_output.compliance_opinion,
            compliance_score=compliance_output.compliance_score,
            compliance_confidence=compliance_output.confidence,
            compliance_reason_codes=compliance_output.reason_codes,
            compliance_policy_flags=compliance_output.policy_flags,
            compliance_check_passed=(
                compliance_output.compliance_opinion in {"allow", "warn"}
            ),
            # EI-derived
            event_bias=event_output.aggregate_view.overall_bias,
            event_conflict=event_output.aggregate_view.event_conflict,
            event_reason_codes=event_output.aggregate_view.top_reason_codes,
            evidence_strength=event_output.aggregate_view.evidence_strength,
            no_material_events=event_output.aggregate_view.no_material_events,
            detected_event_count=event_output.detected_event_count,
            interpreted_event_count=event_output.interpreted_event_count,
            # Metadata
            source_agent_names=(
                event_output.agent_name,
                risk_output.agent_name,
                compliance_output.agent_name,
                composer_output.agent_name,
            ),
            schema_versions=(
                ("event_interpretation", event_output.schema_version),
                ("ai_risk", risk_output.schema_version),
                ("ai_compliance", compliance_output.schema_version),
                ("final_decision_composer", composer_output.schema_version),
            ),
            ei_skipped=ei_skipped,
            ar_skipped=False,
            fdc_skipped=fdc_skipped,
            fdc_ready_at=fdc_ready_at,
            skip_reason_codes=tuple(skip_reason_codes),
        )
        expected_value = evaluate_expected_value_gate(
            decision_type=ai_inputs.decision_type,
            confidence=ai_inputs.confidence,
            conviction=ai_inputs.conviction,
            risk_score=ai_inputs.risk_score,
            context=assembled_context,
        )
        ai_inputs = replace(
            ai_inputs,
            expected_return_bps=expected_value.expected_return_bps,
            expected_downside_bps=expected_value.expected_downside_bps,
            net_expected_value_bps=expected_value.net_expected_value_bps,
            final_trade_score=expected_value.final_trade_score,
            minimum_required_edge_bps=expected_value.minimum_required_edge_bps,
            edge_after_cost_bps=expected_value.edge_after_cost_bps,
            estimated_round_trip_cost_bps=expected_value.estimated_round_trip_cost_bps,
            slippage_buffer_bps=expected_value.slippage_buffer_bps,
            expected_value_gate_passed=expected_value.expected_value_gate_passed,
            expected_value_gate_reason_codes=expected_value.reason_codes,
        )

        return AgentExecutionBundle(
            ai_inputs=ai_inputs,
            event_output=event_output,
            risk_output=risk_output,
            compliance_output=compliance_output,
            composer_output=composer_output,
        )

    # ------------------------------------------------------------------
    # AI Agent execution — subprocess isolation
    # ------------------------------------------------------------------

    async def run_agents_in_subprocess(
        self,
        request: AgentExecutionRequest,
        assembled_context: AIPolicyContextView,
    ) -> AgentExecutionBundle:
        """Run agents in a subprocess with SIGKILL-guaranteed timeout.

        This is the Phase 4 subprocess-isolated alternative to
        ``run_agents()``.  It serializes the agent input, spawns a
        subprocess via ``scripts.run_agent_subprocess``, and enforces a
        timeout.  If the subprocess times out, SIGTERM (10s grace)
        → SIGKILL is used to forcibly terminate C-level httpx I/O
        blocking.

        Returns
        -------
        AgentExecutionBundle
            Always returned — even on timeout or subprocess failure,
            a deterministic fallback ``AgentExecutionBundle`` is
            provided (same safe-fallback policy as ``run_agents()``).

        Timeout handling
        ----------------
        The combined timeout covers all 3 agents plus subprocess
        creation/teardown overhead.

        FDC 실제 dispatch(2026-08-27, held_position lane REDUCE_CANDIDATE/
        SELL_CANDIDATE 한정 — PR #359 리뷰 보정): flag가 켜져 있고
        ``assembled_context``가 대상 lane/후보(``_is_fdc_actual_dispatch_
        target()``)면 이 메서드는 이 아래 단일-subprocess 경로(``mode=
        "full"``) 대신 ``_run_agents_in_subprocess_with_actual_dispatch()``
        (§17 pre_fdc/fdc_only 분리 + 실제 quota reservation/FIFO 대기)로
        위임한다. flag=false이거나 비대상 lane이면 이 분기 자체가 평가되지
        않으므로(``_is_fdc_actual_dispatch_target()``가 호출되지 않음)
        기존 동작과 100% 동일하다.
        """
        if self._fdc_actual_dispatch_enabled and _is_fdc_actual_dispatch_target(
            assembled_context,
        ):
            return await self._run_agents_in_subprocess_with_actual_dispatch(
                request, assembled_context,
            )

        # ── 1. Serialize input ────────────────────────────────────────
        input_bytes = serialize_agent_input(
            request=request,
            context=assembled_context,
            score=None,
            provider_runtime=self._provider_runtime,
        ).encode("utf-8")

        result, stdout = await self._spawn_agent_subprocess(
            input_bytes, request=request,
        )
        if result is None:
            return build_fallback_bundle()

        return self._finalize_subprocess_result(
            result, stdout, request=request, assembled_context=assembled_context,
        )

    async def _spawn_agent_subprocess(
        self, input_bytes: bytes, *, request: AgentExecutionRequest,
    ) -> tuple[dict | None, bytes]:
        """``_spawn_agent_subprocess_impl()``의 인스턴스 wrapper(하위
        호환 — 기존 호출부가 그대로 쓸 수 있도록 유지)."""
        return await _spawn_agent_subprocess_impl(
            input_bytes, subprocess_timeout=self._subprocess_timeout,
            decision_context_id=request.decision_context_id,
            correlation_id=request.correlation_id,
        )

    def _finalize_subprocess_result(
        self,
        result: dict,
        stdout: bytes,
        *,
        request: AgentExecutionRequest,
        assembled_context: AIPolicyContextView,
    ) -> AgentExecutionBundle:
        """파싱된 subprocess 결과를 ``AgentExecutionBundle``로 변환하고
        EV anchor를 적용한다(2026-08-27 추출 — 기존 6단계 순수 이동)."""
        if not result.get("success"):
            logger.warning(
                "Agent subprocess reported failure: %s — "
                "using fallback output. decision_context_id=%s",
                result.get("error", "unknown error"),
                request.decision_context_id,
            )
            return self._apply_expected_value_anchor(
                build_fallback_bundle(),
                assembled_context=assembled_context,
            )

        return self._apply_expected_value_anchor(
            deserialize_agent_output(stdout),
            assembled_context=assembled_context,
        )

    async def _run_agents_in_subprocess_with_actual_dispatch(
        self,
        request: AgentExecutionRequest,
        assembled_context: AIPolicyContextView,
    ) -> AgentExecutionBundle:
        """held_position REDUCE_CANDIDATE/SELL_CANDIDATE 실제 FDC dispatch
        진입점(2026-08-27 2차 리뷰 보정 — PR #359, 설계 문서 §17/§4).

        **이 메서드는 quota reservation을 절대 기다리지 않는다** — symbol
        coroutine이 ``asyncio.gather()``를 무기한 막으면 ops-scheduler의
        decision subprocess timeout(420초)에 걸려 프로세스 전체가
        SIGKILL되고, 그 cycle의 다른 모든 symbol 결과까지 함께 소실되기
        때문이다(1차 리뷰 이후 재보정).

        1. ``mode="pre_fdc"`` subprocess로 EI/AR/AC + FDC skip 판정만
           받는다. FDC가 결정론적으로 skip됐으면(``requires_fdc_
           dispatch=False``) 그 결과를 그대로 최종 결과로 쓴다(기존
           ``--mode full``의 skip 경로와 동일한 산출물) — 이 경우는 원래도
           대기가 필요 없었으므로 이번 cycle 안에서 완결된다.
        2. FDC-ready면 ``self._repos.fdc_quota``에 실제(``mode='real'``)
           job을 등록하고, ``FdcActualDispatchPendingError(job_id=...,
           pre_fdc_result=...)``를 즉시 던진다 — reservation 대기/
           fdc_only 실행은 전혀 하지 않는다. 이 예외는 ``assemble()``을
           그대로 통과해 ``_run_decision_pipeline()``의 전용 핸들러가
           ``SubmitResult(status="FDC_ACTUAL_DISPATCH_PENDING", ...)``로
           변환하고, 호출자(``run_decision_loop.py``)가 이를 post-gather
           dispatcher의 pending sink에 적재한다. 실제 reservation 대기 +
           fdc_only 실행 + 병합은 ``complete_fdc_actual_dispatch()``(모듈
           레벨 함수, 이 클래스 밖)가 별도 concurrency(``FDC_WORKER_
           CONCURRENCY``)로 수행한다.

        ``request``/``assembled_context``가 이미 대상 lane임을
        ``run_agents_in_subprocess()``가 확인했다는 전제로 호출된다.
        """
        pre_fdc_input = serialize_agent_input(
            request=request, context=assembled_context, score=None,
            provider_runtime=self._provider_runtime, mode="pre_fdc",
        ).encode("utf-8")
        pre_fdc_result, pre_fdc_stdout = await self._spawn_agent_subprocess(
            pre_fdc_input, request=request,
        )
        if pre_fdc_result is None:
            return build_fallback_bundle()
        if not pre_fdc_result.get("requires_fdc_dispatch"):
            # 결정론적 skip이거나 subprocess 실패 — 기존 산출물을 그대로 쓴다.
            return self._finalize_subprocess_result(
                pre_fdc_result, pre_fdc_stdout,
                request=request, assembled_context=assembled_context,
            )

        from agent_trading.services.fdc_quota_coordinator import DEFAULT_QUOTA_SCOPE

        quota_scope = DEFAULT_QUOTA_SCOPE
        fdc_ready_at_raw = pre_fdc_result.get("fdc_ready_at") or ""
        try:
            fdc_ready_at = (
                datetime.fromisoformat(fdc_ready_at_raw)
                if fdc_ready_at_raw else datetime.now(timezone.utc)
            )
        except ValueError:
            fdc_ready_at = datetime.now(timezone.utc)

        # 2026-08-28 5차 리뷰 보정(PR #359) — durable resume 계약(§17.3/
        # §17.7)은 register_real_job()의 actual-dispatch 호출 경로에서
        # pre_fdc_result/correlation_id가 "선택"이 아니라 "필수"임을
        # 전제한다. 이 두 값이 없는 채로 QUEUED job이 등록되면, 그
        # 불완전한 row 하나가 try_reserve()의 FIFO admission을 영구
        # 차단할 수 있다(뒤따르는 모든 real job이 "나보다 먼저 등록된
        # QUEUED job이 있다"는 이유로 계속 거절됨). 이 시점에서
        # pre_fdc_result는 이미 non-None임이 위에서 보장됐으므로, 여기서
        # 실제로 방어하는 것은 request.correlation_id 누락이다(정상
        # 경로에서는 DecisionOrchestratorService.assemble()이 항상 채워
        # 넘기므로 도달하지 않아야 하는 방어 코드) — 발생하면 애초에
        # 등록하지 않고 fail-closed로 fallback한다(불완전한 row를 만들지
        # 않는 것이 resume-scan의 사후 정리보다 우선한다).
        if not request.correlation_id:
            logger.error(
                "_run_agents_in_subprocess_with_actual_dispatch: "
                "request.correlation_id가 비어 있다 — durable resume에 "
                "필수인 값이 없어 real job을 등록하지 않는다(데이터 "
                "정합성 이상, fail-closed).",
            )
            return build_fallback_bundle()

        # 2026-09-02 PR A 보정(BUY/core lane 확장 선행 작업) — 이전에는
        # ``request.source_type or "held_position"``로 값이 비어 있으면
        # 조용히 "held_position"을 대입했다. 이 메서드는
        # ``run_agents_in_subprocess()``의 ``_is_fdc_actual_dispatch_
        # target()`` 게이트(3조건 AND, held_position 전용, 무변경)를
        # 통과한 뒤에만 호출되므로, 이 시점의 ``assembled_context.
        # source_type``은 항상 ``"held_position"``이어야 한다 — 그 외
        # 값(빈 문자열 포함)이 들어오면 게이트와 실제 호출 사이에 정합성
        # 이상이 있다는 뜻이다. "held_position"으로 자동 치환하지 않고
        # 원인을 숨기지 않는 fail-closed로 종결한다.
        resolved_source_type = (assembled_context.source_type or "").strip()
        if resolved_source_type != "held_position":
            logger.error(
                "_run_agents_in_subprocess_with_actual_dispatch: 예상치 "
                "못한 source_type=%r로 이 경로에 도달했다(_is_fdc_"
                "actual_dispatch_target()가 held_position만 통과시켜야 "
                "하므로 발생해서는 안 되는 상태) — 'held_position'으로 "
                "조용히 치환하지 않고 fail-closed로 종결한다.",
                resolved_source_type,
            )
            return build_fallback_bundle()

        job_id = await self._repos.fdc_quota.register_real_job(
            decision_cycle_id=request.correlation_id,
            decision_context_id=request.decision_context_id,
            symbol=request.symbol or "",
            source_type=resolved_source_type,
            quota_scope=quota_scope,
            fdc_ready_at=fdc_ready_at,
            # 2026-08-28 4차 리뷰 보정(PR #359, durable carryover) —
            # ops-scheduler는 항상 --count 1 단발 프로세스이므로, 이 job이
            # 이번 프로세스 안에서 완결되지 못하면 in-memory carryover만
            # 으로는 재개할 방법이 없다. pre_fdc_result/correlation_id를
            # DB에 함께 저장해 다음 프로세스가 agent를 다시 호출하지
            # 않고 안전하게 재개할 수 있게 한다.
            pre_fdc_result=pre_fdc_result,
            correlation_id=request.correlation_id,
        )
        raise FdcActualDispatchPendingError(
            job_id=job_id, pre_fdc_result=pre_fdc_result,
            decision_context_id=request.decision_context_id,
        )

    def _apply_expected_value_anchor(
        self,
        bundle: AgentExecutionBundle,
        *,
        assembled_context: AIPolicyContextView,
    ) -> AgentExecutionBundle:
        """모듈 레벨 ``apply_expected_value_anchor()``(순수 함수)로 위임한다
        (2026-08-27 추출 — 로직 변경 없음, post-gather dispatcher와 공유)."""
        return apply_expected_value_anchor(bundle, assembled_context=assembled_context)
