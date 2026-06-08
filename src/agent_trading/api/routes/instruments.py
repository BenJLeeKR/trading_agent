"""Instrument inspection endpoints."""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_db, get_repos
from agent_trading.api.schemas import (
    InstrumentDetail,
    InstrumentMappingConsistencySummaryResponse,
    InstrumentMappingGapItem,
)
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["instruments"])
_KST = timezone(timedelta(hours=9))


@router.get(
    "/instruments/mapping-consistency/summary",
    response_model=InstrumentMappingConsistencySummaryResponse,
)
async def get_instrument_mapping_consistency_summary(
    lookback_days: int = Query(default=7, ge=1, le=365),
    db=Depends(get_db),
) -> InstrumentMappingConsistencySummaryResponse:
    """Return recent symbol→instrument master mapping gaps for key runtime tables."""
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    active_instrument_count = await db.fetchval(
        """
        SELECT COUNT(*)
        FROM trading.instruments
        WHERE is_active = TRUE
        """
    )

    external_event_rows = await db.fetch(
        """
        SELECT
            e.symbol AS symbol,
            COUNT(*)::int AS occurrence_count,
            MAX(COALESCE(e.published_at, e.created_at)) AS latest_observed_at
        FROM trading.external_events e
        LEFT JOIN trading.instruments i
          ON i.symbol = e.symbol
        WHERE e.symbol IS NOT NULL
          AND e.symbol <> ''
          AND COALESCE(e.published_at, e.created_at) >= $1
          AND i.instrument_id IS NULL
        GROUP BY e.symbol
        ORDER BY latest_observed_at DESC, e.symbol ASC
        """,
        since,
    )

    broker_fill_rows = await db.fetch(
        """
        SELECT
            bfs.symbol AS symbol,
            COUNT(*)::int AS occurrence_count,
            MAX(COALESCE(bfs.fill_timestamp, bfs.created_at)) AS latest_observed_at
        FROM trading.broker_fill_snapshots bfs
        LEFT JOIN trading.instruments i
          ON i.symbol = bfs.symbol
        WHERE bfs.symbol IS NOT NULL
          AND bfs.symbol <> ''
          AND COALESCE(bfs.fill_timestamp, bfs.created_at) >= $1
          AND i.instrument_id IS NULL
        GROUP BY bfs.symbol
        ORDER BY latest_observed_at DESC, bfs.symbol ASC
        """,
        since,
    )

    unmapped_external_event_symbols = [
        InstrumentMappingGapItem(
            symbol=row["symbol"],
            occurrence_count=row["occurrence_count"],
            latest_observed_at=row["latest_observed_at"],
        )
        for row in external_event_rows
    ]
    unmapped_broker_fill_symbols = [
        InstrumentMappingGapItem(
            symbol=row["symbol"],
            occurrence_count=row["occurrence_count"],
            latest_observed_at=row["latest_observed_at"],
        )
        for row in broker_fill_rows
    ]
    return InstrumentMappingConsistencySummaryResponse(
        lookback_days=lookback_days,
        active_instrument_count=int(active_instrument_count or 0),
        has_gap=bool(unmapped_external_event_symbols or unmapped_broker_fill_symbols),
        total_unmapped_external_event_symbols=len(unmapped_external_event_symbols),
        total_unmapped_broker_fill_symbols=len(unmapped_broker_fill_symbols),
        unmapped_external_event_symbols=unmapped_external_event_symbols,
        unmapped_broker_fill_symbols=unmapped_broker_fill_symbols,
    )


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
