from __future__ import annotations

import json
from datetime import date, datetime, timezone
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import UniverseFreezeRunEntity


class PostgresUniverseFreezeRunRepository:
    """PostgreSQL implementation of ``UniverseFreezeRunRepository``."""

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, run: UniverseFreezeRunEntity) -> UniverseFreezeRunEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.universe_freeze_runs
                (universe_freeze_run_id, business_date, freeze_purpose,
                 freeze_sequence, frozen_at, selection_version,
                 selection_params_json, target_count, status,
                 created_at, updated_at)
            VALUES ($1, $2, $3,
                    $4, $5, $6,
                    $7::jsonb, $8, $9,
                    $10, $11)
            RETURNING *
            """,
            run.universe_freeze_run_id,
            run.business_date,
            run.freeze_purpose,
            run.freeze_sequence,
            run.frozen_at,
            run.selection_version,
            json.dumps(run.selection_params_json),
            run.target_count,
            run.status,
            run.created_at or datetime.now(timezone.utc),
            run.updated_at or datetime.now(timezone.utc),
        )
        return row_to_entity(row, UniverseFreezeRunEntity)

    async def get(self, run_id: UUID) -> UniverseFreezeRunEntity | None:
        row = await self._tx.connection.fetchrow(
            """
            SELECT *
            FROM trading.universe_freeze_runs
            WHERE universe_freeze_run_id = $1
            """,
            run_id,
        )
        return row_to_entity(row, UniverseFreezeRunEntity) if row else None

    async def get_latest(
        self,
        business_date: date,
        freeze_purpose: str,
    ) -> UniverseFreezeRunEntity | None:
        row = await self._tx.connection.fetchrow(
            """
            SELECT *
            FROM trading.universe_freeze_runs
            WHERE business_date = $1
              AND freeze_purpose = $2
            ORDER BY freeze_sequence DESC, frozen_at DESC
            LIMIT 1
            """,
            business_date,
            freeze_purpose,
        )
        return row_to_entity(row, UniverseFreezeRunEntity) if row else None
