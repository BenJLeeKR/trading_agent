from __future__ import annotations

"""Decision loop smoke test — seed → insert → query end-to-end.

This test exercises the full in-memory repository stack and OrderManager
to verify that the core data flow works correctly without a database.
"""

from decimal import Decimal

import pytest

from agent_trading.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery
from agent_trading.services.order_manager import (
    DuplicateOrderError,
    InvalidStateTransitionError,
    OrderManager,
)


@pytest.mark.asyncio
async def test_paper_loop_happy_path(
    seeded_repos: RepositoryContainer,
    order_manager: OrderManager,
) -> None:
    """End-to-end: seed → create order → validate → transition → query."""

    # ---------------------------------------------------------------
    # 1. Verify seed data exists
    # ---------------------------------------------------------------
    client = await seeded_repos.clients.get_by_code("TEST001")
    assert client is not None, "Seed client should exist"

    accounts = await seeded_repos.accounts.list_by_client(client.client_id)
    assert len(accounts) >= 1, "Seed account should exist"

    instrument = await seeded_repos.instruments.get_by_symbol("005930", "KRX")
    assert instrument is not None, "Seed instrument should exist"

    # ---------------------------------------------------------------
    # 2. Create an order (DRAFT)
    # ---------------------------------------------------------------
    request = SubmitOrderRequest(
        client_order_id="SMOKE-CLI-001",
        correlation_id="SMOKE-CORR-001",
        account_ref="Test Account",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
    )

    order = await order_manager.create_order(request)
    assert order.status == OrderStatus.DRAFT
    assert order.client_order_id == "SMOKE-CLI-001"

    # ---------------------------------------------------------------
    # 3. Validate → VALIDATED
    # ---------------------------------------------------------------
    validated = await order_manager.transition_to(order, OrderStatus.VALIDATED)
    assert validated.status == OrderStatus.VALIDATED

    # ---------------------------------------------------------------
    # 4. Prepare submit → PENDING_SUBMIT
    # ---------------------------------------------------------------
    pending = await order_manager.transition_to(validated, OrderStatus.PENDING_SUBMIT)
    assert pending.status == OrderStatus.PENDING_SUBMIT

    # ---------------------------------------------------------------
    # 5. Mark submitted → SUBMITTED
    # ---------------------------------------------------------------
    submitted = await order_manager.transition_to(pending, OrderStatus.SUBMITTED)
    assert submitted.status == OrderStatus.SUBMITTED

    # ---------------------------------------------------------------
    # 6. Acknowledge → ACKNOWLEDGED
    # ---------------------------------------------------------------
    acknowledged = await order_manager.transition_to(submitted, OrderStatus.ACKNOWLEDGED)
    assert acknowledged.status == OrderStatus.ACKNOWLEDGED

    # ---------------------------------------------------------------
    # 7. Fill → FILLED
    # ---------------------------------------------------------------
    filled = await order_manager.transition_to(acknowledged, OrderStatus.FILLED)
    assert filled.status == OrderStatus.FILLED

    # ---------------------------------------------------------------
    # 8. Query by filters
    # ---------------------------------------------------------------
    # By account
    query = OrderQuery(account_id=accounts[0].account_id)
    results = await seeded_repos.orders.list(query)
    assert len(results) >= 1
    assert any(r.order_request_id == order.order_request_id for r in results)

    # By client_order_id
    fetched = await seeded_repos.orders.get_by_client_order_id("SMOKE-CLI-001")
    assert fetched is not None
    assert fetched.status == OrderStatus.FILLED

    # ---------------------------------------------------------------
    # 9. Verify audit log entries exist
    # ---------------------------------------------------------------
    audit_logs = await seeded_repos.audit_logs.list_by_correlation_id(
        "SMOKE-CORR-001"
    )
    # We expect at least: order.create + each status_change
    assert len(audit_logs) >= 2, "Should have at least create + one status change"
    actions = [log.action for log in audit_logs]
    assert "order.create" in actions
    assert "order.status_change" in actions


@pytest.mark.asyncio
async def test_paper_loop_duplicate_rejected(
    seeded_repos: RepositoryContainer,
    order_manager: OrderManager,
) -> None:
    """Duplicate client_order_id must be rejected."""

    request = SubmitOrderRequest(
        client_order_id="SMOKE-DUP-001",
        correlation_id="SMOKE-DUP-CORR",
        account_ref="Test Account",
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
    await order_manager.create_order(request)

    # Second call with same client_order_id fails
    with pytest.raises(DuplicateOrderError):
        await order_manager.create_order(request)


@pytest.mark.asyncio
async def test_paper_loop_forbidden_transition_rejected(
    seeded_repos: RepositoryContainer,
    order_manager: OrderManager,
) -> None:
    """Forbidden state transitions must be rejected."""

    request = SubmitOrderRequest(
        client_order_id="SMOKE-FORBIDDEN-001",
        correlation_id="SMOKE-FORBIDDEN-CORR",
        account_ref="Test Account",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
    )

    order = await order_manager.create_order(request)

    # DRAFT → SUBMITTED is forbidden (must go through VALIDATED first)
    with pytest.raises(InvalidStateTransitionError):
        await order_manager.transition_to(order, OrderStatus.SUBMITTED)

    # DRAFT → FILLED is forbidden
    with pytest.raises(InvalidStateTransitionError):
        await order_manager.transition_to(order, OrderStatus.FILLED)
