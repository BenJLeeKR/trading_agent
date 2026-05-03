from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import OrderRequestEntity
from agent_trading.domain.enums import (
    BrokerName,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.domain.models import SubmitOrderRequest, SubmitOrderResult
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.reconciliation_service import ReconciliationService


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
    return broker


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
        correlation_id="corr-001",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        requested_quantity=Decimal("10"),
        status=OrderStatus.PENDING_SUBMIT,
        requested_price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
        created_at=now,
        updated_at=now,
    )
    # Persist the order so transition_to() can find it.
    await repos.orders.add(order)
    return order


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


@pytest.mark.asyncio
async def test_submit_normal_path(manager, mock_broker, sample_order, submit_request):
    """Normal path: broker accepts → order transitions to SUBMITTED."""
    mock_broker.submit_order.return_value = SubmitOrderResult(
        accepted=True,
        broker_name=BrokerName.KOREA_INVESTMENT,
        client_order_id="test-001",
        broker_order_id="BRK-001",
        broker_status=OrderStatus.ACKNOWLEDGED,
        ack_timestamp=datetime.now(timezone.utc),
        raw_code="0000",
        raw_message="Accepted",
    )

    result = await manager.submit_order_to_broker(
        sample_order, mock_broker, submit_request
    )

    assert result.status == OrderStatus.SUBMITTED
    mock_broker.submit_order.assert_awaited_once_with(submit_request)


@pytest.mark.asyncio
async def test_submit_uncertain_triggers_reconciliation(
    manager, mock_broker, sample_order, submit_request
):
    """Uncertain result → order transitions to RECONCILE_REQUIRED."""
    mock_broker.submit_order.return_value = SubmitOrderResult(
        accepted=True,
        broker_name=BrokerName.KOREA_INVESTMENT,
        client_order_id="test-001",
        broker_order_id=None,  # Missing broker_order_id → uncertain
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
    assert result.status_reason_code == "TIMEOUT"


@pytest.mark.asyncio
async def test_submit_requires_reconciliation(
    manager, mock_broker, sample_order, submit_request
):
    """requires_reconciliation result → order transitions to RECONCILE_REQUIRED."""
    mock_broker.submit_order.return_value = SubmitOrderResult(
        accepted=False,
        broker_name=BrokerName.KOREA_INVESTMENT,
        client_order_id="test-001",
        broker_order_id=None,
        broker_status=OrderStatus.RECONCILE_REQUIRED,
        ack_timestamp=None,
        raw_code="NETWORK_ERROR",
        raw_message="Network timeout",
        uncertain=False,
        requires_reconciliation=True,
    )

    result = await manager.submit_order_to_broker(
        sample_order, mock_broker, submit_request
    )

    assert result.status == OrderStatus.RECONCILE_REQUIRED
    assert result.status_reason_code == "NETWORK_ERROR"


@pytest.mark.asyncio
async def test_submit_rejected(manager, mock_broker, sample_order, submit_request):
    """Broker explicitly rejects → order transitions to REJECTED (terminal)."""
    mock_broker.submit_order.return_value = SubmitOrderResult(
        accepted=False,
        broker_name=BrokerName.KOREA_INVESTMENT,
        client_order_id="test-001",
        broker_order_id=None,
        broker_status=OrderStatus.REJECTED,
        ack_timestamp=None,
        raw_code="REJECTED",
        raw_message="Insufficient cash",
        uncertain=False,
        requires_reconciliation=False,
    )

    result = await manager.submit_order_to_broker(
        sample_order, mock_broker, submit_request
    )

    # Broker rejection without uncertain/requires_reconciliation flags
    # goes to REJECTED (terminal state).
    assert result.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_submit_blocked_by_reconciliation_lock(
    repos, mock_broker, sample_order, submit_request
):
    """Blocking lock prevents submission → order goes to RECONCILE_REQUIRED."""
    # Create a reconciliation service and acquire a lock first.
    reconciliation_service = ReconciliationService(repos)
    await reconciliation_service.acquire_blocking_lock(
        account_id=sample_order.account_id,
        symbol=submit_request.symbol,
        side=submit_request.side.value,
        reason="test_lock",
        locked_by_run_id=uuid4(),
    )

    manager = OrderManager(
        repos=repos,
        reconciliation_service=reconciliation_service,
    )

    result = await manager.submit_order_to_broker(
        sample_order, mock_broker, submit_request
    )

    # The broker should NOT have been called.
    mock_broker.submit_order.assert_not_called()
    assert result.status == OrderStatus.RECONCILE_REQUIRED
    assert result.status_reason_code == "BLOCKED"


@pytest.mark.asyncio
async def test_submit_without_reconciliation_service(
    repos, mock_broker, sample_order, submit_request
):
    """Without reconciliation_service, submission proceeds normally."""
    manager = OrderManager(repos=repos, reconciliation_service=None)

    mock_broker.submit_order.return_value = SubmitOrderResult(
        accepted=True,
        broker_name=BrokerName.KOREA_INVESTMENT,
        client_order_id="test-001",
        broker_order_id="BRK-001",
        broker_status=OrderStatus.ACKNOWLEDGED,
        ack_timestamp=datetime.now(timezone.utc),
        raw_code="0000",
        raw_message="Accepted",
    )

    result = await manager.submit_order_to_broker(
        sample_order, mock_broker, submit_request
    )

    assert result.status == OrderStatus.SUBMITTED
    mock_broker.submit_order.assert_awaited_once()
