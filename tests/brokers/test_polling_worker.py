"""Tests for PollingWorker."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest

from agent_trading.brokers.dedup import DedupKeyGenerator
from agent_trading.brokers.polling_worker import PollingConfig, PollingWorker
from agent_trading.brokers.source_adapter import RawEvent, SourceAdapter
from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.domain.enums import SourceReliabilityTier
from agent_trading.repositories.contracts import ExternalEventRepository


# ---------------------------------------------------------------------------
# Stub adapter for testing
# ---------------------------------------------------------------------------

class _StubAdapter:
    """A stub SourceAdapter for PollingWorker tests."""

    source_name = "stub_source"
    reliability_tier = SourceReliabilityTier.T3_MEDIA

    def __init__(self, raw_events: list[RawEvent] | None = None) -> None:
        self._raw_events = raw_events or []
        self.fetch_count = 0

    async def fetch(self) -> Sequence[RawEvent]:
        self.fetch_count += 1
        return list(self._raw_events)

    async def normalize(self, raw: RawEvent) -> ExternalEventEntity:
        return ExternalEventEntity(
            event_id=uuid4(),
            event_type=raw.event_type,
            source_name=raw.source_name,
            published_at=raw.published_at,
            source_reliability_tier=raw.source_reliability_tier,
            source_event_id=raw.source_event_id,
            issuer_code=raw.issuer_code,
            symbol=raw.symbol,
            market=raw.market,
            ingested_at=raw.ingested_at,
            effective_at=raw.published_at,
            severity="medium",
            direction="neutral",
            headline=raw.headline,
            body_summary=raw.body,
            raw_payload_uri=None,
            dedup_key_hash=self.generate_dedup_key(raw),
            supersedes_event_id=None,
            metadata={},
            created_at=None,
        )

    def generate_dedup_key(self, raw: RawEvent) -> str:
        return DedupKeyGenerator.generate_from_raw(
            source_name=raw.source_name,
            source_event_id=raw.source_event_id,
            event_type=raw.event_type,
            symbol=raw.symbol,
            issuer_code=raw.issuer_code,
        )


# ---------------------------------------------------------------------------
# Stub in-memory repository for testing
# ---------------------------------------------------------------------------

class _StubExternalEventRepo:
    """Minimal in-memory ExternalEventRepository for testing."""

    def __init__(self) -> None:
        self._items: dict[str, ExternalEventEntity] = {}

    async def add(self, event: ExternalEventEntity) -> ExternalEventEntity:
        self._items[event.event_id] = event
        return event

    async def find_by_dedup_key(self, dedup_key_hash: str) -> ExternalEventEntity | None:
        for item in self._items.values():
            if item.dedup_key_hash == dedup_key_hash:
                return item
        return None

    async def get(self, event_id: Any) -> Any:
        return self._items.get(event_id)

    async def list_by_symbol(self, *args: Any, **kwargs: Any) -> Any:
        return []

    async def list_by_type(self, *args: Any, **kwargs: Any) -> Any:
        return []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPollingWorker:
    """PollingWorker lifecycle and poll cycle."""

    @pytest.mark.asyncio
    async def test_poll_once_returns_zero_when_no_events(self) -> None:
        """poll_once() returns 0 when adapter returns no events."""
        adapter = _StubAdapter(raw_events=[])
        config = PollingConfig(source_name="stub", interval_seconds=60)
        repo = _StubExternalEventRepo()
        worker = PollingWorker(adapter, config, repo)

        count = await worker.poll_once()
        assert count == 0

    @pytest.mark.asyncio
    async def test_poll_once_ingests_new_events(self) -> None:
        """poll_once() ingests new events and returns the count."""
        now = datetime.now(timezone.utc)
        raw = RawEvent(
            source_name="stub_source",
            source_event_id="evt-001",
            event_type="test",
            published_at=now,
            ingested_at=now,
            source_reliability_tier="T3",
            raw_payload={},
        )
        adapter = _StubAdapter(raw_events=[raw])
        config = PollingConfig(source_name="stub", interval_seconds=60)
        repo = _StubExternalEventRepo()
        worker = PollingWorker(adapter, config, repo)

        count = await worker.poll_once()
        assert count == 1

    @pytest.mark.asyncio
    async def test_poll_once_deduplicates(self) -> None:
        """poll_once() skips events that already exist by dedup key."""
        now = datetime.now(timezone.utc)
        raw = RawEvent(
            source_name="stub_source",
            source_event_id="evt-001",
            event_type="test",
            published_at=now,
            ingested_at=now,
            source_reliability_tier="T3",
            raw_payload={},
        )
        adapter = _StubAdapter(raw_events=[raw])
        config = PollingConfig(source_name="stub", interval_seconds=60)
        repo = _StubExternalEventRepo()
        worker = PollingWorker(adapter, config, repo)

        # First poll: ingest
        count1 = await worker.poll_once()
        assert count1 == 1

        # Second poll: same event → dedup
        count2 = await worker.poll_once()
        assert count2 == 0

    @pytest.mark.asyncio
    async def test_poll_once_multiple_events(self) -> None:
        """poll_once() handles multiple events in a single poll."""
        now = datetime.now(timezone.utc)
        events = [
            RawEvent(
                source_name="stub",
                source_event_id=f"evt-{i:03d}",
                event_type="test",
                published_at=now,
                ingested_at=now,
                source_reliability_tier="T3",
                raw_payload={},
            )
            for i in range(5)
        ]
        adapter = _StubAdapter(raw_events=events)
        config = PollingConfig(source_name="stub", interval_seconds=60)
        repo = _StubExternalEventRepo()
        worker = PollingWorker(adapter, config, repo)

        count = await worker.poll_once()
        assert count == 5

    @pytest.mark.asyncio
    async def test_poll_once_partial_dedup(self) -> None:
        """poll_once() handles partial dedup (some new, some existing)."""
        now = datetime.now(timezone.utc)
        # First event
        raw1 = RawEvent(
            source_name="stub",
            source_event_id="evt-001",
            event_type="test",
            published_at=now,
            ingested_at=now,
            source_reliability_tier="T3",
            raw_payload={},
        )
        adapter = _StubAdapter(raw_events=[raw1])
        config = PollingConfig(source_name="stub", interval_seconds=60)
        repo = _StubExternalEventRepo()
        worker = PollingWorker(adapter, config, repo)

        # Ingest first event
        await worker.poll_once()

        # Second poll: one duplicate + one new
        raw2 = RawEvent(
            source_name="stub",
            source_event_id="evt-002",
            event_type="test",
            published_at=now,
            ingested_at=now,
            source_reliability_tier="T3",
            raw_payload={},
        )
        adapter._raw_events = [raw1, raw2]

        count = await worker.poll_once()
        assert count == 1  # only evt-002 is new

    @pytest.mark.asyncio
    async def test_freshness_budget_applied(self) -> None:
        """poll_once() applies freshness budget and marks stale events."""
        now = datetime.now(timezone.utc)
        stale_raw = RawEvent(
            source_name="stub",
            source_event_id="evt-stale",
            event_type="test",
            published_at=now - timedelta(hours=2),  # 2 hours old
            ingested_at=now,
            source_reliability_tier="T3",
            raw_payload={},
        )
        adapter = _StubAdapter(raw_events=[stale_raw])
        config = PollingConfig(
            source_name="stub",
            interval_seconds=60,
            freshness_max_seconds=600,  # 10 minutes
        )
        repo = _StubExternalEventRepo()
        worker = PollingWorker(adapter, config, repo)

        count = await worker.poll_once()
        assert count == 1

        # Verify the stored event has stale=True in metadata
        stored = await repo.find_by_dedup_key(
            adapter.generate_dedup_key(stale_raw)
        )
        assert stored is not None
        assert stored.metadata.get("stale") is True

    @pytest.mark.asyncio
    async def test_fresh_event_not_stale(self) -> None:
        """poll_once() marks fresh events as not stale."""
        now = datetime.now(timezone.utc)
        fresh_raw = RawEvent(
            source_name="stub",
            source_event_id="evt-fresh",
            event_type="test",
            published_at=now - timedelta(minutes=2),  # 2 minutes old
            ingested_at=now,
            source_reliability_tier="T3",
            raw_payload={},
        )
        adapter = _StubAdapter(raw_events=[fresh_raw])
        config = PollingConfig(
            source_name="stub",
            interval_seconds=60,
            freshness_max_seconds=600,
        )
        repo = _StubExternalEventRepo()
        worker = PollingWorker(adapter, config, repo)

        await worker.poll_once()
        stored = await repo.find_by_dedup_key(
            adapter.generate_dedup_key(fresh_raw)
        )
        assert stored is not None
        assert stored.metadata.get("stale") is False

    @pytest.mark.asyncio
    async def test_source_name_property(self) -> None:
        """source_name property returns config source_name."""
        config = PollingConfig(source_name="test_source", interval_seconds=60)
        adapter = _StubAdapter()
        repo = _StubExternalEventRepo()
        worker = PollingWorker(adapter, config, repo)
        assert worker.source_name == "test_source"

    @pytest.mark.asyncio
    async def test_is_running_initially_false(self) -> None:
        """is_running is False before run() is called."""
        config = PollingConfig(source_name="test", interval_seconds=60)
        adapter = _StubAdapter()
        repo = _StubExternalEventRepo()
        worker = PollingWorker(adapter, config, repo)
        assert not worker.is_running
