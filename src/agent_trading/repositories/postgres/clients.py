from __future__ import annotations

from uuid import UUID

import asyncpg

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import ClientEntity


class PostgresClientRepository:
    """PostgreSQL implementation of ``ClientRepository``.

    Satisfies the protocol defined in ``repositories/contracts.py``.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, client: ClientEntity) -> ClientEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.clients (client_id, client_code, name, status, base_currency)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            client.client_id,
            client.client_code,
            client.name,
            client.status,
            client.base_currency,
        )
        return row_to_entity(row, ClientEntity)

    async def get(self, client_id: UUID) -> ClientEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.clients WHERE client_id = $1",
            client_id,
        )
        return row_to_entity(row, ClientEntity) if row else None

    async def get_by_code(self, client_code: str) -> ClientEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.clients WHERE client_code = $1",
            client_code,
        )
        return row_to_entity(row, ClientEntity) if row else None
