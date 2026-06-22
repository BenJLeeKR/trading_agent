"""Order inspection endpoints: ``GET /orders``, ``GET /orders/{id}``,
``GET /orders/{id}/events``, ``GET /orders/{id}/broker-orders``,
``GET /orders/{id}/broker-truth``, ``GET /orders/sell-availability``.

Results are sorted by ``created_at`` descending (newest first).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agent_trading.api.deps import get_kis_client, get_order_manager, get_repos
from agent_trading.api.schemas import (
    BrokerOrderView,
    BrokerTruthResponse,
    BuyBlockSummaryResponse,
    FailureSummaryResponse,
    LinkedFillSnapshotSummary,
    ManualStatusChangeRequest,
    ManualStatusChangeResponse,
    OrderDailySummaryResponse,
    OrderDetail,
    OrderEvent,
    OrderSummary,
    RecentFailureItem,
    SellAvailabilityResponse,
    SubmissionAttemptSummary,
    SubmissionAttemptView,
    TruthProbePendingOrderItem,
    TruthProbePendingSummaryResponse,
    _derive_submission_outcome,
)
from agent_trading.api.security import Principal, require_admin, require_viewer
from agent_trading.domain.enums import OrderStatus
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery
from agent_trading.services.order_manager import InvalidStateTransitionError, OrderManager
from agent_trading.services.sell_guard import AvailableSellQtyResolver

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])
_KST = timezone(timedelta(hours=9))


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
    fill_rows = await repos.broker_fill_snapshots.list_recent(
        limit=20,
        order_request_id=order.order_request_id,  # type: ignore[attr-defined]
    )
    if fill_rows:
        latest_fill = fill_rows[0]
        max_filled_quantity = max(row.filled_quantity for row in fill_rows)
        latest_fill_price = float(latest_fill.fill_price)
        filled_quantity = float(max_filled_quantity)
        summary.filled_quantity = filled_quantity
        summary.avg_fill_price = latest_fill_price
        summary.fill_amount = filled_quantity * latest_fill_price
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


async def _build_truth_probe_pending_order_item(
    order: object,
    repos: RepositoryContainer,
) -> TruthProbePendingOrderItem:
    """Build a compact pending-truth-probe row for reporting."""
    symbol: str | None = None
    instrument_id: UUID | None = getattr(order, "instrument_id", None)
    if instrument_id is not None:
        inst = await repos.instruments.get(instrument_id)
        if inst is not None:
            symbol = inst.symbol

    broker_native_order_id: str | None = None
    broker_orders = await repos.broker_orders.list_by_order_request(  # type: ignore[attr-defined]
        order.order_request_id  # type: ignore[attr-defined]
    )
    if broker_orders:
        latest_broker_order = max(
            broker_orders,
            key=lambda item: item.updated_at or item.created_at or datetime.min.replace(tzinfo=timezone.utc),
        )
        broker_native_order_id = latest_broker_order.broker_native_order_id

    return TruthProbePendingOrderItem(
        order_request_id=str(order.order_request_id),  # type: ignore[attr-defined]
        symbol=symbol,
        side=order.side.value,  # type: ignore[attr-defined]
        status=order.status.value,  # type: ignore[attr-defined]
        requested_quantity=float(order.requested_quantity),  # type: ignore[attr-defined]
        trade_decision_id=str(order.trade_decision_id) if order.trade_decision_id is not None else None,  # type: ignore[attr-defined]
        broker_native_order_id=broker_native_order_id,
        status_reason_code=order.status_reason_code,  # type: ignore[attr-defined]
        status_reason_message=order.status_reason_message,  # type: ignore[attr-defined]
        submitted_at=order.submitted_at,  # type: ignore[attr-defined]
        created_at=order.created_at,  # type: ignore[attr-defined]
        updated_at=order.updated_at,  # type: ignore[attr-defined]
    )


@router.get("/recent-failures", response_model=list[RecentFailureItem])
async def list_recent_submission_failures(
    limit: int = Query(default=5, ge=1, le=20),
    target_date: date | None = Query(default=None, alias="date"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[RecentFailureItem]:
    """Return the most recent order requests whose latest submission
    attempt resulted in rejection or exception.

    Results are sorted by ``submitted_at`` descending (newest first).
    """
    submitted_from: datetime | None = None
    submitted_to: datetime | None = None
    if target_date is not None:
        kst_start = datetime.combine(target_date, datetime.min.time(), tzinfo=_KST)
        kst_end = kst_start + timedelta(days=1) - timedelta(microseconds=1)
        submitted_from = kst_start.astimezone(timezone.utc)
        submitted_to = kst_end.astimezone(timezone.utc)

    rows = await repos.order_submission_attempts.list_recent_failures(
        limit=limit,
        submitted_from=submitted_from,
        submitted_to=submitted_to,
    )
    return [RecentFailureItem(**row) for row in rows]


@router.get("/failure-summary", response_model=FailureSummaryResponse)
async def get_failure_summary(
    repos: RepositoryContainer = Depends(get_repos),
) -> FailureSummaryResponse:
    """Return aggregated submission failure counts for the last 1h and 24h.

    Useful for at-a-glance operational monitoring on the dashboard.
    Data is computed from all submission attempts within the relevant
    time windows and grouped by derived outcome (rejected / exception).
    """
    data = await repos.order_submission_attempts.get_failure_summary()
    return FailureSummaryResponse(**data)


@router.get("/daily-summary", response_model=OrderDailySummaryResponse)
async def get_order_daily_summary(
    target_date: date | None = Query(None, alias="date"),
    repos: RepositoryContainer = Depends(get_repos),
) -> OrderDailySummaryResponse:
    """Return KST day-bounded order counts for the dashboard."""
    kst_now = datetime.now(_KST)
    kst_date = target_date or kst_now.date()
    is_in_memory = type(repos.trade_decisions).__name__.startswith("InMemory")
    in_memory_order_decision_ids: set[UUID] = set()
    if is_in_memory:
        day_orders = await repos.orders.list(
            OrderQuery(
                created_from=datetime.combine(kst_date, datetime.min.time(), tzinfo=_KST).astimezone(timezone.utc),
                created_to=(datetime.combine(kst_date, datetime.min.time(), tzinfo=_KST) + timedelta(days=1) - timedelta(microseconds=1)).astimezone(timezone.utc),
                limit=5000,
            )
        )
        in_memory_order_decision_ids = {
            order.trade_decision_id
            for order in day_orders
            if order.trade_decision_id is not None
        }
    kst_start = datetime.combine(kst_date, datetime.min.time(), tzinfo=_KST)
    kst_end = kst_start + timedelta(days=1) - timedelta(microseconds=1)
    query = OrderQuery(
        created_from=kst_start.astimezone(timezone.utc),
        created_to=kst_end.astimezone(timezone.utc),
        limit=100,
    )
    total_count = await repos.orders.count(query)
    status_counts = await repos.orders.count_by_status(query)
    return OrderDailySummaryResponse(
        date=kst_date,
        total_count=total_count,
        filled_count=status_counts.get(OrderStatus.FILLED.value, 0),
        pending_submit_count=status_counts.get(OrderStatus.PENDING_SUBMIT.value, 0),
        submitted_count=status_counts.get(OrderStatus.SUBMITTED.value, 0),
    )


@router.get("/buy-block-summary", response_model=BuyBlockSummaryResponse)
async def get_buy_block_summary(
    target_date: date | None = Query(None, alias="date"),
    repos: RepositoryContainer = Depends(get_repos),
) -> BuyBlockSummaryResponse:
    """Return KST day-bounded BUY broker submission failure summary."""
    kst_now = datetime.now(_KST)
    kst_date = target_date or kst_now.date()
    kst_start = datetime.combine(kst_date, datetime.min.time(), tzinfo=_KST)
    kst_end = kst_start + timedelta(days=1) - timedelta(microseconds=1)
    day_orders = await repos.orders.list(
        OrderQuery(
            created_from=kst_start.astimezone(timezone.utc),
            created_to=kst_end.astimezone(timezone.utc),
            limit=5000,
        )
    )

    total_buy_orders_count = 0
    buy_submission_attempted_count = 0
    rejected_count = 0
    exception_count = 0

    for order in day_orders:
        if _safe_str(order.side).lower() != "buy":
            continue
        total_buy_orders_count += 1
        attempts = await repos.order_submission_attempts.list_by_order_request(
            order.order_request_id
        )
        if not attempts:
            continue
        buy_submission_attempted_count += 1
        latest_attempt = max(attempts, key=lambda item: item.attempt_number)
        if latest_attempt.error_type is not None:
            exception_count += 1
        elif latest_attempt.accepted is False:
            rejected_count += 1

    return BuyBlockSummaryResponse(
        date=kst_date,
        total_buy_orders_count=total_buy_orders_count,
        buy_submission_attempted_count=buy_submission_attempted_count,
        blocked_count=rejected_count + exception_count,
        rejected_count=rejected_count,
        exception_count=exception_count,
    )


@router.get("/truth-probe-pending-summary", response_model=TruthProbePendingSummaryResponse)
async def get_truth_probe_pending_summary(
    target_date: date | None = Query(None, alias="date"),
    limit: int = Query(default=20, ge=1, le=100),
    repos: RepositoryContainer = Depends(get_repos),
) -> TruthProbePendingSummaryResponse:
    """Return KST day-bounded orders awaiting next fill-sync truth convergence."""
    kst_now = datetime.now(_KST)
    kst_date = target_date or kst_now.date()
    kst_start = datetime.combine(kst_date, datetime.min.time(), tzinfo=_KST)
    kst_end = kst_start + timedelta(days=1) - timedelta(microseconds=1)
    rows = await repos.orders.list(
        OrderQuery(
            created_from=kst_start.astimezone(timezone.utc),
            created_to=kst_end.astimezone(timezone.utc),
            limit=5000,
        )
    )
    pending_rows = [
        row
        for row in rows
        if getattr(row, "status_reason_code", None) == "truth_probe_fill_snapshot_incomplete"
    ]
    pending_rows.sort(
        key=lambda row: getattr(row, "updated_at", None) or getattr(row, "created_at", None) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    status_counts: dict[str, int] = {}
    for row in pending_rows:
        status_key = row.status.value  # type: ignore[attr-defined]
        status_counts[status_key] = status_counts.get(status_key, 0) + 1

    recent_orders = [
        await _build_truth_probe_pending_order_item(row, repos)
        for row in pending_rows[:limit]
    ]
    return TruthProbePendingSummaryResponse(
        date=kst_date,
        total_count=len(pending_rows),
        status_counts=status_counts,
        recent_orders=recent_orders,
    )


@router.get("", response_model=list[OrderSummary])
async def list_orders(
    account_id: str | None = Query(None),
    client_order_id: str | None = Query(None),
    status: str | None = Query(None),
    target_date: date | None = Query(None, alias="date"),
    trade_decision_id: str | None = Query(None, description="Filter by trade decision UUID"),
    decision_context_id: str | None = Query(None, description="Filter by decision context UUID"),
    limit: int = Query(100, ge=1, le=10000),
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
    created_from: datetime | None = None
    created_to: datetime | None = None
    if target_date is not None:
        kst_start = datetime.combine(target_date, datetime.min.time(), tzinfo=_KST)
        kst_end = kst_start + timedelta(days=1) - timedelta(microseconds=1)
        created_from = kst_start.astimezone(timezone.utc)
        created_to = kst_end.astimezone(timezone.utc)
    query = OrderQuery(
        account_id=UUID(account_id) if account_id else None,
        client_order_id=client_order_id,
        status=parsed_status,
        created_from=created_from,
        created_to=created_to,
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

    detail = await _enrich_order_detail(order, repos)

    # Phase 7: submission attempts 요약 조회
    attempts = await repos.order_submission_attempts.list_by_order_request(uid)
    if attempts:
        latest = attempts[-1]  # attempt_number 오름차순 정렬됨
        detail.submission_attempt_summary = SubmissionAttemptSummary(
            attempt_count=len(attempts),
            latest_accepted=latest.accepted,
            latest_raw_code=latest.raw_code,
            latest_raw_message=latest.raw_message,
            latest_error_type=latest.error_type,
            last_submitted_at=latest.submitted_at,
            # Phase 8: derived outcome
            latest_outcome=_derive_submission_outcome(
                latest_accepted=latest.accepted,
                latest_error_type=latest.error_type,
            ),
        )

    fill_rows = await repos.broker_fill_snapshots.list_recent(
        limit=20,
        order_request_id=uid,
    )
    if fill_rows:
        latest_fill = fill_rows[0]
        max_filled_quantity = max(row.filled_quantity for row in fill_rows)
        detail.linked_fill_snapshot_summary = LinkedFillSnapshotSummary(
            snapshot_count=len(fill_rows),
            broker_native_order_id=latest_fill.broker_native_order_id,
            symbol=latest_fill.symbol,
            side=latest_fill.side,
            latest_fill_timestamp=latest_fill.fill_timestamp,
            latest_filled_quantity=float(latest_fill.filled_quantity),
            max_filled_quantity=float(max_filled_quantity),
            latest_fill_price=float(latest_fill.fill_price),
            latest_ordered_quantity=float(latest_fill.ordered_quantity)
            if latest_fill.ordered_quantity is not None
            else None,
            latest_order_status_code=latest_fill.order_status_code,
        )

    return detail


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


@router.get(
    "/{order_request_id}/submission-attempts",
    response_model=list[SubmissionAttemptView],
    dependencies=[Depends(require_viewer)],
)
async def list_submission_attempts(
    order_request_id: UUID,
    repos: RepositoryContainer = Depends(get_repos),
) -> list[SubmissionAttemptView]:
    """Return all submission attempts for a given order request."""
    attempts = await repos.order_submission_attempts.list_by_order_request(
        order_request_id,
    )
    return [
        SubmissionAttemptView(
            order_submission_attempt_id=a.attempt_id,
            order_request_id=a.order_request_id,
            attempt_number=a.attempt_number,
            submitted_at=a.submitted_at,
            broker_name=a.broker_name,
            accepted=a.accepted,
            broker_native_order_id=a.broker_native_order_id,
            broker_status=a.broker_status,
            raw_code=a.raw_code,
            raw_message=a.raw_message,
            error_type=a.error_type,
            retryable=a.retryable,
            http_status=a.http_status,
            duration_ms=a.duration_ms,
            created_at=a.created_at,
            # Phase 9: derived outcome for readability
            attempt_outcome=_derive_submission_outcome(
                latest_accepted=a.accepted,
                latest_error_type=a.error_type,
            ),
        )
        for a in attempts
    ]


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


# ---------------------------------------------------------------------------
# Phase D — Broker Truth Inspection
# ---------------------------------------------------------------------------


def _match_order_by_broker_order_id(
    order: object,
    records: list[dict],
) -> dict | None:
    """Match a KIS daily settlement record by ``ODNO`` (broker native order ID).

    Iterates through KIS ``inquire_daily_ccld`` output records and returns
    the first record whose ``odno`` matches the order's broker native order ID.

    Returns ``None`` when no match is found.
    """
    broker_native_id: str | None = getattr(order, "broker_native_order_id", None)
    if not broker_native_id:
        return None
    for rec in records:
        if rec.get("odno") == broker_native_id:
            return rec
    return None


def _map_kis_status(status_code: str) -> str:
    """Map KIS ``ord_tmd`` / ``ord_dvsn_cd`` status code to domain status.

    KIS status codes (``ord_tmd``):
        - ``01`` : 체결 (filled)
        - ``02`` : 접수 (submitted/acknowledged)
        - ``03`` : 취소 (cancelled)
        - ``04`` : 정정 (amended)
        - ``05`` : 거부 (rejected)
        - ``00`` : 미체결 (open/pending)

    Falls back to ``"unknown"`` for unrecognised codes.
    """
    _KIS_STATUS_MAP: dict[str, str] = {
        "00": "pending",
        "01": "filled",
        "02": "submitted",
        "03": "cancelled",
        "04": "amended",
        "05": "rejected",
    }
    return _KIS_STATUS_MAP.get(status_code, "unknown")


def _safe_decimal(value: object) -> Decimal | None:
    """Safely convert a value to ``Decimal``, returning ``None`` for empty/invalid values."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except Exception:
        return None


