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

from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer

try:
    from agent_trading import __version__ as _version
except ImportError:
    _version = "0.1.0"

from agent_trading.api.security import configure_security, require_viewer

_VALID_ROLES = frozenset({"viewer", "admin"})


def create_app(
    repos: RepositoryContainer | None = None,
    *,
    runtime_mode: str = "in_memory",
    auth_enabled: bool = True,
    auth_token: str | None = None,
    auth_role: str = "viewer",
) -> FastAPI:
    """Create a configured FastAPI application.

    Parameters
    ----------
    repos:
        Repository container to use. When provided, the caller has full control
        and ``runtime_mode`` is treated as a label only.
    runtime_mode:
        Runtime identifier (``"in_memory"`` or ``"postgres"``).
    auth_enabled:
        Whether to enforce Bearer token authentication on protected endpoints.
        ``True`` (default) — token validation is active.
        ``False`` — all endpoints are open (development / testing only).
    auth_token:
        The expected Bearer token value.  **Required** when ``auth_enabled=True``.
        Ignored when ``auth_enabled=False``.
    auth_role:
        Role assigned to authenticated principals (``"viewer"`` or ``"admin"``).
        Defaults to ``"viewer"``.

    Returns
    -------
    FastAPI app with routers registered and (in-memory mode) repos attached to
    ``app.state``.

    Raises
    ------
    ValueError
        If ``auth_enabled=True`` and ``auth_token`` is ``None``, empty, or
        whitespace-only.
    ValueError
        If ``auth_role`` is not one of ``{"viewer", "admin"}``.

    Notes
    -----
    **Postgres mode** — the lifespan only creates a connection pool on startup
    and closes it on shutdown. Repositories are *not* stored in ``app.state``;
    they are created per request via the ``get_repos`` dependency
    (see :mod:`agent_trading.api.deps`).
    """
    if auth_enabled and (not auth_token or not auth_token.strip()):
        raise ValueError(
            "auth_token must be a non-empty string when auth_enabled=True. "
            "Set auth_enabled=False explicitly for unauthenticated (dev/test) mode."
        )

    if auth_role not in _VALID_ROLES:
        raise ValueError(
            f"Invalid auth_role={auth_role!r}. "
            f"Allowed values: {sorted(_VALID_ROLES)}"
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Configure security module at startup
        configure_security(token=auth_token, role=auth_role)

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
        swagger_ui_parameters={"persistAuthorization": True},
    )

    # ── OpenAPI security scheme (Authorize button in Swagger UI) ────────────
    # Register the scheme in `components` so the Authorize button appears.
    # Do NOT set global `security` — that would force ALL endpoints (including
    # health) to show the lock icon in Swagger UI.  Public endpoints are
    # documented as public; protected endpoints enforce auth at runtime via
    # the require_viewer dependency.
    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        openapi_schema["components"]["securitySchemes"] = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",  # format only, not actual JWT
            }
        }
        # No global `security` — public endpoints stay unlocked in Swagger UI.
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    # ── Register routers ──────────────────────────────────────────────────
    # Phase 1 routers
    from agent_trading.api.routes.health import router as health_router
    from agent_trading.api.routes.orders import router as orders_router
    from agent_trading.api.routes.audit_logs import router as audit_logs_router
    from agent_trading.api.routes.reconciliation import router as reconciliation_router
    from agent_trading.api.routes.decisions import router as decisions_router

    # Health is public — no auth dependencies
    app.include_router(health_router)

    # Protected routers — require viewer role when auth is enabled
    protected_routers = [
        orders_router,
        audit_logs_router,
        reconciliation_router,
        decisions_router,
    ]

    # Phase 2 routers
    from agent_trading.api.routes.accounts import router as accounts_router
    from agent_trading.api.routes.instruments import router as instruments_router
    from agent_trading.api.routes.positions import router as positions_router
    from agent_trading.api.routes.clients import router as clients_router

    protected_routers.extend(
        [accounts_router, instruments_router, positions_router, clients_router]
    )

    # Phase 3 — Agent Run inspection
    from agent_trading.api.routes.agent_runs import router as agent_runs_router

    protected_routers.append(agent_runs_router)

    if auth_enabled:
        for router in protected_routers:
            app.include_router(router, dependencies=[Depends(require_viewer)])
    else:
        for router in protected_routers:
            app.include_router(router)

    # ── Admin UI static files ─────────────────────────────────────────────
    # Mount the built React app under /admin if the dist directory exists.
    # The UI shell (HTML/CSS/JS) is publicly served; data access requires
    # Bearer token authentication via the API layer.
    import os

    _admin_ui_dist = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "admin_ui", "dist")
    )
    if os.path.isdir(_admin_ui_dist):
        app.mount(
            "/admin",
            StaticFiles(directory=_admin_ui_dist, html=True),
            name="admin_ui",
        )

    return app


# ── uvicorn --factory support ─────────────────────────────────────────


def create_app_from_env() -> FastAPI:
    """Factory for ``uvicorn ... --factory``.

    Reads environment variables and delegates to :func:`create_app`.
    The module-level ``app`` instance (see below) is **not** affected —
    it always stays in-memory.

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
    INSPECTION_API_TOKEN : str
        Bearer token for authentication.  **Required in production.**
        When missing, ``create_app`` raises ``ValueError`` (startup fail).
    INSPECTION_API_ROLE : str
        Role assigned to authenticated principals (default ``"viewer"``).
        Currently unused for authorization logic, but reserved for future use.
    """
    import os

    mode = os.getenv("API_RUNTIME_MODE", "in_memory")
    token = os.getenv("INSPECTION_API_TOKEN")
    role = os.getenv("INSPECTION_API_ROLE", "viewer")
    return create_app(runtime_mode=mode, auth_token=token, auth_role=role)


# Default instance: in-memory repos, suitable for development / inspection.
# Auth is disabled for the module-level default so that quick `uvicorn ...:app`
# invocations work without requiring INSPECTION_API_TOKEN.
# Production deployments MUST use create_app_from_env() or docker-compose.
app = create_app(auth_enabled=False)
