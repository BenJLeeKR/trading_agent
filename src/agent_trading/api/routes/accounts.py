"""Account inspection endpoints: ``GET /accounts``, ``GET /accounts/{id}``."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import AccountSummary
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["accounts"])


@router.get("/accounts", response_model=list[AccountSummary])
async def list_accounts(
    client_id: str = Query(..., description="Client UUID to filter by"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[AccountSummary]:
    """List all accounts belonging to a client.

    ``client_id`` is required — use ``GET /clients`` (Phase 2) to
    discover available client identifiers first.
    """
    try:
        cid = UUID(client_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid client_id UUID")

    accounts = await repos.accounts.list_by_client(cid)
    return [AccountSummary.model_validate(a) for a in accounts]


@router.get("/accounts/{account_id}", response_model=AccountSummary)
async def get_account(
    account_id: str,
    repos: RepositoryContainer = Depends(get_repos),
) -> AccountSummary:
    """Get a single account by its UUID."""
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    account = await repos.accounts.get(aid)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return AccountSummary.model_validate(account)
