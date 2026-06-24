from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import SignalFeatureBatchRunEntity


class PostgresSignalFeatureBatchRunRepository:
    """PostgreSQL implementation of ``SignalFeatureBatchRunRepository``."""

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, run: SignalFeatureBatchRunEntity) -> SignalFeatureBatchRunEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.signal_feature_batch_runs
                (signal_feature_batch_run_id, business_date, universe_freeze_run_id,
                 trigger_type, timeframe, feature_set_version, input_uri, dry_run,
                 target_count, fetch_success_count, fetch_error_count,
                 persist_success_count, persist_error_count, skipped_count,
                 final_missing_count, status, summary_json,
                 started_at, completed_at, created_at, updated_at)
            VALUES ($1, $2, $3,
                    $4, $5, $6, $7, $8,
                    $9, $10, $11,
                    $12, $13, $14,
                    $15, $16, $17::jsonb,
                    $18, $19, $20, $21)
            RETURNING *
            """,
            run.signal_feature_batch_run_id,
            run.business_date,
            run.universe_freeze_run_id,
            run.trigger_type,
            run.timeframe,
            run.feature_set_version,
            run.input_uri,
            run.dry_run,
            run.target_count,
            run.fetch_success_count,
            run.fetch_error_count,
            run.persist_success_count,
            run.persist_error_count,
            run.skipped_count,
            run.final_missing_count,
            run.status,
            json.dumps(run.summary_json),
            run.started_at,
            run.completed_at,
            run.created_at or datetime.now(timezone.utc),
            run.updated_at or datetime.now(timezone.utc),
        )
        return row_to_entity(row, SignalFeatureBatchRunEntity)

    async def get(self, run_id: UUID) -> SignalFeatureBatchRunEntity | None:
        row = await self._tx.connection.fetchrow(
            """
            SELECT *
            FROM trading.signal_feature_batch_runs
            WHERE signal_feature_batch_run_id = $1
            """,
            run_id,
        )
        return row_to_entity(row, SignalFeatureBatchRunEntity) if row else None
