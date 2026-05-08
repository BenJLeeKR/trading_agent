"""Reconciliation inspection endpoints: ``GET /reconciliation/runs``,
``GET /reconciliation/locks``, ``GET /reconciliation/summary``.

Results are sorted by ``started_at`` descending (newest first).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import (
    BlockingLockStatus,
    ReconciliationRunSummary,
    ReconciliationSummary,
)
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
    Delegates to ``ReconciliationRepository.list_locks()`` which handles
    both in-memory and Postgres backends transparently.
    """
    try:
        uid = UUID(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {account_id}") from exc

    from datetime import datetime, timezone

    locks = await repos.reconciliations.list_locks(uid)
    now = datetime.now(timezone.utc)
    return [
        BlockingLockStatus(
            lock_id=str(lock.lock_id),
            account_id=str(lock.account_id),
            strategy_id=str(lock.strategy_id) if lock.strategy_id else None,
            symbol=lock.symbol,
            side=lock.side,
            reason=lock.reason,
            locked_by_run_id=str(lock.locked_by_run_id) if lock.locked_by_run_id else "",
            locked_at=lock.locked_at,
            expires_at=lock.expires_at,
            is_active=lock.expires_at is None or lock.expires_at > now,
        )
        for lock in locks
    ]


@router.get("/summary", response_model=ReconciliationSummary)
async def get_reconciliation_summary(
    repos: RepositoryContainer = Depends(get_repos),
) -> ReconciliationSummary:
    """Return aggregate reconciliation summary across all accounts.

    This endpoint is used by the Dashboard to display system-wide metrics
    without requiring a representative account ID.
    """
    from datetime import datetime, timezone

    runs = await repos.reconciliations.list_all_runs(limit=50)
    locks = await repos.reconciliations.list_all_active_locks()
    now = datetime.now(timezone.utc)

    incomplete_runs = [r for r in runs if r.status != "completed"]

    return ReconciliationSummary(
        active_locks_count=len(locks),
        incomplete_recon_count=len(incomplete_runs),
        recent_active_locks=[
            BlockingLockStatus(
                lock_id=str(lock.lock_id),
                account_id=str(lock.account_id),
                strategy_id=str(lock.strategy_id) if lock.strategy_id else None,
                symbol=lock.symbol,
                side=lock.side,
                reason=lock.reason,
                locked_by_run_id=str(lock.locked_by_run_id) if lock.locked_by_run_id else "",
                locked_at=lock.locked_at,
                expires_at=lock.expires_at,
                is_active=lock.expires_at is None or lock.expires_at > now,
            )
            for lock in locks
        ],
        recent_incomplete_runs=[
            ReconciliationRunSummary(
                reconciliation_run_id=str(r.reconciliation_run_id),
                account_id=str(r.account_id),
                trigger_type=r.trigger_type,
                status=r.status,
                started_at=r.started_at,
                completed_at=r.completed_at,
                mismatch_count=r.mismatch_count,
            )
            for r in incomplete_runs
        ],
        generated_at=now,
    )
