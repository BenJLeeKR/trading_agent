from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import SignalFeatureBatchRunItemEntity


class PostgresSignalFeatureBatchRunItemRepository:
    """PostgreSQL implementation of ``SignalFeatureBatchRunItemRepository``."""

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(
        self,
        item: SignalFeatureBatchRunItemEntity,
    ) -> SignalFeatureBatchRunItemEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.signal_feature_batch_run_items
                (signal_feature_batch_run_item_id, signal_feature_batch_run_id,
                 instrument_id, symbol, market_code, timeframe, feature_set_version,
                 status, signal_feature_snapshot_id, snapshot_at,
                 error_code, error_message, metadata_json,
                 created_at, updated_at)
            VALUES ($1, $2,
                    $3, $4, $5, $6, $7,
                    $8, $9, $10,
                    $11, $12, $13::jsonb,
                    $14, $15)
            RETURNING *
            """,
            item.signal_feature_batch_run_item_id,
            item.signal_feature_batch_run_id,
            item.instrument_id,
            item.symbol,
            item.market_code,
            item.timeframe,
            item.feature_set_version,
            item.status,
            item.signal_feature_snapshot_id,
            item.snapshot_at,
            item.error_code,
            item.error_message,
            json.dumps(item.metadata_json),
            item.created_at or datetime.now(timezone.utc),
            item.updated_at or datetime.now(timezone.utc),
        )
        return row_to_entity(row, SignalFeatureBatchRunItemEntity)

    async def add_many(
        self,
        items: Sequence[SignalFeatureBatchRunItemEntity],
    ) -> Sequence[SignalFeatureBatchRunItemEntity]:
        saved: list[SignalFeatureBatchRunItemEntity] = []
        for item in items:
            saved.append(await self.add(item))
        return tuple(saved)
