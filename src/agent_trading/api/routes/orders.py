"""Order inspection endpoints: ``GET /orders``, ``GET /orders/{id}``,
``GET /orders/{id}/events``, ``GET /orders/{id}/broker-orders``.

Results are sorted by ``created_at`` descending (newest first).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import BrokerOrderView, OrderDetail, OrderEvent, OrderSummary
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery

router = APIRouter(prefix="/orders", tags=["orders"])


def _order_to_summary(order: object) -> OrderSummary:
    """Convert an ``OrderRequestEntity`` to ``OrderSummary``."""
    return OrderSummary(
        order_request_id=str(order.order_request_id),  # type: ignore[attr-defined]
        client_order_id=str(order.client_order_id),  # type: ignore[attr-defined]
        account_id=str(order.account_id),  # type: ignore[attr-defined]
        side=order.side.value,  # type: ignore[attr-defined]
        order_type=order.order_type.value,  # type: ignore[attr-defined]
        status=order.status.value,  # type: ignore[attr-defined]
        requested_quantity=float(order.requested_quantity),  # type: ignore[attr-defined]
        requested_price=float(order.requested_price) if order.requested_price is not None else None,  # type: ignore[attr-defined]
        symbol=None,  # resolves from instrument_id (skipped for now)
        correlation_id=str(order.correlation_id),  # type: ignore[attr-defined]
        trade_decision_id=str(order.trade_decision_id) if order.trade_decision_id is not None else None,  # type: ignore[attr-defined]
        decision_context_id=str(order.decision_context_id) if order.decision_context_id is not None else None,  # type: ignore[attr-defined]
        created_at=order.created_at,  # type: ignore[attr-defined]
        updated_at=order.updated_at,  # type: ignore[attr-defined]
        version=order.version,  # type: ignore[attr-defined]
    )


def _order_to_detail(order: object) -> OrderDetail:
    """Convert an ``OrderRequestEntity`` to ``OrderDetail``."""
    summary = _order_to_summary(order)
    return OrderDetail(
        **summary.model_dump(),
        instrument_id=str(order.instrument_id),  # type: ignore[attr-defined]
        status_reason_code=order.status_reason_code,  # type: ignore[attr-defined]
        status_reason_message=order.status_reason_message,  # type: ignore[attr-defined]
        submitted_at=order.submitted_at,  # type: ignore[attr-defined]
        time_in_force=order.time_in_force.value if order.time_in_force is not None else None,  # type: ignore[attr-defined]
    )


@router.get("", response_model=list[OrderSummary])
async def list_orders(
    account_id: str | None = Query(None),
    client_order_id: str | None = Query(None),
    status: str | None = Query(None),
    trade_decision_id: str | None = Query(None, description="Filter by trade decision UUID"),
    decision_context_id: str | None = Query(None, description="Filter by decision context UUID"),
    limit: int = Query(100, ge=1, le=1000),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[OrderSummary]:
    """List orders with optional filters.

    Results are sorted by ``created_at`` descending (newest first).
    """
    query = OrderQuery(
        account_id=UUID(account_id) if account_id else None,
        client_order_id=client_order_id,
        status=status,
        trade_decision_id=UUID(trade_decision_id) if trade_decision_id else None,
        decision_context_id=UUID(decision_context_id) if decision_context_id else None,
        limit=limit,
    )
    orders = await repos.orders.list(query)
    return [_order_to_summary(o) for o in orders]


@router.get("/{order_request_id}", response_model=OrderDetail)
async def get_order(
    order_request_id: str,
    repos: RepositoryContainer = Depends(get_repos),
) -> OrderDetail:
    """Get a single order by ID with full detail."""
    try:
        uid = UUID(order_request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {order_request_id}") from exc

    order = await repos.orders.get(uid)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order not found: {order_request_id}")
    return _order_to_detail(order)


@router.get("/{order_request_id}/events", response_model=list[OrderEvent])
async def get_order_events(
    order_request_id: str,
    repos: RepositoryContainer = Depends(get_repos),
) -> list[OrderEvent]:
    """List state transition events for a single order.

    Results are sorted by ``event_timestamp`` ascending (oldest first).
    """
    try:
        uid = UUID(order_request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {order_request_id}") from exc

    # Validate order exists
    order = await repos.orders.get(uid)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order not found: {order_request_id}")

    events = await repos.order_state_events.list_by_order_request(uid)
    return [
        OrderEvent(
            order_state_event_id=str(e.order_state_event_id),
            previous_status=e.previous_status.value if e.previous_status else None,
            new_status=e.new_status.value,
            event_source=e.event_source.value,
            event_timestamp=e.event_timestamp,
            reason_code=e.reason_code,
            correlation_id=e.correlation_id,
            created_at=e.created_at,
        )
        for e in events
    ]


@router.get("/{order_request_id}/broker-orders", response_model=list[BrokerOrderView])
async def get_broker_orders(
    order_request_id: str,
    repos: RepositoryContainer = Depends(get_repos),
) -> list[BrokerOrderView]:
    """List broker-side order references for a given order request.

    Returns an empty list when no broker orders have been registered yet.
    """
    try:
        uid = UUID(order_request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {order_request_id}") from exc

    # Validate order exists first
    order = await repos.orders.get(uid)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order not found: {order_request_id}")

    broker_orders = await repos.broker_orders.list_by_order_request(uid)
    return [BrokerOrderView.model_validate(bo) for bo in broker_orders]
