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
from dataclasses import replace
from datetime import datetime, timezone

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
        """subprocess를 스폰하고 timeout/SIGTERM/SIGKILL을 관리한다
        (2026-08-27 추출 — ``run_agents_in_subprocess()``의 기존 2~5단계를
        순수 이동. 로직 변경 없음, ``_run_agents_in_subprocess_with_
        actual_dispatch()``가 pre_fdc/fdc_only 두 번의 spawn에 재사용하기
        위해 별도 메서드로 뺐다).

        Returns
        -------
        (result, stdout)
            ``result``는 파싱된 stdout JSON dict — timeout이거나 파싱
            실패면 ``None``. ``stdout``은 원본 bytes(성공 시
            ``deserialize_agent_output()``에 그대로 재사용).
        """
        _SUBPROCESS_TIMEOUT = self._subprocess_timeout

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "scripts.run_agent_subprocess",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input_bytes),
                timeout=_SUBPROCESS_TIMEOUT,
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
                _SUBPROCESS_TIMEOUT,
                request.decision_context_id,
                request.correlation_id,
                f" stderr_hint={stderr_hint}" if stderr_hint else "",
            )
            return None, b""

        if stderr and stderr.strip():
            logger.info(
                "Agent subprocess stderr (decision_context_id=%s): %s",
                request.decision_context_id,
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
                request.decision_context_id,
                stdout[:500] if stdout else "(empty)",
            )
            return None, b""

        return result, stdout

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
        (2026-08-27 신설 — PR #359 리뷰 보정, 설계 문서 §17).

        1. ``mode="pre_fdc"`` subprocess로 EI/AR/AC + FDC skip 판정만
           받는다. FDC가 결정론적으로 skip됐으면(``requires_fdc_
           dispatch=False``) 그 결과를 그대로 최종 결과로 쓴다(기존
           ``--mode full``의 skip 경로와 동일한 산출물).
        2. FDC-ready면 ``self._repos.fdc_quota``에 실제(``mode='real'``)
           job을 등록하고, quota reservation이 발급될 때까지 대기한다
           (deadline 없음, §4 "순번 탈락 금지" — quota가 가득 차거나
           FIFO 순번이 아니면 poll interval만큼 대기 후 재시도, DB/
           coordinator 오류는 지수 backoff).
        3. 발급되면 ``mode="fdc_only"`` subprocess를 스폰해 그 grant로
           HTTP one-shot만 실행한다. provider가 retryable 실패(429/5xx/
           timeout)면 **새 reservation**으로 재시도한다(최대
           ``max_provider_attempts``회) — 같은 grant를 재사용하지 않는다.
        4. 종결(성공/최종 실패)되면 job을 ``FDC_SUCCEEDED``/``FDC_FAILED_
           FINAL``로 표시하고, pre_fdc의 EI/AR/AC 결과와 fdc_only의 FDC
           결과를 병합해 최종 ``AgentExecutionBundle``을 만든다.

        ``request``/``assembled_context``가 이미 대상 lane임을
        ``run_agents_in_subprocess()``가 확인했다는 전제로 호출된다.
        """
        from agent_trading.config.settings import (
            _resolve_fdc_provider_rate_window_seconds,
            _resolve_fdc_provider_target_rpm,
            _resolve_gemini_provider_declared_rpm_limit,
        )
        from agent_trading.repositories.contracts import (
            CoordinatorError,
            ReservationDenied,
        )
        from agent_trading.services.fdc_quota_coordinator import (
            DEFAULT_QUOTA_SCOPE,
            FdcQuotaCoordinator,
        )

        caller_id = "ops-scheduler:held_position_reduce_sell"
        manual_run_id = request.correlation_id
        quota_scope = DEFAULT_QUOTA_SCOPE
        max_provider_attempts = 3
        poll_interval_seconds = 2.0
        coordinator_error_backoff_initial_seconds = 1.0
        coordinator_error_backoff_max_seconds = 30.0

        # ── 1. pre_fdc ────────────────────────────────────────────────
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

        # ── 2. 실제 job 등록 ──────────────────────────────────────────
        coordinator = FdcQuotaCoordinator(
            repo=self._repos.fdc_quota,
            target_rpm=_resolve_fdc_provider_target_rpm(),
            window_seconds=_resolve_fdc_provider_rate_window_seconds(),
            declared_rpm_limit=_resolve_gemini_provider_declared_rpm_limit(),
            quota_scope=quota_scope,
        )
        fdc_ready_at_raw = pre_fdc_result.get("fdc_ready_at") or ""
        try:
            fdc_ready_at = (
                datetime.fromisoformat(fdc_ready_at_raw)
                if fdc_ready_at_raw else datetime.now(timezone.utc)
            )
        except ValueError:
            fdc_ready_at = datetime.now(timezone.utc)
        job_id = await self._repos.fdc_quota.register_real_job(
            decision_cycle_id=request.correlation_id,
            decision_context_id=request.decision_context_id,
            symbol=request.symbol or "",
            source_type=request.source_type or "held_position",
            quota_scope=quota_scope,
            fdc_ready_at=fdc_ready_at,
        )

        provider_attempt_no = 1
        coordinator_error_backoff = coordinator_error_backoff_initial_seconds

        while True:
            # ── 3. reservation 대기(FIFO, deadline 없음) ─────────────
            result = await coordinator.try_reserve(
                job_id=job_id, caller_id=caller_id, mode="real",
                manual_run_id=manual_run_id, attempt_no=provider_attempt_no,
            )
            if isinstance(result, ReservationDenied):
                await asyncio.sleep(poll_interval_seconds)
                continue
            if isinstance(result, CoordinatorError):
                await asyncio.sleep(coordinator_error_backoff)
                coordinator_error_backoff = min(
                    coordinator_error_backoff * 2,
                    coordinator_error_backoff_max_seconds,
                )
                continue
            coordinator_error_backoff = coordinator_error_backoff_initial_seconds
            grant = result

            # ── 4. fdc_only 1회 HTTP 시도 ─────────────────────────────
            fdc_only_input = serialize_agent_input(
                request=request, context=assembled_context, score=None,
                provider_runtime=self._provider_runtime, mode="fdc_only",
                event_interpretation_output=pre_fdc_result.get("event_output"),
                ai_risk_output=pre_fdc_result.get("risk_output"),
                ai_compliance_output=pre_fdc_result.get("compliance_output"),
            )
            fdc_only_payload = json.loads(fdc_only_input)
            fdc_only_payload["reservation_id"] = str(grant.reservation_id)
            fdc_only_payload["reservation_job_id"] = str(job_id)
            fdc_only_payload["reservation_attempt_no"] = grant.attempt_no
            fdc_only_payload["reservation_quota_scope"] = grant.quota_scope
            fdc_only_payload["reservation_window_count_before_grant"] = (
                grant.window_count_before_grant
            )
            fdc_only_result, fdc_only_stdout = await self._spawn_agent_subprocess(
                json.dumps(fdc_only_payload).encode("utf-8"), request=request,
            )

            if fdc_only_result is None or not fdc_only_result.get("success"):
                # subprocess timeout/crash — retryable(새 reservation).
                if provider_attempt_no < max_provider_attempts:
                    provider_attempt_no += 1
                    continue
                await self._repos.fdc_quota.mark_job_terminal(
                    job_id=job_id, status="FDC_FAILED_FINAL",
                    reason="fdc_only_subprocess_exhausted",
                )
                return self._apply_expected_value_anchor(
                    build_fallback_bundle(), assembled_context=assembled_context,
                )

            provider_final_status = fdc_only_result.get("provider_final_status", "")
            retryable_statuses = {
                "provider_rate_limit", "provider_error", "provider_timeout",
            }
            if (
                provider_final_status in retryable_statuses
                and provider_attempt_no < max_provider_attempts
            ):
                provider_attempt_no += 1
                continue

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
            await self._repos.fdc_quota.mark_job_terminal(
                job_id=job_id, status=terminal_status,
                reason=None if terminal_status == "FDC_SUCCEEDED" else provider_final_status,
            )
            return self._apply_expected_value_anchor(
                deserialize_agent_output(json.dumps(merged).encode("utf-8")),
                assembled_context=assembled_context,
            )

    def _apply_expected_value_anchor(
        self,
        bundle: AgentExecutionBundle,
        *,
        assembled_context: AIPolicyContextView,
    ) -> AgentExecutionBundle:
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
