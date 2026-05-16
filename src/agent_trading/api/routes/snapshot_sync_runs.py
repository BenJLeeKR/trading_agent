"""KIS Snapshot Sync Run inspection endpoints.

``GET /snapshot-sync-runs`` — list snapshot sync runs, newest first.
``GET /snapshot-sync-runs/summary`` — freshness/health summary for the most recent runs.
``GET /snapshot-sync-runs/{run_id}`` — get a single sync run by UUID.

Results are sorted by ``started_at`` descending (newest first).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import (
    SnapshotSyncRunHealthSummary,
    SnapshotSyncRunSummary,
)
from agent_trading.config.settings import AppSettings
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(prefix="/snapshot-sync-runs", tags=["snapshot-sync"])


def _to_summary(run: object) -> SnapshotSyncRunSummary:
    """Convert a ``SnapshotSyncRunEntity`` to the API response schema."""
    return SnapshotSyncRunSummary(
        snapshot_sync_run_id=str(run.snapshot_sync_run_id),  # type: ignore[attr-defined]
        trigger_type=run.trigger_type,  # type: ignore[attr-defined]
        scope=run.scope,  # type: ignore[attr-defined]
        dry_run=run.dry_run,  # type: ignore[attr-defined]
        total_accounts=run.total_accounts,  # type: ignore[attr-defined]
        succeeded_accounts=run.succeeded_accounts,  # type: ignore[attr-defined]
        partial_accounts=run.partial_accounts,  # type: ignore[attr-defined]
        failed_accounts=run.failed_accounts,  # type: ignore[attr-defined]
        skipped_accounts=run.skipped_accounts,  # type: ignore[attr-defined]
        positions_synced_total=run.positions_synced_total,  # type: ignore[attr-defined]
        positions_skipped_total=run.positions_skipped_total,  # type: ignore[attr-defined]
        cash_synced_count=run.cash_synced_count,  # type: ignore[attr-defined]
        error_count=run.error_count,  # type: ignore[attr-defined]
        status=run.status,  # type: ignore[attr-defined]
        started_at=run.started_at,  # type: ignore[attr-defined]
        completed_at=run.completed_at,  # type: ignore[attr-defined]
        after_hours=run.after_hours,  # type: ignore[attr-defined]
        env_filter=run.env_filter,  # type: ignore[attr-defined]
        status_filter=run.status_filter,  # type: ignore[attr-defined]
        summary_json=run.summary_json,  # type: ignore[attr-defined]
    )


@router.get("", response_model=list[SnapshotSyncRunSummary])
async def list_snapshot_sync_runs(
    limit: int = Query(50, ge=1, le=200, description="Maximum records to return"),
    trigger_type: str | None = Query(
        None, description='Filter by trigger type: "manual" or "scheduler"'
    ),
    status: str | None = Query(
        None, description='Filter by status: "completed", "partial", or "failed"'
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[SnapshotSyncRunSummary]:
    """List KIS snapshot sync execution runs, newest first.

    Optional filters:
    - ``trigger_type`` — ``"manual"`` (CLI) or ``"scheduler"`` (loop)
    - ``status`` — ``"completed"``, ``"partial"``, or ``"failed"``
    - ``limit`` — max records (default 50, max 200)
    """
    runs = await repos.snapshot_sync_runs.list_runs(
        limit=limit,
        trigger_type=trigger_type,
        status=status,
    )
    return [_to_summary(r) for r in runs]


@router.get("/summary", response_model=SnapshotSyncRunHealthSummary)
async def get_snapshot_sync_health_summary(
    repos: RepositoryContainer = Depends(get_repos),
) -> SnapshotSyncRunHealthSummary:
    """Return a freshness/health summary for the most recent snapshot sync runs.

    Indicators include:
    - ``last_run_started_at`` / ``last_run_completed_at`` / ``last_status``
    - ``last_successful_run_at`` — most recent ``status == 'completed'``
    - ``consecutive_failures`` — count of consecutive ``failed`` runs
    - ``is_stale`` — ``True`` when the last successful run exceeds the threshold
    - ``stale_threshold_seconds`` — configured threshold (default 900 = 15 min)
    """
    settings = AppSettings()
    stale_threshold = settings.kis_snapshot_stale_threshold_seconds
    summary = await repos.snapshot_sync_runs.get_sync_health_summary(
        stale_threshold_seconds=stale_threshold,
    )
    return SnapshotSyncRunHealthSummary(
        last_run_started_at=summary.last_run_started_at,
        last_run_completed_at=summary.last_run_completed_at,
        last_status=summary.last_status,
        last_successful_run_at=summary.last_successful_run_at,
        consecutive_failures=summary.consecutive_failures,
        is_stale=summary.is_stale,
        stale_threshold_seconds=summary.stale_threshold_seconds,
        after_hours=summary.after_hours,
    )


@router.get("/{run_id}", response_model=SnapshotSyncRunSummary)
async def get_snapshot_sync_run(
    run_id: str,
    repos: RepositoryContainer = Depends(get_repos),
) -> SnapshotSyncRunSummary:
    """Get a single snapshot sync run by its UUID."""
    try:
        uid = UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid UUID: {run_id}",
        ) from exc

    run = await repos.snapshot_sync_runs.get(uid)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot sync run not found: {run_id}",
        )
    return _to_summary(run)
