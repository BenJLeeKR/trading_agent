from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agent_trading.domain.entities import OrderRequestEntity
from agent_trading.domain.enums import (
    AssetClass,
    Environment,
    EventSource,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.order_manager import OrderManager


@pytest.fixture
def sample_order(account_id, instrument_id) -> OrderRequestEntity:
    now = datetime.now(timezone.utc)
    return OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id="EVT-INT-001",
        idempotency_key="idem-evt-001",
        correlation_id="corr-evt-001",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        requested_price=Decimal("50000"),
        requested_quantity=Decimal("10"),
        status=OrderStatus.DRAFT,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_transition_to_creates_order_state_event(
    seeded_repos: RepositoryContainer,
    order_manager: OrderManager,
    sample_order: OrderRequestEntity,
) -> None:
    """Verify that transition_to() appends an order_state_event."""
    await seeded_repos.orders.add(sample_order)

    after = await order_manager.transition_to(
        sample_order, OrderStatus.VALIDATED, reason_code="test"
    )
    assert after.status == OrderStatus.VALIDATED

    events = await seeded_repos.order_state_events.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(events) == 1
    assert events[0].new_status == OrderStatus.VALIDATED
    assert events[0].previous_status == OrderStatus.DRAFT
    assert events[0].event_source == EventSource.INTERNAL


@pytest.mark.asyncio
async def test_order_state_event_has_correct_source(
    seeded_repos: RepositoryContainer,
    order_manager: OrderManager,
    sample_order: OrderRequestEntity,
) -> None:
    """Verify event_source is always INTERNAL for OrderManager transitions."""
    await seeded_repos.orders.add(sample_order)

    after = await order_manager.transition_to(
        sample_order, OrderStatus.VALIDATED, actor_type="system", actor_id="test"
    )
    assert after.status == OrderStatus.VALIDATED

    events = await seeded_repos.order_state_events.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(events) == 1
    assert events[0].event_source == EventSource.INTERNAL


@pytest.mark.asyncio
async def test_multiple_transitions_create_multiple_events(
    seeded_repos: RepositoryContainer,
    order_manager: OrderManager,
    sample_order: OrderRequestEntity,
) -> None:
    """Verify each transition creates a separate append-only event."""
    await seeded_repos.orders.add(sample_order)

    # DRAFT -> VALIDATED
    order = await order_manager.transition_to(sample_order, OrderStatus.VALIDATED)
    # VALIDATED -> PENDING_SUBMIT
    order = await order_manager.transition_to(order, OrderStatus.PENDING_SUBMIT)
    # PENDING_SUBMIT -> SUBMITTED
    order = await order_manager.transition_to(order, OrderStatus.SUBMITTED)

    events = await seeded_repos.order_state_events.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(events) == 3
    assert events[0].new_status == OrderStatus.VALIDATED
    assert events[1].new_status == OrderStatus.PENDING_SUBMIT
    assert events[2].new_status == OrderStatus.SUBMITTED


@pytest.mark.asyncio
async def test_no_event_on_forbidden_transition(
    seeded_repos: RepositoryContainer,
    order_manager: OrderManager,
    sample_order: OrderRequestEntity,
) -> None:
    """Verify that a forbidden transition does NOT create an event."""
    await seeded_repos.orders.add(sample_order)

    with pytest.raises(Exception):
        await order_manager.transition_to(sample_order, OrderStatus.FILLED)

    events = await seeded_repos.order_state_events.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(events) == 0


@pytest.mark.asyncio
async def test_event_not_recorded_on_version_conflict(
    seeded_repos: RepositoryContainer,
    order_manager: OrderManager,
    sample_order: OrderRequestEntity,
) -> None:
    """Verify that a version conflict does NOT leave a stale event.

    Simulate concurrent modification by updating the order directly
    before calling transition_to(), causing a VersionConflictError.
    """
    await seeded_repos.orders.add(sample_order)

    # Simulate concurrent modification: update status directly
    await seeded_repos.orders.update_status(
        sample_order.order_request_id,
        OrderStatus.VALIDATED,
        expected_version=None,  # bypass version check
    )

    # Now try to transition from DRAFT -> VALIDATED — this will fail
    # because the current status is already VALIDATED (not DRAFT).
    with pytest.raises(Exception):
        await order_manager.transition_to(sample_order, OrderStatus.PENDING_SUBMIT)

    # No event should have been recorded
    events = await seeded_repos.order_state_events.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(events) == 0
