from __future__ import annotations

from uuid import uuid4

import pytest

from agent_trading.domain.entities import StrategyEntity


@pytest.fixture
def sample_strategy(client_id) -> StrategyEntity:
    return StrategyEntity(
        strategy_id=uuid4(),
        client_id=client_id,
        strategy_code="M5_TEST_STRAT",
        name="Milestone 5 Test Strategy",
        asset_class="KR_STOCK",
        status="active",
        description="Test strategy for Milestone 5",
    )


@pytest.mark.asyncio
async def test_add_and_get(seeded_postgres_data, sample_strategy) -> None:
    added = await seeded_postgres_data.strategies.add(sample_strategy)
    assert added.strategy_id == sample_strategy.strategy_id
    assert added.strategy_code == "M5_TEST_STRAT"

    fetched = await seeded_postgres_data.strategies.get(sample_strategy.strategy_id)
    assert fetched is not None
    assert fetched.strategy_id == sample_strategy.strategy_id
    assert fetched.name == "Milestone 5 Test Strategy"
    assert fetched.status == "active"


@pytest.mark.asyncio
async def test_get_nonexistent(seeded_postgres_data) -> None:
    fetched = await seeded_postgres_data.strategies.get(uuid4())
    assert fetched is None


@pytest.mark.asyncio
async def test_get_by_code(seeded_postgres_data, sample_strategy, client_id) -> None:
    await seeded_postgres_data.strategies.add(sample_strategy)

    fetched = await seeded_postgres_data.strategies.get_by_code(
        client_id, "M5_TEST_STRAT"
    )
    assert fetched is not None
    assert fetched.strategy_id == sample_strategy.strategy_id
    assert fetched.strategy_code == "M5_TEST_STRAT"


@pytest.mark.asyncio
async def test_get_by_code_nonexistent(seeded_postgres_data, client_id) -> None:
    fetched = await seeded_postgres_data.strategies.get_by_code(
        client_id, "NONEXISTENT"
    )
    assert fetched is None
