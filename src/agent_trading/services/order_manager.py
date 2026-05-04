from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.brokers.rate_limit import BudgetExhaustedError, RateLimitBudgetManager
from agent_trading.domain.entities import (
    AuditLogEntity,
    BrokerOrderEntity,
    OrderRequestEntity,
    OrderStateEventEntity,
)
from agent_trading.domain.enums import EventSource, OrderStatus
from agent_trading.domain.models import SubmitOrderRequest, SubmitOrderResult
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import AccountLookup
from agent_trading.repositories.postgres.orders import VersionConflictError
from agent_trading.services.reconciliation_service import ReconciliationService


class InvalidStateTransitionError(ValueError):
    """Raised when an order status transition is not allowed."""

    def __init__(
        self,
        order_request_id: UUID,
        current_status: OrderStatus,
        target_status: OrderStatus,
        reason: str = "",
    ) -> None:
        self.order_request_id = order_request_id
        self.current_status = current_status
        self.target_status = target_status
        msg = (
            f"Invalid transition: {current_status.value} -> {target_status.value}"
            f" for order {order_request_id}"
        )
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


class DuplicateOrderError(ValueError):
    """Raised when a duplicate client_order_id or idempotency_key is detected."""

    def __init__(self, field: str, value: str, existing_order_id: UUID) -> None:
        self.field = field
        self.value = value
        self.existing_order_id = existing_order_id
        super().__init__(
            f"Duplicate {field}={value!r}, existing order={existing_order_id}"
        )


# ---------------------------------------------------------------------------
# State transition table
# ---------------------------------------------------------------------------
_ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.DRAFT: {OrderStatus.VALIDATED},
    OrderStatus.VALIDATED: {OrderStatus.PENDING_SUBMIT},
    OrderStatus.PENDING_SUBMIT: {
        OrderStatus.SUBMITTED,
        OrderStatus.RECONCILE_REQUIRED,
        OrderStatus.REJECTED,
    },
    OrderStatus.SUBMITTED: {
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.RECONCILE_REQUIRED,
    },
    OrderStatus.ACKNOWLEDGED: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.RECONCILE_REQUIRED,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.FILLED,
        OrderStatus.CANCEL_PENDING,
        OrderStatus.RECONCILE_REQUIRED,
    },
    OrderStatus.CANCEL_PENDING: {
        OrderStatus.CANCELLED,
        OrderStatus.RECONCILE_REQUIRED,
    },
    OrderStatus.RECONCILE_REQUIRED: {
        OrderStatus.ACKNOWLEDGED,
        # FILLED intentionally removed — a fill notification during
        # reconciliation must NOT optimistically progress the order state.
        # Fill data is preserved (ExternalEvent + FillEvent), but the
        # order stays in RECONCILE_REQUIRED until reconciliation resolves.
        # See plans/34_reconcile_required_fill_transition_policy.md
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    },
}

_TERMINAL_STATES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)

_AUTHORITATIVE_REFLECTION_TARGETS: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)


def _validate_transition(
    order_request_id: UUID,
    current_status: OrderStatus,
    target_status: OrderStatus,
) -> None:
    if current_status in _TERMINAL_STATES:
        raise InvalidStateTransitionError(
            order_request_id,
            current_status,
            target_status,
            reason=f"{current_status.value} is a terminal state",
        )

    allowed = _ALLOWED_TRANSITIONS.get(current_status)
    if allowed is None or target_status not in allowed:
        raise InvalidStateTransitionError(
            order_request_id,
            current_status,
            target_status,
        )


def _validate_authoritative_target(target_status: OrderStatus) -> None:
    """Validate that ``target_status`` is in the authoritative reflection set.

    Raises
    ------
    ValueError
        If ``target_status`` is not in ``_AUTHORITATIVE_REFLECTION_TARGETS``.
    """
    if target_status not in _AUTHORITATIVE_REFLECTION_TARGETS:
        raise ValueError(
            f"{target_status.value} is not a valid authoritative reflection target. "
            f"Allowed: {', '.join(s.value for s in _AUTHORITATIVE_REFLECTION_TARGETS)}"
        )


