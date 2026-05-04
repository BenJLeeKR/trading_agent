"""Reconciliation inspection endpoints: ``GET /reconciliation/runs``,
``GET /reconciliation/locks``.

Results are sorted by ``started_at`` descending (newest first).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import BlockingLockStatus, ReconciliationRunSummary
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.get("/runs", response_model=list[ReconciliationRunSummary])
async def list_reconciliation_runs(
    account_id: str = Query(..., description="Account ID (required)"),
    limit: int = Query(20, ge=1, le=100),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[ReconciliationRunSummary]:
    """List reconciliation runs for an account.

    ``account_id`` is **required** to scope the query.
    Results are sorted by ``started_at`` descending (newest first).
    """
    try:
        uid = UUID(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {account_id}") from exc

    runs = await repos.reconciliations.list_runs_by_account(uid, limit=limit)
    return [
        ReconciliationRunSummary(
            reconciliation_run_id=str(r.reconciliation_run_id),
            account_id=str(r.account_id),
            trigger_type=r.trigger_type,
            status=r.status,
            started_at=r.started_at,
            completed_at=r.completed_at,
            mismatch_count=r.mismatch_count,
        )
        for r in runs
    ]


@router.get("/locks", response_model=list[BlockingLockStatus])
async def list_blocking_locks(
    account_id: str = Query(..., description="Account ID (required)"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[BlockingLockStatus]:
    """List active (non-expired) blocking locks for an account.

    ``account_id`` is **required** to scope the query.
    """
    try:
        uid = UUID(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {account_id}") from exc

    # The in-memory reconciliation repository stores locks internally.
    # We access the private store for inspection purposes.
    # In Postgres mode, this would query `trading.order_blocking_locks`.
    repo = repos.reconciliations
    if hasattr(repo, "_blocking_locks"):
        locks: list[BlockingLockStatus] = []
        for key, value in repo._blocking_locks.items():  # type: ignore[attr-defined]
            if key[0] != uid:
                continue
            # Skip expired locks
            from datetime import datetime, timezone

            expires_at = value.get("expires_at")
            if expires_at and expires_at <= datetime.now(timezone.utc):
                continue
            locks.append(
                BlockingLockStatus(
                    account_id=str(key[0]),
                    strategy_id=str(key[1]) if key[1] else None,
                    symbol=key[2],
                    side=key[3],
                    reason=value.get("reason", "reconciliation"),
                    locked_by_run_id=str(value.get("locked_by_run_id", "")),
                    expires_at=expires_at,
                )
            )
        return locks

    # Fallback for Postgres or unknown repos: return empty.
    return []
