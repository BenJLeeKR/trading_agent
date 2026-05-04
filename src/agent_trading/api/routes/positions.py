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
    """
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    snapshots = await repos.position_snapshots.list_latest_by_account(aid)
    return [PositionSnapshotView.model_validate(s) for s in snapshots]


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
    if snapshot is None:
        return None
    return CashBalanceSnapshotView.model_validate(snapshot)
