from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

import asyncpg

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    ExternalEventEntity,
    GuardrailEvaluationEntity,
    InstrumentEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
    TradeDecisionEntity,
)
from agent_trading.domain.enums import DecisionType, EntryStyle, OrderSide, OrderStatus, OrderType
from agent_trading.domain.models import SubmitOrderRequest
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
    ExecutionPreferences,
    FinalDecisionComposerOutput,
    SizingHint,
)
from agent_trading.services.sizing_engine import (
    SizingInputs,
    calculate_sizing,
)

logger = logging.getLogger(__name__)

# Phase 5.5: post-submit sync timeout (seconds)
_PHASE55_SYNC_TIMEOUT: int = 5

# Per-agent timeout: each LLM call is capped at 25s so that a single
# hanging agent cannot stall the entire decision cycle beyond 75s.
# This value is aligned with the provider client's read timeout (25s).
_PER_AGENT_TIMEOUT = 25  # seconds per agent


# ---------------------------------------------------------------------------
# Scoring protocol (deterministic stub)
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class ScoreResult:
    """Deterministic scoring result from a ``ScoreCalculator``.

    This is a **stub** — actual scoring logic is deferred. The structure
    is defined now so that downstream consumers (``OrderIntent``,
    ``AssembledContext``) can reference it.
    """

    score: float = 0.0
    threshold: float = 0.0
    reason_codes: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class AccountSnapshotFreshness:
    """Account-level snapshot freshness summary for Phase 4c guard.

    Evaluates whether a specific account's cash and position snapshots
    are fresh enough to proceed with broker submission.  Uses the same
    ``stale_threshold_seconds`` as the run-level summary.
    """

    account_id: UUID
    latest_cash_snapshot_at: datetime | None
    latest_position_snapshot_at: datetime | None
    is_cash_stale: bool
    is_position_stale: bool
    is_stale: bool


@dataclass(slots=True, frozen=True)
class AIDecisionInputs:
    """Normalised backend contract carrying v1 Provider AI Agent outputs.

    This is the **only** channel through which EI / AR / FDC agent outputs
    reach the deterministic backend (``OrderIntent`` → ``OrderManager``).

    Design rules
    ------------
    1. Raw agent outputs are **not** carried — only normalised fields
       that the deterministic backend can consume.
    2. Every field has a deterministic default — safe fallback guaranteed
       even when every agent fails.
    3. This contract does **not** modify ``SubmitOrderRequest``.
    4. ``OrderManager``, ``BrokerAdapter``, ``ReconciliationService``
       boundaries are unchanged.
    """

    # ── FDC-derived ──────────────────────────────────────────────────
    decision_type: str = "HOLD"
    confidence: float = 0.0
    conviction: float = 0.0
    reason_codes: tuple[str, ...] = ()
    opposing_evidence: tuple[str, ...] = ()
    execution_preferences: ExecutionPreferences = field(
        default_factory=ExecutionPreferences
    )
    sizing_hint: SizingHint = field(default_factory=SizingHint)

    # ── AR-derived ───────────────────────────────────────────────────
    risk_opinion: str = "allow"
    risk_score: float = 0.0
    risk_confidence: float = 0.0
    size_adjustment_factor: float = 0.0
    risk_reason_codes: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()

    # ── EI-derived ───────────────────────────────────────────────────
    event_bias: str = "neutral"
    event_conflict: bool = False
    event_reason_codes: tuple[str, ...] = ()

    # ── Metadata ─────────────────────────────────────────────────────
    source_agent_names: tuple[str, ...] = ()
    schema_versions: tuple[tuple[str, str], ...] = ()


@dataclass(slots=True, frozen=True)
class AgentExecutionBundle:
    """Internal result bundle from the three-agent chain.

    Keeps raw structured outputs available for persistence while exposing
    only the normalised ``AIDecisionInputs`` to downstream execution code.
    """

    ai_inputs: AIDecisionInputs = field(default_factory=AIDecisionInputs)
    event_output: EventInterpretationOutput = field(
        default_factory=EventInterpretationOutput
    )
    risk_output: AIRiskOutput = field(default_factory=AIRiskOutput)
    composer_output: FinalDecisionComposerOutput = field(
        default_factory=FinalDecisionComposerOutput
    )


class ScoreCalculator(Protocol):
    """Protocol for deterministic scoring of an assembled context.

    This is a **hook** — the actual implementation will be added in a
    later milestone. The protocol exists now so that
    ``DecisionOrchestratorService`` can call it when present.
    """

    async def calculate(self, context: AssembledContext) -> ScoreResult:
        """Calculate a deterministic score for the given context.

        Parameters
        ----------
        context : AssembledContext
            The fully assembled context including decision context,
            config version, and recent external events.

        Returns
        -------
        ScoreResult
            A deterministic score with threshold and reason codes.
        """
        ...


# ---------------------------------------------------------------------------
# Assembled context
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class AssembledContext:
    """Fully assembled context for a single order intent.

    This aggregates all available information at decision time:
    the active decision context, the governing config version,
    recent external events, a deterministic score, and richer
    deterministic account / risk data (position, cash, risk limits).

    All fields are optional — the service assembles what it can and
    leaves missing pieces as ``None`` or empty.

    Parameters
    ----------
    source_type
        Origin of this symbol in the trading universe:
        ``"core"`` | ``"held_position"`` | ``"event_overlay"`` | ``"market_overlay"``.
        Used by FDC to differentiate no-event policy per source type.
    """

    decision_context: DecisionContextEntity | None = None
    config_version: ConfigVersionEntity | None = None
    recent_events: tuple[ExternalEventEntity, ...] = ()
    score: ScoreResult = field(default_factory=ScoreResult)
    position_snapshot: PositionSnapshotEntity | None = None
    cash_balance_snapshot: CashBalanceSnapshotEntity | None = None
    risk_limit_snapshot: RiskLimitSnapshotEntity | None = None
    # --- Axis 2: Source type for no-event policy differentiation ---
    source_type: str = "core"
    """Origin of this symbol: ``"core"`` | ``"held_position"`` | ``"event_overlay"`` | ``"market_overlay"``."""


# ---------------------------------------------------------------------------
# Order intent
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class OrderIntent:
    """Structured order intent assembled by the DecisionOrchestratorService.

    This is a **deterministic stub** — it does not perform any LLM
    orchestration. Its sole responsibility is to assemble P1 fields
    (``decision_context_id``, ``order_intent_id``) into a
    ``SubmitOrderRequest``.

    Full LLM-based orchestration is deferred to a later milestone.
    """

    decision_context_id: UUID | None
    order_intent_id: UUID | None
    request: SubmitOrderRequest
    # --- Priority 3 extensions ---
    context: AssembledContext = field(default_factory=AssembledContext)
    config_version_id: UUID | None = None
    reason_codes: tuple[str, ...] = ()
    # --- Normalised AI backend contract (Priority A coupling) ---
    ai_backend_inputs: AIDecisionInputs = field(default_factory=AIDecisionInputs)


