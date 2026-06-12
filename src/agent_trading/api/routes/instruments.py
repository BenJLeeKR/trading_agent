"""Instrument inspection endpoints."""

from datetime import date, datetime, timedelta, timezone
from collections import Counter
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agent_trading.api.deps import get_db, get_kis_client, get_repos
from agent_trading.api.schemas import (
    InstrumentDetail,
    InstrumentMappingConsistencySummaryResponse,
    InstrumentMappingGapItem,
    TradingUniversePreviewItem,
    TradingUniversePreviewResponse,
)
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.universe_selection import UniverseSelectionService
from agent_trading.services.universe_selection_types import CompositionContext

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
    snapshot_position_rows = await db.fetch(
        """
        WITH recent_snapshot_errors AS (
            SELECT
                ssr.started_at,
                jsonb_array_elements_text(ssr.summary_json->'errors') AS error_text
            FROM trading.snapshot_sync_runs ssr
            WHERE ssr.started_at >= $1
              AND ssr.summary_json IS NOT NULL
              AND jsonb_typeof(ssr.summary_json->'errors') = 'array'
        )
        SELECT
            substring(error_text FROM 'pdno=([0-9A-Z]+)') AS symbol,
            COUNT(*)::int AS occurrence_count,
            MAX(started_at) AS latest_observed_at
        FROM recent_snapshot_errors
        WHERE error_text LIKE 'Instrument not found for pdno=%'
        GROUP BY substring(error_text FROM 'pdno=([0-9A-Z]+)')
        ORDER BY latest_observed_at DESC, symbol ASC
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
    unmapped_snapshot_position_symbols = [
        InstrumentMappingGapItem(
            symbol=row["symbol"],
            occurrence_count=row["occurrence_count"],
            latest_observed_at=row["latest_observed_at"],
        )
        for row in snapshot_position_rows
        if row["symbol"]
    ]
    return InstrumentMappingConsistencySummaryResponse(
        lookback_days=lookback_days,
        active_instrument_count=int(active_instrument_count or 0),
        has_gap=bool(
            unmapped_external_event_symbols
            or unmapped_broker_fill_symbols
            or unmapped_snapshot_position_symbols
        ),
        total_unmapped_external_event_symbols=len(unmapped_external_event_symbols),
        total_unmapped_broker_fill_symbols=len(unmapped_broker_fill_symbols),
        total_unmapped_snapshot_position_symbols=len(unmapped_snapshot_position_symbols),
        unmapped_external_event_symbols=unmapped_external_event_symbols,
        unmapped_broker_fill_symbols=unmapped_broker_fill_symbols,
        unmapped_snapshot_position_symbols=unmapped_snapshot_position_symbols,
    )


@router.get(
    "/instruments/trading-universe/preview",
    response_model=TradingUniversePreviewResponse,
)
async def get_trading_universe_preview(
    request: Request,
    account_id: str = Query(..., description="Account UUID"),
    lookback_hours: int = Query(default=24, ge=1, le=24 * 30),
    max_cap: int = Query(default=30, ge=1, le=500),
    exclude_held_from_cap: bool = Query(default=True),
    market_overlay_cap: int = Query(default=5, ge=0, le=100),
    pre_pool_size: int = Query(default=50, ge=1, le=500),
    repos: RepositoryContainer = Depends(get_repos),
) -> TradingUniversePreviewResponse:
    """Preview the current composed trading universe for an account.

    This is a read-only inspection endpoint for operators. It runs the same
    deterministic universe composition path used by the decision loop and
    returns the selected symbols plus source / reason summaries.
    """
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    kis_client = get_kis_client(request)
    service = UniverseSelectionService(repos=repos, kis_client=kis_client)
    ctx = CompositionContext(
        account_id=aid,
        since=datetime.now(timezone.utc) - timedelta(hours=lookback_hours),
        max_cap=max_cap,
        exclude_held_from_cap=exclude_held_from_cap,
        market_overlay_cap=market_overlay_cap,
        pre_pool_size=pre_pool_size,
    )
    selected = await service.compose(ctx)

    source_type_counts = Counter(item.source_type.value for item in selected)
    inclusion_reason_counts = Counter(item.inclusion_reason for item in selected)
    items = [
        TradingUniversePreviewItem(
            symbol=item.symbol,
            market=item.market,
            source_type=item.source_type.value,
            inclusion_reason=item.inclusion_reason,
            priority=item.priority,
        )
        for item in selected
    ]
    return TradingUniversePreviewResponse(
        account_id=aid,
        lookback_hours=lookback_hours,
        max_cap=max_cap,
        exclude_held_from_cap=exclude_held_from_cap,
        market_overlay_cap=market_overlay_cap,
        pre_pool_size=pre_pool_size,
        kis_env=getattr(kis_client, "env", None),
        total_count=len(items),
        source_type_counts=dict(source_type_counts),
        inclusion_reason_counts=dict(inclusion_reason_counts),
        items=items,
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
