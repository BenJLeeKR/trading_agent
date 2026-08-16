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


# ============================================================================
# Deterministic AI Compliance bot (2026-08-16 결정)
# ============================================================================
#
# LLM 기반 AIComplianceAgent는 더 이상 실행 경로(bootstrap/subprocess)에
# 연결하지 않는다. Authoritative 차단은 이미 submit-time deterministic
# validator(§`08_ai_decision_policy.md` §4.5, §8.6)가 담당하므로, 이
# deterministic bot은 hard block을 새로 만들지 않고 이미 계산된 신호
# (ai_risk opinion, event conflict, deterministic trigger eligibility)를
# compliance projection 형태로 재구성해 관측/감사 가능하게 만드는 역할만
# 한다. 위 ``AIComplianceAgent``(LLM) 클래스는 하위 호환/테스트용으로
# 그대로 남겨둔다.

_DETERMINISTIC_RULE_SET_VERSION = "deterministic_v1"


def _compute_deterministic_compliance(
    request: AgentExecutionRequest,
    *,
    rule_set_version: str = _DETERMINISTIC_RULE_SET_VERSION,
) -> AIComplianceOutput:
    """정형 신호만으로 compliance projection을 계산한다(LLM 호출 없음).

    hard block 조건(broker capability, restricted symbol, 필수 필드
    누락 등)은 이미 deterministic compliance validator가 담당하므로
    여기서 다시 판단하지 않는다. 여기서는 이미 계산된 AR/EI/deterministic
    trigger 신호를 compliance 관점의 관측치로 투영만 한다.
    """
    reason_codes: list[str] = [f"compliance_rule_set:{rule_set_version}"]
    policy_flags: list[str] = []
    opinion = "allow"
    score = 0.0

    source_type = (request.source_type or "core").strip().lower()
    reason_codes.append(f"source_type_{source_type}")

    ar_output = request.ai_risk_output
    proposed_side = ar_output.proposed_side if ar_output is not None else ""
    if ar_output is not None:
        if ar_output.risk_opinion == "reject":
            opinion = "review"
            score = max(score, 0.6)
            reason_codes.append("ai_risk_opinion_reject")
        elif ar_output.risk_opinion == "reduce":
            if opinion == "allow":
                opinion = "warn"
            score = max(score, 0.3)
            reason_codes.append("ai_risk_opinion_reduce")

    ei_output = request.event_interpretation_output
    if ei_output is not None and ei_output.aggregate_view.event_conflict:
        if opinion == "allow":
            opinion = "warn"
        score = max(score, 0.2)
        reason_codes.append("event_conflict_detected")

    deterministic_trigger = getattr(request.context, "deterministic_trigger", None)
    if deterministic_trigger is not None and not bool(
        getattr(deterministic_trigger, "eligibility_passed", True)
    ):
        eligibility_reasons = tuple(
            getattr(deterministic_trigger, "eligibility_reasons", ()) or ()
        )
        policy_flags.extend(eligibility_reasons)
        reason_codes.append("deterministic_eligibility_not_passed")

    summary = (
        f"Deterministic compliance projection({rule_set_version}): "
        f"opinion={opinion} source_type={source_type} "
        "(LLM 호출 없음, hard block은 submit-time deterministic validator가 담당)."
    )

    return AIComplianceOutput(
        agent_name="ai_compliance",
        decision_context_id=(
            str(request.decision_context_id)
            if request.decision_context_id
            else None
        ),
        symbol=request.symbol or "",
        proposed_side=proposed_side,
        compliance_opinion=opinion,
        compliance_score=score,
        confidence=1.0,
        policy_flags=tuple(policy_flags),
        reason_codes=tuple(reason_codes),
        summary=summary,
    )


class DeterministicAIComplianceAgent:
    """Deterministic rule-based AI Compliance projection (LLM 호출 없음).

    ``agent_name``은 기존 API/UI(`api/routes/decisions.py`의
    ``agent_type="ai_compliance"`` 필터)와의 호환을 위해 그대로
    ``"ai_compliance"``를 유지한다. LLM이 아니라는 사실은 ``reason_codes``의
    ``compliance_rule_set:*`` 항목과 ``summary``로 구분한다.
    """

    def __init__(self, rule_set_version: str = _DETERMINISTIC_RULE_SET_VERSION) -> None:
        self._rule_set_version = rule_set_version

    @property
    def agent_name(self) -> str:
        return "ai_compliance"

    @property
    def schema_version(self) -> str:
        return "v1"

    async def run(self, request: AgentExecutionRequest) -> AIComplianceOutput:
        return _compute_deterministic_compliance(
            request, rule_set_version=self._rule_set_version
        )
