"""Reconciliation inspection endpoints: ``GET /reconciliation/runs``,
``GET /reconciliation/locks``, ``GET /reconciliation/summary``.

Results are sorted by ``started_at`` descending (newest first).
"""

from __future__ import annotations

from typing import Any
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

logger = __import__("logging").getLogger(__name__)


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


async def _classify_failure_reason(
    row: dict[str, Any],
    repos: RepositoryContainer,
) -> str | None:
    """``summary_json.error`` + linked order/lock 상태 기반 ``failure_reason`` 분류.

    분류 우선순위:
    1. ``summary_json.error`` 에 "broker" 포함 → ``"broker 오류: ..."``
    2. 연관 lock 존재 → ``"Lock 충돌"``
    3. ``summary_json.error`` 존재 → 첫 100자
    4. linked order 모두 terminal → ``"연결 주문 정리 완료 (기록용)"``
    5. 미해당 → ``None``
    """
    if row.get("status") in ("completed", "started"):
        return None

    summary_json = row.get("summary_json")
    if isinstance(summary_json, dict):
        error = summary_json.get("error")
        if error:
            error_str = str(error)
            if "broker" in error_str.lower():
                return f"broker 오류: {error_str[:80]}"
            return error_str[:100]

    # lock 존재 여부 확인
    try:
        run_id = row.get("reconciliation_run_id")
        if run_id:
            locks = await repos.reconciliations.list_all_active_locks_for_run(UUID(run_id))
            if locks:
                return "Lock 충돌"
    except Exception as exc:
        logger.warning("Failed to check locks for failure_reason: run_id=%s error=%s", run_id, exc)

    # linked order가 모두 terminal인 경우 (is_active=false 이므로)
    return "연결 주문 정리 완료 (기록용)"


def _build_run_summary(
    row: dict[str, Any],
    *,
    failure_reason: str | None = None,
) -> ReconciliationRunSummary:
    """``list_all_runs_with_activity()`` 결과 row 로 ``ReconciliationRunSummary`` 생성."""
    summary_json = row.get("summary_json")
    error = None
    if isinstance(summary_json, dict):
        error = summary_json.get("error")

    return ReconciliationRunSummary(
        reconciliation_run_id=str(row["reconciliation_run_id"]),
        account_id=str(row["account_id"]),
        trigger_type=row["trigger_type"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row.get("completed_at"),
        mismatch_count=row.get("mismatch_count", 0),
        is_active=row.get("is_active", False),
        failure_reason=failure_reason,
        summary_error=str(error) if error else None,
    )


@router.get("/runs", response_model=list[ReconciliationRunSummary])
async def list_reconciliation_runs(
    account_id: str | None = Query(None, description="Account ID (optional — omit for global view)"),
    limit: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True, description="If true (default), return only active (running or unresolved failed/partial) runs"),
    include_historical: bool = Query(False, description="If true, include historical failed/partial runs (is_active=false)"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[ReconciliationRunSummary]:
    """List reconciliation runs.

    When ``account_id`` is provided, results are scoped to that account.
    When omitted, runs across all accounts are returned (newest first).

    **Default behavior** (``active_only=True``, ``include_historical=False``):
    Only active runs (``is_active=true``) are returned. Historical failed/partial
    runs are hidden from the default view.

    Set ``include_historical=True`` to include historical failed/partial runs
    in the response. Each historical run includes a ``failure_reason`` label
    and ``summary_error`` (the raw ``summary_json.error``).
    """
    try:
        if account_id:
            uid = UUID(account_id)
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
        else:
            rows = await repos.reconciliations.list_all_runs_with_activity(
                limit=limit, active_only=active_only, include_historical=include_historical,
            )
            results: list[ReconciliationRunSummary] = []
            for row in rows:
                is_active = row.get("is_active", False)
                status = row["status"]
                failure_reason: str | None = None

                # historical failed run 에만 failure_reason 산출
                if not is_active and status in ("failed", "partial"):
                    failure_reason = await _classify_failure_reason(row, repos)

                results.append(_build_run_summary(row, failure_reason=failure_reason))
            return results
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {account_id}") from exc
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch reconciliation runs")


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
    include_historical: bool = Query(False, description="If true, include historical failed/partial runs in the count"),
    repos: RepositoryContainer = Depends(get_repos),
) -> ReconciliationSummary:
    """Return aggregate reconciliation summary across all accounts.

    This endpoint is used by the Dashboard to display system-wide metrics
    without requiring a representative account ID.

    ``historical_failed_count`` reflects the number of historical failed/partial
    runs (``is_active=false`` + ``status IN ('failed','partial')``). When
    ``include_historical=False`` (default), historical runs are excluded from
    the detailed ``recent_incomplete_runs`` list but the count is still accurate.
    """
    from datetime import datetime, timezone

    runs_data = await repos.reconciliations.list_all_runs_with_activity(
        limit=100,
        active_only=False,
        include_historical=include_historical,
    )
    locks = await repos.reconciliations.list_all_active_locks()
    now = datetime.now(timezone.utc)

    recent_runs: list[ReconciliationRunSummary] = []
    active_issue_count = 0
    historical_failed_count = 0
    recent_active_issues: list[ReconciliationRunSummary] = []

    for rd in runs_data:
        summary = ReconciliationRunSummary(
            reconciliation_run_id=str(rd["reconciliation_run_id"]),
            account_id=str(rd["account_id"]),
            trigger_type=rd["trigger_type"],
            status=rd["status"],
            started_at=rd["started_at"],
            completed_at=rd.get("completed_at"),
            mismatch_count=rd.get("mismatch_count", 0),
            is_active=rd.get("is_active", False),
        )
        recent_runs.append(summary)

        if summary.is_active:
            active_issue_count += 1
            recent_active_issues.append(summary)
        elif summary.status in ("failed", "partial"):
            historical_failed_count += 1

    incomplete_runs = [r for r in recent_runs if r.status != "completed"]

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
                is_active=r.is_active,
            )
            for r in incomplete_runs
        ],
        generated_at=now,
        active_issue_count=active_issue_count,
        historical_failed_count=historical_failed_count,
        recent_active_issues=recent_active_issues,
    )
