from __future__ import annotations

import asyncio
import logging
import os
import time as time_module
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    AccountEntity,
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    ExternalEventEntity,
    GuardrailEvaluationEntity,
    InstrumentEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
    SignalFeatureSnapshotEntity,
    SymbolTradeStateEntity,
    TradeDecisionEntity,
)
from agent_trading.domain.enums import DecisionType, EntryStyle, OrderSide, OrderStatus, OrderType
from agent_trading.domain.models import Quote, SubmitOrderRequest
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.order_sync_service import OrderSyncService
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import AccountLookup
from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    ProviderAIAgent,
)
from agent_trading.services.ai_agents.event_interpretation import (
    StubEventInterpretationAgent,
)
from agent_trading.services.ai_agents.ai_risk import StubAIRiskAgent
from agent_trading.services.ai_agents.final_decision_composer import (
    StubFinalDecisionComposerAgent,
)
from agent_trading.services.ai_agents.korean_normalizer import (
    validate_or_normalize_korean,
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
    AIPolicyContextView,
    AssembledContext,
    OrderIntent,
    PhaseTraceEntry,
    ScoreCalculator,
    ScoreResult,
    StubScoreCalculator,
    SubmitResult,
    dataclass_to_dict,
    dict_to_dataclass,
    event_sort_key,
)
from agent_trading.services.decision_factory import (
    build_trade_decision_entity,
    DecisionContextService,
)
from agent_trading.services.deterministic_trigger_engine import (
    assess_deterministic_triggers,
)
from agent_trading.services.execution_service import (
    ExecutionService,
)
from agent_trading.services.compliance_validator import (
    ComplianceValidationInput,
    evaluate_compliance_rules,
)
from agent_trading.services.instrument_profile import (
    derive_primary_index_membership,
    normalize_index_memberships,
)
from agent_trading.services.holding_profile_policy import (
    derive_holding_profile_policy,
    parse_datetime_or_none,
    serialize_holding_profile_policy,
)
from agent_trading.services.expected_value_gate import (
    evaluate_expected_value_gate,
)
from agent_trading.services.market_regime import classify_market_regime
from agent_trading.services.portfolio_allocation import assess_portfolio_allocation
from agent_trading.services.source_policy import evaluate_action_envelope
from agent_trading.services.sizing_engine import (
    SizingInputs,
    calculate_sizing,
)
from agent_trading.services.strategy_selection import select_strategy
from agent_trading.services.subprocess_helpers import (
    build_fallback_bundle,
    deserialize_agent_output,
    serialize_agent_input,
)
from agent_trading.services.translation import (
    build_submit_order_request_from_decision,
    calculate_max_order_value,
    decimal_or_none,
    is_missing_agent_symbol,
    normalize_decision_type,
    resolve_decision_type,
    resolve_entry_style,
    resolve_order_side,
)
from agent_trading.services.decision_agent_runner import DecisionAgentRunner
from agent_trading.services.validators import ValidationContext, ValidationResult

logger = logging.getLogger(__name__)

_PRE_AI_SHORT_CIRCUIT_SOURCE_TYPES = frozenset({"core"})
_PRE_AI_ELIGIBILITY_BLOCK_REASONS = frozenset(
    {
        "eligibility_low_average_volume",
        "eligibility_low_turnover",
        "eligibility_allocation_blocked",
        "eligibility_risk_off_block",
        "eligibility_core_risk_off_guard_blocked",
        "eligibility_core_risk_off_ranking_blocked",
        "eligibility_core_risk_off_signal_blocked",
        "eligibility_core_risk_off_activity_blocked",
        "eligibility_core_risk_off_strategy_blocked",
        "eligibility_participation_rate_blocked",
    }
)
_AI_OVERRIDE_EXECUTION_INFEASIBLE_REASONS = frozenset(
    {
        "eligibility_low_average_volume",
        "eligibility_low_turnover",
        "eligibility_participation_rate_blocked",
    }
)

# Per-agent timeout: each LLM call is capped at 30s so that a single
# hanging agent cannot stall the entire decision cycle beyond 90s.
# Reduced from 35s to 30s in Phase 5.7 to align with deepseek-chat
# P99 latency (~15.9s) with 1.9x safety margin.
_PER_AGENT_TIMEOUT = 30  # seconds per agent

# Phase 4: subprocess isolation for agent calls.
# When True, _run_agents() delegates to _run_agents_in_subprocess()
# which runs all 3 agents in a separate subprocess with SIGKILL-guaranteed
# timeout.  Set to False in tests for compatibility.
# Can be overridden via the AGENT_SUBPROCESS_ISOLATION env var.
_USE_SUBPROCESS_ISOLATION: bool = (
    os.environ.get("AGENT_SUBPROCESS_ISOLATION", "1") == "1"
)


@dataclass(slots=True, frozen=True)
class DeterministicDerivationBundle:
    """assemble()의 deterministic 파생 계산 결과 묶음."""

    source_type: str
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None = None
    market_regime: Any | None = None
    strategy_selection: Any | None = None
    portfolio_allocation: Any | None = None
    deterministic_trigger: Any | None = None


