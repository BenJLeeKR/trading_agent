"""FastAPI dependency injection — provides ``RepositoryContainer`` to routes.

In-memory mode: returns ``app.state.repos`` (singleton, existing behaviour).
Postgres mode: creates request-scoped ``TransactionManager`` + repos per request.
"""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends, HTTPException, Request

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.order_manager import OrderManager


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


async def get_db(request: Request):
    """Yield an ``asyncpg.Connection`` from the Postgres pool.

    In ``in_memory`` mode the runtime mode check is skipped and this
    dependency raises ``RuntimeError`` so that callers know the DB is
    unavailable — session routes are Postgres-only.

    .. important::

       ``get_db`` yields a raw **Connection**, not a Pool.  Routes must
       **not** call ``db.acquire()`` — use ``db`` directly::

           @router.get("/market-sessions/latest")
           async def latest(db=Depends(get_db)):
               row = await db.fetchrow(...)   # ✓ correct

           # WRONG — db is already a Connection
           # async with db.acquire() as conn:  # AttributeError!
    """
    runtime_mode: str = getattr(request.app.state, "runtime_mode", "in_memory")
    if runtime_mode != "postgres":
        raise RuntimeError(
            "get_db requires API_RUNTIME_MODE=postgres. "
            "Market-session endpoints are not available in in_memory mode."
        )
    from agent_trading.db.connection import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def get_order_manager(
    repos: RepositoryContainer = Depends(get_repos),
) -> AsyncIterator[OrderManager]:
    """Request-scoped ``OrderManager`` for write operations.

    Builds a fresh ``OrderManager`` per request, wired with a
    ``ReconciliationService`` for reconciliation post-processing.
    The manager is yielded and discarded after the response — it is
    stateless from the DB perspective (all state lives in ``repos``).
    """
    from agent_trading.services.reconciliation_service import ReconciliationService

    reconciliation_service = ReconciliationService(repos=repos)
    om = OrderManager(
        repos=repos,
        reconciliation_service=reconciliation_service,
        budget_manager=None,
    )
    yield om


def get_kis_client(request: Request) -> KISRestClient | None:
    """Extract the ``KISRestClient`` from the broker adapter stored on app state.

    Returns ``None`` when no broker adapter is configured (graceful fallback).
    The caller should handle ``None`` by falling back to cached data.

    Usage::

        kis_client = get_kis_client(request)
        if kis_client is not None:
            records = await kis_client.inquire_daily_ccld(...)
    """
    broker_adapter: object | None = getattr(request.app.state, "broker_adapter", None)
    if broker_adapter is None:
        return None
    return getattr(broker_adapter, "rest_client", None)
