"""Tests for EI/FDC HOLD bias mitigation (evidence_strength, source_type, no-event policy).

This module covers:

1. ``AggregateEventView`` default values — no-event → ``evidence_strength="none"``,
   ``event_count=0``, ``no_material_events=True``.
2. FDC system prompt includes no-event policy and source_type consideration.
3. FDC user prompt displays source_type, evidence_strength, event_count,
   no_material_events when EI output is available.
4. ``AgentExecutionRequest`` propagates ``source_type`` correctly.

See Also
--------
* :class:`~agent_trading.services.ai_agents.schemas.AggregateEventView`
* :class:`~agent_trading.services.ai_agents.base.AgentExecutionRequest`
* :class:`~agent_trading.services.ai_agents.final_decision_composer.FinalDecisionComposerAgent`
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.final_decision_composer import (
    FinalDecisionComposerAgent,
)
from agent_trading.services.ai_agents.schemas import (
    AggregateEventView,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.decision_orchestrator import AssembledContext


# ===========================================================================
# Test 1: EI no-event → evidence_strength=none
# ===========================================================================


class TestEvidenceStrengthDefaults:
    """``AggregateEventView()`` default values when no events are provided."""

    def test_default_evidence_strength_is_none(self) -> None:
        """Default ``evidence_strength`` must be ``"none"``."""
        view = AggregateEventView()
        assert view.evidence_strength == "none"

    def test_default_event_count_is_zero(self) -> None:
        """Default ``event_count`` must be ``0``."""
        view = AggregateEventView()
        assert view.event_count == 0

    def test_default_no_material_events_is_true(self) -> None:
        """Default ``no_material_events`` must be ``True``."""
        view = AggregateEventView()
        assert view.no_material_events is True

    def test_ei_output_default_aggregate_view(self) -> None:
        """``EventInterpretationOutput()`` default aggregate_view has no-event fields."""
        output = EventInterpretationOutput()
        assert output.aggregate_view.evidence_strength == "none"
        assert output.aggregate_view.event_count == 0
        assert output.aggregate_view.no_material_events is True

    def test_explicit_values_override_defaults(self) -> None:
        """Explicitly setting evidence fields overrides defaults."""
        view = AggregateEventView(
            overall_bias="bullish",
            event_conflict=False,
            evidence_strength="strong",
            event_count=5,
            no_material_events=False,
        )
        assert view.evidence_strength == "strong"
        assert view.event_count == 5
        assert view.no_material_events is False


# ===========================================================================
# Test 2: FDC differentiates no-event from negative-signal
# ===========================================================================


class TestFDCSystemPromptNoEventPolicy:
    """FDC system prompt must include no-event policy and source_type consideration."""

    def test_system_prompt_contains_no_event_policy(self) -> None:
        """System prompt must mention 'No-Event Policy' section."""
        agent = FinalDecisionComposerAgent(
            provider_client=MagicMock(),
        )
        prompt = agent._build_system_prompt()
        assert "No-Event Policy" in prompt
        assert "no_material_events" in prompt
        assert "negative signal" in prompt.lower()

    def test_system_prompt_contains_source_type_consideration(self) -> None:
        """System prompt must mention 'Source Type Consideration' section."""
        agent = FinalDecisionComposerAgent(
            provider_client=MagicMock(),
        )
        prompt = agent._build_system_prompt()
        assert "Source Type Consideration" in prompt
        assert "market_overlay" in prompt
        assert "core" in prompt

    def test_system_prompt_differentiates_no_event_from_negative(self) -> None:
        """System prompt must explicitly state that no-event != negative signal."""
        agent = FinalDecisionComposerAgent(
            provider_client=MagicMock(),
        )
        prompt = agent._build_system_prompt()
        assert "not the same as" in prompt.lower() or "NOT the same" in prompt


# ===========================================================================
# Test 3: market_overlay no-event doesn't auto-HOLD
# ===========================================================================


class TestFDCUserPromptSourceTypeDisplay:
    """FDC user prompt must display source_type and evidence quality fields."""

    def _make_request(self, source_type: str = "core") -> AgentExecutionRequest:
        """Build a minimal ``AgentExecutionRequest`` with EI output."""
        context = AssembledContext(
            source_type=source_type,
        )
        ei_output = EventInterpretationOutput(
            aggregate_view=AggregateEventView(
                overall_bias="neutral",
                event_conflict=False,
                evidence_strength="none",
                event_count=0,
                no_material_events=True,
            ),
        )
        return AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test-corr",
            context=context,
            symbol="005930",
            market="KRX",
            source_type=source_type,
            event_interpretation_output=ei_output,
        )

    def test_user_prompt_contains_source_type(self) -> None:
        """User prompt must include the source_type line."""
        agent = FinalDecisionComposerAgent(
            provider_client=MagicMock(),
        )
        request = self._make_request(source_type="market_overlay")
        prompt = agent._build_user_prompt(request)
        assert "Source type: market_overlay" in prompt

    def test_user_prompt_contains_evidence_strength(self) -> None:
        """User prompt must include evidence_strength from EI output."""
        agent = FinalDecisionComposerAgent(
            provider_client=MagicMock(),
        )
        request = self._make_request()
        prompt = agent._build_user_prompt(request)
        assert "Evidence strength: none" in prompt

    def test_user_prompt_contains_event_count(self) -> None:
        """User prompt must include event_count from EI output."""
        agent = FinalDecisionComposerAgent(
            provider_client=MagicMock(),
        )
        request = self._make_request()
        prompt = agent._build_user_prompt(request)
        assert "Event count: 0" in prompt

    def test_user_prompt_contains_no_material_events(self) -> None:
        """User prompt must include no_material_events from EI output."""
        agent = FinalDecisionComposerAgent(
            provider_client=MagicMock(),
        )
        request = self._make_request()
        prompt = agent._build_user_prompt(request)
        assert "No material events: True" in prompt

    def test_market_overlay_source_type_in_prompt(self) -> None:
        """market_overlay symbol must show source_type in user prompt."""
        agent = FinalDecisionComposerAgent(
            provider_client=MagicMock(),
        )
        request = self._make_request(source_type="market_overlay")
        prompt = agent._build_user_prompt(request)
        assert "Source type: market_overlay" in prompt
        # Verify the EI section also renders
        assert "=== Event Interpretation Output ===" in prompt
        assert "Evidence strength: none" in prompt

    def test_core_source_type_in_prompt(self) -> None:
        """core symbol must show source_type in user prompt."""
        agent = FinalDecisionComposerAgent(
            provider_client=MagicMock(),
        )
        request = self._make_request(source_type="core")
        prompt = agent._build_user_prompt(request)
        assert "Source type: core" in prompt


# ===========================================================================
# Test 4: No regression — AgentExecutionRequest source_type propagation
# ===========================================================================


class TestAgentExecutionRequestSourceType:
    """``AgentExecutionRequest`` must propagate ``source_type`` correctly."""

    def test_default_source_type_is_core(self) -> None:
        """Default ``source_type`` must be ``"core"``."""
        context = AssembledContext()
        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test",
            context=context,
        )
        assert request.source_type == "core"

    def test_explicit_source_type(self) -> None:
        """Explicit ``source_type`` must be preserved."""
        context = AssembledContext()
        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test",
            context=context,
            source_type="market_overlay",
        )
        assert request.source_type == "market_overlay"

    def test_all_source_types_accepted(self) -> None:
        """All valid source_type values must be accepted."""
        context = AssembledContext()
        for st in ("core", "held_position", "event_overlay", "market_overlay"):
            request = AgentExecutionRequest(
                decision_context_id=uuid4(),
                correlation_id="test",
                context=context,
                source_type=st,
            )
            assert request.source_type == st

    def test_source_type_in_user_prompt_without_ei(self) -> None:
        """Source type must appear in user prompt even without EI output."""
        agent = FinalDecisionComposerAgent(
            provider_client=MagicMock(),
        )
        context = AssembledContext(
            source_type="event_overlay",
        )
        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test",
            context=context,
            symbol="005930",
            market="KRX",
            source_type="event_overlay",
        )
        prompt = agent._build_user_prompt(request)
        assert "Source type: event_overlay" in prompt

    def test_assembled_context_source_type_propagation(self) -> None:
        """``AssembledContext`` must propagate ``source_type``."""
        context = AssembledContext(
            source_type="market_overlay",
        )
        assert context.source_type == "market_overlay"

    def test_assembled_context_default_source_type(self) -> None:
        """``AssembledContext`` default ``source_type`` must be ``"core"``."""
        context = AssembledContext()
        assert context.source_type == "core"
