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
        Repository container to use. If ``None``, builds in-memory repositories.
    runtime_mode:
        Human-readable runtime identifier (``"in_memory"`` or ``"postgres"``).

    Returns
    -------
    FastAPI app with routers registered and repos attached to ``app.state``.
    """
    if repos is None:
        repos = build_in_memory_repositories()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _app.state.repos = repos
        _app.state.runtime_mode = runtime_mode
        yield

    app = FastAPI(
        title="Agent Trading Inspection API",
        description=(
            "Read-only inspection API for the AI Multi-Agent Trading System. "
            "Phase 1 — 9 endpoints for order, audit, reconciliation, and decision inspection."
        ),
        version=_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    # Register routers
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

    return app


# Default instance: in-memory repos, suitable for development / inspection.
app = create_app()
