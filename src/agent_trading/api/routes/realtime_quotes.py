"""``/realtime-quotes/*`` — KIS 실시간 현재가 조회 화면 API.

Read-only from the trading system's perspective: these endpoints never touch
``OrderManager``, ``BrokerAdapter`` (trading account), or the decision
pipeline. They only manage subscriptions against a ``RealtimeQuoteSource``
(``app.state.realtime_quote_source``) and return the latest quote snapshot.

``app.state.realtime_quote_source`` is either an ``InMemoryMockQuoteSource``
(no ``KIS_REALTIME_QUOTE_APP_KEY``/``_APP_SECRET`` configured — the default)
or a ``KisRealtimeQuoteSource`` (Step 3, a completely separate KIS Live
account/appkey from the trading account and ``KIS_LIVE_INFO_*``, connected
only inside the ``api`` process — see ``kis_realtime_quote_source.py`` and
``api/app.py`` lifespan wiring). Both implement the same
``RealtimeQuoteSource`` protocol, so **this route module needs no changes**
regardless of which one is active.

See ``plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md``
and ``plans/[DESIGN]_kis_realtime_quote_operations_screen_plan.md`` (Step 1-3).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_realtime_quote_source
from agent_trading.api.schemas import (
    RealtimeQuoteBootstrapResponse,
    RealtimeQuoteConnectionInfo,
    RealtimeQuoteDailyPriceItem,
    RealtimeQuoteDailyPriceResponse,
    RealtimeQuoteLevel,
    RealtimeQuoteSnapshotResponse,
    RealtimeQuoteSnapshotView,
    RealtimeQuoteSubscribeRequest,
    RealtimeQuoteSubscriptionsResponse,
    RealtimeQuoteSubscriptionView,
    RealtimeQuoteTradeTickView,
    RealtimeQuoteUnsubscribeRequest,
)
from agent_trading.services.realtime_quote_source import (
    InvalidSymbolError,
    MAX_DAILY_PRICE_HISTORY,
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
        recent_trades=[
            RealtimeQuoteTradeTickView(
                trade_time=t.trade_time,
                price=t.price,
                change=t.change,
                change_rate=t.change_rate,
                volume=t.volume,
            )
            for t in quote.recent_trades
        ],
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
    """Idempotently add subscriptions for one or more symbols.

    Re-subscribing to an already-subscribed symbol is a no-op (Phase 1
    single-screen semantics — see ``realtime_quote_source.py`` module
    docstring). It does not accumulate a reference count.
    """
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
    """Remove subscriptions for one or more symbols.

    A single call per symbol fully unsubscribes it — there is no reference
    count to decrement.
    """
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


@router.get("/daily-price", response_model=RealtimeQuoteDailyPriceResponse)
async def get_daily_price(
    symbol: str = Query(..., description="6자리 종목코드, 예: '005930'"),
    source: RealtimeQuoteSource = Depends(get_realtime_quote_source),
) -> RealtimeQuoteDailyPriceResponse:
    """일자별 시세('일별' 탭) — 구독 여부와 무관한 REST 1회 조회.

    WS 구독/등록 budget을 소비하지 않는다(순수 REST 조회).
    """
    try:
        bars = await source.get_daily_price(symbol, count=MAX_DAILY_PRICE_HISTORY)
    except InvalidSymbolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RealtimeQuoteDailyPriceResponse(
        symbol=symbol.strip(),
        bars=[
            RealtimeQuoteDailyPriceItem(
                date=b.date,
                close=b.close,
                change=b.change,
                change_rate=b.change_rate,
                volume=b.volume,
            )
            for b in bars
        ],
        generated_at=datetime.now(timezone.utc),
    )
