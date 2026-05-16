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


async def _enrich_lock_status(
    status: BlockingLockStatus,
    repos: RepositoryContainer,
) -> BlockingLockStatus:
    """Resolve ``instrument_name`` from the lock's symbol using any market.

    Falls back gracefully — ``instrument_name`` stays ``None`` when the
    symbol lookup fails or the lock has no symbol.
    """
    if status.symbol:
        inst = await repos.instruments.get_by_symbol_any_market(status.symbol)
        if inst is not None:
            status.instrument_name = inst.name
    return status


@router.get("/runs", response_model=list[ReconciliationRunSummary])
async def list_reconciliation_runs(
    account_id: str | None = Query(None, description="Account ID (optional — omit for global view)"),
    limit: int = Query(20, ge=1, le=100),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[ReconciliationRunSummary]:
    """List reconciliation runs.

    When ``account_id`` is provided, results are scoped to that account.
    When omitted, runs across all accounts are returned (newest first).
    """
    try:
        if account_id:
            uid = UUID(account_id)
            runs = await repos.reconciliations.list_runs_by_account(uid, limit=limit)
        else:
            runs = await repos.reconciliations.list_all_runs(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {account_id}") from exc
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch reconciliation runs")

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
    account_id: str | None = Query(None, description="Account ID (optional — omit for global view)"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[BlockingLockStatus]:
    """List active (non-expired) blocking locks.

    When ``account_id`` is provided, locks are scoped to that account.
    When omitted, locks across all accounts are returned.
    """
    try:
        if account_id:
            uid = UUID(account_id)
            locks = await repos.reconciliations.list_locks(uid)
        else:
            locks = await repos.reconciliations.list_all_active_locks()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {account_id}") from exc
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch blocking locks")

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    results = [
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
    return [await _enrich_lock_status(s, repos) for s in results]


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

    raw_locks = [
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
    enriched_locks = [await _enrich_lock_status(s, repos) for s in raw_locks]

    return ReconciliationSummary(
        active_locks_count=len(locks),
        incomplete_recon_count=len(incomplete_runs),
        recent_active_locks=enriched_locks,
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
