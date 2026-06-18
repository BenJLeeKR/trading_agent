"""FastAPI ``create_app()`` factory and default ``app`` instance.

Usage::

    from agent_trading.api.app import app  # default (in-memory)

    # Or inject custom repos:
    from agent_trading.api.app import create_app
    custom_app = create_app(repos=my_repos)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
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
    broker_adapter: object | None = None,
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
        # Record process startup timestamp for grace-period logic
        _app.state.started_at = datetime.now(timezone.utc)

        # Configure security module at startup
        configure_security(token=auth_token, role=auth_role)

        # Store broker adapter for /broker-capacity inspection endpoint
        _app.state.broker_adapter = broker_adapter

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

    # Phase 2 routers (Milestone 6 — account/client/instrument inspection)
    from agent_trading.api.routes.accounts import router as accounts_router
    from agent_trading.api.routes.instruments import router as instruments_router
    from agent_trading.api.routes.positions import router as positions_router
    from agent_trading.api.routes.clients import router as clients_router

    protected_routers.extend(
        [accounts_router, instruments_router, positions_router, clients_router]
    )

    # Phase 2b — Guardrail evaluation & risk limit snapshot inspection
    from agent_trading.api.routes.guardrail_evaluations import (
        router as guardrail_evaluations_router,
    )
    from agent_trading.api.routes.risk_limit_snapshots import (
        router as risk_limit_snapshots_router,
    )
    from agent_trading.api.routes.signal_feature_snapshots import (
        router as signal_feature_snapshots_router,
    )

    protected_routers.extend(
        [
            guardrail_evaluations_router,
            risk_limit_snapshots_router,
            signal_feature_snapshots_router,
        ]
    )

    # Phase 3 — Agent Run inspection
    from agent_trading.api.routes.agent_runs import router as agent_runs_router

    protected_routers.append(agent_runs_router)

    # Phase 3b — Broker Capacity inspection
    from agent_trading.api.routes.broker_capacity import router as broker_capacity_router

    protected_routers.append(broker_capacity_router)

    # Phase 4 — Snapshot Sync Run inspection
    from agent_trading.api.routes.snapshot_sync_runs import router as snapshot_sync_runs_router

    protected_routers.append(snapshot_sync_runs_router)

    # Phase 4b — Fill history inspection
    from agent_trading.api.routes.fill_history import router as fill_history_router

    protected_routers.append(fill_history_router)

    # Phase 5 — Paper performance summary
    from agent_trading.api.routes.performance import router as performance_router

    protected_routers.append(performance_router)

    # Phase 5b — Enum metadata inspection
    from agent_trading.api.routes.metadata import router as metadata_router

    protected_routers.append(metadata_router)

    # Phase 5c — Market Session status inspection
    from agent_trading.api.routes.sessions import router as sessions_router

    protected_routers.append(sessions_router)

    # Phase L — External Events inspection (recent events panel)
    from agent_trading.api.routes.external_events import router as external_events_router

    protected_routers.append(external_events_router)

    # Phase 3 — Execution Attempt inspection
    from agent_trading.api.routes.execution_attempts import (
        router as execution_attempts_router,
    )

    protected_routers.append(execution_attempts_router)

    # Phase 6 — Account Snapshots combined endpoint (cash + positions alignment)
    from agent_trading.api.routes.account_snapshots import (
        router as account_snapshots_router,
    )

    protected_routers.append(account_snapshots_router)

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

    Broker adapter
    --------------
    When ``API_RUNTIME_MODE=postgres``, this factory also attempts to build a
    :class:`~agent_trading.brokers.koreainvestment.adapter.KoreaInvestmentAdapter`
    so that ``GET /broker-capacity`` returns live REST budget and WebSocket
    subscription snapshots.  If KIS credentials are missing or the adapter
    cannot be constructed, a warning is logged and the API server continues
    without a broker adapter (``/broker-capacity`` returns 503).
    """
    import os

    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import build_api_broker_adapter

    mode = os.getenv("API_RUNTIME_MODE", "in_memory")
    token = os.getenv("INSPECTION_API_TOKEN")
    role = os.getenv("INSPECTION_API_ROLE", "viewer")

    # Build broker adapter in Postgres mode only.
    # In-memory mode is for development/testing where KIS credentials may not
    # be available — skip adapter construction entirely.
    broker_adapter: object | None = None
    if mode == "postgres":
        settings = AppSettings()
        broker_adapter = build_api_broker_adapter(settings)

    return create_app(
        runtime_mode=mode,
        auth_token=token,
        auth_role=role,
        broker_adapter=broker_adapter,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Module-level default instance
# ═══════════════════════════════════════════════════════════════════════════
#
# WARNING — This ``app`` is ALWAYS in-memory + auth-disabled.
# Environment variables (API_RUNTIME_MODE, INSPECTION_API_TOKEN) are NOT
# read.  The module-level ``app`` is created at import time with hard-coded
# defaults:
#
#   ❌ uvicorn agent_trading.api.app:app
#       → runtime_mode="in_memory", auth_enabled=False
#
#   ❌ INSPECTION_API_TOKEN=... uvicorn agent_trading.api.app:app
#       → STILL in_memory (token is silently ignored)
#
#   ❌ API_RUNTIME_MODE=postgres uvicorn agent_trading.api.app:app
#       → STILL in_memory (env var is silently ignored)
#
# For Postgres-backed mode with authentication, use create_app_from_env
# with the ``--factory`` flag:
#
#   ✅ uvicorn agent_trading.api.app:create_app_from_env --factory
#
#   ✅ API_RUNTIME_MODE=postgres INSPECTION_API_TOKEN=... \
#        uvicorn agent_trading.api.app:create_app_from_env --factory
#
# See ``docker-compose.yml`` for a complete production-grade example.
# ═══════════════════════════════════════════════════════════════════════════
app = create_app(auth_enabled=False)
