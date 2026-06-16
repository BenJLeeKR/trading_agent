from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import SignalFeatureSnapshotEntity


class PostgresSignalFeatureSnapshotRepository:
    """PostgreSQL implementation of ``SignalFeatureSnapshotRepository``."""

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(
        self, snapshot: SignalFeatureSnapshotEntity,
    ) -> SignalFeatureSnapshotEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.signal_feature_snapshots
                (signal_feature_snapshot_id, instrument_id, timeframe,
                 snapshot_at, feature_set_version, bar_count,
                 sma_5, sma_20, sma_60,
                 price_vs_sma_20_pct, price_vs_sma_60_pct,
                 return_1m_pct, return_3m_pct,
                 volatility_20d_pct, atr_14_pct, rsi_14,
                 average_volume_20d, volume_surge_ratio,
                 fast_score, slow_score, overall_score,
                 component_scores_json, reason_codes)
            VALUES ($1, $2, $3, $4, $5, $6,
                    $7, $8, $9,
                    $10, $11,
                    $12, $13,
                    $14, $15, $16,
                    $17, $18,
                    $19, $20, $21,
                    $22::jsonb, $23)
            RETURNING *
            """,
            snapshot.signal_feature_snapshot_id,
            snapshot.instrument_id,
            snapshot.timeframe,
            snapshot.snapshot_at,
            snapshot.feature_set_version,
            snapshot.bar_count,
            snapshot.sma_5,
            snapshot.sma_20,
            snapshot.sma_60,
            snapshot.price_vs_sma_20_pct,
            snapshot.price_vs_sma_60_pct,
            snapshot.return_1m_pct,
            snapshot.return_3m_pct,
            snapshot.volatility_20d_pct,
            snapshot.atr_14_pct,
            snapshot.rsi_14,
            snapshot.average_volume_20d,
            snapshot.volume_surge_ratio,
            snapshot.fast_score,
            snapshot.slow_score,
            snapshot.overall_score,
            json.dumps(snapshot.component_scores_json),
            snapshot.reason_codes,
        )
        return row_to_entity(row, SignalFeatureSnapshotEntity)

    async def get_latest_by_instrument(
        self,
        instrument_id: UUID,
        timeframe: str = "1d",
    ) -> SignalFeatureSnapshotEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.signal_feature_snapshots "
            "WHERE instrument_id = $1 AND timeframe = $2 "
            "ORDER BY snapshot_at DESC "
            "LIMIT 1",
            instrument_id,
            timeframe,
        )
        return row_to_entity(row, SignalFeatureSnapshotEntity) if row else None

    async def list_by_instrument(
        self,
        instrument_id: UUID,
        timeframe: str = "1d",
        limit: int = 20,
    ) -> Sequence[SignalFeatureSnapshotEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.signal_feature_snapshots "
            "WHERE instrument_id = $1 AND timeframe = $2 "
            "ORDER BY snapshot_at DESC "
            "LIMIT $3",
            instrument_id,
            timeframe,
            limit,
        )
        return tuple(row_to_entity(row, SignalFeatureSnapshotEntity) for row in rows)
