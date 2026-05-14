"""Source adapter protocol and raw event model for external event ingestion.

This module defines the ``SourceAdapter`` protocol that all external event
source adapters must implement, and the ``RawEvent`` dataclass that carries
raw event data before normalisation into ``ExternalEventEntity``.

Scope (Priority 2 / v1)
-----------------------
* Protocol definition — all source adapters must conform.
* ``RawEvent`` dataclass — structured raw event with required fields.
* No AI classification, no semantic interpretation — raw data only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.domain.enums import SourceReliabilityTier


@dataclass(slots=True, frozen=True)
class RawEvent:
    """Raw event from an external source before normalisation.

    This is the **input** to a ``SourceAdapter.normalize()`` call. It
    preserves the original source response so that replay pipelines can
    re-normalise with different parser versions.

    Required fields
    ---------------
    * ``source_name`` — stable identifier for the source (e.g. ``"opendart"``).
    * ``source_event_id`` — the source's own unique event identifier.
    * ``event_type`` — source-level classification (e.g. OpenDART ``report_nm``).
    * ``published_at`` — when the source published the event.
    * ``ingested_at`` — when we fetched the event (for freshness calculation).
    * ``source_reliability_tier`` — one of ``SourceReliabilityTier`` values.
    * ``raw_payload`` — the full source response dict for replay/debug.

    At least one of ``symbol`` or ``issuer_code`` must be provided.
    """

    source_name: str
    source_event_id: str
    event_type: str
    published_at: datetime
    ingested_at: datetime
    source_reliability_tier: str
    raw_payload: dict[str, Any]

    symbol: str | None = None
    issuer_code: str | None = None
    market: str | None = None
    headline: str | None = None
    body: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    """Protocol for external event source adapters.

    Each source adapter encapsulates the logic to:
    1. Fetch new events from an external API (``fetch``).
    2. Convert a ``RawEvent`` into a normalised ``ExternalEventEntity``
       (``normalize``).
    3. Generate a deterministic dedup key for a raw event (``generate_dedup_key``).

    v1 scope: fetch → normalise → store only.
    No AI classification, no semantic interpretation.
    """

    @property
    def source_name(self) -> str:
        """Stable identifier for this source (e.g. ``"opendart"``)."""
        ...

    @property
    def reliability_tier(self) -> SourceReliabilityTier:
        """Reliability tier for this source."""
        ...

    async def fetch(self) -> Sequence[RawEvent]:
        """Fetch new events since the last poll.

        Returns a sequence of ``RawEvent`` objects. The adapter is
        responsible for tracking its own polling cursor (e.g. last poll
        timestamp) and returning only events that have not been seen before.

        Returns an empty sequence if there are no new events.
        """
        ...

    async def normalize(self, raw: RawEvent) -> ExternalEventEntity:
        """Convert a ``RawEvent`` into a normalised ``ExternalEventEntity``.

        This method must:
        * Map source fields to ``ExternalEventEntity`` fields.
        * Set ``dedup_key_hash`` using ``generate_dedup_key()``.
        * Preserve the original ``raw_payload`` reference via
          ``raw_payload_uri`` or ``metadata``.

        v1 scope: field mapping only — no AI classification.
        """
        ...

    def generate_dedup_key(self, raw: RawEvent) -> str:
        """Generate a deterministic dedup key for the raw event.

        Rules (Priority 2):
        * Use source-specific stable fields **first**:
          ``{source_name}|{source_event_id}|{event_type}|{symbol or issuer_code}``
        * Do **not** use payload hash as the primary key.
        * The same ``source_event_id`` + ``event_type`` → same event,
          even if payload content differs (e.g. amended disclosure).
        """
        ...
