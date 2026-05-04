"""AI Risk Agent — stub and real implementations.

This agent evaluates risk factors for the current trading context and
produces a structured ``AIRiskOutput``.

* ``StubAIRiskAgent`` — always returns default / zero-risk values
  (no actual Provider API call).
* ``AIRiskAgent`` — calls a real Provider via ``AIProviderClient``.

Safe-fallback policy
--------------------
If an unexpected exception occurs during ``run()``, the agent logs a
warning and returns a default ``AIRiskOutput``.  This ensures that the
calling orchestrator can always proceed.
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
from agent_trading.services.ai_agents.schemas import AIRiskOutput, EventInterpretationOutput, generate_json_schema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stub (existing, unchanged)
# ---------------------------------------------------------------------------


class StubAIRiskAgent:
    """Stub AI Risk Agent — returns default (zero-risk) output.

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
        return "ai_risk"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(self, request: AgentExecutionRequest) -> AIRiskOutput:
        """Execute the agent and return a structured output.

        The stub implementation:
        * Logs the request for observability.
        * Returns a default ``AIRiskOutput`` (zero risk, low level).

        Safe fallback: any exception is caught, a warning is logged, and
        a default output is returned.
        """
        logger.debug(
            "StubAIRiskAgent.run() called: "
            "decision_context_id=%s correlation_id=%s",
            request.decision_context_id,
            request.correlation_id,
        )

        try:
            # --- Stub: no actual Provider call ---
            return AIRiskOutput()
        except Exception:
            logger.warning(
                "StubAIRiskAgent.run() failed — "
                "returning default output (safe fallback).",
                exc_info=True,
            )
            return AIRiskOutput()


# ---------------------------------------------------------------------------
# Real implementation
# ---------------------------------------------------------------------------


