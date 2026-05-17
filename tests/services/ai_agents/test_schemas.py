"""Tests for AI agent schemas — AggregateEventView validation and logging."""

import logging

from agent_trading.services.ai_agents.schemas import AggregateEventView


class TestAggregateEventViewTopReasonCodes:
    """AggregateEventView.top_reason_codes validation tests."""

    def test_default_empty(self):
        """top_reason_codes default value is ()."""
        view = AggregateEventView()
        assert view.top_reason_codes == ()

    def test_with_values(self):
        """top_reason_codes can be assigned values."""
        view = AggregateEventView(top_reason_codes=("code1", "code2"))
        assert view.top_reason_codes == ("code1", "code2")

    def test_empty_with_events_logs_warning(self, caplog):
        """When event_count > 0 and top_reason_codes is empty, a warning is logged."""
        caplog.set_level(logging.WARNING)
        AggregateEventView(
            top_reason_codes=(),
            event_count=3,
        )
        assert any("top_reason_codes" in record.message for record in caplog.records), (
            "Warning log should mention top_reason_codes"
        )

    def test_empty_no_events_no_warning(self, caplog):
        """When event_count=0, empty top_reason_codes should NOT log a warning."""
        caplog.set_level(logging.WARNING)
        AggregateEventView(
            top_reason_codes=(),
            event_count=0,
        )
        assert not any("top_reason_codes" in record.message for record in caplog.records), (
            "No warning expected when event_count=0"
        )

    def test_non_empty_with_events_no_warning(self, caplog):
        """When top_reason_codes has values, no warning should be logged."""
        caplog.set_level(logging.WARNING)
        AggregateEventView(
            top_reason_codes=("code1",),
            event_count=3,
        )
        assert not any("top_reason_codes" in record.message for record in caplog.records)
