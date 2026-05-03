"""Async polling worker for external event ingestion.

The ``PollingWorker`` continuously polls a ``SourceAdapter`` at a
configured interval, deduplicates via ``ExternalEventRepository``,
applies freshness budget, and persists normalised events.

Architecture
------------
::

    PollingWorker (interval loop)
      ├── SourceAdapter.fetch() → RawEvent[]
      ├── DedupKeyGenerator → dedup_key_hash
      ├── ExternalEventRepository.find_by_dedup_key() → skip if exists
      ├── SourceAdapter.normalize() → ExternalEventEntity
      ├── FreshnessBudget.stale_metadata() → metadata["stale"]
      └── ExternalEventRepository.add() → persisted
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent_trading.brokers.dedup import DedupKeyGenerator
from agent_trading.brokers.freshness import FreshnessBudget
from agent_trading.brokers.source_adapter import RawEvent, SourceAdapter
from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.repositories.contracts import ExternalEventRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class PollingConfig:
    """Configuration for a single polling worker.

    Parameters
    ----------
    source_name : str
        Stable source identifier, must match ``SourceAdapter.source_name``.
    interval_seconds : int
        Polling interval in seconds.
    freshness_max_seconds : int | None
        Maximum allowed lag before marking an event as stale.
        ``None`` disables freshness checking.
    """

    source_name: str
    interval_seconds: int
    freshness_max_seconds: int | None = None


class PollingWorker:
    """Async polling worker for a single source adapter.

    The worker runs an infinite async loop that:
    1. Calls ``adapter.fetch()`` to get new raw events.
    2. Deduplicates via ``repo.find_by_dedup_key()``.
    3. Normalises via ``adapter.normalize()``.
    4. Applies freshness budget (if configured).
    5. Persists via ``repo.add()``.
    6. Sleeps for ``config.interval_seconds``.

    Usage::

        worker = PollingWorker(adapter, config, repo)
        task = asyncio.create_task(worker.run())
        # ... later ...
        await worker.stop()
    """

    def __init__(
        self,
        adapter: SourceAdapter,
        config: PollingConfig,
        repo: ExternalEventRepository,
    ) -> None:
        self._adapter = adapter
        self._config = config
        self._repo = repo
        self._freshness: FreshnessBudget | None = (
            FreshnessBudget(freshness_max_seconds=config.freshness_max_seconds)
            if config.freshness_max_seconds is not None
            else None
        )
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def source_name(self) -> str:
        return self._config.source_name

    @property
    def is_running(self) -> bool:
        return self._running

    async def run(self) -> None:
        """Start the infinite polling loop.

        This method is designed to be run as an ``asyncio.Task``::

            task = asyncio.create_task(worker.run())
        """
        self._running = True
        logger.info(
            "PollingWorker[%s] started (interval=%ds)",
            self._config.source_name,
            self._config.interval_seconds,
        )
        try:
            while self._running:
                try:
                    count = await self.poll_once()
                    if count > 0:
                        logger.info(
                            "PollingWorker[%s] ingested %d new event(s)",
                            self._config.source_name,
                            count,
                        )
                except Exception:
                    logger.exception(
                        "PollingWorker[%s] poll cycle failed",
                        self._config.source_name,
                    )
                await asyncio.sleep(self._config.interval_seconds)
        except asyncio.CancelledError:
            logger.info("PollingWorker[%s] cancelled", self._config.source_name)
            self._running = False

    async def poll_once(self) -> int:
        """Execute a single poll cycle.

        Returns
        -------
        int
            Number of new events ingested (after dedup).

        The cycle:
        1. Fetch raw events from the source adapter.
        2. For each raw event:
           a. Generate dedup key.
           b. Check if already exists → skip if so.
           c. Normalise to ``ExternalEventEntity``.
           d. Apply freshness budget (stale marking).
           e. Persist via repository.
        3. Return count of newly ingested events.
        """
        raw_events: Sequence[RawEvent] = await self._adapter.fetch()
        if not raw_events:
            return 0

        count = 0
        for raw in raw_events:
            dedup_key = self._adapter.generate_dedup_key(raw)
            existing = await self._repo.find_by_dedup_key(dedup_key)
            if existing is not None:
                continue  # skip duplicate

            entity = await self._adapter.normalize(raw)

            # Apply freshness budget
            if self._freshness is not None:
                stale_meta = self._freshness.stale_metadata(
                    published_at=raw.published_at,
                    ingested_at=raw.ingested_at,
                )
                # Merge stale flag into existing metadata
                merged = dict(entity.metadata)
                merged.update(stale_meta)
                entity = ExternalEventEntity(
                    event_id=entity.event_id,
                    event_type=entity.event_type,
                    source_name=entity.source_name,
                    published_at=entity.published_at,
                    source_reliability_tier=entity.source_reliability_tier,
                    source_event_id=entity.source_event_id,
                    issuer_code=entity.issuer_code,
                    symbol=entity.symbol,
                    market=entity.market,
                    ingested_at=entity.ingested_at,
                    effective_at=entity.effective_at,
                    severity=entity.severity,
                    direction=entity.direction,
                    headline=entity.headline,
                    body_summary=entity.body_summary,
                    raw_payload_uri=entity.raw_payload_uri,
                    dedup_key_hash=entity.dedup_key_hash,
                    supersedes_event_id=entity.supersedes_event_id,
                    metadata=merged,
                    created_at=entity.created_at,
                )

            await self._repo.add(entity)
            count += 1

        return count

    async def stop(self) -> None:
        """Stop the polling loop gracefully."""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PollingWorker[%s] stopped", self._config.source_name)
