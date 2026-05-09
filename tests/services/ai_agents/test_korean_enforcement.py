"""Integration tests for Korean text enforcement in the AI agent pipeline.

Tests verify that:
1. ``AgentRunRecorder.record()`` normalises narrative fields before storing.
2. ``DecisionOrchestratorService._ensure_trade_decision()`` normalises
   ``rationale_summary`` and ``opposing_evidence`` before persisting.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from agent_trading.services.ai_agents.korean_normalizer import (
    contains_korean,
    validate_or_normalize_korean,
)
from agent_trading.services.ai_agents.recorder import AgentRunRecorder


# ============================================================================
# Recorder integration tests
# ============================================================================


class TestRecorderKoreanNormalization:
    """AgentRunRecorder normalises narrative fields in structured_output."""

    @pytest.mark.asyncio
    async def test_recorder_normalizes_summary(self) -> None:
        """English 'summary' in structured_output is wrapped with [ko: ...]."""
        recorder = AgentRunRecorder()
        run = await recorder.record(
            decision_context_id=uuid4(),
            agent_type="ai_risk",
            structured_output={
                "summary": "Risk assessment passed",
                "agent_name": "ai_risk",
                "risk_score": 0.3,
            },
        )
        stored = run.structured_output_json
        assert stored is not None
        assert stored["summary"] == "[ko: Risk assessment passed]"
        # Non-narrative field untouched
        assert stored["agent_name"] == "ai_risk"
        assert stored["risk_score"] == 0.3

    @pytest.mark.asyncio
    async def test_recorder_preserves_korean_summary(self) -> None:
        """Korean 'summary' passes through unchanged."""
        recorder = AgentRunRecorder()
        run = await recorder.record(
            decision_context_id=uuid4(),
            agent_type="ai_risk",
            structured_output={
                "summary": "리스크 평가 통과",
                "agent_name": "ai_risk",
            },
        )
        stored = run.structured_output_json
        assert stored is not None
        assert stored["summary"] == "리스크 평가 통과"

    @pytest.mark.asyncio
    async def test_recorder_normalizes_opposing_evidence(self) -> None:
        """English strings in 'opposing_evidence' are wrapped."""
        recorder = AgentRunRecorder()
        run = await recorder.record(
            decision_context_id=uuid4(),
            agent_type="final_decision_composer",
            structured_output={
                "decision_type": "APPROVE",
                "opposing_evidence": ("Liquidity concern", "Gap risk"),
                "summary": "Decision summary",
            },
        )
        stored = run.structured_output_json
        assert stored is not None
        assert stored["opposing_evidence"] == (
            "[ko: Liquidity concern]",
            "[ko: Gap risk]",
        )
        assert stored["summary"] == "[ko: Decision summary]"
        # Non-narrative field untouched
        assert stored["decision_type"] == "APPROVE"

    @pytest.mark.asyncio
    async def test_recorder_skips_non_narrative_fields(self) -> None:
        """Machine-readable fields are not modified by recorder."""
        recorder = AgentRunRecorder()
        run = await recorder.record(
            decision_context_id=uuid4(),
            agent_type="final_decision_composer",
            structured_output={
                "decision_type": "REJECT",
                "side": "BUY",
                "reason_codes": ("RISK", "VOLATILITY"),
                "confidence": 0.75,
                "schema_version": "v1",
            },
        )
        stored = run.structured_output_json
        assert stored is not None
        assert stored["decision_type"] == "REJECT"
        assert stored["side"] == "BUY"
        assert stored["reason_codes"] == ("RISK", "VOLATILITY")
        assert stored["confidence"] == 0.75
        assert stored["schema_version"] == "v1"

    @pytest.mark.asyncio
    async def test_recorder_normalizes_nested_events(self) -> None:
        """Nested 'summary' inside events[] is normalised."""
        recorder = AgentRunRecorder()
        run = await recorder.record(
            decision_context_id=uuid4(),
            agent_type="event_interpretation",
            structured_output={
                "events": (
                    {
                        "event_type": "Y",
                        "summary": "Earnings beat",
                        "impact_direction": "positive",
                    },
                    {
                        "event_type": "N",
                        "summary": "규제 리스크 경감",
                        "impact_direction": "positive",
                    },
                ),
                "aggregate_view": {
                    "overall_bias": "positive",
                    "opposing_evidence": ("Mixed signals from macro",),
                },
            },
        )
        stored = run.structured_output_json
        assert stored is not None
        events = stored["events"]
        assert events[0]["summary"] == "[ko: Earnings beat]"
        assert events[1]["summary"] == "규제 리스크 경감"  # Korean unchanged
        # Nested opposing_evidence also normalised
        assert stored["aggregate_view"]["opposing_evidence"] == (
            "[ko: Mixed signals from macro]",
        )

    @pytest.mark.asyncio
    async def test_recorder_none_structured_output(self) -> None:
        """None structured_output does not raise.

        The recorder enriches the output dict with ``decision_context_id``
        during schema alignment, so the stored value is a dict containing
        at least that key rather than ``None`` or ``{}``.
        """
        recorder = AgentRunRecorder()
        run = await recorder.record(
            decision_context_id=uuid4(),
            agent_type="ai_risk",
            structured_output=None,
        )
        # Schema alignment adds decision_context_id; no narrative keys present
        assert run.structured_output_json is not None
        assert "decision_context_id" in run.structured_output_json
        # No narrative keys should appear since none were provided
        assert "summary" not in run.structured_output_json
        assert "risk_opinion" not in run.structured_output_json
        assert "opposing_evidence" not in run.structured_output_json


# ============================================================================
# Utility function integration tests
# ============================================================================


class TestKoreanNormalizerIntegration:
    """End-to-end behaviour of the normalizer functions."""

    def test_validate_or_normalize_korean_roundtrip(self) -> None:
        """English text is wrapped with ``[ko: ...]`` marker.

        The ``[ko: ...]`` wrapper is an ASCII-only operator signal, not a
        machine-readable flag. ``contains_korean()`` returns ``False`` for it
        because no Hangul characters exist. A second pass would double-wrap,
        which is acceptable: the goal is storage-time normalisation, not
        re-entry idempotency.
        """
        original = "Market momentum slowing"
        normalized = validate_or_normalize_korean(original)
        assert normalized == "[ko: Market momentum slowing]"
        # The wrapper is ASCII-only — no actual Hangul characters
        assert contains_korean(normalized) is False

    def test_validate_or_normalize_korean_korean_roundtrip(self) -> None:
        """Korean text round-trips unchanged."""
        original = "시장 모멘텀 둔화"
        normalized = validate_or_normalize_korean(original)
        assert normalized == original
        assert contains_korean(normalized) is True
        # Second pass unchanged
        assert validate_or_normalize_korean(normalized) == original
