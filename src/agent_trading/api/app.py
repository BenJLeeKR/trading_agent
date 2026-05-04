"""FastAPI ``create_app()`` factory and default ``app`` instance.

Usage::

    from agent_trading.api.app import app  # default (in-memory)

    # Or inject custom repos:
    from agent_trading.api.app import create_app
    custom_app = create_app(repos=my_repos)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer

try:
    from agent_trading import __version__ as _version
except ImportError:
    _version = "0.1.0"


def create_app(
    repos: RepositoryContainer | None = None,
    *,
    runtime_mode: str = "in_memory",
) -> FastAPI:
    """Create a configured FastAPI application.

    Parameters
    ----------
    repos:
        Repository container to use. When provided, the caller has full control
        and ``runtime_mode`` is treated as a label only.
    runtime_mode:
        Runtime identifier (``"in_memory"`` or ``"postgres"``).

    Returns
    -------
    FastAPI app with routers registered and (in-memory mode) repos attached to
    ``app.state``.

    Notes
    -----
    **Postgres mode** — the lifespan only creates a connection pool on startup
    and closes it on shutdown. Repositories are *not* stored in ``app.state``;
    they are created per request via the ``get_repos`` dependency
    (see :mod:`agent_trading.api.deps`).
    """
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if repos is not None:
            # Explicit repos injected — caller has full control.
            _app.state.repos = repos
            _app.state.runtime_mode = runtime_mode
            yield
            return

        if runtime_mode == "postgres":
            from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool

            db_config = DatabaseConfig()
            await create_pool(db_config)
            _app.state._db_config = db_config
            _app.state.runtime_mode = "postgres"
            try:
                yield
            finally:
                await close_pool()
        else:
            # Default in-memory
            _app.state.repos = build_in_memory_repositories()
            _app.state.runtime_mode = "in_memory"
            yield

    app = FastAPI(
        title="Agent Trading Inspection API",
        description=(
            "Read-only inspection API for the AI Multi-Agent Trading System. "
            "Phase 2 — accounts, clients, instruments, positions, cash-balances, "
            "and broker-orders."
        ),
        version=_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    # Register routers — Phase 1
    from agent_trading.api.routes.health import router as health_router
    from agent_trading.api.routes.orders import router as orders_router
    from agent_trading.api.routes.audit_logs import router as audit_logs_router
    from agent_trading.api.routes.reconciliation import router as reconciliation_router
    from agent_trading.api.routes.decisions import router as decisions_router

    app.include_router(health_router)
    app.include_router(orders_router)
    app.include_router(audit_logs_router)
    app.include_router(reconciliation_router)
    app.include_router(decisions_router)

    # Register routers — Phase 2
    from agent_trading.api.routes.accounts import router as accounts_router
    from agent_trading.api.routes.instruments import router as instruments_router
    from agent_trading.api.routes.positions import router as positions_router
    from agent_trading.api.routes.clients import router as clients_router

    app.include_router(accounts_router)
    app.include_router(instruments_router)
    app.include_router(positions_router)
    app.include_router(clients_router)

    return app


# ── uvicorn --factory support ─────────────────────────────────────────


def create_app_from_env() -> FastAPI:
    """Factory for ``uvicorn ... --factory``.

    Reads ``API_RUNTIME_MODE`` from the environment and delegates to
    :func:`create_app`.  The module-level ``app`` instance (see below) is
    **not** affected — it always stays in-memory.

    Usage in ``docker-compose.yml``::

        command:
          - uvicorn
          - agent_trading.api.app:create_app_from_env
          - --factory
          - --host
          - "0.0.0.0"
          - --port
          - "8000"

    Environment variables
    ---------------------
    API_RUNTIME_MODE : str
        ``"postgres"`` to run in Postgres-backed mode (requires
        ``DATABASE_*`` env vars).  Defaults to ``"in_memory"``.
    """
    import os

    mode = os.getenv("API_RUNTIME_MODE", "in_memory")
    return create_app(runtime_mode=mode)


# Default instance: in-memory repos, suitable for development / inspection.
app = create_app()
