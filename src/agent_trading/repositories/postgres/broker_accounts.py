from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import BrokerAccountEntity
from agent_trading.domain.enums import Environment


class PostgresBrokerAccountRepository:
    """PostgreSQL implementation of ``BrokerAccountRepository``.

    Uses the UNIQUE constraint on ``(broker_name, account_ref, environment)``
    for the ``get_by_ref`` lookup.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, account: BrokerAccountEntity) -> BrokerAccountEntity:
        row = await self._tx.connection.fetchrow(
            """INSERT INTO trading.broker_accounts
               (broker_account_id, broker_name, account_ref, environment,
                credential_ref, base_url, status, broker_account_code,
                created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               RETURNING *""",
            account.broker_account_id,
            account.broker_name,
            account.account_ref,
            account.environment.value,
            account.credential_ref,
            account.base_url,
            account.status,
            account.broker_account_code,
            account.created_at or datetime.now(timezone.utc),
            account.updated_at or datetime.now(timezone.utc),
        )
        return row_to_entity(row, BrokerAccountEntity)

    async def get(self, broker_account_id: UUID) -> BrokerAccountEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.broker_accounts WHERE broker_account_id = $1",
            broker_account_id,
        )
        return row_to_entity(row, BrokerAccountEntity) if row else None

    async def get_by_ref(
        self,
        broker_name: str,
        account_ref: str,
        environment: Environment,
    ) -> BrokerAccountEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.broker_accounts WHERE broker_name = $1 AND account_ref = $2 AND environment = $3",
            broker_name,
            account_ref,
            environment.value,
        )
        return row_to_entity(row, BrokerAccountEntity) if row else None

    async def list_by_broker(self, broker_name: str) -> Sequence[BrokerAccountEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.broker_accounts WHERE broker_name = $1 ORDER BY account_ref",
            broker_name,
        )
        return tuple(row_to_entity(r, BrokerAccountEntity) for r in rows)
