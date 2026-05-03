from __future__ import annotations

"""Integration tests for ``PostgresFillEventRepository``.

These tests verify that fill event records are persisted to the
PostgreSQL ``trading.fill_events`` table and can be queried back.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    AccountEntity,
    BrokerOrderEntity,
    ClientEntity,
    FillEventEntity,
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
from agent_trading.repositories.container import RepositoryContainer


@pytest.fixture
def client_id() -> UUID:
    return uuid4()


@pytest.fixture
def broker_account_id() -> UUID:
    return uuid4()


@pytest.fixture
def account_id() -> UUID:
    return uuid4()


@pytest.fixture
def instrument_id() -> UUID:
    return uuid4()


@pytest.fixture
def order_request_id() -> UUID:
    return uuid4()


@pytest.fixture
async def seeded_postgres_data(
    postgres_repos: RepositoryContainer,
    client_id: UUID,
    broker_account_id: UUID,
    account_id: UUID,
    instrument_id: UUID,
) -> dict[str, UUID]:
    """Insert prerequisite rows (client, broker_account, account, instrument)."""
    now = datetime.now(timezone.utc)
    conn = postgres_repos.unit_of_work.transaction.connection  # type: ignore[union-attr]

    # 1) Client
    client = ClientEntity(
        client_id=client_id,
        client_code=f"FILL-TEST-CLIENT-{uuid4().hex[:8]}",
        name="FillEvent Test Client",
        status="active",
        base_currency="KRW",
        created_at=now,
        updated_at=now,
    )
    await postgres_repos.clients.add(client)

    # 2) BrokerAccount (raw SQL — no repository exists yet)
    await conn.execute(
        """\
INSERT INTO trading.broker_accounts
    (broker_account_id, broker_name, account_ref, environment,
     credential_ref, base_url, status, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)\