class DecisionOrchestratorService:
    """Deterministic stub for order intent assembly.

    Scope (Milestone 6)
    -------------------
    * Assemble P1 fields (``decision_context_id``, ``order_intent_id``)
      into the ``SubmitOrderRequest`` before it reaches the
      ``OrderManager``.
    * No LLM calls, no AI judgment, no portfolio calculations.

    Milestone 7 additions
    ---------------------
    * Active context resolution from ``DecisionContextRepository``.
    * ID generation for ``decision_id`` and ``correlation_id`` when not
      provided.
    * Minimal assembly of ``SubmitOrderRequest`` from context + intent.

    Priority 3 additions
    --------------------
    * ``AssembledContext`` dataclass — aggregates decision context,
      config version, recent external events, and score.
    * ``OrderIntent`` extended with ``context``, ``config_version_id``,
      ``reason_codes``.
    * Config version lookup via ``decision_context.config_version_id``.
    * External event query stub (``list_by_symbol``).
    * ``ScoreCalculator`` protocol + ``StubScoreCalculator``.
    * No actual LLM calls, no event-driven judgment.

    Priority 4 additions
    --------------------
    * Three v1 Provider AI Agent stubs (Event Interpretation, AI Risk,
      Final Decision Composer) wired into the ``assemble()`` flow.
    * ``AgentRunRecorder`` — in-memory stub that records each agent run.
    * ``_run_agents()`` — private method that executes the three agents
      sequentially and records their outputs.
    * No actual Provider API calls — all agents return default structured
      outputs (safe fallback on exception).

    Priority A additions (AI Decision Backend Contract)
    ---------------------------------------------------
    * ``AIDecisionInputs`` dataclass — normalised aggregate of EI/AR/FDC
      agent outputs, carried on ``OrderIntent.ai_backend_inputs``.
    * ``_run_agents()`` now returns ``AIDecisionInputs`` (not ``None``).
    * ``assemble()`` passes the normalised contract to ``OrderIntent``.
    * ``AgentRunRecorder`` continues to record every run for audit/replay.
    * Raw agent outputs are **not** carried on ``OrderIntent`` — only
      normalised fields via ``AIDecisionInputs``.
    """

    def __init__(
        self,
        repos: RepositoryContainer,
        *,
        stale_threshold_seconds: int = 900,
        score_calculator: ScoreCalculator | None = None,
        event_interpretation_agent: ProviderAIAgent | None = None,
        ai_risk_agent: ProviderAIAgent | None = None,
        final_decision_agent: ProviderAIAgent | None = None,
        agent_recorder: AgentRunRecorder | None = None,
        # --- Phase 5.5: post-submit sync ---
        sync_service: OrderSyncService | None = None,
        snapshot_refresh_cb: Callable[[UUID], Awaitable[None]] | None = None,
        # --- Phase 4: subprocess isolation ---
        use_subprocess_isolation: bool | None = None,
        # --- Provider configuration for subprocess agent creation ---
        llm_provider: str = "",
        provider_api_key: str = "",
        provider_base_url: str = "",
        provider_model_id: str = "",
        provider_timeout_seconds: int = 60,
    ) -> None:
        self._repos = repos
        self._decision_context_service = DecisionContextService(repos)
        self._stale_threshold_seconds = stale_threshold_seconds
        self._score_calculator = score_calculator or StubScoreCalculator()
        self._event_interpretation_agent = (
            event_interpretation_agent or StubEventInterpretationAgent()
        )
        self._ai_risk_agent = ai_risk_agent or StubAIRiskAgent()
        self._final_decision_agent = final_decision_agent or StubFinalDecisionComposerAgent()
        self._agent_recorder = agent_recorder or AgentRunRecorder(repo=self._repos.agent_runs)
        # --- Phase 5.5 ---
        self._sync_service = sync_service
        self._snapshot_refresh_cb = snapshot_refresh_cb
        # --- Phase 4: subprocess isolation ---
        # Default to module-level constant; tests can override via constructor.
        self._use_subprocess_isolation = (
            _USE_SUBPROCESS_ISOLATION if use_subprocess_isolation is None
            else use_subprocess_isolation
        )
        # --- Provider configuration for subprocess ---
        self._llm_provider = llm_provider
        self._provider_api_key = provider_api_key
        self._provider_base_url = provider_base_url
        self._provider_model_id = provider_model_id
        self._provider_timeout_seconds = provider_timeout_seconds
        # --- Execution Service (execution pipeline state: sell guard, quote CB, fresh check) ---
        self._execution_service = ExecutionService(
            repos=repos,
            stale_threshold_seconds=stale_threshold_seconds,
            sync_service=sync_service,
            snapshot_refresh_cb=snapshot_refresh_cb,
        )

        # Initialize DecisionAgentRunner (Phase 5 refactoring)
        self._agent_runner = DecisionAgentRunner(
            repos=self._repos,
            event_interpretation_agent=self._event_interpretation_agent,
            ai_risk_agent=self._ai_risk_agent,
            final_decision_composer_agent=self._final_decision_agent,
            agent_run_recorder=self._agent_recorder,
            score_calculator=self._score_calculator,
            subprocess_timeout=90,
            llm_provider=self._llm_provider,
            provider_api_key=self._provider_api_key,
            provider_base_url=self._provider_base_url,
            provider_model_id=self._provider_model_id,
            provider_timeout_seconds=self._provider_timeout_seconds,
        )

    def _check_held_position_sell_override(
        self,
        source_type: str,
        ar_output: AIRiskOutput | None,
        fdc_output: FinalDecisionComposerOutput | None,
    ) -> tuple[str, str, str] | None:
        """보유 포지션 + 강한 리스크 신호 → REDUCE/EXIT sell override 판단.

        Args:
            source_type: 출처 타입 (``"held_position"`` 등)
            ar_output: AI Risk agent 출력
            fdc_output: FDC agent 출력

        Returns:
            ``(decision_type, side, rationale)`` 튜플 (override 필요 시),
            ``None`` (override 불필요 시)
        """
        # held position이 아니면 override 절대 안 함
        if source_type != "held_position":
            return None

        if ar_output is None or fdc_output is None:
            return None

        # FDC가 이미 REDUCE/EXIT로 판단했으면 override 불필요
        if fdc_output.decision_type in ("REDUCE", "EXIT"):
            return None

        # AI risk가 강한 부정 신호인지 확인
        risk_override = False
        override_reason = ""

        if ar_output.risk_opinion in ("reject", "reduce"):
            risk_override = True
            override_reason = f"리스크 경고({ar_output.risk_opinion})"
        elif ar_output.risk_opinion == "review" and ar_output.risk_score >= 0.8:
            risk_override = True
            override_reason = f"리스크 검토 필요(score:{ar_output.risk_score:.1f})"
        elif ar_output.risk_score >= 0.8:
            risk_override = True
            override_reason = f"리스크 점수高危({ar_output.risk_score:.1f})"

        if not risk_override:
            return None

        # FDC가 HOLD인데 risk 신호가 강하면 → REDUCE로 전환
        # FDC가 APPROVE/BUY여도 held position + risk 신호면 → REDUCE
        rationale = (
            f"[held_position_override] 보유 포지션 {override_reason}. "
            f"FDC={fdc_output.decision_type}→REDUCE 전환. "
            f"AR opinion={ar_output.risk_opinion} score={ar_output.risk_score:.2f}"
        )

        # 과집중(risk_flags에 concentration 관련)이면 EXIT 고려
        risk_flags_lower = tuple(f.lower() for f in ar_output.risk_flags)
        if any("concent" in f or "expos" in f or "over" in f for f in risk_flags_lower):
            return ("EXIT", "SELL", rationale)

        return ("REDUCE", "SELL", rationale)

    def _check_watch_candidate_upgrade_guard(
        self,
        *,
        source_type: str,
        deterministic_trigger: Any | None,
        fdc_output: FinalDecisionComposerOutput | None,
        position_snapshot: PositionSnapshotEntity | None = None,
    ) -> tuple[str, str] | None:
        """결정적 WATCH 후보가 AI 단계에서 진입/매도로 승격되는 것을 제한한다."""
        if deterministic_trigger is None or fdc_output is None:
            return None

        guarded_source_types = {"core", "held_position"}
        if source_type not in guarded_source_types:
            return None

        if source_type == "core":
            has_position = (
                position_snapshot is not None
                and position_snapshot.quantity is not None
                and position_snapshot.quantity > 0
            )
            if has_position:
                return None

        primary_candidate = (
            getattr(deterministic_trigger, "primary_candidate", "") or ""
        ).strip().upper()
        if primary_candidate != "WATCH":
            return None

        decision_type = (fdc_output.decision_type or "").strip().upper()
        if decision_type not in {"APPROVE", "BUY", "SELL", "EXIT", "REDUCE"}:
            return None

        if source_type == "held_position":
            decision_side = (fdc_output.side or "").strip().upper()
            if decision_type in {"REDUCE", "EXIT"} and decision_side == "SELL":
                return None

        rationale = (
            f"[watch_candidate_guard] source_type={source_type} "
            f"deterministic_trigger=WATCH 이므로 FDC={decision_type}를 WATCH로 제한"
        )
        return ("WATCH", rationale)

    def _check_buy_eligibility_upgrade_guard(
        self,
        *,
        source_type: str,
        deterministic_trigger: Any | None,
        fdc_output: FinalDecisionComposerOutput | None,
        position_snapshot: PositionSnapshotEntity | None = None,
    ) -> tuple[str, str] | None:
        """BUY 적격성 실패 상태에서 AI의 진입 승격을 제한한다."""
        if deterministic_trigger is None or fdc_output is None:
            return None

        if source_type != "core":
            return None

        has_position = (
            position_snapshot is not None
            and position_snapshot.quantity is not None
            and position_snapshot.quantity > 0
        )
        if has_position:
            return None

        if bool(getattr(deterministic_trigger, "eligibility_passed", False)):
            return None

        decision_type = (fdc_output.decision_type or "").strip().upper()
        if decision_type not in {"APPROVE", "BUY"}:
            return None

        eligibility_reasons = tuple(
            getattr(deterministic_trigger, "eligibility_reasons", ()) or ()
        )
        has_execution_feasibility_block = any(
            reason in {
                "eligibility_low_average_volume",
                "eligibility_low_turnover",
                "eligibility_participation_rate_blocked",
            }
            for reason in eligibility_reasons
        )
        if not has_execution_feasibility_block:
            return None

        downgrade_decision = (
            "WATCH"
            if (getattr(deterministic_trigger, "watch_candidate", False))
            else "HOLD"
        )
        rationale = (
            f"[buy_eligibility_guard] source_type={source_type} "
            f"eligibility_reasons={','.join(eligibility_reasons)} "
            f"이므로 FDC={decision_type} 진입 승격을 {downgrade_decision}로 제한"
        )
        return (downgrade_decision, rationale)

    def _check_source_policy_upgrade_guard(
        self,
        *,
        source_type: str,
        deterministic_trigger: Any | None,
        fdc_output: FinalDecisionComposerOutput | None,
        position_snapshot: PositionSnapshotEntity | None = None,
    ) -> tuple[str, str, tuple[str, ...]] | None:
        """source_type 정책상 금지된 신규 BUY 승격을 제한한다."""
        if fdc_output is None:
            return None

        has_position = (
            position_snapshot is not None
            and position_snapshot.quantity is not None
            and position_snapshot.quantity > 0
        )
        envelope = evaluate_action_envelope(
            source_type=source_type,
            has_position=has_position,
        )
        if envelope.allow_new_buy:
            return None

        decision_type = (fdc_output.decision_type or "").strip().upper()
        if decision_type not in {"APPROVE", "BUY"}:
            return None

        downgrade_decision = "HOLD"
        if (
            deterministic_trigger is not None
            and bool(getattr(deterministic_trigger, "watch_candidate", False))
        ):
            downgrade_decision = "WATCH"

        rationale = (
            f"[source_policy_guard] source_type={source_type} "
            f"reason_codes={','.join(envelope.reason_codes)} "
            f"이므로 FDC={decision_type} 진입 승격을 {downgrade_decision}로 제한"
        )
        return (
            downgrade_decision,
            rationale,
            ("source_policy_guard",) + envelope.reason_codes,
        )

    async def _check_ai_buy_override_gate(
        self,
        *,
        source_type: str,
        deterministic_trigger: Any | None,
        fdc_output: FinalDecisionComposerOutput | None,
        ai_inputs: AIDecisionInputs,
        position_snapshot: PositionSnapshotEntity | None,
        decision_context: DecisionContextEntity | None,
        instrument: InstrumentEntity | None,
    ) -> tuple[str, str, tuple[str, ...]] | None:
        """BUY/APPROVE override는 eligibility + EV + state 통과 시에만 허용한다."""
        if fdc_output is None or deterministic_trigger is None:
            return None

        decision_type = (fdc_output.decision_type or "").strip().upper()
        if decision_type not in {"APPROVE", "BUY"}:
            return None

        has_position = (
            position_snapshot is not None
            and position_snapshot.quantity is not None
            and position_snapshot.quantity > 0
        )
        if has_position:
            return None

        if bool(getattr(deterministic_trigger, "buy_candidate", False)):
            return None

        downgrade_decision = (
            "WATCH"
            if bool(getattr(deterministic_trigger, "watch_candidate", False))
            else "HOLD"
        )
        normalized_source_type = (source_type or "core").strip().lower()
        envelope = evaluate_action_envelope(
            source_type=normalized_source_type,
            has_position=False,
        )
        if not envelope.allow_new_buy:
            rationale = (
                f"[ai_override_gate] source_type={normalized_source_type} "
                f"action_envelope blocked FDC={decision_type} -> {downgrade_decision}"
            )
            return (
                downgrade_decision,
                rationale,
                ("ai_override_gate", "ai_override_source_policy_blocked"),
            )

        eligibility_passed = bool(
            getattr(deterministic_trigger, "eligibility_passed", False)
        )
        eligibility_reasons = tuple(
            getattr(deterministic_trigger, "eligibility_reasons", ()) or ()
        )
        if (
            not eligibility_passed
            and decision_context is not None
            and decision_context.signal_feature_snapshot_id is None
            and eligibility_reasons
            and set(eligibility_reasons).issubset(
                {
                    "eligibility_source_type_allowed",
                    "eligibility_low_feature_coverage",
                }
            )
        ):
            return None
        if not eligibility_passed:
            rationale = (
                f"[ai_override_gate] source_type={normalized_source_type} "
                f"eligibility_passed=false reasons={','.join(eligibility_reasons)} "
                f"FDC={decision_type} -> {downgrade_decision}"
            )
            return (
                downgrade_decision,
                rationale,
                ("ai_override_gate", "ai_override_eligibility_blocked"),
            )
        if any(
            reason in _AI_OVERRIDE_EXECUTION_INFEASIBLE_REASONS
            for reason in eligibility_reasons
        ):
            rationale = (
                f"[ai_override_gate] source_type={normalized_source_type} "
                f"execution_infeasible reasons={','.join(eligibility_reasons)} "
                f"FDC={decision_type} -> {downgrade_decision}"
            )
            return (
                downgrade_decision,
                rationale,
                ("ai_override_gate", "ai_override_execution_infeasible"),
            )

        if not ai_inputs.expected_value_gate_passed:
            rationale = (
                f"[ai_override_gate] source_type={normalized_source_type} "
                f"expected_value_gate_passed=false FDC={decision_type} -> {downgrade_decision}"
            )
            return (
                downgrade_decision,
                rationale,
                ("ai_override_gate", "ai_override_expected_value_blocked"),
            )

        if (
            decision_context is None
            or instrument is None
        ):
            return None

        symbol_state = await self._repos.symbol_trade_states.get_by_account_and_instrument(
            decision_context.account_id,
            instrument.instrument_id,
        )
        if symbol_state is None:
            return None

        now_utc = datetime.now(timezone.utc)
        if symbol_state.state in {"entry_pending", "reduce_pending", "exit_pending"}:
            rationale = (
                f"[ai_override_gate] symbol_state={symbol_state.state} "
                f"pending conflict FDC={decision_type} -> {downgrade_decision}"
            )
            return (
                downgrade_decision,
                rationale,
                ("ai_override_gate", "ai_override_state_pending_conflict"),
            )
        if (
            symbol_state.reentry_cooldown_until is not None
            and symbol_state.reentry_cooldown_until > now_utc
        ):
            rationale = (
                f"[ai_override_gate] reentry_cooldown_until="
                f"{symbol_state.reentry_cooldown_until.isoformat()} "
                f"FDC={decision_type} -> {downgrade_decision}"
            )
            return (
                downgrade_decision,
                rationale,
                ("ai_override_gate", "ai_override_reverse_cooldown_blocked"),
            )
        return None

    async def _ensure_or_create_decision_context(
        self,
        request: SubmitOrderRequest,
        existing_context_id: UUID | None,
    ) -> UUID | None:
        """Thin wrapper — delegates to DecisionContextService.ensure_or_create()."""
        return await self._decision_context_service.ensure_or_create(
            request=request,
            existing_context_id=existing_context_id,
        )

    async def _ensure_trade_decision(
        self,
        *,
        decision_context_id: UUID | None,
        request: SubmitOrderRequest,
        assembled_context: AssembledContext,
        agent_bundle: AgentExecutionBundle,
        instrument: InstrumentEntity | None = None,
        fdc_run_id: UUID | None = None,
    ) -> TradeDecisionEntity | None:
        """Thin wrapper — delegates to build_trade_decision_entity() + repository add."""
        resolved_instrument = instrument
        if resolved_instrument is None:
            try:
                resolved_instrument = await self._repos.instruments.get_by_symbol(
                    symbol=request.symbol,
                    market_code=request.market,
                )
                if resolved_instrument is None:
                    resolved_instrument = await self._repos.instruments.get_by_symbol_any_market(
                        request.symbol
                    )
            except Exception:
                resolved_instrument = None
        td_entity = build_trade_decision_entity(
            decision_context_id=decision_context_id,
            request=request,
            assembled_context=assembled_context,
            agent_bundle=agent_bundle,
            instrument_id=(
                resolved_instrument.instrument_id
                if resolved_instrument is not None
                else None
            ),
            fdc_run_id=fdc_run_id,
        )
        if td_entity is not None:
            td_entity = await self._repos.trade_decisions.add(td_entity)
            await self._persist_symbol_trade_state_from_decision(
                trade_decision=td_entity,
                assembled_context=assembled_context,
                instrument=resolved_instrument,
                composer_output=agent_bundle.composer_output,
            )
        return td_entity

    async def _persist_symbol_trade_state_from_decision(
        self,
        *,
        trade_decision: TradeDecisionEntity,
        assembled_context: AssembledContext,
        instrument: InstrumentEntity | None,
        composer_output: FinalDecisionComposerOutput | None,
    ) -> None:
        decision_context = assembled_context.decision_context
        if decision_context is None or instrument is None:
            return

        now = trade_decision.created_at
        current_state = await self._repos.symbol_trade_states.get_by_account_and_instrument(
            decision_context.account_id,
            instrument.instrument_id,
        )
        policy_payload = trade_decision.decision_json.get("holding_profile_policy")
        serialized_policy_payload: dict[str, object] | None = None
        if isinstance(policy_payload, dict):
            serialized_policy_payload = dict(policy_payload)
            holding_profile = policy_payload.get("holding_profile")
            minimum_hold_until = parse_datetime_or_none(
                policy_payload.get("minimum_hold_until")
            )
            reentry_cooldown_until = parse_datetime_or_none(
                policy_payload.get("reentry_cooldown_until")
            )
            sell_cooldown_until = parse_datetime_or_none(
                policy_payload.get("sell_cooldown_until")
            )
            thesis_state_hash = policy_payload.get("thesis_state_hash")
            policy_metadata = (
                dict(policy_payload.get("metadata"))
                if isinstance(policy_payload.get("metadata"), dict)
                else {}
            )
        else:
            fallback_policy = derive_holding_profile_policy(
                source_type=assembled_context.source_type,
                decision_type=(
                    composer_output.decision_type
                    if composer_output is not None
                    else trade_decision.decision_type.value
                ),
                side=(
                    composer_output.side
                    if composer_output is not None and composer_output.side
                    else trade_decision.side
                ),
                time_horizon=(
                    composer_output.time_horizon
                    if composer_output is not None
                    else None
                ),
                quantity=trade_decision.quantity,
                max_order_value=trade_decision.max_order_value,
                signal_feature_snapshot_id=(
                    str(assembled_context.signal_feature_snapshot.signal_feature_snapshot_id)
                    if assembled_context.signal_feature_snapshot is not None
                    else (
                        str(decision_context.signal_feature_snapshot_id)
                        if decision_context.signal_feature_snapshot_id is not None
                        else None
                    )
                ),
                reason_codes=trade_decision.reason_codes,
                now_utc=now,
            )
            serialized_policy = serialize_holding_profile_policy(fallback_policy)
            serialized_policy_payload = dict(serialized_policy)
            holding_profile = serialized_policy.get("holding_profile")
            minimum_hold_until = parse_datetime_or_none(
                serialized_policy.get("minimum_hold_until")
            )
            reentry_cooldown_until = parse_datetime_or_none(
                serialized_policy.get("reentry_cooldown_until")
            )
            sell_cooldown_until = parse_datetime_or_none(
                serialized_policy.get("sell_cooldown_until")
            )
            thesis_state_hash = serialized_policy.get("thesis_state_hash")
            policy_metadata = (
                dict(serialized_policy.get("metadata"))
                if isinstance(serialized_policy.get("metadata"), dict)
                else {}
            )

        state_value = current_state.state if current_state is not None else "flat"
        last_entry_at = current_state.last_entry_at if current_state is not None else None
        last_reduce_at = current_state.last_reduce_at if current_state is not None else None
        last_exit_at = current_state.last_exit_at if current_state is not None else None
        if trade_decision.side == OrderSide.BUY and trade_decision.decision_type in {
            DecisionType.APPROVE,
            DecisionType.BUY,
        }:
            state_value = "entry_pending"
            last_entry_at = now
        elif trade_decision.side == OrderSide.SELL and trade_decision.decision_type == DecisionType.REDUCE:
            state_value = "reduce_pending"
            last_reduce_at = now
        elif trade_decision.side == OrderSide.SELL and trade_decision.decision_type in {
            DecisionType.SELL,
            DecisionType.EXIT,
        }:
            state_value = "exit_pending"
            last_exit_at = now

        merged_metadata = dict(current_state.metadata_json) if current_state is not None else {}
        merged_metadata["holding_profile_policy"] = (
            serialized_policy_payload
            if serialized_policy_payload is not None
            else policy_metadata
        )
        merged_metadata["last_trade_decision_id"] = str(trade_decision.trade_decision_id)

        await self._repos.symbol_trade_states.upsert(
            SymbolTradeStateEntity(
                symbol_trade_state_id=(
                    current_state.symbol_trade_state_id
                    if current_state is not None
                    else uuid4()
                ),
                account_id=decision_context.account_id,
                instrument_id=instrument.instrument_id,
                symbol=trade_decision.symbol,
                market=trade_decision.market,
                state=state_value,
                holding_profile=(
                    str(holding_profile)
                    if holding_profile is not None
                    else (
                        current_state.holding_profile
                        if current_state is not None
                        else None
                    )
                ),
                position_quantity=(
                    assembled_context.position_snapshot.quantity
                    if assembled_context.position_snapshot is not None
                    else (
                        current_state.position_quantity
                        if current_state is not None
                        else Decimal("0")
                    )
                ),
                last_entry_order_request_id=(
                    current_state.last_entry_order_request_id
                    if current_state is not None
                    else None
                ),
                last_exit_order_request_id=(
                    current_state.last_exit_order_request_id
                    if current_state is not None
                    else None
                ),
                last_entry_source_type=trade_decision.source_type,
                last_entry_at=last_entry_at,
                last_reduce_at=last_reduce_at,
                last_exit_at=last_exit_at,
                minimum_hold_until=minimum_hold_until,
                reentry_cooldown_until=reentry_cooldown_until,
                sell_cooldown_until=sell_cooldown_until,
                last_signal_feature_snapshot_id=decision_context.signal_feature_snapshot_id,
                last_decision_context_id=trade_decision.decision_context_id,
                last_reason_codes=list(trade_decision.reason_codes or ()),
                thesis_state_hash=(
                    str(thesis_state_hash)
                    if thesis_state_hash is not None
                    else (
                        current_state.thesis_state_hash
                        if current_state is not None
                        else None
                    )
                ),
                metadata_json=merged_metadata,
                created_at=(
                    current_state.created_at
                    if current_state is not None
                    else now
                ),
                updated_at=now,
            )
        )

    # ------------------------------------------------------------------
    # Sizing input builder — public delegation to ExecutionService boundary
    # ------------------------------------------------------------------

    def build_sizing_inputs(
        self,
        intent: OrderIntent,
        reference_price: Decimal | None = None,
    ) -> SizingInputs:
        """Build ``SizingInputs`` from an ``OrderIntent``.

        Public delegation method — forwards to
        ``ExecutionService._build_sizing_inputs()`` (a ``@staticmethod``)
        to avoid duplicating the sizing-input mapping logic.  External
        callers (scripts, tests) must use this method instead of reaching
        into execution-boundary internals directly.
        """
        return ExecutionService._build_sizing_inputs(
            intent=intent,
            reference_price=reference_price,
        )

    def _extract_source_type(
        self,
        request: SubmitOrderRequest,
    ) -> str:
        """요청 metadata에서 source_type을 안전하게 추출한다."""
        source_type = "core"
        try:
            if request.metadata and isinstance(request.metadata, dict):
                source_type = request.metadata.get("source_type", "core") or "core"
        except Exception:
            pass
        return source_type

    async def _derive_deterministic_context_components(
        self,
        *,
        request: SubmitOrderRequest,
        config_version: ConfigVersionEntity | None,
        instrument: InstrumentEntity | None,
        position_snapshot: PositionSnapshotEntity | None,
        cash_balance_snapshot: CashBalanceSnapshotEntity | None,
        risk_limit_snapshot: RiskLimitSnapshotEntity | None,
    ) -> DeterministicDerivationBundle:
        """assemble()의 deterministic 파생 계산 단계를 별도 helper로 분리한다."""
        signal_feature_snapshot: SignalFeatureSnapshotEntity | None = None
        instrument_for_signal = instrument
        if instrument_for_signal is None:
            try:
                instrument_for_signal = await self._repos.instruments.get_by_symbol(
                    symbol=request.symbol,
                    market_code=request.market,
                )
            except Exception:
                instrument_for_signal = None
        if instrument_for_signal is not None:
            try:
                signal_feature_snapshot = (
                    await self._repos.signal_feature_snapshots.get_latest_by_instrument(
                        instrument_for_signal.instrument_id,
                    )
                )
            except Exception:
                pass

        market_regime = classify_market_regime(signal_feature_snapshot)
        source_type = self._extract_source_type(request)
        strategy_selection = select_strategy(
            market_regime=market_regime,
            source_type=source_type,
        )
        portfolio_allocation = assess_portfolio_allocation(
            symbol=request.symbol,
            source_type=source_type,
            config_version=config_version,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
            market_regime=market_regime,
            strategy_selection=strategy_selection,
        )
        deterministic_trigger = assess_deterministic_triggers(
            source_type=source_type,
            signal_feature_snapshot=signal_feature_snapshot,
            market_regime=market_regime,
            strategy_selection=strategy_selection,
            portfolio_allocation=portfolio_allocation,
            position_snapshot=position_snapshot,
        )
        return DeterministicDerivationBundle(
            source_type=source_type,
            signal_feature_snapshot=signal_feature_snapshot,
            market_regime=market_regime,
            strategy_selection=strategy_selection,
            portfolio_allocation=portfolio_allocation,
            deterministic_trigger=deterministic_trigger,
        )

    async def _attach_signal_feature_snapshot_to_context(
        self,
        decision_context: DecisionContextEntity | None,
        signal_feature_snapshot: SignalFeatureSnapshotEntity | None,
    ) -> DecisionContextEntity | None:
        """decision_context에 실제 사용한 signal feature snapshot 식별자를 고정한다."""
        if (
            decision_context is None
            or signal_feature_snapshot is None
            or decision_context.signal_feature_snapshot_id
            == signal_feature_snapshot.signal_feature_snapshot_id
        ):
            return decision_context
        try:
            updated = await self._repos.decision_contexts.attach_signal_feature_snapshot(
                decision_context.decision_context_id,
                signal_feature_snapshot.signal_feature_snapshot_id,
            )
            return updated or decision_context
        except Exception:
            return decision_context

    async def _select_usable_cash_snapshot(
        self,
        account_id: UUID,
    ) -> CashBalanceSnapshotEntity | None:
        try:
            snapshots = await self._repos.cash_balance_snapshots.list_by_account(
                account_id,
            )
        except Exception:
            return None

        latest_any = snapshots[0] if snapshots else None
        for snapshot in snapshots:
            if snapshot.fetch_status == "success":
                return snapshot
        return latest_any

    async def _attach_cash_balance_snapshot_to_context(
        self,
        decision_context: DecisionContextEntity | None,
        cash_balance_snapshot: CashBalanceSnapshotEntity | None,
    ) -> DecisionContextEntity | None:
        if (
            decision_context is None
            or cash_balance_snapshot is None
            or decision_context.cash_balance_snapshot_id
            == cash_balance_snapshot.cash_balance_snapshot_id
        ):
            return decision_context
        try:
            updated = await self._repos.decision_contexts.attach_cash_balance_snapshot(
                decision_context.decision_context_id,
                cash_balance_snapshot.cash_balance_snapshot_id,
            )
            return updated or decision_context
        except Exception:
            return decision_context

    def _build_ai_policy_context_view(
        self,
        assembled_context: AssembledContext,
    ) -> AIPolicyContextView:
        """내부 assembled context를 AI Policy Stage 전용 입력 뷰로 축소한다."""
        return AIPolicyContextView(
            decision_context=assembled_context.decision_context,
            recent_events=assembled_context.recent_events,
            score=assembled_context.score,
            position_snapshot=assembled_context.position_snapshot,
            cash_balance_snapshot=assembled_context.cash_balance_snapshot,
            risk_limit_snapshot=assembled_context.risk_limit_snapshot,
            signal_feature_snapshot=assembled_context.signal_feature_snapshot,
            market_regime=assembled_context.market_regime,
            strategy_selection=assembled_context.strategy_selection,
            portfolio_allocation=assembled_context.portfolio_allocation,
            deterministic_trigger=assembled_context.deterministic_trigger,
            instrument_market_segment=assembled_context.instrument_market_segment,
            instrument_index_memberships=assembled_context.instrument_index_memberships,
            primary_index_membership=assembled_context.primary_index_membership,
            source_type=assembled_context.source_type,
        )

    @staticmethod
    def _extract_instrument_market_segment(
        instrument: InstrumentEntity | None,
        request: SubmitOrderRequest,
    ) -> str | None:
        if instrument is not None and instrument.market_segment:
            value = str(instrument.market_segment).strip().upper()
            if value:
                return value
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        raw = metadata.get("market_segment")
        if raw is None:
            return None
        value = str(raw).strip().upper()
        return value or None

    @staticmethod
    def _extract_instrument_index_memberships(
        instrument: InstrumentEntity | None,
        request: SubmitOrderRequest,
    ) -> tuple[str, ...]:
        candidates: object | None = None
        if instrument is not None and isinstance(instrument.metadata, dict):
            candidates = instrument.metadata.get("index_memberships")
        if candidates is None and isinstance(request.metadata, dict):
            candidates = request.metadata.get("index_memberships")
        if candidates is None:
            return ()
        if isinstance(candidates, str):
            raw_values = [candidates]
        elif isinstance(candidates, (list, tuple, set, frozenset)):
            raw_values = list(candidates)
        else:
            return ()
        return normalize_index_memberships(raw_values)

    def _build_short_circuit_agent_bundle(
        self,
        *,
        decision_type: str,
        rationale: str,
        reason_codes: tuple[str, ...],
        validation_result: ValidationResult,
    ) -> AgentExecutionBundle:
        """AI 호출 없이 deterministic policy stage에서 종료할 bundle 생성."""
        event_output = EventInterpretationOutput()
        risk_output = AIRiskOutput(
            reason_codes=("pre_ai_short_circuit",),
            summary="AI 호출 전 deterministic short-circuit 적용",
        )
        composer_output = FinalDecisionComposerOutput(
            decision_type=decision_type,
            side="",
            confidence=0.0,
            conviction=0.0,
            reason_codes=reason_codes,
            summary=rationale,
        )
        ai_inputs = AIDecisionInputs(
            decision_type=decision_type,
            confidence=0.0,
            conviction=0.0,
            reason_codes=reason_codes,
            side="",
            risk_opinion=risk_output.risk_opinion,
            risk_score=risk_output.risk_score,
            risk_confidence=risk_output.confidence,
            size_adjustment_factor=risk_output.size_adjustment_factor,
            risk_reason_codes=risk_output.reason_codes,
            risk_flags=risk_output.risk_flags,
            event_bias=event_output.aggregate_view.overall_bias,
            event_conflict=event_output.aggregate_view.event_conflict,
            event_reason_codes=event_output.aggregate_view.top_reason_codes,
            evidence_strength=event_output.aggregate_view.evidence_strength,
            no_material_events=event_output.aggregate_view.no_material_events,
            detected_event_count=event_output.detected_event_count,
            interpreted_event_count=event_output.interpreted_event_count,
            source_agent_names=(),
            schema_versions=(
                ("event_interpretation", event_output.schema_version),
                ("ai_risk", risk_output.schema_version),
                ("final_decision_composer", composer_output.schema_version),
            ),
            ei_skipped=True,
            ar_skipped=True,
            fdc_skipped=True,
            skip_reason_codes=reason_codes,
        )
        expected_value = evaluate_expected_value_gate(
            decision_type=ai_inputs.decision_type,
            confidence=ai_inputs.confidence,
            conviction=ai_inputs.conviction,
            risk_score=ai_inputs.risk_score,
            context=AssembledContext(source_type="core"),
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
            validator_rule_set_version=validation_result.rule_set_version,
            validator_stop_reason=validation_result.stop_reason,
            validator_blocking_rule_codes=validation_result.blocking_rule_codes,
        )
        return AgentExecutionBundle(
            ai_inputs=ai_inputs,
            event_output=event_output,
            risk_output=risk_output,
            composer_output=composer_output,
        )

    def _build_decision_policy_validation_result(
        self,
        *,
        blocking_rule_codes: tuple[str, ...],
        rule_results: dict[str, object] | None = None,
    ) -> ValidationResult:
        """decision_orchestrator의 deterministic 차단 결과를 공통 계약으로 표현한다."""
        return ValidationResult.blocked(
            rule_set_version="decision_policy_validator_v1",
            blocking_rule_codes=blocking_rule_codes,
            rule_results=rule_results or {},
            stop_reason=blocking_rule_codes[0] if blocking_rule_codes else None,
        )

    def _build_compliance_validation_result(
        self,
        *,
        source_type: str,
        has_position: bool,
        intent_action: str = "new_buy",
        context_metadata: dict[str, object] | None = None,
    ) -> ValidationResult:
        return evaluate_compliance_rules(
            context=ValidationContext(
                source_type=source_type,
                metadata=dict(context_metadata or {}),
            ),
            validation_input=ComplianceValidationInput(
                source_type=source_type,
                has_position=has_position,
                intent_action=intent_action,
            ),
        )

    def _apply_validation_result_to_ai_inputs(
        self,
        ai_inputs: AIDecisionInputs,
        *,
        validation_result: ValidationResult,
    ) -> None:
        """최종 AI 입력 계약에 validator 메타데이터를 누적한다."""
        existing_codes = tuple(ai_inputs.validator_blocking_rule_codes or ())
        merged_codes = tuple(
            dict.fromkeys(existing_codes + tuple(validation_result.blocking_rule_codes))
        )
        object.__setattr__(
            ai_inputs,
            "validator_rule_set_version",
            validation_result.rule_set_version,
        )
        object.__setattr__(
            ai_inputs,
            "validator_stop_reason",
            validation_result.stop_reason,
        )
        object.__setattr__(
            ai_inputs,
            "validator_blocking_rule_codes",
            merged_codes,
        )

    def _evaluate_pre_agent_short_circuit(
        self,
        *,
        assembled_context: AIPolicyContextView,
    ) -> AgentExecutionBundle | None:
        """AI 호출 전 deterministic context만으로 종료 가능한 경우를 판정한다."""
        source_type = (assembled_context.source_type or "core").strip().lower()

        position_snapshot = assembled_context.position_snapshot
        has_position = (
            position_snapshot is not None
            and position_snapshot.quantity is not None
            and position_snapshot.quantity > 0
        )

        deterministic_trigger = assembled_context.deterministic_trigger
        if deterministic_trigger is None:
            return None

        envelope = evaluate_action_envelope(
            source_type=source_type,
            has_position=has_position,
        )
        if (
            source_type == "reconciliation_overlay"
            and not has_position
            and not envelope.allow_new_buy
        ):
            decision_type = (
                "WATCH" if bool(deterministic_trigger.watch_candidate) else "HOLD"
            )
            rationale = (
                "[pre_ai_short_circuit] source policy상 신규 진입 금지. "
                f"source_type={source_type} "
                f"reason_codes={','.join(envelope.reason_codes)} "
                f"이므로 AI 호출 없이 {decision_type}로 종료"
            )
            reason_codes = (
                "pre_ai_short_circuit",
                "source_policy_buy_blocked",
            ) + envelope.reason_codes
            compliance_result = self._build_compliance_validation_result(
                source_type=source_type,
                has_position=has_position,
                intent_action="new_buy",
                context_metadata={
                    "decision_type": decision_type,
                    "pre_ai_short_circuit": True,
                },
            )
            return self._build_short_circuit_agent_bundle(
                decision_type=decision_type,
                rationale=rationale,
                reason_codes=reason_codes,
                validation_result=compliance_result,
            )

        if source_type not in _PRE_AI_SHORT_CIRCUIT_SOURCE_TYPES:
            return None
        if has_position:
            return None

        eligibility_reasons = tuple(
            deterministic_trigger.eligibility_reasons or ()
        )
        blocking_reasons = tuple(
            reason
            for reason in eligibility_reasons
            if reason in _PRE_AI_ELIGIBILITY_BLOCK_REASONS
        )
        risk_off_exception_eligible = bool(
            getattr(deterministic_trigger, "risk_off_exception_eligible", False)
        )
        if blocking_reasons:
            residual_blocking_reasons = tuple(
                reason
                for reason in blocking_reasons
                if not (
                    reason == "eligibility_risk_off_block"
                    and risk_off_exception_eligible
                )
            )
            if not residual_blocking_reasons:
                return None
            decision_type = (
                "WATCH" if bool(deterministic_trigger.watch_candidate) else "HOLD"
            )
            rationale = (
                "[pre_ai_short_circuit] core 신규 진입 비적격 종목. "
                f"eligibility_reasons={','.join(residual_blocking_reasons)} "
                f"이므로 AI 호출 없이 {decision_type}로 종료"
            )
            reason_codes = ("pre_ai_short_circuit",) + residual_blocking_reasons
            validation_result = self._build_decision_policy_validation_result(
                blocking_rule_codes=reason_codes,
                rule_results={
                    "source_type": source_type,
                    "decision_type": decision_type,
                    "eligibility_reasons": residual_blocking_reasons,
                },
            )
            return self._build_short_circuit_agent_bundle(
                decision_type=decision_type,
                rationale=rationale,
                reason_codes=reason_codes,
                validation_result=validation_result,
            )

        primary_candidate = (
            getattr(deterministic_trigger, "primary_candidate", "") or ""
        ).strip().upper()
        if primary_candidate == "NO_ACTION" and not assembled_context.recent_events:
            rationale = (
                "[pre_ai_short_circuit] deterministic_trigger=NO_ACTION 이고 "
                "recent_events=0 이므로 AI 호출 없이 HOLD로 종료"
            )
            validation_result = self._build_decision_policy_validation_result(
                blocking_rule_codes=(
                    "pre_ai_short_circuit",
                    "pre_ai_no_action_no_event",
                ),
                rule_results={
                    "source_type": source_type,
                    "decision_type": "HOLD",
                    "recent_event_count": 0,
                },
            )
            return self._build_short_circuit_agent_bundle(
                decision_type="HOLD",
                rationale=rationale,
                reason_codes=(
                    "pre_ai_short_circuit",
                    "pre_ai_no_action_no_event",
                ),
                validation_result=validation_result,
            )

        return None

    async def assemble(
        self,
        request: SubmitOrderRequest,
        *,
        decision_context_id: UUID | None = None,
        order_intent_id: UUID | None = None,
        seeded_events: list[ExternalEventEntity] | None = None,
    ) -> OrderIntent:
        """Assemble a structured order intent from a raw request.

        Parameters
        ----------
        request : SubmitOrderRequest
            The partially populated order request from the decision layer.
        decision_context_id : UUID | None
            The active decision context ID (P0 field). If not provided,
            the service resolves the most recent active context.
        order_intent_id : UUID | None
            The order intent ID (P1 field, optional). If not provided,
            a new UUID is generated.
        seeded_events : list[ExternalEventEntity] | None
            Transient seeded news events (T3) to inject alongside authoritative
            events. Passed from ``_run_one_cycle()`` — not persisted to DB.

        Returns
        -------
        OrderIntent
            A structured intent with P1 fields and assembled context attached.
        """
        # --- Resolve or create active decision context ---
        # Ensures a valid decision_context_id exists before agent execution,
        # so that Postgres-backed agent run persistence works correctly.
        resolved_context_id = await self._ensure_or_create_decision_context(
            request, decision_context_id
        )

        # --- Resolve full DecisionContextEntity ---
        decision_context: DecisionContextEntity | None = None
        if resolved_context_id is not None:
            decision_context = await self._decision_context_service.resolve(
                resolved_context_id
            )

        # --- Resolve config version from decision context ---
        config_version: ConfigVersionEntity | None = None
        config_version_id: UUID | None = None
        if decision_context is not None and decision_context.config_version_id is not None:
            try:
                config_version = await self._repos.config_versions.get(
                    decision_context.config_version_id
                )
                if config_version is not None:
                    config_version_id = config_version.config_version_id
            except Exception:
                pass

        # --- Query recent external events (stub) ---
        recent_events: tuple[ExternalEventEntity, ...] = ()
        try:
            events = await self._repos.external_events.list_by_symbol(
                symbol=request.symbol,
                since=datetime.now(timezone.utc) - timedelta(hours=72),
                include_seeded_news=True,
            )
            events = list(events)

            # Inject seeded news events as lower-priority supplement
            # Dedup by event_id: seeded_events may overlap with list_by_symbol
            # results since both originate from external_events table.
            if seeded_events:
                existing_ids = {e.event_id for e in events}
                symbol_seeded = [
                    e for e in seeded_events
                    if e.symbol == request.symbol and e.event_id not in existing_ids
                ]
                if symbol_seeded:
                    events.extend(symbol_seeded)

            # Sort: importance desc → T1/T2 first → T3/T4 later → published_at desc
            events.sort(key=event_sort_key, reverse=True)
            recent_events = tuple(events)

            logger.info(
                "assemble() recent_events: symbol=%s count=%d "
                "(list_by_symbol=%d seeded_supplement=%d)",
                request.symbol,
                len(recent_events),
                len(events) - (len(symbol_seeded) if seeded_events else 0),
                len(symbol_seeded) if seeded_events else 0,
            )
        except Exception:
            logger.warning(
                "assemble() failed to query recent_events: symbol=%s",
                request.symbol,
                exc_info=True,
            )

        # --- Resolve instrument for position filtering ---
        instrument: InstrumentEntity | None = None
        try:
            instrument = await self._repos.instruments.get_by_symbol(
                symbol=request.symbol,
                market_code=request.market,
            )
            if instrument is None:
                instrument = await self._repos.instruments.get_by_symbol_any_market(
                    request.symbol
                )
        except Exception:
            pass

        # --- Query position snapshot ---
        # Priority:
        #   1. decision_context.position_snapshot_id → get(id) → accept regardless of
        #      instrument lookup success (strongest source of truth for replay).
        #   2. If no explicit ID, account latest snapshots → symbol-filter by instrument.
        position_snapshot: PositionSnapshotEntity | None = None
        if decision_context is not None:
            if decision_context.position_snapshot_id is not None:
                try:
                    pos = await self._repos.position_snapshots.get(
                        decision_context.position_snapshot_id
                    )
                    if pos is not None:
                        position_snapshot = pos
                except Exception:
                    pass
            if position_snapshot is None and decision_context.account_id is not None:
                try:
                    snaps = await self._repos.position_snapshots.list_latest_by_account(
                        decision_context.account_id
                    )
                    for s in snaps:
                        if instrument is not None and s.instrument_id == instrument.instrument_id:
                            position_snapshot = s
                            break
                except Exception:
                    pass

        # --- Query cash balance snapshot ---
        # Priority: decision_context.cash_balance_snapshot_id → account latest
        cash_balance_snapshot: CashBalanceSnapshotEntity | None = None
        if decision_context is not None:
            if decision_context.cash_balance_snapshot_id is not None:
                try:
                    cash_balance_snapshot = await self._repos.cash_balance_snapshots.get(
                        decision_context.cash_balance_snapshot_id
                    )
                except Exception:
                    pass
            if cash_balance_snapshot is None and decision_context.account_id is not None:
                try:
                    cash_balance_snapshot = await self._repos.cash_balance_snapshots.get_latest_by_account(
                        decision_context.account_id
                    )
                except Exception:
                    pass
            if decision_context.account_id is not None and (
                cash_balance_snapshot is None
                or cash_balance_snapshot.fetch_status != "success"
            ):
                replacement_cash = await self._select_usable_cash_snapshot(
                    decision_context.account_id,
                )
                if replacement_cash is not None:
                    cash_balance_snapshot = replacement_cash

        # --- Query risk limit snapshot ---
        risk_limit_snapshot: RiskLimitSnapshotEntity | None = None
        if decision_context is not None and decision_context.account_id is not None:
            try:
                risk_limit_snapshot = await self._repos.risk_limit_snapshots.get_latest_by_account(
                    decision_context.account_id
                )
            except Exception:
                pass

        derivation = await self._derive_deterministic_context_components(
            request=request,
            config_version=config_version,
            instrument=instrument,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
        )
        decision_context = await self._attach_signal_feature_snapshot_to_context(
            decision_context,
            derivation.signal_feature_snapshot,
        )
        decision_context = await self._attach_cash_balance_snapshot_to_context(
            decision_context,
            cash_balance_snapshot,
        )
        instrument_market_segment = self._extract_instrument_market_segment(
            instrument,
            request,
        )
        instrument_index_memberships = self._extract_instrument_index_memberships(
            instrument,
            request,
        )
        primary_index_membership = derive_primary_index_membership(
            instrument_index_memberships
        )

        # --- Assemble context (without score yet) ---
        assembled_context = AssembledContext(
            decision_context=decision_context,
            config_version=config_version,
            recent_events=recent_events,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
            signal_feature_snapshot=derivation.signal_feature_snapshot,
            market_regime=derivation.market_regime,
            strategy_selection=derivation.strategy_selection,
            portfolio_allocation=derivation.portfolio_allocation,
            deterministic_trigger=derivation.deterministic_trigger,
            instrument_market_segment=instrument_market_segment,
            instrument_index_memberships=instrument_index_memberships,
            primary_index_membership=primary_index_membership,
            source_type=derivation.source_type,
        )

        # --- Calculate score ---
        score_result = await self._score_calculator.calculate(assembled_context)

        # --- Rebuild context with score ---
        assembled_context = AssembledContext(
            decision_context=decision_context,
            config_version=config_version,
            recent_events=recent_events,
            score=score_result,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
            signal_feature_snapshot=derivation.signal_feature_snapshot,
            market_regime=derivation.market_regime,
            strategy_selection=derivation.strategy_selection,
            portfolio_allocation=derivation.portfolio_allocation,
            deterministic_trigger=derivation.deterministic_trigger,
            instrument_market_segment=instrument_market_segment,
            instrument_index_memberships=instrument_index_memberships,
            primary_index_membership=primary_index_membership,
            source_type=derivation.source_type,
        )

        # --- Generate order_intent_id if not provided ---
        resolved_intent_id = order_intent_id or uuid4()

        # --- Generate correlation_id if not provided ---
        correlation_id = request.correlation_id
        if not correlation_id:
            correlation_id = str(uuid4())

        # --- Run AI agents → persistence bundle + normalised backend inputs ---
        # Phase 4: subprocess isolation — when enabled, agents run in a separate
        # subprocess with SIGKILL-guaranteed timeout.  When disabled (tests),
        # the original in-process _run_agents() is used.
        ai_policy_context = self._build_ai_policy_context_view(assembled_context)

        # Build shared AgentExecutionRequest for the agent runner wrappers.
        agent_request = AgentExecutionRequest(
            decision_context_id=resolved_context_id,
            correlation_id=correlation_id,
            context=ai_policy_context,
            symbol=request.symbol,
            market=request.market,
            source_type=assembled_context.source_type,
        )
        short_circuit_bundle = self._evaluate_pre_agent_short_circuit(
            assembled_context=ai_policy_context,
        )
        if short_circuit_bundle is not None:
            agent_bundle = short_circuit_bundle
            _fdc_run_id = None
            logger.info(
                "Pre-agent short-circuit applied: symbol=%s source_type=%s "
                "decision_type=%s reason_codes=%s",
                request.symbol,
                assembled_context.source_type,
                agent_bundle.ai_inputs.decision_type,
                agent_bundle.ai_inputs.reason_codes,
            )
        elif self._use_subprocess_isolation:
            agent_bundle = await self._run_agents_in_subprocess(
                request=agent_request,
                assembled_context=ai_policy_context,
            )
            # ── Phase 5.6: Rehydrate AgentRunEntity records from subprocess output ──
            # The subprocess path does NOT call recorder.record() internally
            # (unlike _run_agents()).  We rehydrate here so that AgentRuns
            # persistence works identically for both paths.
            _fdc_run_id: UUID | None = None
            try:
                # ★ subprocess 경로: EI 실패 시 error metadata를 __error__로 주입
                _ei_structured = dataclass_to_dict(agent_bundle.event_output)
                if agent_bundle.ei_error_metadata is not None:
                    _ei_structured["__error__"] = agent_bundle.ei_error_metadata
                _ei_run = await self._agent_recorder.record(
                    decision_context_id=resolved_context_id,
                    agent_type=self._event_interpretation_agent.agent_name,
                    structured_output=_ei_structured,
                )
                _ar_run = await self._agent_recorder.record(
                    decision_context_id=resolved_context_id,
                    agent_type=self._ai_risk_agent.agent_name,
                    structured_output=dataclass_to_dict(agent_bundle.risk_output),
                )
                _fdc_run = await self._agent_recorder.record(
                    decision_context_id=resolved_context_id,
                    agent_type=self._final_decision_agent.agent_name,
                    structured_output=dataclass_to_dict(agent_bundle.composer_output),
                )
                _fdc_run_id = _fdc_run.agent_run_id
                logger.info(
                    'Rehydrated %d agent runs from subprocess output '
                    '(decision_context_id=%s fdc_run_id=%s)',
                    3, resolved_context_id, _fdc_run_id,
                )
            except Exception:
                logger.warning(
                    'Failed to rehydrate agent runs from subprocess output — '
                    'AgentRuns will be missing for this cycle. '
                    'decision_context_id=%s',
                    resolved_context_id,
                    exc_info=True,
                )
        else:
            agent_bundle = await self._run_agents(
                request=agent_request,
                assembled_context=ai_policy_context,
            )
            # In-process path: _run_agents() already calls recorder.record()
            # internally, so we extract the FDC run_id from the recorder's
            # in-memory buffer for _ensure_trade_decision linkage.
            _fdc_run_id = None
            try:
                _recent = await self._agent_recorder.list_by_decision_context(
                    resolved_context_id
                ) if resolved_context_id else []
                if _recent:
                    _fdc_run_id = _recent[0].agent_run_id
            except Exception:
                pass

        # ── Held position sell override ──
        # 보유 포지션(held_position) 종목에 대해 AI risk가 강한 부정 신호를 보내면
        # FDC의 HOLD/APPROVE/BUY 결정을 REDUCE/EXIT sell로 override한다.
        # recording 이후, _ensure_trade_decision() 이전에 수행하여
        # override된 값이 DB에 저장되도록 한다.
        override = self._check_held_position_sell_override(
            source_type=derivation.source_type,
            ar_output=agent_bundle.risk_output,
            fdc_output=agent_bundle.composer_output,
        )
        if override is not None:
            override_dt, override_side, override_rationale = override
            # frozen dataclass 수정을 위해 object.__setattr__ 사용
            object.__setattr__(agent_bundle.ai_inputs, "decision_type", override_dt)
            object.__setattr__(agent_bundle.ai_inputs, "side", override_side)
            # ★ composer_output도 함께 override
            # _ensure_trade_decision()에서 composer_output.decision_type/side를
            # trade_decisions에 저장하므로, override 값을 반영해야 함
            if agent_bundle.composer_output is not None:
                object.__setattr__(
                    agent_bundle.composer_output, "decision_type", override_dt,
                )
                object.__setattr__(
                    agent_bundle.composer_output, "side", override_side,
                )
                fdc_summary = agent_bundle.composer_output.summary
                object.__setattr__(
                    agent_bundle.composer_output, "summary",
                    (fdc_summary + f" | {override_rationale}") if fdc_summary else override_rationale,
                )
            logger.info(
                "Held position sell override: symbol=%s source_type=%s "
                "decision_type=%s side=%s rationale=%s",
                request.symbol, source_type, override_dt, override_side,
                override_rationale,
            )

        source_policy_guard = self._check_source_policy_upgrade_guard(
            source_type=derivation.source_type,
            deterministic_trigger=derivation.deterministic_trigger,
            fdc_output=agent_bundle.composer_output,
            position_snapshot=position_snapshot,
        )
        if source_policy_guard is not None:
            guarded_dt, guard_rationale, guard_reason_codes = source_policy_guard
            validation_result = (
                self._build_compliance_validation_result(
                    source_type=derivation.source_type,
                    has_position=(
                        position_snapshot is not None
                        and position_snapshot.quantity is not None
                        and position_snapshot.quantity > 0
                    ),
                    intent_action="new_buy",
                    context_metadata={"guarded_decision_type": guarded_dt},
                )
                if "source_policy_guard" in guard_reason_codes
                or any(code.startswith("policy_") for code in guard_reason_codes)
                else self._build_decision_policy_validation_result(
                    blocking_rule_codes=guard_reason_codes,
                    rule_results={
                        "source_type": derivation.source_type,
                        "guarded_decision_type": guarded_dt,
                    },
                )
            )
            object.__setattr__(agent_bundle.ai_inputs, "decision_type", guarded_dt)
            object.__setattr__(agent_bundle.ai_inputs, "side", "")
            self._apply_validation_result_to_ai_inputs(
                agent_bundle.ai_inputs,
                validation_result=validation_result,
            )
            existing_reason_codes = tuple(agent_bundle.ai_inputs.reason_codes or ())
            merged_reason_codes = tuple(
                dict.fromkeys(existing_reason_codes + guard_reason_codes)
            )
            object.__setattr__(
                agent_bundle.ai_inputs,
                "reason_codes",
                merged_reason_codes,
            )
            if agent_bundle.composer_output is not None:
                object.__setattr__(agent_bundle.composer_output, "decision_type", guarded_dt)
                object.__setattr__(agent_bundle.composer_output, "side", "")
                composer_reason_codes = tuple(agent_bundle.composer_output.reason_codes or ())
                merged_composer_reason_codes = tuple(
                    dict.fromkeys(composer_reason_codes + guard_reason_codes)
                )
                object.__setattr__(
                    agent_bundle.composer_output,
                    "reason_codes",
                    merged_composer_reason_codes,
                )
                fdc_summary = agent_bundle.composer_output.summary
                object.__setattr__(
                    agent_bundle.composer_output,
                    "summary",
                    (fdc_summary + f" | {guard_rationale}") if fdc_summary else guard_rationale,
                )
            logger.info(
                "Source policy upgrade guard: symbol=%s source_type=%s rationale=%s",
                request.symbol,
                derivation.source_type,
                guard_rationale,
            )

        watch_guard = self._check_watch_candidate_upgrade_guard(
            source_type=derivation.source_type,
            deterministic_trigger=derivation.deterministic_trigger,
            fdc_output=agent_bundle.composer_output,
            position_snapshot=position_snapshot,
        )
        if watch_guard is not None:
            guarded_dt, guard_rationale = watch_guard
            validation_result = self._build_decision_policy_validation_result(
                blocking_rule_codes=("watch_candidate_guard",),
                rule_results={
                    "source_type": derivation.source_type,
                    "guarded_decision_type": guarded_dt,
                },
            )
            object.__setattr__(agent_bundle.ai_inputs, "decision_type", guarded_dt)
            object.__setattr__(agent_bundle.ai_inputs, "side", "")
            self._apply_validation_result_to_ai_inputs(
                agent_bundle.ai_inputs,
                validation_result=validation_result,
            )
            existing_reason_codes = tuple(agent_bundle.ai_inputs.reason_codes or ())
            if "watch_candidate_guard" not in existing_reason_codes:
                object.__setattr__(
                    agent_bundle.ai_inputs,
                    "reason_codes",
                    existing_reason_codes + ("watch_candidate_guard",),
                )
            if agent_bundle.composer_output is not None:
                object.__setattr__(agent_bundle.composer_output, "decision_type", guarded_dt)
                object.__setattr__(agent_bundle.composer_output, "side", "")
                composer_reason_codes = tuple(agent_bundle.composer_output.reason_codes or ())
                if "watch_candidate_guard" not in composer_reason_codes:
                    object.__setattr__(
                        agent_bundle.composer_output,
                        "reason_codes",
                        composer_reason_codes + ("watch_candidate_guard",),
                    )
                fdc_summary = agent_bundle.composer_output.summary
                object.__setattr__(
                    agent_bundle.composer_output,
                    "summary",
                    (fdc_summary + f" | {guard_rationale}") if fdc_summary else guard_rationale,
                )
            logger.info(
                "Watch candidate upgrade guard: symbol=%s source_type=%s rationale=%s",
                request.symbol,
                derivation.source_type,
                guard_rationale,
            )

        buy_eligibility_guard = self._check_buy_eligibility_upgrade_guard(
            source_type=derivation.source_type,
            deterministic_trigger=derivation.deterministic_trigger,
            fdc_output=agent_bundle.composer_output,
            position_snapshot=position_snapshot,
        )
        if buy_eligibility_guard is not None:
            guarded_dt, guard_rationale = buy_eligibility_guard
            validation_result = self._build_decision_policy_validation_result(
                blocking_rule_codes=("buy_eligibility_guard",),
                rule_results={
                    "source_type": derivation.source_type,
                    "guarded_decision_type": guarded_dt,
                },
            )
            object.__setattr__(agent_bundle.ai_inputs, "decision_type", guarded_dt)
            object.__setattr__(agent_bundle.ai_inputs, "side", "")
            self._apply_validation_result_to_ai_inputs(
                agent_bundle.ai_inputs,
                validation_result=validation_result,
            )
            existing_reason_codes = tuple(agent_bundle.ai_inputs.reason_codes or ())
            if "buy_eligibility_guard" not in existing_reason_codes:
                object.__setattr__(
                    agent_bundle.ai_inputs,
                    "reason_codes",
                    existing_reason_codes + ("buy_eligibility_guard",),
                )
            if agent_bundle.composer_output is not None:
                object.__setattr__(agent_bundle.composer_output, "decision_type", guarded_dt)
                object.__setattr__(agent_bundle.composer_output, "side", "")
                composer_reason_codes = tuple(agent_bundle.composer_output.reason_codes or ())
                if "buy_eligibility_guard" not in composer_reason_codes:
                    object.__setattr__(
                        agent_bundle.composer_output,
                        "reason_codes",
                        composer_reason_codes + ("buy_eligibility_guard",),
                    )
                fdc_summary = agent_bundle.composer_output.summary
                object.__setattr__(
                    agent_bundle.composer_output,
                    "summary",
                    (fdc_summary + f" | {guard_rationale}") if fdc_summary else guard_rationale,
                )
            logger.info(
                "Buy eligibility upgrade guard: symbol=%s source_type=%s rationale=%s",
                request.symbol,
                derivation.source_type,
                guard_rationale,
            )

        ai_override_gate = await self._check_ai_buy_override_gate(
            source_type=derivation.source_type,
            deterministic_trigger=derivation.deterministic_trigger,
            fdc_output=agent_bundle.composer_output,
            ai_inputs=agent_bundle.ai_inputs,
            position_snapshot=position_snapshot,
            decision_context=decision_context,
            instrument=instrument,
        )
        if ai_override_gate is not None:
            guarded_dt, guard_rationale, guard_reason_codes = ai_override_gate
            validation_result = self._build_decision_policy_validation_result(
                blocking_rule_codes=guard_reason_codes,
                rule_results={
                    "source_type": derivation.source_type,
                    "guarded_decision_type": guarded_dt,
                },
            )
            object.__setattr__(agent_bundle.ai_inputs, "decision_type", guarded_dt)
            object.__setattr__(agent_bundle.ai_inputs, "side", "")
            self._apply_validation_result_to_ai_inputs(
                agent_bundle.ai_inputs,
                validation_result=validation_result,
            )
            existing_reason_codes = tuple(agent_bundle.ai_inputs.reason_codes or ())
            merged_reason_codes = tuple(
                dict.fromkeys(existing_reason_codes + guard_reason_codes)
            )
            object.__setattr__(
                agent_bundle.ai_inputs,
                "reason_codes",
                merged_reason_codes,
            )
            if agent_bundle.composer_output is not None:
                object.__setattr__(agent_bundle.composer_output, "decision_type", guarded_dt)
                object.__setattr__(agent_bundle.composer_output, "side", "")
                composer_reason_codes = tuple(agent_bundle.composer_output.reason_codes or ())
                merged_composer_reason_codes = tuple(
                    dict.fromkeys(composer_reason_codes + guard_reason_codes)
                )
                object.__setattr__(
                    agent_bundle.composer_output,
                    "reason_codes",
                    merged_composer_reason_codes,
                )
                fdc_summary = agent_bundle.composer_output.summary
                object.__setattr__(
                    agent_bundle.composer_output,
                    "summary",
                    (fdc_summary + f" | {guard_rationale}") if fdc_summary else guard_rationale,
                )
            logger.info(
                "AI override gate blocked: symbol=%s source_type=%s rationale=%s",
                request.symbol,
                derivation.source_type,
                guard_rationale,
            )

        # --- Persist or reuse trade decision when a concrete context exists ---
        td_entity = await self._ensure_trade_decision(
            decision_context_id=resolved_context_id,
            request=request,
            assembled_context=assembled_context,
            agent_bundle=agent_bundle,
            instrument=instrument,
            fdc_run_id=_fdc_run_id,
        )
        if td_entity is not None:
            trade_decision_id = td_entity.trade_decision_id
        else:
            trade_decision_id = None

        # --- Generate decision_id if not provided ---
        decision_id = request.decision_id
        if trade_decision_id is not None:
            decision_id = str(trade_decision_id)
        elif not decision_id:
            decision_id = str(uuid4())

        # --- Assemble the final SubmitOrderRequest ---
        assembled_request = SubmitOrderRequest(
            client_order_id=request.client_order_id,
            correlation_id=correlation_id,
            account_ref=request.account_ref,
            symbol=request.symbol,
            market=request.market,
            side=request.side,
            order_type=request.order_type,
            time_in_force=request.time_in_force,
            quantity=request.quantity,
            price=request.price,
            decision_id=decision_id,
            strategy_id=request.strategy_id,
            idempotency_key=request.idempotency_key,
            price_band_lower=request.price_band_lower,
            price_band_upper=request.price_band_upper,
            max_slippage_bps=request.max_slippage_bps,
            allow_partial_fill=request.allow_partial_fill,
            decision_context_id=str(resolved_context_id) if resolved_context_id else None,
            order_intent_id=str(resolved_intent_id),
            client_timestamp=request.client_timestamp,
            metadata=request.metadata,
        )

        # --- REDUCE/EXIT + sell side override ---
        # FDC가 REDUCE/EXIT + side="sell"을 결정하면, assembled_request.side를
        # OrderSide.SELL로 오버라이드한다. BUY/APPROVE decision_type일 때는
        # side가 오버라이드되지 않도록 조건 검사.
        fdc_side = agent_bundle.ai_inputs.side if agent_bundle else ""
        if agent_bundle.ai_inputs.decision_type in ("REDUCE", "EXIT") and fdc_side.lower() == OrderSide.SELL.value:
            assembled_request = replace(assembled_request, side=OrderSide.SELL)

        assembled_metadata = dict(assembled_request.metadata or {})
        signal_feature_snapshot_id = (
            str(assembled_context.signal_feature_snapshot.signal_feature_snapshot_id)
            if assembled_context.signal_feature_snapshot is not None
            else (
                str(assembled_context.decision_context.signal_feature_snapshot_id)
                if assembled_context.decision_context is not None
                and assembled_context.decision_context.signal_feature_snapshot_id is not None
                else None
            )
        )
        holding_profile_policy = derive_holding_profile_policy(
            source_type=assembled_context.source_type,
            decision_type=agent_bundle.ai_inputs.decision_type,
            side=agent_bundle.ai_inputs.side or assembled_request.side,
            time_horizon=(
                agent_bundle.composer_output.time_horizon
                if agent_bundle.composer_output is not None
                else None
            ),
            quantity=assembled_request.quantity,
            max_order_value=calculate_max_order_value(
                assembled_request.price,
                assembled_request.quantity,
            ),
            signal_feature_snapshot_id=signal_feature_snapshot_id,
            reason_codes=agent_bundle.ai_inputs.reason_codes,
        )
        assembled_metadata["holding_profile_policy"] = serialize_holding_profile_policy(
            holding_profile_policy
        )
        assembled_request = replace(assembled_request, metadata=assembled_metadata)

        return OrderIntent(
            decision_context_id=resolved_context_id,
            order_intent_id=resolved_intent_id,
            request=assembled_request,
            context=assembled_context,
            config_version_id=config_version_id,
            reason_codes=score_result.reason_codes,
            ai_backend_inputs=agent_bundle.ai_inputs,
            trade_decision_id=trade_decision_id,
        )

    # ------------------------------------------------------------------
    # Full pipeline: assemble → validate → create_order → submit_order
    # ------------------------------------------------------------------

    async def assemble_and_submit(
        self,
        request: SubmitOrderRequest,
        *,
        order_manager: OrderManager,
        broker: BrokerAdapter,
        decision_context_id: UUID | None = None,
        order_intent_id: UUID | None = None,
        seeded_events: list[ExternalEventEntity] | None = None,
        actor_type: str = "system",
        actor_id: str = "decision_orchestrator",
    ) -> SubmitResult:
        """Execute the full AI decision → order submit pipeline.

        This is the **primary entry point** for paper trading.  It chains:

        1. ``assemble()`` → runs EI/AR/FDC agents, persists ``TradeDecisionEntity``,
           returns ``OrderIntent``.
        2. ``build_submit_order_request_from_decision()`` → validates the intent
           and builds a ``SubmitOrderRequest`` (or signals ``SKIPPED`` when the
           decision is HOLD).
        3. ``OrderManager.create_order()`` → validates, persists a ``DRAFT`` order.
        4. ``OrderManager.transition_to(PENDING_SUBMIT)`` → moves the order to
           submit-ready state.
        5. ``OrderManager.submit_order_to_broker()`` → blocking lock check,
           broker submission, result handling (SUBMITTED / RECONCILE_REQUIRED /
           REJECTED).

        Parameters
        ----------
        request : SubmitOrderRequest
            Initial order request (minimal fields — side, symbol, market, etc.).
        order_manager : OrderManager
            Fully configured ``OrderManager`` with repository and reconciliation
            service wired in.
        broker : BrokerAdapter
            The broker adapter to submit orders through.
        decision_context_id : UUID | None
            Optional explicit decision context ID.  Auto-resolved when ``None``.
        order_intent_id : UUID | None
            Optional explicit order intent ID.  Auto-generated when ``None``.
        seeded_events : list[ExternalEventEntity] | None
            Transient seeded news events (T3) to inject into assemble context.
        actor_type, actor_id :
            Identity used for audit-log entries.

        Returns
        -------
        SubmitResult
            Structured result with status, intent, order, and error details.
        """
        # ── Phase trace accumulator (EXE-001) ──
        _phase_start = time_module.monotonic()
        _phase_trace: list[PhaseTraceEntry] = []

        def _add_phase(phase: str, status: str) -> None:
            """현재 단계 추적을 기록하고 타이머를 재설정한다."""
            nonlocal _phase_start
            now = time_module.monotonic()
            elapsed = int((now - _phase_start) * 1000)
            _phase_trace.append(PhaseTraceEntry(phase=phase, elapsed_ms=elapsed, status=status))
            _phase_start = now

        # ── Phase 1: Decision pipeline (AI assemble → TD resolve) ──
        intent, trade_decision_id, pipeline_result = await self._run_decision_pipeline(
            request,
            decision_context_id=decision_context_id,
            order_intent_id=order_intent_id,
            seeded_events=seeded_events,
            _add_phase=_add_phase,
            _phase_trace=_phase_trace,
        )
        if pipeline_result is not None:
            return pipeline_result

        # ── Phase 1.5–5.5: Execution pipeline (sizing → guard → translate → create → submit) ──
        return await self._execution_service.run_execution_pipeline(
            intent,
            trade_decision_id,
            request,
            order_manager,
            broker,
            actor_type=actor_type,
            actor_id=actor_id,
            _add_phase=_add_phase,
            _phase_trace=_phase_trace,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------


    async def _run_decision_pipeline(
        self,
        request: SubmitOrderRequest,
        *,
        decision_context_id: UUID | None = None,
        order_intent_id: UUID | None = None,
        seeded_events: list[ExternalEventEntity] | None = None,
        _add_phase: Callable[[str, str], None],
        _phase_trace: list[PhaseTraceEntry],
    ) -> tuple[OrderIntent | None, UUID | None, SubmitResult | None]:
        """Decision pipeline: AI assemble → TD resolve.

        Returns ``(intent, trade_decision_id, None)`` on success,
        or ``(None, None, submit_result)`` on error (caller should return
        the ``submit_result`` immediately).

        Note
        ----
        ``ExecutionAttemptEntity`` creation has moved to
        ``ExecutionService.run_execution_pipeline()``.
        """
        _symbol = request.symbol
        _add_phase("ai_assemble", "start")
        logger.info(
            "PHASE_TRACE symbol=%s phase=assemble_start elapsed_ms=0 status=start",
            _symbol,
        )
        _assemble_t0 = time_module.monotonic()
        logger.info("Phase 1: assemble() — running AI agents …")
        try:
            intent = await self.assemble(
                request,
                decision_context_id=decision_context_id,
                order_intent_id=order_intent_id,
                seeded_events=seeded_events,
            )
            _assemble_elapsed = time_module.monotonic() - _assemble_t0
            logger.info(
                "PHASE_TRACE symbol=%s phase=assemble_done elapsed_ms=%d status=ok",
                _symbol, int(_assemble_elapsed * 1000),
            )
            _add_phase("ai_assemble", "ok")
        except asyncio.TimeoutError:
            logger.error(
                "Phase 1 TIMEOUT: assemble() exceeded timeout. "
                "decision_context_id=%s symbol=%s",
                decision_context_id,
                request.symbol,
            )
            return None, None, SubmitResult(
                status="ERROR",
                error_phase="ai_timeout",
                error_message=f"assemble() timed out for symbol={request.symbol}",
                decision_context_id=decision_context_id,
            )
        except Exception as exc:
            logger.exception(
                "Phase 1 FAILED (ai): assemble() raised unexpectedly. "
                "decision_context_id=%s",
                decision_context_id,
            )
            return None, None, SubmitResult(
                status="ERROR",
                error_phase="ai",
                error_message=f"assemble() failed: {exc}",
                decision_context_id=decision_context_id,
            )

        # trade_decision_id is already stored on the intent by assemble()
        trade_decision_id = intent.trade_decision_id

        # NOTE: ExecutionAttemptEntity creation has moved to
        # ExecutionService.run_execution_pipeline().

        return intent, trade_decision_id, None






    # ------------------------------------------------------------------
    # AI Agent execution — thin wrappers delegating to DecisionAgentRunner
    # ------------------------------------------------------------------

    async def _run_agents(
        self,
        request: AgentExecutionRequest,
        assembled_context: AIPolicyContextView,
    ) -> AgentExecutionBundle:
        """Thin wrapper — delegates to DecisionAgentRunner.run_agents()."""
        return await self._agent_runner.run_agents(
            request=request,
            assembled_context=assembled_context,
        )

    # ------------------------------------------------------------------
    # Phase 4: Subprocess isolation for agent calls — thin wrapper
    # ------------------------------------------------------------------

    async def _run_agents_in_subprocess(
        self,
        request: AgentExecutionRequest,
        assembled_context: AIPolicyContextView,
    ) -> AgentExecutionBundle:
        """Thin wrapper — delegates to DecisionAgentRunner.run_agents_in_subprocess()."""
        return await self._agent_runner.run_agents_in_subprocess(
            request=request,
            assembled_context=assembled_context,
        )
