"""
Phase 6 Subtask 5: 성공/거절/예외 시나리오 검증

order_manager.submit_order_to_broker()의 3개 경로가
모두 _record_submission_attempt()를 호출하는지 검증

NOTE: OrderManager는 @dataclass(slots=True)이므로 인스턴스 레벨
patch.object 사용 불가 → 클래스 레벨 patch.object 사용
"""
import uuid
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

# ============================================================
# 검증 1: _record_submission_attempt() 단위 테스트 — 성공
# ============================================================

@pytest.mark.asyncio
async def test_record_submission_attempt_success():
    """성공 경로: accepted=True, broker_native_order_id 포함"""
    from agent_trading.domain.entities import OrderSubmissionAttemptEntity
    from agent_trading.repositories.memory import InMemoryOrderSubmissionAttemptRepository
    
    repo = InMemoryOrderSubmissionAttemptRepository()
    order_request_id = uuid.uuid4()
    
    attempt = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=order_request_id,
        attempt_number=1,
        submitted_at=datetime.now(timezone.utc),
        accepted=True,
        broker_name="kis",
        broker_native_order_id="ODNO12345",
        broker_status="00",
        raw_code="0",
        raw_message="success",
        duration_ms=150,
    )
    
    saved = await repo.add(attempt)
    assert saved.accepted == True
    assert saved.broker_native_order_id == "ODNO12345"
    assert saved.broker_status == "00"
    
    listed = await repo.list_by_order_request(order_request_id)
    assert len(listed) == 1
    assert listed[0].attempt_id == attempt.attempt_id
    print("✅ 검증 1: 성공 경로 저장 OK")


@pytest.mark.asyncio
async def test_record_submission_attempt_rejected():
    """거절 경로: accepted=False, raw_code/raw_message 포함"""
    from agent_trading.domain.entities import OrderSubmissionAttemptEntity
    from agent_trading.repositories.memory import InMemoryOrderSubmissionAttemptRepository
    
    repo = InMemoryOrderSubmissionAttemptRepository()
    order_request_id = uuid.uuid4()
    
    attempt = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=order_request_id,
        attempt_number=1,
        submitted_at=datetime.now(timezone.utc),
        accepted=False,
        broker_name="kis",
        broker_native_order_id=None,
        raw_code="VALIDATION_ERROR",
        raw_message="Insufficient cash balance",
        http_status=400,
        duration_ms=50,
    )
    
    saved = await repo.add(attempt)
    assert saved.accepted == False
    assert saved.raw_code == "VALIDATION_ERROR"
    assert saved.http_status == 400
    
    print("✅ 검증 2: 거절 경로 저장 OK")


@pytest.mark.asyncio
async def test_record_submission_attempt_exception():
    """예외 경로: accepted=False, error_type, retryable 포함"""
    from agent_trading.domain.entities import OrderSubmissionAttemptEntity
    from agent_trading.repositories.memory import InMemoryOrderSubmissionAttemptRepository
    
    repo = InMemoryOrderSubmissionAttemptRepository()
    order_request_id = uuid.uuid4()
    
    attempt = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(),
        order_request_id=order_request_id,
        attempt_number=1,
        submitted_at=datetime.now(timezone.utc),
        accepted=False,
        broker_name="kis",
        raw_code="EGW00201",
        raw_message="Rate limit exceeded",
        error_type="RateLimitError",
        retryable=True,
        http_status=429,
        duration_ms=2300,
    )
    
    saved = await repo.add(attempt)
    assert saved.accepted == False
    assert saved.error_type == "RateLimitError"
    assert saved.retryable == True
    assert saved.http_status == 429
    
    print("✅ 검증 3: 예외 경로 저장 OK")


