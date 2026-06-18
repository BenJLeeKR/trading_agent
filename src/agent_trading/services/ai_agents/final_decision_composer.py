"""Stub and real implementations of the Final Decision Composer Agent.

This agent synthesises the outputs of the Event Interpretation and AI Risk
agents into a final structured decision (``FinalDecisionComposerOutput``).

Safe-fallback policy
--------------------
If an unexpected exception occurs during ``run()``, the agent logs a
warning and returns a default ``FinalDecisionComposerOutput``.  This
ensures that the calling orchestrator can always proceed.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from decimal import Decimal

from agent_trading.config.settings import _resolve_provider_model_id
from agent_trading.services.ai_agents._prompt_config import (
    MAX_EVENTS_FDC,
    MAX_INTERPRETED_EVENTS,
)
from agent_trading.services.ai_agents.prompt_context_projection import (
    append_shared_deterministic_context_sections,
)
from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    AIProviderClient,
    ProviderAIAgent,
    RawProviderResponse,
)
from agent_trading.services.ai_agents.schemas import (
    FinalDecisionComposerOutput,
    generate_json_schema,
)

logger = logging.getLogger(__name__)


class StubFinalDecisionComposerAgent:
    """Stub Final Decision Composer — returns default ("hold") output.

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
        return "final_decision_composer"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(
        self, request: AgentExecutionRequest
    ) -> FinalDecisionComposerOutput:
        """Execute the agent and return a structured output.

        The stub implementation:
        * Logs the request for observability.
        * Returns a default ``FinalDecisionComposerOutput`` (hold action,
          zero adjustments, full consensus).

        Safe fallback: any exception is caught, a warning is logged, and
        a default output is returned.
        """
        logger.debug(
            "StubFinalDecisionComposerAgent.run() called: "
            "decision_context_id=%s correlation_id=%s",
            request.decision_context_id,
            request.correlation_id,
        )

        try:
            # --- Stub: no actual Provider call ---
            return FinalDecisionComposerOutput()
        except Exception:
            logger.warning(
                "StubFinalDecisionComposerAgent.run() failed — "
                "returning default output (safe fallback).",
                exc_info=True,
            )
            return FinalDecisionComposerOutput()


