"""Tests for deterministic EI summary and output finalization."""


from __future__ import annotations

from uuid import UUID

from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.services.ai_agents.event_interpretation import (
    _build_summary_text,
    _finalize_ei_output,
    _reconstruct_events,
)
from agent_trading.services.ai_agents.schemas import (
    EventInterpretationOutput,
    AggregateEventView,
    InterpretedEvent,
)


class TestBuildEiSummary:
    """``_build_summary_text()`` — deterministic Korean summary from EI output."""

    def test_no_material_events_neutral(self) -> None:
        """``no_material_events=True`` + ``overall_bias=neutral``."""
        output = EventInterpretationOutput(
            aggregate_view=AggregateEventView(
                no_material_events=True,
                overall_bias="neutral",
            ),
        )
        summary = _build_summary_text(output)
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
        summary = _build_summary_text(output)
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
        summary = _build_summary_text(output)
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
        summary = _build_summary_text(output)
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
        summary = _build_summary_text(output)
        assert "(1건)" in summary
        assert "중립" in summary  # summary가 비어있어도 bias는 표시

    def test_empty_events_no_material_false(self) -> None:
        """``events``가 비어있고 ``no_material_events=False``이면 Case 6 fallback."""
        output = EventInterpretationOutput(
            events=(),
            aggregate_view=AggregateEventView(
                no_material_events=False,
                overall_bias="neutral",
            ),
        )
        summary = _build_summary_text(output)
        # no_material_events=False이므로 Case 5 미충족 → Case 6 fallback
        assert "이벤트 분석을 수행할 수 없습니다" in summary

    def test_stub_output(self) -> None:
        """Stub 기본 출력 (모든 필드 기본값)."""
        output = EventInterpretationOutput()
        summary = _build_summary_text(output)
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
        summary = _build_summary_text(output)
        assert "(2건)" in summary
        assert "첫번째" in summary
        assert "부정" in summary
        assert "strong" in summary