""",
        broker_account_id,
        "koreainvestment",
        f"ref-{uuid4().hex[:8]}",
        Environment.PAPER.value,
        "test-cred",
        None,
        "active",
        now,
        now,
    )

    # 3) Account
    account = AccountEntity(
        account_id=account_id,
        client_id=client_id,
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="FillEvent Test Account",
        account_masked="****1234",
        status="active",
        risk_profile={},
        created_at=now,
        updated_at=now,
    )
    await postgres_repos.accounts.add(account)

    # 4) Instrument
    instrument = InstrumentEntity(
        instrument_id=instrument_id,
        symbol=f"FILL{uuid4().hex[:4].upper()}",
        market_code="KRX",
        asset_class=AssetClass.KR_STOCK.value,
        currency="KRW",
        name="FillEvent Test Instrument",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    await postgres_repos.instruments.add(instrument)

    return {
        "client_id": client_id,
        "broker_account_id": broker_account_id,
        "account_id": account_id,
        "instrument_id": instrument_id,
    }


@pytest.fixture
async def seeded_broker_order(
    postgres_repos: RepositoryContainer,
    order_request_id: UUID,
    seeded_postgres_data: dict[str, UUID],
) -> UUID:
    """Insert a parent OrderRequestEntity + BrokerOrderEntity into the DB.

    Returns the ``broker_order_id`` that fill-event tests can use.
    """
    now = datetime.now(timezone.utc)

    # 1) Insert parent OrderRequestEntity
    order = OrderRequestEntity(
        order_request_id=order_request_id,
        account_id=seeded_postgres_data["account_id"],
        instrument_id=seeded_postgres_data["instrument_id"],
        client_order_id=f"FILL-TEST-{uuid4().hex[:8]}",
        idempotency_key=f"idem-{uuid4().hex[:8]}",
        correlation_id=f"corr-{uuid4().hex[:8]}",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        requested_price=None,
        requested_quantity=Decimal("1"),
        status=OrderStatus.DRAFT,
        trade_decision_id=None,
        submitted_at=None,
        status_reason_code=None,
        status_reason_message=None,
        created_at=now,
        updated_at=now,
    )
    await postgres_repos.orders.add(order)

    # 2) Insert parent BrokerOrderEntity referencing the OrderRequestEntity
    broker_order_id = uuid4()
    broker_order = BrokerOrderEntity(
        broker_order_id=broker_order_id,
        order_request_id=order_request_id,
        broker_name="koreainvestment",
        broker_status="acknowledged",
        broker_native_order_id=f"NATIVE-{uuid4().hex[:8]}",
        request_payload_uri=None,
        response_payload_uri=None,
        last_synced_at=None,
        created_at=now,
        updated_at=now,
    )
    await postgres_repos.broker_orders.add(broker_order)

    return broker_order_id


@pytest.fixture
def sample_fill_event(seeded_broker_order: UUID) -> FillEventEntity:
    return FillEventEntity(
        fill_event_id=uuid4(),
        broker_order_id=seeded_broker_order,
        broker_fill_id="FILL-001",
        fill_timestamp=datetime.now(timezone.utc),
        fill_price=Decimal("50000.00"),
        fill_quantity=Decimal("10"),
        fill_fee=Decimal("0.01"),
        fill_tax=Decimal("0.00"),
        source_channel="rest_poll",
        raw_payload_uri=None,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_add_and_list_by_broker_order(
    postgres_repos: RepositoryContainer,
    seeded_broker_order: UUID,
    sample_fill_event: FillEventEntity,
) -> None:
    """Add a fill event and retrieve it by broker_order_id."""
    saved = await postgres_repos.fill_events.add(sample_fill_event)
    assert saved.fill_event_id == sample_fill_event.fill_event_id
    assert saved.fill_price == Decimal("50000.00")
    assert saved.fill_quantity == Decimal("10")
    assert saved.source_channel == "rest_poll"

    results = await postgres_repos.fill_events.list_by_broker_order(seeded_broker_order)
    assert len(results) == 1
    assert results[0].fill_event_id == sample_fill_event.fill_event_id


@pytest.mark.asyncio
async def test_list_by_broker_order_ordered_desc(
    postgres_repos: RepositoryContainer,
    seeded_broker_order: UUID,
) -> None:
    """Fill events are returned in descending fill_timestamp order."""
    base = datetime.now(timezone.utc)
    ids = []

    for i in range(3):
        fe = FillEventEntity(
            fill_event_id=uuid4(),
            broker_order_id=seeded_broker_order,
            broker_fill_id=f"FILL-ORDER-{i}",
            fill_timestamp=base.replace(hour=i + 1),
            fill_price=Decimal(f"50000.00"),
            fill_quantity=Decimal("10"),
            fill_fee=None,
            fill_tax=None,
            source_channel="rest_poll",
            raw_payload_uri=None,
            created_at=base,
        )
        saved = await postgres_repos.fill_events.add(fe)
        ids.append(saved.fill_event_id)

    results = await postgres_repos.fill_events.list_by_broker_order(seeded_broker_order)
    assert len(results) == 3
    # Must be in DESC order (latest first)
    assert results[0].fill_event_id == ids[-1]
    assert results[-1].fill_event_id == ids[0]


@pytest.mark.asyncio
async def test_list_by_broker_order_empty(
    postgres_repos: RepositoryContainer,
) -> None:
    """Non-existent broker_order_id returns an empty sequence."""
    results = await postgres_repos.fill_events.list_by_broker_order(uuid4())
    assert len(results) == 0


@pytest.mark.asyncio
async def test_broker_fill_id_nullable(
    postgres_repos: RepositoryContainer,
    seeded_broker_order: UUID,
) -> None:
    """broker_fill_id can be NULL."""
    fe = FillEventEntity(
        fill_event_id=uuid4(),
        broker_order_id=seeded_broker_order,
        broker_fill_id=None,
        fill_timestamp=datetime.now(timezone.utc),
        fill_price=Decimal("50000.00"),
        fill_quantity=Decimal("10"),
        fill_fee=None,
        fill_tax=None,
        source_channel="websocket",
        raw_payload_uri=None,
        created_at=datetime.now(timezone.utc),
    )

    saved = await postgres_repos.fill_events.add(fe)
    assert saved.broker_fill_id is None
