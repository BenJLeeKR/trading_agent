"""PostgreSQL implementation of ``ExternalEventRepository``."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from agent_trading.db.row_mapper import entity_to_insert_kwargs, row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.repositories.contracts import ExternalEventRepository


class PostgresExternalEventRepository(ExternalEventRepository):
    """PostgreSQL implementation of ``ExternalEventRepository``.

    This is a **foundation** implementation for Milestone 7. Actual
    polling workers and source adapters are deferred to a later milestone.
    """

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, event: ExternalEventEntity) -> ExternalEventEntity:
        import json

        kwargs = entity_to_insert_kwargs(event)
        # Keep event_id so the caller controls the identity
        kwargs.pop("created_at", None)

        metadata = kwargs.get("metadata", {})
        if isinstance(metadata, dict):
            metadata = json.dumps(metadata)

        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.external_events (
                event_id, event_type, source_name, source_reliability_tier,
                source_event_id, issuer_code, symbol, market,
                published_at, ingested_at, effective_at,
                severity, direction, headline, body_summary,
                raw_payload_uri, dedup_key_hash, supersedes_event_id,
                metadata
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8,
                $9, $10, $11,
                $12, $13, $14, $15,
                $16, $17, $18,
                $19
            )
            RETURNING *
            """,
            kwargs.get("event_id"),
            kwargs.get("event_type"),
            kwargs.get("source_name"),
            kwargs.get("source_reliability_tier", "T3"),
            kwargs.get("source_event_id"),
            kwargs.get("issuer_code"),
            kwargs.get("symbol"),
            kwargs.get("market"),
            kwargs.get("published_at"),
            kwargs.get("ingested_at") or datetime.now(tz=kwargs.get("published_at").tzinfo),
            kwargs.get("effective_at"),
            kwargs.get("severity", "medium"),
            kwargs.get("direction", "neutral"),
            kwargs.get("headline"),
            kwargs.get("body_summary"),
            kwargs.get("raw_payload_uri"),
            kwargs.get("dedup_key_hash"),
            kwargs.get("supersedes_event_id"),
            metadata,
        )
        return row_to_entity(row, ExternalEventEntity)

    async def get(self, event_id: UUID) -> ExternalEventEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.external_events WHERE event_id = $1",
            event_id,
        )
        return row_to_entity(row, ExternalEventEntity) if row else None

    async def find_by_dedup_key(self, dedup_key_hash: str) -> ExternalEventEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.external_events WHERE dedup_key_hash = $1",
            dedup_key_hash,
        )
        return row_to_entity(row, ExternalEventEntity) if row else None

    async def list_by_symbol(
        self,
        symbol: str,
        since: datetime,
        include_non_listed: bool = False,
        include_seeded_news: bool = False,
    ) -> Sequence[ExternalEventEntity]:
        """List events by symbol, excluding non-listed (corp_cls=E) by default.

        The listed-event filter uses the ``event_type`` prefix convention
        (``Y|``, ``K|``, ``N|`` = listed; ``E|`` = non-listed). When
        ``include_non_listed=False`` (default), only listed-entity events
        are returned.

        Seeded news events (``event_type='seeded_news'``) do not carry the
        listed prefix.  Pass ``include_seeded_news=True`` to include them
        alongside listed events — this is the intended mode for EI decision
        context assembly.
        """
        if include_non_listed:
            rows = await self._tx.connection.fetch(
                """
                SELECT * FROM trading.external_events
                WHERE symbol = $1 AND published_at >= $2
                ORDER BY published_at DESC
                """,
                symbol,
                since,
            )
        elif include_seeded_news:
            rows = await self._tx.connection.fetch(
                """
                SELECT * FROM trading.external_events
                WHERE symbol = $1
                  AND published_at >= $2
                  AND (
                      (event_type LIKE 'Y|%' OR event_type LIKE 'K|%' OR event_type LIKE 'N|%')
                      OR event_type = 'seeded_news'
                  )
                ORDER BY published_at DESC
                """,
                symbol,
                since,
            )
        else:
            rows = await self._tx.connection.fetch(
                """
                SELECT * FROM trading.external_events
                WHERE symbol = $1
                  AND published_at >= $2
                  AND (event_type LIKE 'Y|%' OR event_type LIKE 'K|%' OR event_type LIKE 'N|%')
                ORDER BY published_at DESC
                """,
                symbol,
                since,
            )
        return [row_to_entity(r, ExternalEventEntity) for r in rows]

    async def list_by_type(
        self,
        event_type: str,
        since: datetime,
        include_non_listed: bool = False,
        include_seeded_news: bool = False,
    ) -> Sequence[ExternalEventEntity]:
        """List events by type, excluding non-listed (corp_cls=E) by default.

        The listed-event filter uses the ``event_type`` prefix convention
        (``Y|``, ``K|``, ``N|`` = listed; ``E|`` = non-listed). When
        ``include_non_listed=False`` (default), only listed-entity events
        are returned.

        Seeded news events (``event_type='seeded_news'``) do not carry the
        listed prefix.  Pass ``include_seeded_news=True`` to include them
        alongside listed events.
        """
        if include_non_listed:
            rows = await self._tx.connection.fetch(
                """
                SELECT * FROM trading.external_events
                WHERE event_type = $1 AND published_at >= $2
                ORDER BY published_at DESC
                """,
                event_type,
                since,
            )
        elif include_seeded_news:
            rows = await self._tx.connection.fetch(
                """
                SELECT * FROM trading.external_events
                WHERE event_type = $1
                  AND published_at >= $2
                  AND (
                      (event_type LIKE 'Y|%' OR event_type LIKE 'K|%' OR event_type LIKE 'N|%')
                      OR event_type = 'seeded_news'
                  )
                ORDER BY published_at DESC
                """,
                event_type,
                since,
            )
        else:
            rows = await self._tx.connection.fetch(
                """
                SELECT * FROM trading.external_events
                WHERE event_type = $1
                  AND published_at >= $2
                  AND (event_type LIKE 'Y|%' OR event_type LIKE 'K|%' OR event_type LIKE 'N|%')
                ORDER BY published_at DESC
                """,
                event_type,
                since,
            )
        return [row_to_entity(r, ExternalEventEntity) for r in rows]
