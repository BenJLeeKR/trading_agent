"""Freshness budget and stale marking for external events.

Freshness is evaluated **at storage time** and recorded deterministically
so that replay pipelines produce the same stale/not-stale classification
for the same raw event.

Rules (Priority 2 / v1)
-----------------------
* ``freshness_max_seconds`` is configured per source.
* Stale = ``ingested_at - published_at > freshness_max_seconds``.
* Stale flag is written to ``metadata["stale"]`` at insert time.
* Replay: same ``published_at`` + ``ingested_at`` + ``freshness_max_seconds``
  → same stale classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True, frozen=True)
class FreshnessBudget:
    """Freshness budget configuration for a single source.

    Parameters
    ----------
    freshness_max_seconds : int
        Maximum allowed lag between ``published_at`` and ``ingested_at``
        before the event is marked as stale.
    """

    freshness_max_seconds: int

    def is_stale(self, published_at: datetime, ingested_at: datetime) -> bool:
        """Determine whether an event is stale.

        The calculation is purely deterministic:
        ``(ingested_at - published_at).total_seconds() > freshness_max_seconds``

        Parameters
        ----------
        published_at : datetime
            When the source published the event.
        ingested_at : datetime
            When we fetched and ingested the event.

        Returns
        -------
        bool
            ``True`` if the event is stale.
        """
        lag = (ingested_at - published_at).total_seconds()
        return lag > self.freshness_max_seconds

    def stale_metadata(self, published_at: datetime, ingested_at: datetime) -> dict[str, object]:
        """Return metadata dict with deterministic stale flag.

        This is the primary method for recording freshness at storage time.
        The returned dict can be merged into ``ExternalEventEntity.metadata``.

        Parameters
        ----------
        published_at : datetime
            When the source published the event.
        ingested_at : datetime
            When we fetched and ingested the event.

        Returns
        -------
        dict[str, object]
            ``{"stale": True}`` or ``{"stale": False}``.
        """
        return {"stale": self.is_stale(published_at, ingested_at)}
