"""Order inspection endpoints: ``GET /orders``, ``GET /orders/{id}``,
``GET /orders/{id}/events``, ``GET /orders/{id}/broker-orders``.

Results are sorted by ``created_at`` descending (newest first).
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_order_manager, get_repos
from agent_trading.api.schemas import (
    BrokerOrderView,
    ManualStatusChangeRequest,
    ManualStatusChangeResponse,
    OrderDetail,
    OrderEvent,
    OrderSummary,
)
from agent_trading.api.security import Principal, require_admin
from agent_trading.domain.enums import OrderStatus
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery
from agent_trading.services.order_manager import InvalidStateTransitionError, OrderManager
from agent_trading.domain.enums import OrderStatus
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery

router = APIRouter(prefix="/orders", tags=["orders"])


def _safe_str(val: object) -> str:
    """Safely convert an enum or string value to its string representation.

    Handles the case where DB rows contain plain strings (e.g.
    ``"broker_truth_recovery"``, ``"system_ops_recovery"``) that are not
    members of the ``EventSource`` enum, avoiding ``AttributeError`` when
    calling ``.value`` on a plain ``str``.
    """
    if isinstance(val, Enum):
        return val.value
    return str(val)


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
        symbol=None,  # enriched by _enrich_order_summary
        correlation_id=str(order.correlation_id),  # type: ignore[attr-defined]
        trade_decision_id=str(order.trade_decision_id) if order.trade_decision_id is not None else None,  # type: ignore[attr-defined]
        decision_context_id=str(order.decision_context_id) if order.decision_context_id is not None else None,  # type: ignore[attr-defined]
        created_at=order.created_at,  # type: ignore[attr-defined]
        updated_at=order.updated_at,  # type: ignore[attr-defined]
        version=order.version,  # type: ignore[attr-defined]
    )


async def _enrich_order_summary(
    order: object,
    repos: RepositoryContainer,
) -> OrderSummary:
    """Convert an ``OrderRequestEntity`` to ``OrderSummary`` with symbol resolved.

    Looks up the instrument by ``instrument_id`` to populate the ``symbol``
    field.  Falls back to ``None`` when the instrument is not found.
    """
    summary = _order_to_summary(order)
    instrument_id: UUID | None = getattr(order, "instrument_id", None)
    if instrument_id is not None:
        inst = await repos.instruments.get(instrument_id)
        if inst is not None:
            summary.symbol = inst.symbol
            summary.instrument_name = inst.name
    return summary


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


async def _enrich_order_detail(
    order: object,
    repos: RepositoryContainer,
) -> OrderDetail:
    """Convert an ``OrderRequestEntity`` to ``OrderDetail`` with symbol resolved."""
    detail = _order_to_detail(order)
    instrument_id: UUID | None = getattr(order, "instrument_id", None)
    if instrument_id is not None:
        inst = await repos.instruments.get(instrument_id)
        if inst is not None:
            detail.symbol = inst.symbol
    return detail


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
    parsed_status: OrderStatus | None = None
    if status is not None:
        try:
            parsed_status = OrderStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid order status: {status}",
            )
    query = OrderQuery(
        account_id=UUID(account_id) if account_id else None,
        client_order_id=client_order_id,
        status=parsed_status,
        trade_decision_id=UUID(trade_decision_id) if trade_decision_id else None,
        decision_context_id=UUID(decision_context_id) if decision_context_id else None,
        limit=limit,
    )
    orders = await repos.orders.list(query)
    return [await _enrich_order_summary(o, repos) for o in orders]


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
    return await _enrich_order_detail(order, repos)


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
            previous_status=_safe_str(e.previous_status) if e.previous_status is not None else None,
            new_status=_safe_str(e.new_status),
            event_source=_safe_str(e.event_source),
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


@router.put("/{order_request_id}/status", response_model=ManualStatusChangeResponse)
async def manual_resolve_order_status(
    order_request_id: str,
    body: ManualStatusChangeRequest,
    repos: RepositoryContainer = Depends(get_repos),
    order_manager: OrderManager = Depends(get_order_manager),
    principal: Principal = Depends(require_admin),
) -> ManualStatusChangeResponse:
    """Manually override the status of a RECONCILE_REQUIRED order (v1 — admin only).

    v1 scope:
    - Only orders in ``RECONCILE_REQUIRED`` status are accepted.
    - Target must be one of ``{FILLED, CANCELLED, REJECTED, EXPIRED}``.
    - ``evidence`` is required and must contain at least ``source`` and ``checked_at``.

    Audit trail:
    - Appends an ``order_state_event`` with ``event_source = "operator"``.
    - Writes an ``audit_log`` entry with full evidence in metadata.

    Reconciliation fallback:
    - If a pending reconciliation run is linked to this order, it is
      automatically resolved.
    """
    # 1. Parse UUID
    try:
        uid = UUID(order_request_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {order_request_id}")

    # 2. Find order
    order = await repos.orders.get(uid)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order not found: {order_request_id}")

    # 3. Validate evidence structure
    if not body.evidence:
        raise HTTPException(status_code=400, detail="evidence is required")
    required_fields: set[str] = {"source", "checked_at"}
    missing: set[str] = required_fields - set(body.evidence.keys())
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"evidence missing required fields: {', '.join(sorted(missing))}",
        )

    # 4. Execute manual resolve
    try:
        updated = await order_manager.manual_resolve(
            order,
            body.target_status,
            reason_code=body.reason_code or "MANUAL_RESOLVE",
            reason_message=body.reason_message,
            evidence=body.evidence,
            operator=principal.role,
        )
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ManualStatusChangeResponse(
        order_id=str(updated.order_request_id),
        old_status=order.status.value,
        new_status=updated.status.value,
        updated_at=updated.updated_at,
        actor=principal.role,
    )
