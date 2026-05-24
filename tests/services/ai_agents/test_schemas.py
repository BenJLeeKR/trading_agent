"""Tests for AI agent schemas — AggregateEventView validation and logging."""

import logging

from agent_trading.services.ai_agents.schemas import (
    AggregateEventView,
    EventInterpretationOutput,
)


class TestAggregateEventViewTopReasonCodes:
    """AggregateEventView.top_reason_codes validation tests.

    Phase 2: __post_init__ warning is removed from AggregateEventView.
    The warning now lives in EventInterpretationOutput.__post_init__() where
    ``detected_event_count`` is the canonical source.  ``event_count`` is
    LEGACY (LLM prompt schema compatibility only).
    """

    def test_default_empty(self):
        """top_reason_codes default value is ()."""
        view = AggregateEventView()
        assert view.top_reason_codes == ()

    def test_with_values(self):
        """top_reason_codes can be assigned values."""
        view = AggregateEventView(top_reason_codes=("code1", "code2"))
        assert view.top_reason_codes == ("code1", "code2")

    def test_aggregate_view_event_count_no_warning(self, caplog):
        """Phase 2: AggregateEventView 생성 시 event_count > 0여도 warning 없음 (제거됨)."""
        caplog.set_level(logging.WARNING)
        AggregateEventView(
            top_reason_codes=(),
            event_count=3,
        )
        # AggregateEventView.__post_init__()에서 더 이상 warning을 내보내지 않음
        assert not any("top_reason_codes" in record.message for record in caplog.records), (
            "AggregateEventView no longer logs warning for event_count>0 + empty top_reason_codes"
        )


class TestEventInterpretationOutputPostInit:
    """EventInterpretationOutput.__post_init__() validation tests.

    Phase 2:
    - max() sync (aggregate_view.event_count → detected_event_count) 제거됨.
    - Warning: detected_event_count > 0 + empty top_reason_codes → 경고 로그.
    """

    def test_detected_event_count_not_synced_from_aggregate_view(self):
        """Phase 2: detected_event_count는 더 이상 aggregate_view.event_count에서 sync되지 않음."""
        output = EventInterpretationOutput(
            aggregate_view=AggregateEventView(
                event_count=5,
                no_material_events=False,
            ),
            # detected_event_count 명시하지 않음 → 기본값 0 유지
        )
        # __post_init__에서 더 이상 sync하지 않음
        assert output.detected_event_count == 0, (
            f"Expected detected_event_count=0 (no longer synced), "
            f"got {output.detected_event_count}"
        )

    def test_post_init_warning_with_detected_event_count_and_empty_top_reason_codes(self, caplog):
        """Phase 2: Warning이 EventInterpretationOutput.__post_init__()에서 발생.

        detected_event_count > 0이고 top_reason_codes가 빈 경우 경고.
        """
        caplog.set_level(logging.WARNING)
        EventInterpretationOutput(
            detected_event_count=3,
            aggregate_view=AggregateEventView(
                top_reason_codes=(),
                no_material_events=False,
            ),
        )
        assert any("detected_event_count" in record.message for record in caplog.records), (
            "Warning log should mention detected_event_count"
        )

    def test_no_warning_when_top_reason_codes_present(self, caplog):
        """top_reason_codes에 값이 있으면 warning 없음."""
        caplog.set_level(logging.WARNING)
        EventInterpretationOutput(
            detected_event_count=3,
            aggregate_view=AggregateEventView(
                top_reason_codes=("code1",),
                no_material_events=False,
            ),
        )
        assert not any("detected_event_count" in record.message for record in caplog.records), (
            "No warning expected when top_reason_codes has values"
        )

    def test_no_warning_when_detected_event_count_zero(self, caplog):
        """detected_event_count=0이면 warning 없음."""
        caplog.set_level(logging.WARNING)
        EventInterpretationOutput(
            detected_event_count=0,
            aggregate_view=AggregateEventView(
                top_reason_codes=(),
                no_material_events=False,
            ),
        )
        assert not any("detected_event_count" in record.message for record in caplog.records), (
            "No warning expected when detected_event_count=0"
        )