class FinalDecisionComposerAgent:
    """Real Final Decision Composer — calls a Provider via AIProviderClient.

    Conforms to the ``ProviderAIAgent`` protocol.

    This agent receives an ``AgentExecutionRequest`` that may carry:
    * ``event_interpretation_output`` — output from the Event Interpretation
      Agent (aggregate view, interpreted events).
    * ``ai_risk_output`` — output from the AI Risk Agent (risk opinion,
      risk score, size adjustment factor, reason codes, opposing evidence).

    The prompt is built from the assembled context plus both agent outputs.
    When either output is ``None`` (not provided by the orchestrator), the
    prompt simply omits that section — preserving backward compatibility.

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
        model_id: str | None = None,
        schema_version: str = "v1",
    ) -> None:
        self._provider = provider_client
        self._model_id = model_id or _resolve_provider_model_id()
        self._schema_version = schema_version

    @property
    def agent_name(self) -> str:
        return "final_decision_composer"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(
        self, request: AgentExecutionRequest
    ) -> FinalDecisionComposerOutput:
        """Execute the agent and return a structured output.

        Builds a system prompt with the expected JSON schema, sends the
        request context to the Provider, parses the response, and returns
        a validated ``FinalDecisionComposerOutput``.

        Safe fallback: any exception is caught, a warning is logged, and
        a default output (``decision_type="HOLD"``) is returned with
        agent identity preserved.
        """
        logger.debug(
            "FinalDecisionComposerAgent.run() called: "
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
                response_format=FinalDecisionComposerOutput,
            )

            result: FinalDecisionComposerOutput = raw_response.parsed  # type: ignore[assignment]

            # Override metadata fields from request / agent identity
            result = FinalDecisionComposerOutput(
                schema_version=result.schema_version or self._schema_version,
                agent_name=result.agent_name or self.agent_name,
                decision_context_id=(
                    str(request.decision_context_id)
                    if request.decision_context_id
                    else None
                ),
                symbol=result.symbol,
                decision_type=result.decision_type,
                side=result.side,
                entry_style=result.entry_style,
                time_horizon=result.time_horizon,
                confidence=result.confidence,
                conviction=result.conviction,
                reason_codes=result.reason_codes,
                opposing_evidence=result.opposing_evidence,
                execution_preferences=result.execution_preferences,
                sizing_hint=result.sizing_hint,
                exit_plan_hint=result.exit_plan_hint,
                summary=result.summary,
            )

            logger.info(
                "FinalDecisionComposerAgent succeeded: "
                "symbol=%s decision_type=%s confidence=%.2f",
                result.symbol,
                result.decision_type,
                result.confidence,
            )
            return result

        except Exception:
            logger.warning(
                "FinalDecisionComposerAgent failed — returning default HOLD output "
                "(safe fallback). decision_context_id=%s",
                request.decision_context_id,
                exc_info=True,
            )
            # Preserve agent identity and request metadata in fallback output
            fallback = FinalDecisionComposerOutput(
                schema_version=self._schema_version,
                agent_name=self.agent_name,
                decision_context_id=(
                    str(request.decision_context_id)
                    if request.decision_context_id
                    else None
                ),
            )
            return fallback

    def _build_system_prompt(self) -> str:
        """Build the system prompt describing the expected output schema."""
        schema_json = json.dumps(
            generate_json_schema(FinalDecisionComposerOutput), indent=2
        )
        return (
            "You are a Final Decision Composer for a trading system. "
            "Synthesise the outputs of the Event Interpretation Agent and "
            "the AI Risk Agent, together with the assembled trading context, "
            "to produce a structured final decision.\n\n"
            "Output must be valid JSON matching this schema:\n"
            f"{schema_json}\n\n"
            "IMPORTANT: The following fields MUST use canonical English enum values:\n"
            "- decision_type: one of APPROVE, BUY, SELL, HOLD, WATCH, EXIT, REDUCE\n"
            "- side: BUY or SELL\n"
            "- entry_style: LIMIT, MARKET, VWAP, TWAP\n"
            "- time_horizon: short, swing, long\n"
            "- reason_codes: machine-readable English codes\n\n"
            "## No-Event Policy\n"
            "- no_material_events + evidence_strength=none (core): "
            "insufficient information to act → HOLD. "
            "WATCH may be considered as a valid non-HOLD option "
            "(monitor without entering).\n"
            "- no_material_events + evidence_strength=none (market_overlay): "
            "can be APPROVED or WATCHed.\n"
            "- no_material_events + evidence_strength=weak: "
            "WATCH viable for non-core; for core, "
            "WATCH may be considered (monitor without entering) "
            "as a valid non-HOLD option.\n"
            "- evidence_strength=moderate/strong: "
            "Evaluate normally → APPROVE/REDUCE/EXIT.\n"
            "- 'negative signal' (bearish bias): "
            "HOLD/REDUCE regardless of source. "
            "IMPORTANT: 'negative signal' is NOT the same as 'no event'.\n\n"
            "## Source Type Consideration\n"
            "- core → conservative; WATCH may be viable when evidence is weak.\n"
            "- held_position → need clear signal;\n"
            "- event_overlay → consider events; market_overlay → no-event OK.\n\n"
            "Narrative fields (summary, opposing_evidence) MUST be written in Korean. "
            "Machine-readable fields listed above MUST remain in English."
        )

    def _build_user_prompt(self, request: AgentExecutionRequest) -> str:
        """Build the user prompt with the current request context.

        The prompt includes:
        * Assembled context score and reason codes.
        * Event Interpretation output (aggregate view, events summary) —
          only when ``event_interpretation_output`` is provided.
        * AI Risk output (risk opinion, risk score, size adjustment factor,
          reason codes, opposing evidence) — only when ``ai_risk_output``
          is provided.
        * Recent external events.

        When either agent output is ``None``, the corresponding section is
        omitted — the flow never breaks.
        """
        context = request.context
        score = context.score
        events = context.recent_events or []

        lines: list[str] = [
            f"Correlation ID: {request.correlation_id}",
        ]

        # Symbol source priority:
        #   1. explicit request.symbol
        #   2. context.recent_events first non-None e.symbol
        #   3. Fallback "(not available)"
        symbol: str = "(not available)"
        if request.symbol:
            symbol = request.symbol
        elif events:
            for e in events:
                if e.symbol:
                    symbol = e.symbol
                    break
        lines.append(f"Symbol: {symbol}")
        if request.market:
            lines.append(f"Market: {request.market}")
        lines.append(f"Source type: {request.source_type}")

        # Decision context
        dc = context.decision_context
        if dc:
            lines.append(f"Account ID: {dc.account_id}")

        # === Assembled context score ===
        if score:
            lines.append("")
            lines.append("=== Assembled Context Score ===")
            lines.append(f"Score: {score.score} (threshold: {score.threshold})")
            if score.reason_codes:
                lines.append(f"Reason codes: {', '.join(score.reason_codes)}")

        append_shared_deterministic_context_sections(
            lines,
            context,
            profile="final_decision_composer",
        )

        # === Event Interpretation output (if available) ===
        ei_output = request.event_interpretation_output
        if ei_output is not None:
            lines.append("")
            lines.append("=== Event Interpretation Output ===")
            lines.append(f"Overall bias: {ei_output.aggregate_view.overall_bias}")
            lines.append(f"Event conflict: {ei_output.aggregate_view.event_conflict}")
            lines.append(f"Evidence strength: {ei_output.aggregate_view.evidence_strength}")
            lines.append(f"Event count: {ei_output.detected_event_count}")
            lines.append(f"No material events: {ei_output.aggregate_view.no_material_events}")
            if ei_output.aggregate_view.top_reason_codes:
                lines.append(
                    "Top reason codes: "
                    f"{', '.join(ei_output.aggregate_view.top_reason_codes)}"
                )

            # Interpreted events summary (max 10)
            interpreted = ei_output.events or ()
            if interpreted:
                lines.append(f"Interpreted events ({len(interpreted)}):")
                for ie in interpreted[:MAX_INTERPRETED_EVENTS]:
                    if isinstance(ie, dict):
                        summary = ie.get("summary") or "(no summary)"
                        lines.append(f"  - [{ie.get('event_type', '?')}] {summary}")
                        lines.append(
                            f"    impact={ie.get('impact_direction', '?')} "
                            f"confidence={ie.get('confidence', '?')}"
                        )
                    else:
                        summary = ie.summary or "(no summary)"
                        lines.append(f"  - [{ie.event_type}] {summary}")
                        lines.append(
                            f"    impact={ie.impact_direction} "
                            f"confidence={ie.confidence}"
                        )

        # === AI Risk output (if available) ===
        ar_output = request.ai_risk_output
        if ar_output is not None:
            lines.append("")
            lines.append("=== AI Risk Output ===")
            lines.append(f"Risk opinion: {ar_output.risk_opinion}")
            lines.append(f"Risk score: {ar_output.risk_score}")
            lines.append(f"Confidence: {ar_output.confidence}")
            lines.append(f"Size adjustment factor: {ar_output.size_adjustment_factor}")
            if ar_output.reason_codes:
                lines.append(f"Reason codes: {', '.join(ar_output.reason_codes)}")
            if ar_output.opposing_evidence:
                lines.append("Opposing evidence:")
                for oe in ar_output.opposing_evidence:
                    lines.append(f"  - {oe}")


        # === Recent events ===
        lines.append("")
        lines.append(f"Recent events ({len(events)}):")
        now = datetime.now(timezone.utc)
        for e in events[:MAX_EVENTS_FDC]:
            headline = e.headline or "(no headline)"

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
            if e.severity and e.severity != "medium":
                parts.append(f"[severity:{e.severity}]")
            if e.direction and e.direction not in ("neutral", ""):
                parts.append(f"[{e.direction}]")

            stale_mark = ""
            if e.ingested_at and (now - e.ingested_at).total_seconds() > 86400:
                stale_mark = " ⚠️STALE"

            tagged = " ".join(parts)
            lines.append(f"  {tagged}{stale_mark} {headline}")

        return "\n".join(lines)