def _to_broker_truth_response(
    matched: dict,
    order: object,
) -> BrokerTruthResponse:
    """Convert a matched KIS record and order entity to ``BrokerTruthResponse``."""
    return BrokerTruthResponse(
        order_request_id=getattr(order, "order_request_id"),
        broker_order_id=str(matched.get("odno", "")),
        kis_status_code=str(matched.get("ord_tmd", "")),
        mapped_status=_map_kis_status(str(matched.get("ord_tmd", ""))),
        filled_qty=_safe_decimal(matched.get("tot_ccld_qty")),
        open_qty=_safe_decimal(matched.get("rmmn_qty")),
        avg_fill_price=_safe_decimal(matched.get("avg_prvs")),
        order_qty=_safe_decimal(matched.get("ord_qty")),
        order_price=_safe_decimal(matched.get("ord_unpr")),
        last_synced_at=datetime.now(timezone.utc),
        source="VTTC0081R",
    )


def _to_cached_broker_truth_response(order: object) -> BrokerTruthResponse:
    """Build a ``BrokerTruthResponse`` from cached ``broker_orders`` data.

    Used as fallback when the KIS API is unavailable.
    """
    broker_native_id: str | None = getattr(order, "broker_native_order_id", None)
    status_val = getattr(order, "status", None)
    mapped_status: str | None = _safe_str(status_val) if status_val is not None else None

    return BrokerTruthResponse(
        order_request_id=getattr(order, "order_request_id"),
        broker_order_id=broker_native_id,
        kis_status_code=None,
        mapped_status=mapped_status,
        filled_qty=_safe_decimal(getattr(order, "filled_quantity", None)),
        open_qty=None,
        avg_fill_price=_safe_decimal(getattr(order, "average_fill_price", None)),
        order_qty=_safe_decimal(getattr(order, "requested_quantity", None)),
        order_price=_safe_decimal(getattr(order, "requested_price", None)),
        last_synced_at=getattr(order, "updated_at", None),
        source="cached",
    )


