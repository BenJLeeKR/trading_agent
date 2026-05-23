"""Deterministic backend translation — OrderIntent → SubmitOrderRequest (or None).

This module contains **pure transformation functions only**.  Design rules:

1. **No repository access** — no DB queries, no async repo calls.
2. **No logger** — no logging side effects; callers log if needed.
3. **No settings** — no config, env vars, or runtime context.
4. **No domain entity imports** — only ``SubmitOrderRequest`` (API model) and
   ``OrderIntent`` (local dataclass).
5. **No AI agent references** — this is deterministic backend logic.

The sole function ``build_submit_order_request_from_decision()`` translates an
``OrderIntent`` produced by ``DecisionOrchestratorService.assemble()`` into a
``SubmitOrderRequest`` that can be passed to ``OrderManager.create_order()``.
When the decision type is non-actionable (HOLD, WATCH, or an unrecognised type),
or the quantity is zero/negative, the function returns ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.services.ai_agents.schemas import (
    ExecutionPreferences,
    SizingHint,
)

if TYPE_CHECKING:
    from agent_trading.domain.entities import (
        CashBalanceSnapshotEntity,
        ConfigVersionEntity,
        DecisionContextEntity,
        ExternalEventEntity,
        PositionSnapshotEntity,
        RiskLimitSnapshotEntity,
    )

__all__ = [
    "AIDecisionInputs",
    "AssembledContext",
    "OrderIntent",
    "ScoreResult",
    "build_submit_order_request_from_decision",
]


# ---------------------------------------------------------------------------
# Scoring result (stub)
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


# ---------------------------------------------------------------------------
# Normalised AI decision inputs
# ---------------------------------------------------------------------------


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

    # ── Metadata ─────────────────────────────────────────────────────
    source_agent_names: tuple[str, ...] = ()
    schema_versions: tuple[tuple[str, str], ...] = ()


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
# Order intent — the interface between decision pipeline and translation
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
# Pure translation function
# ---------------------------------------------------------------------------


def build_submit_order_request_from_decision(
    intent: OrderIntent,
    client_order_id: str | None = None,
) -> SubmitOrderRequest | None:
    """Translate an ``OrderIntent`` into a ``SubmitOrderRequest`` for broker submission.

    This is the **deterministic backend translation** step.  It validates
    that the AI decision is actionable and constructs a valid submission
    request from the assembled intent.

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
    decision_type = intent.ai_backend_inputs.decision_type
    actionable_types = {"APPROVE", "BUY", "SELL", "EXIT", "REDUCE", "WATCH"}
    if decision_type not in actionable_types:
        return None

    # WATCH decisions are monitored but never submitted.
    # (Caller is responsible for any logging.)
    if decision_type == "WATCH":
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
