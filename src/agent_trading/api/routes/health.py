"""``GET /health`` — minimal server and database status."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import HealthResponse
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["health"])

try:
    from agent_trading import __version__ as _version
except ImportError:
    _version = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health(
    repos: RepositoryContainer = Depends(get_repos),
) -> HealthResponse:
    """Return minimal server status and database connectivity."""
    runtime_mode: str = "in_memory"
    database_status: str = "in_memory"

    # Attempt a lightweight DB probe if Postgres repos are detected.
    uow = repos.unit_of_work
    if hasattr(uow, "_pool") and uow._pool is not None:  # type: ignore[attr-defined]
        runtime_mode = "postgres"
        try:
            async with uow._pool.acquire() as conn:  # type: ignore[attr-defined]
                await conn.execute("SELECT 1")
                database_status = "connected"
        except Exception:  # noqa: BLE001
            database_status = "disconnected"

    return HealthResponse(
        status="ok",
        version=_version,
        timestamp=datetime.now(timezone.utc),
        database=database_status,
        runtime_mode=runtime_mode,
    )


@router.get("/health/readyz")
async def readyz() -> JSONResponse:
    """Kubernetes-style readiness probe — always 200 for now."""
    return JSONResponse({"status": "ok"})
