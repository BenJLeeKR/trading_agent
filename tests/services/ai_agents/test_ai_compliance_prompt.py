"""Tests for AI Compliance prompt invariants."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from agent_trading.services.ai_agents.ai_compliance import AIComplianceAgent
from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    AggregateEventView,
    EventInterpretationOutput,
)
from agent_trading.services.common_types import AIPolicyContextView


class TestAICompliancePrompt:
    """AI Compliance prompt contract must preserve non-authoritative boundaries."""

    def _make_request(self) -> AgentExecutionRequest:
        return AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="ai-compliance-prompt-test",
            context=AIPolicyContextView(source_type="core"),
            symbol="005930",
            market="KRX",
            source_type="core",
            event_interpretation_output=EventInterpretationOutput(
                detected_event_count=1,
                aggregate_view=AggregateEventView(
                    overall_bias="positive",
                    evidence_strength="moderate",
                    event_count=1,
                    no_material_events=False,
                    top_reason_codes=("earnings_surprise",),
                ),
            ),
            ai_risk_output=AIRiskOutput(
                risk_opinion="warn",
                risk_score=0.42,
                risk_flags=("high_volatility",),
                reason_codes=("risk_warn",),
            ),
        )

    def test_system_prompt_keeps_non_authoritative_boundary(self) -> None:
        """System prompt는 deterministic validator 최종 권한을 명시해야 한다."""
        agent = AIComplianceAgent(provider_client=MagicMock())

        prompt = agent._build_system_prompt()

        assert "compliance_opinion: one of allow, warn, review, reject" in prompt
        assert "Deterministic validator remains final authority." in prompt
        assert "You MUST NOT re-implement hard broker rejection rules" in prompt

    def test_user_prompt_contains_ei_ar_sections(self) -> None:
        """User prompt는 source type, EI, AR 맥락을 모두 포함해야 한다."""
        agent = AIComplianceAgent(provider_client=MagicMock())

        prompt = agent._build_user_prompt(self._make_request())

        assert "Source type: core" in prompt
        assert "=== Event Interpretation Output ===" in prompt
        assert "Evidence strength: moderate" in prompt
        assert "Top reason codes: earnings_surprise" in prompt
        assert "=== AI Risk Output ===" in prompt
        assert "Risk opinion: warn" in prompt
        assert "Risk flags: high_volatility" in prompt
