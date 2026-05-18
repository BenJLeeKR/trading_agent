"""``GET /health`` — minimal server and database status, plus snapshot sync freshness.

Uses ``request.app.state.runtime_mode`` directly instead of
``Depends(get_repos)`` to avoid creating request-scoped Postgres
repos for a simple health check.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agent_trading.api.schemas import HealthResponse, SchedulerHealth

router = APIRouter(tags=["health"])

try:
    from agent_trading import __version__ as _version
except ImportError:
    _version = "0.1.0"


def _snapshot_sync_detail(
    summary: object | None,
) -> tuple[str | None, bool | None, datetime | None, int | None]:
    """Extract snapshot sync freshness fields from a health summary (if available).

    Returns
    -------
    tuple of (detail, is_stale, last_successful_run_at, consecutive_failures)
    """
    if summary is None:
        return None, None, None, None

    # SnapshotSyncHealthSummary dataclass — duck-typing via getattr
    is_stale: bool | None = getattr(summary, "is_stale", None)
    last_successful: datetime | None = getattr(summary, "last_successful_run_at", None)
    consecutive_failures: int | None = getattr(summary, "consecutive_failures", 0)

    if last_successful is None:
        detail = "no_history"
    elif is_stale:
        detail = "stale"
    else:
        detail = "ok"

    return detail, is_stale, last_successful, consecutive_failures


def _is_within_grace(request: Request) -> bool:
    """Check whether the process is still within the startup grace window.

    During this window, snapshot sync freshness checks are skipped in readiness
    probes to avoid false ``degraded`` before the first scheduler run completes.
    """
    from agent_trading.config.settings import AppSettings

    settings = AppSettings()
    grace_seconds = getattr(settings, "kis_snapshot_startup_grace_seconds", 0)
    if grace_seconds <= 0:
        return False

    started_at = getattr(request.app.state, "started_at", None)
    if started_at is None:
        return False

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    return elapsed < grace_seconds


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return minimal server status, database connectivity, and snapshot sync freshness.

    Uses ``request.app.state.runtime_mode`` directly (no ``Depends(get_repos)``)
    to keep the health probe lightweight and independent of request-scoped repos.
    Snapshot sync freshness is included when repos are accessible on ``app.state``
    (in-memory mode).
    """
    runtime_mode: str = getattr(request.app.state, "runtime_mode", "in_memory")
    database_status: str = runtime_mode  # fallback: same as mode label

    if runtime_mode == "postgres":
        from agent_trading.db.connection import health_check

        db_ok = await health_check()
        database_status = "connected" if db_ok else "disconnected"

    # Snapshot sync freshness — only when repos are on app.state
    snapshot_detail: str | None = None
    snapshot_stale: bool | None = None
    snapshot_last_ok: datetime | None = None
    snapshot_failures: int | None = None

    repos = getattr(request.app.state, "repos", None)
    if repos is not None and hasattr(repos, "snapshot_sync_runs"):
        # Startup grace period — skip snapshot sync query, report "starting_up"
        if _is_within_grace(request):
            snapshot_detail = "starting_up"
        else:
            try:
                from agent_trading.config.settings import AppSettings

                settings = AppSettings()
                health_summary = await repos.snapshot_sync_runs.get_sync_health_summary(
                    stale_threshold_seconds=settings.kis_snapshot_stale_threshold_seconds,
                )
                snapshot_detail, snapshot_stale, snapshot_last_ok, snapshot_failures = (
                    _snapshot_sync_detail(health_summary)
                )
            except Exception:
                snapshot_detail = "unavailable"

    # Scheduler freshness — query latest market_sessions row
    scheduler_health = await _get_scheduler_health(database_status)

    return HealthResponse(
        status="ok",
        version=_version,
        timestamp=datetime.now(timezone.utc),
        database=database_status,
        runtime_mode=runtime_mode,
        snapshot_sync_detail=snapshot_detail,
        snapshot_sync_stale=snapshot_stale,
        snapshot_sync_last_successful_run_at=snapshot_last_ok,
        snapshot_sync_consecutive_failures=snapshot_failures,
        scheduler=scheduler_health,
    )


