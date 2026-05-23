"""Account snapshot combined endpoint.

``GET /account-snapshots/latest`` — single combined response with
position snapshots + cash balance snapshot + alignment status.

Replaces the two-call pattern (``GET /positions`` + ``GET /cash-balances``)
so the UI always sees a consistent point-in-time view.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import (
    AccountSnapshotResponse,
    AlignmentStatus,
    CashBalanceSnapshotView,
    PositionSnapshotView,
)
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["account-snapshots"])

# ── Tolerance for "same snapshot"判定 ─────────────────────────────
# Positions와 Cash Balance가 동일 sync run에서 캡처되었는지
# timestamp 차이로 판단. KIS API는 보통 동일 HTTP 요청 내에서
# cash+positions를 함께 받아오므로, 5초 이내면 동일 run으로 간주.
_SNAPSHOT_ALIGNMENT_TOLERANCE_SECONDS = 5.0


def _compute_alignment_status(
    positions_snapshot_at: datetime | None,
    cash_snapshot_at: datetime | None,
) -> AlignmentStatus:
    """두 snapshot 시점을 비교하여 alignment 상태를 반환.

    Parameters
    ----------
    positions_snapshot_at:
        가장 최근 position snapshot의 ``snapshot_at``. ``None``이면 포지션 없음.
    cash_snapshot_at:
        가장 최근 cash balance snapshot의 ``snapshot_at``. ``None``이면 캐시 없음.

    Returns
    -------
    AlignmentStatus
        ``"aligned"`` — 두 시점이 동일 (5초 이내 차이)
        ``"partial"`` — 시점 차이가 5초 초과
        ``"unknown"`` — 한쪽 또는 양쪽 데이터가 없음
    """
    if positions_snapshot_at is None or cash_snapshot_at is None:
        return AlignmentStatus.UNKNOWN

    diff = abs((cash_snapshot_at - positions_snapshot_at).total_seconds())
    if diff <= _SNAPSHOT_ALIGNMENT_TOLERANCE_SECONDS:
        return AlignmentStatus.ALIGNED

    return AlignmentStatus.PARTIAL


@router.get("/account-snapshots/latest", response_model=AccountSnapshotResponse)
async def get_latest_account_snapshots(
    account_id: str = Query(..., description="Account UUID"),
    repos: RepositoryContainer = Depends(get_repos),
) -> AccountSnapshotResponse:
    """Get latest position snapshots + cash balance + alignment status
    for a single account — all in one call.

    Parameters
    ----------
    account_id:
        UUID of the account to fetch snapshots for.

    Returns
    -------
    AccountSnapshotResponse
        Combined response with positions, cash balance, and alignment info.

    Raises
    ------
    HTTPException 400
        If ``account_id`` is not a valid UUID.
    """
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    # ── 1. Fetch latest positions ───────────────────────────────────
    snapshots = await repos.position_snapshots.list_latest_by_account(aid)
    positions: list[PositionSnapshotView] = []
    positions_snapshot_at: datetime | None = None
    for s in snapshots:
        view = PositionSnapshotView.model_validate(s)
        inst = await repos.instruments.get(s.instrument_id)
        if inst is not None:
            view.symbol = inst.symbol
            view.instrument_name = inst.name
        positions.append(view)
        # Track the most recent snapshot_at across all positions
        if positions_snapshot_at is None or s.snapshot_at > positions_snapshot_at:
            positions_snapshot_at = s.snapshot_at

    # ── 2. Fetch latest cash balance ────────────────────────────────
    cash_snapshot = await repos.cash_balance_snapshots.get_latest_by_account(aid)
    cash_balance: CashBalanceSnapshotView | None = (
        CashBalanceSnapshotView.model_validate(cash_snapshot)
        if cash_snapshot is not None
        else None
    )
    cash_snapshot_at: datetime | None = (
        cash_snapshot.snapshot_at if cash_snapshot is not None else None
    )

    # ── 3. Compute alignment status ─────────────────────────────────
    alignment_status = _compute_alignment_status(
        positions_snapshot_at, cash_snapshot_at
    )

    return AccountSnapshotResponse(
        account_id=aid,
        positions=positions,
        cash_balance=cash_balance,
        alignment_status=alignment_status,
        positions_snapshot_at=positions_snapshot_at,
        cash_snapshot_at=cash_snapshot_at,
    )
