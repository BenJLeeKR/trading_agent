"""Tests for deterministic EI summary generation."""

from __future__ import annotations

from agent_trading.services.ai_agents.event_interpretation import _build_ei_summary
from agent_trading.services.ai_agents.schemas import (
    EventInterpretationOutput,
    AggregateEventView,
    InterpretedEvent,
)


class TestBuildEiSummary:
    """``_build_ei_summary()`` — deterministic Korean summary from EI output."""

    def test_no_material_events_neutral(self) -> None:
        """``no_material_events=True`` + ``overall_bias=neutral``."""
        output = EventInterpretationOutput(
            aggregate_view=AggregateEventView(
                no_material_events=True,
                overall_bias="neutral",
            ),
        )
        summary = _build_ei_summary(output)
        assert "유의미한 신규 이벤트 없음" in summary
        assert "중립" in summary

    def test_no_material_events_negative(self) -> None:
        """``no_material_events=True`` + ``overall_bias=negative``."""
        output = EventInterpretationOutput(
            aggregate_view=AggregateEventView(
                no_material_events=True,
                overall_bias="negative",
            ),
        )
        summary = _build_ei_summary(output)
        assert "유의미한 신규 이벤트 없음" in summary
        assert "부정" in summary

    def test_no_material_events_positive(self) -> None:
        """``no_material_events=True`` + ``overall_bias=positive``."""
        output = EventInterpretationOutput(
            aggregate_view=AggregateEventView(
                no_material_events=True,
                overall_bias="positive",
            ),
        )
        summary = _build_ei_summary(output)
        assert "유의미한 신규 이벤트 없음" in summary
        assert "긍정" in summary

    def test_with_events_and_summary(self) -> None:
        """이벤트가 있고 ``events[0].summary``가 있을 때."""
        output = EventInterpretationOutput(
            events=(
                InterpretedEvent(
                    source_event_id="evt-001",
                    event_type="disclosure",
                    summary="매출이 전년 대비 15% 증가했습니다. 영업이익도 증가 추세.",
                ),
            ),
            aggregate_view=AggregateEventView(
                no_material_events=False,
                event_count=1,
                overall_bias="positive",
                evidence_strength="moderate",
            ),
        )
        summary = _build_ei_summary(output)
        assert "(1건)" in summary
        assert "매출" in summary
        assert "긍정" in summary
        assert "moderate" in summary

    def test_with_events_empty_summary(self) -> None:
        """이벤트는 있지만 ``events[0].summary``가 빈 문자열일 때."""
        output = EventInterpretationOutput(
            events=(
                InterpretedEvent(
                    source_event_id="evt-001",
                    event_type="disclosure",
                    summary="",
                ),
            ),
            aggregate_view=AggregateEventView(
                no_material_events=False,
                event_count=1,
                overall_bias="neutral",
                evidence_strength="weak",
            ),
        )
        summary = _build_ei_summary(output)
        assert "(1건)" in summary
        assert "중립" in summary  # summary가 비어있어도 bias는 표시

    def test_empty_events_no_material_false(self) -> None:
        """``events``가 비어있고 ``no_material_events=False``이면 no-material 처리."""
        output = EventInterpretationOutput(
            events=(),
            aggregate_view=AggregateEventView(
                no_material_events=False,
                overall_bias="neutral",
            ),
        )
        summary = _build_ei_summary(output)
        assert "유의미한 신규 이벤트 없음" in summary

    def test_stub_output(self) -> None:
        """Stub 기본 출력 (모든 필드 기본값)."""
        output = EventInterpretationOutput()
        summary = _build_ei_summary(output)
        assert "유의미한 신규 이벤트 없음" in summary
        assert "중립" in summary

    def test_multiple_events(self) -> None:
        """여러 이벤트가 있을 때 첫 번째 이벤트의 summary만 사용."""
        output = EventInterpretationOutput(
            events=(
                InterpretedEvent(
                    source_event_id="evt-001",
                    event_type="disclosure",
                    summary="첫번째 이벤트 요약입니다.",
                ),
                InterpretedEvent(
                    source_event_id="evt-002",
                    event_type="news",
                    summary="두번째 이벤트 요약입니다.",
                ),
            ),
            aggregate_view=AggregateEventView(
                no_material_events=False,
                event_count=2,
                overall_bias="negative",
                evidence_strength="strong",
            ),
        )
        summary = _build_ei_summary(output)
        assert "(2건)" in summary
        assert "첫번째" in summary
        assert "부정" in summary
        assert "strong" in summary