@router.get("/{order_request_id}/broker-truth", response_model=BrokerTruthResponse)
async def get_order_broker_truth(
    order_request_id: str,
    request: Request,
    repos: RepositoryContainer = Depends(get_repos),
) -> BrokerTruthResponse:
    """Query KIS broker truth for a specific order.

    Calls KIS ``inquire_daily_ccld`` and returns the matched record.
    Falls back to cached ``broker_orders`` data if KIS API is unavailable.

    The KIS real-time query uses the ``VTTC0081R`` (inquire-daily-ccld) endpoint
    with a date range spanning from one day before the order was created to today.
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

    # 3. Try KIS real-time query
    kis_client = get_kis_client(request)
    if kis_client is not None:
        try:
            # Determine date range: from one day before order creation to today
            created_at: datetime = getattr(order, "created_at", datetime.now(timezone.utc))
            from_date = (created_at - timedelta(days=1)).strftime("%Y%m%d")
            to_date = datetime.now(timezone.utc).strftime("%Y%m%d")

            records = await kis_client.inquire_daily_ccld(
                strt_dt=from_date,
                end_dt=to_date,
            )
            matched = _match_order_by_broker_order_id(order, records)
            if matched:
                return _to_broker_truth_response(matched, order)
        except Exception:
            logger.warning("KIS broker truth query failed, falling back to cached data", exc_info=True)

    # 4. Fallback to cached data
    return _to_cached_broker_truth_response(order)


# ---------------------------------------------------------------------------
# Phase D — Sell Availability Inspection
# ---------------------------------------------------------------------------


@router.get("/sell-availability", response_model=SellAvailabilityResponse)
async def get_sell_availability(
    account_id: UUID,
    symbol: str,
    position_qty: Decimal | None = Query(None, description="Optional override for current position quantity"),
    repos: RepositoryContainer = Depends(get_repos),
) -> SellAvailabilityResponse:
    """Calculate available sell quantity considering open orders.

    Uses ``AvailableSellQtyResolver`` to compute the available sell quantity
    by considering:
    - Current position quantity (from position snapshot, or overridden via query param)
    - Open sell orders (PENDING_SUBMIT / SUBMITTED / ACKNOWLEDGED)
    - Partially filled sell orders (remaining quantity)

    When ``position_qty`` is provided, it overrides the current position quantity
    from the snapshot (useful for manual inspection with hypothetical values).
    """
    resolver = AvailableSellQtyResolver(repos=repos)

    # Resolve symbol → instrument_id
    instrument = await repos.instruments.get_by_symbol_any_market(symbol)
    instrument_id: UUID | None = instrument.instrument_id if instrument else None

    # Determine the requested_qty for the resolver.
    # When position_qty is provided as an override, use it as the requested_qty
    # so the resolver computes availability against that hypothetical position.
    # Otherwise, use Decimal("1") as a minimal positive value — we only need
    # the resolver's intermediate calculations (open_sell_qty, partial_remaining).
    requested_qty = position_qty if position_qty is not None else Decimal("1")

    availability = await resolver.resolve(
        account_id=account_id,
        symbol=symbol,
        requested_qty=requested_qty,
    )

    # When position_qty override is provided, use it as the current position
    # instead of what the resolver fetched from snapshots.
    current_position_qty = position_qty if position_qty is not None else availability.current_position_qty

    # Recalculate available_sell_qty with the (possibly overridden) position qty
    available_sell_qty = current_position_qty - availability.open_sell_qty - availability.partially_filled_remaining_qty

    # Determine block status: blocked when available <= 0
    is_blocked = available_sell_qty <= 0
    block_reason: str | None = None
    if is_blocked:
        parts: list[str] = []
        if current_position_qty <= 0:
            parts.append(f"position_qty={current_position_qty} (no position)")
        if availability.open_sell_qty > 0:
            parts.append(f"open_sell_qty={availability.open_sell_qty}")
        if availability.partially_filled_remaining_qty > 0:
            parts.append(f"partial_remaining={availability.partially_filled_remaining_qty}")
        parts.append(f"available={available_sell_qty}")
        block_reason = "Sell guard blocked: " + "; ".join(parts)

    return SellAvailabilityResponse(
        account_id=account_id,
        symbol=symbol,
        current_position_qty=current_position_qty,
        open_sell_qty=availability.open_sell_qty,
        partially_filled_qty=availability.partially_filled_remaining_qty,
        available_sell_qty=available_sell_qty,
        is_blocked=is_blocked,
        block_reason=block_reason,
    )
