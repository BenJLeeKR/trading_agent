from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import FillSyncRunEntity
from agent_trading.repositories.contracts import FillSyncHealthSummary


class PostgresFillSyncRunRepository:
    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, run: FillSyncRunEntity) -> FillSyncRunEntity:
        row = await self._tx.connection.fetchrow(
            """INSERT INTO trading.fill_sync_runs
               (fill_sync_run_id, trigger_type, scope, dry_run,
                total_accounts, succeeded_accounts, partial_accounts,
                failed_accounts, skipped_accounts,
                fills_synced_total, fills_skipped_total, error_count,
                status, env_filter, summary_json,
                started_at, completed_at, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                       $10, $11, $12, $13, $14, $15, $16, $17, $18)
               RETURNING *""",
            run.fill_sync_run_id,
            run.trigger_type,
            run.scope,
            run.dry_run,
            run.total_accounts,
            run.succeeded_accounts,
            run.partial_accounts,
            run.failed_accounts,
            run.skipped_accounts,
            run.fills_synced_total,
            run.fills_skipped_total,
            run.error_count,
            run.status,
            run.env_filter,
            json.dumps(run.summary_json) if run.summary_json is not None else json.dumps({}),
            run.started_at,
            run.completed_at,
            run.created_at or datetime.now(timezone.utc),
        )
        return row_to_entity(row, FillSyncRunEntity)

    async def list_runs(
        self,
        limit: int = 50,
        trigger_type: str | None = None,
        status: str | None = None,
    ) -> Sequence[FillSyncRunEntity]:
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
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = await self._tx.connection.fetch(
            f"SELECT * FROM trading.fill_sync_runs{where_clause} ORDER BY started_at DESC LIMIT ${idx}",
            *params,
        )
        return tuple(row_to_entity(row, FillSyncRunEntity) for row in rows)

    async def get(self, run_id: UUID) -> FillSyncRunEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.fill_sync_runs WHERE fill_sync_run_id = $1",
            run_id,
        )
        return row_to_entity(row, FillSyncRunEntity) if row else None

    async def update_run(self, run: FillSyncRunEntity) -> FillSyncRunEntity:
        row = await self._tx.connection.fetchrow(
            """UPDATE trading.fill_sync_runs SET
                trigger_type = $2,
                scope = $3,
                dry_run = $4,
                total_accounts = $5,
                succeeded_accounts = $6,
                partial_accounts = $7,
                failed_accounts = $8,
                skipped_accounts = $9,
                fills_synced_total = $10,
                fills_skipped_total = $11,
                error_count = $12,
                status = $13,
                env_filter = $14,
                summary_json = $15,
                started_at = $16,
                completed_at = $17
               WHERE fill_sync_run_id = $1
               RETURNING *""",
            run.fill_sync_run_id,
            run.trigger_type,
            run.scope,
            run.dry_run,
            run.total_accounts,
            run.succeeded_accounts,
            run.partial_accounts,
            run.failed_accounts,
            run.skipped_accounts,
            run.fills_synced_total,
            run.fills_skipped_total,
            run.error_count,
            run.status,
            run.env_filter,
            json.dumps(run.summary_json) if run.summary_json is not None else json.dumps({}),
            run.started_at,
            run.completed_at,
        )
        return row_to_entity(row, FillSyncRunEntity)

    async def get_sync_health_summary(
        self,
        stale_threshold_seconds: int = 1800,
    ) -> FillSyncHealthSummary:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.fill_sync_runs ORDER BY started_at DESC LIMIT 100",
        )
        if not rows:
            return FillSyncHealthSummary(
                last_run_started_at=None,
                last_run_completed_at=None,
                last_status=None,
                last_successful_run_at=None,
                consecutive_failures=0,
                is_stale=True,
                stale_threshold_seconds=stale_threshold_seconds,
                retried_accounts=0,
                retried_days=0,
                total_retries=0,
            )
        entities = [row_to_entity(row, FillSyncRunEntity) for row in rows]
        last = entities[0]
        last_successful = next((entity for entity in entities if entity.status == "completed"), None)
        consecutive_failures = 0
        for entity in entities:
            if entity.status == "failed":
                consecutive_failures += 1
            else:
                break
        now = datetime.now(timezone.utc)
        last_successful_at = last_successful.started_at if last_successful else None
        is_stale = True
        if last_successful_at is not None:
            is_stale = (now - last_successful_at).total_seconds() > stale_threshold_seconds
        summary_json = last.summary_json or {}
        return FillSyncHealthSummary(
            last_run_started_at=last.started_at,
            last_run_completed_at=last.completed_at,
            last_status=last.status,
            last_successful_run_at=last_successful_at,
            consecutive_failures=consecutive_failures,
            is_stale=is_stale,
            stale_threshold_seconds=stale_threshold_seconds,
            retried_accounts=int(summary_json.get("retried_accounts", 0) or 0),
            retried_days=int(summary_json.get("retried_days", 0) or 0),
            total_retries=int(summary_json.get("total_retries", 0) or 0),
        )
