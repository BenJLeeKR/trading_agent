"""Post-Submit Unknown State / Reconciliation Boundary Verification (Plan 33).

Test categories
---------------
**Safety boundary verification** (Tests A, C, D, E):
  Verify that after broker submit, unknown/uncertain states trigger
  reconciliation-first behavior rather than optimistic state progression.

**Known gap characterization** (Test B):
  Document current behavior where a WS full-fill notification CAN bypass
  the reconciliation process. This is NOT a safety guarantee.

References
----------
* ``plans/33_post_submit_reconciliation_boundary.md`` — full plan document
* ``plans/32_ai_broker_boundary_pre_submit_verification.md`` — pre-submit boundary
* ``_ALLOWED_TRANSITIONS`` in ``order_manager.py`` — state machine definition
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    AuditLogEntity,
    BrokerOrderEntity,
    FillEventEntity,
    ExternalEventEntity,
    OrderRequestEntity,
)
from agent_trading.domain.enums import (
    BrokerName,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.domain.models import (
    OrderStatusResult,
    SubmitOrderRequest,
    SubmitOrderResult,
)
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.order_manager import (
    OrderManager,
    InvalidStateTransitionError,
)
from agent_trading.services.reconciliation_service import ReconciliationService
from agent_trading.services.event_loop import RealTimeEventLoop

pytestmark = pytest.mark.asyncio


# ======================================================================
# Shared fixtures
# ======================================================================


@pytest.fixture
def repos():
    return build_in_memory_repositories()


@pytest.fixture
def reconciliation_service(repos):
    return ReconciliationService(repos)


@pytest.fixture
def manager(repos, reconciliation_service):
    return OrderManager(
        repos=repos,
        reconciliation_service=reconciliation_service,
    )


@pytest.fixture
def mock_broker() -> BrokerAdapter:
    broker = MagicMock(spec=BrokerAdapter)
    broker.submit_order = AsyncMock()
    broker.resolve_unknown_state = AsyncMock()
    return broker


@pytest.fixture
def mock_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.ws_messages = AsyncMock()
    adapter.get_fills = AsyncMock(return_value=[])
    return adapter


@pytest.fixture
def submit_request() -> SubmitOrderRequest:
    return SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="test-001",
        correlation_id="corr-001",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
    )


# ======================================================================
# Helper: create a persisted order with a given status
# ======================================================================


async def _create_order(
    repos,
    status: OrderStatus = OrderStatus.PENDING_SUBMIT,
    *,
    account_id: UUID | None = None,
    client_order_id: str = "test-001",
    **kwargs,
) -> OrderRequestEntity:
    now = datetime.now(timezone.utc)
    order = OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id or uuid4(),
        instrument_id=kwargs.get("instrument_id", uuid4()),
        client_order_id=client_order_id,
        idempotency_key=kwargs.get("idempotency_key", f"ik-{client_order_id}"),
        correlation_id=kwargs.get("correlation_id", "corr-001"),
        side=kwargs.get("side", OrderSide.BUY),
        order_type=kwargs.get("order_type", OrderType.LIMIT),
        requested_quantity=kwargs.get("requested_quantity", Decimal("10")),
        status=status,
        requested_price=kwargs.get("requested_price", Decimal("50000")),
        time_in_force=kwargs.get("time_in_force", TimeInForce.DAY),
        created_at=now,
        updated_at=now,
    )
    await repos.orders.add(order)
    return order


# ======================================================================
# Helper: build a RealTimeEventLoop with real repos + services
# ======================================================================


def _build_event_loop(
    mock_adapter: MagicMock,
    manager: OrderManager,
    reconciliation_service: ReconciliationService,
    repos,
) -> RealTimeEventLoop:
    return RealTimeEventLoop(
        adapter=mock_adapter,
        order_manager=manager,
        reconciliation_service=reconciliation_service,
        order_repo=repos.orders,
        fill_repo=repos.fill_events,
        external_event_repo=repos.external_events,
        broker_order_repo=repos.broker_orders,
    )


# ======================================================================
# Category 1: Safety Boundary Verification
# ======================================================================


class TestPartialFillOnReconcileRequiredBlocks:
    """Test A: State machine blocks PARTIALLY_FILLED from RECONCILE_REQUIRED.

    Verifies that a WebSocket partial-fill notification for an order in
    ``RECONCILE_REQUIRED`` status does NOT progress the order to
    ``PARTIALLY_FILLED``.

    Safety principle
    ----------------
    ``_ALLOWED_TRANSITIONS[RECONCILE_REQUIRED]`` explicitly excludes
    ``PARTIALLY_FILLED``.  This is the safety barrier: any partial-fill
    event arriving while reconciliation is pending is blocked.  The fill
    data is still persisted (append-only ingest), so no data is lost.
    """

    # ------------------------------------------------------------------
    # 1a. Direct state machine test
    # ------------------------------------------------------------------

    async def test_transition_to_partially_filled_raises_error(
        self,
        repos,
        manager: OrderManager,
    ) -> None:
        """Direct ``transition_to()`` call raises ``InvalidStateTransitionError``."""
        order = await _create_order(repos, status=OrderStatus.RECONCILE_REQUIRED)

        with pytest.raises(InvalidStateTransitionError):
            await manager.transition_to(
                order,
                OrderStatus.PARTIALLY_FILLED,
                reason_code="WS_FILL",
                reason_message="Partial fill during reconciliation",
            )

    # ------------------------------------------------------------------
    # 1b. Event loop path — data preservation
    # ------------------------------------------------------------------

    async def test_event_loop_preserves_fill_data_when_transition_blocked(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_adapter: MagicMock,
    ) -> None:
        """Event loop preserves ExternalEvent + FillEvent even when transition
        is blocked — no data loss despite the safety barrier.

        This verifies the append-only ingest principle: fill notifications
        are always persisted regardless of state machine decisions.
        """
        # --- Arrange ---
        account_id = uuid4()
        order = await _create_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            account_id=account_id,
        )

        # BrokerOrderEntity needed for native ID resolution
        broker_order = BrokerOrderEntity(
            broker_order_id=uuid4(),
            order_request_id=order.order_request_id,
            broker_name="koreainvestment",
            broker_status="reconcile_required",
            broker_native_order_id="KIS12345678",
            created_at=datetime.now(timezone.utc),
        )
        await repos.broker_orders.add(broker_order)

        event_loop = _build_event_loop(
            mock_adapter, manager, reconciliation_service, repos
        )

        # Partial fill: filled_qty=3 < order_qty=10
        data = {
            "broker_order_id": "KIS12345678",
            "stock_code": "005930",
            "filled_qty": "3",
            "filled_price": "50000",
            "filled_time": "143025",
            "side": OrderSide.BUY,
            "order_qty": "10",
        }

        # --- Act ---
        await event_loop._handle_fill_notification(data)

        # --- Assert ---

        # ExternalEvent persisted (append-only ingest)
        ext_event = await repos.external_events.find_by_dedup_key(
            "fill:KIS12345678:143025"
        )
        assert ext_event is not None, "ExternalEvent should be persisted"
        assert ext_event.event_type == "fill_notification"
        assert ext_event.dedup_key_hash == "fill:KIS12345678:143025"

        # FillEvent persisted (no data loss)
        # Note: FillEventEntity.broker_order_id stores the local order_request_id
        fill_events = await repos.fill_events.list_by_broker_order(
            order.order_request_id
        )
        assert len(fill_events) == 1
        assert fill_events[0].fill_quantity == Decimal("3")
        assert fill_events[0].fill_price == Decimal("50000")

        # Order status is STILL RECONCILE_REQUIRED (transition blocked)
        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.RECONCILE_REQUIRED


class TestReconciliationLockPersistsAfterUncertainSubmit:
    """Test C: Reconciliation lock persists and blocks subsequent submissions.

    Verifies that after an uncertain broker submit result:
    1. The order transitions to ``RECONCILE_REQUIRED``.
    2. A blocking lock is acquired (by ``ReconciliationService.trigger()``).
    3. ``is_blocked()`` returns ``True`` for the scoped key.
    """

    async def test_lock_acquired_after_uncertain_submit(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """Uncertain submit → lock acquired → is_blocked() returns True."""
        # --- Arrange: first submit returns uncertain ---
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id=None,  # Missing → uncertain
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )

        # --- Act: submit with uncertain result ---
        result = await manager.submit_order_to_broker(
            sample_order, mock_broker, submit_request
        )

        # --- Assert: order is in RECONCILE_REQUIRED ---
        assert result.status == OrderStatus.RECONCILE_REQUIRED

        # --- Assert: lock is held ---
        locked = await reconciliation_service.is_blocked(
            account_id=sample_order.account_id,
            symbol=submit_request.symbol,
            side=submit_request.side.value,
        )
        assert locked is True, (
            "Expected is_blocked() to return True after uncertain submit"
        )

    async def test_lock_blocks_second_submit(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """Lock from first uncertain submit blocks a second submission."""
        # --- First submit: uncertain ---
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )
        await manager.submit_order_to_broker(sample_order, mock_broker, submit_request)

        # Reset call count for second submit check
        mock_broker.submit_order.reset_mock()

        # --- Second order, same account ---
        second_order = await _create_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            account_id=sample_order.account_id,
            client_order_id="test-002",
        )

        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-002",
            broker_order_id="BRK-002",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="0000",
            raw_message="Accepted",
        )

        result2 = await manager.submit_order_to_broker(
            second_order, mock_broker, submit_request
        )

        # Second submit was blocked by lock — broker NOT called again
        assert result2.status == OrderStatus.RECONCILE_REQUIRED
        assert result2.status_reason_code == "BLOCKED"
        mock_broker.submit_order.assert_not_called()


class TestResolveAndMarkUnblocksSubmission:
    """Test D: Recovery path — broker inquiry resolves unknown state, releases
    lock, and reopens the broker submission path.

    Verifies that ``resolve_and_mark()``:
    1. Inquires the broker for the current order status.
    2. If resolved (e.g. FILLED, CANCELLED, ACKNOWLEDGED), marks the
       reconciliation run as resolved.
    3. Releases the blocking lock.
    4. After release, ``is_blocked()`` returns ``False`` and a subsequent
       ``submit_order_to_broker()`` succeeds.
    """

    async def test_resolve_and_mark_releases_lock(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """resolve_and_mark() → broker inquiry → lock released → path open."""
        # --- Step 1: Submit with uncertain result to enter RECONCILE_REQUIRED ---
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )
        result = await manager.submit_order_to_broker(
            sample_order, mock_broker, submit_request
        )
        assert result.status == OrderStatus.RECONCILE_REQUIRED

        # --- Step 2: Verify lock is held ---
        locked = await reconciliation_service.is_blocked(
            account_id=sample_order.account_id,
            symbol=submit_request.symbol,
            side=submit_request.side.value,
        )
        assert locked is True

        # --- Step 3: Get the active reconciliation run ---
        active_run = await reconciliation_service.get_active_run(
            sample_order.account_id
        )
        assert active_run is not None
        assert active_run.status == "started"

        # --- Step 4: Broker inquiry returns a resolved status ---
        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id="BRK-001",
            status=OrderStatus.ACKNOWLEDGED,
        )

        await reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="test-001",
        )

        # --- Step 5: Lock is released ---
        locked_after = await reconciliation_service.is_blocked(
            account_id=sample_order.account_id,
            symbol=submit_request.symbol,
            side=submit_request.side.value,
        )
        assert locked_after is False, (
            "Expected lock to be released after resolve_and_mark"
        )

        # --- Step 6: Verify broker path is reopened by submitting a new order ---
        second_order = await _create_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            account_id=sample_order.account_id,
            client_order_id="test-002",
        )

        mock_broker.submit_order.reset_mock()
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-002",
            broker_order_id="BRK-002",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="0000",
            raw_message="Accepted",
        )

        result2 = await manager.submit_order_to_broker(
            second_order, mock_broker, submit_request
        )

        # Submission succeeds — broker was called
        assert result2.status == OrderStatus.SUBMITTED
        mock_broker.submit_order.assert_awaited_once()

    async def test_mark_resolved_releases_lock_by_run_id(
        self,
        repos,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """mark_resolved() releases only locks created by the resolved run."""
        # Acquire a blocking lock via trigger
        run = await reconciliation_service.trigger(
            account_id=sample_order.account_id,
            trigger_type="uncertain_result",
            symbol=submit_request.symbol,
            side=submit_request.side.value,
        )
        assert run.status == "started"

        # Lock is held
        locked = await reconciliation_service.is_blocked(
            account_id=sample_order.account_id,
            symbol=submit_request.symbol,
            side=submit_request.side.value,
        )
        assert locked is True

        # mark_resolved releases locks by locked_by_run_id
        await reconciliation_service.mark_resolved(
            reconciliation_run_id=run.reconciliation_run_id,
            summary_json={"resolved_via": "test"},
        )

        # Lock is released after mark_resolved
        locked_after = await reconciliation_service.is_blocked(
            account_id=sample_order.account_id,
            symbol=submit_request.symbol,
            side=submit_request.side.value,
        )
        assert locked_after is False


class TestUnknownStateLifecycleOrderAuditAndReconciliationState:
    """Test E: Order audit entries and reconciliation state for unknown-state lifecycle.

    Verifies:
    1. ``order.status_change`` audit entry created on uncertain submit
       (by ``OrderManager._record_status_change``, action="order.status_change").
    2. Reconciliation run lifecycle: active run exists after uncertain submit,
       and ``resolve_and_mark()`` updates run status to ``"resolved"``.

    Note: ``ReconciliationService`` does NOT produce audit-log entries.
          Reconciliation state is verified directly via ``ReconciliationRepository``.
    """

    async def test_audit_log_entries_for_uncertain_submit(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """Uncertain submit produces ``order.status_change`` audit entries."""
        # --- Arrange ---
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )

        # --- Act ---
        await manager.submit_order_to_broker(
            sample_order, mock_broker, submit_request
        )

        # --- Assert: audit logs exist for the lifecycle ---
        audit_logs = await repos.audit_logs.list_by_correlation_id(
            sample_order.correlation_id
        )

        # There should be at least the status_change entry
        status_changes = [
            e
            for e in audit_logs
            if e.action == "order.status_change"
            and e.target_entity_id == str(sample_order.order_request_id)
        ]
        assert len(status_changes) >= 1, (
            f"Expected at least 1 status_change audit entry for "
            f"order {sample_order.order_request_id}, got {len(status_changes)}"
        )

        # Verify the status change metadata
        change_entry = status_changes[0]
        assert change_entry.metadata.get("from_status") == OrderStatus.PENDING_SUBMIT.value
        assert change_entry.metadata.get("to_status") == OrderStatus.RECONCILE_REQUIRED.value

    async def test_unknown_state_lifecycle_records_order_audit_and_reconciliation_state(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """Full lifecycle: uncertain submit → order.status_change audit entry +
        reconciliation run active → resolve_and_mark() → run status == resolved."""
        # --- Phase 1: Uncertain submit ---
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )
        result = await manager.submit_order_to_broker(
            sample_order, mock_broker, submit_request
        )
        assert result.status == OrderStatus.RECONCILE_REQUIRED

        # --- Phase 2: Resolve via broker inquiry ---
        active_run = await reconciliation_service.get_active_run(
            sample_order.account_id
        )
        assert active_run is not None

        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id="BRK-001",
            status=OrderStatus.ACKNOWLEDGED,
        )
        await reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="test-001",
        )

        # --- Assert: audit entries ---
        audit_logs = await repos.audit_logs.list_by_correlation_id(
            sample_order.correlation_id
        )

        status_change_entries = [
            e
            for e in audit_logs
            if e.action == "order.status_change"
        ]
        # At minimum: PENDING_SUBMIT → RECONCILE_REQUIRED (1 entry)
        assert len(status_change_entries) >= 1

        # Verify reconciliation run was resolved
        resolved_run = await repos.reconciliations.get_run(
            active_run.reconciliation_run_id
        )
        assert resolved_run is not None
        assert resolved_run.status == "resolved"
        assert resolved_run.summary_json is not None
        assert resolved_run.summary_json.get("resolved_via") == "broker_inquiry"


# ======================================================================
# Category 2: Known Gap Characterization
# ======================================================================


class TestWsFullFillOnReconcileRequiredCurrentlyAllowedKnownGap:
    """Test B: KNOWN GAP — ``FILLED`` is currently allowed from
    ``RECONCILE_REQUIRED``.

    ╔══════════════════════════════════════════════════════════════════╗
    ║  THIS IS NOT A SAFETY VERIFICATION TEST.                       ║
    ║  It characterizes CURRENT BEHAVIOR, which is known to differ   ║
    ║  from production-safe semantics.                               ║
    ╚══════════════════════════════════════════════════════════════════╝

    Current state
    -------------
    ``_ALLOWED_TRANSITIONS[RECONCILE_REQUIRED]`` includes ``FILLED``
    (see ``order_manager.py`` lines 62–97).  This means a WS full-fill
    notification CAN transition an order out of ``RECONCILE_REQUIRED``
    into ``FILLED``, effectively bypassing the reconciliation process.

    Why this is acceptable (for now)
    ---------------------------------
    1. The fill data is always persisted (append-only ingest).
    2. The reconciliation run still exists for audit/review.
    3. The lock is released when reconciliation is resolved.

    Why this is a known gap for production safety
    ----------------------------------------------
    1. A full fill during reconciliation means the system accepted a
       broker state transition without completing reconciliation.
    2. If the reconciliation would have detected a mismatch, the full
       fill consumes that mismatch silently.
    3. Future work should revisit whether ``FILLED`` should be removed
       from ``_ALLOWED_TRANSITIONS[RECONCILE_REQUIRED]``.

    See Also
    --------
    * ``plans/33_post_submit_reconciliation_boundary.md`` §6.1
    * ``order_manager._ALLOWED_TRANSITIONS``
    """

    # ------------------------------------------------------------------
    # 2a. Direct state machine — transition succeeds (known gap)
    # ------------------------------------------------------------------

    async def test_full_fill_transition_from_reconcile_required_succeeds(
        self,
        repos,
        manager: OrderManager,
    ) -> None:
        """RECONCILE_REQUIRED → FILLED is currently allowed (known gap).

        Verifies that the state machine accepts this transition.
        This documents the current behavior, NOT a safety guarantee.
        """
        order = await _create_order(repos, status=OrderStatus.RECONCILE_REQUIRED)

        updated = await manager.transition_to(
            order,
            OrderStatus.FILLED,
            reason_code="WS_FILL",
            reason_message="Full fill during reconciliation (known gap)",
        )

        assert updated.status == OrderStatus.FILLED

    # ------------------------------------------------------------------
    # 2b. Event loop path — full fill goes through (known gap)
    # ------------------------------------------------------------------

    async def test_event_loop_full_fill_on_reconcile_required_allowed(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_adapter: MagicMock,
    ) -> None:
        """Event loop: full fill notification transitions order from
        RECONCILE_REQUIRED to FILLED (known gap — currently allowed).

        This characterizes current behavior.  The transition succeeds
        but reconciliation data is preserved for audit/review.
        """
        # --- Arrange ---
        account_id = uuid4()
        order = await _create_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            account_id=account_id,
        )

        broker_order = BrokerOrderEntity(
            broker_order_id=uuid4(),
            order_request_id=order.order_request_id,
            broker_name="koreainvestment",
            broker_status="reconcile_required",
            broker_native_order_id="KIS12345678",
            created_at=datetime.now(timezone.utc),
        )
        await repos.broker_orders.add(broker_order)

        event_loop = _build_event_loop(
            mock_adapter, manager, reconciliation_service, repos
        )

        # Full fill: filled_qty=10 >= order_qty=10
        data = {
            "broker_order_id": "KIS12345678",
            "stock_code": "005930",
            "filled_qty": "10",
            "filled_price": "50000",
            "filled_time": "143025",
            "side": OrderSide.BUY,
            "order_qty": "10",
        }

        # --- Act ---
        await event_loop._handle_fill_notification(data)

        # --- Assert ---

        # ExternalEvent persisted
        ext_event = await repos.external_events.find_by_dedup_key(
            "fill:KIS12345678:143025"
        )
        assert ext_event is not None, "ExternalEvent should be persisted"
        assert ext_event.dedup_key_hash == "fill:KIS12345678:143025"

        # FillEvent persisted
        # Note: FillEventEntity.broker_order_id stores the local order_request_id
        fill_events = await repos.fill_events.list_by_broker_order(
            order.order_request_id
        )
        assert len(fill_events) == 1

        # Order transitioned to FILLED (known gap — currently allowed)
        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.FILLED, (
            f"Known gap: RECONCILE_REQUIRED → FILLED is currently allowed. "
            f"Order status = {updated_order.status}"
        )


# ======================================================================
# Fixtures required by test classes using the submit path
# ======================================================================


@pytest.fixture
async def sample_order(repos) -> OrderRequestEntity:
    """Create a sample order in PENDING_SUBMIT status, persisted in repos."""
    account_id = uuid4()
    instrument_id = uuid4()
    now = datetime.now(timezone.utc)

    order = OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id="test-001",
        idempotency_key="ik-test-001",
        correlation_id="corr-unknown-state",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        requested_quantity=Decimal("10"),
        status=OrderStatus.PENDING_SUBMIT,
        requested_price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
        created_at=now,
        updated_at=now,
    )
    await repos.orders.add(order)
    return order
