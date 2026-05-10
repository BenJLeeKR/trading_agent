from __future__ import annotations

"""Integration tests for ``PostgresBrokerOrderRepository``.

These tests verify that broker order records are persisted to the
PostgreSQL ``trading.broker_orders`` table and can be queried back.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    BrokerOrderEntity,
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
        client_code=f"BRK-TEST-CLIENT-{uuid4().hex[:8]}",
        name="BrokerOrder Test Client",
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
        account_alias="BrokerOrder Test Account",
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
        symbol=f"BRK{uuid4().hex[:4].upper()}",
        market_code="KRX",
        asset_class=AssetClass.KR_STOCK.value,
        currency="KRW",
        name="BrokerOrder Test Instrument",
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
async def seeded_order_request(
    postgres_repos: RepositoryContainer,
    order_request_id: UUID,
    seeded_postgres_data: dict[str, UUID],
) -> UUID:
    """Insert a parent ``order_request`` row so FK constraints are satisfied."""
    now = datetime.now(timezone.utc)
    order = OrderRequestEntity(
        order_request_id=order_request_id,
        account_id=seeded_postgres_data["account_id"],
        instrument_id=seeded_postgres_data["instrument_id"],
        client_order_id=f"BRK-TEST-{uuid4().hex[:8]}",
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
    return order_request_id


@pytest.fixture
def sample_broker_order(order_request_id: UUID) -> BrokerOrderEntity:
    now = datetime.now(timezone.utc)
    return BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order_request_id,
        broker_name="KIS",
        broker_native_order_id=f"NATIVE-{uuid4().hex[:8]}",
        broker_status="submitted",
        request_payload_uri=None,
        response_payload_uri=None,
        last_synced_at=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_add_and_get_by_native_order_id(
    postgres_repos: RepositoryContainer,
    seeded_order_request: UUID,
    sample_broker_order: BrokerOrderEntity,
) -> None:
    """Add a broker order and retrieve it by native order id."""
    saved = await postgres_repos.broker_orders.add(sample_broker_order)
    assert saved.broker_order_id == sample_broker_order.broker_order_id
    assert saved.broker_status == "submitted"

    fetched = await postgres_repos.broker_orders.get_by_native_order_id(
        "KIS", sample_broker_order.broker_native_order_id
    )
    assert fetched is not None
    assert fetched.broker_order_id == sample_broker_order.broker_order_id


@pytest.mark.asyncio
async def test_get_by_native_order_id_nonexistent(
    postgres_repos: RepositoryContainer,
) -> None:
    """Non-existent native order id returns None."""
    result = await postgres_repos.broker_orders.get_by_native_order_id(
        "KIS", "DOES-NOT-EXIST"
    )
    assert result is None


@pytest.mark.asyncio
async def test_list_by_order_request(
    postgres_repos: RepositoryContainer,
    seeded_order_request: UUID,
) -> None:
    """List all broker orders for a given order request."""
    now = datetime.now(timezone.utc)
    ids = []

    for i in range(2):
        bo = BrokerOrderEntity(
            broker_order_id=uuid4(),
            order_request_id=seeded_order_request,
            broker_name="KIS",
            broker_native_order_id=f"NATIVE-LIST-{uuid4().hex[:8]}-{i}",
            broker_status="submitted",
            request_payload_uri=None,
            response_payload_uri=None,
            last_synced_at=None,
            created_at=now,
            updated_at=now,
        )
        saved = await postgres_repos.broker_orders.add(bo)
        ids.append(saved.broker_order_id)

    results = await postgres_repos.broker_orders.list_by_order_request(
        seeded_order_request
    )
    assert len(results) == 2
    assert {r.broker_order_id for r in results} == set(ids)


@pytest.mark.asyncio
async def test_broker_native_order_id_nullable(
    postgres_repos: RepositoryContainer,
    seeded_order_request: UUID,
) -> None:
    """broker_native_order_id can be NULL (before broker acknowledges)."""
    now = datetime.now(timezone.utc)
    bo = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=seeded_order_request,
        broker_name="KIS",
        broker_native_order_id=None,
        broker_status="pending",
        request_payload_uri=None,
        response_payload_uri=None,
        last_synced_at=None,
        created_at=now,
        updated_at=now,
    )

    saved = await postgres_repos.broker_orders.add(bo)
    assert saved.broker_native_order_id is None


@pytest.mark.asyncio
async def test_get_by_id(
    postgres_repos: RepositoryContainer,
    seeded_order_request: UUID,
    sample_broker_order: BrokerOrderEntity,
) -> None:
    """Retrieve a broker order by ``broker_order_id`` (PK lookup)."""
    saved = await postgres_repos.broker_orders.add(sample_broker_order)

    fetched = await postgres_repos.broker_orders.get(saved.broker_order_id)
    assert fetched is not None
    assert fetched.broker_order_id == sample_broker_order.broker_order_id
    assert fetched.broker_status == "submitted"
    assert fetched.broker_name == "KIS"


@pytest.mark.asyncio
async def test_get_by_id_not_found(
    postgres_repos: RepositoryContainer,
) -> None:
    """Nonexistent ``broker_order_id`` returns ``None``."""
    result = await postgres_repos.broker_orders.get(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_update_status(
    postgres_repos: RepositoryContainer,
    seeded_order_request: UUID,
    sample_broker_order: BrokerOrderEntity,
) -> None:
    """Update ``broker_status`` only and verify via ``get()``."""
    saved = await postgres_repos.broker_orders.add(sample_broker_order)
    new_status = "filled"

    await postgres_repos.broker_orders.update(
        saved.broker_order_id,
        broker_status=new_status,
    )

    updated = await postgres_repos.broker_orders.get(saved.broker_order_id)
    assert updated is not None
    assert updated.broker_status == new_status
    # updated_at should have been bumped
    assert updated.updated_at > saved.updated_at


@pytest.mark.asyncio
async def test_update_last_synced_at(
    postgres_repos: RepositoryContainer,
    seeded_order_request: UUID,
    sample_broker_order: BrokerOrderEntity,
) -> None:
    """Update ``last_synced_at`` only."""
    saved = await postgres_repos.broker_orders.add(sample_broker_order)
    assert saved.last_synced_at is None  # fixture starts with None

    sync_time = datetime.now(timezone.utc)
    await postgres_repos.broker_orders.update(
        saved.broker_order_id,
        last_synced_at=sync_time,
    )

    updated = await postgres_repos.broker_orders.get(saved.broker_order_id)
    assert updated is not None
    assert updated.last_synced_at is not None
    # Allow small rounding differences from the DB timestamptz
    assert abs((updated.last_synced_at - sync_time).total_seconds()) < 2


@pytest.mark.asyncio
async def test_update_multiple_fields(
    postgres_repos: RepositoryContainer,
    seeded_order_request: UUID,
    sample_broker_order: BrokerOrderEntity,
) -> None:
    """Update ``broker_status`` and ``last_synced_at`` simultaneously."""
    saved = await postgres_repos.broker_orders.add(sample_broker_order)
    new_status = "partially_filled"
    sync_time = datetime.now(timezone.utc)

    await postgres_repos.broker_orders.update(
        saved.broker_order_id,
        broker_status=new_status,
        last_synced_at=sync_time,
    )

    updated = await postgres_repos.broker_orders.get(saved.broker_order_id)
    assert updated is not None
    assert updated.broker_status == new_status
    assert updated.last_synced_at is not None
    assert abs((updated.last_synced_at - sync_time).total_seconds()) < 2
    assert updated.updated_at > saved.updated_at


@pytest.mark.asyncio
async def test_update_not_found(
    postgres_repos: RepositoryContainer,
) -> None:
    """Update on a nonexistent ``broker_order_id`` raises ``ValueError``."""
    with pytest.raises(ValueError, match="BrokerOrder not found"):
        await postgres_repos.broker_orders.update(
            uuid4(),
            broker_status="filled",
        )
