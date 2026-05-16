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
        "reason": None,
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
        "checked_at": old,
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
