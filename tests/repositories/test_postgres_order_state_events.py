from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import OrderRequestEntity, OrderStateEventEntity
from agent_trading.domain.enums import EventSource, OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.container import RepositoryContainer


@pytest.fixture
async def seeded_order(
    seeded_postgres_data: RepositoryContainer,
    sample_order: OrderRequestEntity,
) -> UUID:
    """Create a persisted order request for FK references."""
    saved = await seeded_postgres_data.orders.add(sample_order)
    return saved.order_request_id


@pytest.mark.asyncio
async def test_add_and_list_by_order_request(
    seeded_postgres_data: RepositoryContainer,
    seeded_order: UUID,
) -> None:
    order_request_id = seeded_order
    now = datetime.now(timezone.utc)

    event = OrderStateEventEntity(
        order_state_event_id=uuid4(),
        order_request_id=order_request_id,
        previous_status=OrderStatus.DRAFT,
        new_status=OrderStatus.VALIDATED,
        event_source=EventSource.INTERNAL,
        event_timestamp=now,
        ingested_at=now,
        reason_code=None,
        correlation_id="corr-001",
    )
    saved = await seeded_postgres_data.order_state_events.add(event)
    assert saved.order_state_event_id == event.order_state_event_id
    assert saved.new_status == OrderStatus.VALIDATED

    events = await seeded_postgres_data.order_state_events.list_by_order_request(
        order_request_id
    )
    assert len(events) == 1
    assert events[0].new_status == OrderStatus.VALIDATED


@pytest.mark.asyncio
async def test_list_by_order_request_empty(seeded_postgres_data: RepositoryContainer) -> None:
    events = await seeded_postgres_data.order_state_events.list_by_order_request(uuid4())
    assert len(events) == 0


@pytest.mark.asyncio
async def test_list_recent(
    seeded_postgres_data: RepositoryContainer,
    seeded_order: UUID,
) -> None:
    order_request_id = seeded_order
    now = datetime.now(timezone.utc)

    for status in (OrderStatus.DRAFT, OrderStatus.VALIDATED, OrderStatus.PENDING_SUBMIT):
        await seeded_postgres_data.order_state_events.add(
            OrderStateEventEntity(
                order_state_event_id=uuid4(),
                order_request_id=order_request_id,
                previous_status=None,
                new_status=status,
                event_source=EventSource.INTERNAL,
                event_timestamp=now,
                ingested_at=now,
            )
        )

    recent = await seeded_postgres_data.order_state_events.list_recent(limit=10)
    assert len(recent) >= 3


@pytest.mark.asyncio
async def test_add_multiple_events_same_order(
    seeded_postgres_data: RepositoryContainer,
    seeded_order: UUID,
) -> None:
    """Verify append-only: multiple events for the same order are all preserved."""
    order_request_id = seeded_order
    now = datetime.now(timezone.utc)

    for status in (
        OrderStatus.DRAFT,
        OrderStatus.VALIDATED,
        OrderStatus.PENDING_SUBMIT,
        OrderStatus.SUBMITTED,
    ):
        await seeded_postgres_data.order_state_events.add(
            OrderStateEventEntity(
                order_state_event_id=uuid4(),
                order_request_id=order_request_id,
                previous_status=None,
                new_status=status,
                event_source=EventSource.INTERNAL,
                event_timestamp=now,
                ingested_at=now,
            )
        )

    events = await seeded_postgres_data.order_state_events.list_by_order_request(
        order_request_id
    )
    assert len(events) == 4
