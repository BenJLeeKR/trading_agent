"""Position / cash-balance inspection endpoints.

``GET /positions`` — point-in-time position snapshots for an account.
``GET /cash-balances`` — latest cash-balance snapshot for an account.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import CashBalanceSnapshotView, PositionSnapshotView
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["positions"])


async def _build_cash_balance_view(
    repos: RepositoryContainer,
    account_id: UUID,
    snapshot,
) -> CashBalanceSnapshotView | None:
    """Build cash balance view with a recent non-null orderable fallback.

    이 백필은 ``get_latest_with_orderable_amount()``로 1건만 DB에서
    직접 조회한다 — ``list_by_account()``로 계좌 전체 현금 이력을 전부
    읽어와 Python에서 첫 non-null 값을 찾던 방식은, 이력이 많은 계좌에서
    요청마다 수천 행을 왕복시켜 이 endpoint의 지배적인 지연 요인이었다
    (실측 근거: PR #318 후속 조사).
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


@router.get("/positions", response_model=list[PositionSnapshotView])
async def list_positions(
    account_id: str = Query(..., description="Account UUID"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[PositionSnapshotView]:
    """List the latest position snapshots for an account.

    .. note::

       This endpoint returns **snapshot** data — not the current live
       position.  All snapshots for the account are returned ordered by
       ``snapshot_at`` descending.  Use the ``snapshot_at`` field to
       identify the most recent observation.

    Each snapshot is enriched with ``symbol`` and ``instrument_name``
    resolved from the ``instrument_id`` via the instruments repository.
    """
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    snapshots = await repos.position_snapshots.list_latest_by_account(aid)
    if not snapshots:
        return []

    # 포지션 1건마다 instruments.get()/position_cost_basis_states.get()을
    # 순차 await하던 N+1을 없애기 위해, instrument 조회 1회(get_many)와
    # 계좌의 cost-basis state 조회 1회(list_by_account)만 배치로 가져온 뒤
    # 메모리에서 조립한다 — 포지션 개수와 무관하게 항상 2회의 배치 조회다.
    instrument_ids = {s.instrument_id for s in snapshots}
    instruments_by_id = await repos.instruments.get_many(instrument_ids)
    cost_basis_states = await repos.position_cost_basis_states.list_by_account(aid)
    cost_basis_by_instrument = {state.instrument_id: state for state in cost_basis_states}

    result: list[PositionSnapshotView] = []
    for s in snapshots:
        view = PositionSnapshotView.model_validate(s)
        inst = instruments_by_id.get(s.instrument_id)
        if inst is not None:
            view.symbol = inst.symbol
            view.instrument_name = inst.name
        cost_basis_state = cost_basis_by_instrument.get(s.instrument_id)
        if cost_basis_state is not None:
            view.remaining_buy_fee_pool = float(cost_basis_state.remaining_buy_fee_pool)
        result.append(view)
    return result


@router.get("/cash-balances", response_model=CashBalanceSnapshotView | None)
async def get_cash_balance(
    account_id: str = Query(..., description="Account UUID"),
    repos: RepositoryContainer = Depends(get_repos),
) -> CashBalanceSnapshotView | None:
    """Get the latest cash-balance snapshot for an account.

    .. note::

       Returns ``null`` when no snapshot exists for the given account.
       This is **not** an error — the account may not be funded yet or
       no snapshot has been recorded.  A non‑null response always carries
       a valid ``CashBalanceSnapshotView``.
    """
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    snapshot = await repos.cash_balance_snapshots.get_latest_by_account(aid)
    return await _build_cash_balance_view(repos, aid, snapshot)
