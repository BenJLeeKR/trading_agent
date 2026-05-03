from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from agent_trading.db.connection import connection


class TransactionManager:
    """Async context manager for PostgreSQL transactions.

    Wraps an asyncpg connection transaction with explicit commit/rollback.
    Designed to satisfy the ``UnitOfWork`` protocol from
    ``repositories/base.py``.

    Usage::

        async with TransactionManager() as tx:
            await tx.connection.fetch("INSERT ...")
            await tx.commit()

    If neither ``commit()`` nor ``rollback()`` is called explicitly, the
    transaction is rolled back on exit (safe default).
    """

    def __init__(self, *, force_rollback: bool = False) -> None:
        self._connection: asyncpg.Connection | None = None
        self._transaction: asyncpg.transaction.Transaction | None = None
        self._conn_ctx: Any = None
        self._finalized = False
        self._force_rollback = force_rollback

    @property
    def connection(self) -> asyncpg.Connection:
        if self._connection is None:
            raise RuntimeError("Transaction not started. Use 'async with'.")
        return self._connection

    async def __aenter__(self) -> TransactionManager:
        conn_ctx = connection()
        self._connection = await conn_ctx.__aenter__()
        self._conn_ctx = conn_ctx
        self._transaction = self._connection.transaction()
        await self._transaction.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        try:
            if self._finalized:
                return
            if self._force_rollback or exc_type is not None:
                # Force rollback mode (for test fixtures) or exception occurred.
                # asyncpg's Transaction.__aexit__ only rolls back for
                # PostgresError subclasses; for arbitrary Python exceptions
                # (e.g. AttributeError) we must rollback explicitly.
                try:
                    await self._transaction.rollback()
                except Exception:
                    pass
            else:
                # No exception, no force_rollback → commit.
                try:
                    await self._transaction.__aexit__(None, None, None)
                except Exception:
                    pass
        finally:
            await self._conn_ctx.__aexit__(exc_type, exc_val, exc_tb)
            self._connection = None
            self._transaction = None

    async def commit(self) -> None:
        """Commit the current transaction."""
        if self._transaction is None:
            raise RuntimeError("No active transaction to commit.")
        await self._transaction.__aexit__(None, None, None)
        self._finalized = True

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        if self._transaction is None:
            raise RuntimeError("No active transaction to rollback.")
        if self._finalized:
            return
        await self._transaction.rollback()
        self._finalized = True


@asynccontextmanager
async def transaction(
    *, force_rollback: bool = False,
) -> AsyncIterator[TransactionManager]:
    """Shortcut context manager for a single transaction.

    Usage::

        async with transaction() as tx:
            await tx.connection.fetch("INSERT ...")
            await tx.commit()

    Parameters
    ----------
    force_rollback:
        If True, the transaction is always rolled back on exit regardless
        of whether an exception occurred.  Useful for test fixtures.
    """
    async with TransactionManager(force_rollback=force_rollback) as tx:
        yield tx
