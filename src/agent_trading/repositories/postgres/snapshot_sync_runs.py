from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import SnapshotSyncRunEntity
from agent_trading.repositories.contracts import (
    SnapshotSyncHealthSummary,
    SnapshotSyncRunRepository,
)


class PostgresSnapshotSyncRunRepository:
    """PostgreSQL implementation of ``SnapshotSyncRunRepository``.

    Stores run-level summary of KIS snapshot sync executions.
    Append-only: each sync run creates one record.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, run: SnapshotSyncRunEntity) -> SnapshotSyncRunEntity:
        row = await self._tx.connection.fetchrow(
            """INSERT INTO trading.snapshot_sync_runs
               (snapshot_sync_run_id, trigger_type, scope,
                env_filter, status_filter, dry_run,
                total_accounts, succeeded_accounts, partial_accounts,
                failed_accounts, skipped_accounts,
                positions_synced_total, positions_skipped_total,
                cash_synced_count, error_count,
                status, started_at, completed_at, summary_json,
                created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                       $11, $12, $13, $14, $15, $16, $17, $18, $19, $20)
               RETURNING *""",
            run.snapshot_sync_run_id,
            run.trigger_type,
            run.scope,
            run.env_filter,
            run.status_filter,
            run.dry_run,
            run.total_accounts,
            run.succeeded_accounts,
            run.partial_accounts,
            run.failed_accounts,
            run.skipped_accounts,
            run.positions_synced_total,
            run.positions_skipped_total,
            run.cash_synced_count,
            run.error_count,
            run.status,
            run.started_at,
            run.completed_at,
            run.summary_json,
            run.created_at or datetime.now(timezone.utc),
        )
        return row_to_entity(row, SnapshotSyncRunEntity)

    async def list_runs(
        self,
        limit: int = 50,
        trigger_type: str | None = None,
        status: str | None = None,
    ) -> tuple[SnapshotSyncRunEntity, ...]:
        """List sync runs, newest first.

        Builds a dynamic WHERE clause when optional filters are provided.
        """
        conditions: list[str] = []
        params: list[object] = []
        idx = 1

        if trigger_type is not None:
            conditions.append(f"trigger_type = ${idx}")
            params.append(trigger_type)
            idx += 1
        if status is not None:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)

        rows = await self._tx.connection.fetch(
            f"SELECT * FROM trading.snapshot_sync_runs{where_clause} ORDER BY started_at DESC LIMIT ${idx}",
            *params,
        )
        return tuple(row_to_entity(row, SnapshotSyncRunEntity) for row in rows)

    async def get(self, run_id: UUID) -> SnapshotSyncRunEntity | None:
        """Get a single sync run by its UUID."""
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.snapshot_sync_runs WHERE snapshot_sync_run_id = $1",
            run_id,
        )
        return row_to_entity(row, SnapshotSyncRunEntity) if row else None

    async def get_sync_health_summary(
        self,
        stale_threshold_seconds: int = 900,
    ) -> SnapshotSyncHealthSummary:
        """Compute a freshness/staleness summary from the last 100 runs."""
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.snapshot_sync_runs ORDER BY started_at DESC LIMIT 100",
        )

        if not rows:
            return SnapshotSyncHealthSummary(
                last_run_started_at=None,
                last_run_completed_at=None,
                last_status=None,
                last_successful_run_at=None,
                consecutive_failures=0,
                is_stale=True,
                stale_threshold_seconds=stale_threshold_seconds,
            )

        entities = [row_to_entity(row, SnapshotSyncRunEntity) for row in rows]

        # Most recent run
        last = entities[0]

        # Most recent successful run (status == "completed")
        last_successful: SnapshotSyncRunEntity | None = None
        for e in entities:
            if e.status == "completed":
                last_successful = e
                break

        # Count consecutive failures (status == "failed") in reverse order
        consecutive_failures = 0
        for e in entities:
            if e.status == "failed":
                consecutive_failures += 1
            else:
                break

        # Staleness check
        now = datetime.now(timezone.utc)
        last_successful_at = last_successful.started_at if last_successful else None
        is_stale = True
        if last_successful_at is not None:
            is_stale = (now - last_successful_at).total_seconds() > stale_threshold_seconds

        return SnapshotSyncHealthSummary(
            last_run_started_at=last.started_at,
            last_run_completed_at=last.completed_at,
            last_status=last.status,
            last_successful_run_at=last_successful_at,
            consecutive_failures=consecutive_failures,
            is_stale=is_stale,
            stale_threshold_seconds=stale_threshold_seconds,
        )