@pytest.mark.asyncio
async def test_multiple_attempts_same_order():
    """동일 order_request_id에 여러 번 시도"""
    from agent_trading.domain.entities import OrderSubmissionAttemptEntity
    from agent_trading.repositories.memory import InMemoryOrderSubmissionAttemptRepository
    
    repo = InMemoryOrderSubmissionAttemptRepository()
    order_request_id = uuid.uuid4()
    
    # 시도 1: 실패 (예외)
    a1 = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(), order_request_id=order_request_id,
        attempt_number=1, submitted_at=datetime.now(timezone.utc),
        accepted=False, error_type="RateLimitError", retryable=True,
    )
    await repo.add(a1)
    
    # 시도 2: 실패 (거절)
    a2 = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(), order_request_id=order_request_id,
        attempt_number=2, submitted_at=datetime.now(timezone.utc),
        accepted=False, raw_code="VALIDATION_ERROR",
    )
    await repo.add(a2)
    
    # 시도 3: 성공
    a3 = OrderSubmissionAttemptEntity(
        attempt_id=uuid.uuid4(), order_request_id=order_request_id,
        attempt_number=3, submitted_at=datetime.now(timezone.utc),
        accepted=True, broker_native_order_id="ODNO999",
    )
    await repo.add(a3)
    
    listed = await repo.list_by_order_request(order_request_id)
    assert len(listed) == 3
    assert [a.attempt_number for a in listed] == [1, 2, 3]
    assert listed[-1].accepted == True
    
    print("✅ 검증 4: 동일 주문 3회 시도 이력 저장 OK")


# ============================================================
# 공통 헬퍼: mock RepositoryContainer 생성
# ============================================================

def _build_mock_repos(with_real_attempts_repo=True):
    """Minimal mock RepositoryContainer for OrderManager tests."""
    from agent_trading.repositories.memory import (
        InMemoryOrderSubmissionAttemptRepository,
        InMemoryOrderRepository,
        InMemoryBrokerOrderRepository,
        InMemoryAuditLogRepository,
    )
    from agent_trading.repositories.container import RepositoryContainer
    
    mock_repos = MagicMock(spec=RepositoryContainer)
    
    if with_real_attempts_repo:
        mock_repos.order_submission_attempts = InMemoryOrderSubmissionAttemptRepository()
    
    mock_repos.orders = InMemoryOrderRepository()
    mock_repos.broker_orders = InMemoryBrokerOrderRepository()
    mock_repos.audit_logs = InMemoryAuditLogRepository()
    
    # Remaining repos: MagicMock (not called in our test paths)
    mock_repos.unit_of_work = MagicMock()
    mock_repos.agent_runs = MagicMock()
    mock_repos.execution_attempts = MagicMock()
    mock_repos.clients = MagicMock()
    mock_repos.accounts = MagicMock()
    mock_repos.strategies = MagicMock()
    mock_repos.config_versions = MagicMock()
    mock_repos.instruments = MagicMock()
    mock_repos.decision_contexts = MagicMock()
    mock_repos.position_snapshots = MagicMock()
    mock_repos.cash_balance_snapshots = MagicMock()
    mock_repos.trade_decisions = MagicMock()
    mock_repos.fill_events = MagicMock()
    mock_repos.reconciliations = MagicMock()
    mock_repos.broker_accounts = MagicMock()
    mock_repos.snapshot_sync_runs = MagicMock()
    mock_repos.order_state_events = MagicMock()
    mock_repos.guardrail_evaluations = MagicMock()
    mock_repos.risk_limit_snapshots = MagicMock()
    mock_repos.external_events = MagicMock()
    mock_repos.market_session_repo = MagicMock()
    
    return mock_repos


def _make_order_request(
    order_request_id=None,
    client_order_id="client-test",
    idempotency_key="idem-test",
    correlation_id="corr-test",
    side=None,
    quantity=Decimal("10"),
    price=Decimal("50000"),
    status=None,
):
    """Helper to create a minimal OrderRequestEntity."""
    from agent_trading.domain.entities import OrderRequestEntity
    from agent_trading.domain.enums import OrderSide, OrderType, TimeInForce, OrderStatus
    
    now = datetime.now(timezone.utc)
    return OrderRequestEntity(
        order_request_id=order_request_id or uuid.uuid4(),
        account_id=uuid.uuid4(),
        instrument_id=uuid.uuid4(),
        client_order_id=client_order_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        side=side or OrderSide.BUY,
        order_type=OrderType.LIMIT,
        requested_quantity=quantity,
        status=status or OrderStatus.PENDING_SUBMIT,
        requested_price=price,
        time_in_force=TimeInForce.DAY,
        submitted_at=None,
        status_reason_code=None,
        status_reason_message=None,
        created_at=now,
        updated_at=now,
    )


