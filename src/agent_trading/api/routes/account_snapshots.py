"""Account snapshot combined endpoint.

``GET /account-snapshots/latest`` — single combined response with
position snapshots + cash balance snapshot + alignment status.

Replaces the two-call pattern (``GET /positions`` + ``GET /cash-balances``)
so the UI always sees a consistent point-in-time view.

The endpoint uses ``snapshot_sync_run_id`` FK to guarantee that positions
and cash balance come from the **exact same sync run** whenever FK data is
available. Falls back to timestamp-based alignment for legacy data.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import TypeAdapter

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import (
    AccountSnapshotResponse,
    AlignmentStatus,
    CashBalanceSnapshotView,
    PositionSnapshotView,
)
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["account-snapshots"])

# ── Fallback tolerance (legacy data without FK) ────────────────────
_SNAPSHOT_ALIGNMENT_TOLERANCE_SECONDS = 5.0


def _compute_alignment_status(
    positions_snapshot_at: datetime | None,
    cash_snapshot_at: datetime | None,
) -> AlignmentStatus:
    """두 snapshot 시점을 비교하여 alignment 상태를 반환 (legacy fallback).

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

    The endpoint first attempts **FK-based alignment**: it finds the latest
    ``snapshot_sync_run_id`` recorded for the account and fetches positions
    + cash balance scoped to that single run. If FK data does not exist
    (legacy rows) it falls back to timestamp-proximity heuristics.

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

    # ── 1. position과 cash 각각 최신 sync_run_id 조회 ───────────────
    pos_sync_id = await repos.position_snapshots.get_latest_sync_run_id(aid)
    cash_sync_id = await repos.cash_balance_snapshots.get_latest_sync_run_id(aid)

    # ── 2. alignment_detail 결정 및 데이터 fetch ─────────────────────
    alignment_detail = "unknown"
    sync_run_id: UUID | None = None

    # 2a. position과 cash가 동일 sync_run (정규 장, 완전 정합)
    if pos_sync_id is not None and pos_sync_id == cash_sync_id:
        alignment_detail = "same_run"
        sync_run_id = pos_sync_id

        sync_positions = await repos.position_snapshots.list_by_sync_run(
            aid, sync_run_id,
        )
        sync_cash = await repos.cash_balance_snapshots.get_by_sync_run(
            aid, sync_run_id,
        )

        positions: list[PositionSnapshotView] = []
        for s in sync_positions:
            view = PositionSnapshotView.model_validate(s)
            inst = await repos.instruments.get(s.instrument_id)
            if inst is not None:
                view.symbol = inst.symbol
                view.instrument_name = inst.name
            positions.append(view)

        cash_balance: CashBalanceSnapshotView | None = (
            CashBalanceSnapshotView.model_validate(sync_cash)
            if sync_cash is not None
            else None
        )

        alignment_status = AlignmentStatus.ALIGNED if positions and cash_balance else AlignmentStatus.PARTIAL

        positions_snapshot_at: datetime | None = (
            max(s.snapshot_at for s in sync_positions)
            if sync_positions
            else None
        )
        cash_snapshot_at: datetime | None = (
            sync_cash.snapshot_at if sync_cash is not None else None
        )

        description = (
            f"포지션과 현금 잔고가 동일 sync-run({str(sync_run_id)[:8]}...) "
            f"기준으로 캡처되었습니다"
        )
        return AccountSnapshotResponse(
            account_id=aid,
            positions=positions,
            cash_balance=cash_balance,
            alignment_status=alignment_status,
            positions_snapshot_at=positions_snapshot_at,
            cash_snapshot_at=cash_snapshot_at,
            snapshot_sync_run_id=str(sync_run_id) if sync_run_id else None,
            alignment_detail=alignment_detail,
            alignment_detail_description=description,
        )

    # 2b. cash만 있고 position은 없음 (cash-only after-hours)
    if cash_sync_id is not None and pos_sync_id is None:
        alignment_detail = "cash_only"
        sync_run_id = cash_sync_id

        # cash만 fetch
        sync_cash = await repos.cash_balance_snapshots.get_by_sync_run(
            aid, sync_run_id,
        )
        cash_balance = (
            CashBalanceSnapshotView.model_validate(sync_cash)
            if sync_cash is not None
            else None
        )

        positions = []
        positions_snapshot_at = None
        cash_snapshot_at = sync_cash.snapshot_at if sync_cash is not None else None

        return AccountSnapshotResponse(
            account_id=aid,
            positions=positions,
            cash_balance=cash_balance,
            alignment_status=AlignmentStatus.PARTIAL,
            positions_snapshot_at=positions_snapshot_at,
            cash_snapshot_at=cash_snapshot_at,
            snapshot_sync_run_id=str(sync_run_id) if sync_run_id else None,
            alignment_detail=alignment_detail,
            alignment_detail_description="현금 잔고 데이터만 조회되었습니다 (포지션 데이터 없음)",
        )

    # 2c. position만 있고 cash는 없음
    if pos_sync_id is not None and cash_sync_id is None:
        alignment_detail = "partial_position_only"
        sync_run_id = pos_sync_id

        sync_positions = await repos.position_snapshots.list_by_sync_run(
            aid, sync_run_id,
        )

        positions = []
        for s in sync_positions:
            view = PositionSnapshotView.model_validate(s)
            inst = await repos.instruments.get(s.instrument_id)
            if inst is not None:
                view.symbol = inst.symbol
                view.instrument_name = inst.name
            positions.append(view)

        cash_balance = None
        positions_snapshot_at = (
            max(s.snapshot_at for s in sync_positions)
            if sync_positions
            else None
        )
        cash_snapshot_at = None

        return AccountSnapshotResponse(
            account_id=aid,
            positions=positions,
            cash_balance=cash_balance,
            alignment_status=AlignmentStatus.PARTIAL,
            positions_snapshot_at=positions_snapshot_at,
            cash_snapshot_at=cash_snapshot_at,
            snapshot_sync_run_id=str(sync_run_id) if sync_run_id else None,
            alignment_detail=alignment_detail,
            alignment_detail_description="포지션 데이터만 조회되었습니다 (현금 잔고 데이터 없음)",
        )

    # 2d. after-hours: position과 cash의 sync_run_id가 다름
    #     cash는 최신 run, position은 이전 정규 장 run
    if pos_sync_id is not None and cash_sync_id is not None and pos_sync_id != cash_sync_id:
        alignment_detail = "after_hours_cash_updated"
        sync_run_id = cash_sync_id  # 최신 cash 기준

        # position은 pos_sync_id로, cash는 cash_sync_id로 각각 fetch
        pos_positions = await repos.position_snapshots.list_by_sync_run(
            aid, pos_sync_id,
        )
        sync_cash = await repos.cash_balance_snapshots.get_by_sync_run(
            aid, cash_sync_id,
        )

        positions = []
        for s in pos_positions:
            view = PositionSnapshotView.model_validate(s)
            inst = await repos.instruments.get(s.instrument_id)
            if inst is not None:
                view.symbol = inst.symbol
                view.instrument_name = inst.name
            positions.append(view)

        cash_balance = (
            CashBalanceSnapshotView.model_validate(sync_cash)
            if sync_cash is not None
            else None
        )

        positions_snapshot_at = (
            max(s.snapshot_at for s in pos_positions)
            if pos_positions
            else None
        )
        cash_snapshot_at = sync_cash.snapshot_at if sync_cash is not None else None

        return AccountSnapshotResponse(
            account_id=aid,
            positions=positions,
            cash_balance=cash_balance,
            alignment_status=AlignmentStatus.ALIGNED,
            positions_snapshot_at=positions_snapshot_at,
            cash_snapshot_at=cash_snapshot_at,
            snapshot_sync_run_id=str(sync_run_id) if sync_run_id else None,
            alignment_detail=alignment_detail,
            alignment_detail_description="포지션은 정규장 sync-run 기준, 현금은 after-hours sync-run 기준입니다",
        )

    # ── 3. Fallback: timestamp-based (legacy data without FK) ──────
    snapshots = await repos.position_snapshots.list_latest_by_account(aid)
    positions = []
    positions_snapshot_at = None
    for s in snapshots:
        view = PositionSnapshotView.model_validate(s)
        inst = await repos.instruments.get(s.instrument_id)
        if inst is not None:
            view.symbol = inst.symbol
            view.instrument_name = inst.name
        positions.append(view)
        if positions_snapshot_at is None or s.snapshot_at > positions_snapshot_at:
            positions_snapshot_at = s.snapshot_at

    cash_snapshot = await repos.cash_balance_snapshots.get_latest_by_account(aid)
    cash_balance = (
        CashBalanceSnapshotView.model_validate(cash_snapshot)
        if cash_snapshot is not None
        else None
    )
    cash_snapshot_at = cash_snapshot.snapshot_at if cash_snapshot is not None else None

    alignment_status = _compute_alignment_status(
        positions_snapshot_at, cash_snapshot_at,
    )
    alignment_detail = "timestamp_proximity"

    return AccountSnapshotResponse(
        account_id=aid,
        positions=positions,
        cash_balance=cash_balance,
        alignment_status=alignment_status,
        positions_snapshot_at=positions_snapshot_at,
        cash_snapshot_at=cash_snapshot_at,
        snapshot_sync_run_id=None,
        alignment_detail=alignment_detail,
        alignment_detail_description="FK 연결 없이 timestamp 근사치로 정합된 legacy 데이터입니다",
    )
