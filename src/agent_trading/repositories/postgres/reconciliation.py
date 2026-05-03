from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import ReconciliationRunEntity


class PostgresReconciliationRepository:
    """PostgreSQL implementation of ``ReconciliationRepository``."""

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add_run(self, run: ReconciliationRunEntity) -> ReconciliationRunEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.reconciliation_runs (
                reconciliation_run_id, account_id, trigger_type, status,
                mismatch_count, summary_json, started_at, completed_at, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
            RETURNING *
            """,
            run.reconciliation_run_id,
            run.account_id,
            run.trigger_type,
            run.status,
            run.mismatch_count,
            run.summary_json,
            run.started_at,
            run.completed_at,
            run.created_at,
        )
        return row_to_entity(row, ReconciliationRunEntity)

    async def get_run(self, reconciliation_run_id: UUID) -> ReconciliationRunEntity | None:
        row = await self._tx.connection.fetchrow(
            """
            SELECT * FROM trading.reconciliation_runs
            WHERE reconciliation_run_id = $1
            """,
            reconciliation_run_id,
        )
        return row_to_entity(row, ReconciliationRunEntity) if row else None

    async def attach_order_mismatch(
        self,
        reconciliation_run_id: UUID,
        order_request_id: UUID,
        mismatch_type: str,
        details: dict[str, object],
    ) -> None:
        await self._tx.connection.execute(
            """
            INSERT INTO trading.reconciliation_order_links
                (reconciliation_run_id, order_request_id, mismatch_type, details_json)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            reconciliation_run_id,
            order_request_id,
            mismatch_type,
            details,
        )

    async def attach_position_mismatch(
        self,
        reconciliation_run_id: UUID,
        position_snapshot_id: UUID,
        mismatch_type: str,
        details: dict[str, object],
    ) -> None:
        await self._tx.connection.execute(
            """
            INSERT INTO trading.reconciliation_position_links
                (reconciliation_run_id, position_snapshot_id, mismatch_type, details_json)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            reconciliation_run_id,
            position_snapshot_id,
            mismatch_type,
            details,
        )

    async def list_runs_by_account(
        self, account_id: UUID, limit: int = 20
    ) -> Sequence[ReconciliationRunEntity]:
        rows = await self._tx.connection.fetch(
            """
            SELECT * FROM trading.reconciliation_runs
            WHERE account_id = $1
            ORDER BY started_at DESC
            LIMIT $2
            """,
            account_id,
            limit,
        )
        return [row_to_entity(row, ReconciliationRunEntity) for row in rows]

    async def get_active_run(
        self, account_id: UUID
    ) -> ReconciliationRunEntity | None:
        row = await self._tx.connection.fetchrow(
            """
            SELECT * FROM trading.reconciliation_runs
            WHERE account_id = $1 AND status = 'started'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            account_id,
        )
        return row_to_entity(row, ReconciliationRunEntity) if row else None

    async def update_run_status(
        self,
        reconciliation_run_id: UUID,
        status: str,
        summary_json: dict[str, object] | None = None,
    ) -> None:
        if summary_json is not None:
            await self._tx.connection.execute(
                """
                UPDATE trading.reconciliation_runs
                SET status = $2, summary_json = $3::jsonb
                WHERE reconciliation_run_id = $1
                """,
                reconciliation_run_id,
                status,
                summary_json,
            )
        else:
            await self._tx.connection.execute(
                """
                UPDATE trading.reconciliation_runs
                SET status = $2
                WHERE reconciliation_run_id = $1
                """,
                reconciliation_run_id,
                status,
            )