class TestFinalizeEiOutput:
    """``_finalize_ei_output()`` — interpreted_event_count, summary_basis, summary 설정."""

    def test_finalize_normal_path_interpreted(self) -> None:
        """T1: 정상 경로 — events 있음, degraded=False → summary_basis='interpreted'."""
        output = EventInterpretationOutput(
            symbol="005930",
            events=(
                InterpretedEvent(
                    source_event_id="evt-001",
                    event_type="disclosure",
                    summary="매출 증가",
                ),
            ),
            aggregate_view=AggregateEventView(
                event_count=1,
                no_material_events=False,
                overall_bias="positive",
                evidence_strength="moderate",
            ),
            detected_event_count=1,
        )
        result = _finalize_ei_output(output, input_event_count=1)

        assert result.interpreted_event_count == 1, (
            f"Expected interpreted_event_count=1, got {result.interpreted_event_count}"
        )
        assert result.summary_basis == "interpreted", (
            f"Expected summary_basis='interpreted', got {result.summary_basis}"
        )
        assert result.summary != "", "Summary should be non-empty"
        assert "(1건)" in result.summary

    def test_finalize_degraded_with_events_interpreted_degraded(self) -> None:
        """T2: degraded + events 있음 → summary_basis='interpreted_degraded'."""
        output = EventInterpretationOutput(
            symbol="005930",
            events=(
                InterpretedEvent(
                    source_event_id="evt-001",
                    event_type="disclosure",
                    summary="부분 해석",
                ),
            ),
            aggregate_view=AggregateEventView(
                event_count=1,
                no_material_events=False,
                overall_bias="neutral",
                evidence_strength="weak",
                interpretation_incomplete=True,
                degraded_reason="provider_error",
            ),
            detected_event_count=1,
        )
        result = _finalize_ei_output(output, input_event_count=2)

        assert result.interpreted_event_count == 1, (
            f"Expected interpreted_event_count=1, got {result.interpreted_event_count}"
        )
        assert result.summary_basis == "interpreted_degraded", (
            f"Expected summary_basis='interpreted_degraded', got {result.summary_basis}"
        )
        assert result.summary != "", "Summary should be non-empty"

    def test_finalize_self_contradiction_detected_only(self) -> None:
        """T3: Self-contradiction — events=[], degraded=True, detected=0, input>0 → 'detected_only'."""
        output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                event_count=0,
                no_material_events=True,
                overall_bias="neutral",
                evidence_strength="none",
                interpretation_incomplete=True,
                degraded_reason="self_contradiction_corrected",
            ),
            detected_event_count=0,  # LLM raw 보존
        )
        result = _finalize_ei_output(output, input_event_count=3)

        assert result.interpreted_event_count == 0, (
            f"Expected interpreted_event_count=0, got {result.interpreted_event_count}"
        )
        assert result.summary_basis == "detected_only", (
            f"Expected summary_basis='detected_only', got {result.summary_basis}"
        )
        assert "(3건)" in result.summary, (
            f"Expected '(3건)' in summary, got: {result.summary}"
        )

    def test_finalize_exception_fallback_detected_only(self) -> None:
        """T4: Exception fallback — events=[], degraded=True, detected>0, input>0 → 'detected_only'."""
        output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                event_count=2,
                no_material_events=False,
                overall_bias="neutral",
                evidence_strength="weak",
                interpretation_incomplete=True,
                degraded_reason="provider_error",
            ),
            detected_event_count=2,  # 시스템이 감지
        )
        result = _finalize_ei_output(output, input_event_count=2)

        assert result.interpreted_event_count == 0, (
            f"Expected interpreted_event_count=0, got {result.interpreted_event_count}"
        )
        # detected=2, input_event_count=2, events=() → "detected_only"
        assert result.summary_basis == "detected_only", (
            f"Expected summary_basis='detected_only', got {result.summary_basis}"
        )

    def test_finalize_no_event_none(self) -> None:
        """T5: 입력 없음, 출력 없음 → summary_basis='none'."""
        output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                event_count=0,
                no_material_events=True,
                overall_bias="neutral",
                evidence_strength="none",
            ),
            detected_event_count=0,
        )
        result = _finalize_ei_output(output, input_event_count=0)

        assert result.interpreted_event_count == 0, (
            f"Expected interpreted_event_count=0, got {result.interpreted_event_count}"
        )
        assert result.summary_basis == "none", (
            f"Expected summary_basis='none', got {result.summary_basis}"
        )
        assert "유의미한 신규 이벤트 없음" in result.summary

    def test_finalize_aggregate_view_event_count_synced(self) -> None:
        """T6: __post_init__에서 detected_event_count가 aggregate_view.event_count와 동기화 (Phase 3-1: max() 방식)."""
        # aggregate_view.event_count > 0 이지만 detected_event_count=0 인 경우
        # __post_init__ (max 방식)이 자동으로 detected_event_count를 설정
        output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                event_count=3,
                no_material_events=False,
                overall_bias="neutral",
                evidence_strength="weak",
            ),
            # detected_event_count 명시하지 않음 → 기본값 0
        )
        # __post_init__에서 detected_event_count=3으로 설정
        assert output.detected_event_count == 3, (
            f"Expected detected_event_count=3 (synced from aggregate_view), got {output.detected_event_count}"
        )

        result = _finalize_ei_output(output, input_event_count=0)

        assert result.interpreted_event_count == 0, (
            f"Expected interpreted_event_count=0, got {result.interpreted_event_count}"
        )
        # detected=3, events=() → not has_events AND detected>0 → "detected_only"
        assert result.summary_basis == "detected_only", (
            f"Expected summary_basis='detected_only', got {result.summary_basis}"
        )

    # ──────────────────────────────────────────────────────────────
    # 신규 테스트: summary_basis semantics 보정 (2026-05-22)
    # ──────────────────────────────────────────────────────────────

    def test_detected_only_provider_error(self) -> None:
        """T7: Provider error — detected>0, events=[], degraded_reason='provider_error' → 'detected_only'."""
        output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                event_count=3,
                no_material_events=False,
                overall_bias="neutral",
                evidence_strength="weak",
                interpretation_incomplete=True,
                degraded_reason="provider_error",
            ),
            detected_event_count=3,
        )
        result = _finalize_ei_output(output, input_event_count=3)

        assert result.interpreted_event_count == 0, (
            f"Expected interpreted_event_count=0, got {result.interpreted_event_count}"
        )
        assert result.summary_basis == "detected_only", (
            f"Expected summary_basis='detected_only', got {result.summary_basis}"
        )

    def test_detected_only_self_contradiction(self) -> None:
        """T8: Self-contradiction — detected=0, events=[], degraded_reason='self_contradiction_corrected', input>0 → 'detected_only'."""
        output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                event_count=0,
                no_material_events=True,
                overall_bias="neutral",
                evidence_strength="none",
                interpretation_incomplete=True,
                degraded_reason="self_contradiction_corrected",
            ),
            detected_event_count=0,
        )
        result = _finalize_ei_output(output, input_event_count=3)

        assert result.interpreted_event_count == 0, (
            f"Expected interpreted_event_count=0, got {result.interpreted_event_count}"
        )
        # input_event_count=3, detected=0 → not has_events AND (detected>0 OR input_event_count>0) → True
        assert result.summary_basis == "detected_only", (
            f"Expected summary_basis='detected_only', got {result.summary_basis}"
        )

    def test_none_truly_no_event(self) -> None:
        """T9: Truly no event — detected=0, events=[], input_event_count=0 → 'none'."""
        output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                event_count=0,
                no_material_events=True,
                overall_bias="neutral",
                evidence_strength="none",
            ),
            detected_event_count=0,
        )
        result = _finalize_ei_output(output, input_event_count=0)

        assert result.interpreted_event_count == 0, (
            f"Expected interpreted_event_count=0, got {result.interpreted_event_count}"
        )
        # not has_events AND detected==0 AND input_event_count==0 → "none"
        assert result.summary_basis == "none", (
            f"Expected summary_basis='none', got {result.summary_basis}"
        )

    def test_interpreted_normal(self) -> None:
        """T10: Normal path — detected>0, events=[InterpretedEvent(...)], input>0 → 'interpreted'."""
        output = EventInterpretationOutput(
            symbol="005930",
            events=(
                InterpretedEvent(
                    source_event_id="evt-001",
                    event_type="disclosure",
                    summary="매출 증가",
                ),
            ),
            aggregate_view=AggregateEventView(
                event_count=2,
                no_material_events=False,
                overall_bias="positive",
                evidence_strength="moderate",
            ),
            detected_event_count=2,
        )
        result = _finalize_ei_output(output, input_event_count=3)

        assert result.interpreted_event_count == 1, (
            f"Expected interpreted_event_count=1, got {result.interpreted_event_count}"
        )
        assert result.summary_basis == "interpreted", (
            f"Expected summary_basis='interpreted', got {result.summary_basis}"
        )

    def test_interpreted_degraded(self) -> None:
        """T11: Degraded + events — detected>0, events=[InterpretedEvent(...)], degraded_reason='partial_failure' → 'interpreted_degraded'."""
        output = EventInterpretationOutput(
            symbol="005930",
            events=(
                InterpretedEvent(
                    source_event_id="evt-001",
                    event_type="news",
                    summary="부분 해석",
                ),
            ),
            aggregate_view=AggregateEventView(
                event_count=2,
                no_material_events=False,
                overall_bias="neutral",
                evidence_strength="weak",
                interpretation_incomplete=True,
                degraded_reason="partial_failure",
            ),
            detected_event_count=2,
        )
        result = _finalize_ei_output(output, input_event_count=3)

        assert result.interpreted_event_count == 1, (
            f"Expected interpreted_event_count=1, got {result.interpreted_event_count}"
        )
        # has_events=True AND degraded=True → "interpreted_degraded"
        assert result.summary_basis == "interpreted_degraded", (
            f"Expected summary_basis='interpreted_degraded', got {result.summary_basis}"
        )


