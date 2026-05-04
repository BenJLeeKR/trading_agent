from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID, uuid4

from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    ExternalEventEntity,
    InstrumentEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
)
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
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
from agent_trading.services.ai_agents.recorder import AgentRunRecorder
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    EventInterpretationOutput,
    ExecutionPreferences,
    FinalDecisionComposerOutput,
    SizingHint,
)

logger = logging.getLogger(__name__)


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
    """

    decision_context: DecisionContextEntity | None = None
    config_version: ConfigVersionEntity | None = None
    recent_events: tuple[ExternalEventEntity, ...] = ()
    score: ScoreResult = field(default_factory=ScoreResult)
    position_snapshot: PositionSnapshotEntity | None = None
    cash_balance_snapshot: CashBalanceSnapshotEntity | None = None
    risk_limit_snapshot: RiskLimitSnapshotEntity | None = None


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
        score_calculator: ScoreCalculator | None = None,
        event_interpretation_agent: ProviderAIAgent | None = None,
        ai_risk_agent: ProviderAIAgent | None = None,
        final_decision_agent: ProviderAIAgent | None = None,
        agent_recorder: AgentRunRecorder | None = None,
    ) -> None:
        self._repos = repos
        self._score_calculator = score_calculator or StubScoreCalculator()
        self._event_interpretation_agent = (
            event_interpretation_agent or StubEventInterpretationAgent()
        )
        self._ai_risk_agent = ai_risk_agent or StubAIRiskAgent()
        self._final_decision_agent = final_decision_agent or StubFinalDecisionComposerAgent()
        self._agent_recorder = agent_recorder or AgentRunRecorder()

    async def assemble(
        self,
        request: SubmitOrderRequest,
        *,
        decision_context_id: UUID | None = None,
        order_intent_id: UUID | None = None,
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

        Returns
        -------
        OrderIntent
            A structured intent with P1 fields and assembled context attached.
        """
        # --- Resolve active decision context ---
        resolved_context_id = decision_context_id
        if resolved_context_id is None:
            resolved_context_id = await self._resolve_active_context()

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
                since=datetime.now(timezone.utc) - timedelta(hours=24),
            )
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

        # --- Assemble context (without score yet) ---
        assembled_context = AssembledContext(
            decision_context=decision_context,
            config_version=config_version,
            recent_events=recent_events,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
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
        )

        # --- Generate order_intent_id if not provided ---
        resolved_intent_id = order_intent_id or uuid4()

        # --- Generate correlation_id if not provided ---
        correlation_id = request.correlation_id
        if not correlation_id:
            correlation_id = str(uuid4())

        # --- Run AI agents → AIDecisionInputs ---
        ai_inputs = await self._run_agents(
            assembled_context=assembled_context,
            decision_context_id=resolved_context_id,
            correlation_id=correlation_id,
        )

        # --- Generate decision_id if not provided ---
        decision_id = request.decision_id
        if not decision_id:
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
            ai_backend_inputs=ai_inputs,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
    ) -> AIDecisionInputs:
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
        """
        # --- Build the shared request envelope ---
        request = AgentExecutionRequest(
            decision_context_id=decision_context_id,
            correlation_id=correlation_id,
            context=assembled_context,
        )

        # --- 1. Event Interpretation Agent ---
        event_output: EventInterpretationOutput
        try:
            event_output = await self._event_interpretation_agent.run(request)
        except Exception:
            logger.warning(
                "Event Interpretation Agent failed — using default output "
                "(safe fallback). decision_context_id=%s",
                decision_context_id,
                exc_info=True,
            )
            event_output = EventInterpretationOutput()

        await self._agent_recorder.record(
            decision_context_id=decision_context_id,
            agent_type=self._event_interpretation_agent.agent_name,
            structured_output=_dataclass_to_dict(event_output),
        )

        # --- Build a new request with the EI output for downstream agents ---
        # AgentExecutionRequest is frozen, so we must create a new instance.
        # When EI fails, event_output is an empty EventInterpretationOutput(),
        # so downstream agents always receive a structured value (never None).
        request_with_ei = AgentExecutionRequest(
            decision_context_id=request.decision_context_id,
            correlation_id=request.correlation_id,
            context=request.context,
            event_interpretation_output=event_output,
            model_id=request.model_id,
            prompt_id=request.prompt_id,
        )

        # --- 2. AI Risk Agent ---
        risk_output: AIRiskOutput
        try:
            risk_output = await self._ai_risk_agent.run(request_with_ei)
        except Exception:
            logger.warning(
                "AI Risk Agent failed — using default output "
                "(safe fallback). decision_context_id=%s",
                decision_context_id,
                exc_info=True,
            )
            risk_output = AIRiskOutput()

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
            event_interpretation_output=event_output,
            ai_risk_output=risk_output,
            model_id=request.model_id,
            prompt_id=request.prompt_id,
        )

        # --- 3. Final Decision Composer Agent ---
        composer_output: FinalDecisionComposerOutput
        try:
            composer_output = await self._final_decision_agent.run(request_with_ei_and_ar)
        except Exception:
            logger.warning(
                "Final Decision Composer Agent failed — using default output "
                "(safe fallback). decision_context_id=%s",
                decision_context_id,
                exc_info=True,
            )
            composer_output = FinalDecisionComposerOutput()

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

        return ai_inputs


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
