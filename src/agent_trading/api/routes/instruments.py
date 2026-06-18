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
    MarketOverlayFunnelItem,
    MarketOverlayFunnelResponse,
    MarketOverlayDiagnosticsView,
    TradingUniverseCoverageItem,
    TradingUniverseCoverageSummaryResponse,
    TradingUniversePreviewItem,
    TradingUniversePreviewResponse,
)
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.universe_selection import UniverseSelectionService
from agent_trading.services.universe_selection_types import CompositionContext

router = APIRouter(tags=["instruments"])
_KST = timezone(timedelta(hours=9))


def _parse_manual_symbols(raw: str | None) -> tuple[tuple[str, str], ...]:
    if raw is None or not raw.strip():
        return ()

    parsed: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token:
            continue
        if ":" in token:
            symbol_part, market_part = token.split(":", 1)
            symbol = symbol_part.strip()
            market = market_part.strip().upper() or "KRX"
        else:
            symbol = token
            market = "KRX"
        if not symbol:
            continue
        key = (symbol, market)
        if key not in seen:
            parsed.append(key)
            seen.add(key)
    return tuple(parsed)


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
    core_cap: int | None = Query(default=12, ge=1, le=500),
    exclude_held_from_cap: bool = Query(default=True),
    market_overlay_cap: int = Query(default=5, ge=0, le=100),
    pre_pool_size: int = Query(default=50, ge=1, le=500),
    manual_symbols: str | None = Query(
        default=None,
        description="Optional manual watchlist symbols. Example: 005930,000660:KRX",
    ),
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
        core_cap=core_cap,
        exclude_held_from_cap=exclude_held_from_cap,
        market_overlay_cap=market_overlay_cap,
        pre_pool_size=pre_pool_size,
        manual_symbols=_parse_manual_symbols(manual_symbols),
    )
    selected, market_overlay_diagnostics = await service.compose_with_diagnostics(ctx)

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
        core_cap=core_cap,
        exclude_held_from_cap=exclude_held_from_cap,
        market_overlay_cap=market_overlay_cap,
        pre_pool_size=pre_pool_size,
        kis_env=getattr(kis_client, "env", None),
        total_count=len(items),
        source_type_counts=dict(source_type_counts),
        inclusion_reason_counts=dict(inclusion_reason_counts),
        market_overlay_diagnostics=MarketOverlayDiagnosticsView(
            enabled=market_overlay_diagnostics.enabled,
            skipped_reason=market_overlay_diagnostics.skipped_reason,
            effective_pre_pool_size=market_overlay_diagnostics.effective_pre_pool_size,
            pre_pool_candidate_count=market_overlay_diagnostics.pre_pool_candidate_count,
            quotes_requested_count=market_overlay_diagnostics.quotes_requested_count,
            quotes_received_count=market_overlay_diagnostics.quotes_received_count,
            filtered_out_count=market_overlay_diagnostics.filtered_out_count,
            scored_candidate_count=market_overlay_diagnostics.scored_candidate_count,
            added_count=market_overlay_diagnostics.added_count,
        ),
        items=items,
    )


@router.get(
    "/instruments/trading-universe/coverage-summary",
    response_model=TradingUniverseCoverageSummaryResponse,
)
async def get_trading_universe_coverage_summary(
    lookback_days: int = Query(default=14, ge=1, le=90),
    db=Depends(get_db),
) -> TradingUniverseCoverageSummaryResponse:
    """Summarize recent source-type coverage from decision to order creation.

    This is an operational measurement endpoint for Universe Selection /
    market_overlay effectiveness. It aggregates recent trade decisions and
    created orders by ``source_type``.
    """
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    rows = await db.fetch(
        """
        WITH decision_stats AS (
            SELECT
                COALESCE(td.source_type, 'unknown') AS source_type,
                COUNT(*)::int AS decision_count,
                MIN(td.created_at) AS first_decision_at,
                MAX(td.created_at) AS last_decision_at
            FROM trading.trade_decisions td
            WHERE td.created_at >= $1
            GROUP BY COALESCE(td.source_type, 'unknown')
        ),
        order_stats AS (
            SELECT
                COALESCE(td.source_type, 'unknown') AS source_type,
                COUNT(*)::int AS order_count,
                MAX(o.created_at) AS last_order_at
            FROM trading.order_requests o
            JOIN trading.trade_decisions td
              ON td.trade_decision_id = o.trade_decision_id
            WHERE o.created_at >= $1
            GROUP BY COALESCE(td.source_type, 'unknown')
        )
        SELECT
            ds.source_type,
            ds.decision_count,
            COALESCE(os.order_count, 0)::int AS order_count,
            ds.first_decision_at,
            ds.last_decision_at,
            os.last_order_at
        FROM decision_stats ds
        LEFT JOIN order_stats os
          ON os.source_type = ds.source_type
        ORDER BY ds.decision_count DESC, ds.source_type ASC
        """,
        since,
    )

    items = [
        TradingUniverseCoverageItem(
            source_type=row["source_type"],
            decision_count=int(row["decision_count"] or 0),
            order_count=int(row["order_count"] or 0),
            order_conversion_rate=(
                float(row["order_count"] or 0) / float(row["decision_count"])
                if row["decision_count"]
                else 0.0
            ),
            first_decision_at=row["first_decision_at"],
            last_decision_at=row["last_decision_at"],
            last_order_at=row["last_order_at"],
        )
        for row in rows
    ]
    total_decision_count = sum(item.decision_count for item in items)
    total_order_count = sum(item.order_count for item in items)
    market_overlay_active = any(
        item.source_type == "market_overlay" and item.decision_count > 0
        for item in items
    )
    return TradingUniverseCoverageSummaryResponse(
        lookback_days=lookback_days,
        total_decision_count=total_decision_count,
        total_order_count=total_order_count,
        market_overlay_active=market_overlay_active,
        items=items,
    )


