from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import RealizedPnlRecomputeQueueEntity


class PostgresRealizedPnlRecomputeQueueRepository:
    """PostgreSQL implementation of ``RealizedPnlRecomputeQueueRepository``.

    "fill 저장 성공 후 ledger 실패"를 조용히 넘기지 않기 위한 관측 가능한
    복구 계약의 저장소다.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(
        self, item: RealizedPnlRecomputeQueueEntity
    ) -> RealizedPnlRecomputeQueueEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.realized_pnl_recompute_queue
                (recompute_queue_id, account_id, instrument_id, reason_code,
                 triggering_fill_event_id, requested_at, resolved_at,
                 resolved_by_computation_run_id)
            VALUES ($1, $2, $3, $4, $5, COALESCE($6, NOW()), $7, $8)
            RETURNING *
            """,
            item.recompute_queue_id,
            item.account_id,
            item.instrument_id,
            item.reason_code,
            item.triggering_fill_event_id,
            item.requested_at,
            item.resolved_at,
            item.resolved_by_computation_run_id,
        )
        return row_to_entity(row, RealizedPnlRecomputeQueueEntity)

    async def list_pending(
        self, limit: int = 100
    ) -> Sequence[RealizedPnlRecomputeQueueEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.realized_pnl_recompute_queue "
            "WHERE resolved_at IS NULL "
            "ORDER BY requested_at ASC LIMIT $1",
            limit,
        )
        return tuple(row_to_entity(row, RealizedPnlRecomputeQueueEntity) for row in rows)

    async def mark_resolved(
        self,
        recompute_queue_id: UUID,
        *,
        resolved_by_computation_run_id: UUID,
        resolved_at: datetime | None = None,
    ) -> RealizedPnlRecomputeQueueEntity | None:
        row = await self._tx.connection.fetchrow(
            """
            UPDATE trading.realized_pnl_recompute_queue SET
                resolved_at = $2,
                resolved_by_computation_run_id = $3
            WHERE recompute_queue_id = $1
            RETURNING *
            """,
            recompute_queue_id,
            resolved_at or datetime.now(timezone.utc),
            resolved_by_computation_run_id,
        )
        return row_to_entity(row, RealizedPnlRecomputeQueueEntity) if row else None
