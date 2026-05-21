"""Structured output schemas for the v1 Provider AI Agent set.

Each dataclass mirrors the JSON schema defined in the design document
(``08_ai_decision_policy.md``, section 4.2).  Stub agents return default
instances; real agents will populate these from Provider API responses.

Schema versioning
-----------------
Every output type carries a ``schema_version`` class attribute so that
downstream consumers (recorder, audit log, replay) can detect format
changes at runtime.  The initial version is ``"v1"``.

Alignment
---------
The three output dataclasses (``EventInterpretationOutput``,
``AIRiskOutput``, ``FinalDecisionComposerOutput``) are aligned with the
JSON schema in the design document.  Nested dataclasses are used for
structured sub-objects (e.g. ``InterpretedEvent``, ``AggregateEventView``,
``ExecutionPreferences``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Shared utility: generate a minimal JSON schema from a dataclass type
# ---------------------------------------------------------------------------


def generate_json_schema(dataclass_type: type) -> dict[str, Any]:
    """Generate a minimal JSON schema for a dataclass type.

    This is used to instruct the LLM on the expected output format.
    Handles ``str``, ``int``, ``float``, ``bool``, ``tuple`` of dataclasses,
    and nested dataclasses.

    .. note::

       This fix addresses the ``from __future__ import annotations`` issue
       where all type annotations are strings at runtime.  By using
       ``typing.get_type_hints()`` we resolve string annotations back to
       their actual types (e.g. ``tuple[InterpretedEvent, ...]`` instead of
       ``"tuple[InterpretedEvent, ...]"``).

       **This is a prompt quality improvement, not a runtime guarantee.**
       Providers may still return malformed JSON.  Runtime defence is
       handled separately by ``__post_init__()`` methods.
    """
    import dataclasses
    import typing

    # Resolve string annotations to actual types (PEP 563 / from __future__)
    try:
        resolved_hints = typing.get_type_hints(dataclass_type)
    except Exception:
        resolved_hints = {}

    fields: dict[str, Any] = {}
    required: list[str] = []

    for f in dataclasses.fields(dataclass_type):
        field_type = resolved_hints.get(f.name, f.type)
        origin = getattr(field_type, "__origin__", None)
        type_name = getattr(field_type, "__name__", str(field_type))

        # Determine JSON type
        if type_name == "str":
            json_type = "string"
        elif type_name == "int":
            json_type = "integer"
        elif type_name == "float":
            json_type = "number"
        elif type_name == "bool":
            json_type = "boolean"
        elif origin is tuple:
            # Tuple of dataclasses — array of objects
            args = getattr(field_type, "__args__", ())
            if args and hasattr(args[0], "__dataclass_fields__"):
                json_type = "array"
                fields[f.name] = {
                    "type": "array",
                    "items": {"$ref": f"#/definitions/{args[0].__name__}"},
                }
                continue
            else:
                json_type = "array"
        elif hasattr(field_type, "__dataclass_fields__"):
            # Nested dataclass
            fields[f.name] = {"$ref": f"#/definitions/{field_type.__name__}"}
            continue
        else:
            json_type = "string"

        fields[f.name] = {"type": json_type}

        # Check if the field has a default — if not, it's required
        default = f.default
        if default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            required.append(f.name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": fields,
    }
    if required:
        schema["required"] = required

    # Build definitions for nested dataclasses (using resolved hints)
    definitions: dict[str, Any] = {}
    for f in dataclasses.fields(dataclass_type):
        field_type = resolved_hints.get(f.name, f.type)
        origin = getattr(field_type, "__origin__", None)
        if origin is tuple:
            args = getattr(field_type, "__args__", ())
            if args and hasattr(args[0], "__dataclass_fields__"):
                nested = args[0]
                if nested.__name__ not in definitions:
                    definitions[nested.__name__] = generate_json_schema(nested)
        elif hasattr(field_type, "__dataclass_fields__"):
            if field_type.__name__ not in definitions:
                definitions[field_type.__name__] = generate_json_schema(field_type)

    if definitions:
        schema["definitions"] = definitions

    return schema


# ============================================================================
# Agent 1. Event Interpretation Agent
# ============================================================================


@dataclass(slots=True, frozen=True)
class InterpretedEvent:
    """A single interpreted event within the Event Interpretation output.

    Corresponds to each item in the ``events[]`` array of the JSON schema
    in ``08_ai_decision_policy.md`` §4.2 Agent 1.

    Parameters
    ----------
    source_event_id
        Original event identifier from the source (e.g. OpenDART receipt
        number).
    event_type
        Classification of the event (e.g. ``"Y|사업보고서 (2023)"``).
    source_name
        Name of the source adapter (e.g. ``"opendart"``).
    source_reliability_tier
        Reliability tier of the source (e.g. ``"T1"``).
    stale
        Whether the event is considered stale per the freshness budget.
    impact_direction
        Perceived impact direction: ``"positive"``, ``"negative"``, or
        ``"neutral"``.
    impact_horizon
        Expected impact horizon: ``"short"``, ``"swing"``, or ``"long"``.
    confidence
        Confidence in this interpretation (0.0 – 1.0).
    novelty
        How novel / surprising the event is: ``"high"``, ``"medium"``,
        or ``"low"``.
    supports_entry
        Whether this event supports entering a new position.
    supports_exit
        Whether this event supports exiting an existing position.
    risk_flags
        Any risk flags raised by this event.
    reason_codes
        Machine-readable reason codes for this interpretation.
    summary
        Human-readable summary of the interpretation.
    """

    source_event_id: str = ""
    event_type: str = ""
    source_name: str = ""
    source_reliability_tier: str = ""
    stale: bool = False
    impact_direction: str = "neutral"
    impact_horizon: str = "swing"
    confidence: float = 0.0
    novelty: str = "medium"
    supports_entry: bool = False
    supports_exit: bool = False
    risk_flags: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    summary: str = ""


@dataclass(slots=True, frozen=True)
class AggregateEventView:
    """Aggregate view across all interpreted events.

    Corresponds to the ``aggregate_view`` object in the JSON schema
    (``08_ai_decision_policy.md`` §4.2 Agent 1).

    Parameters
    ----------
    overall_bias
        Overall directional bias: ``"positive"``, ``"negative"``, or
        ``"neutral"``.
    event_conflict
        Whether there is conflicting evidence across events.
    top_reason_codes
        Most important reason codes across all events.
    opposing_evidence
        Human-readable list of evidence that opposes the overall bias.
    evidence_strength
        Quality/quantity of evidence: ``"none"``, ``"weak"``,
        ``"moderate"``, or ``"strong"``.
    event_count
        Number of material events actually grounded for this symbol.
    no_material_events
        ``True`` when there are no material events to analyze.
    """

    overall_bias: str = "neutral"
    event_conflict: bool = False
    top_reason_codes: tuple[str, ...] = ()
    opposing_evidence: tuple[str, ...] = ()
    # --- Axis 1: Evidence quality fields ---
    evidence_strength: str = "none"
    """Quality/quantity of evidence: ``"none"`` | ``"weak"`` | ``"moderate"`` | ``"strong"``."""
    event_count: int = 0
    """Number of material events actually grounded for this symbol."""
    no_material_events: bool = True
    """``True`` when there are no material events to analyze."""

    def __post_init__(self) -> None:
        _logger = logging.getLogger(self.__class__.__module__)
        if not self.top_reason_codes and self.event_count > 0:
            _logger.warning(
                "AggregateEventView.top_reason_codes is empty but "
                "event_count=%d — LLM may have omitted the field",
                self.event_count,
            )


@dataclass(slots=True, frozen=True)
class EventInterpretationOutput:
    """Structured output of the Event Interpretation Agent.

    Corresponds to the JSON schema in ``08_ai_decision_policy.md`` §4.2
    Agent 1.

    Parameters
    ----------
    schema_version
        Version of the output schema (``"v1"``).
    agent_name
        Agent identifier (``"event_interpretation"``).
    decision_context_id
        UUID of the decision context this output belongs to, as a string
        (or ``None`` if not yet associated).
    symbol
        The trading symbol being evaluated.
    issuer_code
        Issuer / company code for the symbol.
    events
        Ordered tuple of interpreted events.
    aggregate_view
        Aggregate view across all events.
    summary
        Deterministic Korean summary string generated from aggregate_view
        and events (no additional LLM call).
    """

    schema_version: str = "v1"
    agent_name: str = "event_interpretation"
    decision_context_id: str | None = None
    symbol: str = ""
    issuer_code: str = ""
    events: tuple[InterpretedEvent, ...] = ()
    aggregate_view: AggregateEventView = field(default_factory=AggregateEventView)
    summary: str = ""
    """Deterministic Korean summary (no LLM call)."""

    def __post_init__(self) -> None:
        """Coerce malformed fields to safe defaults.

        Some providers (e.g. DeepSeek) may return nested objects as serialised
        JSON strings instead of proper nested JSON objects.  Because
        ``from __future__ import annotations`` makes all type annotations strings
        at runtime, the ``_coerce_nested_json_strings`` helper in
        ``provider_client.py`` may not always resolve the target type correctly.
        This ``__post_init__`` acts as a second line of defence.

        Malformed item policy
        ---------------------
        - ``events`` string → ``()`` empty tuple
        - ``events`` list with invalid items → item-level skip, all fail → ``()``
        - ``aggregate_view`` JSON string → ``json.loads()`` → ``AggregateEventView``
        - ``aggregate_view`` plain string → ``AggregateEventView()`` default
        - ``aggregate_view`` dict with shape mismatch → ``AggregateEventView()`` default
        """
        import json

        # --- aggregate_view 방어 ---
        av = self.aggregate_view
        if isinstance(av, str):
            try:
                parsed = json.loads(av)
                if isinstance(parsed, dict):
                    object.__setattr__(self, "aggregate_view", AggregateEventView(**parsed))
                else:
                    # JSON string but not a dict → default
                    object.__setattr__(self, "aggregate_view", AggregateEventView())
            except (json.JSONDecodeError, TypeError, ValueError):
                # Plain string ("중립적") → default
                object.__setattr__(self, "aggregate_view", AggregateEventView())
        elif isinstance(av, dict) and not isinstance(av, AggregateEventView):
            try:
                object.__setattr__(self, "aggregate_view", AggregateEventView(**av))
            except (TypeError, ValueError):
                # Dict but shape mismatch → default
                object.__setattr__(self, "aggregate_view", AggregateEventView())

        # --- events 방어 ---
        ev = self.events
        if isinstance(ev, str):
            # String events → empty tuple
            object.__setattr__(self, "events", ())
        elif isinstance(ev, (list, tuple)):
            # Item-level skip: keep only valid InterpretedEvent items
            safe: list[InterpretedEvent] = []
            for item in ev:
                if isinstance(item, dict):
                    try:
                        safe.append(InterpretedEvent(**item))
                    except (TypeError, ValueError):
                        pass  # Malformed item — skip
                elif isinstance(item, InterpretedEvent):
                    safe.append(item)
            # If items were removed, replace with filtered tuple
            if len(safe) != len(ev):
                object.__setattr__(self, "events", tuple(safe))


# ============================================================================
# Agent 2. AI Risk Agent
# ============================================================================


@dataclass(slots=True, frozen=True)
class AIRiskOutput:
    """Structured output of the AI Risk Agent.

    Corresponds to the JSON schema in ``08_ai_decision_policy.md`` §4.2
    Agent 2.

    Parameters
    ----------
    schema_version
        Version of the output schema (``"v1"``).
    agent_name
        Agent identifier (``"ai_risk"``).
    decision_context_id
        UUID of the decision context this output belongs to, as a string
        (or ``None`` if not yet associated).
    symbol
        The trading symbol being evaluated.
    proposed_side
        The proposed trade side (``"BUY"`` or ``"SELL"``).
    risk_opinion
        Risk opinion: ``"allow"``, ``"reduce"``, ``"reject"``, or
        ``"review"``.
    risk_score
        Composite risk score (0.0 – 1.0).  Higher = more risky.
    confidence
        Confidence in the risk assessment (0.0 – 1.0).
    size_adjustment_factor
        Recommended size reduction factor (0.0 = no reduction, 0.5 = halve,
        1.0 = zero the position).
    max_holding_horizon
        Maximum recommended holding horizon: ``"short"``, ``"swing"``, or
        ``"long"``.
    risk_flags
        Risk flags raised by the agent.
    reason_codes
        Machine-readable reason codes for the risk opinion.
    opposing_evidence
        Human-readable list of evidence that opposes the risk opinion.
    summary
        Human-readable summary of the risk assessment.
    """

    schema_version: str = "v1"
    agent_name: str = "ai_risk"
    decision_context_id: str | None = None
    symbol: str = ""
    proposed_side: str = ""
    risk_opinion: str = "allow"
    risk_score: float = 0.0
    confidence: float = 0.0
    size_adjustment_factor: float = 0.0
    max_holding_horizon: str = "swing"
    risk_flags: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    opposing_evidence: tuple[str, ...] = ()
    summary: str = ""


# ============================================================================
# Agent 3. Final Decision Composer
# ============================================================================


@dataclass(slots=True, frozen=True)
class PriceBandHint:
    """Price band hint within execution preferences.

    Parameters
    ----------
    reference_type
        Price reference (e.g. ``"last_price"``, ``"vwap"``).
    max_slippage_bps
        Maximum acceptable slippage in basis points.
    """

    reference_type: str = "last_price"
    max_slippage_bps: int = 15


@dataclass(slots=True, frozen=True)
class ExecutionPreferences:
    """Execution preferences for the order.

    Corresponds to the ``execution_preferences`` object in the JSON schema
    (``08_ai_decision_policy.md`` §4.2 Agent 3).

    Parameters
    ----------
    use_limit_order
        Whether to use a limit order (vs. market order).
    price_band_hint
        Price band hint for limit order placement.
    allow_partial_fill
        Whether partial fills are acceptable.
    """

    use_limit_order: bool = True
    price_band_hint: PriceBandHint = field(default_factory=PriceBandHint)
    allow_partial_fill: bool = True


@dataclass(slots=True, frozen=True)
class SizingHint:
    """Sizing hint for the order.

    Corresponds to the ``sizing_hint`` object in the JSON schema
    (``08_ai_decision_policy.md`` §4.2 Agent 3).

    Parameters
    ----------
    size_mode
        Sizing mode: ``"fractional_reduce"``, ``"no_change"``, or
        ``"increase"``.
    size_adjustment_factor
        Fractional adjustment factor (0.0 = no change, 0.5 = reduce by
        half, etc.).
    """

    size_mode: str = "no_change"
    size_adjustment_factor: float = 0.0


@dataclass(slots=True, frozen=True)
class ExitPlanHint:
    """Exit plan hint for the order.

    Corresponds to the ``exit_plan_hint`` object in the JSON schema
    (``08_ai_decision_policy.md`` §4.2 Agent 3).

    Parameters
    ----------
    stop_style
        Stop-loss style (e.g. ``"volatility_based"``, ``"fixed"``).
    take_profit_style
        Take-profit style (e.g. ``"partial_scale_out"``, ``"full"``).
    max_holding_days
        Maximum number of days to hold the position.
    """

    stop_style: str = "volatility_based"
    take_profit_style: str = "partial_scale_out"
    max_holding_days: int = 20


@dataclass(slots=True, frozen=True)
class FinalDecisionComposerOutput:
    """Structured output of the Final Decision Composer.

    Corresponds to the JSON schema in ``08_ai_decision_policy.md`` §4.2
    Agent 3.

    Parameters
    ----------
    schema_version
        Version of the output schema (``"v1"``).
    agent_name
        Agent identifier (``"final_decision_composer"``).
    decision_context_id
        UUID of the decision context this output belongs to, as a string
        (or ``None`` if not yet associated).
    symbol
        The trading symbol being evaluated.
    decision_type
        Final decision type: ``"APPROVE"``, ``"REJECT"``, ``"HOLD"``,
        ``"WATCH"``, ``"EXIT"``, or ``"REDUCE"``.
    side
        Trade side: ``"BUY"`` or ``"SELL"``.
    entry_style
        Entry style (e.g. ``"LIMIT"``, ``"MARKET"``).
    time_horizon
        Expected time horizon: ``"short"``, ``"swing"``, or ``"long"``.
    confidence
        Overall confidence in the decision (0.0 – 1.0).
    conviction
        Strength of conviction (0.0 – 1.0).
    reason_codes
        Machine-readable reason codes for the decision.
    opposing_evidence
        Human-readable list of evidence opposing the decision.
    execution_preferences
        Execution preferences for the order.
    sizing_hint
        Sizing hint for the order.
    exit_plan_hint
        Exit plan hint for the order.
    summary
        Human-readable summary of the decision.
    """

    schema_version: str = "v1"
    agent_name: str = "final_decision_composer"
    decision_context_id: str | None = None
    symbol: str = ""
    decision_type: str = "HOLD"
    side: str = ""
    entry_style: str = ""
    time_horizon: str = "swing"
    confidence: float = 0.0
    conviction: float = 0.0
    reason_codes: tuple[str, ...] = ()
    opposing_evidence: tuple[str, ...] = ()
    execution_preferences: ExecutionPreferences = field(
        default_factory=ExecutionPreferences
    )
    sizing_hint: SizingHint = field(default_factory=SizingHint)
    exit_plan_hint: ExitPlanHint = field(default_factory=ExitPlanHint)
    summary: str = ""
