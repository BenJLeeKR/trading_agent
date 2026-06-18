"""Shared data types between decision pipeline and execution pipeline.

Design rules
------------
1. Pure dataclasses only — no logic, no side effects.
2. No repository access, no async code.
3. No AI agent references beyond ``services/ai_agents/schemas.py``.
"""

from __future__ import annotations

import dataclasses
import typing
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    ExternalEventEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
    SignalFeatureSnapshotEntity,
)
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    EventInterpretationOutput,
    ExecutionPreferences,
    FinalDecisionComposerOutput,
    SizingHint,
)
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)
from agent_trading.services.market_regime import MarketRegimeAssessment
from agent_trading.services.portfolio_allocation import PortfolioAllocationAssessment
from agent_trading.services.sizing_engine import SizingResult
from agent_trading.services.strategy_selection import StrategySelectionAssessment


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
    side: str = ""  # FDC에서 결정된 side (buy/sell)

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
    evidence_strength: str = "none"
    no_material_events: bool = True
    detected_event_count: int = 0
    interpreted_event_count: int = 0

    # ── Metadata ─────────────────────────────────────────────────────
    source_agent_names: tuple[str, ...] = ()
    schema_versions: tuple[tuple[str, str], ...] = ()
    ei_skipped: bool = False
    ar_skipped: bool = False
    fdc_skipped: bool = False
    skip_reason_codes: tuple[str, ...] = ()


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
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None = None
    market_regime: MarketRegimeAssessment | None = None
    strategy_selection: StrategySelectionAssessment | None = None
    portfolio_allocation: PortfolioAllocationAssessment | None = None
    deterministic_trigger: DeterministicTriggerAssessment | None = None
    # --- Axis 2: Source type for no-event policy differentiation ---
    source_type: str = "core"
    """Origin of this symbol: ``"core"`` | ``"held_position"`` | ``"event_overlay"`` | ``"market_overlay"``."""


@dataclass(slots=True, frozen=True)
class AIPolicyContextView:
    """AI Policy Stage 전용 입력 뷰.

    내부 조립용 ``AssembledContext`` 전체를 그대로 AI에 넘기지 않고,
    실제 프롬프트/에이전트 판단에 필요한 읽기 전용 필드만 분리한다.
    """

    decision_context: DecisionContextEntity | None = None
    recent_events: tuple[ExternalEventEntity, ...] = ()
    score: ScoreResult = field(default_factory=ScoreResult)
    position_snapshot: PositionSnapshotEntity | None = None
    cash_balance_snapshot: CashBalanceSnapshotEntity | None = None
    risk_limit_snapshot: RiskLimitSnapshotEntity | None = None
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None = None
    market_regime: MarketRegimeAssessment | None = None
    strategy_selection: StrategySelectionAssessment | None = None
    portfolio_allocation: PortfolioAllocationAssessment | None = None
    deterministic_trigger: DeterministicTriggerAssessment | None = None
    source_type: str = "core"


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
    # --- Trade decision ID (set by DecisionOrchestratorService.assemble()) ---
    trade_decision_id: UUID | None = None


# ---------------------------------------------------------------------------
# Phase trace entry
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class PhaseTraceEntry:
    phase: str
    elapsed_ms: int | None = None
    status: str = ""


# ---------------------------------------------------------------------------
# Submit result
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class SubmitResult:
    """Result of a single order submission attempt.

    ``order_intent`` carries the full intent object.
    ``status``, ``error_phase``, ``decision_context_id`` are the
    primary script/test interface fields.
    """

    # ── Execution pipeline interface ──────────────────────────────────
    order_intent: OrderIntent | None = None
    phase_trace: tuple[PhaseTraceEntry, ...] = ()
    sizing_result: SizingResult | None = None
    submit_response: object | None = None
    error_message: str | None = None
    is_submitted: bool = False
    is_skipped: bool = False
    trade_decision_id: str | None = None
    stop_reason: str | None = None

    # ── Decision pipeline / script interface ──────────────────────────
    status: str = ""
    error_phase: str | None = None
    decision_context_id: UUID | None = None

    @classmethod
    def build(
        cls,
        order_intent: OrderIntent | None = None,
        phase_trace: tuple[PhaseTraceEntry, ...] = (),
        sizing_result: SizingResult | None = None,
        submit_response: object | None = None,
        error_message: str | None = None,
        is_submitted: bool = False,
        is_skipped: bool = False,
        trade_decision_id: str | None = None,
        stop_reason: str | None = None,
        status: str = "",
        error_phase: str | None = None,
        decision_context_id: UUID | None = None,
    ) -> SubmitResult:
        """Build a ``SubmitResult``.

        ``status``, ``error_phase``, ``decision_context_id`` are
        forwarded directly from the primary fields when not explicitly provided.
        """
        # Derive decision_context_id from order_intent when not provided
        if not decision_context_id and order_intent is not None:
            decision_context_id = order_intent.decision_context_id
        return cls(
            order_intent=order_intent,
            phase_trace=phase_trace,
            sizing_result=sizing_result,
            submit_response=submit_response,
            error_message=error_message,
            is_submitted=is_submitted,
            is_skipped=is_skipped,
            trade_decision_id=trade_decision_id,
            stop_reason=stop_reason,
            status=status,
            error_phase=error_phase,
            decision_context_id=decision_context_id,
        )


