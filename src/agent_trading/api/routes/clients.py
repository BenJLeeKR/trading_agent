"""Client inspection endpoint: ``GET /clients/{id}``."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import ClientDetail
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["clients"])


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
