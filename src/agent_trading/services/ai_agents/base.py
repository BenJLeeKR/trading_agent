"""Core protocols and request model for the AI Agent execution layer.

This module defines the fundamental abstractions that all v1 Provider AI
Agents conform to:

* ``AgentExecutionRequest`` — the input envelope passed to every agent.
* ``ProviderAIAgent`` — the protocol each agent must satisfy.
* ``AIProviderClient`` — the abstraction over the external Provider SDK
  (e.g. OpenAI, Anthropic) so that agents never call the SDK directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from agent_trading.services.decision_orchestrator import AssembledContext
    from agent_trading.services.ai_agents.schemas import EventInterpretationOutput
    from agent_trading.services.ai_agents.schemas import AIRiskOutput


# ---------------------------------------------------------------------------
# Agent execution request
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class AgentExecutionRequest:
    """Input envelope passed to every ``ProviderAIAgent.run()``.

    Parameters
    ----------
    decision_context_id
        The active decision context ID.  ``None`` when no context could be
        resolved (e.g. first-time order without a prior decision context).
    correlation_id
        Stable correlation identifier that ties together all agent runs
        for a single order intent assembly.
    context
        The fully assembled ``AssembledContext`` (decision context, config
        version, recent events, score).
    symbol
        Trading symbol being evaluated. This is provided explicitly because
        some cycles have no recent events, so downstream agents cannot infer
        the symbol from event provenance alone.
    market
        Market code for ``symbol`` (for example ``"KRX"``).
    event_interpretation_output
        Optional output from the Event Interpretation Agent.  When provided,
        downstream agents (AI Risk, Final Decision Composer) can use the
        interpreted event data to inform their own analysis.
    model_id
        Optional model identifier (e.g. ``"gpt-4o"``).  Stub agents ignore
        this; real agents will use it to select the model.
    prompt_id
        Optional prompt template identifier.  Stub agents ignore this;
        real agents will use it to select the system/user prompt.
    source_type
        Origin of this symbol in the trading universe:
        ``"core"`` | ``"held_position"`` | ``"event_overlay"`` | ``"market_overlay"``.
        Used by FDC to differentiate no-event policy per source type.
    """

    decision_context_id: UUID | None
    correlation_id: str
    context: AssembledContext
    symbol: str | None = None
    market: str | None = None
    event_interpretation_output: EventInterpretationOutput | None = None
    ai_risk_output: AIRiskOutput | None = None
    model_id: str | None = None
    prompt_id: str | None = None
    # --- Axis 2: Source type for no-event policy differentiation ---
    source_type: str = "core"
    """Origin of this symbol: ``"core"`` | ``"held_position"`` | ``"event_overlay"`` | ``"market_overlay"``."""


# ---------------------------------------------------------------------------
# Provider AI Agent protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ProviderAIAgent(Protocol):
    """Protocol that every v1 Provider AI Agent must satisfy.

    Each agent has a human-readable ``agent_name``, a ``schema_version``
    string for output compatibility checks, and a single ``run()`` method
    that accepts an ``AgentExecutionRequest`` and returns a structured
    output object (defined in ``schemas.py``).
    """

    @property
    def agent_name(self) -> str:
        """Human-readable agent identifier (e.g. ``"event_interpretation"``)."""
        ...

    @property
    def schema_version(self) -> str:
        """Semantic version of the agent's output schema (e.g. ``"1.0.0"``)."""
        ...

    async def run(self, request: AgentExecutionRequest) -> object:
        """Execute the agent and return a structured output.

        Parameters
        ----------
        request : AgentExecutionRequest
            The input envelope containing the decision context, assembled
            context, and optional model/prompt identifiers.

        Returns
        -------
        object
            A structured output dataclass defined in ``schemas.py``.
            The exact type depends on the agent:
            * ``EventInterpretationOutput`` for the Event Interpretation Agent.
            * ``AIRiskOutput`` for the AI Risk Agent.
            * ``FinalDecisionComposerOutput`` for the Final Decision Composer.
        """
        ...


# ---------------------------------------------------------------------------
# Raw provider response wrapper
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class RawProviderResponse:
    """Wrapper for a parsed structured output together with the raw content.

    Parameters
    ----------
    parsed
        The parsed dataclass instance (e.g. ``EventInterpretationOutput``).
    raw_content
        The raw JSON string returned by the provider.
    """

    parsed: object
    raw_content: str


# ---------------------------------------------------------------------------
# AI Provider Client protocol (abstraction over external SDK)
# ---------------------------------------------------------------------------


@runtime_checkable
class AIProviderClient(Protocol):
    """Abstraction over the external Provider SDK (OpenAI, Anthropic, …).

    Agents **never** call the Provider SDK directly.  Instead they receive
    an ``AIProviderClient`` instance that exposes a single high-level
    ``generate_structured()`` method.  This keeps the agent code testable
    and provider-agnostic.

    The stub implementation (used in this milestone) returns a fixed /
    default response.  The real implementation will be wired in a later
    milestone when actual Provider API calls are introduced.
    """

    async def generate_structured(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        response_format: type,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> RawProviderResponse:
        """Send a prompt to the Provider and return a structured response.

        Parameters
        ----------
        model_id : str
            The model identifier (e.g. ``"gpt-4o"``, ``"claude-3-opus"``).
        system_prompt : str
            The system-level instruction for the model.
        user_prompt : str
            The user / context prompt.
        response_format : type
            A dataclass type that the response should conform to.
            The implementation is responsible for parsing the Provider's
            response into an instance of this type.
        temperature : float
            Sampling temperature (default ``0.0`` for deterministic output).
        seed : int | None
            Optional seed for reproducible sampling.

        Returns
        -------
        RawProviderResponse
            A wrapper containing both the parsed dataclass instance and the
            raw JSON string from the provider.
        """
        ...
