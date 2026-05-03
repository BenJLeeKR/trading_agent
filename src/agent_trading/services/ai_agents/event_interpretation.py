"""Event Interpretation Agent — stub and real implementations.

This agent interprets recent external events and produces a structured
``EventInterpretationOutput``.

* ``StubEventInterpretationAgent`` — always returns default / empty values
  (no actual Provider API call).
* ``EventInterpretationAgent`` — calls a real Provider via
  ``AIProviderClient``.

Safe-fallback policy
--------------------
If an unexpected exception occurs during ``run()``, the agent logs a
warning and returns a default ``EventInterpretationOutput``.  This
ensures that the calling orchestrator can always proceed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent_trading.services.ai_agents.base import (
    AIProviderClient,
    AgentExecutionRequest,
    ProviderAIAgent,
    RawProviderResponse,
)
from agent_trading.services.ai_agents.schemas import (
    EventInterpretationOutput,
    InterpretedEvent,
    AggregateEventView,
    generate_json_schema,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stub (existing, unchanged)
# ---------------------------------------------------------------------------


class StubEventInterpretationAgent:
    """Stub Event Interpretation Agent — returns default output.

    This agent conforms to the ``ProviderAIAgent`` protocol.

    Parameters
    ----------
    schema_version
        Version string reported via the ``schema_version`` property.
    """

    def __init__(self, schema_version: str = "v1") -> None:
        self._schema_version = schema_version

    @property
    def agent_name(self) -> str:
        return "event_interpretation"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(self, request: AgentExecutionRequest) -> EventInterpretationOutput:
        """Execute the agent and return a structured output.

        The stub implementation:
        * Logs the request for observability.
        * Returns a default ``EventInterpretationOutput``.

        Safe fallback: any exception is caught, a warning is logged, and
        a default output is returned.
        """
        logger.debug(
            "StubEventInterpretationAgent.run() called: "
            "decision_context_id=%s correlation_id=%s",
            request.decision_context_id,
            request.correlation_id,
        )

        try:
            # --- Stub: no actual Provider call ---
            return EventInterpretationOutput()
        except Exception:
            logger.warning(
                "StubEventInterpretationAgent.run() failed — "
                "returning default output (safe fallback).",
                exc_info=True,
            )
            return EventInterpretationOutput()


# ---------------------------------------------------------------------------
# Real implementation
# ---------------------------------------------------------------------------


class EventInterpretationAgent:
    """Real Event Interpretation Agent — calls a Provider via AIProviderClient.

    Conforms to the ``ProviderAIAgent`` protocol.

    Parameters
    ----------
    provider_client
        The ``AIProviderClient`` instance used to call the external Provider.
    model_id
        The model identifier (e.g. ``"deepseek-chat"``).
    schema_version
        Version string reported via the ``schema_version`` property.
    """

    def __init__(
        self,
        provider_client: AIProviderClient,
        *,
        model_id: str = "deepseek-chat",
        schema_version: str = "v1",
    ) -> None:
        self._provider = provider_client
        self._model_id = model_id
        self._schema_version = schema_version

    @property
    def agent_name(self) -> str:
        return "event_interpretation"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(
        self, request: AgentExecutionRequest
    ) -> EventInterpretationOutput:
        """Execute the agent and return a structured output.

        Builds a system prompt with the expected JSON schema, sends the
        request context to the Provider, parses the response, and returns
        a validated ``EventInterpretationOutput``.

        Safe fallback: any exception is caught, a warning is logged, and
        a default output is returned.
        """
        logger.debug(
            "EventInterpretationAgent.run() called: "
            "decision_context_id=%s correlation_id=%s model_id=%s",
            request.decision_context_id,
            request.correlation_id,
            self._model_id,
        )

        try:
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_user_prompt(request)

            raw_response: RawProviderResponse = await self._provider.generate_structured(
                model_id=self._model_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=EventInterpretationOutput,
            )

            result: EventInterpretationOutput = raw_response.parsed  # type: ignore[assignment]

            # Override metadata fields from request / agent identity
            result = EventInterpretationOutput(
                schema_version=result.schema_version or self._schema_version,
                agent_name=result.agent_name or self.agent_name,
                decision_context_id=(
                    str(request.decision_context_id)
                    if request.decision_context_id
                    else None
                ),
                symbol=result.symbol,
                issuer_code=result.issuer_code,
                events=result.events,
                aggregate_view=result.aggregate_view,
            )

            logger.info(
                "EventInterpretationAgent succeeded: "
                "symbol=%s events=%d",
                result.symbol,
                len(result.events),
            )
            return result

        except Exception:
            logger.warning(
                "EventInterpretationAgent failed — returning default output "
                "(safe fallback). decision_context_id=%s",
                request.decision_context_id,
                exc_info=True,
            )
            return EventInterpretationOutput()

    def _build_system_prompt(self) -> str:
        """Build the system prompt describing the expected output schema."""
        schema_json = json.dumps(
            generate_json_schema(EventInterpretationOutput), indent=2
        )
        return (
            "You are an Event Interpretation Agent for a trading system. "
            "Analyze the following external events and produce a structured "
            "interpretation output.\n\n"
            "Output must be valid JSON matching this schema:\n"
            f"{schema_json}"
        )

    def _build_user_prompt(self, request: AgentExecutionRequest) -> str:
        """Build the user prompt with the current request context."""
        context = request.context
        score = context.score
        events = context.recent_events or []

        lines: list[str] = [
            f"Correlation ID: {request.correlation_id}",
        ]

        if score:
            lines.append(f"Score: {score.score} (threshold: {score.threshold})")
            if score.reason_codes:
                lines.append(f"Reason codes: {', '.join(score.reason_codes)}")

        lines.append(f"Recent events ({len(events)}):")
        for e in events[:20]:
            headline = e.headline or "(no headline)"
            summary = e.body_summary or ""
            lines.append(
                f"  - [{e.event_type}] {headline}"
                f"{' — ' + summary[:200] if summary else ''}"
            )

        return "\n".join(lines)
