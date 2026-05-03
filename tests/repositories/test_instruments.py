from __future__ import annotations

from uuid import uuid4

import pytest

from agent_trading.domain.entities import InstrumentEntity
from agent_trading.domain.enums import AssetClass


class TestInstrumentRepositoryContract:
    """Verify that InstrumentRepository implementations satisfy the contract."""

    @pytest.mark.asyncio
    async def test_add_and_get(self, in_memory_repos, sample_instrument) -> None:
        created = await in_memory_repos.instruments.add(sample_instrument)
        assert created.instrument_id == sample_instrument.instrument_id

        fetched = await in_memory_repos.instruments.get(sample_instrument.instrument_id)
        assert fetched is not None
        assert fetched.symbol == "005930"
        assert fetched.name == "Samsung Electronics"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, in_memory_repos) -> None:
        result = await in_memory_repos.instruments.get(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_symbol(self, in_memory_repos, sample_instrument) -> None:
        await in_memory_repos.instruments.add(sample_instrument)

        fetched = await in_memory_repos.instruments.get_by_symbol(
            "005930", "KRX"
        )
        assert fetched is not None
        assert fetched.instrument_id == sample_instrument.instrument_id

    @pytest.mark.asyncio
    async def test_get_by_symbol_nonexistent_returns_none(
        self, in_memory_repos
    ) -> None:
        result = await in_memory_repos.instruments.get_by_symbol(
            "NONEXISTENT", "KRX"
        )
        assert result is None