@router.get("/health/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Kubernetes-style readiness probe.

    Checks:
    1. Database reachability (postgres mode only).
    2. Snapshot sync freshness — stale sync → ``degraded``.
    """
    runtime_mode: str = getattr(request.app.state, "runtime_mode", "in_memory")

    # 1. Database check (existing logic)
    if runtime_mode == "postgres":
        from agent_trading.db.connection import health_check

        db_ok = await health_check()
        if not db_ok:
            return JSONResponse(
                {"status": "not_ready", "reason": "database unreachable"},
                status_code=503,
            )

    # 2. Snapshot sync freshness check (when repos are accessible)
    repos = getattr(request.app.state, "repos", None)
    if repos is not None and hasattr(repos, "snapshot_sync_runs"):
        if _is_within_grace(request):
            # Startup grace period — skip stale check, return ok
            pass
        else:
            try:
                from agent_trading.config.settings import AppSettings

                settings = AppSettings()
                health_summary = await repos.snapshot_sync_runs.get_sync_health_summary(
                    stale_threshold_seconds=settings.kis_snapshot_stale_threshold_seconds,
                )
                if health_summary.is_stale:
                    return JSONResponse(
                        {
                            "status": "degraded",
                            "reason": "snapshot_sync_stale",
                            "snapshot_sync_last_successful_run_at": (
                                health_summary.last_successful_run_at.isoformat()
                                if health_summary.last_successful_run_at
                                else None
                            ),
                            "snapshot_sync_consecutive_failures": health_summary.consecutive_failures,
                        },
                    )
            except Exception:
                # Don't fail readiness when the snapshot sync check itself errors
                pass

    return JSONResponse({"status": "ok"})


async def _get_scheduler_health(database_status: str) -> SchedulerHealth | None:
    """Query the latest ``market_sessions`` row for scheduler freshness.

    Returns ``None`` when the database is not connected or the query fails,
    or when no database connection environment variables are set.
    """
    if database_status != "connected":
        return None
    try:
        import os

        # Resolution order matches ``_build_dsn()`` in the ops-scheduler script.
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_DSN")
        if not dsn:
            host = os.environ.get("DATABASE_HOST") or os.environ.get("DB_HOST") or "localhost"
            port = os.environ.get("DATABASE_PORT") or os.environ.get("DB_PORT") or "5432"
            user = os.environ.get("DATABASE_USER") or os.environ.get("DB_USER") or "trading"
            password = os.environ.get("DATABASE_PASSWORD") or os.environ.get("DB_PASSWORD") or "trading"
            dbname = os.environ.get("DATABASE_NAME") or os.environ.get("DB_NAME") or "trading"
            dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

        import asyncpg

        conn = await asyncpg.connect(dsn=dsn)
        try:
            row = await conn.fetchrow(
                "SELECT last_heartbeat_at, checked_at, is_trading_day, market_phase "
                "FROM trading.market_sessions ORDER BY updated_at DESC LIMIT 1"
            )
        finally:
            await conn.close()

        if row is None:
            return SchedulerHealth()

        last_heartbeat: datetime | None = row["last_heartbeat_at"]
        checked_at: datetime | None = row["checked_at"]
        is_trading_day: bool | None = row["is_trading_day"]
        market_phase: str | None = row["market_phase"]
        now = datetime.now(timezone.utc)

        # Derive healthy flag using same logic as Docker healthcheck
        # after_hours/idle phase에서는 heartbeat timeout을 적용하지 않음
        # (Docker healthcheck와 일관성 유지)
        healthy: bool | None = None
        if market_phase in ("after_hours", "idle"):
            healthy = True
        elif is_trading_day and last_heartbeat and (now - last_heartbeat).total_seconds() < 120:
            healthy = True
        elif is_trading_day:
            healthy = False
        elif not is_trading_day and checked_at and (now - checked_at).total_seconds() < 86400:
            healthy = True
        elif not is_trading_day:
            healthy = False

        return SchedulerHealth(
            last_heartbeat_at=last_heartbeat,
            is_trading_day=is_trading_day,
            checked_at=checked_at,
            phase=market_phase,
            healthy=healthy,
        )
    except Exception:
        return None
