"""Tests for ``InMemoryInstrumentIndexMembershipRepository.get_latest_effective_from``
(UNIV-4 staleness 감시 — in-memory 경로)."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from agent_trading.repositories.bootstrap import build_in_memory_repositories


@pytest.mark.asyncio
async def test_get_latest_effective_from_returns_none_when_empty() -> None:
    repos = build_in_memory_repositories()

    latest = await repos.instrument_index_memberships.get_latest_effective_from()

    assert latest is None


@pytest.mark.asyncio
async def test_get_latest_effective_from_returns_max_active_date() -> None:
    repos = build_in_memory_repositories()
    instrument_id = uuid4()

    await repos.instrument_index_memberships.sync_current_memberships(
        instrument_id,
        ["KOSPI200"],
        effective_from=date(2026, 6, 19),
    )
    await repos.instrument_index_memberships.sync_current_memberships(
        instrument_id,
        ["KOSPI200", "KOSPI100"],
        effective_from=date(2026, 6, 27),
    )

    latest = await repos.instrument_index_memberships.get_latest_effective_from()

    assert latest == date(2026, 6, 27)
