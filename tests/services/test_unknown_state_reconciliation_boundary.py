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
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    AuditLogEntity,
    BrokerOrderEntity,
    FillEventEntity,
    ExternalEventEntity,
    OrderRequestEntity,
    ReconciliationRunEntity,
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

    # ------------------------------------------------------------------
    # Plan 35: Authoritative state reflection via resolve_and_mark()
    # ------------------------------------------------------------------

    async def test_resolve_and_mark_reflects_authoritative_state(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """resolve_and_mark() with order_manager reflects order state."""
        # --- Step 1: Submit with uncertain result ---
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

        active_run = await reconciliation_service.get_active_run(
            sample_order.account_id
        )
        assert active_run is not None
        assert active_run.status == "started"

        # --- Step 2: Broker inquiry returns ACKNOWLEDGED ---
        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id="BRK-001",
            status=OrderStatus.ACKNOWLEDGED,
        )

        # --- Step 3: resolve_and_mark with order_manager ---
        await reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="test-001",
            order_manager=manager,
        )

        # --- Step 4: Order state reflected ---
        updated = await repos.orders.get(sample_order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.ACKNOWLEDGED, (
            f"Expected order state reflected to ACKNOWLEDGED, "
            f"got {updated.status}"
        )

        # --- Step 5: Reconciliation run resolved ---
        resolved_run = await repos.reconciliations.get_run(
            active_run.reconciliation_run_id
        )
        assert resolved_run is not None
        assert resolved_run.status == "resolved"

    async def test_resolve_and_mark_preserves_audit_trail(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """State reflection produces order_state_event with reason_code='RECONCILE_RESOLVED'."""
        # --- Step 1: Submit with uncertain result ---
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
        await manager.submit_order_to_broker(
            sample_order, mock_broker, submit_request
        )

        active_run = await reconciliation_service.get_active_run(
            sample_order.account_id
        )
        assert active_run is not None

        # --- Step 2: Broker returns FILLED ---
        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id="BRK-001",
            status=OrderStatus.FILLED,
        )

        # --- Step 3: resolve_and_mark with order_manager ---
        await reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="test-001",
            order_manager=manager,
        )

        # --- Step 4: Verify order_state_event ---
        events = await repos.order_state_events.list_by_order_request(
            sample_order.order_request_id
        )
        assert len(events) >= 1
        assert events[-1].reason_code == "RECONCILE_RESOLVED"
        assert events[-1].new_status == OrderStatus.FILLED

    async def test_resolve_and_mark_handles_unresolved_status(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """Ambiguous broker status -> run stays started, lock stays held."""
        # --- Step 1: Submit with uncertain result ---
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
        await manager.submit_order_to_broker(
            sample_order, mock_broker, submit_request
        )

        active_run = await reconciliation_service.get_active_run(
            sample_order.account_id
        )
        assert active_run is not None
        assert active_run.status == "started"

        # Lock is held
        locked = await reconciliation_service.is_blocked(
            account_id=sample_order.account_id,
            symbol=submit_request.symbol,
            side=submit_request.side.value,
        )
        assert locked is True

        # --- Step 2: Broker returns RECONCILE_REQUIRED (ambiguous) ---
        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id=None,
            status=OrderStatus.RECONCILE_REQUIRED,
        )

        # --- Step 3: resolve_and_mark with order_manager ---
        await reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="test-001",
            order_manager=manager,
        )

        # --- Step 4: Run still "started" ---
        run_after = await repos.reconciliations.get_run(
            active_run.reconciliation_run_id
        )
        assert run_after is not None
        assert run_after.status == "started", (
            f"Expected run status 'started' for ambiguous broker result, "
            f"got '{run_after.status}'"
        )

        # --- Step 5: Lock still held ---
        locked_after = await reconciliation_service.is_blocked(
            account_id=sample_order.account_id,
            symbol=submit_request.symbol,
            side=submit_request.side.value,
        )
        assert locked_after is True, (
            "Expected lock to remain held when broker returns ambiguous status"
        )

        # --- Step 6: Order state NOT transitioned ---
        updated = await repos.orders.get(sample_order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.RECONCILE_REQUIRED


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
# Test F: Reconciliation Authoritative State Reflection (Plan 35)
# ======================================================================


class TestReconciliationAuthoritativeStateReflection:
    """Test F: Reconciliation authoritative state reflection (Plan 35).

    Verifies that ``resolve_and_mark()`` with ``order_manager`` reflects
    each authoritative broker status to the local ``OrderRequestEntity``
    via ``transition_to_authoritative()``.

    Authoritative status set
    ------------------------
    FILLED, ACKNOWLEDGED, CANCELLED, REJECTED, EXPIRED

    Reflection failure behavior
    ---------------------------
    When ``transition_to_authoritative()`` fails, the reconciliation run
    is set to ``"reflection_failed"``, the lock remains held, and the
    error is recorded in ``summary_json["reflection_error"]``.
    """

    # ------------------------------------------------------------------
    # 5a. FILLED reflection
    # ------------------------------------------------------------------

    async def test_full_fill_reflected_after_reconciliation(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """Broker resolves FILLED -> order state reflected to FILLED."""
        # --- Arrange: submit with uncertain result ---
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
        await manager.submit_order_to_broker(
            sample_order, mock_broker, submit_request
        )
        active_run = await reconciliation_service.get_active_run(
            sample_order.account_id
        )
        assert active_run is not None
        assert active_run.status == "started"

        # --- Act: broker resolves FILLED ---
        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id="BRK-001",
            status=OrderStatus.FILLED,
        )

        await reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="test-001",
            order_manager=manager,
        )

        # --- Assert: order state reflected to FILLED ---
        updated = await repos.orders.get(sample_order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.FILLED

        # Run resolved
        resolved_run = await repos.reconciliations.get_run(
            active_run.reconciliation_run_id
        )
        assert resolved_run is not None
        assert resolved_run.status == "resolved"
        assert resolved_run.summary_json.get("resolved_status") == "filled"

    # ------------------------------------------------------------------
    # 5b. ACKNOWLEDGED reflection
    # ------------------------------------------------------------------

    async def test_acknowledged_reflected_after_reconciliation(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """Broker resolves ACKNOWLEDGED -> order state reflected to ACKNOWLEDGED."""
        # --- Arrange: submit with uncertain result ---
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
        await manager.submit_order_to_broker(
            sample_order, mock_broker, submit_request
        )
        active_run = await reconciliation_service.get_active_run(
            sample_order.account_id
        )
        assert active_run is not None
        assert active_run.status == "started"

        # --- Act: broker resolves ACKNOWLEDGED ---
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
            order_manager=manager,
        )

        # --- Assert: order state reflected to ACKNOWLEDGED ---
        updated = await repos.orders.get(sample_order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.ACKNOWLEDGED

    # ------------------------------------------------------------------
    # 5c. CANCELLED reflection
    # ------------------------------------------------------------------

    async def test_cancelled_reflected_after_reconciliation(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """Broker resolves CANCELLED -> order state reflected to CANCELLED."""
        # --- Arrange: submit with uncertain result ---
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
        await manager.submit_order_to_broker(
            sample_order, mock_broker, submit_request
        )
        active_run = await reconciliation_service.get_active_run(
            sample_order.account_id
        )
        assert active_run is not None
        assert active_run.status == "started"

        # --- Act: broker resolves CANCELLED ---
        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id="BRK-001",
            status=OrderStatus.CANCELLED,
        )

        await reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="test-001",
            order_manager=manager,
        )

        # --- Assert: order state reflected to CANCELLED ---
        updated = await repos.orders.get(sample_order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.CANCELLED

    # ------------------------------------------------------------------
    # 5d. REJECTED reflection
    # ------------------------------------------------------------------

    async def test_rejected_reflected_after_reconciliation(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """Broker resolves REJECTED -> order state reflected to REJECTED."""
        # --- Arrange: submit with uncertain result ---
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
        await manager.submit_order_to_broker(
            sample_order, mock_broker, submit_request
        )
        active_run = await reconciliation_service.get_active_run(
            sample_order.account_id
        )
        assert active_run is not None
        assert active_run.status == "started"

        # --- Act: broker resolves REJECTED ---
        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id="BRK-001",
            status=OrderStatus.REJECTED,
        )

        await reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="test-001",
            order_manager=manager,
        )

        # --- Assert: order state reflected to REJECTED ---
        updated = await repos.orders.get(sample_order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.REJECTED

    # ------------------------------------------------------------------
    # 5e. EXPIRED reflection
    # ------------------------------------------------------------------

    async def test_expired_reflected_after_reconciliation(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """Broker resolves EXPIRED -> order state reflected to EXPIRED."""
        # --- Arrange: submit with uncertain result ---
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
        await manager.submit_order_to_broker(
            sample_order, mock_broker, submit_request
        )
        active_run = await reconciliation_service.get_active_run(
            sample_order.account_id
        )
        assert active_run is not None
        assert active_run.status == "started"

        # --- Act: broker resolves EXPIRED ---
        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id="BRK-001",
            status=OrderStatus.EXPIRED,
        )

        await reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="test-001",
            order_manager=manager,
        )

        # --- Assert: order state reflected to EXPIRED ---
        updated = await repos.orders.get(sample_order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.EXPIRED

    # ------------------------------------------------------------------
    # 5f. Reflection failure — run stays, lock stays
    # ------------------------------------------------------------------

    async def test_reflection_failure_keeps_run_and_lock(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_order,
        submit_request: SubmitOrderRequest,
    ) -> None:
        """Reflection failure -> run='reflection_failed', lock stays held, error recorded."""
        # --- Arrange: submit with uncertain result ---
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
        await manager.submit_order_to_broker(
            sample_order, mock_broker, submit_request
        )
        active_run = await reconciliation_service.get_active_run(
            sample_order.account_id
        )
        assert active_run is not None
        assert active_run.status == "started"

        # Lock is held
        locked = await reconciliation_service.is_blocked(
            account_id=sample_order.account_id,
            symbol=submit_request.symbol,
            side=submit_request.side.value,
        )
        assert locked is True

        # Broker resolves FILLED
        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-001",
            broker_order_id="BRK-001",
            status=OrderStatus.FILLED,
        )

        # --- Act: make transition_to_authoritative() fail via class-level mock ---
        # NOTE: OrderManager is @dataclass(slots=True), so instance-level
        # mock.patch.object() fails (slots attributes are read-only).
        # We mock at the CLASS level (OrderManager) instead, which works
        # because class attributes are always writable.
        with patch.object(
            OrderManager,
            "transition_to_authoritative",
            new=AsyncMock(side_effect=RuntimeError("Simulated transition failure")),
        ):
            await reconciliation_service.resolve_and_mark(
                reconciliation_run_id=active_run.reconciliation_run_id,
                account_ref="test_account",
                broker=mock_broker,
                client_order_id="test-001",
                order_manager=manager,
            )

        # --- Assert: run status is "reflection_failed" ---
        run_after = await repos.reconciliations.get_run(
            active_run.reconciliation_run_id
        )
        assert run_after is not None
        assert run_after.status == "reflection_failed", (
            f"Expected 'reflection_failed', got '{run_after.status}'"
        )

        # summary_json contains reflection_error
        assert run_after.summary_json is not None
        assert "reflection_error" in run_after.summary_json
        assert "Simulated transition failure" in run_after.summary_json["reflection_error"]
        assert run_after.summary_json.get("resolved_status") == "filled"

        # Lock still held
        locked_after = await reconciliation_service.is_blocked(
            account_id=sample_order.account_id,
            symbol=submit_request.symbol,
            side=submit_request.side.value,
        )
        assert locked_after is True, (
            "Expected lock to remain held after reflection failure"
        )

        # Order state NOT transitioned
        updated = await repos.orders.get(sample_order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.RECONCILE_REQUIRED


# ======================================================================
# Category 2: Safety Verification — Fill Data Preserved, State Held
# ======================================================================


class TestWsFullFillOnReconcileRequiredFillDataPreservedStateHeld:
    """Test B: SAFETY VERIFICATION — WS fill on RECONCILE_REQUIRED must
    preserve fill data AND hold order state progression.

    Core principle (Plan 34)
    ------------------------
    When a WS fill notification arrives for an order in RECONCILE_REQUIRED
    state, the system MUST:

    1. Persist all fill data (ExternalEvent + FillEvent) — data preserved
    2. NOT transition the order state — state progression held
    3. Wait for reconciliation to resolve the authoritative result

    Why two layers of protection?
    -----------------------------
    - ``_ALLOWED_TRANSITIONS`` (state machine): hard boundary — removes
      ``FILLED`` from ``RECONCILE_REQUIRED`` transitions. Catches ALL
      paths (current and future).
    - ``_handle_fill_notification`` (event loop guard): explicit guard
      with clear warning logging before transition_to(). Avoids
      exception-as-control-flow anti-pattern.

    Design Decision
    ---------------
    Both layers are needed because the state machine raises an exception
    (``InvalidStateTransitionError``), which is caught generically in the
    event loop's exception handler.  The explicit guard ensures the
    behavior is intentional and logged clearly, not an accidental
    exception swallow.

    See Also
    --------
    * ``plans/34_reconcile_required_fill_transition_policy.md``
    * ``order_manager._ALLOWED_TRANSITIONS``
    """

    # ------------------------------------------------------------------
    # 2a. Direct state machine — transition raises error
    # ------------------------------------------------------------------

    async def test_reconcile_required_to_filled_state_machine_blocked(
        self,
        repos,
        manager: OrderManager,
    ) -> None:
        """State machine blocks RECONCILE_REQUIRED → FILLED.

        Fill data is preserved by the caller; state progression is held
        until reconciliation resolves the authoritative result.
        """
        order = await _create_order(repos, status=OrderStatus.RECONCILE_REQUIRED)

        with pytest.raises(InvalidStateTransitionError):
            await manager.transition_to(
                order,
                OrderStatus.FILLED,
                reason_code="WS_FILL",
                reason_message="Full fill during reconciliation (blocked by Plan 34)",
            )

    # ------------------------------------------------------------------
    # 2b. Event loop path — full fill data preserved, state held
    # ------------------------------------------------------------------

    async def test_ws_full_fill_on_reconcile_required_data_preserved_state_held(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_adapter: MagicMock,
    ) -> None:
        """Event loop: full fill data preserved, order stays RECONCILE_REQUIRED.

        Verifies the core principle: fill data (ExternalEvent + FillEvent)
        is persisted, but order state progression is held until
        reconciliation resolves.
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

        # --- Assert: fill data preserved ---

        # ExternalEvent persisted
        ext_event = await repos.external_events.find_by_dedup_key(
            "fill:KIS12345678:143025"
        )
        assert ext_event is not None, "ExternalEvent should be persisted"
        assert ext_event.dedup_key_hash == "fill:KIS12345678:143025"

        # FillEvent persisted
        fill_events = await repos.fill_events.list_by_broker_order(
            order.order_request_id
        )
        assert len(fill_events) == 1

        # --- Assert: state progression held ---
        # Order MUST remain in RECONCILE_REQUIRED — NOT transitioned to FILLED
        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.RECONCILE_REQUIRED, (
            f"Fill data preserved, state progression held. "
            f"Expected RECONCILE_REQUIRED, got {updated_order.status}"
        )

    # ------------------------------------------------------------------
    # 2c. Event loop path — partial fill also blocked
    # ------------------------------------------------------------------

    async def test_ws_partial_fill_on_reconcile_required_data_preserved_state_held(
        self,
        repos,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_adapter: MagicMock,
    ) -> None:
        """Event loop: partial fill data preserved, order stays RECONCILE_REQUIRED.

        Even a partial fill during reconciliation must not optimistically
        progress the order state. Fill data is persisted for reconciliation
        to use when resolving the authoritative result.
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
            broker_native_order_id="KIS87654321",
            created_at=datetime.now(timezone.utc),
        )
        await repos.broker_orders.add(broker_order)

        event_loop = _build_event_loop(
            mock_adapter, manager, reconciliation_service, repos
        )

        # Partial fill: filled_qty=3 < order_qty=10
        data = {
            "broker_order_id": "KIS87654321",
            "stock_code": "005930",
            "filled_qty": "3",
            "filled_price": "50000",
            "filled_time": "143025",
            "side": OrderSide.BUY,
            "order_qty": "10",
        }

        # --- Act ---
        await event_loop._handle_fill_notification(data)

        # --- Assert: fill data preserved ---

        # ExternalEvent persisted
        ext_event = await repos.external_events.find_by_dedup_key(
            "fill:KIS87654321:143025"
        )
        assert ext_event is not None, "ExternalEvent should be persisted"
        assert ext_event.dedup_key_hash == "fill:KIS87654321:143025"

        # FillEvent persisted
        fill_events = await repos.fill_events.list_by_broker_order(
            order.order_request_id
        )
        assert len(fill_events) == 1
        assert fill_events[0].fill_quantity == Decimal("3")

        # --- Assert: state progression held ---
        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.RECONCILE_REQUIRED, (
            f"Partial fill data preserved, state progression held. "
            f"Expected RECONCILE_REQUIRED, got {updated_order.status}"
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
