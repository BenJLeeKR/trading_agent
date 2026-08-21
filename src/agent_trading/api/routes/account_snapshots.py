"""Account snapshot combined endpoint.

``GET /account-snapshots/latest`` — single combined response with
position snapshots + cash balance snapshot + alignment status.

Replaces the two-call pattern (``GET /positions`` + ``GET /cash-balances``)
so the UI always sees a consistent point-in-time view.

The endpoint uses ``snapshot_sync_run_id`` FK to guarantee that positions
and cash balance come from the **exact same sync run** whenever FK data is
available. Falls back to timestamp-based alignment for legacy data.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import (
    AccountSnapshotResponse,
    AlignmentStatus,
    CashBalanceSnapshotView,
    PositionSnapshotView,
)
from agent_trading.domain.entities import InstrumentEntity, PositionCostBasisStateEntity
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["account-snapshots"])

# ── Fallback tolerance (legacy data without FK) ────────────────────
_SNAPSHOT_ALIGNMENT_TOLERANCE_SECONDS = 5.0


async def _build_cash_balance_view(
    repos: RepositoryContainer,
    account_id: UUID,
    snapshot,
) -> CashBalanceSnapshotView | None:
    """Build cash balance view with a recent non-null orderable fallback.

    Some latest after-hours / degraded snapshots legitimately store
    ``orderable_amount=None``. For inspection UI readability, backfill the
    most recent non-null ``orderable_amount`` from the same account when the
    latest snapshot omits it.

    이 백필은 ``get_latest_with_orderable_amount()``로 1건만 DB에서
    직접 조회한다 — ``list_by_account()``로 계좌 전체 현금 이력을
    전부 읽어와 Python에서 첫 non-null 값을 찾던 방식은, 이력이 많은
    계좌에서 요청마다 수천 행을 왕복시켜 이 endpoint의 지배적인 지연
    요인이었다(실측 근거: PR #318 후속 조사).
    """
    if snapshot is None:
        return None

    effective_snapshot = snapshot
    if snapshot.orderable_amount is None:
        fallback_snapshot = await repos.cash_balance_snapshots.get_latest_with_orderable_amount(
            account_id,
        )
        fallback_orderable_amount = (
            fallback_snapshot.orderable_amount if fallback_snapshot is not None else None
        )
        if fallback_orderable_amount is not None:
            effective_snapshot = type(snapshot)(
                cash_balance_snapshot_id=snapshot.cash_balance_snapshot_id,
                account_id=snapshot.account_id,
                currency=snapshot.currency,
                available_cash=snapshot.available_cash,
                settled_cash=snapshot.settled_cash,
                unsettled_cash=snapshot.unsettled_cash,
                source_of_truth=snapshot.source_of_truth,
                snapshot_at=snapshot.snapshot_at,
                total_asset=snapshot.total_asset,
                settlement_amount=snapshot.settlement_amount,
                total_unrealized_pnl=snapshot.total_unrealized_pnl,
                orderable_amount=fallback_orderable_amount,
                created_at=snapshot.created_at,
                fetch_status=snapshot.fetch_status,
                snapshot_sync_run_id=snapshot.snapshot_sync_run_id,
            )

    return CashBalanceSnapshotView.model_validate(effective_snapshot)


def _build_position_view(
    snapshot,
    instruments_by_id: dict[UUID, InstrumentEntity],
    cost_basis_by_instrument: dict[UUID, PositionCostBasisStateEntity],
) -> PositionSnapshotView:
    """스냅샷 엔티티 하나를 symbol/instrument_name/remaining_buy_fee_pool까지

    채운 ``PositionSnapshotView``로 변환한다. DB 조회는 하지 않고, 미리
    배치로 가져온 dict에서만 조회한다(``_build_position_views`` 참고).
    """
    view = PositionSnapshotView.model_validate(snapshot)
    inst = instruments_by_id.get(snapshot.instrument_id)
    if inst is not None:
        view.symbol = inst.symbol
        view.instrument_name = inst.name
    cost_basis_state = cost_basis_by_instrument.get(snapshot.instrument_id)
    if cost_basis_state is not None:
        view.remaining_buy_fee_pool = float(cost_basis_state.remaining_buy_fee_pool)
    return view


async def _build_position_views(
    repos: RepositoryContainer,
    account_id: UUID,
    snapshots: Sequence,
) -> list[PositionSnapshotView]:
    """포지션 스냅샷 목록을 ``PositionSnapshotView`` 목록으로 일괄 변환한다.

    예전에는 포지션 1건마다 ``instruments.get()`` + ``position_cost_basis_
    states.get()``을 순차 ``await``해(N+1) 포지션 개수만큼 DB 라운드트립이
    발생했다. 여기서는 이 파일의 4개 코드 경로(same_run /
    partial_position_only / after_hours_cash_updated / timestamp_proximity
    fallback)가 공통으로, instrument 조회 1회(``get_many``)와 계좌의
    cost-basis state 조회 1회(``list_by_account``)만 수행한 뒤 메모리에서
    조립한다 — 포지션 개수와 무관하게 항상 2회의 배치 조회다.
    """
    if not snapshots:
        return []
    instrument_ids = {s.instrument_id for s in snapshots}
    instruments_by_id = await repos.instruments.get_many(instrument_ids)
    cost_basis_states = await repos.position_cost_basis_states.list_by_account(account_id)
    cost_basis_by_instrument = {s.instrument_id: s for s in cost_basis_states}
    return [
        _build_position_view(s, instruments_by_id, cost_basis_by_instrument)
        for s in snapshots
    ]


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

        positions: list[PositionSnapshotView] = await _build_position_views(
            repos, aid, sync_positions,
        )

        cash_balance = await _build_cash_balance_view(repos, aid, sync_cash)

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
        cash_balance = await _build_cash_balance_view(repos, aid, sync_cash)

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

        positions = await _build_position_views(repos, aid, sync_positions)

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

        positions = await _build_position_views(repos, aid, pos_positions)

        cash_balance = await _build_cash_balance_view(repos, aid, sync_cash)

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
    positions = await _build_position_views(repos, aid, snapshots)
    positions_snapshot_at = (
        max(s.snapshot_at for s in snapshots) if snapshots else None
    )

    cash_snapshot = await repos.cash_balance_snapshots.get_latest_by_account(aid)
    cash_balance = await _build_cash_balance_view(repos, aid, cash_snapshot)
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