class TestReconstruction:
    """``_reconstruct_events()`` + ``_finalize_ei_output()`` with reconstruction."""

    # ── Helpers ──

    def _make_input_event(
        self,
        event_id: str = "evt-001",
        event_type: str = "disclosure",
        source_name: str = "test_source",
        source_reliability_tier: str = "T2",
        direction: str = "neutral",
        headline: str | None = None,
        body_summary: str | None = None,
    ) -> ExternalEventEntity:
        return ExternalEventEntity(
            event_id=UUID(int=0),  # dummy UUID, overridden by kwargs
            event_type=event_type,
            source_name=source_name,
            published_at=None,  # type: ignore[arg-type]
            source_reliability_tier=source_reliability_tier,
            source_event_id=event_id,
            direction=direction,
            headline=headline,
            body_summary=body_summary,
        )

    # ── _reconstruct_events tests ──

    def test_reconstruct_events_basic(self) -> None:
        """기본 reconstruction: 3개 입력 → 3개 reconstructed events."""
        events = (
            self._make_input_event(event_id="evt-001", event_type="disclosure", headline="매출 호조"),
            self._make_input_event(event_id="evt-002", event_type="news", headline="경쟁사 신제품"),
            self._make_input_event(event_id="evt-003", event_type="macro", headline="금리 인상"),
        )
        result = _reconstruct_events(events)
        assert len(result) == 3
        for ev in result:
            assert ev.is_reconstructed is True
            # LLM-only fields must be defaults
            assert ev.confidence == 0.0
            assert ev.novelty == "medium"
            assert ev.supports_entry is False
            assert ev.supports_exit is False
            assert ev.risk_flags == ()
            assert ev.reason_codes == ()
        assert result[0].source_event_id == "evt-001"
        assert result[0].summary == "매출 호조"

    def test_reconstruct_events_empty_input(self) -> None:
        """빈 입력 → 빈 tuple."""
        assert _reconstruct_events(()) == ()

    def test_reconstruct_events_default_fields(self) -> None:
        """reconstructed event는 is_reconstructed=True, LLM 필드는 기본값."""
        events = (self._make_input_event(),)
        result = _reconstruct_events(events)
        ev = result[0]
        assert ev.is_reconstructed is True
        assert ev.impact_horizon == "swing"
        assert ev.confidence == 0.0
        assert ev.novelty == "medium"
        assert ev.supports_entry is False
        assert ev.supports_exit is False

    def test_reconstruct_events_summary_from_headline(self) -> None:
        """headline이 있으면 summary에 사용."""
        events = (self._make_input_event(headline="주요 뉴스"),)
        result = _reconstruct_events(events)
        assert result[0].summary == "주요 뉴스"

    def test_reconstruct_events_summary_from_body(self) -> None:
        """headline이 없고 body_summary만 있으면 body_summary를 summary에 사용."""
        events = (self._make_input_event(headline=None, body_summary="본문 요약 내용"),)
        result = _reconstruct_events(events)
        assert result[0].summary == "본문 요약 내용"

    def test_reconstruct_events_summary_body_truncation(self) -> None:
        """body_summary가 200자 초과면 truncation."""
        long_body = "x" * 250
        events = (self._make_input_event(headline=None, body_summary=long_body),)
        result = _reconstruct_events(events)
        assert len(result[0].summary) <= 204  # 200 + "..."

    def test_reconstruct_events_source_event_id_fallback(self) -> None:
        """source_event_id가 None이면 str(event_id) 사용."""
        ev = ExternalEventEntity(
            event_id=UUID(int=12345),
            event_type="news",
            source_name="test",
            published_at=None,  # type: ignore[arg-type]
            source_event_id=None,
        )
        result = _reconstruct_events((ev,))
        assert result[0].source_event_id == str(UUID(int=12345))

    def test_reconstruct_events_direction_mapped(self) -> None:
        """impact_direction은 source의 direction을 그대로 사용."""
        events = (self._make_input_event(direction="positive"),)
        result = _reconstruct_events(events)
        assert result[0].impact_direction == "positive"

    # ── _finalize_ei_output reconstruction integration tests ──

    def test_reconstruction_provider_error(self) -> None:
        """provider_error + input events 3건 → reconstructed events 3개 생성."""
        recent = (
            self._make_input_event(event_id="evt-001", headline="첫번째"),
            self._make_input_event(event_id="evt-002", headline="두번째"),
            self._make_input_event(event_id="evt-003", headline="세번째"),
        )
        output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                event_count=3,
                no_material_events=False,
                overall_bias="neutral",
                evidence_strength="weak",
                interpretation_incomplete=True,
                degraded_reason="provider_error",
            ),
            detected_event_count=3,
        )
        result = _finalize_ei_output(
            output,
            input_event_count=3,
            recent_events=recent,
        )

        assert len(result.events) == 3, (
            f"Expected 3 reconstructed events, got {len(result.events)}"
        )
        assert all(e.is_reconstructed for e in result.events), (
            "All events should be reconstructed"
        )
        assert result.interpreted_event_count == 3
        assert result.summary_basis == "detected_only", (
            f"Expected summary_basis='detected_only', got {result.summary_basis}"
        )
        assert "AI 분석이 완료되지 않았으나" in result.summary, (
            f"Expected reconstruction summary, got: {result.summary}"
        )

    def test_reconstruction_self_contradiction(self) -> None:
        """self-contradiction guard + input events 2건 → reconstructed events 2개."""
        recent = (
            self._make_input_event(event_id="evt-001", headline="첫번째"),
            self._make_input_event(event_id="evt-002", headline="두번째"),
        )
        output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                event_count=0,
                no_material_events=True,
                overall_bias="neutral",
                evidence_strength="none",
                interpretation_incomplete=True,
                degraded_reason="self_contradiction_corrected",
            ),
            detected_event_count=0,
        )
        result = _finalize_ei_output(
            output,
            input_event_count=2,
            recent_events=recent,
        )

        assert len(result.events) == 2, (
            f"Expected 2 reconstructed events, got {len(result.events)}"
        )
        assert all(e.is_reconstructed for e in result.events)
        assert result.summary_basis == "detected_only"

    def test_no_reconstruction_when_no_input_events(self) -> None:
        """input_event_count=0이고 events=()이면 reconstruction 안 함 → summary_basis='none'."""
        result = _finalize_ei_output(
            EventInterpretationOutput(),
            input_event_count=0,
            recent_events=(),
        )
        assert len(result.events) == 0
        assert result.summary_basis == "none"

    def test_reconstruction_summary_basis_detected_only(self) -> None:
        """reconstructed events가 있어도 summary_basis='detected_only'."""
        recent = (self._make_input_event(event_id="evt-001"),)
        output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                event_count=1,
                no_material_events=False,
                overall_bias="neutral",
                evidence_strength="weak",
                interpretation_incomplete=True,
                degraded_reason="provider_error",
            ),
            detected_event_count=1,
        )
        result = _finalize_ei_output(
            output,
            input_event_count=1,
            recent_events=recent,
        )
        assert result.summary_basis == "detected_only"

    def test_reconstruction_summary_text(self) -> None:
        """reconstructed events 포함 summary에 'AI 분석이 완료되지 않았으나' 포함."""
        recent = (self._make_input_event(event_id="evt-001", headline="테스트"),)
        output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                event_count=1,
                no_material_events=False,
                overall_bias="neutral",
                evidence_strength="weak",
                interpretation_incomplete=True,
                degraded_reason="provider_error",
            ),
            detected_event_count=1,
        )
        result = _finalize_ei_output(
            output,
            input_event_count=1,
            recent_events=recent,
        )
        assert "AI 분석이 완료되지 않았으나" in result.summary
        assert "1건" in result.summary

    def test_normal_path_no_reconstruction(self) -> None:
        """정상 경로(events 이미 있음)에서는 reconstruction 영향 없음 → summary_basis='interpreted'."""
        recent = (self._make_input_event(event_id="evt-001", headline="테스트"),)
        output = EventInterpretationOutput(
            symbol="005930",
            events=(
                InterpretedEvent(
                    source_event_id="evt-001",
                    event_type="disclosure",
                    summary="매출 증가",
                ),
            ),
            aggregate_view=AggregateEventView(
                event_count=1,
                no_material_events=False,
                overall_bias="positive",
                evidence_strength="moderate",
            ),
            detected_event_count=1,
        )
        result = _finalize_ei_output(
            output,
            input_event_count=1,
            recent_events=recent,
        )

        assert len(result.events) == 1
        assert result.events[0].is_reconstructed is False  # original event
        assert result.summary_basis == "interpreted"
        assert "AI 분석이 완료되지 않았으나" not in result.summary