class AIRiskAgent:
    """Real AI Risk Agent — calls a Provider via AIProviderClient.

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
        return "ai_risk"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(
        self, request: AgentExecutionRequest
    ) -> AIRiskOutput:
        """Execute the agent and return a structured output.

        Builds a system prompt with the expected JSON schema, sends the
        request context to the Provider, parses the response, and returns
        a validated ``AIRiskOutput``.

        Safe fallback: any exception is caught, a warning is logged, and
        a default output is returned.
        """
        logger.debug(
            "AIRiskAgent.run() called: "
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
                response_format=AIRiskOutput,
            )

            result: AIRiskOutput = raw_response.parsed  # type: ignore[assignment]

            # Override metadata fields from request / agent identity
            result = AIRiskOutput(
                schema_version=result.schema_version or self._schema_version,
                agent_name=result.agent_name or self.agent_name,
                decision_context_id=(
                    str(request.decision_context_id)
                    if request.decision_context_id
                    else None
                ),
                symbol=result.symbol,
                proposed_side=result.proposed_side,
                risk_opinion=result.risk_opinion,
                risk_score=result.risk_score,
                confidence=result.confidence,
                size_adjustment_factor=result.size_adjustment_factor,
                max_holding_horizon=result.max_holding_horizon,
                risk_flags=result.risk_flags,
                reason_codes=result.reason_codes,
                opposing_evidence=result.opposing_evidence,
                summary=result.summary,
            )

            logger.info(
                "AIRiskAgent succeeded: "
                "symbol=%s risk_opinion=%s risk_score=%.2f",
                result.symbol,
                result.risk_opinion,
                result.risk_score,
            )
            return result

        except Exception:
            logger.warning(
                "AIRiskAgent failed — returning default output "
                "(safe fallback). decision_context_id=%s",
                request.decision_context_id,
                exc_info=True,
            )
            # Preserve agent identity and request metadata in fallback output
            fallback = AIRiskOutput(
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
            generate_json_schema(AIRiskOutput), indent=2
        )
        return (
            "You are an AI Risk Agent for a trading system. "
            "Assess the risk of the proposed trade based on the current "
            "trading context. Consider market conditions, recent events, "
            "and any available scoring information.\n\n"
            "Output must be valid JSON matching this schema:\n"
            f"{schema_json}"
        )

    def _build_user_prompt(self, request: AgentExecutionRequest) -> str:
        """Build the user prompt with the current request context.

        When the request carries an ``event_interpretation_output`` (i.e. the
        Event Interpretation Agent has run successfully), the prompt includes
        the interpreted event data (overall bias, event conflict, top reason
        codes, and per-event summaries).  When it is ``None`` (no EI output
        available), the prompt uses only the assembled context — this preserves
        backward compatibility with callers that do not pass EI output.
        """
        context = request.context
        score = context.score
        events = context.recent_events or []

        lines: list[str] = [
            f"Correlation ID: {request.correlation_id}",
        ]

        # Symbol and proposed side
        lines.append(f"Symbol: {request.context.decision_context or '(not available)'}")

        # === Event Interpretation output (if available) ===
        # The orchestrator always passes a structured EventInterpretationOutput
        # (never None) when the EI agent ran, but we guard against None here
        # for callers that construct AgentExecutionRequest directly.
        ei_output = request.event_interpretation_output
        if ei_output is not None:
            lines.append("")
            lines.append("=== Event Interpretation ===")
            lines.append(f"Overall bias: {ei_output.aggregate_view.overall_bias}")
            lines.append(f"Event conflict: {ei_output.aggregate_view.event_conflict}")
            if ei_output.aggregate_view.top_reason_codes:
                lines.append(
                    "Top reason codes: "
                    f"{', '.join(ei_output.aggregate_view.top_reason_codes)}"
                )

            # Interpreted events summary (max 10 to keep prompt length manageable)
            interpreted = ei_output.events or ()
            if interpreted:
                lines.append(f"Interpreted events ({len(interpreted)}):")
                for ie in interpreted[:10]:
                    summary = ie.summary or ie.headline or "(no summary)"
                    lines.append(f"  - [{ie.event_type}] {summary}")
                    lines.append(
                        f"    impact={ie.impact_direction} "
                        f"confidence={ie.confidence}"
                    )
            lines.append("")
        # ==================================================

        if score:
            lines.append(f"Score: {score.score} (threshold: {score.threshold})")
            if score.reason_codes:
                lines.append(f"Reason codes: {', '.join(score.reason_codes)}")

        # Decision context info
        dc = context.decision_context
        if dc:
            lines.append(f"Decision context account_id: {dc.account_id}")

        # === Position snapshot summary (if available) ===
        pos = context.position_snapshot
        if pos is not None:
            lines.append("")
            lines.append("=== Current Position (this symbol) ===")
            lines.append(f"  Quantity: {pos.quantity}")
            lines.append(f"  Average price: {pos.average_price}")
            if pos.market_price is not None:
                lines.append(f"  Market price: {pos.market_price}")
            if pos.unrealized_pnl is not None:
                lines.append(f"  Unrealised P&L: {pos.unrealized_pnl}")
        # ==================================================

        # === Cash balance snapshot summary (if available) ===
        cash = context.cash_balance_snapshot
        if cash is not None:
            lines.append("")
            lines.append("=== Cash Balance ===")
            lines.append(f"  Available cash: {cash.available_cash}")
            lines.append(f"  Currency: {cash.currency}")
            if cash.settled_cash is not None:
                lines.append(f"  Settled cash: {cash.settled_cash}")
            if cash.unsettled_cash is not None:
                lines.append(f"  Unsettled cash: {cash.unsettled_cash}")
        # ==================================================

        # === Risk limit snapshot summary (if available) ===
        rl = context.risk_limit_snapshot
        if rl is not None:
            lines.append("")
            lines.append("=== Risk Limit State ===")
            lines.append(f"  Kill switch active: {rl.kill_switch_active}")
            if rl.drawdown_state:
                lines.append(f"  Drawdown state: {rl.drawdown_state}")
            if rl.blocked_reason_codes:
                lines.append(
                    "  Blocked reason codes: "
                    f"{', '.join(rl.blocked_reason_codes)}"
                )
            if rl.daily_loss_used_pct is not None and rl.max_daily_loss_limit_pct is not None:
                lines.append(
                    f"  Daily loss: {rl.daily_loss_used_pct}% / "
                    f"{rl.max_daily_loss_limit_pct}% limit"
                )
            if rl.gross_exposure_pct is not None:
                lines.append(f"  Gross exposure: {rl.gross_exposure_pct}%")
            if rl.net_exposure_pct is not None:
                lines.append(f"  Net exposure: {rl.net_exposure_pct}%")
        # ==================================================

        lines.append(f"Recent events ({len(events)}):")
        for e in events[:20]:
            headline = e.headline or "(no headline)"
            summary = e.body_summary or ""
            lines.append(
                f"  - [{e.event_type}] {headline}"
                f"{' — ' + summary[:200] if summary else ''}"
            )

        return "\n".join(lines)
