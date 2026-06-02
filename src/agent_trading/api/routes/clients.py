"""Client inspection endpoints: ``GET /clients``, ``GET /clients/{id}``,
``GET /clients/default``."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import ClientDetail
from agent_trading.config.settings import AppSettings
from agent_trading.domain.enums import Environment
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import AccountLookup

router = APIRouter(tags=["clients"])


@router.get("/clients", response_model=list[ClientDetail])
async def list_clients(
    repos: RepositoryContainer = Depends(get_repos),
) -> list[ClientDetail]:
    """List all clients (read‑only, no search/sort/pagination)."""
    clients = await repos.clients.list_all()
    return [ClientDetail.model_validate(c) for c in clients]


@router.get("/clients/default", response_model=ClientDetail)
async def get_default_client(
    repos: RepositoryContainer = Depends(get_repos),
) -> ClientDetail:
    """Return the client that owns the account mapped to the .env ``KIS_ACCOUNT_NO``.

    Resolution chain::

        settings.kis_account_number
        → broker_accounts.get_by_ref(broker_name, account_ref, environment)
        → accounts.find_one(broker_account_id)
        → clients.get(account.client_id)

    Returns 404 when any step in the chain is missing.
    """
    settings = AppSettings()
    kis_account_no = settings.kis_account_number
    if not kis_account_no:
        raise HTTPException(status_code=404, detail="KIS_ACCOUNT_NO not configured")

    # Look up the broker account that matches the .env account reference
    broker_account = await repos.broker_accounts.get_by_ref(
        broker_name="koreainvestment",
        account_ref=kis_account_no,
        environment=Environment(settings.kis_env),
    )
    if not broker_account:
        raise HTTPException(
            status_code=404,
            detail=f"No broker account found for ref={kis_account_no}",
        )

    # Find the internal account linked to this broker account
    account = await repos.accounts.find_one(
        AccountLookup(broker_account_id=broker_account.broker_account_id),
    )
    if not account:
        raise HTTPException(
            status_code=404,
            detail="No internal account linked to broker account",
        )

    # Resolve the client that owns this account
    client = await repos.clients.get(account.client_id)
    if not client:
        raise HTTPException(
            status_code=404,
            detail="Client not found for the resolved account",
        )

    return ClientDetail.model_validate(client)


@router.get("/clients/{client_id}", response_model=ClientDetail)
async def get_client(
    client_id: str,
    repos: RepositoryContainer = Depends(get_repos),
) -> ClientDetail:
    """Get a single client by its UUID."""
    try:
        cid = UUID(client_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid client_id UUID")

    client = await repos.clients.get(cid)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return ClientDetail.model_validate(client)
