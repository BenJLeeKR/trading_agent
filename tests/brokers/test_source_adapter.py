"""Tests for SourceAdapter protocol and RawEvent dataclass."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_trading.brokers.source_adapter import RawEvent, SourceAdapter
from agent_trading.domain.enums import SourceReliabilityTier


class TestRawEvent:
    """RawEvent dataclass field requirements."""

    def test_required_fields(self) -> None:
        """All required fields must be provided."""
        now = datetime.now(timezone.utc)
        event = RawEvent(
            source_name="test_source",
            source_event_id="evt-001",
            event_type="test_event",
            published_at=now,
            ingested_at=now,
            source_reliability_tier=SourceReliabilityTier.T3_MEDIA.value,
            raw_payload={"key": "value"},
        )
        assert event.source_name == "test_source"
        assert event.source_event_id == "evt-001"
        assert event.event_type == "test_event"
        assert event.published_at == now
        assert event.ingested_at == now
        assert event.source_reliability_tier == SourceReliabilityTier.T3_MEDIA.value
        assert event.raw_payload == {"key": "value"}

    def test_optional_fields_default_none(self) -> None:
        """Optional fields default to None."""
        now = datetime.now(timezone.utc)
        event = RawEvent(
            source_name="test",
            source_event_id="evt-001",
            event_type="test",
            published_at=now,
            ingested_at=now,
            source_reliability_tier="T3",
            raw_payload={},
        )
        assert event.symbol is None
        assert event.issuer_code is None
        assert event.market is None
        assert event.headline is None
        assert event.body is None

    def test_frozen_dataclass(self) -> None:
        """RawEvent is frozen (immutable)."""
        now = datetime.now(timezone.utc)
        event = RawEvent(
            source_name="test",
            source_event_id="evt-001",
            event_type="test",
            published_at=now,
            ingested_at=now,
            source_reliability_tier="T3",
            raw_payload={},
        )
        with pytest.raises(AttributeError):
            event.source_name = "changed"  # type: ignore[misc]

    def test_slots_attribute(self) -> None:
        """RawEvent has __slots__ defined."""
        assert hasattr(RawEvent, "__slots__"), "RawEvent should have __slots__"


class TestSourceAdapterProtocol:
    """SourceAdapter protocol conformance."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """SourceAdapter is runtime-checkable."""
        assert hasattr(SourceAdapter, "__instancecheck__")

    def test_protocol_methods_exist(self) -> None:
        """SourceAdapter defines the expected methods."""
        expected = {"fetch", "normalize", "generate_dedup_key"}
        protocol_methods = {
            name for name in dir(SourceAdapter) if not name.startswith("_")
        }
        assert expected.issubset(protocol_methods), (
            f"Missing methods: {expected - protocol_methods}"
        )

    def test_protocol_properties_exist(self) -> None:
        """SourceAdapter defines source_name and reliability_tier properties."""
        assert hasattr(SourceAdapter, "source_name")
        assert hasattr(SourceAdapter, "reliability_tier")
