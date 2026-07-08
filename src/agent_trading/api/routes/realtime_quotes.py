"""``/realtime-quotes/*`` — KIS 실시간 현재가 조회 화면 API (Phase 1: mock-backed).

Read-only from the trading system's perspective: these endpoints never touch
``OrderManager``, ``BrokerAdapter`` (trading account), or the decision
pipeline. They only manage subscriptions against a ``RealtimeQuoteSource``
(``app.state.realtime_quote_source``) and return the latest quote snapshot.

Phase 1 wires an ``InMemoryMockQuoteSource`` — no KIS WebSocket connection.
Phase 2 will swap in a KIS-backed implementation of the same
``RealtimeQuoteSource`` protocol; these routes will not need to change.

See ``plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md``
and ``plans/[DESIGN]_kis_realtime_quote_operations_screen_plan.md`` (Step 1/2).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_realtime_quote_source
from agent_trading.api.schemas import (
    RealtimeQuoteBootstrapResponse,
    RealtimeQuoteConnectionInfo,
    RealtimeQuoteLevel,
    RealtimeQuoteSnapshotResponse,
    RealtimeQuoteSnapshotView,
    RealtimeQuoteSubscribeRequest,
    RealtimeQuoteSubscriptionsResponse,
    RealtimeQuoteSubscriptionView,
    RealtimeQuoteUnsubscribeRequest,
)
from agent_trading.services.realtime_quote_source import (
    InvalidSymbolError,
    QuoteSnapshot,
    RealtimeQuoteSource,
    SubscriptionLimitExceededError,
)

router = APIRouter(prefix="/realtime-quotes", tags=["realtime-quotes"])


def _connection_info(source: RealtimeQuoteSource) -> RealtimeQuoteConnectionInfo:
    max_reg = source.max_registrations
    per_symbol = source.registrations_per_symbol
    return RealtimeQuoteConnectionInfo(
        connection_state=source.connection_state().value,
        environment=source.environment,
        data_source=source.environment,  # Phase 1: "mock" for both
        registered_count=source.registered_count(),
        max_registrations=max_reg,
        registrations_per_symbol=per_symbol,
        symbol_capacity=max_reg // per_symbol if per_symbol else max_reg,
    )


def _subscription_views(source: RealtimeQuoteSource) -> list[RealtimeQuoteSubscriptionView]:
    views = []
    for symbol in source.list_subscriptions():
        info = source.instrument_info(symbol)
        views.append(
            RealtimeQuoteSubscriptionView(symbol=info.symbol, market=info.market, name=info.name)
        )
    return views


def _subscriptions_response(source: RealtimeQuoteSource) -> RealtimeQuoteSubscriptionsResponse:
    return RealtimeQuoteSubscriptionsResponse(
        connection=_connection_info(source),
        subscriptions=_subscription_views(source),
        generated_at=datetime.now(timezone.utc),
    )


def _to_snapshot_view(quote: QuoteSnapshot) -> RealtimeQuoteSnapshotView:
    return RealtimeQuoteSnapshotView(
        symbol=quote.symbol,
        market=quote.market,
        name=quote.name,
        last_price=quote.last_price,
        prev_close=quote.prev_close,
        change=quote.change,
        change_rate=quote.change_rate,
        change_sign=quote.change_sign,
        open_price=quote.open_price,
        high_price=quote.high_price,
        low_price=quote.low_price,
        upper_limit=quote.upper_limit,
        lower_limit=quote.lower_limit,
        accumulated_volume=quote.accumulated_volume,
        accumulated_value=quote.accumulated_value,
        per=quote.per,
        pbr=quote.pbr,
        eps=quote.eps,
        bps=quote.bps,
        ask_levels=[RealtimeQuoteLevel(price=lvl.price, quantity=lvl.quantity) for lvl in quote.ask_levels],
        bid_levels=[RealtimeQuoteLevel(price=lvl.price, quantity=lvl.quantity) for lvl in quote.bid_levels],
        total_ask_quantity=quote.total_ask_quantity,
        total_bid_quantity=quote.total_bid_quantity,
        trade_time=quote.trade_time,
        hour_class=quote.hour_class,
        trading_halted=quote.trading_halted,
        data_source=quote.data_source,
        updated_at=quote.updated_at,
    )


@router.get("/bootstrap", response_model=RealtimeQuoteBootstrapResponse)
async def bootstrap(
    source: RealtimeQuoteSource = Depends(get_realtime_quote_source),
) -> RealtimeQuoteBootstrapResponse:
    """Initial screen-load payload: connection status + current subscriptions."""
    return RealtimeQuoteBootstrapResponse(
        connection=_connection_info(source),
        subscriptions=_subscription_views(source),
        generated_at=datetime.now(timezone.utc),
    )


@router.post(
    "/subscriptions",
    response_model=RealtimeQuoteSubscriptionsResponse,
    status_code=201,
)
async def add_subscriptions(
    body: RealtimeQuoteSubscribeRequest,
    source: RealtimeQuoteSource = Depends(get_realtime_quote_source),
) -> RealtimeQuoteSubscriptionsResponse:
    """Add (reference-count) subscriptions for one or more symbols."""
    for symbol in body.symbols:
        try:
            await source.subscribe(symbol)
        except InvalidSymbolError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SubscriptionLimitExceededError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _subscriptions_response(source)


@router.delete("/subscriptions", response_model=RealtimeQuoteSubscriptionsResponse)
async def remove_subscriptions(
    body: RealtimeQuoteUnsubscribeRequest,
    source: RealtimeQuoteSource = Depends(get_realtime_quote_source),
) -> RealtimeQuoteSubscriptionsResponse:
    """Remove (reference-count) subscriptions for one or more symbols."""
    for symbol in body.symbols:
        await source.unsubscribe(symbol)
    return _subscriptions_response(source)


@router.get("/subscriptions", response_model=RealtimeQuoteSubscriptionsResponse)
async def list_subscriptions(
    source: RealtimeQuoteSource = Depends(get_realtime_quote_source),
) -> RealtimeQuoteSubscriptionsResponse:
    """Current subscription list + connection/capacity status."""
    return _subscriptions_response(source)


@router.get("/snapshot", response_model=RealtimeQuoteSnapshotResponse)
async def get_snapshot(
    symbols: str = Query(..., description="Comma-separated symbol codes, e.g. '005930,000660'"),
    source: RealtimeQuoteSource = Depends(get_realtime_quote_source),
) -> RealtimeQuoteSnapshotResponse:
    """Latest quote snapshot for the given (already-subscribed) symbols.

    Symbols not currently subscribed are silently omitted from ``quotes``.
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=422, detail="symbols query parameter must not be empty")

    raw_snapshots = source.get_snapshots(symbol_list)
    quotes = {symbol: _to_snapshot_view(quote) for symbol, quote in raw_snapshots.items()}
    return RealtimeQuoteSnapshotResponse(quotes=quotes, generated_at=datetime.now(timezone.utc))
