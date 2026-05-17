"""Tests for EventInterpretationAgent system prompt — top_reason_codes generation."""

from unittest.mock import MagicMock

from agent_trading.services.ai_agents.event_interpretation import (
    EventInterpretationAgent,
)


class TestEventInterpretationSystemPrompt:
    """_build_system_prompt() must include top_reason_codes requirements."""

    def _make_agent(self) -> EventInterpretationAgent:
        """Create an EventInterpretationAgent with a mock provider."""
        mock_provider = MagicMock()
        return EventInterpretationAgent(provider_client=mock_provider)

    def test_system_prompt_contains_top_reason_codes(self):
        """_build_system_prompt() must contain top_reason_codes generation requirement."""
        agent = self._make_agent()
        prompt = agent._build_system_prompt()
        assert "top_reason_codes" in prompt, (
            "system_prompt MUST contain top_reason_codes generation requirement"
        )

    def test_system_prompt_mentions_at_least_one_reason_code(self):
        """With events present, prompt should require at least one reason code."""
        agent = self._make_agent()
        prompt = agent._build_system_prompt()
        assert "at least one" in prompt.lower(), (
            "Prompt should require at least one reason code when events exist"
        )

    def test_system_prompt_mentions_korean_for_summary(self):
        """Narrative fields must be written in Korean per prompt requirements."""
        agent = self._make_agent()
        prompt = agent._build_system_prompt()
        assert "korean" in prompt.lower() or "한국어" in prompt, (
            "Prompt should require Korean for narrative fields"
        )
