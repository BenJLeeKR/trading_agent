"""Tests for market session API routes.

``GET /market-sessions/latest`` — most recent session row.
``GET /market-sessions/events/recent`` — recent session events.

These endpoints require ``API_RUNTIME_MODE=postgres`` and read directly
from the ``market_sessions`` / ``session_events`` tables via the
``get_db`` dependency.

``get_db`` yields a raw ``asyncpg.Connection`` (not a Pool), so the mock
override returns a connection mock directly (no ``acquire()`` wrapper).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.api.deps import get_db


@pytest.fixture
def _mock_get_db():
    """Override ``get_db`` with a mock ``asyncpg.Connection``.

    ``get_db`` yields a raw connection, so the override simply yields the
    mock connection directly (no ``acquire()`` wrapper).

    Returns ``(override, mock_conn)`` so tests can configure
    ``mock_conn.fetchrow`` / ``mock_conn.fetch`` return values before
    hitting the endpoint.
    """
    mock_conn = AsyncMock()

    async def _override():
        yield mock_conn  # yields Connection directly, matching get_db

    return _override, mock_conn


def test_get_latest_session_no_data(_mock_get_db):
    """``GET /market-sessions/latest`` when no sessions exist."""
    override, mock_conn = _mock_get_db
    mock_conn.fetchrow.return_value = None  # no row

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get("/market-sessions/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "status": "no_data",
        "data": None,
        "healthy": False,
        "stale_seconds": None,
    }
    sql = mock_conn.fetchrow.await_args.args[0]
    assert "FROM market_sessions ms" in sql
    assert "odr.run_date = ms.run_date" in sql
    assert "COALESCE(ms.last_heartbeat_at, ms.checked_at, ms.updated_at)" in sql

    app.dependency_overrides.clear()


def test_get_operations_day_by_date_found(_mock_get_db):
    """``GET /market-sessions/operations-day/by-date/{run_date}`` returns stored row."""
    override, mock_conn = _mock_get_db
    now = datetime.now(timezone.utc)
    mock_conn.fetchrow.return_value = {
        "operations_day_run_id": 7,
        "run_date": now.date(),
        "scheduler_status": "intraday",
        "is_trading_day": True,
        "session_source": "combined",
        "market_phase": "OPEN",
        "pre_market_done": True,
        "end_of_day_done": False,
        "after_hours_mode": False,
        "recovery_batch_done": False,
        "submit_count": 2,
        "held_position_sell_submit_count": 1,
        "cycles": 88,
        "last_phase_change_at": now,
        "last_heartbeat_at": now,
        "created_at": now,
        "updated_at": now,
        "summary_json": {"decision_loop": {"name": "decision_submit_gate", "ok": True}},
    }

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get(f"/market-sessions/operations-day/by-date/{now.date().isoformat()}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["data"]["scheduler_status"] == "intraday"
    assert data["data"]["summary_json"]["decision_loop"]["name"] == "decision_submit_gate"

    app.dependency_overrides.clear()


def test_get_operations_day_by_date_no_data(_mock_get_db):
    """Specific operations-day run_date missing → ``no_data``."""
    override, mock_conn = _mock_get_db
    mock_conn.fetchrow.return_value = None

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get("/market-sessions/operations-day/by-date/2026-06-03")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "no_data",
        "data": None,
    }

    app.dependency_overrides.clear()


def test_get_operations_day_history_with_date_filters(_mock_get_db):
    """History endpoint returns operations_day_runs rows and passes filters."""
    override, mock_conn = _mock_get_db
    now = datetime.now(timezone.utc)
    mock_conn.fetch.return_value = [
        {
            "operations_day_run_id": 8,
            "run_date": now.date(),
            "scheduler_status": "intraday",
            "is_trading_day": True,
            "session_source": "combined",
            "market_phase": "OPEN",
            "pre_market_done": True,
            "end_of_day_done": False,
            "after_hours_mode": False,
            "recovery_batch_done": False,
            "submit_count": 2,
            "held_position_sell_submit_count": 1,
            "cycles": 88,
            "last_phase_change_at": now,
            "last_heartbeat_at": now,
            "created_at": now,
            "updated_at": now,
            "summary_json": {"ok_count": 5},
        },
        {
            "operations_day_run_id": 7,
            "run_date": (now - timedelta(days=1)).date(),
            "scheduler_status": "after_hours",
            "is_trading_day": True,
            "session_source": "combined",
            "market_phase": "CLOSE",
            "pre_market_done": True,
            "end_of_day_done": True,
            "after_hours_mode": True,
            "recovery_batch_done": True,
            "submit_count": 1,
            "held_position_sell_submit_count": 0,
            "cycles": 120,
            "last_phase_change_at": now - timedelta(days=1),
            "last_heartbeat_at": now - timedelta(days=1),
            "created_at": now - timedelta(days=1),
            "updated_at": now - timedelta(days=1),
            "summary_json": {"ok_count": 9},
        },
    ]

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get(
            f"/market-sessions/operations-day/history?date_from={(now - timedelta(days=1)).date().isoformat()}"
            f"&date_to={now.date().isoformat()}&limit=5"
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert len(data["data"]) == 2
    assert data["data"][0]["run_date"] == now.date().isoformat()
    assert data["data"][1]["run_date"] == (now - timedelta(days=1)).date().isoformat()

    fetch_call = mock_conn.fetch.await_args
    assert fetch_call.args[1] == (now - timedelta(days=1)).date()
    assert fetch_call.args[2] == now.date()
    assert fetch_call.args[3] == 5

    app.dependency_overrides.clear()


def test_get_session_by_date_found(_mock_get_db):
    """``GET /market-sessions/by-date/{run_date}`` returns the stored row."""
    override, mock_conn = _mock_get_db
    now = datetime.now(timezone.utc)
    mock_conn.fetchrow.return_value = {
        "id": 11,
        "run_date": now.date(),
        "is_trading_day": False,
        "opnd_yn": "N",
        "bzdy_yn": "N",
        "tr_day_yn": "N",
        "market_phase": None,
        "raw_opnd_yn": "N",
        "raw_mkop_cls_code": None,
        "raw_antc_mkop_cls_code": None,
        "source": "kis_holiday_api",
        "reason_code": "KIS_HOLIDAY_CLOSED",
        "reason": "임시공휴일",
        "operations_day_scheduler_status": "after_hours",
        "operations_day_summary_json": {
            "next_trading_day_readiness": {"overall_status": "READY"},
            "intraday_validation": {"overall_status": "WARN"},
        },
        "last_heartbeat_at": None,
        "checked_at": now,
        "created_at": now,
        "updated_at": now,
    }

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get(f"/market-sessions/by-date/{now.date().isoformat()}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["data"]["source"] == "kis_holiday_api"
    assert data["data"]["reason_code"] == "KIS_HOLIDAY_CLOSED"
    assert data["data"]["reason"] == "임시공휴일"
    assert data["data"]["operations_day_scheduler_status"] == "after_hours"
    assert data["data"]["next_trading_day_readiness"]["overall_status"] == "READY"
    assert data["data"]["intraday_validation"]["overall_status"] == "WARN"
    sql = mock_conn.fetchrow.await_args.args[0]
    assert "FROM market_sessions ms" in sql
    assert "WHERE ms.run_date = $1" in sql

    app.dependency_overrides.clear()


def test_get_session_by_date_no_data(_mock_get_db):
    """Specific run_date missing → ``no_data``."""
    override, mock_conn = _mock_get_db
    mock_conn.fetchrow.return_value = None

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get("/market-sessions/by-date/2026-06-03")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "no_data",
        "data": None,
    }

    app.dependency_overrides.clear()


def test_get_session_history_with_date_filters(_mock_get_db):
    """History endpoint returns rows and passes date filters to SQL fetch."""
    override, mock_conn = _mock_get_db
    now = datetime.now(timezone.utc)
    mock_conn.fetch.return_value = [
        {
            "id": 21,
            "run_date": now.date(),
            "is_trading_day": True,
            "opnd_yn": "Y",
            "bzdy_yn": "Y",
            "tr_day_yn": "Y",
            "market_phase": "OPEN",
            "raw_opnd_yn": "Y",
            "raw_mkop_cls_code": "2",
            "raw_antc_mkop_cls_code": "2",
            "source": "combined",
            "reason_code": "COMBINED_TRADING",
            "reason": "정상 장중",
            "operations_day_scheduler_status": "intraday",
            "operations_day_summary_json": {
                "next_trading_day_readiness": {"overall_status": "READY"},
            },
            "last_heartbeat_at": now,
            "checked_at": now,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": 20,
            "run_date": (now - timedelta(days=1)).date(),
            "is_trading_day": False,
            "opnd_yn": "N",
            "bzdy_yn": "N",
            "tr_day_yn": "N",
            "market_phase": None,
            "raw_opnd_yn": "N",
            "raw_mkop_cls_code": None,
            "raw_antc_mkop_cls_code": None,
            "source": "kis_holiday_api",
            "reason_code": "KIS_HOLIDAY_CLOSED",
            "reason": "휴장",
            "operations_day_scheduler_status": "after_hours",
            "operations_day_summary_json": {
                "next_trading_day_readiness": {"overall_status": "READY"},
                "intraday_validation": {"overall_status": "READY"},
            },
            "last_heartbeat_at": None,
            "checked_at": now - timedelta(days=1),
            "created_at": now - timedelta(days=1),
            "updated_at": now - timedelta(days=1),
        },
    ]

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get(
            f"/market-sessions/history?date_from={(now - timedelta(days=1)).date().isoformat()}"
            f"&date_to={now.date().isoformat()}&limit=5"
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert len(data["data"]) == 2
    assert data["data"][0]["run_date"] == now.date().isoformat()
    assert data["data"][1]["run_date"] == (now - timedelta(days=1)).date().isoformat()
    assert data["data"][0]["next_trading_day_readiness"]["overall_status"] == "READY"
    assert data["data"][1]["intraday_validation"]["overall_status"] == "READY"

    fetch_call = mock_conn.fetch.await_args
    sql = fetch_call.args[0]
    assert "FROM market_sessions ms" in sql
    assert "WHERE ($1::date IS NULL OR ms.run_date >= $1::date)" in sql
    assert "ORDER BY ms.run_date DESC" in sql
    assert fetch_call.args[1] == (now - timedelta(days=1)).date()
    assert fetch_call.args[2] == now.date()
    assert fetch_call.args[3] == 5

    app.dependency_overrides.clear()


def test_get_latest_session_healthy(_mock_get_db):
    """Seed a session row and verify healthy response (healthy=True)."""
    override, mock_conn = _mock_get_db
    now = datetime.now(timezone.utc)
    mock_conn.fetchrow.return_value = {
        "id": 1,
        "run_date": now.date(),
        "is_trading_day": True,
        "opnd_yn": "Y",
        "bzdy_yn": "Y",
        "tr_day_yn": "Y",
        "market_phase": "OPEN",
        "raw_opnd_yn": None,
        "raw_mkop_cls_code": None,
        "raw_antc_mkop_cls_code": None,
        "source": "kis_live",
        "reason_code": "KIS_HOLIDAY_TRADING_DAY",
        "reason": None,
        "operations_day_scheduler_status": "intraday",
        "operations_day_summary_json": {
            "intraday_validation": {"overall_status": "BLOCKED"},
        },
        "last_heartbeat_at": now,
        "checked_at": now,
        "created_at": now,
        "updated_at": now,
    }

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get("/market-sessions/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["data"] is not None
    assert data["data"]["market_phase"] == "OPEN"
    assert data["data"]["intraday_validation"]["overall_status"] == "BLOCKED"
    assert data["healthy"] is True
    assert data["stale_seconds"] is not None
    assert data["stale_seconds"] < 5  # just fetched, should be near-zero

    app.dependency_overrides.clear()


def test_get_latest_session_stale(_mock_get_db):
    """Seed a stale session row (checked_at > 120s ago) → healthy=False, stale_seconds>0."""
    override, mock_conn = _mock_get_db
    old = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=300)
    mock_conn.fetchrow.return_value = {
        "id": 2,
        "run_date": old.date(),
        "is_trading_day": True,
        "opnd_yn": "N",
        "bzdy_yn": "Y",
        "tr_day_yn": "Y",
        "market_phase": "PRE_MARKET",
        "raw_opnd_yn": None,
        "raw_mkop_cls_code": None,
        "raw_antc_mkop_cls_code": None,
        "source": "kis_live",
        "reason": None,
        "last_heartbeat_at": old,
        "checked_at": datetime.now(timezone.utc),
        "created_at": old,
        "updated_at": old,
    }

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get("/market-sessions/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["data"] is not None
    assert data["data"]["market_phase"] == "PRE_MARKET"
    assert data["healthy"] is False
    # 300 seconds ago → stale_seconds ≈ 300
    assert data["stale_seconds"] is not None
    assert data["stale_seconds"] >= 300

    app.dependency_overrides.clear()


def test_get_latest_session_trading_day_uses_heartbeat_not_checked_at(_mock_get_db):
    """Trading day status should remain healthy when heartbeat is fresh even if checked_at is old."""
    override, mock_conn = _mock_get_db
    now = datetime.now(timezone.utc).replace(microsecond=0)
    mock_conn.fetchrow.return_value = {
        "id": 3,
        "run_date": now.date(),
        "is_trading_day": True,
        "opnd_yn": "Y",
        "bzdy_yn": "Y",
        "tr_day_yn": "Y",
        "market_phase": "OPEN",
        "raw_opnd_yn": None,
        "raw_mkop_cls_code": None,
        "raw_antc_mkop_cls_code": None,
        "source": "scheduler",
        "reason": None,
        "last_heartbeat_at": now,
        "checked_at": now - timedelta(minutes=20),
        "created_at": now,
        "updated_at": now,
    }

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get("/market-sessions/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["healthy"] is True
    assert data["stale_seconds"] is not None
    assert data["stale_seconds"] < 5

    app.dependency_overrides.clear()


def test_get_latest_operations_day_no_data(_mock_get_db):
    """``GET /market-sessions/operations-day/latest`` when no rows exist."""
    override, mock_conn = _mock_get_db
    mock_conn.fetchrow.return_value = None

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get("/market-sessions/operations-day/latest")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "no_data",
        "data": None,
        "healthy": False,
        "stale_seconds": None,
    }

    app.dependency_overrides.clear()


def test_get_latest_operations_day_healthy(_mock_get_db):
    """최근 heartbeat가 있으면 operations-day 상태는 healthy=True."""
    override, mock_conn = _mock_get_db
    now = datetime.now(timezone.utc)
    mock_conn.fetchrow.return_value = {
        "operations_day_run_id": 7,
        "run_date": now.date(),
        "scheduler_status": "intraday",
        "is_trading_day": True,
        "session_source": "kis_live",
        "market_phase": "OPEN",
        "pre_market_done": True,
        "end_of_day_done": False,
        "after_hours_mode": False,
        "recovery_batch_done": False,
        "submit_count": 2,
        "held_position_sell_submit_count": 1,
        "cycles": 14,
        "last_phase_change_at": now,
        "last_heartbeat_at": now,
        "created_at": now,
        "updated_at": now,
        "summary_json": '{"command_results_count": 4}',
    }

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get("/market-sessions/operations-day/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["healthy"] is True
    assert data["stale_seconds"] is not None
    assert data["stale_seconds"] < 5
    assert data["data"]["scheduler_status"] == "intraday"
    assert data["data"]["submit_count"] == 2
    assert data["data"]["summary_json"] == {"command_results_count": 4}

    app.dependency_overrides.clear()


def test_get_latest_operations_day_stale_uses_updated_at_when_heartbeat_missing(_mock_get_db):
    """heartbeat가 없으면 updated_at 기준으로 stale 계산."""
    override, mock_conn = _mock_get_db
    old = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=300)
    mock_conn.fetchrow.return_value = {
        "operations_day_run_id": 8,
        "run_date": old.date(),
        "scheduler_status": "pre_market",
        "is_trading_day": True,
        "session_source": "scheduler",
        "market_phase": None,
        "pre_market_done": False,
        "end_of_day_done": False,
        "after_hours_mode": False,
        "recovery_batch_done": False,
        "submit_count": 0,
        "held_position_sell_submit_count": 0,
        "cycles": 0,
        "last_phase_change_at": None,
        "last_heartbeat_at": None,
        "created_at": old,
        "updated_at": old,
        "summary_json": {},
    }

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get("/market-sessions/operations-day/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["healthy"] is False
    assert data["stale_seconds"] is not None
    assert data["stale_seconds"] >= 300
    assert data["data"]["scheduler_status"] == "pre_market"

    app.dependency_overrides.clear()


def test_get_recent_events_not_empty(_mock_get_db):
    """Seed events and verify response."""
    override, mock_conn = _mock_get_db
    now = datetime.now(timezone.utc)
    mock_conn.fetch.return_value = [
        {
            "id": 10,
            "market_session_id": 1,
            "previous_phase": "PRE_MARKET",
            "new_phase": "OPEN",
            "trigger_source": "combined_phase_provider",
            "metadata": None,
            "occurred_at": now,
            "created_at": now,
        }
    ]

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get("/market-sessions/events/recent?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert len(data["data"]) >= 1
    assert data["data"][0]["new_phase"] == "OPEN"
    assert data["data"][0]["previous_phase"] == "PRE_MARKET"

    app.dependency_overrides.clear()


def test_get_recent_events_with_run_date_filter(_mock_get_db):
    """``run_date`` filter should be passed through to the session_events query."""
    override, mock_conn = _mock_get_db
    now = datetime.now(timezone.utc)
    mock_conn.fetch.return_value = [
        {
            "id": 12,
            "market_session_id": 5,
            "previous_phase": "OPEN",
            "new_phase": "AFTER_HOURS",
            "trigger_source": "scheduler_phase_monitor",
            "metadata": {"reason_code": "COMBINED_TRADING"},
            "occurred_at": now,
            "created_at": now,
        }
    ]

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get("/market-sessions/events/recent?run_date=2026-06-03&limit=7")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert len(data["data"]) == 1
    assert data["data"][0]["new_phase"] == "AFTER_HOURS"

    fetch_call = mock_conn.fetch.await_args
    assert fetch_call.args[1].isoformat() == "2026-06-03"
    assert fetch_call.args[2] == 7

    app.dependency_overrides.clear()


def test_get_recent_events_empty(_mock_get_db):
    """No events → empty events list."""
    override, mock_conn = _mock_get_db
    mock_conn.fetch.return_value = []

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_db] = override

    with TestClient(app) as client:
        resp = client.get("/market-sessions/events/recent?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"status": "ok", "data": []}

    app.dependency_overrides.clear()
