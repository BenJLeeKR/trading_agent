from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import AccountEntity
from agent_trading.repositories.filters import AccountLookup


class PostgresAccountRepository:
    """PostgreSQL implementation of ``AccountRepository``.

    Satisfies the protocol defined in ``repositories/contracts.py``.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, account: AccountEntity) -> AccountEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.accounts
                (account_id, client_id, broker_account_id, environment,
                 account_alias, account_masked, status, risk_profile,
                 account_code)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
            RETURNING *
            """,
            account.account_id,
            account.client_id,
            account.broker_account_id,
            account.environment.value,
            account.account_alias,
            account.account_masked,
            account.status,
            json.dumps(account.risk_profile) if account.risk_profile is not None else None,
            account.account_code,
        )
        return row_to_entity(row, AccountEntity)

    async def get(self, account_id: UUID) -> AccountEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.accounts WHERE account_id = $1",
            account_id,
        )
        return row_to_entity(row, AccountEntity) if row else None

    async def find_one(self, lookup: AccountLookup) -> AccountEntity | None:
        conditions: list[str] = []
        params: list[object] = []
        idx = 1

        if lookup.account_id is not None:
            conditions.append(f"account_id = ${idx}")
            params.append(lookup.account_id)
            idx += 1
        if lookup.client_id is not None:
            conditions.append(f"client_id = ${idx}")
            params.append(lookup.client_id)
            idx += 1
        if lookup.account_alias is not None:
            conditions.append(f"account_alias = ${idx}")
            params.append(lookup.account_alias)
            idx += 1
        if lookup.environment is not None:
            conditions.append(f"environment = ${idx}")
            params.append(lookup.environment.value)
            idx += 1

        if not conditions:
            return None

        sql = f"SELECT * FROM trading.accounts WHERE {' AND '.join(conditions)} LIMIT 1"
        row = await self._tx.connection.fetchrow(sql, *params)
        return row_to_entity(row, AccountEntity) if row else None

    async def list_by_client(self, client_id: UUID) -> Sequence[AccountEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.accounts WHERE client_id = $1 ORDER BY account_alias",
            client_id,
        )
        return tuple(row_to_entity(r, AccountEntity) for r in rows)

    async def update_metadata(
        self,
        account_id: UUID,
        *,
        account_masked: str | None = None,
    ) -> AccountEntity | None:
        """Update mutable metadata fields on an existing account.

        Only non-``None`` keyword arguments are applied.  ``updated_at`` is
        always bumped to the current UTC timestamp.
        """
        sets: list[str] = []
        params: list[object] = []
        idx = 1

        if account_masked is not None:
            sets.append(f"account_masked = ${idx}")
            params.append(account_masked)
            idx += 1

        if not sets:
            # Nothing to update — just return the current entity
            return await self.get(account_id)

        sets.append(f"updated_at = ${idx}")
        params.append(datetime.now(timezone.utc))
        idx += 1

        params.append(account_id)
        sql = (
            "UPDATE trading.accounts SET "
            + ", ".join(sets)
            + f" WHERE account_id = ${idx} RETURNING *"
        )
        row = await self._tx.connection.fetchrow(sql, *params)
        return row_to_entity(row, AccountEntity) if row else None
