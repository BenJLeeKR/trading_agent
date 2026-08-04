from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import PositionCostBasisStateEntity


class PostgresPositionCostBasisStateRepository:
    """PostgreSQL implementation of ``PositionCostBasisStateRepository``.

    ``trading.position_cost_basis_state``의 PK는 ``(account_id, instrument_id)``다.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def get(
        self, account_id: UUID, instrument_id: UUID
    ) -> PositionCostBasisStateEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.position_cost_basis_state "
            "WHERE account_id = $1 AND instrument_id = $2",
            account_id,
            instrument_id,
        )
        return row_to_entity(row, PositionCostBasisStateEntity) if row else None

    async def upsert(
        self, state: PositionCostBasisStateEntity
    ) -> PositionCostBasisStateEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.position_cost_basis_state
                (account_id, instrument_id, quantity, average_cost,
                 last_applied_fill_event_id, last_applied_fill_timestamp,
                 recompute_required, recompute_reason, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (account_id, instrument_id) DO UPDATE SET
                quantity = EXCLUDED.quantity,
                average_cost = EXCLUDED.average_cost,
                last_applied_fill_event_id = EXCLUDED.last_applied_fill_event_id,
                last_applied_fill_timestamp = EXCLUDED.last_applied_fill_timestamp,
                recompute_required = EXCLUDED.recompute_required,
                recompute_reason = EXCLUDED.recompute_reason,
                updated_at = NOW()
            RETURNING *
            """,
            state.account_id,
            state.instrument_id,
            state.quantity,
            state.average_cost,
            state.last_applied_fill_event_id,
            state.last_applied_fill_timestamp,
            state.recompute_required,
            state.recompute_reason,
        )
        return row_to_entity(row, PositionCostBasisStateEntity)

    async def list_recompute_required(
        self, limit: int = 100
    ) -> Sequence[PositionCostBasisStateEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.position_cost_basis_state "
            "WHERE recompute_required = TRUE "
            "ORDER BY updated_at ASC LIMIT $1",
            limit,
        )
        return tuple(row_to_entity(row, PositionCostBasisStateEntity) for row in rows)
