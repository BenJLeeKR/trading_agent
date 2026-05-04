"""FastAPI dependency injection — provides ``RepositoryContainer`` to routes.

In-memory mode: returns ``app.state.repos`` (singleton, existing behaviour).
Postgres mode: creates request-scoped ``TransactionManager`` + repos per request.
"""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Request

from agent_trading.repositories.container import RepositoryContainer


async def get_repos(request: Request) -> AsyncIterator[RepositoryContainer]:
    """Request-scoped dependency that yields a ``RepositoryContainer``.

    In ``in_memory`` mode, returns the pre-built repos from ``app.state``.
    In ``postgres`` mode, opens a new ``TransactionManager``, builds
    Postgres repos, yields them, then closes the transaction on teardown.
    Postgres repos are tx‑bound — every Postgres repository accesses
    ``self._tx.connection``, so a fresh transaction is required per request.

    Usage (unchanged)::

        @router.get("/orders")
        async def list_orders(
            repos: RepositoryContainer = Depends(get_repos),
        ) -> ...:
    """
    runtime_mode: str = getattr(request.app.state, "runtime_mode", "in_memory")

    if runtime_mode == "postgres":
        from agent_trading.db.transaction import TransactionManager
        from agent_trading.repositories.postgres.bootstrap import (
            build_postgres_repositories,
        )

        tx = TransactionManager()
        await tx.__aenter__()
        try:
            repos = build_postgres_repositories(tx)
            yield repos
        finally:
            await tx.__aexit__(None, None, None)
    else:
        # In-memory: yield the pre‑built singleton repos from app state.
        yield request.app.state.repos
