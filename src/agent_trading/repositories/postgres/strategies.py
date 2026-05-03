from __future__ import annotations

from uuid import UUID

import asyncpg

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import StrategyEntity


class PostgresStrategyRepository:
    """PostgreSQL implementation of ``StrategyRepository``.

    Satisfies the protocol defined in ``repositories/contracts.py``.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, strategy: StrategyEntity) -> StrategyEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.strategies
                (strategy_id, client_id, strategy_code, name, asset_class, status, description)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
            """,
            strategy.strategy_id,
            strategy.client_id,
            strategy.strategy_code,
            strategy.name,
            strategy.asset_class,
            strategy.status,
            strategy.description,
        )
        return row_to_entity(row, StrategyEntity)

    async def get(self, strategy_id: UUID) -> StrategyEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.strategies WHERE strategy_id = $1",
            strategy_id,
        )
        return row_to_entity(row, StrategyEntity) if row else None

    async def get_by_code(self, client_id: UUID, strategy_code: str) -> StrategyEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.strategies WHERE client_id = $1 AND strategy_code = $2",
            client_id,
            strategy_code,
        )
        return row_to_entity(row, StrategyEntity) if row else None
