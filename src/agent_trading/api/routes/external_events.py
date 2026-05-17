"""External events inspection endpoints: ``GET /external-events/recent``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import ExternalEventView, ExternalEventsResponse
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["external-events"])


@router.get(
    "/external-events/recent",
    response_model=ExternalEventsResponse,
)
async def get_recent_external_events(
    symbol: str = Query(..., description="Stock symbol to filter events"),
    limit: int = Query(5, ge=1, le=50, description="Max events to return"),
    include_non_listed: bool = Query(True, description="Include non-listed events (T3)"),
    since_hours: int = Query(72, ge=1, le=720, description="Lookback window in hours"),
    repos: RepositoryContainer = Depends(get_repos),
) -> ExternalEventsResponse:
    """Return recent external events for a given symbol.

    T1 (OpenDART) + T3 (seeded news) events are both included by default.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    events = await repos.external_events.list_by_symbol(
        symbol=symbol,
        since=cutoff,
        include_non_listed=include_non_listed,
    )
    # Filter by cutoff and limit
    filtered = [e for e in events if e.published_at >= cutoff]
    filtered.sort(key=lambda e: e.published_at, reverse=True)
    top = filtered[:limit]

    return ExternalEventsResponse(
        data=[
            ExternalEventView(
                event_id=str(e.event_id),
                event_type=e.event_type,
                source_name=e.source_name,
                source_reliability_tier=e.source_reliability_tier or "T3",
                symbol=e.symbol,
                headline=e.headline,
                body_summary=e.body_summary,
                published_at=e.published_at,
                created_at=e.created_at,
            )
            for e in top
        ]
    )
