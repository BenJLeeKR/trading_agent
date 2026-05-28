"""Runs the three v1 Provider AI Agents (EI → AR → FDC) in sequence.

Extracted from DecisionOrchestratorService (Phase 5 refactoring).
Supports both in-process execution and subprocess-based execution
with SIGKILL-guaranteed timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess  # noqa: F401 — used by subprocess-based execution
import sys
import time as time_module
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from agent_trading.domain.entities import (
    AccountEntity,
    AgentRunEntity,
    InstrumentEntity,
    TradeDecisionEntity,
)
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    ProviderAIAgent,
)
from agent_trading.services.ai_agents.recorder import AgentRunRecorder
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.common_types import (
    AgentExecutionBundle,
    AIDecisionInputs,
    AssembledContext,
    ScoreCalculator,
    ScoreResult,
    StubScoreCalculator,
    dataclass_to_dict,
    dict_to_dataclass,
    event_sort_key,
)
from agent_trading.services.subprocess_helpers import (
    build_fallback_bundle,
    deserialize_agent_output,
    serialize_agent_input,
)
from agent_trading.services.translation import (
    calculate_max_order_value,
    is_missing_agent_symbol,
    normalize_decision_type,
)

logger = logging.getLogger(__name__)

# Per-agent timeout: each LLM call is capped at 30s so that a single
# hanging agent cannot stall the entire decision cycle beyond 90s.
_PER_AGENT_TIMEOUT = 30  # seconds per agent


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
        final_decision_composer_agent: ProviderAIAgent,
        agent_run_recorder: AgentRunRecorder,
        score_calculator: ScoreCalculator | None = None,
        subprocess_timeout: int = 90,
    ) -> None:
        self._repos = repos
        self._ei_agent = event_interpretation_agent
        self._ar_agent = ai_risk_agent
        self._fdc_agent = final_decision_composer_agent
        self._recorder = agent_run_recorder
        self._score_calculator = score_calculator or StubScoreCalculator()
        self._subprocess_timeout = subprocess_timeout

    # ------------------------------------------------------------------
    # AI Agent execution — in-process
    # ------------------------------------------------------------------

    async def run_agents(
        self,
        request: AgentExecutionRequest,
        assembled_context: AssembledContext,
    ) -> AgentExecutionBundle:
        """Execute the three v1 Provider AI Agents sequentially.

        Execution order
        ---------------
        1. Event Interpretation Agent
        2. AI Risk Agent
        3. Final Decision Composer

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
        market = request.market

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

        # --- Build a new request with both EI and AR output for FDC ---
        # AgentExecutionRequest is frozen, so we must create a new instance.
        # When AR fails, risk_output is an empty AIRiskOutput(), so FDC always
        # receives a structured value (never None).
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

        # --- 3. Final Decision Composer Agent ---
        composer_output: FinalDecisionComposerOutput
        _t2 = time_module.monotonic()
        try:
            composer_output = await asyncio.wait_for(
                self._fdc_agent.run(request_with_ei_and_ar),
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
            "event=%s risk=%s composer=%s",
            decision_context_id,
            event_output.agent_name,
            risk_output.risk_opinion,
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
            # EI-derived
            event_bias=event_output.aggregate_view.overall_bias,
            event_conflict=event_output.aggregate_view.event_conflict,
            event_reason_codes=event_output.aggregate_view.top_reason_codes,
            # Metadata
            source_agent_names=(
                event_output.agent_name,
                risk_output.agent_name,
                composer_output.agent_name,
            ),
            schema_versions=(
                ("event_interpretation", event_output.schema_version),
                ("ai_risk", risk_output.schema_version),
                ("final_decision_composer", composer_output.schema_version),
            ),
        )

        return AgentExecutionBundle(
            ai_inputs=ai_inputs,
            event_output=event_output,
            risk_output=risk_output,
            composer_output=composer_output,
        )

    # ------------------------------------------------------------------
    # AI Agent execution — subprocess isolation
    # ------------------------------------------------------------------

    async def run_agents_in_subprocess(
        self,
        request: AgentExecutionRequest,
        assembled_context: AssembledContext,
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
        """

        # ── 1. Serialize input ────────────────────────────────────────
        input_bytes = serialize_agent_input(
            request=request,
            context=assembled_context,
            score=None,
        ).encode("utf-8")

        # ── 2. Combined timeout ─────────────────────────────────────────
        # The outer timeout covers 3 sequential agent API calls (EI, AR,
        # FDC) plus subprocess startup/teardown overhead.  It is NOT
        # configurable per-agent — each agent uses the httpx client timeout
        # (provider_timeout_seconds) internally.  The outer timeout should
        # be generous enough to allow 3× provider_timeout with headroom.
        _SUBPROCESS_TIMEOUT = self._subprocess_timeout

        # ── 3. Create subprocess ──────────────────────────────────────
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "scripts.run_agent_subprocess",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # ── 4. Communicate with timeout ───────────────────────────────
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input_bytes),
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except asyncio.TimeoutError:
            # ── Capture stderr before killing ─────────────────────────────
            # This is critical for diagnosing subprocess hangs. On timeout,
            # communicate() was cancelled but the pipe may still have data.
            stderr_hint = ""
            try:
                stderr_data = await asyncio.wait_for(
                    proc.stderr.read(), timeout=2.0
                )
                if stderr_data:
                    stderr_hint = stderr_data.decode("utf-8", errors="replace")[:2000]
            except (asyncio.TimeoutError, ProcessLookupError, Exception):
                pass

            # SIGTERM first (10s grace period)
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=10.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                # SIGKILL — forcibly terminate C-level blocking
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
            return build_fallback_bundle()

        # ── 5. Log subprocess stderr (diagnostics) ────────────────────
        if stderr and stderr.strip():
            logger.info(
                "Agent subprocess stderr (decision_context_id=%s): %s",
                request.decision_context_id,
                stderr.decode("utf-8", errors="replace")[:2000],
            )

        # ── 6. Parse output ───────────────────────────────────────────
        try:
            result = json.loads(stdout)
            if not result.get("success"):
                logger.warning(
                    "Agent subprocess reported failure: %s — "
                    "using fallback output. decision_context_id=%s",
                    result.get("error", "unknown error"),
                    request.decision_context_id,
                )
                return build_fallback_bundle()

            return deserialize_agent_output(stdout)

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.error(
                "Failed to parse agent subprocess output: %s — "
                "using fallback output. decision_context_id=%s "
                "stdout_preview=%s",
                exc,
                request.decision_context_id,
                stdout[:500] if stdout else "(empty)",
            )
            return build_fallback_bundle()
