"""Pytest fixtures for the FastAPI inspection API tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.domain.entities import (
    AccountEntity,
    AgentRunEntity,
    AuditLogEntity,
    BrokerOrderEntity,
    CashBalanceSnapshotEntity,
    ClientEntity,
    DecisionContextEntity,
    InstrumentEntity,
    OrderRequestEntity,
    OrderStateEventEntity,
    PositionSnapshotEntity,
    ReconciliationRunEntity,
    TradeDecisionEntity,
)
from agent_trading.domain.enums import (
    DecisionType,
    EntryStyle,
    Environment,
    EventSource,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer


@pytest.fixture
def client_id() -> UUID:
    return uuid4()


@pytest.fixture
def account_id() -> UUID:
    return uuid4()


@pytest.fixture
def broker_account_id() -> UUID:
    return uuid4()


@pytest.fixture
def instrument_id() -> UUID:
    return uuid4()


@pytest.fixture
def strategy_id() -> UUID:
    return uuid4()


@pytest.fixture
def config_version_id() -> UUID:
    return uuid4()


@pytest.fixture
def decision_context_id() -> UUID:
    return uuid4()


@pytest.fixture
def trade_decision_id() -> UUID:
    return uuid4()


@pytest.fixture
def position_snapshot_id() -> UUID:
    return uuid4()


@pytest.fixture
def broker_order_id() -> UUID:
    return uuid4()


@pytest.fixture
def correlation_id() -> str:
    return f"test-correlation-{uuid4()}"


@pytest.fixture
async def seeded_repos(
    client_id: UUID,
    account_id: UUID,
    broker_account_id: UUID,
    instrument_id: UUID,
    strategy_id: UUID,
    config_version_id: UUID,
    decision_context_id: UUID,
    trade_decision_id: UUID,
    position_snapshot_id: UUID,
    broker_order_id: UUID,
    correlation_id: str,
) -> RepositoryContainer:
    """Build in-memory repos and seed with sample data."""
    repos = build_in_memory_repositories()

    # Seed: client
    await repos.clients.add(
        ClientEntity(
            client_id=client_id,
            client_code="API_TEST",
            name="API Test Client",
            status="active",
            base_currency="KRW",
            created_at=datetime.now(timezone.utc),
        )
    )

    # Seed: account
    await repos.accounts.add(
        AccountEntity(
            account_id=account_id,
            client_id=client_id,
            broker_account_id=broker_account_id,
            environment=Environment.PAPER,
            account_alias="API-ACCT-001",
            account_masked="****1234",
            status="active",
            created_at=datetime.now(timezone.utc),
        )
    )

    # Seed: instrument
    await repos.instruments.add(
        InstrumentEntity(
            instrument_id=instrument_id,
            symbol="AAPL",
            market_code="NASDAQ",
            asset_class="us_stock",
            currency="USD",
            name="Apple Inc.",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
    )

    # Seed: decision context
    dc = DecisionContextEntity(
        decision_context_id=decision_context_id,
        account_id=account_id,
        strategy_id=strategy_id,
        config_version_id=config_version_id,
        market_timestamp=datetime.now(timezone.utc),
        correlation_id=correlation_id,
        created_at=datetime.now(timezone.utc),
    )
    await repos.decision_contexts.add(dc)

    # Seed: trade decision
    td = TradeDecisionEntity(
        trade_decision_id=trade_decision_id,
        decision_context_id=decision_context_id,
        decision_type=DecisionType.APPROVE,
        side=OrderSide.BUY,
        strategy_id=strategy_id,
        symbol="AAPL",
        market="NASDAQ",
        entry_style=EntryStyle.LIMIT,
        created_at=datetime.now(timezone.utc),
        entry_price=Decimal("150.00"),
        quantity=Decimal("100"),
        max_order_value=Decimal("15000"),
    )
    await repos.trade_decisions.add(td)

    # Seed: order
    order = OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id="API-ORDER-001",
        idempotency_key=f"idem-{uuid4()}",
        correlation_id=correlation_id,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        requested_quantity=Decimal("100"),
        status=OrderStatus.ACKNOWLEDGED,
        trade_decision_id=trade_decision_id,
        decision_context_id=decision_context_id,
        requested_price=Decimal("150.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await repos.orders.add(order)

    # Seed: order state events — plausible path to ACKNOWLEDGED
    event1 = OrderStateEventEntity(
        order_state_event_id=uuid4(),
        order_request_id=order.order_request_id,
        previous_status=None,
        new_status=OrderStatus.PENDING_SUBMIT,
        event_source=EventSource.INTERNAL,
        event_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        correlation_id=correlation_id,
    )
    await repos.order_state_events.add(event1)

    event2 = OrderStateEventEntity(
        order_state_event_id=uuid4(),
        order_request_id=order.order_request_id,
        previous_status=OrderStatus.PENDING_SUBMIT,
        new_status=OrderStatus.SUBMITTED,
        event_source=EventSource.BROKER_REST,
        event_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        correlation_id=correlation_id,
    )
    await repos.order_state_events.add(event2)

    # Seed: audit log
    audit = AuditLogEntity(
        audit_log_id=uuid4(),
        actor_type="system",
        actor_id="order_manager",
        action="order.created",
        target_entity_type="order",
        target_entity_id=str(order.order_request_id),
        created_at=datetime.now(timezone.utc),
        correlation_id=correlation_id,
    )
    await repos.audit_logs.add(audit)

    # Seed: reconciliation run
    run = ReconciliationRunEntity(
        reconciliation_run_id=uuid4(),
        account_id=account_id,
        trigger_type="post_submit",
        status="started",
        started_at=datetime.now(timezone.utc),
        mismatch_count=0,
    )
    await repos.reconciliations.add_run(run)

    # Seed: blocking lock (in-memory via acquire_lock)
    repos.reconciliations.acquire_lock(
        account_id=account_id,
        strategy_id=strategy_id,
        symbol="AAPL",
        side="buy",
        reason="reconciliation",
        locked_by_run_id=run.reconciliation_run_id,
        expires_at=datetime.now(timezone.utc).replace(year=9999),  # far future = active
    )

    # Seed: position snapshot
    await repos.position_snapshots.add(
        PositionSnapshotEntity(
            position_snapshot_id=position_snapshot_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("100"),
            average_price=Decimal("150.00"),
            market_price=Decimal("155.00"),
            unrealized_pnl=Decimal("500.00"),
            source_of_truth="broker",
            snapshot_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
    )

    # Seed: cash balance snapshot
    await repos.cash_balance_snapshots.add(
        CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account_id,
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("1000000"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
    )

    # Seed: broker order linked to the order above
    await repos.broker_orders.add(
        BrokerOrderEntity(
            broker_order_id=broker_order_id,
            order_request_id=order.order_request_id,
            broker_name="KIS",
            broker_status="filled",
            broker_native_order_id="KIS-12345",
            last_synced_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
    )

    # Seed: agent runs (3 runs for the decision context)
    # Use distinct started_at values so ordering tests can verify DESC contract.
    now = datetime.now(timezone.utc)
    agent_run_seeds = [
        ("event_interpretation", now - timedelta(seconds=2)),
        ("ai_risk", now - timedelta(seconds=1)),
        ("final_decision_composer", now),
    ]
    for agent_type, started_at in agent_run_seeds:
        await repos.agent_runs.add(
            AgentRunEntity(
                agent_run_id=uuid4(),
                decision_context_id=decision_context_id,
                agent_type=agent_type,
                started_at=started_at,
                status="completed",
                completed_at=started_at,
                created_at=started_at,
            )
        )

    return repos


@pytest.fixture
async def client(seeded_repos: RepositoryContainer) -> TestClient:
    """FastAPI ``TestClient`` with seeded repos (no auth)."""
    app = create_app(repos=seeded_repos, auth_enabled=False)
    with TestClient(app) as tc:
        yield tc


@pytest.fixture
async def empty_client() -> TestClient:
    """FastAPI ``TestClient`` with empty (unseeded) in-memory repos (no auth)."""
    app = create_app(auth_enabled=False)
    with TestClient(app) as tc:
        yield tc


@pytest.fixture
async def auth_client() -> TestClient:
    """FastAPI ``TestClient`` with auth enabled (token: ``"test-token"``)."""
    app = create_app(auth_token="test-token")
    with TestClient(app) as tc:
        yield tc


@pytest.fixture
def mock_budget_manager() -> MagicMock:
    """Return a ``MagicMock`` mimicking ``RateLimitBudgetManager``."""
    from unittest.mock import MagicMock

    mgr = MagicMock()
    mgr.snapshot.return_value = {
        "session_id": "test-session",
        "order": {"remaining": 3.0, "capacity": 5.0, "refill_rate": 1.0, "utilization": 0.4},
        "inquiry": {"remaining": 8.0, "capacity": 10.0, "refill_rate": 2.0, "utilization": 0.2},
        "reconciliation": {
            "remaining": 2.0,
            "capacity": 3.0,
            "refill_rate": 0.5,
            "utilization": 0.33,
        },
        "market_data": {
            "remaining": 5.0,
            "capacity": 5.0,
            "refill_rate": 0.0,
            "utilization": 0.0,
        },
        "auth": {"remaining": 1.0, "capacity": 1.0, "refill_rate": 1.0, "utilization": 0.0},
        "can_accept_new_entries": True,
    }
    return mgr


@pytest.fixture
def mock_subscription_budget() -> MagicMock:
    """Return a ``MagicMock`` mimicking ``SubscriptionBudget``."""
    from unittest.mock import MagicMock

    budget = MagicMock()
    budget.snapshot.return_value = {
        "max_subscriptions": 100,
        "critical_limit": 20,
        "optional_limit": 80,
        "current_critical": 3,
        "current_optional": 5,
        "total_used": 8,
        "remaining": 92,
    }
    return budget


@pytest.fixture
def client_with_adapter(
    seeded_repos: RepositoryContainer,
    mock_budget_manager: MagicMock,
    mock_subscription_budget: MagicMock,
) -> TestClient:
    """FastAPI ``TestClient`` with a mock broker adapter (no auth)."""
    from unittest.mock import MagicMock

    adapter = MagicMock()
    adapter._mode = "paper"
    adapter._rest.budget_manager = mock_budget_manager
    adapter._subscription_budget = mock_subscription_budget
    adapter._market_data_subscriptions = {"005930": None, "000660": None}
    adapter._order_event_accounts = {"account-1"}

    app = create_app(
        repos=seeded_repos,
        auth_enabled=False,
        broker_adapter=adapter,
    )
    with TestClient(app) as tc:
        yield tc
