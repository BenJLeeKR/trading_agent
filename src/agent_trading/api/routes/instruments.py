"""Instrument inspection endpoint: ``GET /instruments/{id}``."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import InstrumentDetail
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["instruments"])


@router.get("/instruments/{instrument_id}", response_model=InstrumentDetail)
async def get_instrument(
    instrument_id: str,
    repos: RepositoryContainer = Depends(get_repos),
) -> InstrumentDetail:
    """Get a single instrument by its UUID."""
    try:
        iid = UUID(instrument_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid instrument_id UUID")

    instrument = await repos.instruments.get(iid)
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    return InstrumentDetail.model_validate(instrument)