# ---------------------------------------------------------------------------
# Submit result — return type for the full assemble → submit pipeline
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class SubmitResult:
    """Result of the full ``assemble_and_submit()`` pipeline.

    Tracks the outcome across all phases from AI agent execution through
    to broker submission, enabling the caller to distinguish between
    different failure modes.

    Parameters
    ----------
    status
        One of:
        * ``"SUBMITTED"`` — order was successfully submitted to the broker.
        * ``"SKIPPED"`` — decision was HOLD/WATCH, no order created.
        * ``"REJECTED"`` — broker explicitly rejected the order.
        * ``"RECONCILE_REQUIRED"`` — broker returned uncertain result;
          blocking lock acquired, reconciliation needed.
        * ``"FAILED"`` — translation failure (e.g. HOLD decision skipped).
        * ``"ERROR"`` — unexpected exception during any phase.
    intent
        The ``OrderIntent`` produced by ``assemble()``, if available.
    order
        The ``OrderRequestEntity`` created by ``OrderManager.create_order()``,
        if available (``None`` when creation failed or was skipped).
    error_phase
        Which phase produced the error, for diagnostics:
        ``None`` | ``"ai"`` | ``"decision_save"`` | ``"translation"`` |
        ``"order_create"`` | ``"order_submit"``
    error_message
        Human-readable error detail, if any.
    trade_decision_id
        UUID of the persisted ``TradeDecisionEntity``, if available.
    """

    status: str
    intent: OrderIntent | None = None
    order: OrderRequestEntity | None = None
    error_phase: str | None = None
    error_message: str | None = None
    trade_decision_id: UUID | None = None
    decision_context_id: UUID | None = None


# ---------------------------------------------------------------------------
# Stub score calculator (default when no real calculator is configured)
# ---------------------------------------------------------------------------


class StubScoreCalculator:
    """Default stub implementation of ``ScoreCalculator``.

    Returns a zero-score ``ScoreResult`` with no reason codes.
    This is the fallback when no real calculator is injected.
    """

    async def calculate(self, context: AssembledContext) -> ScoreResult:
        return ScoreResult()


# ---------------------------------------------------------------------------
# Orchestrator service
# ---------------------------------------------------------------------------


