"""``GET /health`` — minimal server and database status.

Uses ``request.app.state.runtime_mode`` directly instead of
``Depends(get_repos)`` to avoid creating request-scoped Postgres
repos for a simple health check.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agent_trading.api.schemas import HealthResponse

router = APIRouter(tags=["health"])

try:
    from agent_trading import __version__ as _version
except ImportError:
    _version = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return minimal server status and database connectivity.

    Uses ``request.app.state.runtime_mode`` directly (no ``Depends(get_repos)``)
    to keep the health probe lightweight and independent of request-scoped repos.
    """
    runtime_mode: str = getattr(request.app.state, "runtime_mode", "in_memory")
    database_status: str = runtime_mode  # fallback: same as mode label

    if runtime_mode == "postgres":
        from agent_trading.db.connection import health_check

        db_ok = await health_check()
        database_status = "connected" if db_ok else "disconnected"

    return HealthResponse(
        status="ok",
        version=_version,
        timestamp=datetime.now(timezone.utc),
        database=database_status,
        runtime_mode=runtime_mode,
    )


@router.get("/health/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Kubernetes-style readiness probe.

    In postgres mode, checks database reachability.
    """
    runtime_mode: str = getattr(request.app.state, "runtime_mode", "in_memory")

    if runtime_mode == "postgres":
        from agent_trading.db.connection import health_check

        db_ok = await health_check()
        if not db_ok:
            return JSONResponse(
                {"status": "not_ready", "reason": "database unreachable"},
                status_code=503,
            )

    return JSONResponse({"status": "ok"})
