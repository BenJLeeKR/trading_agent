from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import UniverseFreezeRunItemEntity


class PostgresUniverseFreezeRunItemRepository:
    """PostgreSQL implementation of ``UniverseFreezeRunItemRepository``."""

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, item: UniverseFreezeRunItemEntity) -> UniverseFreezeRunItemEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.universe_freeze_run_items
                (universe_freeze_run_item_id, universe_freeze_run_id, instrument_id,
                 symbol, market_code, source_type, inclusion_reason,
                 priority_score, rank, cap_bucket, metadata_json, created_at)
            VALUES ($1, $2, $3,
                    $4, $5, $6, $7,
                    $8, $9, $10, $11::jsonb, $12)
            RETURNING *
            """,
            item.universe_freeze_run_item_id,
            item.universe_freeze_run_id,
            item.instrument_id,
            item.symbol,
            item.market_code,
            item.source_type,
            item.inclusion_reason,
            item.priority_score,
            item.rank,
            item.cap_bucket,
            json.dumps(item.metadata_json),
            item.created_at or datetime.now(timezone.utc),
        )
        return row_to_entity(row, UniverseFreezeRunItemEntity)

    async def add_many(
        self,
        items: Sequence[UniverseFreezeRunItemEntity],
    ) -> Sequence[UniverseFreezeRunItemEntity]:
        saved: list[UniverseFreezeRunItemEntity] = []
        for item in items:
            saved.append(await self.add(item))
        return tuple(saved)

    async def list_by_run(
        self,
        universe_freeze_run_id: UUID,
    ) -> Sequence[UniverseFreezeRunItemEntity]:
        rows = await self._tx.connection.fetch(
            """
            SELECT *
            FROM trading.universe_freeze_run_items
            WHERE universe_freeze_run_id = $1
            ORDER BY rank ASC NULLS LAST, symbol ASC
            """,
            universe_freeze_run_id,
        )
        return tuple(row_to_entity(row, UniverseFreezeRunItemEntity) for row in rows)