def _event_sort_key(e: ExternalEventEntity) -> tuple:
    """Sort key: importance(high=3/medium=2/low=1) → tier(T1=4/T2=3/T3=2/T4=1) → published_at DESC."""
    importance_map: dict[str, int] = {"high": 3, "medium": 2, "low": 1}
    tier_map: dict[str, int] = {"T1": 4, "T2": 3, "T3": 2, "T4": 1}
    imp = importance_map.get(
        (e.metadata or {}).get("importance", "medium"), 2
    )
    tier = tier_map.get(e.source_reliability_tier, 1)
    ts = e.published_at.timestamp() if e.published_at else 0
    return (imp, tier, ts)


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
    ) -> None:
        self._repos = repos
        self._stale_threshold_seconds = stale_threshold_seconds
        self._score_calculator = score_calculator or StubScoreCalculator()
        self._event_interpretation_agent = (
            event_interpretation_agent or StubEventInterpretationAgent()
        )
        self._ai_risk_agent = ai_risk_agent or StubAIRiskAgent()
        self._final_decision_agent = final_decision_agent or StubFinalDecisionComposerAgent()
        self._agent_recorder = agent_recorder or AgentRunRecorder()
        # --- Phase 5.5 ---
        self._sync_service = sync_service
        self._snapshot_refresh_cb = snapshot_refresh_cb

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
            decision_context = await self._resolve_decision_context(
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
            )
            events = list(events)

            # Inject seeded news events as lower-priority supplement
            if seeded_events:
                symbol_seeded = [e for e in seeded_events if e.symbol == request.symbol]
                events.extend(symbol_seeded)

            # Sort: importance desc → T1/T2 first → T3/T4 later → published_at desc
            events.sort(key=_event_sort_key, reverse=True)
            recent_events = tuple(events)
        except Exception:
            pass

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

        # --- Query risk limit snapshot ---
        risk_limit_snapshot: RiskLimitSnapshotEntity | None = None
        if decision_context is not None and decision_context.account_id is not None:
            try:
                risk_limit_snapshot = await self._repos.risk_limit_snapshots.get_latest_by_account(
                    decision_context.account_id
                )
            except Exception:
                pass

        # --- Extract source_type from request metadata (Axis 2) ---
        source_type: str = "core"
        try:
            if request.metadata and isinstance(request.metadata, dict):
                source_type = request.metadata.get("source_type", "core") or "core"
        except Exception:
            pass

        # --- Assemble context (without score yet) ---
        assembled_context = AssembledContext(
            decision_context=decision_context,
            config_version=config_version,
            recent_events=recent_events,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
            source_type=source_type,
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
            source_type=source_type,
        )

        # --- Generate order_intent_id if not provided ---
        resolved_intent_id = order_intent_id or uuid4()

        # --- Generate correlation_id if not provided ---
        correlation_id = request.correlation_id
        if not correlation_id:
            correlation_id = str(uuid4())

        # --- Run AI agents → persistence bundle + normalised backend inputs ---
        agent_bundle = await self._run_agents(
            assembled_context=assembled_context,
            decision_context_id=resolved_context_id,
            correlation_id=correlation_id,
            symbol=request.symbol,
            market=request.market,
        )

        # --- Persist or reuse trade decision when a concrete context exists ---
        trade_decision_id = await self._ensure_trade_decision(
            request=request,
            assembled_context=assembled_context,
            agent_bundle=agent_bundle,
            decision_context_id=resolved_context_id,
        )

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

        return OrderIntent(
            decision_context_id=resolved_context_id,
            order_intent_id=resolved_intent_id,
            request=assembled_request,
            context=assembled_context,
            config_version_id=config_version_id,
            reason_codes=score_result.reason_codes,
            ai_backend_inputs=agent_bundle.ai_inputs,
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
        # ── Phase 1: assemble() ──
        logger.info("Phase 1: assemble() — running AI agents …")
        try:
            intent = await self.assemble(
                request,
                decision_context_id=decision_context_id,
                order_intent_id=order_intent_id,
                seeded_events=seeded_events,
            )
        except Exception as exc:
            logger.exception(
                "Phase 1 FAILED (ai): assemble() raised unexpectedly. "
                "decision_context_id=%s",
                decision_context_id,
            )
            return SubmitResult(
                status="ERROR",
                error_phase="ai",
                error_message=f"assemble() failed: {exc}",
                decision_context_id=decision_context_id,
            )

        # Resolve trade_decision_id from the intent for diagnostics.
        trade_decision_id: UUID | None = None
        if intent.decision_context_id is not None:
            try:
                td = await self._repos.trade_decisions.get_by_context(
                    intent.decision_context_id
                )
                if td is not None:
                    trade_decision_id = td.trade_decision_id
            except Exception:
                pass

        # ── Phase 1.5: deterministic sizing engine ──
        logger.info(
            "Phase 1.5: sizing engine — decision_type=%s side=%s quantity=%s",
            intent.ai_backend_inputs.decision_type,
            intent.request.side,
            intent.request.quantity,
        )
        sizing_inputs = self._build_sizing_inputs(intent)
        sizing_result = calculate_sizing(sizing_inputs)

        logger.info(
            "Sizing Phase 1.5: request_qty=%s sizing_qty=%s "
            "applied_constraints=%s skip_reason=%s",
            intent.request.quantity,
            sizing_result.quantity,
            sizing_result.applied_constraints,
            sizing_result.skip_reason or "none",
        )

        if sizing_result.quantity <= 0:
            logger.info(
                "Phase 1.5 SKIPPED (sizing): reason=%s, trade_decision_id=%s",
                sizing_result.skip_reason,
                trade_decision_id,
            )
            return SubmitResult(
                status="SKIPPED",
                intent=intent,
                trade_decision_id=trade_decision_id,
                decision_context_id=intent.decision_context_id,
                error_phase="sizing",
                error_message=sizing_result.skip_reason or "Sizing rejected order",
            )

        # Log applied constraints
        if sizing_result.applied_constraints:
            logger.info(
                "Phase 1.5: constraints applied=%s sized_quantity=%s",
                sizing_result.applied_constraints,
                sizing_result.quantity,
            )

        # Apply sizing result — override intent request quantity
        if sizing_result.quantity != intent.request.quantity:
            sized_request = replace(intent.request, quantity=sizing_result.quantity)
            intent = replace(intent, request=sized_request)
            logger.info(
                "Phase 1.5: quantity overridden by sizing — original=%s sized=%s",
                intent.request.quantity,
                sizing_result.quantity,
            )

        # ── Phase 2: validate intent (skip HOLD/WATCH) ──
        _dt = intent.ai_backend_inputs.decision_type
        logger.info(
            "Phase 2: validate intent — decision_type=%s",
            _dt,
        )
        submit_request = build_submit_order_request_from_decision(intent)
        if submit_request is None:
            skip_reason = "watch" if _dt == "WATCH" else "hold"
            logger.info(
                "Phase 2 SKIPPED (%s): decision_type=%s, trade_decision_id=%s",
                skip_reason,
                _dt,
                trade_decision_id,
            )
            return SubmitResult(
                status="SKIPPED",
                intent=intent,
                trade_decision_id=trade_decision_id,
                decision_context_id=intent.decision_context_id,
                error_phase="translation",
                error_message=(
                    f"Decision type '{_dt}' "
                    f"produced no order request"
                ),
            )

        # ── Phase 3: OrderManager.create_order() ──
        logger.info(
            "Phase 3: create_order — client_order_id=%s symbol=%s side=%s",
            submit_request.client_order_id,
            submit_request.symbol,
            submit_request.side,
        )
        try:
            order = await order_manager.create_order(
                submit_request,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        except Exception as exc:
            logger.exception(
                "Phase 3 FAILED (order_create): client_order_id=%s",
                submit_request.client_order_id,
            )
            return SubmitResult(
                status="ERROR",
                intent=intent,
                error_phase="order_create",
                error_message=f"create_order() failed: {exc}",
                trade_decision_id=trade_decision_id,
                decision_context_id=intent.decision_context_id,
            )

        # ── Phase 4a: transition DRAFT → VALIDATED ──
        logger.info(
            "Phase 4a: transition_to(VALIDATED) — order_id=%s",
            order.order_request_id,
        )
        try:
            validated_order = await order_manager.transition_to(
                order,
                OrderStatus.VALIDATED,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        except Exception as exc:
            logger.exception(
                "Phase 4a FAILED (order_create): transition to VALIDATED "
                "failed for order_id=%s",
                order.order_request_id,
            )
            return SubmitResult(
                status="ERROR",
                intent=intent,
                order=order,
                error_phase="order_create",
                error_message=f"transition_to(VALIDATED) failed: {exc}",
                trade_decision_id=trade_decision_id,
                decision_context_id=intent.decision_context_id,
            )

        # ── Phase 4b: transition VALIDATED → PENDING_SUBMIT ──
        logger.info(
            "Phase 4b: transition_to(PENDING_SUBMIT) — order_id=%s",
            validated_order.order_request_id,
        )
        try:
            pending_order = await order_manager.transition_to(
                validated_order,
                OrderStatus.PENDING_SUBMIT,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        except Exception as exc:
            logger.exception(
                "Phase 4b FAILED (order_create): transition to PENDING_SUBMIT "
                "failed for order_id=%s",
                validated_order.order_request_id,
            )
            return SubmitResult(
                status="ERROR",
                intent=intent,
                order=validated_order,
                error_phase="order_create",
                error_message=f"transition_to(PENDING_SUBMIT) failed: {exc}",
                trade_decision_id=trade_decision_id,
                decision_context_id=intent.decision_context_id,
            )

        # ── Phase 4c: stale snapshot guard (account-level preferred) ──
        account_id: UUID | None = (
            intent.context.decision_context.account_id
            if intent.context is not None
            and intent.context.decision_context is not None
            else None
        )
        if account_id is not None:
            freshness = await self._check_account_snapshot_freshness(account_id)
            if freshness.is_stale:
                logger.info(
                    "Phase 4c BLOCKED STALE_SNAPSHOT_ACCOUNT: account_id=%s "
                    "cash_stale=%s pos_stale=%s threshold=%ds trade_decision_id=%s",
                    account_id,
                    freshness.is_cash_stale,
                    freshness.is_position_stale,
                    self._stale_threshold_seconds,
                    trade_decision_id,
                )
                try:
                    guardrail_eval = GuardrailEvaluationEntity(
                        guardrail_evaluation_id=uuid4(),
                        decision_context_id=intent.decision_context_id,
                        trade_decision_id=trade_decision_id,
                        order_request_id=pending_order.order_request_id,
                        rule_set_version="stale_snapshot_guard_v1",
                        overall_passed=False,
                        evaluated_at=datetime.now(timezone.utc),
                        rule_results={
                            "is_stale": True,
                            "stale_level": "account",
                            "account_id": str(account_id),
                            "latest_cash_snapshot_at": (
                                str(freshness.latest_cash_snapshot_at)
                                if freshness.latest_cash_snapshot_at
                                else None
                            ),
                            "latest_position_snapshot_at": (
                                str(freshness.latest_position_snapshot_at)
                                if freshness.latest_position_snapshot_at
                                else None
                            ),
                            "is_cash_stale": freshness.is_cash_stale,
                            "is_position_stale": freshness.is_position_stale,
                            "stale_threshold_seconds": self._stale_threshold_seconds,
                        },
                        blocking_rule_codes=["STALE_SNAPSHOT_ACCOUNT"],
                    )
                    await self._repos.guardrail_evaluations.add(guardrail_eval)
                except Exception:
                    logger.warning(
                        "Failed to record guardrail evaluation for stale snapshot (account)",
                        exc_info=True,
                    )

                return SubmitResult(
                    status="SKIPPED",
                    intent=intent,
                    order=pending_order,
                    error_phase="stale_snapshot",
                    error_message=(
                        f"Account-level snapshot stale: account_id={account_id}, "
                        f"cash_stale={freshness.is_cash_stale}, "
                        f"pos_stale={freshness.is_position_stale}, "
                        f"threshold={self._stale_threshold_seconds}s"
                    ),
                    trade_decision_id=trade_decision_id,
                    decision_context_id=intent.decision_context_id,
                )
        else:
            # Fallback: run-level summary
            health = await self._repos.snapshot_sync_runs.get_sync_health_summary(
                stale_threshold_seconds=self._stale_threshold_seconds,
            )
            if health.is_stale:
                logger.info(
                    "Phase 4c BLOCKED stale_snapshot (run-level fallback): "
                    "last_successful_run_at=%s threshold=%ds trade_decision_id=%s",
                    health.last_successful_run_at,
                    self._stale_threshold_seconds,
                    trade_decision_id,
                )
                try:
                    guardrail_eval = GuardrailEvaluationEntity(
                        guardrail_evaluation_id=uuid4(),
                        decision_context_id=intent.decision_context_id,
                        trade_decision_id=trade_decision_id,
                        order_request_id=pending_order.order_request_id,
                        rule_set_version="stale_snapshot_guard_v1",
                        overall_passed=False,
                        evaluated_at=datetime.now(timezone.utc),
                        rule_results={
                            "is_stale": True,
                            "stale_level": "run",
                            "last_successful_run_at": (
                                str(health.last_successful_run_at)
                                if health.last_successful_run_at
                                else None
                            ),
                            "stale_threshold_seconds": self._stale_threshold_seconds,
                            "last_run_status": health.last_status,
                        },
                        blocking_rule_codes=["STALE_SNAPSHOT"],
                    )
                    await self._repos.guardrail_evaluations.add(guardrail_eval)
                except Exception:
                    logger.warning(
                        "Failed to record guardrail evaluation for stale snapshot (run-level)",
                        exc_info=True,
                    )

                return SubmitResult(
                    status="SKIPPED",
                    intent=intent,
                    order=pending_order,
                    error_phase="stale_snapshot",
                    error_message=(
                        f"Snapshot sync is stale (run-level fallback): "
                        f"last successful run at "
                        f"{health.last_successful_run_at}, "
                        f"threshold={self._stale_threshold_seconds}s"
                    ),
                    trade_decision_id=trade_decision_id,
                    decision_context_id=intent.decision_context_id,
                )

        # ── Phase 5: submit to broker ──
        _decision_type: str = "unknown"
        if intent.ai_backend_inputs is not None:
            _decision_type = intent.ai_backend_inputs.decision_type or "unknown"
        logger.info(
            "Phase 5: submit_order_to_broker — order_id=%s broker=%s "
            "symbol=%s decision_type=%s quantity=%s",
            pending_order.order_request_id,
            broker.__class__.__name__,
            submit_request.symbol if hasattr(submit_request, "symbol") else "unknown",
            _decision_type,
            submit_request.quantity if hasattr(submit_request, "quantity") else "unknown",
        )
        try:
            submitted_order = await order_manager.submit_order_to_broker(
                pending_order,
                broker,
                submit_request,
                actor_type=actor_type,
                actor_id=actor_id,
            )
        except Exception as exc:
            logger.exception(
                "Phase 5 FAILED (order_submit): order_id=%s symbol=%s "
                "decision_type=%s trade_decision_id=%s",
                pending_order.order_request_id,
                submit_request.symbol if hasattr(submit_request, "symbol") else "unknown",
                _decision_type,
                trade_decision_id,
            )
            return SubmitResult(
                status="ERROR",
                intent=intent,
                order=pending_order,
                error_phase="order_submit",
                error_message=f"submit_order_to_broker() failed: {exc}",
                trade_decision_id=trade_decision_id,
                decision_context_id=intent.decision_context_id,
            )

        # ── Phase 5.5: post-submit sync (fire-and-forget with timeout) ──
        if (
            submitted_order.status == OrderStatus.SUBMITTED
            and self._sync_service is not None
        ):
            try:
                broker_orders = (
                    await self._repos.broker_orders.list_by_order_request(
                        submitted_order.order_request_id,
                    )
                )
                if broker_orders:
                    bo = broker_orders[0]
                    await asyncio.wait_for(
                        self._sync_service.sync_order_post_submit(
                            account_ref=submit_request.account_ref,
                            broker=broker,
                            broker_order_id=bo.broker_order_id,
                            snapshot_refresh_cb=self._snapshot_refresh_cb,
                        ),
                        timeout=_PHASE55_SYNC_TIMEOUT,
                    )
                    logger.info(
                        "Phase 5.5 sync complete: "
                        "order_id=%s broker_order_id=%s",
                        submitted_order.order_request_id,
                        bo.broker_order_id,
                    )
            except asyncio.TimeoutError:
                logger.warning(
                    "Phase 5.5 sync TIMEOUT (order_id=%s) — "
                    "submit result preserved",
                    submitted_order.order_request_id,
                )
            except Exception as exc:
                logger.warning(
                    "Phase 5.5 sync FAILED (order_id=%s): %s — "
                    "submit result preserved",
                    submitted_order.order_request_id,
                    exc,
                )

        # ── Map final order status to SubmitResult.status ──
        final_status = submitted_order.status
        if final_status == OrderStatus.SUBMITTED:
            result_status = "SUBMITTED"
        elif final_status == OrderStatus.RECONCILE_REQUIRED:
            result_status = "RECONCILE_REQUIRED"
        elif final_status == OrderStatus.REJECTED:
            result_status = "REJECTED"
        else:
            result_status = f"UNEXPECTED:{final_status.value}"

        logger.info(
            "Pipeline complete: status=%s order_id=%s trade_decision_id=%s",
            result_status,
            submitted_order.order_request_id,
            trade_decision_id,
        )
        return SubmitResult(
            status=result_status,
            intent=intent,
            order=submitted_order,
            trade_decision_id=trade_decision_id,
            decision_context_id=intent.decision_context_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_sizing_inputs(self, intent: OrderIntent) -> SizingInputs:
        """Build ``SizingInputs`` from an ``OrderIntent``.

        Extracts position, cash, NAV, and config data from the assembled
        context and maps them to the sizing engine's input format.

        **Key resolution order** (nested ``risk.*`` / ``execution.*`` first,
        then legacy flat key fallback):

        * ``max_single_position_pct`` ← ``risk.max_single_position_pct``
          | ``max_position_size`` (legacy)
        * ``min_cash_buffer_pct``    ← ``risk.min_cash_buffer_pct``
          | ``min_cash_buffer_pct`` (legacy flat)
        * ``max_order_value``        ← ``execution.max_order_value``
          | ``max_order_value`` (legacy flat)
        """
        ctx = intent.context
        ai = intent.ai_backend_inputs
        req = intent.request

        config = ctx.config_version.config_json if ctx.config_version else {}
        risk = config.get("risk", {})
        execution = config.get("execution", {})

        pos_qty = ctx.position_snapshot.quantity if ctx.position_snapshot else None
        pos_avg_price = ctx.position_snapshot.average_price if ctx.position_snapshot else None
        available_cash = ctx.cash_balance_snapshot.available_cash if ctx.cash_balance_snapshot else None
        nav = ctx.risk_limit_snapshot.nav if ctx.risk_limit_snapshot else None
        # Fallback: risk_limit_snapshot이 없으면 cash_balance_snapshot.total_asset을 NAV로 사용
        if nav is None and ctx.cash_balance_snapshot is not None and ctx.cash_balance_snapshot.total_asset is not None:
            nav = ctx.cash_balance_snapshot.total_asset
            logger.warning(
                "risk_limit_snapshot not available; using cash_balance_snapshot.total_asset as NAV fallback. "
                "account_id=%s nav=%s",
                ctx.cash_balance_snapshot.account_id, nav,
            )

        # ── Resolve keys with legacy flat-key fallback ──────────────────
        max_single_position_pct = _decimal_or_none(
            risk.get("max_single_position_pct")
            or config.get("max_position_size")
        )
        min_cash_buffer_pct = _decimal_or_none(
            risk.get("min_cash_buffer_pct")
            or config.get("min_cash_buffer_pct")
        )
        max_order_value = _decimal_or_none(
            execution.get("max_order_value")
            or config.get("max_order_value")
        )

        # ── Operational visibility logging ──────────────────────────────
        max_pct_source = (
            "risk.max_single_position_pct"
            if risk.get("max_single_position_pct")
            else "max_position_size (legacy)"
        )
        cash_buffer_source = (
            "risk.min_cash_buffer_pct"
            if risk.get("min_cash_buffer_pct")
            else "min_cash_buffer_pct (legacy flat)"
        )
        max_ov_source = (
            "execution.max_order_value"
            if execution.get("max_order_value")
            else "max_order_value (legacy flat)"
        )

        logger.info(
            "SizingInputs: max_single_position_pct=%s (src=%s) "
            "min_cash_buffer_pct=%s (src=%s) "
            "max_order_value=%s (src=%s) nav=%s",
            max_single_position_pct, max_pct_source,
            min_cash_buffer_pct, cash_buffer_source,
            max_order_value, max_ov_source,
            nav,
        )

        return SizingInputs(
            decision_type=ai.decision_type,
            side=req.side,
            requested_quantity=req.quantity,
            requested_price=req.price,
            sizing_hint=ai.sizing_hint,
            current_position_qty=pos_qty,
            current_position_avg_price=pos_avg_price,
            available_cash=available_cash,
            nav=nav,
            max_single_position_pct=max_single_position_pct,
            min_cash_buffer_pct=min_cash_buffer_pct,
            max_order_value=max_order_value,
            min_order_qty=_decimal_or_none(execution.get("min_order_qty")),
            max_order_qty=_decimal_or_none(execution.get("max_order_qty")),
        )

    async def _check_account_snapshot_freshness(
        self, account_id: UUID
    ) -> AccountSnapshotFreshness:
        """Check whether a specific account's snapshots are fresh.

        Returns an ``AccountSnapshotFreshness`` summary for the given
        ``account_id``.  Uses the same ``_stale_threshold_seconds`` as the
        run-level summary.

        **Zero-position account policy**: if ``list_latest_by_account()``
        returns an empty list, the positions are considered fresh *iff* a
        cash snapshot exists and is fresh (because the sync function
        fetches cash and positions together).
        """
        now = datetime.now(timezone.utc)

        # 1. Cash snapshot
        cash_snapshot = await self._repos.cash_balance_snapshots.get_latest_by_account(
            account_id
        )
        if cash_snapshot is None:
            return AccountSnapshotFreshness(
                account_id=account_id,
                latest_cash_snapshot_at=None,
                latest_position_snapshot_at=None,
                is_cash_stale=True,
                is_position_stale=True,
                is_stale=True,
            )

        is_cash_stale = (
            now - cash_snapshot.snapshot_at
        ).total_seconds() > self._stale_threshold_seconds

        # 2. Position snapshots
        position_snapshots = (
            await self._repos.position_snapshots.list_latest_by_account(account_id)
        )
        latest_position_snapshot_at: datetime | None = None
        is_position_stale = False

        if position_snapshots:
            latest_position_snapshot_at = max(s.snapshot_at for s in position_snapshots)
            is_position_stale = (
                now - latest_position_snapshot_at
            ).total_seconds() > self._stale_threshold_seconds

        # Zero-position account policy: empty positions + cash fresh = pass
        is_stale = is_cash_stale or is_position_stale
        if is_stale:
            logger.warning(
                "Snapshot freshness check: account_id=%s "
                "cash_stale=%s (snapshot_at=%s, age=%.1fs) "
                "pos_stale=%s (latest_snapshot_at=%s) "
                "threshold=%ds",
                account_id,
                is_cash_stale,
                cash_snapshot.snapshot_at,
                (now - cash_snapshot.snapshot_at).total_seconds(),
                is_position_stale,
                latest_position_snapshot_at,
                self._stale_threshold_seconds,
            )
        return AccountSnapshotFreshness(
            account_id=account_id,
            latest_cash_snapshot_at=cash_snapshot.snapshot_at,
            latest_position_snapshot_at=latest_position_snapshot_at,
            is_cash_stale=is_cash_stale,
            is_position_stale=is_position_stale,
            is_stale=is_stale,
        )

    async def _ensure_or_create_decision_context(
        self,
        request: SubmitOrderRequest,
        existing_context_id: UUID | None,
    ) -> UUID | None:
        """Resolve or create a valid ``decision_context_id`` before agent execution.

        Strategy
        --------
        1. ``existing_context_id``가 제공되면 → DB 존재 여부와 관계없이 그 ID를 반환.
           (caller가 명시적으로 ID를 제공했으므로 책임을 가짐)
        2. ``existing_context_id``가 ``None``이면 → request fields에서 FK chain을
           resolve하여 새 context 생성:
           - ``request.account_ref`` → ``repos.accounts.find_one()`` → ``account_id``
           - ``request.strategy_id`` → ``UUID`` 파싱 → ``strategy_id``
           - ``account.client_id + account.environment`` → ``repos.config_versions.get_active()``
        3. **3개 조건이 모두 충족될 때만** 생성하고, 하나라도 실패하면 ``None`` 반환 (fail-open).

        Returns
        -------
        UUID | None
            유효한 ``decision_context_id`` 또는 ``None`` (생성 불가).
        """
        # Case 1: existing_context_id가 제공됨 → caller가 책임지고 사용
        if existing_context_id is not None:
            return existing_context_id

        # Case 2: request fields에서 FK chain resolution
        try:
            # 조건 1: account_ref → account
            account = await self._repos.accounts.find_one(
                AccountLookup(account_alias=request.account_ref)
            )
            if account is None:
                logger.warning(
                    "Cannot create decision context: account not found for ref=%s",
                    request.account_ref,
                )
                return None

            # 조건 2: strategy_id UUID 파싱
            try:
                strategy_id = UUID(request.strategy_id)
            except (ValueError, AttributeError):
                logger.warning(
                    "Cannot create decision context: invalid strategy_id=%s",
                    request.strategy_id,
                )
                return None

            # 조건 3: client_id + environment → active config version
            config_version = await self._repos.config_versions.get_active(
                client_id=account.client_id,
                environment=account.environment,
            )
            if config_version is None:
                logger.warning(
                    "Cannot create decision context: no active config version "
                    "for client=%s env=%s",
                    account.client_id,
                    account.environment,
                )
                return None

            # Best-effort snapshot anchoring for replayability and agent context.
            # The assemble path can still fall back to latest snapshots, but storing
            # the IDs here makes the exact inputs auditable after the cycle.
            position_snapshot_id: UUID | None = None
            cash_balance_snapshot_id: UUID | None = None
            try:
                instrument = await self._repos.instruments.get_by_symbol(
                    symbol=request.symbol,
                    market_code=request.market,
                )
                if instrument is not None:
                    positions = await self._repos.position_snapshots.list_latest_by_account(
                        account.account_id,
                    )
                    for snapshot in positions:
                        if snapshot.instrument_id == instrument.instrument_id:
                            position_snapshot_id = snapshot.position_snapshot_id
                            break
            except Exception:
                logger.debug(
                    "Unable to anchor latest position snapshot for symbol=%s market=%s",
                    request.symbol,
                    request.market,
                    exc_info=True,
                )

            try:
                cash = await self._repos.cash_balance_snapshots.get_latest_by_account(
                    account.account_id,
                )
                if cash is not None:
                    cash_balance_snapshot_id = cash.cash_balance_snapshot_id
            except Exception:
                logger.debug(
                    "Unable to anchor latest cash balance snapshot for account=%s",
                    account.account_id,
                    exc_info=True,
                )

            # --- 모든 조건 충족 → DecisionContextEntity 생성 ---
            now = datetime.now(timezone.utc)
            context_id = existing_context_id or uuid4()
            correlation_id = request.correlation_id or str(uuid4())

            context = DecisionContextEntity(
                decision_context_id=context_id,
                account_id=account.account_id,
                strategy_id=strategy_id,
                config_version_id=config_version.config_version_id,
                position_snapshot_id=position_snapshot_id,
                cash_balance_snapshot_id=cash_balance_snapshot_id,
                market_timestamp=now,
                correlation_id=correlation_id,
                created_at=now,
            )

            # Savepoint-protected insert: UniqueViolationError 격리
            # PostgreSQL nested connection.transaction() creates a savepoint,
            # so a UniqueViolationError only rolls back the savepoint, not
            # the outer transaction. In-memory UoW has no connection attr.
            try:
                conn = getattr(self._repos.unit_of_work, "connection", None)
                if conn is not None:
                    async with conn.transaction():
                        saved = await self._repos.decision_contexts.add(context)
                else:
                    saved = await self._repos.decision_contexts.add(context)
            except asyncpg.exceptions.UniqueViolationError:
                logger.warning(
                    "correlation_id=%s already exists — savepoint rollback, "
                    "continuing with decision_context_id=None",
                    correlation_id,
                )
                return None

            logger.info(
                "Created decision context: id=%s account_id=%s strategy_id=%s "
                "correlation_id=%s",
                saved.decision_context_id,
                saved.account_id,
                saved.strategy_id,
                saved.correlation_id,
            )
            return saved.decision_context_id

        except Exception:
            logger.warning(
                "Failed to create decision context — agent runs will proceed "
                "without persistence. account_ref=%s",
                request.account_ref,
                exc_info=True,
            )
            return None

    async def _resolve_active_context(self) -> UUID | None:
        """Resolve the most recent active decision context.

        .. note::
           This is a future hook. The current implementation always returns
           ``None`` because ``DecisionContextQuery`` does not yet support a
           ``status`` filter. Once the query model is extended, this method
           should query for active contexts and return the most recent one.

        Returns ``None`` (future hook).
        """
        # Future: query decision_contexts with status="active" filter
        # once DecisionContextQuery supports it.
        return None

    async def _resolve_decision_context(
        self, context_id: UUID
    ) -> DecisionContextEntity | None:
        """Resolve a full ``DecisionContextEntity`` by ID.

        Returns ``None`` if the context is not found or on error.
        """
        try:
            return await self._repos.decision_contexts.get(context_id)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # AI Agent execution
    # ------------------------------------------------------------------

    async def _run_agents(
        self,
        *,
        assembled_context: AssembledContext,
        decision_context_id: UUID | None,
        correlation_id: str,
        symbol: str | None = None,
        market: str | None = None,
    ) -> AgentExecutionBundle:
        """Execute the three v1 Provider AI Agents sequentially.

        Execution order
        ---------------
        1. Event Interpretation Agent
        2. AI Risk Agent
        3. Final Decision Composer

        Each agent receives an ``AgentExecutionRequest`` built from the
        assembled context.  Individual outputs are kept as local variables
        and recorded via ``self._agent_recorder``.

        Returns
        -------
        AIDecisionInputs
            Normalised backend contract aggregating outputs from all three
            agents.  Always returned — even when every agent fails, a
            deterministic default ``AIDecisionInputs()`` is provided.

        Safe-fallback policy
        --------------------
        If any agent raises an exception, a warning is logged and the
        agent's output defaults to an empty / safe structured output.
        The orchestrator **always** proceeds — agent failures never
        block order assembly.

        Per-agent timeout
        -----------------
        Each agent call is wrapped with ``asyncio.wait_for()`` using
        ``_PER_AGENT_TIMEOUT`` (25s).  If an agent hangs beyond this
        limit, ``asyncio.TimeoutError`` is caught separately and the
        agent's output falls back to a safe default — the remaining
        agents still execute normally.
        """
        # --- Build the shared request envelope ---
        request = AgentExecutionRequest(
            decision_context_id=decision_context_id,
            correlation_id=correlation_id,
            context=assembled_context,
            symbol=symbol,
            market=market,
            source_type=assembled_context.source_type,
        )

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
        try:
            event_output = await asyncio.wait_for(
                self._event_interpretation_agent.run(request),
                timeout=_PER_AGENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Event Interpretation Agent timed out after %ds — "
                "using default output (safe fallback). decision_context_id=%s",
                _PER_AGENT_TIMEOUT,
                decision_context_id,
            )
            event_output = EventInterpretationOutput()
        except Exception:
            logger.warning(
                "Event Interpretation Agent failed — using default output "
                "(safe fallback). decision_context_id=%s",
                decision_context_id,
                exc_info=True,
            )
            event_output = EventInterpretationOutput()

        if _is_missing_agent_symbol(event_output.symbol) and symbol:
            event_output = replace(event_output, symbol=symbol)

        await self._agent_recorder.record(
            decision_context_id=decision_context_id,
            agent_type=self._event_interpretation_agent.agent_name,
            structured_output=_dataclass_to_dict(event_output),
        )

        # ── EI top_reason_codes empty detection ─────────────────────
        if (event_output.aggregate_view
                and not event_output.aggregate_view.top_reason_codes
                and event_output.aggregate_view.event_count > 0):
            logger.warning(
                "EI top_reason_codes is empty but event_count=%d "
                "(symbol=%s) — LLM may have omitted the field in aggregation",
                event_output.aggregate_view.event_count, symbol,
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
        try:
            risk_output = await asyncio.wait_for(
                self._ai_risk_agent.run(request_with_ei),
                timeout=_PER_AGENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "AI Risk Agent timed out after %ds — "
                "using default output (safe fallback). decision_context_id=%s",
                _PER_AGENT_TIMEOUT,
                decision_context_id,
            )
            risk_output = AIRiskOutput()
        except Exception:
            logger.warning(
                "AI Risk Agent failed — using default output "
                "(safe fallback). decision_context_id=%s",
                decision_context_id,
                exc_info=True,
            )
            risk_output = AIRiskOutput()

        if _is_missing_agent_symbol(risk_output.symbol) and symbol:
            risk_output = replace(risk_output, symbol=symbol)

        await self._agent_recorder.record(
            decision_context_id=decision_context_id,
            agent_type=self._ai_risk_agent.agent_name,
            structured_output=_dataclass_to_dict(risk_output),
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
        try:
            composer_output = await asyncio.wait_for(
                self._final_decision_agent.run(request_with_ei_and_ar),
                timeout=_PER_AGENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Final Decision Composer Agent timed out after %ds — "
                "using default output (safe fallback). decision_context_id=%s",
                _PER_AGENT_TIMEOUT,
                decision_context_id,
            )
            composer_output = FinalDecisionComposerOutput()
        except Exception:
            logger.warning(
                "Final Decision Composer Agent failed — using default output "
                "(safe fallback). decision_context_id=%s",
                decision_context_id,
                exc_info=True,
            )
            composer_output = FinalDecisionComposerOutput()

        if _is_missing_agent_symbol(composer_output.symbol) and symbol:
            composer_output = replace(composer_output, symbol=symbol)

        await self._agent_recorder.record(
            decision_context_id=decision_context_id,
            agent_type=self._final_decision_agent.agent_name,
            structured_output=_dataclass_to_dict(composer_output),
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
        normalized_dt = _normalize_decision_type(composer_output.decision_type)
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

    async def _ensure_trade_decision(
        self,
        *,
        request: SubmitOrderRequest,
        assembled_context: AssembledContext,
        agent_bundle: AgentExecutionBundle,
        decision_context_id: UUID | None,
    ) -> UUID | None:
        """Persist or reuse a ``TradeDecisionEntity`` for this context.

        This keeps ``trade_decisions`` aligned with the live AI assembly
        path without changing the submit/order/reconciliation boundaries.
        When the orchestrator cannot build a valid entity, it fails open
        and simply omits the trade-decision link from the order path.
        """
        if decision_context_id is None:
            return None

        try:
            existing = await self._repos.trade_decisions.get_by_context(
                decision_context_id
            )
        except Exception:
            logger.warning(
                "Trade decision lookup failed before persistence. "
                "decision_context_id=%s",
                decision_context_id,
                exc_info=True,
            )
            return None

        if existing is not None:
            return existing.trade_decision_id

        decision_context = assembled_context.decision_context
        if decision_context is None:
            return None

        now = datetime.now(timezone.utc)
        composer_output = agent_bundle.composer_output
        ai_inputs = agent_bundle.ai_inputs

        try:
            decision = TradeDecisionEntity(
                trade_decision_id=uuid4(),
                decision_context_id=decision_context_id,
                decision_type=_resolve_decision_type(composer_output.decision_type),
                side=_resolve_order_side(composer_output.side, request.side),
                strategy_id=decision_context.strategy_id,
                symbol=request.symbol,
                market=request.market,
                entry_style=_resolve_entry_style(
                    composer_output.entry_style,
                    request.order_type,
                ),
                created_at=now,
                # --- Axis 2: Source type ---
                source_type=assembled_context.source_type,
                entry_price=_decimal_or_none(request.price),
                quantity=_decimal_or_none(request.quantity),
                max_order_value=_calculate_max_order_value(
                    request.price,
                    request.quantity,
                ),
                confidence=Decimal(str(composer_output.confidence)),
                risk_check_passed=ai_inputs.risk_opinion in {"allow", "reduce"},
                reason_codes=list(composer_output.reason_codes) or None,
                opposing_evidence={
                    "items": [
                        validate_or_normalize_korean(item)
                        for item in composer_output.opposing_evidence
                    ],
                }
                if composer_output.opposing_evidence
                else {},
                exit_plan_json=_dataclass_to_dict(composer_output.exit_plan_hint),
                calculation_version="decision_orchestrator.v1",
                agent_version_json=dict(ai_inputs.schema_versions),
                rationale_summary=validate_or_normalize_korean(
                    composer_output.summary or None
                ),
                decision_json={
                    "decision_type": composer_output.decision_type,
                    "side": composer_output.side,
                    "entry_style": composer_output.entry_style,
                    "time_horizon": composer_output.time_horizon,
                    "event_bias": ai_inputs.event_bias,
                    "event_conflict": ai_inputs.event_conflict,
                    "event_reason_codes": list(ai_inputs.event_reason_codes),
                    "risk_reason_codes": list(ai_inputs.risk_reason_codes),
                    "reason_codes": list(ai_inputs.reason_codes),
                    "opposing_evidence": list(ai_inputs.opposing_evidence),
                    "confidence": ai_inputs.confidence,
                    "conviction": ai_inputs.conviction,
                    "risk_opinion": ai_inputs.risk_opinion,
                    "risk_flags": list(ai_inputs.risk_flags),
                    "execution_preferences": _dataclass_to_dict(
                        composer_output.execution_preferences
                    ),
                    "sizing_hint": _dataclass_to_dict(composer_output.sizing_hint),
                },
            )
            saved = await self._repos.trade_decisions.add(decision)
            return saved.trade_decision_id
        except Exception:
            logger.warning(
                "Trade decision persistence failed. decision_context_id=%s",
                decision_context_id,
                exc_info=True,
            )
            return None


# ---------------------------------------------------------------------------
# Helper: convert a frozen dataclass to a plain dict
# ---------------------------------------------------------------------------


def _dataclass_to_dict(obj: object) -> dict[str, object]:
    """Recursively convert a frozen dataclass to a JSON-compatible dict.

    Handles:
    * Nested dataclasses (recursed into).
    * Tuples of dataclasses (each element recursed).
    * ``UUID`` objects (converted to ``str``).
    * Tuples of ``UUID`` objects (each element converted to ``str``).
    * Plain values (returned as-is).

    The result is suitable for storage in
    ``AgentRunEntity.structured_output_json``.
    """
    if not hasattr(obj, "__dataclass_fields__"):
        return {}
    result: dict[str, object] = {}
    for field_name in obj.__dataclass_fields__:  # type: ignore[arg-type]
        value = getattr(obj, field_name)
        if isinstance(value, UUID):
            result[field_name] = str(value)  # type: ignore[literal-required]
        elif hasattr(value, "__dataclass_fields__"):
            result[field_name] = _dataclass_to_dict(value)  # type: ignore[literal-required]
        elif isinstance(value, tuple):
            result[field_name] = tuple(  # type: ignore[literal-required]
                _dataclass_to_dict(v) if hasattr(v, "__dataclass_fields__")
                else str(v) if isinstance(v, UUID)
                else v
                for v in value
            )
        else:
            result[field_name] = value  # type: ignore[literal-required]
    return result


def _normalize_decision_type(decision_type: str) -> str:
    """Normalize AI output decision_type to canonical backend contract values.

    Maps known drift vocabulary to equivalent canonical values while
    preserving direct matches and existing BUY/SELL handling.

    == Canonical pass-through (그대로 유지) ==
    APPROVE, REJECT, HOLD, WATCH, EXIT, REDUCE
    BUY, SELL  (actionable_types에서 이미 처리 중이므로 보존)

    == Known drift → canonical mapping (대소문자 불변) ==
    entry → APPROVE  (단, side=BUY/SELL이 별도로 존재한다는 전제)
    no_action → HOLD
    no_trade → HOLD
    none → HOLD

    == 대소문자/표기 변형 처리 ==
    - 입력을 strip() + upper()로 정규화 후 매핑
    - ENTRY, entry, Entry → 모두 "ENTRY" → APPROVE
    - NO_TRADE, no_trade, No_Trade → 모두 "NO_TRADE" → HOLD

    == Fallback ==
    Any other unknown value → HOLD (same as existing _resolve_decision_type)
    """
    normalized = decision_type.strip().upper()

    # Direct canonical match — pass through
    if normalized in {
        "APPROVE", "REJECT", "HOLD", "WATCH", "EXIT", "REDUCE",
        "BUY", "SELL",
    }:
        return normalized

    # Known drift vocabulary → canonical mapping
    mapping: dict[str, str] = {
        "ENTRY": "APPROVE",
        "NO_ACTION": "HOLD",
        "NO_TRADE": "HOLD",
        "NONE": "HOLD",
    }
    return mapping.get(normalized, "HOLD")


def _is_missing_agent_symbol(value: str | None) -> bool:
    """Return true when an agent omitted or emitted an unknown symbol."""
    if value is None:
        return True
    normalized = value.strip().upper()
    return normalized in {"", "UNKNOWN", "(NOT AVAILABLE)", "N/A", "NONE", "NULL"}


def _resolve_decision_type(value: str | None) -> DecisionType:
    if not value:
        return DecisionType.HOLD
    try:
        return DecisionType(value.lower())
    except ValueError:
        return DecisionType.HOLD


def _resolve_order_side(value: str | None, fallback: OrderSide) -> OrderSide:
    if value:
        try:
            return OrderSide(value.lower())
        except ValueError:
            pass
    return fallback


def _resolve_entry_style(
    value: str | None,
    fallback_order_type: OrderType,
) -> EntryStyle:
    if value:
        try:
            return EntryStyle(value.lower())
        except ValueError:
            pass

    if fallback_order_type == OrderType.MARKET:
        return EntryStyle.MARKET
    if fallback_order_type == OrderType.LIMIT:
        return EntryStyle.LIMIT
    return EntryStyle.NO_ORDER


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _calculate_max_order_value(
    price: Decimal | None,
    quantity: Decimal,
) -> Decimal | None:
    if price is None:
        return None
    return price * quantity


# ---------------------------------------------------------------------------
# Deterministic translation: OrderIntent → SubmitOrderRequest
# ---------------------------------------------------------------------------


def build_submit_order_request_from_decision(
    intent: OrderIntent,
    client_order_id: str | None = None,
) -> SubmitOrderRequest | None:
    """Translate an ``OrderIntent`` into a ``SubmitOrderRequest`` for broker submission.

    This is the **deterministic backend translation** step.  It validates
    that the AI decision is actionable and constructs a valid submission
    request from the assembled intent.

    Design rules
    ------------
    1. **AI = judgment only, backend = execution**: This function is pure
       deterministic logic — no LLM calls, no AI judgment.
    2. **HOLD / WATCH decisions are skipped**: The function returns ``None``
       when the decision is not actionable.
    3. **No broker semantics change**: The returned ``SubmitOrderRequest``
       preserves all existing fields and does not modify ``SubmitOrderRequest``,
       ``OrderManager``, or ``BrokerAdapter`` boundaries.
    4. **Stateless**: The function does not access repositories, databases,
       or external services.

    Parameters
    ----------
    intent : OrderIntent
        The fully assembled order intent from ``DecisionOrchestratorService``.
    client_order_id : str | None
        Optional explicit client order ID.  When ``None``, a deterministic
        ID is generated from the decision context ID.

    Returns
    -------
    SubmitOrderRequest | None
        A valid submission request, or ``None`` when the decision type
        indicates no order should be submitted (HOLD / WATCH / REDUCE with
        no quantity).
    """
    # ── Decision type check: skip non-actionable decisions ──
    # WATCH is recognised as a valid decision type (it is recorded in
    # trade_decisions) but must NOT produce a submit order request.
    decision_type = intent.ai_backend_inputs.decision_type
    actionable_types = {"APPROVE", "BUY", "SELL", "EXIT", "REDUCE", "WATCH"}
    if decision_type not in actionable_types:
        return None

    # WATCH decisions are monitored but never submitted
    if decision_type == "WATCH":
        logger.info(
            "WATCH decision for symbol=%s — monitoring, order not submitted",
            intent.request.symbol,
        )
        return None

    # ── Quantity validation ──
    if intent.request.quantity <= 0:
        return None

    # ── Generate client_order_id if not provided ──
    resolved_client_order_id: str
    if client_order_id:
        resolved_client_order_id = client_order_id
    elif intent.decision_context_id is not None:
        # Deterministic: "dc-{short_uuid}-{timestamp_suffix}"
        short = str(intent.decision_context_id).split("-")[0]
        ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:10]
        resolved_client_order_id = f"dc-{short}-{ts}"
    else:
        return None

    # ── Build the SubmitOrderRequest from intent.request ──
    # Preserve all fields from the assembled request; the assemble() method
    # has already set decision_id, decision_context_id, order_intent_id, etc.
    return SubmitOrderRequest(
        account_ref=intent.request.account_ref,
        client_order_id=resolved_client_order_id,
        correlation_id=intent.request.correlation_id,
        strategy_id=intent.request.strategy_id,
        symbol=intent.request.symbol,
        market=intent.request.market,
        side=intent.request.side,
        order_type=intent.request.order_type,
        quantity=intent.request.quantity,
        time_in_force=intent.request.time_in_force,
        price=intent.request.price,
        idempotency_key=intent.request.idempotency_key,
        decision_id=intent.request.decision_id,
        decision_context_id=intent.request.decision_context_id,
        order_intent_id=intent.request.order_intent_id,
        price_band_lower=intent.request.price_band_lower,
        price_band_upper=intent.request.price_band_upper,
        max_slippage_bps=intent.request.max_slippage_bps,
        allow_partial_fill=intent.request.allow_partial_fill,
        client_timestamp=intent.request.client_timestamp,
        metadata=intent.request.metadata,
    )
