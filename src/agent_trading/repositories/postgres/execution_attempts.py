from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import ExecutionAttemptEntity


class PostgresExecutionAttemptRepository:
    """Postgres-backed repository for ``ExecutionAttemptEntity``.

    Maps to ``trading.execution_attempts`` table.
    JSONB ``phase_trace`` is serialized via ``json.dumps()`` for asyncpg.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(
        self, attempt: ExecutionAttemptEntity
    ) -> ExecutionAttemptEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.execution_attempts
                (execution_attempt_id, trade_decision_id,
                 decision_context_id, status,
                 stop_phase, stop_reason,
                 phase_trace, order_request_id,
                 started_at, completed_at, created_at)
            VALUES ($1, $2, $3, $4, $5, $6,
                    $7::jsonb, $8, $9, $10, $11)
            RETURNING *
            """,
            attempt.execution_attempt_id,
            attempt.trade_decision_id,
            attempt.decision_context_id,
            attempt.status,
            attempt.stop_phase,
            attempt.stop_reason,
            json.dumps(attempt.phase_trace) if attempt.phase_trace is not None else None,
            attempt.order_request_id,
            attempt.started_at,
            attempt.completed_at,
            attempt.created_at or datetime.now(timezone.utc),
        )
        return _row_to_entity(row)

    async def get(
        self, execution_attempt_id: UUID
    ) -> ExecutionAttemptEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.execution_attempts "
            "WHERE execution_attempt_id = $1",
            execution_attempt_id,
        )
        return _row_to_entity(row) if row else None

    async def update_status(
        self,
        execution_attempt_id: UUID,
        status: str,
        *,
        stop_phase: str | None = None,
        stop_reason: str | None = None,
        phase_trace: list[dict[str, object]] | None = None,
        order_request_id: UUID | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        await self._tx.connection.execute(
            """
            UPDATE trading.execution_attempts
            SET status = $1,
                stop_phase = $2,
                stop_reason = $3,
                phase_trace = CASE WHEN $4::jsonb IS NOT NULL
                    THEN $4::jsonb ELSE phase_trace END,
                order_request_id = COALESCE($5, order_request_id),
                completed_at = COALESCE($6, completed_at)
            WHERE execution_attempt_id = $7
            """,
            status,
            stop_phase,
            stop_reason,
            json.dumps(phase_trace) if phase_trace is not None else None,
            order_request_id,
            completed_at,
            execution_attempt_id,
        )

    async def list_by_trade_decision(
        self, trade_decision_id: UUID
    ) -> Sequence[ExecutionAttemptEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.execution_attempts "
            "WHERE trade_decision_id = $1 "
            "ORDER BY started_at DESC",
            trade_decision_id,
        )
        return [_row_to_entity(r) for r in rows]


def _row_to_entity(row) -> ExecutionAttemptEntity:
    # JSONB phase_trace: asyncpg는 설정에 따라 문자열로 반환할 수 있음
    raw_phase_trace = row.get("phase_trace")
    if isinstance(raw_phase_trace, str):
        try:
            phase_trace = json.loads(raw_phase_trace)
        except (json.JSONDecodeError, TypeError):
            phase_trace = raw_phase_trace
    else:
        phase_trace = raw_phase_trace

    return ExecutionAttemptEntity(
        execution_attempt_id=row["execution_attempt_id"],
        trade_decision_id=row["trade_decision_id"],
        decision_context_id=row["decision_context_id"],
        status=row["status"],
        stop_phase=row.get("stop_phase"),
        stop_reason=row.get("stop_reason"),
        phase_trace=phase_trace,
        order_request_id=row.get("order_request_id"),
        started_at=row["started_at"],
        completed_at=row.get("completed_at"),
        created_at=row.get("created_at"),
    )