# ---------------------------------------------------------------------------
# OrderManager
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class OrderManager:
    """Application service for order lifecycle management.

    Responsibilities
    -----------------
    * Validate incoming order requests (basic field checks).
    * Enforce the order state machine (allowed / forbidden transitions).
    * Double-layer idempotency defence (app-level pre-check + DB constraints).
    * Record audit-log entries for every state change.
    * Persist orders through the provided ``RepositoryContainer``.
    * Submit orders to broker adapters and handle results (Milestone 6).
    * Trigger reconciliation on uncertain / requires_reconciliation results.
    * **Budget exhaustion check** (Milestone 7): reject new entries when
      the ``RateLimitBudgetManager`` indicates budget is exhausted.

    The OrderManager is an **execution orchestrator**, not a decision engine.
    It does **not** perform AI judgment, risk assessment, hard-guardrail
    limit checks, broker capability resolution, or portfolio calculations.
    """

    repos: RepositoryContainer
    reconciliation_service: ReconciliationService | None = None
    budget_manager: RateLimitBudgetManager | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_order(
        self,
        request: SubmitOrderRequest,
        *,
        actor_type: str = "system",
        actor_id: str = "order_manager",
    ) -> OrderRequestEntity:
        """Validate, resolve references, create, and persist a new order.

        Parameters
        ----------
        request : SubmitOrderRequest
            The validated order intent from the decision layer.
        actor_type, actor_id :
            Identity used for the audit-log entry.

        Returns
        -------
        OrderRequestEntity
            The newly created order with ``status == DRAFT``.

        Raises
        ------
        ValueError
            If basic validation fails (quantity <= 0, missing fields).
        DuplicateOrderError
            If ``client_order_id`` already exists.
        BudgetExhaustedError
            If the ``RateLimitBudgetManager`` indicates that new entries
            cannot be accepted (inquiry budget < 20% or reconciliation
            reserve < 50%).
        """
        # --- Budget exhaustion check (Milestone 7) ---
        if self.budget_manager is not None and not self.budget_manager.can_accept_new_entries:
            raise BudgetExhaustedError(
                bucket="new_entry",
                message=(
                    "Budget exhausted: cannot accept new entries. "
                    f"inquiry_utilization={self.budget_manager.snapshot().get('inquiry', {}).get('utilization', 'N/A')}, "
                    f"reconciliation_utilization={self.budget_manager.snapshot().get('reconciliation', {}).get('utilization', 'N/A')}"
                ),
            )

        # --- basic field validation ---
        if request.quantity <= 0:
            raise ValueError("order quantity must be positive")

        if not all([request.client_order_id, request.side, request.order_type]):
            raise ValueError("client_order_id, side, and order_type are required")

        # --- resolve account_id from account_ref ---
        account = await self.repos.accounts.find_one(
            AccountLookup(account_alias=request.account_ref)
        )
        if account is None:
            raise ValueError(f"Account not found for ref={request.account_ref!r}")
        account_id = account.account_id

        # --- resolve instrument_id from symbol + market ---
        instrument = await self.repos.instruments.get_by_symbol(
            request.symbol, request.market
        )
        if instrument is None:
            raise ValueError(
                f"Instrument not found for symbol={request.symbol!r} "
                f"market={request.market!r}"
            )
        instrument_id = instrument.instrument_id

        # --- generate idempotency_key ---
        idempotency_key = self._generate_idempotency_key(request)

        # --- idempotency pre-check (Layer 1) ---
        existing = await self.repos.orders.get_by_client_order_id(
            request.client_order_id
        )
        if existing is not None:
            raise DuplicateOrderError(
                "client_order_id",
                request.client_order_id,
                existing.order_request_id,
            )

        # --- resolve trade_decision_id from decision_id if provided ---
        trade_decision_id: UUID | None = None
        if request.decision_id is not None:
            try:
                trade_decision_id = UUID(request.decision_id)
            except (ValueError, AttributeError):
                pass

        # --- build entity ---
        now = datetime.now(timezone.utc)
        order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument_id,
            client_order_id=request.client_order_id,
            idempotency_key=idempotency_key,
            correlation_id=request.correlation_id,
            side=request.side,
            order_type=request.order_type,
            time_in_force=request.time_in_force,
            requested_price=request.price,
            requested_quantity=request.quantity,
            status=OrderStatus.DRAFT,
            trade_decision_id=trade_decision_id,
            submitted_at=None,
            status_reason_code=None,
            status_reason_message=None,
            created_at=now,
            updated_at=now,
        )

        # --- persist ---
        created = await self.repos.orders.add(order)

        # --- audit log ---
        await self._record_audit(
            actor_type=actor_type,
            actor_id=actor_id,
            action="order.create",
            target_entity_type="order_request",
            target_entity_id=str(created.order_request_id),
            before_json=None,
            after_json=_entity_to_json(created),
            correlation_id=created.correlation_id,
        )

        return created

    async def submit_order_to_broker(
        self,
        order: OrderRequestEntity,
        broker: BrokerAdapter,
        request: SubmitOrderRequest,
        *,
        actor_type: str = "system",
        actor_id: str = "order_manager",
    ) -> OrderRequestEntity:
        """Submit an order to a broker adapter and handle the result.

        This method implements the full submit flow:

        1. **Blocking lock check** — if a reconciliation is active for the
           account/strategy/symbol/side, the submission is blocked and the
           order transitions to ``RECONCILE_REQUIRED``.
        2. **Submit to broker** — delegates to the broker adapter.
        3. **Result handling**:
           - ``accepted=True``, normal → transition to ``SUBMITTED``.
           - ``uncertain=True`` → trigger reconciliation, transition to
             ``RECONCILE_REQUIRED``.
           - ``requires_reconciliation=True`` → trigger reconciliation,
             transition to ``RECONCILE_REQUIRED``.
           - ``accepted=False`` (explicit rejection) → transition to
             ``REJECTED`` (terminal state).

        Parameters
        ----------
        order : OrderRequestEntity
            The order to submit (must be in ``PENDING_SUBMIT`` status).
        broker : BrokerAdapter
            The broker adapter to use for submission.
        request : SubmitOrderRequest
            The original submit request (used for broker submission).
        actor_type, actor_id :
            Identity for the audit-log entry.

        Returns
        -------
        OrderRequestEntity
            The updated order entity reflecting the new status.
        """
        # --- Step 1: Blocking lock check ---
        if self.reconciliation_service is not None:
            # Resolve strategy_id from the request if available.
            strategy_id: UUID | None = None
            try:
                strategy = await self.repos.strategies.get_by_code(
                    client_id=UUID(int=0),  # Placeholder — resolved from context.
                    strategy_code=request.strategy_id,
                )
                if strategy is not None:
                    strategy_id = strategy.strategy_id
            except (ValueError, Exception):
                pass

            blocked = await self.reconciliation_service.is_blocked(
                account_id=order.account_id,
                strategy_id=strategy_id,
                symbol=request.symbol,
                side=request.side.value,
            )
            if blocked:
                return await self.transition_to(
                    order,
                    OrderStatus.RECONCILE_REQUIRED,
                    reason_code="BLOCKED",
                    reason_message=(
                        f"Order blocked by active reconciliation lock for "
                        f"account={order.account_id}"
                    ),
                    actor_type=actor_type,
                    actor_id=actor_id,
                )

        # --- Step 2: Submit to broker ---
        result: SubmitOrderResult = await broker.submit_order(request)

        # --- Step 3: Handle result ---
        if result.uncertain or result.requires_reconciliation:
            # Trigger reconciliation.
            if self.reconciliation_service is not None:
                await self.reconciliation_service.trigger(
                    account_id=order.account_id,
                    trigger_type="uncertain_result" if result.uncertain else "requires_reconciliation",
                    symbol=request.symbol,
                    side=request.side.value,
                )

            return await self.transition_to(
                order,
                OrderStatus.RECONCILE_REQUIRED,
                reason_code=result.raw_code or "UNCERTAIN",
                reason_message=(
                    result.raw_message
                    or f"Broker returned uncertain={result.uncertain}, "
                    f"requires_reconciliation={result.requires_reconciliation}"
                ),
                actor_type=actor_type,
                actor_id=actor_id,
            )

        if result.accepted:
            # Normal path: order was accepted by broker.
            # Record the broker order.
            broker_order = BrokerOrderEntity(
                broker_order_id=uuid4(),
                order_request_id=order.order_request_id,
                broker_name=result.broker_name.value,
                broker_status=result.broker_status.value,
                broker_native_order_id=result.broker_order_id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await self.repos.broker_orders.add(broker_order)

            return await self.transition_to(
                order,
                OrderStatus.SUBMITTED,
                reason_code=result.raw_code,
                reason_message=result.raw_message,
                actor_type=actor_type,
                actor_id=actor_id,
            )

        # Order was explicitly rejected by broker.
        # From PENDING_SUBMIT, REJECTED is now a valid transition.
        return await self.transition_to(
            order,
            OrderStatus.REJECTED,
            reason_code=result.raw_code or "REJECTED",
            reason_message=result.raw_message or "Broker rejected the order",
            actor_type=actor_type,
            actor_id=actor_id,
        )

    async def transition_to(
        self,
        order: OrderRequestEntity,
        target_status: OrderStatus,
        *,
        reason_code: str | None = None,
        reason_message: str | None = None,
        actor_type: str = "system",
        actor_id: str = "order_manager",
        max_retries: int = 3,
        retry_delay: float = 0.05,
    ) -> OrderRequestEntity:
        """Validate and persist a state transition with optimistic locking.

        Enforces ``_ALLOWED_TRANSITIONS`` via ``_validate_transition()``.
        This is the standard path for all regular callers (event loop,
        broker response handlers, etc.).

        For reconciliation authoritative reflection, use
        ``transition_to_authoritative()`` instead.

        Parameters
        ----------
        order : OrderRequestEntity
            The current order entity (must be the latest known state).
        target_status : OrderStatus
            The desired next status.
        reason_code, reason_message :
            Optional reason metadata (e.g. broker rejection code).
        actor_type, actor_id :
            Identity for the audit-log entry.
        max_retries :
            Maximum number of retry attempts on version conflict.
        retry_delay :
            Base delay in seconds between retries (exponential back-off).

        Returns
        -------
        OrderRequestEntity
            A new entity reflecting the updated status.
        """
        _validate_transition(order.order_request_id, order.status, target_status)
        return await self._transition_to_core(
            order,
            target_status,
            reason_code=reason_code,
            reason_message=reason_message,
            actor_type=actor_type,
            actor_id=actor_id,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

    async def transition_to_authoritative(
        self,
        order: OrderRequestEntity,
        target_status: OrderStatus,
        *,
        reconciliation_run_id: UUID,
        reason_message: str | None = None,
        max_retries: int = 3,
        retry_delay: float = 0.05,
    ) -> OrderRequestEntity:
        """Authoritative state reflection for reconciliation path ONLY.

        This method is EXCLUSIVELY for use by ReconciliationService when
        a broker inquiry has resolved an unknown order state.

        Design rationale
        ----------------
        This method deliberately SKIPS ``_validate_transition()`` because
        the transition is driven by the broker's authoritative inquiry
        response, NOT by an optimistic WS fill.  The regular state machine
        (``_ALLOWED_TRANSITIONS``) remains conservative — Plan 34's hard
        boundary is preserved for all other callers.

        All other safeguards are preserved:
        * Optimistic locking with retry
        * Audit log entry (status_change) with actor="reconciliation_service"
        * Order state event (append-only) with reason_code="RECONCILE_RESOLVED"
        * Terminal state detection on version conflict

        Parameters
        ----------
        reconciliation_run_id : UUID
            The reconciliation run driving this reflection.  Included in
            audit/log for full traceability.
        """
        _validate_authoritative_target(target_status)

        # Terminal state check (same safeguard as transition_to).
        if order.status in _TERMINAL_STATES:
            raise InvalidStateTransitionError(
                order.order_request_id,
                order.status,
                target_status,
                reason=f"Cannot transition from terminal state {order.status.value}",
            )

        return await self._transition_to_core(
            order,
            target_status,
            reason_code="RECONCILE_RESOLVED",
            reason_message=reason_message or (
                f"Reconciliation authoritative reflection: "
                f"run_id={reconciliation_run_id}, broker returned {target_status.value}"
            ),
            actor_type="system",
            actor_id="reconciliation_service",
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

    async def _transition_to_core(
        self,
        order: OrderRequestEntity,
        target_status: OrderStatus,
        *,
        reason_code: str | None = None,
        reason_message: str | None = None,
        actor_type: str = "system",
        actor_id: str = "order_manager",
        max_retries: int = 3,
        retry_delay: float = 0.05,
    ) -> OrderRequestEntity:
        """Shared core: optimistic locking retry + audit + order_state_event.

        This is the extracted inner logic of ``transition_to()``, shared
        with ``transition_to_authoritative()`` to avoid code duplication.
        Callers MUST perform their own pre-transition validation before
        calling this method.
        """
        before = order
        after = _replace_status(
            order, target_status, reason_code=reason_code, reason_message=reason_message
        )

        # Retry loop: only update_status() is retried.
        # _record_status_change (audit log) runs once outside the loop.
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                await self.repos.orders.update_status(
                    after.order_request_id,
                    after.status,
                    reason_code=reason_code,
                    reason_message=reason_message,
                    expected_version=after.version,
                )
                last_exc = None
                break
            except VersionConflictError as exc:
                last_exc = exc
                # Re-fetch the latest order to detect terminal state.
                latest = await self.repos.orders.get(after.order_request_id)
                if latest is None:
                    raise ValueError(f"Order not found: {after.order_request_id}") from exc
                # If another worker already moved to a terminal state,
                # do not retry — the transition is no longer valid.
                if latest.status in _TERMINAL_STATES:
                    raise InvalidStateTransitionError(
                        order.order_request_id,
                        after.status,
                        latest.status,
                        reason=(
                            f"Cannot transition to {target_status.value}: "
                            f"order is already in terminal state {latest.status.value}"
                        ),
                    ) from exc
                # Rebuild `after` from the latest version.
                after = _replace_status(
                    latest, target_status, reason_code=reason_code, reason_message=reason_message
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (2**attempt))
        if last_exc is not None:
            raise last_exc

        # Record order_state_event (append-only, outside retry loop).
        # This runs ONLY after a successful update_status, so no stale
        # or incorrect state events are persisted on version conflict.
        await self._record_order_state_event(before, after)

        await self._record_status_change(before, after, actor_type, actor_id)
        return after

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_idempotency_key(request: SubmitOrderRequest) -> str:
        """Deterministic idempotency key from request fields.

        If ``request.idempotency_key`` is explicitly provided, use it directly.
        Otherwise, derive a deterministic key from the core request fields.
        """
        if request.idempotency_key:
            return request.idempotency_key
        raw = ":".join(
            [
                request.client_order_id,
                request.correlation_id,
                request.symbol,
                request.market,
                str(request.quantity),
            ]
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    async def _record_order_state_event(
        self,
        before: OrderRequestEntity,
        after: OrderRequestEntity,
    ) -> None:
        """Append an ``order_state_event`` for the transition.

        This is a **supplementary** audit trail, not a replacement for
        the current-state stored in ``order_requests.status``.

        The event is recorded **after** a successful ``update_status()``
        call, so version conflicts or transition failures never produce
        stale event entries.
        """
        event = OrderStateEventEntity(
            order_state_event_id=uuid4(),
            order_request_id=after.order_request_id,
            previous_status=before.status,
            new_status=after.status,
            event_source=EventSource.INTERNAL,
            event_timestamp=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            reason_code=after.status_reason_code,
            correlation_id=after.correlation_id,
        )
        await self.repos.order_state_events.add(event)

    async def _record_status_change(
        self,
        before: OrderRequestEntity,
        after: OrderRequestEntity,
        actor_type: str,
        actor_id: str,
    ) -> None:
        await self._record_audit(
            actor_type=actor_type,
            actor_id=actor_id,
            action="order.status_change",
            target_entity_type="order_request",
            target_entity_id=str(after.order_request_id),
            before_json=_entity_to_json(before),
            after_json=_entity_to_json(after),
            correlation_id=after.correlation_id,
            metadata={
                "from_status": before.status.value,
                "to_status": after.status.value,
            },
        )

    async def _record_audit(
        self,
        *,
        actor_type: str,
        actor_id: str,
        action: str,
        target_entity_type: str,
        target_entity_id: str,
        before_json: dict[str, object] | None,
        after_json: dict[str, object] | None,
        correlation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        entry = AuditLogEntity(
            audit_log_id=uuid4(),
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            created_at=datetime.now(timezone.utc),
            before_json=before_json,
            after_json=after_json,
            correlation_id=correlation_id,
            metadata=metadata or {},
        )
        await self.repos.audit_logs.add(entry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _replace_status(
    order: OrderRequestEntity,
    new_status: OrderStatus,
    *,
    reason_code: str | None = None,
    reason_message: str | None = None,
) -> OrderRequestEntity:
    import dataclasses

    return dataclasses.replace(
        order,
        status=new_status,
        status_reason_code=reason_code,
        status_reason_message=reason_message,
        updated_at=datetime.now(timezone.utc),
    )


def _entity_to_json(entity: OrderRequestEntity) -> dict[str, object]:
    def _val(v: object) -> object:
        """Return ``.value`` if v is an enum, otherwise v as-is."""
        return v.value if hasattr(v, "value") else v

    return {
        "order_request_id": str(entity.order_request_id),
        "account_id": str(entity.account_id),
        "instrument_id": str(entity.instrument_id),
        "client_order_id": entity.client_order_id,
        "idempotency_key": entity.idempotency_key,
        "correlation_id": entity.correlation_id,
        "side": _val(entity.side),
        "order_type": _val(entity.order_type),
        "time_in_force": _val(entity.time_in_force),
        "requested_price": str(entity.requested_price) if entity.requested_price else None,
        "requested_quantity": str(entity.requested_quantity),
        "status": _val(entity.status),
        "status_reason_code": entity.status_reason_code,
        "status_reason_message": entity.status_reason_message,
        "trade_decision_id": str(entity.trade_decision_id) if entity.trade_decision_id else None,
        "submitted_at": entity.submitted_at.isoformat() if entity.submitted_at else None,
        "created_at": entity.created_at.isoformat() if entity.created_at else None,
        "updated_at": entity.updated_at.isoformat() if entity.updated_at else None,
    }
