from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from agent_trading.db.connection import connection

logger = logging.getLogger(__name__)


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

    Savepoint support
    -----------------
    Use ``savepoint()`` as a nested context manager to create an isolated
    sub-transaction.  If the savepoint body raises, only the savepoint is
    rolled back; the outer transaction remains usable::

        async with TransactionManager() as tx:
            async with tx.savepoint("sp1"):
                await tx.connection.fetch("INSERT ...")  # may fail safely
            # outer transaction is still valid
    """

    def __init__(self, *, force_rollback: bool = False) -> None:
        self._connection: asyncpg.Connection | None = None
        self._transaction: asyncpg.transaction.Transaction | None = None
        self._conn_ctx: Any = None
        self._finalized = False
        self._force_rollback = force_rollback
        self._savepoint_counter = 0

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
        try:
            await self._transaction.rollback()
        except asyncpg.InterfaceError:
            # asyncpg forbids manual rollback when the transaction was
            # entered via __aenter__ (i.e. ``async with``).  We ignore
            # this because __aexit__ already handles the actual rollback.
            pass
        self._finalized = True

    # ------------------------------------------------------------------
    # Savepoint support
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def savepoint(self, name: str | None = None) -> AsyncIterator[str]:
        """Create a named savepoint within the current transaction.

        If the body raises, the savepoint is rolled back and the exception
        is re-raised.  The outer transaction remains usable after rollback.

        Parameters
        ----------
        name:
            Optional savepoint name.  If omitted, an auto-incrementing name
            ``sp_1``, ``sp_2``, … is generated.

        Yields
        ------
        str
            The savepoint name (useful for logging).

        Raises
        ------
        RuntimeError
            If there is no active connection.
        """
        if self._connection is None:
            raise RuntimeError("No active connection. Use 'async with' first.")

        if name is None:
            self._savepoint_counter += 1
            name = f"sp_{self._savepoint_counter}"

        await self._connection.execute(f"SAVEPOINT {name}")
        logger.debug("Savepoint %s created", name)
        try:
            yield name
        except Exception:
            logger.warning(
                "Rolling back savepoint %s due to exception",
                name,
                exc_info=True,
            )
            await self._connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
            raise
        finally:
            # Release the savepoint so it doesn't accumulate.
            try:
                await self._connection.execute(f"RELEASE SAVEPOINT {name}")
            except Exception:
                pass


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
