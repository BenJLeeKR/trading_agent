"""Market session status API routes.

``GET /market-sessions/latest`` — most recent market_sessions row (heartbeat).
``GET /market-sessions/events/recent`` — recent session events (phase transitions).

These endpoints require ``API_RUNTIME_MODE=postgres`` because they read
directly from the ``market_sessions`` and ``session_events`` tables.

``get_db`` yields a raw ``asyncpg.Connection`` (not a Pool), so routes
must **not** call ``db.acquire()`` — use ``db`` directly.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from agent_trading.api.deps import get_db
from agent_trading.api.schemas import (
    MarketSessionSummary,
    MarketSessionDetailResponse,
    MarketSessionHistoryResponse,
    OperationsDayDetailResponse,
    OperationsDayHistoryResponse,
    OperationsDayRunSummary,
    OperationsDayStatusResponse,
    SchedulerStatusResponse,
    SessionEventSummary,
    SessionEventsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market-sessions", tags=["market-sessions"])

STALE_THRESHOLD_SECONDS = 120  # scheduler heartbeat threshold


def _coerce_summary_json(row_dict: dict[str, object]) -> dict[str, object]:
    """Normalize ``summary_json`` to a dictionary for API responses."""
    raw = row_dict.get("summary_json")
    if isinstance(raw, dict):
        return row_dict
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        row_dict["summary_json"] = parsed if isinstance(parsed, dict) else {}
        return row_dict
    row_dict["summary_json"] = {}
    return row_dict


def _coerce_json_field(row_dict: dict[str, object], field_name: str) -> dict[str, object]:
    """Normalize an arbitrary JSON field to a dictionary for API responses."""
    raw = row_dict.get(field_name)
    if isinstance(raw, dict):
        return row_dict
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        row_dict[field_name] = parsed if isinstance(parsed, dict) else {}
        return row_dict
    row_dict[field_name] = {}
    return row_dict


def _coerce_market_session_row(row_dict: dict[str, object]) -> dict[str, object]:
    """Normalize linked operations-day JSON and expose validation summaries."""
    row_dict = _coerce_json_field(row_dict, "reason_metadata")
    row_dict = _coerce_json_field(row_dict, "operations_day_summary_json")
    ops_summary = row_dict.get("operations_day_summary_json")
    if isinstance(ops_summary, dict):
        row_dict["next_trading_day_readiness"] = ops_summary.get("next_trading_day_readiness")
        row_dict["intraday_validation"] = ops_summary.get("intraday_validation")
    else:
        row_dict["next_trading_day_readiness"] = None
        row_dict["intraday_validation"] = None
    return row_dict


@router.get("/by-date/{run_date}", response_model=MarketSessionDetailResponse)
async def get_session_by_date(run_date: date, db=Depends(get_db)):
    """Return the stored ``market_sessions`` row for a specific KST date."""
    row = await db.fetchrow(
        """
        SELECT ms.id, ms.run_date, ms.is_trading_day, ms.opnd_yn, ms.bzdy_yn, ms.tr_day_yn,
               ms.market_phase, ms.raw_opnd_yn, ms.raw_mkop_cls_code, ms.raw_antc_mkop_cls_code,
               ms.source, ms.reason_code, ms.reason, ms.reason_metadata,
               odr.scheduler_status AS operations_day_scheduler_status,
               odr.summary_json AS operations_day_summary_json,
               ms.last_heartbeat_at, ms.checked_at, ms.created_at, ms.updated_at
        FROM market_sessions ms
        LEFT JOIN trading.operations_day_runs odr ON odr.run_date = ms.run_date
        WHERE ms.run_date = $1
        """,
        run_date,
    )
    if not row:
        return MarketSessionDetailResponse(status="no_data", data=None)
    return MarketSessionDetailResponse(
        status="ok",
        data=MarketSessionSummary(**_coerce_market_session_row(dict(row))),
    )


@router.get("/history", response_model=MarketSessionHistoryResponse)
async def get_session_history(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(30, ge=1, le=365),
    db=Depends(get_db),
):
    """Return stored ``market_sessions`` rows ordered by ``run_date DESC``."""
    rows = await db.fetch(
        """
        SELECT ms.id, ms.run_date, ms.is_trading_day, ms.opnd_yn, ms.bzdy_yn, ms.tr_day_yn,
               ms.market_phase, ms.raw_opnd_yn, ms.raw_mkop_cls_code, ms.raw_antc_mkop_cls_code,
               ms.source, ms.reason_code, ms.reason, ms.reason_metadata,
               odr.scheduler_status AS operations_day_scheduler_status,
               odr.summary_json AS operations_day_summary_json,
               ms.last_heartbeat_at, ms.checked_at, ms.created_at, ms.updated_at
        FROM market_sessions ms
        LEFT JOIN trading.operations_day_runs odr ON odr.run_date = ms.run_date
        WHERE ($1::date IS NULL OR ms.run_date >= $1::date)
          AND ($2::date IS NULL OR ms.run_date <= $2::date)
        ORDER BY ms.run_date DESC
        LIMIT $3
        """,
        date_from,
        date_to,
        limit,
    )
    return MarketSessionHistoryResponse(
        status="ok",
        data=[MarketSessionSummary(**_coerce_market_session_row(dict(r))) for r in rows],
    )


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
        SELECT ms.id, ms.run_date, ms.is_trading_day, ms.opnd_yn, ms.bzdy_yn, ms.tr_day_yn,
               ms.market_phase, ms.raw_opnd_yn, ms.raw_mkop_cls_code, ms.raw_antc_mkop_cls_code,
               ms.source, ms.reason_code, ms.reason, ms.reason_metadata,
               odr.scheduler_status AS operations_day_scheduler_status,
               odr.summary_json AS operations_day_summary_json,
               ms.last_heartbeat_at, ms.checked_at, ms.created_at, ms.updated_at
        FROM market_sessions ms
        LEFT JOIN trading.operations_day_runs odr ON odr.run_date = ms.run_date
        ORDER BY COALESCE(ms.last_heartbeat_at, ms.checked_at, ms.updated_at) DESC NULLS LAST
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
        data=MarketSessionSummary(**_coerce_market_session_row(dict(row))),
        healthy=not stale,
        stale_seconds=stale_seconds,
    )


@router.get("/operations-day/latest", response_model=OperationsDayStatusResponse)
async def get_latest_operations_day_run(db=Depends(get_db)):
    """Return the most recent ``operations_day_runs`` row.

    Uses ``last_heartbeat_at`` when present, else ``updated_at`` to derive
    freshness. This provides a scheduler-centric status view that is separate
    from the lower-level ``market_sessions`` source data.
    """
    row = await db.fetchrow(
        """
        SELECT operations_day_run_id, run_date, scheduler_status, is_trading_day,
               session_source, market_phase, pre_market_done, end_of_day_done,
               after_hours_mode, recovery_batch_done, submit_count,
               held_position_sell_submit_count, cycles, last_phase_change_at,
               last_heartbeat_at, created_at, updated_at, summary_json
        FROM trading.operations_day_runs
        ORDER BY COALESCE(last_heartbeat_at, updated_at, created_at) DESC NULLS LAST
        LIMIT 1
        """
    )
    if not row:
        return OperationsDayStatusResponse(
            status="no_data",
            data=None,
            healthy=False,
            stale_seconds=None,
        )

    now = datetime.now(timezone.utc)
    freshness_ts = row["last_heartbeat_at"] or row["updated_at"] or row["created_at"]
    stale_seconds = int((now - freshness_ts).total_seconds()) if freshness_ts else None
    stale = freshness_ts is None or stale_seconds >= STALE_THRESHOLD_SECONDS

    return OperationsDayStatusResponse(
        status="ok",
        data=OperationsDayRunSummary(**_coerce_summary_json(dict(row))),
        healthy=not stale,
        stale_seconds=stale_seconds,
    )


@router.get("/operations-day/by-date/{run_date}", response_model=OperationsDayDetailResponse)
async def get_operations_day_run_by_date(run_date: date, db=Depends(get_db)):
    """Return the stored ``operations_day_runs`` row for a specific KST date."""
    row = await db.fetchrow(
        """
        SELECT operations_day_run_id, run_date, scheduler_status, is_trading_day,
               session_source, market_phase, pre_market_done, end_of_day_done,
               after_hours_mode, recovery_batch_done, submit_count,
               held_position_sell_submit_count, cycles, last_phase_change_at,
               last_heartbeat_at, created_at, updated_at, summary_json
        FROM trading.operations_day_runs
        WHERE run_date = $1
        ORDER BY COALESCE(last_heartbeat_at, updated_at, created_at) DESC NULLS LAST
        LIMIT 1
        """,
        run_date,
    )
    if not row:
        return OperationsDayDetailResponse(status="no_data", data=None)
    return OperationsDayDetailResponse(
        status="ok",
        data=OperationsDayRunSummary(**_coerce_summary_json(dict(row))),
    )


@router.get("/operations-day/history", response_model=OperationsDayHistoryResponse)
async def get_operations_day_run_history(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(30, ge=1, le=365),
    db=Depends(get_db),
):
    """Return stored ``operations_day_runs`` rows ordered by ``run_date DESC``."""
    rows = await db.fetch(
        """
        SELECT operations_day_run_id, run_date, scheduler_status, is_trading_day,
               session_source, market_phase, pre_market_done, end_of_day_done,
               after_hours_mode, recovery_batch_done, submit_count,
               held_position_sell_submit_count, cycles, last_phase_change_at,
               last_heartbeat_at, created_at, updated_at, summary_json
        FROM trading.operations_day_runs
        WHERE ($1::date IS NULL OR run_date >= $1::date)
          AND ($2::date IS NULL OR run_date <= $2::date)
        ORDER BY run_date DESC
        LIMIT $3
        """,
        date_from,
        date_to,
        limit,
    )
    return OperationsDayHistoryResponse(
        status="ok",
        data=[OperationsDayRunSummary(**_coerce_summary_json(dict(r))) for r in rows],
    )


@router.get("/events/recent", response_model=SessionEventsResponse)
async def get_recent_events(
    run_date: date | None = Query(None),
    limit: int = Query(5, ge=1, le=50),
    db=Depends(get_db),
):
    """Return recent session events (phase transitions).

    ``run_date``를 지정하면 해당 날짜의 ``market_sessions`` row에 연결된
    이벤트만 반환한다. Always returns 200 — empty event set yields ``data=[]``.
    """
    rows = await db.fetch(
        """
        SELECT se.id, se.market_session_id, se.previous_phase, se.new_phase,
               se.trigger_source, se.metadata, se.occurred_at, se.created_at
        FROM session_events se
        JOIN market_sessions ms ON ms.id = se.market_session_id
        WHERE ($1::date IS NULL OR ms.run_date = $1::date)
        ORDER BY se.occurred_at DESC
        LIMIT $2
        """,
        run_date,
        limit,
    )
    return SessionEventsResponse(
        status="ok",
        data=[SessionEventSummary(**dict(r)) for r in rows],
    )
