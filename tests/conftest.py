from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from dotenv import load_dotenv

# Auto-load .env from project root so that smoke tests and other test suites
# can read KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT_NO etc. without needing
# a separate ``python -c "load_dotenv(); pytest(...)"`` wrapper.
load_dotenv()

from agent_trading.domain.entities import (
    AccountEntity,
    ClientEntity,
    InstrumentEntity,
    OrderRequestEntity,
)
from agent_trading.domain.enums import (
    AssetClass,
    Environment,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.order_manager import OrderManager


# ---------------------------------------------------------------------------
# Fixtures: shared entities
# ---------------------------------------------------------------------------


@pytest.fixture
def client_id() -> UUID:
    return uuid4()


@pytest.fixture
def account_id() -> UUID:
    return uuid4()


@pytest.fixture
def instrument_id() -> UUID:
    return uuid4()


@pytest.fixture
def sample_client(client_id: UUID) -> ClientEntity:
    return ClientEntity(
        client_id=client_id,
        client_code="TEST001",
        name="Test Client",
        status="active",
        base_currency="KRW",
    )


@pytest.fixture
def sample_account(account_id: UUID, client_id: UUID) -> AccountEntity:
    return AccountEntity(
        account_id=account_id,
        client_id=client_id,
        broker_account_id=uuid4(),
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )


@pytest.fixture
def sample_instrument(instrument_id: UUID) -> InstrumentEntity:
    return InstrumentEntity(
        instrument_id=instrument_id,
        symbol="005930",
        market_code="KRX",
        asset_class=AssetClass.KR_STOCK.value,
        currency="KRW",
        name="Samsung Electronics",
        is_active=True,
    )


@pytest.fixture
def sample_order(
    account_id: UUID,
    instrument_id: UUID,
) -> OrderRequestEntity:
    now = datetime.now(timezone.utc)
    return OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id="CLI-001",
        idempotency_key="idem-001",
        correlation_id="corr-001",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        requested_price=Decimal("50000"),
        requested_quantity=Decimal("10"),
        status=OrderStatus.DRAFT,
        trade_decision_id=None,
        submitted_at=None,
        status_reason_code=None,
        status_reason_message=None,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Fixtures: in-memory repositories + OrderManager
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_repos() -> RepositoryContainer:
    return build_in_memory_repositories()


@pytest.fixture
def order_manager(in_memory_repos: RepositoryContainer) -> OrderManager:
    return OrderManager(repos=in_memory_repos)


# ---------------------------------------------------------------------------
# Fixtures: pre-seeded repositories (in-memory)
# ---------------------------------------------------------------------------


@pytest.fixture
async def seeded_repos(
    in_memory_repos: RepositoryContainer,
    sample_client: ClientEntity,
    sample_account: AccountEntity,
    sample_instrument: InstrumentEntity,
) -> RepositoryContainer:
    """Repositories pre-loaded with a client, account, and instrument."""
    await in_memory_repos.clients.add(sample_client)
    await in_memory_repos.accounts.add(sample_account)
    await in_memory_repos.instruments.add(sample_instrument)
    return in_memory_repos


# ---------------------------------------------------------------------------
# Fixtures: PostgreSQL-backed repositories (integration tests)
# ---------------------------------------------------------------------------
# Principles (per user requirements):
#   1. Migrations are applied before each test session.
#   2. Clean state is guaranteed by rolling back the transaction.
#   3. The ``trading`` schema is used explicitly in all queries.
#   4. Tests are repeatable — no side effects persist between runs.


@pytest.fixture
async def postgres_repos() -> AsyncIterator[RepositoryContainer]:
    """PostgreSQL-backed repositories for integration tests.

    Each test gets a fresh transaction that is automatically rolled
    back when the test finishes — no manual cleanup required.

    Usage::

        async def test_foo(postgres_repos: RepositoryContainer) -> None:
            await postgres_repos.audit_logs.add(...)
            ...

    Migrations are applied automatically on entry.
    The transaction is always rolled back on exit (``force_rollback=True``)
    so that no side effects persist between tests.
    """
    from agent_trading.db.connection import create_pool, close_pool
    from agent_trading.db.migrations.run import run_all_migrations
    from agent_trading.db.transaction import TransactionManager

    await create_pool()
    await run_all_migrations()
    tx = TransactionManager(force_rollback=True)
    await tx.__aenter__()
    try:
        from agent_trading.repositories.postgres.bootstrap import (
            build_postgres_repositories,
        )

        repos = build_postgres_repositories(tx)
        yield repos
    finally:
        await tx.__aexit__(None, None, None)
        await close_pool()


@pytest.fixture
async def seeded_postgres_data(
    postgres_repos: RepositoryContainer,
    sample_client: ClientEntity,
    sample_account: AccountEntity,
    sample_instrument: InstrumentEntity,
) -> RepositoryContainer:
    """PostgreSQL repositories pre-seeded with a client, account, instrument,
    strategy, config_version, and decision_context.

    Use this fixture when your test needs existing FK references
    (e.g., for ``order_state_events``, ``guardrail_evaluations``,
    ``risk_limit_snapshots``).

    Note: ``sample_account.broker_account_id`` references the
    ``broker_accounts`` table, so a matching ``BrokerAccountEntity``
    is also seeded automatically.
    """
    from agent_trading.domain.entities import (
        BrokerAccountEntity,
        ConfigVersionEntity,
        DecisionContextEntity,
        StrategyEntity,
    )
    from agent_trading.domain.enums import Environment

    # Seed broker_account first (FK target for sample_account.broker_account_id)
    broker_account = BrokerAccountEntity(
        broker_account_id=sample_account.broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref-001",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
    )
    await postgres_repos.broker_accounts.add(broker_account)

    await postgres_repos.clients.add(sample_client)
    await postgres_repos.accounts.add(sample_account)
    await postgres_repos.instruments.add(sample_instrument)

    # Seed strategy via PostgresStrategyRepository (Milestone 5)
    strategy = StrategyEntity(
        strategy_id=uuid4(),
        client_id=sample_client.client_id,
        strategy_code="TEST_STRAT",
        name="Test Strategy",
        asset_class="KR_STOCK",
        status="active",
    )
    await postgres_repos.strategies.add(strategy)

    # Seed config_version via PostgresConfigVersionRepository (Milestone 5)
    config_version = ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=sample_client.client_id,
        environment=Environment.PAPER,
        version_tag="v1.0",
        config_json={"max_position_size": "0.1"},
        checksum="abc123",
    )
    await postgres_repos.config_versions.add(config_version)

    # Seed decision_context via PostgresDecisionContextRepository (Milestone 5)
    decision_context = DecisionContextEntity(
        decision_context_id=uuid4(),
        account_id=sample_account.account_id,
        strategy_id=strategy.strategy_id,
        config_version_id=config_version.config_version_id,
        market_timestamp=datetime.now(timezone.utc),
        correlation_id="test-correlation",
    )
    await postgres_repos.decision_contexts.add(decision_context)

    return postgres_repos
