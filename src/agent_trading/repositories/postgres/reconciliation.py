from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import (
    BlockingLockEntity,
    ReconciliationOrderLinkEntity,
    ReconciliationPositionLinkEntity,
    ReconciliationRunEntity,
)


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
            json.dumps(run.summary_json) if run.summary_json is not None else None,
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
            json.dumps(details) if details is not None else None,
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
            json.dumps(details) if details is not None else None,
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

    async def list_locks(
        self, account_id: UUID
    ) -> Sequence[BlockingLockEntity]:
        """Return active (non-expired) blocking locks for an account.

        Active lock check uses ``expires_at > NOW()`` since the DDL has no
        ``resolved_at`` / ``deleted_at`` column — locks are physically
        DELETEd, not soft-deleted. If a soft-delete column is added in a
        future migration, include it in the WHERE clause alongside the
        expiry check.
        """
        rows = await self._tx.connection.fetch(
            """
            SELECT lock_id, account_id, strategy_id, symbol, side,
                   reason, locked_by_run_id, locked_at, expires_at
            FROM trading.order_blocking_locks
            WHERE account_id = $1
              AND expires_at > NOW()
            ORDER BY locked_at DESC
            """,
            account_id,
        )
        return [_row_to_blocking_lock(r) for r in rows]

    # -- Plan 64: Aggregate (all-account) queries for Dashboard --

    async def list_all_runs(
        self, limit: int = 20
    ) -> Sequence[ReconciliationRunEntity]:
        """Return reconciliation runs across all accounts, newest first."""
        rows = await self._tx.connection.fetch(
            """
            SELECT * FROM trading.reconciliation_runs
            ORDER BY started_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [row_to_entity(row, ReconciliationRunEntity) for row in rows]

    async def list_all_active_locks(
        self,
    ) -> Sequence[BlockingLockEntity]:
        """Return active (non-expired) blocking locks across all accounts."""
        rows = await self._tx.connection.fetch(
            """
            SELECT lock_id, account_id, strategy_id, symbol, side,
                   reason, locked_by_run_id, locked_at, expires_at
            FROM trading.order_blocking_locks
            WHERE expires_at > NOW()
            ORDER BY locked_at DESC
            """
        )
        return [_row_to_blocking_lock(r) for r in rows]

    # -- Worker read path (Reconciliation Worker) --

    async def list_pending_runs(
        self,
        limit: int = 20,
        *,
        account_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> Sequence[ReconciliationRunEntity]:
        """Return reconciliation runs with ``status = 'started'``."""
        conditions = ["status = 'started'"]
        params: list[object] = []
        idx = 1

        if account_id is not None:
            conditions.append(f"account_id = ${idx}")
            params.append(account_id)
            idx += 1
        if run_id is not None:
            conditions.append(f"reconciliation_run_id = ${idx}")
            params.append(run_id)
            idx += 1

        where = " AND ".join(conditions)
        sql = (
            f"SELECT * FROM trading.reconciliation_runs"
            f" WHERE {where}"
            f" ORDER BY started_at ASC"
            f" LIMIT ${idx}"
        )
        params.append(limit)

        rows = await self._tx.connection.fetch(sql, *params)
        return [row_to_entity(row, ReconciliationRunEntity) for row in rows]

    async def get_run_order_links(
        self,
        reconciliation_run_id: UUID,
    ) -> Sequence[ReconciliationOrderLinkEntity]:
        """Return order links attached to a reconciliation run."""
        rows = await self._tx.connection.fetch(
            """
            SELECT reconciliation_run_id, order_request_id, mismatch_type,
                   details_json, created_at
            FROM trading.reconciliation_order_links
            WHERE reconciliation_run_id = $1
            ORDER BY created_at ASC
            """,
            reconciliation_run_id,
        )
        return [_row_to_link_entity(row) for row in rows]

    async def list_run_position_links(
        self,
        reconciliation_run_id: UUID,
    ) -> Sequence[ReconciliationPositionLinkEntity]:
        """Return position links attached to a reconciliation run."""
        rows = await self._tx.connection.fetch(
            """
            SELECT reconciliation_run_id, position_snapshot_id, mismatch_type,
                   details_json, created_at
            FROM trading.reconciliation_position_links
            WHERE reconciliation_run_id = $1
            ORDER BY created_at ASC
            """,
            reconciliation_run_id,
        )
        return [_row_to_position_link_entity(row) for row in rows]

    async def update_run_status(
        self,
        reconciliation_run_id: UUID,
        status: str,
        completed_at: datetime | None = None,
        summary_json: dict[str, object] | None = None,
    ) -> None:
        sets = ["status = $2"]
        params = [reconciliation_run_id, status]
        idx = 3

        if completed_at is not None:
            sets.append(f"completed_at = ${idx}")
            params.append(completed_at)
            idx += 1
        if summary_json is not None:
            sets.append(f"summary_json = ${idx}::jsonb")
            params.append(json.dumps(summary_json))
            idx += 1

        set_clause = ", ".join(sets)
        sql = (
            f"UPDATE trading.reconciliation_runs"
            f" SET {set_clause}"
            f" WHERE reconciliation_run_id = $1"
        )
        await self._tx.connection.execute(sql, *params)

    async def list_legacy_runs(
        self,
        limit: int = 50,
        *,
        account_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> Sequence[ReconciliationRunEntity]:
        """Return legacy runs: ``status = 'started'`` AND no order links."""
        conditions = ["r.status = 'started'"]
        params: list[object] = []
        idx = 1

        if account_id is not None:
            conditions.append(f"r.account_id = ${idx}")
            params.append(account_id)
            idx += 1
        if run_id is not None:
            conditions.append(f"r.reconciliation_run_id = ${idx}")
            params.append(run_id)
            idx += 1

        where = " AND ".join(conditions)
        sql = (
            f"SELECT r.* FROM trading.reconciliation_runs r"
            f" WHERE {where}"
            f" AND NOT EXISTS ("
            f"     SELECT 1 FROM trading.reconciliation_order_links l"
            f"     WHERE l.reconciliation_run_id = r.reconciliation_run_id"
            f" )"
            f" ORDER BY r.started_at ASC"
            f" LIMIT ${idx}"
        )
        params.append(limit)

        rows = await self._tx.connection.fetch(sql, *params)
        return [row_to_entity(row, ReconciliationRunEntity) for row in rows]


def _row_to_blocking_lock(row: object) -> BlockingLockEntity:
    """Convert a ``trading.order_blocking_locks`` row to a ``BlockingLockEntity``."""
    return BlockingLockEntity(
        lock_id=row["lock_id"],
        account_id=row["account_id"],
        strategy_id=row.get("strategy_id"),
        symbol=row.get("symbol"),
        side=row.get("side"),
        reason=row.get("reason", "reconciliation"),
        locked_by_run_id=row.get("locked_by_run_id"),
        locked_at=row.get("locked_at"),
        expires_at=row.get("expires_at"),
    )


def _row_to_link_entity(row: object) -> ReconciliationOrderLinkEntity:
    """Convert a ``trading.reconciliation_order_links`` row to a ``ReconciliationOrderLinkEntity``."""
    details = row.get("details_json") or {}
    if isinstance(details, str):
        details = json.loads(details)
    return ReconciliationOrderLinkEntity(
        reconciliation_run_id=row["reconciliation_run_id"],
        order_request_id=row["order_request_id"],
        mismatch_type=row["mismatch_type"],
        details_json=details,
        created_at=row.get("created_at"),
    )


def _row_to_position_link_entity(row: object) -> ReconciliationPositionLinkEntity:
    """Convert a ``trading.reconciliation_position_links`` row to a ``ReconciliationPositionLinkEntity``."""
    details = row.get("details_json") or {}
    if isinstance(details, str):
        details = json.loads(details)
    return ReconciliationPositionLinkEntity(
        reconciliation_run_id=row["reconciliation_run_id"],
        position_snapshot_id=row["position_snapshot_id"],
        mismatch_type=row["mismatch_type"],
        details_json=details,
        created_at=row.get("created_at"),
    )
