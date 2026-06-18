from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from agent_trading.domain.entities import (
    ConfigVersionEntity,
    DecisionContextEntity,
    StrategyEntity,
)
from agent_trading.domain.enums import Environment
from agent_trading.repositories.filters import DecisionContextQuery


@pytest.fixture
async def seeded_decision_context_deps(
    postgres_repos, sample_client, sample_account
) -> dict:
    """Seed the FK dependencies needed for decision_context tests."""
    from agent_trading.domain.entities import BrokerAccountEntity

    broker_account = BrokerAccountEntity(
        broker_account_id=sample_account.broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref-dc",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****00dc",
    )
    await postgres_repos.broker_accounts.add(broker_account)
    await postgres_repos.clients.add(sample_client)
    await postgres_repos.accounts.add(sample_account)

    strategy = StrategyEntity(
        strategy_id=uuid4(),
        client_id=sample_client.client_id,
        strategy_code="DC_TEST_STRAT",
        name="DC Test Strategy",
        asset_class="KR_STOCK",
        status="active",
    )
    await postgres_repos.strategies.add(strategy)

    config_version = ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=sample_client.client_id,
        environment=Environment.PAPER,
        version_tag="dc-v1.0",
        config_json={"max_position_size": "0.1"},
        checksum="dc-abc123",
    )
    await postgres_repos.config_versions.add(config_version)

    return {
        "strategy": strategy,
        "config_version": config_version,
    }


@pytest.fixture
def sample_decision_context(
    sample_account, seeded_decision_context_deps
) -> DecisionContextEntity:
    deps = seeded_decision_context_deps
    return DecisionContextEntity(
        decision_context_id=uuid4(),
        account_id=sample_account.account_id,
        strategy_id=deps["strategy"].strategy_id,
        config_version_id=deps["config_version"].config_version_id,
        market_timestamp=datetime.now(timezone.utc),
        correlation_id="dc-test-corr-001",
    )


@pytest.mark.asyncio
async def test_add_and_get(
    postgres_repos, sample_decision_context
) -> None:
    added = await postgres_repos.decision_contexts.add(sample_decision_context)
    assert added.decision_context_id == sample_decision_context.decision_context_id
    assert added.correlation_id == "dc-test-corr-001"

    fetched = await postgres_repos.decision_contexts.get(
        sample_decision_context.decision_context_id
    )
    assert fetched is not None
    assert fetched.decision_context_id == sample_decision_context.decision_context_id
    assert fetched.account_id == sample_decision_context.account_id


@pytest.mark.asyncio
async def test_get_nonexistent(postgres_repos) -> None:
    fetched = await postgres_repos.decision_contexts.get(uuid4())
    assert fetched is None


@pytest.mark.asyncio
async def test_get_by_correlation_id(
    postgres_repos, sample_decision_context
) -> None:
    await postgres_repos.decision_contexts.add(sample_decision_context)

    fetched = await postgres_repos.decision_contexts.get_by_correlation_id(
        "dc-test-corr-001"
    )
    assert fetched is not None
    assert fetched.decision_context_id == sample_decision_context.decision_context_id


@pytest.mark.asyncio
async def test_get_by_correlation_id_nonexistent(postgres_repos) -> None:
    fetched = await postgres_repos.decision_contexts.get_by_correlation_id(
        "nonexistent-corr"
    )
    assert fetched is None


@pytest.mark.asyncio
async def test_list_with_filters(
    postgres_repos, sample_account, seeded_decision_context_deps
) -> None:
    deps = seeded_decision_context_deps
    now = datetime.now(timezone.utc)

    # Create two decision contexts
    dc1 = DecisionContextEntity(
        decision_context_id=uuid4(),
        account_id=sample_account.account_id,
        strategy_id=deps["strategy"].strategy_id,
        config_version_id=deps["config_version"].config_version_id,
        market_timestamp=now - timedelta(hours=2),
        correlation_id="dc-list-corr-001",
    )
    dc2 = DecisionContextEntity(
        decision_context_id=uuid4(),
        account_id=sample_account.account_id,
        strategy_id=deps["strategy"].strategy_id,
        config_version_id=deps["config_version"].config_version_id,
        market_timestamp=now - timedelta(hours=1),
        correlation_id="dc-list-corr-002",
    )
    await postgres_repos.decision_contexts.add(dc1)
    await postgres_repos.decision_contexts.add(dc2)

    # List with account filter
    query = DecisionContextQuery(
        account_id=sample_account.account_id,
        limit=10,
    )
    results = await postgres_repos.decision_contexts.list(query)
    assert len(results) == 2
    # Should be ordered by market_timestamp DESC
    assert results[0].correlation_id == "dc-list-corr-002"
    assert results[1].correlation_id == "dc-list-corr-001"

    # List with time range filter
    query_time = DecisionContextQuery(
        account_id=sample_account.account_id,
        market_timestamp_from=now - timedelta(hours=1, minutes=30),
        market_timestamp_to=now,
        limit=10,
    )
    results_time = await postgres_repos.decision_contexts.list(query_time)
    assert len(results_time) == 1
    assert results_time[0].correlation_id == "dc-list-corr-002"


@pytest.mark.asyncio
async def test_list_empty(postgres_repos) -> None:
    now = datetime.now(timezone.utc)
    query = DecisionContextQuery(
        correlation_id="decision-context-empty-case",
        market_timestamp_from=now + timedelta(days=1),
        limit=10,
    )
    results = await postgres_repos.decision_contexts.list(query)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_attach_signal_feature_snapshot(
    postgres_repos, sample_decision_context
) -> None:
    from agent_trading.domain.entities import InstrumentEntity, SignalFeatureSnapshotEntity
    from decimal import Decimal

    await postgres_repos.decision_contexts.add(sample_decision_context)
    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol=f"T{uuid4().hex[:5].upper()}",
        market_code="KRX",
        asset_class="KR_STOCK",
        currency="KRW",
        name="테스트종목",
    )
    await postgres_repos.instruments.add(instrument)
    snapshot = SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=uuid4(),
        instrument_id=instrument.instrument_id,
        timeframe="1d",
        snapshot_at=datetime.now(timezone.utc),
        feature_set_version="signal_backbone_v1",
        bar_count=80,
        overall_score=Decimal("0.42"),
    )
    await postgres_repos.signal_feature_snapshots.add(snapshot)

    updated = await postgres_repos.decision_contexts.attach_signal_feature_snapshot(
        sample_decision_context.decision_context_id,
        snapshot.signal_feature_snapshot_id,
    )

    assert updated is not None
    assert updated.signal_feature_snapshot_id == snapshot.signal_feature_snapshot_id

    fetched = await postgres_repos.decision_contexts.get(
        sample_decision_context.decision_context_id
    )
    assert fetched is not None
    assert fetched.signal_feature_snapshot_id == snapshot.signal_feature_snapshot_id
