from __future__ import annotations

import asyncpg

from agent_trading.db.transaction import TransactionManager
from agent_trading.repositories.base import UnitOfWork


class PostgresUnitOfWork(UnitOfWork):
    """Adapter that makes ``TransactionManager`` satisfy the ``UnitOfWork`` protocol.

    This allows the existing ``RepositoryContainer`` to work with
    PostgreSQL-backed repositories without changing the container type.

    .. note::

       The ``connection`` property is provided for **repository implementations**
       and **test fixtures** only. Service/application layer code **must not**
       access the raw connection directly — all data access should go through
       repository protocols.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    @property
    def transaction(self) -> TransactionManager:
        return self._tx

    @property
    def connection(self) -> asyncpg.Connection:
        """Proxy to the underlying ``TransactionManager.connection``.

        Intended for repository implementations and test fixtures only.
        """
        return self._tx.connection

    async def commit(self) -> None:
        await self._tx.commit()

    async def rollback(self) -> None:
        await self._tx.rollback()
