"""Tests for ``GET /external-events/recent`` endpoint.

Uses in-memory repositories with pre-seeded data.  The ``get_repos``
dependency is overridden so that the route reads from the seeded repos.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.api.deps import get_repos
from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.repositories.bootstrap import build_in_memory_repositories


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T0 = datetime(2026, 5, 17, 8, 0, 0, tzinfo=timezone.utc)       # 8h ago (within 72h)
T1 = datetime(2026, 5, 17, 6, 0, 0, tzinfo=timezone.utc)       # 10h ago
T2 = datetime(2026, 5, 17, 4, 0, 0, tzinfo=timezone.utc)       # 12h ago
T3 = datetime(2026, 5, 15, 1, 0, 0, tzinfo=timezone.utc)       # 58h ago (within 72h)
T_STALE = datetime(2026, 5, 13, 0, 0, 0, tzinfo=timezone.utc)  # 107h ago (> 72h)


def make_event(
    *,
    event_type: str = "Y|정기공시",
    source_name: str = "opendart",
    symbol: str = "005930",
    published_at: datetime = T0,
    headline: str | None = "Test headline",
    body_summary: str | None = "Test body",
    source_reliability_tier: str = "T1",
) -> ExternalEventEntity:
    return ExternalEventEntity(
        event_id=uuid4(),
        event_type=event_type,
        source_name=source_name,
        source_reliability_tier=source_reliability_tier,
        source_event_id=None,
        issuer_code=None,
        symbol=symbol,
        market="KRX",
        published_at=published_at,
        ingested_at=None,
        effective_at=None,
        severity="medium",
        direction="neutral",
        headline=headline,
        body_summary=body_summary,
        raw_payload_uri=None,
        dedup_key_hash=None,
        supersedes_event_id=None,
        metadata={},
    )


# ===================================================================
# Tests
# ===================================================================


def test_get_recent_events_empty():
    """No symbol match → empty data list."""
    repos = build_in_memory_repositories()
    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_repos] = lambda: repos

    with TestClient(app) as client:
        resp = client.get("/external-events/recent?symbol=999999")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["data"] == []

    app.dependency_overrides.clear()


def test_get_recent_events_with_data():
    """Seed T1 + T3 events → both returned."""
    repos = build_in_memory_repositories()

    t1_event = make_event(
        event_type="Y|정기공시",
        source_name="opendart",
        symbol="005930",
        published_at=T0,
        headline="삼성전자 영업이익 14조",
        source_reliability_tier="T1",
    )
    t3_event = make_event(
        event_type="N|seeded_news",
        source_name="naver_news",
        symbol="005930",
        published_at=T1,
        headline="HBM4 개발 속도",
        source_reliability_tier="T3",
    )

    # Add events via the async add method
    import asyncio
    asyncio.run(repos.external_events.add(t1_event))
    asyncio.run(repos.external_events.add(t3_event))

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_repos] = lambda: repos

    with TestClient(app) as client:
        resp = client.get("/external-events/recent?symbol=005930")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["data"]) == 2

    # Most recent first (T0 > T1)
    assert body["data"][0]["headline"] == "삼성전자 영업이익 14조"
    assert body["data"][0]["source_reliability_tier"] == "T1"
    assert body["data"][0]["source_name"] == "opendart"

    assert body["data"][1]["headline"] == "HBM4 개발 속도"
    assert body["data"][1]["source_reliability_tier"] == "T3"
    assert body["data"][1]["source_name"] == "naver_news"

    app.dependency_overrides.clear()


def test_get_recent_events_limit():
    """Respects limit parameter — only N events returned."""
    repos = build_in_memory_repositories()

    # Add 7 events (all within 72h)
    import asyncio
    for i in range(7):
        ev = make_event(
            symbol="005930",
            published_at=T0 - timedelta(hours=i),
            headline=f"Event {i+1}",
        )
        asyncio.run(repos.external_events.add(ev))

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_repos] = lambda: repos

    # Default limit = 5
    with TestClient(app) as client:
        resp = client.get("/external-events/recent?symbol=005930")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 5

    # Explicit limit = 3
    with TestClient(app) as client:
        resp = client.get("/external-events/recent?symbol=005930&limit=3")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 3

    app.dependency_overrides.clear()


def test_get_recent_events_include_non_listed():
    """include_non_listed=true (default) returns both listed and non-listed events."""
    repos = build_in_memory_repositories()

    listed = make_event(
        event_type="Y|정기공시",
        source_name="opendart",
        symbol="005930",
        published_at=T0,
        source_reliability_tier="T1",
    )
    non_listed = make_event(
        event_type="E|비상장",
        source_name="some_source",
        symbol="005930",
        published_at=T1,
        source_reliability_tier="T3",
    )

    import asyncio
    asyncio.run(repos.external_events.add(listed))
    asyncio.run(repos.external_events.add(non_listed))

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_repos] = lambda: repos

    with TestClient(app) as client:
        resp = client.get("/external-events/recent?symbol=005930&include_non_listed=true")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2

    # include_non_listed=false → only listed (Y| prefix) events
    with TestClient(app) as client:
        resp = client.get("/external-events/recent?symbol=005930&include_non_listed=false")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["source_reliability_tier"] == "T1"

    app.dependency_overrides.clear()


def test_get_recent_events_cutoff():
    """Events older than since_hours are excluded."""
    repos = build_in_memory_repositories()

    recent = make_event(
        symbol="005930",
        published_at=T0,  # 8h ago — within 72h
    )
    stale = make_event(
        symbol="005930",
        published_at=T_STALE,  # 107h ago — outside 72h
    )

    import asyncio
    asyncio.run(repos.external_events.add(recent))
    asyncio.run(repos.external_events.add(stale))

    app = create_app(auth_enabled=False)
    app.dependency_overrides[get_repos] = lambda: repos

    with TestClient(app) as client:
        resp = client.get("/external-events/recent?symbol=005930&since_hours=72")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    # Compare by parsing to datetime — avoid Z vs +00:00 mismatch
    published = datetime.fromisoformat(body["data"][0]["published_at"])
    assert published == T0

    app.dependency_overrides.clear()


def test_get_recent_events_missing_symbol():
    """symbol query param is required → 422."""
    app = create_app(auth_enabled=False)

    with TestClient(app) as client:
        resp = client.get("/external-events/recent")

    assert resp.status_code == 422
    app.dependency_overrides.clear()
