from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.brokers.errors import BrokerError
from agent_trading.domain.entities import (
    AccountEntity,
    InstrumentEntity,
    OrderRequestEntity,
)
from agent_trading.domain.enums import (
    BrokerName,
    BrokerErrorType,
    Environment,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.domain.models import SubmitOrderRequest, SubmitOrderResult
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
    OrderIntent,
)
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
async def test_submit_normal_path(repos, manager, mock_broker, sample_order, submit_request):
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
    assert result.submitted_at is not None
    mock_broker.submit_order.assert_awaited_once_with(submit_request)

    # 저장 row 검증
    attempts = await repos.order_submission_attempts.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(attempts) == 1
    assert attempts[0].accepted is True
    assert attempts[0].broker_native_order_id == "BRK-001"

    persisted = await repos.orders.get(sample_order.order_request_id)
    assert persisted is not None
    assert persisted.submitted_at is not None


@pytest.mark.asyncio
async def test_submit_uncertain_triggers_reconciliation(
    repos, manager, mock_broker, sample_order, submit_request
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

    # 저장 row 검증
    attempts = await repos.order_submission_attempts.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(attempts) == 1
    assert attempts[0].accepted is True  # uncertain 플래그와 accepted는 독립적

    persisted = await repos.orders.get(sample_order.order_request_id)
    assert persisted is not None
    assert persisted.submitted_at is not None


@pytest.mark.asyncio
async def test_submit_requires_reconciliation(
    repos, manager, mock_broker, sample_order, submit_request
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

    # 저장 row 검증
    attempts = await repos.order_submission_attempts.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(attempts) == 1
    assert attempts[0].accepted is False  # requires_reconciliation일 때 accepted=False 일반적

    persisted = await repos.orders.get(sample_order.order_request_id)
    assert persisted is not None
    assert persisted.submitted_at is not None


@pytest.mark.asyncio
async def test_submit_rejected(repos, manager, mock_broker, sample_order, submit_request):
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
    assert result.submitted_at is not None

    # 저장 row 검증
    attempts = await repos.order_submission_attempts.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(attempts) == 1
    assert attempts[0].accepted is False

    persisted = await repos.orders.get(sample_order.order_request_id)
    assert persisted is not None
    assert persisted.submitted_at is not None


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

    # lock blocked는 broker 제출이 차단되므로 저장 row가 없어야 정상
    attempts = await repos.order_submission_attempts.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(attempts) == 0  # 저장되지 않음


@pytest.mark.asyncio
async def test_submit_broker_exception_records_attempt(
    repos,
    manager,
    mock_broker,
    sample_order,
    submit_request,
):
    """Broker가 예외를 raise하면 order_submission_attempts에 error_type이 저장되어야 함."""
    # Given: broker가 예외를 발생시킴
    mock_broker.submit_order.side_effect = ValueError("KIS API connection error")

    # When: submit 실패 (예외 전파)
    with pytest.raises(ValueError, match="KIS API connection error"):
        await manager.submit_order_to_broker(
            order=sample_order,
            broker=mock_broker,
            request=submit_request,
        )

    # Then: 저장 row가 1건 생성되고 error_type이 기록됨
    attempts = await repos.order_submission_attempts.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(attempts) == 1, "예외 경로에서도 저장 row가 생성되어야 함"
    assert attempts[0].accepted is False, "예외 시 accepted는 False"
    assert attempts[0].error_type == "ValueError", "error_type에 예외 클래스명이 기록되어야 함"
    assert attempts[0].duration_ms is not None, "duration_ms가 기록되어야 함"


@pytest.mark.asyncio
async def test_submit_broker_error_rejected_transitions_terminal(
    repos, manager, mock_broker, sample_order, submit_request
):
    """명확한 BrokerError는 pending_submit에 남기지 않고 즉시 REJECTED 처리."""
    mock_broker.submit_order.side_effect = BrokerError(
        broker_name=BrokerName.KOREA_INVESTMENT,
        error_type=BrokerErrorType.ORDER_REJECTED,
        retryable=False,
        raw_code="IGW00007",
        raw_message="KIS order_cash: HTTP 500 (msg_cd=IGW00007): MCA 전문바디 구성 중 오류가 발생하였습니다.",
    )

    result = await manager.submit_order_to_broker(
        order=sample_order,
        broker=mock_broker,
        request=submit_request,
    )

    assert result.status == OrderStatus.REJECTED
    assert result.status_reason_code == "IGW00007"
    attempts = await repos.order_submission_attempts.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(attempts) == 1
    assert attempts[0].accepted is False
    assert attempts[0].error_type == "BrokerError"


@pytest.mark.asyncio
async def test_submit_broker_error_reconcile_required_transitions_immediately(
    repos, manager, mock_broker, sample_order, submit_request
):
    """모호한 BrokerError는 즉시 RECONCILE_REQUIRED로 전이하고 lock을 건다."""
    mock_broker.submit_order.side_effect = BrokerError(
        broker_name=BrokerName.KOREA_INVESTMENT,
        error_type=BrokerErrorType.API_ERROR,
        retryable=False,
        raw_code="TIMEOUT",
        raw_message="Broker submit timed out",
        requires_reconciliation=True,
        blocks_new_orders=True,
    )

    result = await manager.submit_order_to_broker(
        order=sample_order,
        broker=mock_broker,
        request=submit_request,
    )

    assert result.status == OrderStatus.RECONCILE_REQUIRED
    assert result.status_reason_code == "TIMEOUT"
    attempts = await repos.order_submission_attempts.list_by_order_request(
        sample_order.order_request_id
    )
    assert len(attempts) == 1
    assert attempts[0].accepted is False


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


# ---------------------------------------------------------------------------
# Plan 32: AI-Broker Pre-Submit Safety Boundary — Test B
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_request_only_passed_to_broker(
    repos, reconciliation_service, mock_broker, sample_order, submit_request
):
    """intent.request (SubmitOrderRequest) reaches broker, not the full OrderIntent.

    This verifies that:
    1. ``assemble()`` populates ``ai_backend_inputs`` on the ``OrderIntent``.
    2. But only ``intent.request`` (a ``SubmitOrderRequest``) is passed to the
       broker — the ``OrderIntent`` wrapper, including ``ai_backend_inputs``,
       never reaches the execution boundary.
    """
    service = DecisionOrchestratorService(repos=repos)

    # --- assemble() returns OrderIntent with populated ai_backend_inputs ---
    intent = await service.assemble(submit_request)

    # ai_backend_inputs is populated (stub agents produce deterministic defaults)
    assert intent.ai_backend_inputs is not None
    assert intent.ai_backend_inputs.decision_type == "HOLD"
    assert isinstance(intent.request, SubmitOrderRequest)

    # intent.request is a plain SubmitOrderRequest — no ai_backend_inputs field
    assert not hasattr(intent.request, "ai_backend_inputs")

    # --- Submit via OrderManager sharing the same repos ---
    manager = OrderManager(
        repos=repos,
        reconciliation_service=reconciliation_service,
    )

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
        sample_order, mock_broker, intent.request
    )

    assert result.status == OrderStatus.SUBMITTED

    # Broker received intent.request (SubmitOrderRequest) — NOT the OrderIntent.
    # This proves ai_backend_inputs stayed on the OrderIntent side of the boundary.
    mock_broker.submit_order.assert_awaited_once_with(intent.request)


# ---------------------------------------------------------------------------
# Plan 32: AI-Broker Pre-Submit Safety Boundary — Test C
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciliation_lock_blocks_submission_after_uncertain(
    manager, repos, reconciliation_service, mock_broker, sample_order, submit_request
):
    """Uncertain result creates a lock; second submit is blocked; broker called once.

    This verifies the reconciliation-first principle:
    1. First submit with ``uncertain=True`` → order transitions to
       ``RECONCILE_REQUIRED`` and a blocking lock is acquired.
    2. Second submit (new order, same account) → blocked by lock →
       ``RECONCILE_REQUIRED`` without calling the broker.
    3. ``mock_broker.submit_order.call_count == 1`` — the second submit
       never reaches the broker.
    """
    # --- First submit: uncertain → RECONCILE_REQUIRED + lock acquired ---
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

    result1 = await manager.submit_order_to_broker(
        sample_order, mock_broker, submit_request
    )

    assert result1.status == OrderStatus.RECONCILE_REQUIRED
    assert result1.status_reason_code == "TIMEOUT"
    assert mock_broker.submit_order.call_count == 1  # First submit reached broker

    # --- Create a second order with the SAME account_id in PENDING_SUBMIT ---
    now = datetime.now(timezone.utc)
    second_order = OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=sample_order.account_id,  # Same account → same lock scope
        instrument_id=sample_order.instrument_id,
        client_order_id="test-002",
        idempotency_key="ik-test-002",
        correlation_id="corr-002",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        requested_quantity=Decimal("10"),
        status=OrderStatus.PENDING_SUBMIT,
        requested_price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
        created_at=now,
        updated_at=now,
    )
    await repos.orders.add(second_order)

    # Reset the mock return value (does not affect call_count)
    # The second submit should be blocked by the reconciliation lock.
    result2 = await manager.submit_order_to_broker(
        second_order, mock_broker, submit_request
    )

    # Second submit was blocked by lock — broker NOT called again
    assert result2.status == OrderStatus.RECONCILE_REQUIRED
    assert result2.status_reason_code == "BLOCKED"
    assert mock_broker.submit_order.call_count == 1, (
        f"Expected call_count=1 (blocked), got {mock_broker.submit_order.call_count}"
    )