@router.get(
    "/instruments/trading-universe/market-overlay-funnel",
    response_model=MarketOverlayFunnelResponse,
)
async def get_market_overlay_funnel(
    lookback_days: int = Query(default=14, ge=1, le=90),
    sample_limit: int = Query(default=20, ge=1, le=100),
    db=Depends(get_db),
) -> MarketOverlayFunnelResponse:
    """Return recent `market_overlay` funnel metrics and samples.

    This endpoint is intended for intraday / post-close operational measurement
    of the market overlay branch: did it generate decisions, did those decisions
    create orders, and what were the recent concrete samples.
    """
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    summary_row = await db.fetchrow(
        """
        WITH overlay_decisions AS (
            SELECT
                td.trade_decision_id,
                td.decision_type,
                td.symbol,
                td.market,
                td.side,
                td.rationale_summary,
                td.created_at,
                COALESCE(td.decision_json->>'inclusion_reason', '') AS inclusion_reason
            FROM trading.trade_decisions td
            WHERE td.created_at >= $1
              AND LOWER(COALESCE(td.source_type, '')) = 'market_overlay'
        ),
        latest_orders AS (
            SELECT DISTINCT ON (o.trade_decision_id)
                o.trade_decision_id,
                o.order_request_id,
                LOWER(COALESCE(o.status::text, '')) AS order_status,
                o.created_at AS order_created_at
            FROM trading.order_requests o
            JOIN overlay_decisions od
              ON od.trade_decision_id = o.trade_decision_id
            ORDER BY o.trade_decision_id, o.created_at DESC, o.order_request_id DESC
        )
        SELECT
            (SELECT COUNT(*)::int FROM overlay_decisions) AS decision_count,
            (SELECT COUNT(*)::int FROM latest_orders) AS order_count
        """,
        since,
    )

    decision_type_rows = await db.fetch(
        """
        SELECT
            LOWER(COALESCE(td.decision_type::text, 'unknown')) AS decision_type,
            COUNT(*)::int AS decision_count
        FROM trading.trade_decisions td
        WHERE td.created_at >= $1
          AND LOWER(COALESCE(td.source_type, '')) = 'market_overlay'
        GROUP BY LOWER(COALESCE(td.decision_type::text, 'unknown'))
        ORDER BY decision_count DESC, decision_type ASC
        """,
        since,
    )
    order_status_rows = await db.fetch(
        """
        WITH latest_orders AS (
            SELECT DISTINCT ON (o.trade_decision_id)
                o.trade_decision_id,
                LOWER(COALESCE(o.status::text, 'unknown')) AS order_status
            FROM trading.order_requests o
            JOIN trading.trade_decisions td
              ON td.trade_decision_id = o.trade_decision_id
            WHERE o.created_at >= $1
              AND LOWER(COALESCE(td.source_type, '')) = 'market_overlay'
            ORDER BY o.trade_decision_id, o.created_at DESC, o.order_request_id DESC
        )
        SELECT
            order_status,
            COUNT(*)::int AS order_count
        FROM latest_orders
        GROUP BY order_status
        ORDER BY order_count DESC, order_status ASC
        """,
        since,
    )
    sample_rows = await db.fetch(
        """
        WITH latest_orders AS (
            SELECT DISTINCT ON (o.trade_decision_id)
                o.trade_decision_id,
                o.order_request_id,
                LOWER(COALESCE(o.status::text, '')) AS order_status,
                o.created_at AS order_created_at
            FROM trading.order_requests o
            ORDER BY o.trade_decision_id, o.created_at DESC, o.order_request_id DESC
        )
        SELECT
            td.trade_decision_id,
            td.symbol,
            td.market,
            LOWER(COALESCE(td.decision_type::text, '')) AS decision_type,
            LOWER(COALESCE(td.side::text, '')) AS side,
            COALESCE(td.decision_json->>'inclusion_reason', '') AS inclusion_reason,
            td.rationale_summary,
            td.created_at,
            lo.order_request_id,
            lo.order_status,
            lo.order_created_at
        FROM trading.trade_decisions td
        LEFT JOIN latest_orders lo
          ON lo.trade_decision_id = td.trade_decision_id
        WHERE td.created_at >= $1
          AND LOWER(COALESCE(td.source_type, '')) = 'market_overlay'
        ORDER BY td.created_at DESC, td.trade_decision_id DESC
        LIMIT $2
        """,
        since,
        sample_limit,
    )

    decision_count = int((summary_row or {}).get("decision_count") or 0)
    order_count = int((summary_row or {}).get("order_count") or 0)
    return MarketOverlayFunnelResponse(
        lookback_days=lookback_days,
        sample_limit=sample_limit,
        decision_count=decision_count,
        order_count=order_count,
        order_conversion_rate=(
            float(order_count) / float(decision_count) if decision_count else 0.0
        ),
        decision_type_counts={
            str(row["decision_type"]): int(row["decision_count"] or 0)
            for row in decision_type_rows
        },
        order_status_counts={
            str(row["order_status"]): int(row["order_count"] or 0)
            for row in order_status_rows
        },
        recent_items=[
            MarketOverlayFunnelItem(
                trade_decision_id=row["trade_decision_id"],
                symbol=row["symbol"],
                market=row["market"],
                decision_type=row["decision_type"] or None,
                side=row["side"] or None,
                inclusion_reason=row["inclusion_reason"] or None,
                rationale_summary=row["rationale_summary"],
                created_at=row["created_at"],
                order_request_id=row["order_request_id"],
                order_status=row["order_status"] or None,
                order_created_at=row["order_created_at"],
            )
            for row in sample_rows
        ],
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