def _make_submit_request(
    client_order_id="client-test",
    correlation_id="corr-test",
    side=None,
    quantity=Decimal("10"),
    price=Decimal("50000"),
    symbol="005930",
    market="KRX",
):
    """Helper to create a minimal SubmitOrderRequest."""
    from agent_trading.domain.models import SubmitOrderRequest
    from agent_trading.domain.enums import OrderSide, OrderType, TimeInForce
    return SubmitOrderRequest(
        account_ref="account-001",
        client_order_id=client_order_id,
        correlation_id=correlation_id,
        strategy_id="strat-001",
        symbol=symbol,
        market=market,
        side=side or OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        time_in_force=TimeInForce.DAY,
        price=price,
    )


# ============================================================
# 검증 5: 성공 경로 — accepted=True
# ============================================================

@pytest.mark.asyncio
async def test_order_manager_submit_success_path():
    """
    submit_order_to_broker() 성공 경로:
    broker.submit_order()가 accepted=True 반환
    → _record_submission_attempt(accepted=True, broker_native_order_id=...) 호출
    """
    from agent_trading.domain.enums import OrderSide, OrderStatus, BrokerName
    from agent_trading.domain.models import SubmitOrderResult
    from agent_trading.services.order_manager import OrderManager
    
    mock_repos = _build_mock_repos(with_real_attempts_repo=True)
    om = OrderManager(repos=mock_repos, reconciliation_service=None)
    
    order_request_id = uuid.uuid4()
    order_request = _make_order_request(order_request_id=order_request_id)
    submit_request = _make_submit_request()
    
    # Mock broker adapter: success result
    mock_adapter = AsyncMock()
    mock_adapter.submit_order.return_value = SubmitOrderResult(
        accepted=True,
        broker_name=BrokerName.KOREA_INVESTMENT,
        client_order_id="client-test",
        broker_order_id="ODNO_SUCCESS",
        broker_status=OrderStatus.SUBMITTED,
        ack_timestamp=datetime.now(timezone.utc),
        raw_code="0",
        raw_message="success",
        uncertain=False,
        requires_reconciliation=False,
    )
    
    # 클래스 레벨 patch (slots=True 대응)
    with patch.object(OrderManager, 'transition_to', new_callable=AsyncMock) as mock_transition:
        mock_transition.return_value = order_request
        result = await om.submit_order_to_broker(
            order=order_request,
            broker=mock_adapter,
            request=submit_request,
        )
    
    # transition_to가 PENDING_SUBMIT→SUBMITTED로 호출되었는지 확인
    mock_transition.assert_awaited_once()
    # await_args[0] = positional args tuple, args[1] = target_status
    assert mock_transition.await_args is not None
    pos_args = mock_transition.await_args[0]
    assert pos_args[1] == OrderStatus.SUBMITTED  # target_status (2nd positional arg)
    
    # _record_submission_attempt 호출 확인
    attempts_repo = mock_repos.order_submission_attempts
    attempts = await attempts_repo.list_by_order_request(order_request_id)
    
    assert len(attempts) == 1
    a = attempts[0]
    assert a.accepted == True
    assert a.broker_native_order_id == "ODNO_SUCCESS"
    assert a.broker_status == "submitted"
    assert a.broker_name == BrokerName.KOREA_INVESTMENT.value
    print(f"✅ 검증 5 (성공): accepted={a.accepted}, broker_native_order_id={a.broker_native_order_id}, broker_status={a.broker_status}")


# ============================================================
# 검증 6: 예외 경로 — broker.submit_order()가 예외 발생
# ============================================================

@pytest.mark.asyncio
async def test_order_manager_submit_exception_path():
    """
    submit_order_to_broker() 예외 경로:
    broker.submit_order()가 예외 발생
    → _record_submission_attempt(accepted=False, error_type=..., retryable=...) 호출
    → 예외 재발생 (raise)
    """
    from agent_trading.domain.enums import OrderSide
    from agent_trading.services.order_manager import OrderManager
    
    mock_repos = _build_mock_repos(with_real_attempts_repo=True)
    om = OrderManager(repos=mock_repos, reconciliation_service=None)
    
    order_request_id = uuid.uuid4()
    order_request = _make_order_request(order_request_id=order_request_id, side=OrderSide.SELL)
    submit_request = _make_submit_request(side=OrderSide.SELL)
    
    # Mock adapter that raises with broker attributes
    mock_adapter = AsyncMock()
    
    class MockBrokerError(Exception):
        def __init__(self):
            self.broker_name = "kis"
            self.raw_code = "EGW00201"
            self.raw_message = "Rate limit exceeded"
            self.retryable = True
            self.http_status = 429
            super().__init__("Rate limit exceeded")
    
    mock_adapter.submit_order.side_effect = MockBrokerError()
    
    # 예외 경로에서는 transition_to가 호출되지 않음 (raise 전)
    with pytest.raises(MockBrokerError):
        await om.submit_order_to_broker(
            order=order_request,
            broker=mock_adapter,
            request=submit_request,
        )
    
    # _record_submission_attempt 호출 확인
    attempts_repo = mock_repos.order_submission_attempts
    attempts = await attempts_repo.list_by_order_request(order_request_id)
    
    assert len(attempts) == 1
    a = attempts[0]
    assert a.accepted == False
    assert a.error_type == "MockBrokerError"
    assert a.retryable == True
    assert a.http_status == 429
    assert a.raw_code == "EGW00201"
    assert a.raw_message == "Rate limit exceeded"
    print(f"✅ 검증 6 (예외): error_type={a.error_type}, retryable={a.retryable}, http_status={a.http_status}")