# ---------------------------------------------------------------------------
# Account snapshot freshness
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class AccountSnapshotFreshness:
    """Freshness summary for account snapshots.

    Used by both the execution pipeline (rich check with per-resource
    staleness) and the decision pipeline (simple stale/not-stale flag).
    """

    # ── Simple consumer fields (decision pipeline) ────────────────────
    is_stale: bool = False
    position_age_seconds: float | None = None
    cash_age_seconds: float | None = None
    warning: str | None = None
    last_position_sync_at: datetime | None = None
    last_cash_sync_at: datetime | None = None

    # ── Execution-specific fields (execution pipeline) ────────────────
    account_id: UUID | None = None
    latest_cash_snapshot_at: datetime | None = None
    latest_position_snapshot_at: datetime | None = None
    is_cash_stale: bool = False
    is_position_stale: bool = False


# ---------------------------------------------------------------------------
# Agent execution bundle
# ---------------------------------------------------------------------------


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
    # subprocess isolation 경로에서 EI 실패 시 error metadata
    # (orchestrator가 structured_output_json["__error__"] 주입에 사용)
    ei_error_metadata: dict[str, object] | None = None


# ---------------------------------------------------------------------------
# ScoreCalculator Protocol + StubScoreCalculator
# ---------------------------------------------------------------------------


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


class StubScoreCalculator:
    """Default stub implementation of ``ScoreCalculator``.

    Returns a zero-score ``ScoreResult`` with no reason codes.
    This is the fallback when no real calculator is injected.
    """

    async def calculate(self, context: AssembledContext) -> ScoreResult:
        return ScoreResult()


# ---------------------------------------------------------------------------
# Event sort key helper
# ---------------------------------------------------------------------------


def event_sort_key(e: ExternalEventEntity) -> tuple:
    """Sort key: importance(high=3/medium=2/low=1) → tier(T1=4/T2=3/T3=2/T4=1) → published_at DESC."""
    importance_map: dict[str, int] = {"high": 3, "medium": 2, "low": 1}
    tier_map: dict[str, int] = {"T1": 4, "T2": 3, "T3": 2, "T4": 1}
    imp = importance_map.get(
        (e.metadata or {}).get("importance", "medium"), 2
    )
    tier = tier_map.get(e.source_reliability_tier, 1)
    ts = e.published_at.timestamp() if e.published_at else 0
    return (imp, tier, ts)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def phase_trace_to_dicts(trace: tuple[PhaseTraceEntry, ...]) -> list[dict[str, object]]:
    return [dataclasses.asdict(t) for t in trace]


def dataclass_to_dict(obj: object) -> dict[str, object]:
    """Recursively convert a frozen dataclass to a JSON-compatible dict.

    Handles:
    * Nested dataclasses (recursed into).
    * Tuples of dataclasses (each element recursed).
    * ``UUID`` objects (converted to ``str``).
    * Tuples of ``UUID`` objects (each element converted to ``str``).
    * Plain values (returned as-is).

    The result is suitable for storage in
    ``AgentRunEntity.structured_output_json``.

    Moved from ``decision_orchestrator._dataclass_to_dict``.
    """
    if not hasattr(obj, "__dataclass_fields__"):
        return {}
    result: dict[str, object] = {}
    for field_name in obj.__dataclass_fields__:  # type: ignore[arg-type]
        value = getattr(obj, field_name)
        if isinstance(value, UUID):
            result[field_name] = str(value)  # type: ignore[literal-required]
        elif hasattr(value, "__dataclass_fields__"):
            result[field_name] = dataclass_to_dict(value)  # type: ignore[literal-required]
        elif isinstance(value, tuple):
            result[field_name] = tuple(  # type: ignore[literal-required]
                dataclass_to_dict(v) if hasattr(v, "__dataclass_fields__")
                else str(v) if isinstance(v, UUID)
                else v
                for v in value
            )
        else:
            result[field_name] = value  # type: ignore[literal-required]
    return result


def dict_to_dataclass(data: dict[str, Any], cls: type) -> Any:
    """Convert a JSON-safe dict back into a dataclass instance.

    Handles nested dataclasses and tuples of dataclasses by recursing
    into fields that are themselves dataclasses.  Unknown fields are
    silently ignored (forward-compatible with schema additions).

    Moved from ``subprocess_helpers._dict_to_dataclass`` (private → public).
    """
    if not data:
        return cls()

    # Resolve string annotations to actual types (PEP 563)
    try:
        resolved_hints = typing.get_type_hints(cls)
    except Exception:
        resolved_hints = {}

    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        field_type = resolved_hints.get(f.name, f.type)
        origin = getattr(field_type, "__origin__", None)

        if value is None:
            kwargs[f.name] = None
        elif hasattr(field_type, "__dataclass_fields__"):
            # Nested dataclass
            if isinstance(value, dict):
                kwargs[f.name] = dict_to_dataclass(value, field_type)
            else:
                kwargs[f.name] = value
        elif origin is tuple:
            # Tuple of dataclasses
            args = getattr(field_type, "__args__", ())
            if args and hasattr(args[0], "__dataclass_fields__") and isinstance(value, (list, tuple)):
                kwargs[f.name] = tuple(
                    dict_to_dataclass(item, args[0]) if isinstance(item, dict) else item
                    for item in value
                )
            else:
                kwargs[f.name] = tuple(value) if isinstance(value, (list, tuple)) else value
        elif isinstance(value, (list, tuple)) and not isinstance(value, str):
            # Plain tuple (e.g. tuple[str, ...])
            kwargs[f.name] = tuple(value)
        else:
            kwargs[f.name] = value

    return cls(**kwargs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "ScoreResult",
    "AIDecisionInputs",
    "AssembledContext",
    "OrderIntent",
    "PhaseTraceEntry",
    "SubmitResult",
    "AccountSnapshotFreshness",
    "AgentExecutionBundle",
    "ScoreCalculator",
    "StubScoreCalculator",
    "event_sort_key",
    "dataclass_to_dict",
    "dict_to_dataclass",
    "phase_trace_to_dicts",
]
