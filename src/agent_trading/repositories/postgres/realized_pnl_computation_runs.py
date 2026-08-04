from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import RealizedPnlComputationRunEntity
from agent_trading.domain.enums import RealizedPnlComputationRunType


class PostgresRealizedPnlComputationRunRepository:
    """PostgreSQL implementation of ``RealizedPnlComputationRunRepository``."""

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(
        self, run: RealizedPnlComputationRunEntity
    ) -> RealizedPnlComputationRunEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.realized_pnl_computation_runs
                (computation_run_id, run_type, account_id, status,
                 fills_applied, fills_skipped_duplicate, fills_replayed,
                 anomalies_detected, summary_json, started_at, completed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING *
            """,
            run.computation_run_id,
            run.run_type.value,
            run.account_id,
            run.status,
            run.fills_applied,
            run.fills_skipped_duplicate,
            run.fills_replayed,
            run.anomalies_detected,
            json.dumps(run.summary_json) if run.summary_json is not None else json.dumps({}),
            run.started_at,
            run.completed_at,
        )
        return row_to_entity(row, RealizedPnlComputationRunEntity)

    async def update_run(
        self, run: RealizedPnlComputationRunEntity
    ) -> RealizedPnlComputationRunEntity:
        row = await self._tx.connection.fetchrow(
            """
            UPDATE trading.realized_pnl_computation_runs SET
                run_type = $2,
                account_id = $3,
                status = $4,
                fills_applied = $5,
                fills_skipped_duplicate = $6,
                fills_replayed = $7,
                anomalies_detected = $8,
                summary_json = $9,
                started_at = $10,
                completed_at = $11
            WHERE computation_run_id = $1
            RETURNING *
            """,
            run.computation_run_id,
            run.run_type.value,
            run.account_id,
            run.status,
            run.fills_applied,
            run.fills_skipped_duplicate,
            run.fills_replayed,
            run.anomalies_detected,
            json.dumps(run.summary_json) if run.summary_json is not None else json.dumps({}),
            run.started_at,
            run.completed_at,
        )
        return row_to_entity(row, RealizedPnlComputationRunEntity)

    async def get(
        self, computation_run_id: UUID
    ) -> RealizedPnlComputationRunEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.realized_pnl_computation_runs WHERE computation_run_id = $1",
            computation_run_id,
        )
        return row_to_entity(row, RealizedPnlComputationRunEntity) if row else None

    async def list_runs(
        self,
        limit: int = 50,
        status: str | None = None,
        run_type: RealizedPnlComputationRunType | None = None,
    ) -> Sequence[RealizedPnlComputationRunEntity]:
        conditions: list[str] = []
        params: list[object] = []
        idx = 1
        if status is not None:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if run_type is not None:
            conditions.append(f"run_type = ${idx}")
            params.append(run_type.value)
            idx += 1
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = await self._tx.connection.fetch(
            f"SELECT * FROM trading.realized_pnl_computation_runs{where_clause} "
            f"ORDER BY started_at DESC LIMIT ${idx}",
            *params,
        )
        return tuple(row_to_entity(row, RealizedPnlComputationRunEntity) for row in rows)
