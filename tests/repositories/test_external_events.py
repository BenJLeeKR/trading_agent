"""Tests for ``ExternalEventRepository`` implementations.

Covers both ``InMemoryExternalEventRepository`` (unit) and
``PostgresExternalEventRepository`` (integration).

Test matrix
-----------
InMemory (8):
  1. add + get — round-trip
  2. get — nonexistent returns None
  3. find_by_dedup_key — hit
  4. find_by_dedup_key — miss
  5. list_by_symbol — filters by symbol + since
  6. list_by_type — filters by event_type + since
  7. list_by_symbol — include_seeded_news=True includes seeded_news
  8. list_by_symbol — include_seeded_news=False (default) excludes seeded_news

Postgres (6):
  9. add + get — round-trip
  10. find_by_dedup_key — hit
  11. list_by_symbol — filters by symbol + since
  12. list_by_type — filters by event_type + since
  13. list_by_symbol — include_seeded_news=True includes seeded_news
  14. list_by_symbol — include_seeded_news=False (default) excludes seeded_news
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.repositories.bootstrap import build_in_memory_repositories


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

T0 = datetime(2025, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
T2 = datetime(2025, 6, 1, 11, 0, 0, tzinfo=timezone.utc)


def make_event(
    *,
    event_type: str = "disclosure",
    source_name: str = "test_source",
    symbol: str | None = "005930",
    market: str | None = "KRX",
    published_at: datetime = T0,
    dedup_key_hash: str | None = None,
    severity: str = "medium",
    direction: str = "neutral",
) -> ExternalEventEntity:
    return ExternalEventEntity(
        event_id=uuid4(),
        event_type=event_type,
        source_name=source_name,
        published_at=published_at,
        source_reliability_tier="T3",
        source_event_id=None,
        issuer_code=None,
        symbol=symbol,
        market=market,
        ingested_at=None,
        effective_at=None,
        severity=severity,
        direction=direction,
        headline=None,
        body_summary=None,
        raw_payload_uri=None,
        dedup_key_hash=dedup_key_hash,
        supersedes_event_id=None,
        metadata={},
    )


# ===================================================================
# InMemory tests
# ===================================================================


@pytest.fixture
def repo():
    return build_in_memory_repositories().external_events


@pytest.mark.asyncio
async def test_inmemory_add_and_get(repo) -> None:
    """1. add + get — round-trip."""
    event = make_event()
    added = await repo.add(event)
    assert added == event

    fetched = await repo.get(event.event_id)
    assert fetched == event


@pytest.mark.asyncio
async def test_inmemory_get_nonexistent(repo) -> None:
    """2. get — nonexistent returns None."""
    result = await repo.get(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_inmemory_find_by_dedup_key_hit(repo) -> None:
    """3. find_by_dedup_key — hit."""
    event = make_event(dedup_key_hash="dedup-001")
    await repo.add(event)

    found = await repo.find_by_dedup_key("dedup-001")
    assert found == event


@pytest.mark.asyncio
async def test_inmemory_find_by_dedup_key_miss(repo) -> None:
    """4. find_by_dedup_key — miss."""
    result = await repo.find_by_dedup_key("nonexistent-hash")
    assert result is None


@pytest.mark.asyncio
async def test_inmemory_list_by_symbol(repo) -> None:
    """5. list_by_symbol — filters by symbol + since."""
    e1 = make_event(symbol="005930", published_at=T0)
    e2 = make_event(symbol="005930", published_at=T1)
    e3 = make_event(symbol="000660", published_at=T2)  # different symbol

    await repo.add(e1)
    await repo.add(e2)
    await repo.add(e3)

    # Should return e2 (T1) and e1 (T0) — both match symbol, ordered DESC
    results = await repo.list_by_symbol("005930", since=T0 - timedelta(hours=1))
    assert len(results) == 2
    assert results[0] == e2  # newer first
    assert results[1] == e1

    # Filter by since=T1 → only e2
    results = await repo.list_by_symbol("005930", since=T1)
    assert len(results) == 1
    assert results[0] == e2


@pytest.mark.asyncio
async def test_inmemory_list_by_symbol_excludes_seeded_news_by_default(repo) -> None:
    """7. list_by_symbol — include_seeded_news=False (default) excludes seeded_news."""
    e1 = make_event(symbol="005930", event_type="Y|분기보고서", published_at=T0)
    e2 = make_event(symbol="005930", event_type="seeded_news", published_at=T1)

    await repo.add(e1)
    await repo.add(e2)

    # Default (include_seeded_news=False) → only listed event
    results = await repo.list_by_symbol("005930", since=T0 - timedelta(hours=1))
    assert len(results) == 1
    assert results[0].event_id == e1.event_id

    # Explicit False → same result
    results = await repo.list_by_symbol(
        "005930", since=T0 - timedelta(hours=1), include_seeded_news=False,
    )
    assert len(results) == 1
    assert results[0].event_id == e1.event_id


@pytest.mark.asyncio
async def test_inmemory_list_by_symbol_includes_seeded_news(repo) -> None:
    """8. list_by_symbol — include_seeded_news=True includes seeded_news alongside listed."""
    e1 = make_event(symbol="005930", event_type="Y|분기보고서", published_at=T0)
    e2 = make_event(symbol="005930", event_type="seeded_news", published_at=T1)

    await repo.add(e1)
    await repo.add(e2)

    # include_seeded_news=True → both listed + seeded_news
    results = await repo.list_by_symbol(
        "005930", since=T0 - timedelta(hours=1), include_seeded_news=True,
    )
    assert len(results) == 2
    # e2 (T1) is newer → first
    assert results[0].event_id == e2.event_id
    assert results[1].event_id == e1.event_id


@pytest.mark.asyncio
async def test_inmemory_list_by_type(repo) -> None:
    """6. list_by_type — filters by event_type + since."""
    e1 = make_event(event_type="disclosure", published_at=T0)
    e2 = make_event(event_type="disclosure", published_at=T1)
    e3 = make_event(event_type="news", published_at=T2)

    await repo.add(e1)
    await repo.add(e2)
    await repo.add(e3)

    results = await repo.list_by_type("disclosure", since=T0 - timedelta(hours=1))
    assert len(results) == 2
    assert results[0] == e2
    assert results[1] == e1

    results = await repo.list_by_type("news", since=T0)
    assert len(results) == 1
    assert results[0] == e3


# ===================================================================
# Postgres integration tests
# ===================================================================


@pytest.mark.asyncio
async def test_postgres_add_and_get(postgres_repos) -> None:
    """7. add + get — round-trip."""
    repo = postgres_repos.external_events
    event = make_event()
    added = await repo.add(event)
    assert added.event_id == event.event_id

    fetched = await repo.get(event.event_id)
    assert fetched is not None
    assert fetched.event_id == event.event_id
    assert fetched.event_type == event.event_type
    assert fetched.source_name == event.source_name
    assert fetched.symbol == event.symbol
    assert fetched.dedup_key_hash == event.dedup_key_hash


@pytest.mark.asyncio
async def test_postgres_find_by_dedup_key(postgres_repos) -> None:
    """8. find_by_dedup_key — hit."""
    repo = postgres_repos.external_events
    event = make_event(dedup_key_hash="pg-dedup-001")
    await repo.add(event)

    found = await repo.find_by_dedup_key("pg-dedup-001")
    assert found is not None
    assert found.event_id == event.event_id


@pytest.mark.asyncio
async def test_postgres_list_by_symbol(postgres_repos) -> None:
    """9. list_by_symbol — filters by symbol + since."""
    repo = postgres_repos.external_events
    e1 = make_event(symbol="005930", published_at=T0)
    e2 = make_event(symbol="005930", published_at=T1)
    e3 = make_event(symbol="000660", published_at=T2)

    await repo.add(e1)
    await repo.add(e2)
    await repo.add(e3)

    results = await repo.list_by_symbol("005930", since=T0 - timedelta(hours=1))
    assert len(results) == 2
    assert results[0].event_id == e2.event_id
    assert results[1].event_id == e1.event_id


@pytest.mark.asyncio
async def test_postgres_list_by_type(postgres_repos) -> None:
    """10. list_by_type — filters by event_type + since."""
    repo = postgres_repos.external_events
    e1 = make_event(event_type="disclosure", published_at=T0)
    e2 = make_event(event_type="disclosure", published_at=T1)
    e3 = make_event(event_type="news", published_at=T2)

    await repo.add(e1)
    await repo.add(e2)
    await repo.add(e3)

    results = await repo.list_by_type("disclosure", since=T0 - timedelta(hours=1))
    assert len(results) == 2
    assert results[0].event_id == e2.event_id
    assert results[1].event_id == e1.event_id


@pytest.mark.asyncio
async def test_postgres_list_by_symbol_excludes_seeded_news_by_default(postgres_repos) -> None:
    """13. list_by_symbol — include_seeded_news=False (default) excludes seeded_news."""
    repo = postgres_repos.external_events
    e1 = make_event(symbol="005930", event_type="Y|분기보고서", published_at=T0)
    e2 = make_event(symbol="005930", event_type="seeded_news", published_at=T1)

    await repo.add(e1)
    await repo.add(e2)

    # Default → only listed event
    results = await repo.list_by_symbol("005930", since=T0 - timedelta(hours=1))
    assert len(results) == 1
    assert results[0].event_id == e1.event_id

    # Explicit False → same result
    results = await repo.list_by_symbol(
        "005930", since=T0 - timedelta(hours=1), include_seeded_news=False,
    )
    assert len(results) == 1
    assert results[0].event_id == e1.event_id


@pytest.mark.asyncio
async def test_postgres_list_by_symbol_includes_seeded_news(postgres_repos) -> None:
    """14. list_by_symbol — include_seeded_news=True includes seeded_news alongside listed."""
    repo = postgres_repos.external_events
    e1 = make_event(symbol="005930", event_type="Y|분기보고서", published_at=T0)
    e2 = make_event(symbol="005930", event_type="seeded_news", published_at=T1)

    await repo.add(e1)
    await repo.add(e2)

    # include_seeded_news=True → both listed + seeded_news
    results = await repo.list_by_symbol(
        "005930", since=T0 - timedelta(hours=1), include_seeded_news=True,
    )
    assert len(results) == 2
    # e2 (T1) is newer → first
    assert results[0].event_id == e2.event_id
    assert results[1].event_id == e1.event_id
