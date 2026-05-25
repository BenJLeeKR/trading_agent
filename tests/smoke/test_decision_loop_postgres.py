from __future__ import annotations

"""PostgreSQL-backed decision loop smoke test.

This test exercises the full Postgres repository stack and OrderManager
to verify that the core data flow works correctly with a real database.

The ``postgres_repos`` fixture:
  - Applies migrations before the test.
  - Rolls back the transaction after the test (clean state).
  - Uses the ``trading`` schema explicitly.
"""

from decimal import Decimal

import pytest

from datetime import datetime, timezone
from uuid import UUID

from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    ClientEntity,
    InstrumentEntity,
)
from agent_trading.domain.enums import (
    AssetClass,
    Environment,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery
from agent_trading.services.order_manager import (
    DuplicateOrderError,
    InvalidStateTransitionError,
    OrderManager,
)


async def _seed_broker_account(
    postgres_repos: RepositoryContainer,
    broker_account_id: UUID,
    account_ref: str = "PG-SMOKE-ACCT",
) -> None:
    """Insert a broker_account row via the repository."""
    account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="KoreaInvestment",
        account_ref=account_ref,
        environment=Environment.PAPER,
        credential_ref="pg-smoke-cred",
        base_url=None,
        status="active",
        broker_account_code="KIS-PAPER-****ACCT",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await postgres_repos.broker_accounts.add(account)


@pytest.mark.asyncio
async def test_postgres_paper_loop_happy_path(
    postgres_repos: RepositoryContainer,
) -> None:
    """End-to-end: seed -> create order -> transition -> audit verify.

    This test verifies the full closed loop:
      account -> instrument -> order -> audit_log
    """
    # ---------------------------------------------------------------
    # 1. Seed data directly into Postgres
    # ---------------------------------------------------------------
    from uuid import uuid4
    from datetime import datetime, timezone

    client_id = uuid4()
    account_id = uuid4()
    instrument_id = uuid4()
    broker_account_id = uuid4()
    now = datetime.now(timezone.utc)

    client = ClientEntity(
        client_id=client_id,
        client_code="PG-SMOKE-001",
        name="Postgres Smoke Test Client",
        status="active",
        base_currency="KRW",
    )
    await postgres_repos.clients.add(client)

    # broker_accounts must exist before accounts (FK constraint)
    await _seed_broker_account(postgres_repos, broker_account_id, "PG-SMOKE-BA")

    account = AccountEntity(
        account_id=account_id,
        client_id=client_id,
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="PG Smoke Account",
        account_masked="****0001",
        status="active",
    )
    await postgres_repos.accounts.add(account)

    instrument = InstrumentEntity(
        instrument_id=instrument_id,
        symbol="005930",
        market_code="KRX",
        asset_class=AssetClass.KR_STOCK.value,
        currency="KRW",
        name="Samsung Electronics",
        is_active=True,
    )
    await postgres_repos.instruments.add(instrument)

    # ---------------------------------------------------------------
    # 2. Create an order (DRAFT)
    # ---------------------------------------------------------------
    mgr = OrderManager(repos=postgres_repos)

    request = SubmitOrderRequest(
        client_order_id="PG-SMOKE-CLI-001",
        correlation_id="PG-SMOKE-CORR-001",
        account_ref="PG Smoke Account",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
    )

    order = await mgr.create_order(request)
    assert order.status == OrderStatus.DRAFT
    assert order.client_order_id == "PG-SMOKE-CLI-001"

    # ---------------------------------------------------------------
    # 3. Verify audit log: order.create exists
    # ---------------------------------------------------------------
    audit_logs = await postgres_repos.audit_logs.list_by_correlation_id(
        "PG-SMOKE-CORR-001"
    )
    assert len(audit_logs) >= 1
    actions = [log.action for log in audit_logs]
    assert "order.create" in actions

    # ---------------------------------------------------------------
    # 4. Validate -> VALIDATED
    # ---------------------------------------------------------------
    validated = await mgr.transition_to(order, OrderStatus.VALIDATED)
    assert validated.status == OrderStatus.VALIDATED

    # ---------------------------------------------------------------
    # 5. Prepare submit -> PENDING_SUBMIT
    # ---------------------------------------------------------------
    pending = await mgr.transition_to(validated, OrderStatus.PENDING_SUBMIT)
    assert pending.status == OrderStatus.PENDING_SUBMIT

    # ---------------------------------------------------------------
    # 6. Mark submitted -> SUBMITTED
    # ---------------------------------------------------------------
    submitted = await mgr.transition_to(pending, OrderStatus.SUBMITTED)
    assert submitted.status == OrderStatus.SUBMITTED

    # ---------------------------------------------------------------
    # 7. Acknowledge -> ACKNOWLEDGED
    # ---------------------------------------------------------------
    acknowledged = await mgr.transition_to(submitted, OrderStatus.ACKNOWLEDGED)
    assert acknowledged.status == OrderStatus.ACKNOWLEDGED

    # ---------------------------------------------------------------
    # 8. Fill -> FILLED
    # ---------------------------------------------------------------
    filled = await mgr.transition_to(acknowledged, OrderStatus.FILLED)
    assert filled.status == OrderStatus.FILLED

    # ---------------------------------------------------------------
    # 9. Query by filters
    # ---------------------------------------------------------------
    query = OrderQuery(account_id=account_id)
    results = await postgres_repos.orders.list(query)
    assert len(results) >= 1
    assert any(r.order_request_id == order.order_request_id for r in results)

    fetched = await postgres_repos.orders.get_by_client_order_id("PG-SMOKE-CLI-001")
    assert fetched is not None
    assert fetched.status == OrderStatus.FILLED

    # ---------------------------------------------------------------
    # 10. Verify audit log entries (detailed)
    # ---------------------------------------------------------------
    audit_logs = await postgres_repos.audit_logs.list_by_correlation_id(
        "PG-SMOKE-CORR-001"
    )
    # Expect: order.create + each status_change (DRAFT->VALIDATED->PENDING_SUBMIT->SUBMITTED->ACKNOWLEDGED->FILLED)
    assert len(audit_logs) >= 6, (
        f"Expected at least 6 audit log entries, got {len(audit_logs)}"
    )

    actions = [log.action for log in audit_logs]
    assert "order.create" in actions
    assert "order.status_change" in actions

    # Verify before_json/after_json on status changes
    status_changes = [log for log in audit_logs if log.action == "order.status_change"]
    assert len(status_changes) >= 1
    # First status change: DRAFT -> VALIDATED
    assert status_changes[0].before_json is not None
    assert status_changes[0].after_json is not None
    assert status_changes[0].before_json.get("status") == OrderStatus.DRAFT.value
    assert status_changes[0].after_json.get("status") == OrderStatus.VALIDATED.value


@pytest.mark.asyncio
async def test_postgres_paper_loop_duplicate_rejected(
    postgres_repos: RepositoryContainer,
) -> None:
    """Duplicate client_order_id must be rejected (Postgres UNIQUE)."""
    from uuid import uuid4
    from datetime import datetime, timezone

    # Seed minimal data
    client_id = uuid4()
    account_id = uuid4()
    instrument_id = uuid4()
    broker_account_id = uuid4()
    now = datetime.now(timezone.utc)

    await postgres_repos.clients.add(
        ClientEntity(
            client_id=client_id,
            client_code="PG-DUP-001",
            name="Dup Test",
            status="active",
            base_currency="KRW",
        )
    )

    # broker_accounts must exist before accounts (FK constraint)
    await _seed_broker_account(postgres_repos, broker_account_id, "PG-DUP-BA")

    await postgres_repos.accounts.add(
        AccountEntity(
            account_id=account_id,
            client_id=client_id,
            broker_account_id=broker_account_id,
            environment=Environment.PAPER,
            account_alias="Dup Account",
            account_masked="****0002",
            status="active",
        )
    )
    await postgres_repos.instruments.add(
        InstrumentEntity(
            instrument_id=instrument_id,
            symbol="005930",
            market_code="KRX",
            asset_class=AssetClass.KR_STOCK.value,
            currency="KRW",
            name="Samsung Electronics",
            is_active=True,
        )
    )

    mgr = OrderManager(repos=postgres_repos)

    request = SubmitOrderRequest(
        client_order_id="PG-DUP-CLI-001",
        correlation_id="PG-DUP-CORR",
        account_ref="Dup Account",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("5"),
        price=Decimal("60000"),
        time_in_force=TimeInForce.DAY,
    )

    # First call succeeds
    await mgr.create_order(request)

    # Second call with same client_order_id fails
    with pytest.raises(DuplicateOrderError):
        await mgr.create_order(request)

    # Verify audit log captured the duplicate attempt
    audit_logs = await postgres_repos.audit_logs.list_by_correlation_id("PG-DUP-CORR")
    assert len(audit_logs) >= 1


@pytest.mark.asyncio
async def test_postgres_paper_loop_forbidden_transition_rejected(
    postgres_repos: RepositoryContainer,
) -> None:
    """Forbidden state transitions must be rejected."""
    from uuid import uuid4
    from datetime import datetime, timezone

    # Seed minimal data
    client_id = uuid4()
    account_id = uuid4()
    instrument_id = uuid4()
    broker_account_id = uuid4()
    now = datetime.now(timezone.utc)

    await postgres_repos.clients.add(
        ClientEntity(
            client_id=client_id,
            client_code="PG-FORBID-001",
            name="Forbidden Test",
            status="active",
            base_currency="KRW",
        )
    )

    # broker_accounts must exist before accounts (FK constraint)
    await _seed_broker_account(postgres_repos, broker_account_id, "PG-FORBID-BA")

    await postgres_repos.accounts.add(
        AccountEntity(
            account_id=account_id,
            client_id=client_id,
            broker_account_id=broker_account_id,
            environment=Environment.PAPER,
            account_alias="Forbidden Account",
            account_masked="****0003",
            status="active",
        )
    )
    await postgres_repos.instruments.add(
        InstrumentEntity(
            instrument_id=instrument_id,
            symbol="005930",
            market_code="KRX",
            asset_class=AssetClass.KR_STOCK.value,
            currency="KRW",
            name="Samsung Electronics",
            is_active=True,
        )
    )

    mgr = OrderManager(repos=postgres_repos)

    request = SubmitOrderRequest(
        client_order_id="PG-FORBIDDEN-001",
        correlation_id="PG-FORBIDDEN-CORR",
        account_ref="Forbidden Account",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
    )

    order = await mgr.create_order(request)

    # DRAFT -> SUBMITTED is forbidden (must go through VALIDATED first)
    with pytest.raises(InvalidStateTransitionError):
        await mgr.transition_to(order, OrderStatus.SUBMITTED)

    # DRAFT -> FILLED is forbidden
    with pytest.raises(InvalidStateTransitionError):
        await mgr.transition_to(order, OrderStatus.FILLED)
