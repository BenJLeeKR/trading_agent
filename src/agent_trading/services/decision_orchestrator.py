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
from agent_trading.services.market_regime import classify_market_regime
from agent_trading.services.portfolio_allocation import assess_portfolio_allocation
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

logger = logging.getLogger(__name__)

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
    ) -> tuple[str, str] | None:
        """결정적 WATCH 후보가 AI 단계에서 진입/매도로 승격되는 것을 제한한다."""
        if deterministic_trigger is None or fdc_output is None:
            return None

        guarded_source_types = {"core", "held_position"}
        if source_type not in guarded_source_types:
            return None

        primary_candidate = (
            getattr(deterministic_trigger, "primary_candidate", "") or ""
        ).strip().upper()
        if primary_candidate != "WATCH":
            return None

        decision_type = (fdc_output.decision_type or "").strip().upper()
        if decision_type not in {"APPROVE", "BUY", "SELL", "EXIT", "REDUCE"}:
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
    ) -> tuple[str, str] | None:
        """BUY 적격성 실패 상태에서 AI의 진입 승격을 제한한다."""
        if deterministic_trigger is None or fdc_output is None:
            return None

        if source_type != "core":
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
        fdc_run_id: UUID | None = None,
    ) -> TradeDecisionEntity | None:
        """Thin wrapper — delegates to build_trade_decision_entity() + repository add."""
        td_entity = build_trade_decision_entity(
            decision_context_id=decision_context_id,
            request=request,
            assembled_context=assembled_context,
            agent_bundle=agent_bundle,
            fdc_run_id=fdc_run_id,
        )
        if td_entity is not None:
            td_entity = await self._repos.trade_decisions.add(td_entity)
        return td_entity

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
            source_type=assembled_context.source_type,
        )

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
        if self._use_subprocess_isolation:
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

        watch_guard = self._check_watch_candidate_upgrade_guard(
            source_type=derivation.source_type,
            deterministic_trigger=derivation.deterministic_trigger,
            fdc_output=agent_bundle.composer_output,
        )
        if watch_guard is not None:
            guarded_dt, guard_rationale = watch_guard
            object.__setattr__(agent_bundle.ai_inputs, "decision_type", guarded_dt)
            object.__setattr__(agent_bundle.ai_inputs, "side", "")
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
        )
        if buy_eligibility_guard is not None:
            guarded_dt, guard_rationale = buy_eligibility_guard
            object.__setattr__(agent_bundle.ai_inputs, "decision_type", guarded_dt)
            object.__setattr__(agent_bundle.ai_inputs, "side", "")
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

        # --- Persist or reuse trade decision when a concrete context exists ---
        td_entity = await self._ensure_trade_decision(
            decision_context_id=resolved_context_id,
            request=request,
            assembled_context=assembled_context,
            agent_bundle=agent_bundle,
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
