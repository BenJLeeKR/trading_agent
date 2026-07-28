"""FastAPI dependency injection — provides ``RepositoryContainer`` to routes.

In-memory mode: returns ``app.state.repos`` (singleton, existing behaviour).
Postgres mode: creates request-scoped ``TransactionManager`` + repos per request.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import Depends, HTTPException, Request

from agent_trading.api.schemas import SchedulerHealth
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.db.connection import (
    DatabaseConfig,
    close_pool,
    create_pool,
    get_pool,
    health_check,
)
from agent_trading.db.transaction import TransactionManager
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.realtime_quote_broadcaster import QuoteBroadcaster
from agent_trading.services.realtime_quote_source import (
    InstrumentInfo,
    RealtimeQuoteSource,
)


async def get_repos(request: Request) -> AsyncIterator[RepositoryContainer]:
    """Request-scoped dependency that yields a ``RepositoryContainer``.

    In ``in_memory`` mode, returns the pre-built repos from ``app.state``.
    In ``postgres`` mode, opens a new ``TransactionManager``, builds
    Postgres repos, yields them, then closes the transaction on teardown.
    Postgres repos are tx‑bound — every Postgres repository accesses
    ``self._tx.connection``, so a fresh transaction is required per request.

    Usage (unchanged)::

        @router.get("/orders")
        async def list_orders(
            repos: RepositoryContainer = Depends(get_repos),
        ) -> ...:
    """
    runtime_mode: str = getattr(request.app.state, "runtime_mode", "in_memory")

    if runtime_mode == "postgres":
        from agent_trading.repositories.postgres.bootstrap import (
            build_postgres_repositories,
        )

        tx = TransactionManager()
        await tx.__aenter__()
        try:
            repos = build_postgres_repositories(tx)
            yield repos
        finally:
            await tx.__aexit__(None, None, None)
    else:
        # In-memory: yield the pre‑built singleton repos from app state.
        yield request.app.state.repos


async def start_postgres_api_pool() -> DatabaseConfig:
    """API lifespan에서 사용하는 Postgres pool을 생성하고 설정을 반환한다."""
    db_config = DatabaseConfig()
    await create_pool(db_config)
    return db_config


async def close_postgres_api_pool() -> None:
    """API lifespan에서 생성한 Postgres pool을 닫는다."""
    await close_pool()


async def lookup_instrument_info_from_postgres(symbol: str) -> InstrumentInfo | None:
    """구독 시점의 1회성 종목 메타데이터 조회를 API DB 경계 안에서 수행한다."""
    from agent_trading.repositories.postgres.instruments import (
        PostgresInstrumentRepository,
    )

    async with TransactionManager() as tx:
        entity = await PostgresInstrumentRepository(tx).get_by_symbol_any_market(symbol)

    if entity is None:
        return None
    market = (
        entity.market_segment
        if entity.market_segment in {"KOSPI", "KOSDAQ"}
        else "UNKNOWN"
    )
    return InstrumentInfo(symbol=entity.symbol, name=entity.name, market=market)


async def get_db(request: Request):
    """Yield an ``asyncpg.Connection`` from the Postgres pool.

    In ``in_memory`` mode the runtime mode check is skipped and this
    dependency raises ``RuntimeError`` so that callers know the DB is
    unavailable — session routes are Postgres-only.

    .. important::

       ``get_db`` yields a raw **Connection**, not a Pool.  Routes must
       **not** call ``db.acquire()`` — use ``db`` directly::

           @router.get("/market-sessions/latest")
           async def latest(db=Depends(get_db)):
               row = await db.fetchrow(...)   # ✓ correct

           # WRONG — db is already a Connection
           # async with db.acquire() as conn:  # AttributeError!
    """
    runtime_mode: str = getattr(request.app.state, "runtime_mode", "in_memory")
    if runtime_mode != "postgres":
        raise RuntimeError(
            "get_db requires API_RUNTIME_MODE=postgres. "
            "Market-session endpoints are not available in in_memory mode."
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def check_database_health() -> bool:
    """Return Postgres connectivity status for lightweight API health probes."""
    return await health_check()


async def get_scheduler_health(database_status: str) -> SchedulerHealth | None:
    """Return latest scheduler freshness from the active Postgres pool."""
    if database_status != "connected":
        return None
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT last_heartbeat_at, checked_at, is_trading_day, market_phase "
                "FROM trading.market_sessions ORDER BY updated_at DESC LIMIT 1"
            )

        if row is None:
            return SchedulerHealth()

        last_heartbeat = row["last_heartbeat_at"]
        checked_at = row["checked_at"]
        is_trading_day = row["is_trading_day"]
        market_phase = row["market_phase"]
        now = datetime.now(timezone.utc)

        healthy: bool | None = None
        if market_phase in ("after_hours", "idle"):
            healthy = True
        elif is_trading_day and last_heartbeat and (now - last_heartbeat).total_seconds() < 120:
            healthy = True
        elif is_trading_day:
            healthy = False
        elif not is_trading_day and checked_at and (now - checked_at).total_seconds() < 86400:
            healthy = True
        elif not is_trading_day:
            healthy = False

        return SchedulerHealth(
            last_heartbeat_at=last_heartbeat,
            is_trading_day=is_trading_day,
            checked_at=checked_at,
            phase=market_phase,
            healthy=healthy,
        )
    except Exception:
        return None


async def get_order_manager(
    repos: RepositoryContainer = Depends(get_repos),
) -> AsyncIterator[OrderManager]:
    """Request-scoped ``OrderManager`` for write operations.

    Builds a fresh ``OrderManager`` per request, wired with a
    ``ReconciliationService`` for reconciliation post-processing.
    The manager is yielded and discarded after the response — it is
    stateless from the DB perspective (all state lives in ``repos``).
    """
    from agent_trading.services.reconciliation_service import ReconciliationService

    reconciliation_service = ReconciliationService(repos=repos)
    om = OrderManager(
        repos=repos,
        reconciliation_service=reconciliation_service,
        budget_manager=None,
    )
    yield om


def get_kis_client(request: Request) -> KISRestClient | None:
    """Extract the ``KISRestClient`` from the broker adapter stored on app state.

    Returns ``None`` when no broker adapter is configured (graceful fallback).
    The caller should handle ``None`` by falling back to cached data.

    Usage::

        kis_client = get_kis_client(request)
        if kis_client is not None:
            records = await kis_client.inquire_daily_ccld(...)
    """
    broker_adapter: object | None = getattr(request.app.state, "broker_adapter", None)
    if broker_adapter is None:
        return None
    return getattr(broker_adapter, "rest_client", None)


def get_realtime_quote_source(request: Request) -> RealtimeQuoteSource:
    """Return the app-wide ``RealtimeQuoteSource`` singleton.

    Phase 1: ``app.state.realtime_quote_source`` is an ``InMemoryMockQuoteSource``
    (set in ``create_app``'s ``lifespan``) — no KIS WebSocket connection.
    Phase 2 will replace it with a KIS-backed implementation of the same
    ``RealtimeQuoteSource`` protocol without changing this function or the
    routes that depend on it.
    """
    source: RealtimeQuoteSource | None = getattr(
        request.app.state, "realtime_quote_source", None
    )
    if source is None:
        raise HTTPException(status_code=503, detail="Realtime quote source not configured")
    return source


def get_realtime_quote_broadcaster(request: Request) -> QuoteBroadcaster:
    """Return the app-wide ``QuoteBroadcaster`` singleton (Phase 4 push relay).

    ``app.state.realtime_quote_broadcaster`` is created once in ``create_app``'s
    ``lifespan`` and wraps whichever ``realtime_quote_source`` is active
    (mock or KIS-backed) — see ``realtime_quote_broadcaster.py``.
    """
    broadcaster: QuoteBroadcaster | None = getattr(
        request.app.state, "realtime_quote_broadcaster", None
    )
    if broadcaster is None:
        raise HTTPException(status_code=503, detail="Realtime quote broadcaster not configured")
    return broadcaster
