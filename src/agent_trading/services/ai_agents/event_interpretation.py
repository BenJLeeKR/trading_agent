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
from datetime import datetime, timezone
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
        The model identifier (e.g. ``"deepseek-v4-pro"``).
    schema_version
        Version string reported via the ``schema_version`` property.
    """

    def __init__(
        self,
        provider_client: AIProviderClient,
        *,
        model_id: str = "deepseek-v4-pro",
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
            f"{schema_json}\n\n"
            "## Evidence Strength Classification\n"
            "Set evidence_strength based on the number and quality of events:\n"
            "- 'none': No material events found for this symbol.\n"
            "- 'weak': 1-2 events available, low or medium importance only.\n"
            "- 'moderate': 2+ events available, may include high importance.\n"
            "- 'strong': 3+ events, multiple high-importance, consistent direction.\n\n"
            "Set no_material_events=True if event_count == 0.\n"
            "Set event_count to the actual count of events provided.\n"
            "IMPORTANT: 'lack of evidence' is NOT the same as 'negative signal'. "
            "When there are no events, set overall_bias='neutral' and "
            "evidence_strength='none' — do NOT infer a negative bias from absence.\n\n"
            "top_reason_codes: A tuple of the most important reason codes "
            "aggregated across all events. Extract the top 3-5 reason codes "
            "from the individual event reason_codes. When events exist and "
            "no_material_events is False, this MUST contain at least one "
            "reason code. When no_material_events is True, this MUST be empty.\n\n"
            "Language requirement: All human-readable narrative fields "
            "(summary, opposing_evidence) MUST be written in Korean. "
            "Machine-readable fields (reason_codes, event_type, impact_direction, "
            "source_name, etc.) MUST remain in English."
        )

    def _build_user_prompt(self, request: AgentExecutionRequest) -> str:
        """Build the user prompt with provenance-rich event context."""
        context = request.context
        score = context.score
        events = context.recent_events or []
        now = datetime.now(timezone.utc)

        lines: list[str] = [
            f"Correlation ID: {request.correlation_id}",
        ]
        if request.symbol:
            lines.append(f"Symbol: {request.symbol}")
        if request.market:
            lines.append(f"Market: {request.market}")

        if score:
            score_line = f"Score: {score.score} (threshold: {score.threshold})"
            lines.append(score_line)
            if score.reason_codes:
                lines.append(f"Reason codes: {', '.join(score.reason_codes)}")

        lines.append(f"Recent events ({len(events)}):")
        for e in events[:20]:
            headline = e.headline or "(no headline)"
            summary = e.body_summary or ""

            # Provenance tags — only non-None/non-empty, non-default
            parts: list[str] = []
            if e.source_name:
                parts.append(f"[src:{e.source_name}]")
            if e.source_reliability_tier:
                parts.append(f"[tier:{e.source_reliability_tier}]")
            if e.event_type:
                parts.append(f"[{e.event_type}]")
            if e.published_at:
                parts.append(f"[{e.published_at.strftime('%Y-%m-%d')}]")
            if e.issuer_code:
                parts.append(f"[issuer:{e.issuer_code}]")
            # Non-default severity only
            if e.severity and e.severity != "medium":
                parts.append(f"[severity:{e.severity}]")
            # Non-default direction only
            if e.direction and e.direction not in ("neutral", ""):
                parts.append(f"[{e.direction}]")

            # Stale check — based on ingested_at, not published_at
            stale_mark = ""
            if e.ingested_at and (now - e.ingested_at).total_seconds() > 86400:  # 24h
                stale_mark = " ⚠️STALE"

            tagged = " ".join(parts)
            body = f" — {summary[:200]}" if summary else ""
            lines.append(f"  {tagged}{stale_mark} {headline}{body}")

        return "\n".join(lines)
