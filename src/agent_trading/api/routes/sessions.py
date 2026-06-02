"""Market session status API routes.

``GET /market-sessions/latest`` — most recent market_sessions row (heartbeat).
``GET /market-sessions/events/recent`` — recent session events (phase transitions).

These endpoints require ``API_RUNTIME_MODE=postgres`` because they read
directly from the ``market_sessions`` and ``session_events`` tables.

``get_db`` yields a raw ``asyncpg.Connection`` (not a Pool), so routes
must **not** call ``db.acquire()`` — use ``db`` directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from agent_trading.api.deps import get_db
from agent_trading.api.schemas import (
    MarketSessionSummary,
    SchedulerStatusResponse,
    SessionEventSummary,
    SessionEventsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market-sessions", tags=["market-sessions"])

STALE_THRESHOLD_SECONDS = 120  # scheduler heartbeat threshold


@router.get("/latest", response_model=SchedulerStatusResponse)
async def get_latest_session(db=Depends(get_db)):
    """Return the most recent market_sessions row (today or latest available).

    ``stale_seconds`` is derived from ``last_heartbeat_at`` on trading days
    (actual scheduler liveness) and from ``checked_at`` on non-trading days.
    Always returns 200 — no 500 even when the DB table is empty or the
    heartbeat is old.
    """
    row = await db.fetchrow(
        """
        SELECT id, run_date, is_trading_day, opnd_yn, bzdy_yn, tr_day_yn,
               market_phase, raw_opnd_yn, raw_mkop_cls_code, raw_antc_mkop_cls_code,
               source, reason, last_heartbeat_at, checked_at, created_at, updated_at
        FROM market_sessions
        ORDER BY COALESCE(last_heartbeat_at, checked_at, updated_at) DESC NULLS LAST
        LIMIT 1
        """
    )
    if not row:
        return SchedulerStatusResponse(
            status="no_data",
            data=None,
            healthy=False,
            stale_seconds=None,
        )

    now = datetime.now(timezone.utc)
    last_heartbeat = row["last_heartbeat_at"]
    checked = row["checked_at"]
    is_trading_day = bool(row["is_trading_day"])

    freshness_ts = last_heartbeat if is_trading_day else checked
    stale_seconds = int((now - freshness_ts).total_seconds()) if freshness_ts else None
    stale = freshness_ts is None or stale_seconds >= STALE_THRESHOLD_SECONDS

    return SchedulerStatusResponse(
        status="ok",
        data=MarketSessionSummary(**dict(row)),
        healthy=not stale,
        stale_seconds=stale_seconds,
    )


@router.get("/events/recent", response_model=SessionEventsResponse)
async def get_recent_events(
    limit: int = Query(5, ge=1, le=50),
    db=Depends(get_db),
):
    """Return recent session events (phase transitions).

    Always returns 200 — empty event set yields ``data=[]``.
    """
    rows = await db.fetch(
        """
        SELECT se.id, se.market_session_id, se.previous_phase, se.new_phase,
               se.trigger_source, se.metadata, se.occurred_at, se.created_at
        FROM session_events se
        ORDER BY se.occurred_at DESC
        LIMIT $1
        """,
        limit,
    )
    return SessionEventsResponse(
        status="ok",
        data=[SessionEventSummary(**dict(r)) for r in rows],
    )