# ============================================================
# 검증 7: 거절 경로 — broker.submit_order()가 accepted=False 반환
# ============================================================

@pytest.mark.asyncio
async def test_order_manager_submit_rejection_path():
    """
    submit_order_to_broker() 거절 경로:
    broker.submit_order()가 accepted=False 반환
    → _record_submission_attempt(accepted=False, raw_code=..., raw_message=...) 호출
    """
    from agent_trading.domain.enums import OrderSide, OrderStatus, BrokerName
    from agent_trading.domain.models import SubmitOrderResult
    from agent_trading.services.order_manager import OrderManager
    
    mock_repos = _build_mock_repos(with_real_attempts_repo=True)
    om = OrderManager(repos=mock_repos, reconciliation_service=None)
    
    order_request_id = uuid.uuid4()
    order_request = _make_order_request(
        order_request_id=order_request_id,
        client_order_id="client-reject",
        idempotency_key="idem-reject",
        correlation_id="corr-reject",
    )
    submit_request = _make_submit_request(
        client_order_id="client-reject",
        correlation_id="corr-reject",
    )
    
    # Mock broker adapter: rejected result
    mock_adapter = AsyncMock()
    mock_adapter.submit_order.return_value = SubmitOrderResult(
        accepted=False,
        broker_name=BrokerName.KOREA_INVESTMENT,
        client_order_id="client-reject",
        broker_order_id=None,
        broker_status=OrderStatus.REJECTED,
        ack_timestamp=datetime.now(timezone.utc),
        raw_code="VALIDATION_ERROR",
        raw_message="Insufficient cash balance",
        uncertain=False,
        requires_reconciliation=False,
    )
    
    with patch.object(OrderManager, 'transition_to', new_callable=AsyncMock) as mock_transition:
        mock_transition.return_value = order_request
        result = await om.submit_order_to_broker(
            order=order_request,
            broker=mock_adapter,
            request=submit_request,
        )
    
    # transition_to가 PENDING_SUBMIT→REJECTED로 호출되었는지 확인
    mock_transition.assert_awaited_once()
    assert mock_transition.await_args is not None
    pos_args = mock_transition.await_args[0]
    assert pos_args[1] == OrderStatus.REJECTED
    
    # _record_submission_attempt 호출 확인
    attempts_repo = mock_repos.order_submission_attempts
    attempts = await attempts_repo.list_by_order_request(order_request_id)
    
    assert len(attempts) == 1
    a = attempts[0]
    assert a.accepted == False
    assert a.raw_code == "VALIDATION_ERROR"
    assert a.raw_message == "Insufficient cash balance"
    print(f"✅ 검증 7 (거절): accepted={a.accepted}, raw_code={a.raw_code}, raw_message={a.raw_message}")


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    import asyncio
    
    async def run_all():
        print("=" * 60)
        print("Phase 6 Subtask 5: 시나리오 검증")
        print("=" * 60)
        
        await test_record_submission_attempt_success()
        await test_record_submission_attempt_rejected()
        await test_record_submission_attempt_exception()
        await test_multiple_attempts_same_order()
        await test_order_manager_submit_success_path()
        await test_order_manager_submit_exception_path()
        await test_order_manager_submit_rejection_path()
        
        print("\n" + "=" * 60)
        print("✅ 모든 검증 완료")
        print("=" * 60)
    
    asyncio.run(run_all())
