"""Risk limit snapshot inspection endpoints: ``GET /risk-limit-snapshots``.

Returns point-in-time risk limit and exposure snapshots for an account,
optionally limited to the most recent entry.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import RiskLimitSnapshotView
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["risk-limit-snapshots"])


def _to_view(snapshot: object) -> RiskLimitSnapshotView:
    """Convert domain entity to API schema."""
    return RiskLimitSnapshotView(
        risk_limit_snapshot_id=snapshot.risk_limit_snapshot_id,
        account_id=snapshot.account_id,
        snapshot_at=snapshot.snapshot_at,
        nav=float(snapshot.nav) if snapshot.nav is not None else None,
        cash_available=(
            float(snapshot.cash_available)
            if snapshot.cash_available is not None
            else None
        ),
        gross_exposure_pct=(
            float(snapshot.gross_exposure_pct)
            if snapshot.gross_exposure_pct is not None
            else None
        ),
        net_exposure_pct=(
            float(snapshot.net_exposure_pct)
            if snapshot.net_exposure_pct is not None
            else None
        ),
        daily_realized_pnl=(
            float(snapshot.daily_realized_pnl)
            if snapshot.daily_realized_pnl is not None
            else None
        ),
        daily_unrealized_pnl=(
            float(snapshot.daily_unrealized_pnl)
            if snapshot.daily_unrealized_pnl is not None
            else None
        ),
        daily_loss_used_pct=(
            float(snapshot.daily_loss_used_pct)
            if snapshot.daily_loss_used_pct is not None
            else None
        ),
        max_daily_loss_limit_pct=(
            float(snapshot.max_daily_loss_limit_pct)
            if snapshot.max_daily_loss_limit_pct is not None
            else None
        ),
        symbol_exposure_json=snapshot.symbol_exposure_json,
        sector_exposure_json=snapshot.sector_exposure_json,
        open_order_exposure_json=snapshot.open_order_exposure_json,
        drawdown_state=snapshot.drawdown_state,
        kill_switch_active=snapshot.kill_switch_active,
        blocked_reason_codes=snapshot.blocked_reason_codes,
        created_at=snapshot.created_at,
    )


@router.get(
    "/risk-limit-snapshots",
    response_model=list[RiskLimitSnapshotView],
)
async def list_risk_limit_snapshots(
    account_id: UUID = Query(..., description="Account UUID"),
    limit: int = Query(20, ge=1, le=200, description="Max results"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[RiskLimitSnapshotView]:
    """List risk limit snapshots for an account, newest first."""
    snapshots = await repos.risk_limit_snapshots.list_by_account(account_id, limit)
    return [_to_view(s) for s in snapshots]


@router.get(
    "/risk-limit-snapshots/latest",
    response_model=RiskLimitSnapshotView,
)
async def get_latest_risk_limit_snapshot(
    account_id: UUID = Query(..., description="Account UUID"),
    repos: RepositoryContainer = Depends(get_repos),
) -> RiskLimitSnapshotView:
    """Get the latest risk limit snapshot for an account."""
    snapshot = await repos.risk_limit_snapshots.get_latest_by_account(account_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No risk limit snapshot found for this account",
        )
    return _to_view(snapshot)
