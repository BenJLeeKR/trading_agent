"""Tests for the deterministic AI Compliance bot.

2026-08-16 결정: LLM 기반 ``AIComplianceAgent``를 실행 경로에서 제거하고,
``DeterministicAIComplianceAgent``로 전환했다. Authoritative 차단은
submit-time deterministic validator가 담당하므로, 이 bot은 새 hard block을
만들지 않고 이미 계산된 AR/EI/deterministic trigger 신호를 compliance
projection으로 재구성하는 역할만 검증한다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from agent_trading.services.ai_agents.ai_compliance import (
    DeterministicAIComplianceAgent,
    _compute_deterministic_compliance,
)
from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.schemas import (
    AIComplianceOutput,
    AIRiskOutput,
    AggregateEventView,
    EventInterpretationOutput,
)
from agent_trading.services.common_types import AIPolicyContextView
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)


def _make_request(
    *,
    source_type: str = "core",
    ai_risk_output: AIRiskOutput | None = None,
    event_interpretation_output: EventInterpretationOutput | None = None,
    deterministic_trigger: DeterministicTriggerAssessment | None = None,
) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        decision_context_id=uuid4(),
        correlation_id="ai-compliance-deterministic-test",
        context=AIPolicyContextView(
            source_type=source_type,
            deterministic_trigger=deterministic_trigger,
        ),
        symbol="005930",
        market="KRX",
        source_type=source_type,
        ai_risk_output=ai_risk_output,
        event_interpretation_output=event_interpretation_output,
    )


class TestDeterministicAIComplianceAgent:
    """``DeterministicAIComplianceAgent``는 LLM 호출 없이 항상 값을 반환한다."""

    def test_agent_name_matches_llm_agent_for_compatibility(self) -> None:
        """agent_type 기반 API/UI 필터(``agent_type=="ai_compliance"``) 호환을
        위해 agent_name을 그대로 유지해야 한다."""
        agent = DeterministicAIComplianceAgent()
        assert agent.agent_name == "ai_compliance"
        assert agent.schema_version == "v1"

    @pytest.mark.asyncio
    async def test_run_never_calls_llm_and_returns_ai_compliance_output(self) -> None:
        agent = DeterministicAIComplianceAgent()
        result = await agent.run(_make_request())
        assert isinstance(result, AIComplianceOutput)
        assert result.compliance_opinion in {"allow", "warn", "review", "reject"}


class TestComputeDeterministicCompliance:
    """규칙 계산 함수 ``_compute_deterministic_compliance()`` 단위 테스트."""

    def test_default_allow_with_no_signals(self) -> None:
        output = _compute_deterministic_compliance(_make_request())
        assert output.compliance_opinion == "allow"
        assert output.compliance_score == 0.0
        assert output.confidence == 1.0
        assert any(
            code.startswith("compliance_rule_set:") for code in output.reason_codes
        )
        assert any(code == "source_type_core" for code in output.reason_codes)

    def test_ai_risk_reject_escalates_to_review(self) -> None:
        request = _make_request(
            ai_risk_output=AIRiskOutput(risk_opinion="reject", proposed_side="BUY"),
        )
        output = _compute_deterministic_compliance(request)
        assert output.compliance_opinion == "review"
        assert output.compliance_score >= 0.6
        assert "ai_risk_opinion_reject" in output.reason_codes
        assert output.proposed_side == "BUY"

    def test_ai_risk_reduce_escalates_to_warn(self) -> None:
        request = _make_request(
            ai_risk_output=AIRiskOutput(risk_opinion="reduce"),
        )
        output = _compute_deterministic_compliance(request)
        assert output.compliance_opinion == "warn"
        assert "ai_risk_opinion_reduce" in output.reason_codes

    def test_ai_risk_allow_stays_allow(self) -> None:
        request = _make_request(
            ai_risk_output=AIRiskOutput(risk_opinion="allow"),
        )
        output = _compute_deterministic_compliance(request)
        assert output.compliance_opinion == "allow"

    def test_event_conflict_escalates_to_warn(self) -> None:
        request = _make_request(
            event_interpretation_output=EventInterpretationOutput(
                aggregate_view=AggregateEventView(event_conflict=True),
            ),
        )
        output = _compute_deterministic_compliance(request)
        assert output.compliance_opinion == "warn"
        assert "event_conflict_detected" in output.reason_codes

    def test_reject_takes_priority_over_event_conflict(self) -> None:
        """AR reject(review)가 이벤트 충돌(warn)보다 우선해야 한다."""
        request = _make_request(
            ai_risk_output=AIRiskOutput(risk_opinion="reject"),
            event_interpretation_output=EventInterpretationOutput(
                aggregate_view=AggregateEventView(event_conflict=True),
            ),
        )
        output = _compute_deterministic_compliance(request)
        assert output.compliance_opinion == "review"

    def test_deterministic_trigger_eligibility_failure_adds_policy_flags_only(
        self,
    ) -> None:
        """eligibility 미통과는 policy_flags/reason_codes로만 남기고
        opinion을 review/reject로 격상시키지 않는다(hard block 중복 방지)."""
        trigger = DeterministicTriggerAssessment(
            trigger_version="deterministic_trigger_v1",
            primary_candidate="NO_ACTION",
            candidate_set=(),
            watch_candidate=False,
            buy_candidate=False,
            sell_candidate=False,
            reduce_candidate=False,
            candidate_confidence=0.0,
            entry_score=None,
            exit_score=None,
            watch_score=None,
            eligibility_passed=False,
            eligibility_reasons=("eligibility_low_average_volume",),
        )
        request = _make_request(deterministic_trigger=trigger)
        output = _compute_deterministic_compliance(request)
        assert output.compliance_opinion == "allow"
        assert "eligibility_low_average_volume" in output.policy_flags
        assert "deterministic_eligibility_not_passed" in output.reason_codes

    def test_decision_context_id_and_symbol_propagated(self) -> None:
        ctx_id = uuid4()
        request = AgentExecutionRequest(
            decision_context_id=ctx_id,
            correlation_id="test",
            context=AIPolicyContextView(source_type="core"),
            symbol="000660",
            market="KRX",
            source_type="core",
        )
        output = _compute_deterministic_compliance(request)
        assert output.decision_context_id == str(ctx_id)
        assert output.symbol == "000660"
        assert output.agent_name == "ai_compliance"
