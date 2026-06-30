"""AI Compliance Agent — stub and real implementations.

이 agent는 deterministic compliance validator를 대체하지 않는다.
역할은 정책/규정/이벤트 맥락의 애매한 해석을 구조화 output으로 보강하는 것이다.
"""

from __future__ import annotations

import json
import logging

from agent_trading.config.settings import _resolve_provider_model_id
from agent_trading.services.ai_agents.base import (
    AIProviderClient,
    AgentExecutionRequest,
    RawProviderResponse,
)
from agent_trading.services.ai_agents.prompt_context_projection import (
    append_shared_deterministic_context_sections,
)
from agent_trading.services.ai_agents.schemas import (
    AIComplianceOutput,
    generate_json_schema,
)

logger = logging.getLogger(__name__)

_ALLOWED_COMPLIANCE_OPINIONS: frozenset[str] = frozenset({
    "allow", "warn", "review", "reject",
})


def _normalize_compliance_score(score: float) -> float:
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0 if score <= 100.0 else 1.0
    return score


class StubAIComplianceAgent:
    """Stub AI Compliance Agent — 기본 allow output 반환."""

    def __init__(self, schema_version: str = "v1") -> None:
        self._schema_version = schema_version

    @property
    def agent_name(self) -> str:
        return "ai_compliance"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(self, request: AgentExecutionRequest) -> AIComplianceOutput:
        try:
            return AIComplianceOutput(
                schema_version=self._schema_version,
                agent_name=self.agent_name,
                decision_context_id=(
                    str(request.decision_context_id)
                    if request.decision_context_id
                    else None
                ),
                symbol=request.symbol or "",
            )
        except Exception:
            logger.warning(
                "StubAIComplianceAgent.run() failed — returning default output.",
                exc_info=True,
            )
            return AIComplianceOutput()


class AIComplianceAgent:
    """Real AI Compliance Agent — provider structured output wrapper."""

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
        return "ai_compliance"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(self, request: AgentExecutionRequest) -> AIComplianceOutput:
        logger.debug(
            "AIComplianceAgent.run() called: decision_context_id=%s correlation_id=%s model_id=%s",
            request.decision_context_id,
            request.correlation_id,
            self._model_id,
        )
        try:
            raw_response: RawProviderResponse = await self._provider.generate_structured(
                model_id=self._model_id,
                system_prompt=self._build_system_prompt(),
                user_prompt=self._build_user_prompt(request),
                response_format=AIComplianceOutput,
            )
            result: AIComplianceOutput = raw_response.parsed  # type: ignore[assignment]
            opinion = (result.compliance_opinion or "").strip().lower()
            if opinion not in _ALLOWED_COMPLIANCE_OPINIONS:
                logger.warning(
                    "AIComplianceAgent compliance_opinion drift detected — fallback to review. raw=%s",
                    result.compliance_opinion,
                )
                opinion = "review"
            return AIComplianceOutput(
                schema_version=result.schema_version or self._schema_version,
                agent_name=result.agent_name or self.agent_name,
                decision_context_id=(
                    str(request.decision_context_id)
                    if request.decision_context_id
                    else None
                ),
                symbol=result.symbol or request.symbol or "",
                proposed_side=result.proposed_side,
                compliance_opinion=opinion,
                compliance_score=_normalize_compliance_score(result.compliance_score),
                confidence=_normalize_compliance_score(result.confidence),
                policy_flags=result.policy_flags,
                reason_codes=result.reason_codes,
                opposing_evidence=result.opposing_evidence,
                summary=result.summary,
            )
        except Exception:
            logger.warning(
                "AIComplianceAgent failed — returning default output (safe fallback). decision_context_id=%s",
                request.decision_context_id,
                exc_info=True,
            )
            return AIComplianceOutput(
                schema_version=self._schema_version,
                agent_name=self.agent_name,
                decision_context_id=(
                    str(request.decision_context_id)
                    if request.decision_context_id
                    else None
                ),
                symbol=request.symbol or "",
            )

    def _build_system_prompt(self) -> str:
        schema_json = json.dumps(
            generate_json_schema(AIComplianceOutput), indent=2
        )
        return (
            "You are an AI Compliance Agent for a trading system. "
            "Interpret ambiguous policy, market-rule, source-policy, and event-risk context. "
            "You MUST NOT re-implement hard broker rejection rules or deterministic validator authority.\n\n"
            "Output must be valid JSON matching this schema:\n"
            f"{schema_json}\n\n"
            "IMPORTANT:\n"
            "- compliance_opinion: one of allow, warn, review, reject\n"
            "- policy_flags and reason_codes: machine-readable English codes\n"
            "- summary and opposing_evidence: Korean only\n"
            "- Do not claim authoritative blocking. Deterministic validator remains final authority.\n"
        )

    def _build_user_prompt(self, request: AgentExecutionRequest) -> str:
        context = request.context
        lines: list[str] = [
            f"Correlation ID: {request.correlation_id}",
            f"Symbol: {request.symbol or '(not available)'}",
            f"Market: {request.market or '(not available)'}",
            f"Source type: {request.source_type}",
        ]

        append_shared_deterministic_context_sections(
            lines,
            context,
            profile="ai_compliance",
        )

        if request.event_interpretation_output is not None:
            ei = request.event_interpretation_output
            lines.append("")
            lines.append("=== Event Interpretation Output ===")
            lines.append(f"Overall bias: {ei.aggregate_view.overall_bias}")
            lines.append(f"Evidence strength: {ei.aggregate_view.evidence_strength}")
            lines.append(f"Detected event count: {ei.detected_event_count}")
            if ei.aggregate_view.top_reason_codes:
                lines.append(
                    f"Top reason codes: {', '.join(ei.aggregate_view.top_reason_codes)}"
                )

        if request.ai_risk_output is not None:
            ar = request.ai_risk_output
            lines.append("")
            lines.append("=== AI Risk Output ===")
            lines.append(f"Risk opinion: {ar.risk_opinion}")
            lines.append(f"Risk score: {ar.risk_score}")
            if ar.risk_flags:
                lines.append(f"Risk flags: {', '.join(ar.risk_flags)}")
            if ar.reason_codes:
                lines.append(f"Reason codes: {', '.join(ar.reason_codes)}")

        lines.append("")
        lines.append("Decide whether the current context is policy-safe, ambiguous, or should be flagged for review.")
        lines.append("Focus on strategy-policy mismatch, source-policy ambiguity, market-rule ambiguity, and event-driven restriction context.")
        return "\n".join(lines)
