from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID, uuid4

from agent_trading.domain.entities import (
    ConfigVersionEntity,
    DecisionContextEntity,
    ExternalEventEntity,
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
    FinalDecisionComposerOutput,
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
    recent external events, and a deterministic score.

    All fields are optional — the service assembles what it can and
    leaves missing pieces as ``None`` or empty.
    """

    decision_context: DecisionContextEntity | None = None
    config_version: ConfigVersionEntity | None = None
    recent_events: tuple[ExternalEventEntity, ...] = ()
    score: ScoreResult = field(default_factory=ScoreResult)


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
    * ``OrderIntent`` is **not** modified — agent outputs are accessible
      via the recorder.
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

        # --- Assemble context (without score yet) ---
        assembled_context = AssembledContext(
            decision_context=decision_context,
            config_version=config_version,
            recent_events=recent_events,
        )

        # --- Calculate score ---
        score_result = await self._score_calculator.calculate(assembled_context)

        # --- Rebuild context with score ---
        assembled_context = AssembledContext(
            decision_context=decision_context,
            config_version=config_version,
            recent_events=recent_events,
            score=score_result,
        )

        # --- Generate order_intent_id if not provided ---
        resolved_intent_id = order_intent_id or uuid4()

        # --- Generate correlation_id if not provided ---
        correlation_id = request.correlation_id
        if not correlation_id:
            correlation_id = str(uuid4())

        # --- Run AI agents (stub — no actual Provider calls) ---
        await self._run_agents(
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
    ) -> None:
        """Execute the three v1 Provider AI Agents sequentially.

        Execution order
        ---------------
        1. Event Interpretation Agent
        2. AI Risk Agent
        3. Final Decision Composer

        Each agent receives an ``AgentExecutionRequest`` built from the
        assembled context.  Individual outputs are kept as local variables
        and recorded via ``self._agent_recorder``.

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

        # --- 2. AI Risk Agent ---
        risk_output: AIRiskOutput
        try:
            risk_output = await self._ai_risk_agent.run(request)
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

        # --- 3. Final Decision Composer Agent ---
        composer_output: FinalDecisionComposerOutput
        try:
            composer_output = await self._final_decision_agent.run(request)
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
