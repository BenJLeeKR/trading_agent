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
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from agent_trading.services.ai_agents._prompt_config import (
    MAX_EVENTS_AR,
    MAX_INTERPRETED_EVENTS,
)
from agent_trading.services.ai_agents.base import (
    AIProviderClient,
    AgentExecutionRequest,
    ProviderAIAgent,
    RawProviderResponse,
)
from agent_trading.services.ai_agents.schemas import AIRiskOutput, EventInterpretationOutput, generate_json_schema

logger = logging.getLogger(__name__)

# Canonical risk_opinion values (machine-readable enum).
# Any value outside this set is treated as drift and falls back to "allow".
_ALLOWED_RISK_OPINIONS: frozenset[str] = frozenset({
    "allow", "reduce", "reject", "review",
})


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

            # --- risk_opinion canonical validation ---
            # strip().lower() 후 canonical 4값(allow/reduce/reject/review)과 비교.
            # drift 감지 시 의미 해석 없이 "allow"로 fallback + 경고 로그.
            risk_opinion_normalized = result.risk_opinion.strip().lower()

            # === Layer 2: Post-processing Guard for orderable_amount ===
            # orderable_amount > 0인데 LLM이 reject를 출력하면 review로 완화
            cash_snapshot = (
                request.context.cash_balance_snapshot
                if hasattr(request, 'context')
                else None
            )
            if (
                cash_snapshot is not None
                and cash_snapshot.orderable_amount is not None
                and cash_snapshot.orderable_amount > 0
                and risk_opinion_normalized == "reject"
            ):
                logger.warning(
                    "Layer2 Guard applied: orderable_amount=%s > 0 but "
                    "risk_opinion='reject' \u2192 downgraded to 'review'. "
                    "symbol=%s decision_context_id=%s",
                    cash_snapshot.orderable_amount,
                    result.symbol,
                    result.decision_context_id,
                )
                result = AIRiskOutput(
                    schema_version=result.schema_version,
                    agent_name=result.agent_name,
                    decision_context_id=result.decision_context_id,
                    symbol=result.symbol,
                    proposed_side=result.proposed_side,
                    risk_opinion="review",
                    risk_score=result.risk_score,
                    confidence=result.confidence,
                    size_adjustment_factor=result.size_adjustment_factor,
                    max_holding_horizon=result.max_holding_horizon,
                    risk_flags=result.risk_flags,
                    reason_codes=result.reason_codes,
                    opposing_evidence=result.opposing_evidence,
                    summary=result.summary,
                )
                risk_opinion_normalized = "review"
            # === End Layer 2 Guard ===

            if risk_opinion_normalized not in _ALLOWED_RISK_OPINIONS:
                logger.warning(
                    "risk_opinion drift detected — falling back to 'allow'. "
                    "raw=%r symbol=%s decision_context_id=%s",
                    result.risk_opinion,
                    result.symbol,
                    result.decision_context_id,
                )
                result = AIRiskOutput(
                    schema_version=result.schema_version,
                    agent_name=result.agent_name,
                    decision_context_id=result.decision_context_id,
                    symbol=result.symbol,
                    proposed_side=result.proposed_side,
                    risk_opinion="allow",
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
            f"{schema_json}\n\n"
            "IMPORTANT — Machine-readable fields (English enum values only):\n"
            "- risk_opinion: one of allow, reduce, reject, review\n"
            "- proposed_side: BUY or SELL\n"
            "- max_holding_horizon: short, swing, long\n"
            "- risk_flags: machine-readable English codes\n"
            "- reason_codes: machine-readable English codes\n\n"
            "Narrative fields (Korean only):\n"
            "- summary: Korean narrative summary\n"
            "- opposing_evidence: Korean narrative list\n\n"
            "Machine-readable fields MUST contain ONLY canonical English values. "
            "Narrative fields MUST be written in Korean."
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
                for ie in interpreted[:MAX_INTERPRETED_EVENTS]:
                    if isinstance(ie, dict):
                        summary = ie.get("summary") or ie.get("headline") or "(no summary)"
                        lines.append(f"  - [{ie.get('event_type', '?')}] {summary}")
                        lines.append(
                            f"    impact={ie.get('impact_direction', '?')} "
                            f"confidence={ie.get('confidence', '?')}"
                        )
                    else:
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
        # Layer 1: effective_buying_cash = orderable_amount 우선, 없으면 available_cash fallback
        cash = context.cash_balance_snapshot
        if cash is not None:
            if cash.orderable_amount is not None:
                effective_buying_cash = cash.orderable_amount
            else:
                effective_buying_cash = cash.available_cash

            lines.append("")
            lines.append("=== Cash Balance ===")
            lines.append(f"  Effective buying cash (primary): {effective_buying_cash}")
            lines.append(f"  Available cash (accounting reference): {cash.available_cash}")
            lines.append(f"  Currency: {cash.currency}")
            if cash.settled_cash is not None:
                lines.append(f"  Settled cash: {cash.settled_cash}")
            if cash.unsettled_cash is not None:
                lines.append(f"  Unsettled cash: {cash.unsettled_cash}")
            lines.append("")
            lines.append("  【Cash Judgment Guide】")
            lines.append("  - BUY feasibility MUST use 'Effective buying cash' (listed first above) as the primary criterion")
            lines.append("  - 'Available cash' is D+2 settlement basis — accounting reference only, do NOT use for BUY feasibility")
            lines.append("  - Do NOT conclude 'cannot buy' solely because 'Available cash' is negative")
        # ==================================================

        # ── Position Concentration ────────────────────────────────────────
        nav: Decimal | None = None
        if context.risk_limit_snapshot is not None and context.risk_limit_snapshot.nav is not None:
            nav = context.risk_limit_snapshot.nav
        elif context.cash_balance_snapshot is not None and context.cash_balance_snapshot.total_asset is not None:
            nav = context.cash_balance_snapshot.total_asset

        current_position_value: Decimal | None = None
        concentration_pct: float | None = None
        over_concentrated: bool = False
        remaining_capacity_pct: float | None = None

        if (
            context.position_snapshot is not None
            and context.position_snapshot.quantity is not None
            and context.position_snapshot.average_price is not None
        ):
            current_position_value = context.position_snapshot.quantity * context.position_snapshot.average_price

        if nav is not None and current_position_value is not None and nav > 0:
            concentration_pct = float(current_position_value / nav * 100)
            over_concentrated = concentration_pct > 15.0
            remaining_capacity_pct = max(0.0, 15.0 - concentration_pct)

        lines.append("")
        lines.append("=== Position Concentration ===")
        if current_position_value is not None:
            lines.append(f"  Current position value: {float(current_position_value):,.0f} KRW")
        else:
            lines.append("  Current position value: N/A")
        if nav is not None:
            lines.append(f"  NAV: {float(nav):,.0f} KRW")
        else:
            lines.append("  NAV: N/A")
        if concentration_pct is not None:
            lines.append(f"  Concentration: {concentration_pct:.1f}% of NAV")
        else:
            lines.append("  Concentration: N/A")
        lines.append(f"  Over-concentrated: {'Yes' if over_concentrated else 'No'}")
        lines.append("  Max single position limit: ~15% of NAV")
        if remaining_capacity_pct is not None:
            lines.append(f"  Remaining capacity: {remaining_capacity_pct:.1f}%p")
        else:
            lines.append("  Remaining capacity: N/A")
        lines.append("")
        lines.append("**Policy**:")
        lines.append("- When over-concentrated (over_concentrated=true), consider setting risk_opinion to 'reduce' as a priority.")
        lines.append("- Higher concentration increases risk — set size_adjustment_factor higher (range 0.3-0.7).")
        lines.append("- When over-concentrated, additional BUY is considered high risk — consider setting risk_opinion to 'reject' or 'review'.")
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
        now = datetime.now(timezone.utc)
        for e in events[:MAX_EVENTS_AR]:
            headline = e.headline or "(no headline)"

            # Provenance tags — same rules as EI (severity/direction default omission,
            # stale check, issuer_code condition, etc.)
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

            # Stale check — based on ingested_at, not published_at
            stale_mark = ""
            if e.ingested_at and (now - e.ingested_at).total_seconds() > 86400:
                stale_mark = " ⚠️STALE"

            tagged = " ".join(parts)
            lines.append(f"  {tagged}{stale_mark} {headline}")

        return "\n".join(lines)
