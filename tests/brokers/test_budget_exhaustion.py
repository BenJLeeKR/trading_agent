"""Tests for budget exhaustion safety policies.

Verifies that:
1. ``OrderManager.create_order()`` blocks new entries when inquiry or
   reconciliation budget is exhausted.
2. ``KISRestClient.resolve_unknown_state()`` falls back to the
   reconciliation reserve when the inquiry bucket is exhausted.
3. When both inquiry and reconciliation reserves are exhausted, recovery
   fails with ``BudgetExhaustedError``.
4. ``KoreaInvestmentAdapter.submit_order()`` returns ``REJECTED`` (not
   ``RECONCILE_REQUIRED``) when ``BudgetExhaustedError`` is raised for a
   BUY order.
5. Held-position SELL reserve lane retry behaviour is preserved after
   ``BudgetExhaustedError``.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agent_trading.brokers.koreainvestment.adapter import KoreaInvestmentAdapter
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.rate_limit import (
    BudgetExhaustedError,
    BucketType,
    RateLimitBudgetManager,
)
from agent_trading.domain.entities import AccountEntity, OrderRequestEntity
from agent_trading.domain.enums import BrokerName, Environment, OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.domain.models import SubmitOrderRequest, SubmitOrderResult
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.reconciliation_service import ReconciliationService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repos():
    return build_in_memory_repositories()


@pytest.fixture
def mock_rest_client() -> AsyncMock:
    """Mock KISRestClient for adapter-level tests."""
    return AsyncMock(spec=KISRestClient)


@pytest.fixture
def adapter(mock_rest_client: AsyncMock) -> KoreaInvestmentAdapter:
    """KoreaInvestmentAdapter with a mocked rest client."""
    return KoreaInvestmentAdapter(rest_client=mock_rest_client)


@pytest.fixture
def reconciliation_service(repos):
    return ReconciliationService(repos)


@pytest.fixture
def sample_request() -> SubmitOrderRequest:
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


@pytest.fixture
async def seeded_repos(repos):
    """Repos with a pre-seeded account + instrument matching sample_request."""
    client_id = uuid4()
    account = AccountEntity(
        account_id=uuid4(),
        client_id=client_id,
        broker_account_id=uuid4(),
        environment=Environment.PAPER,
        account_alias="test_account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    from agent_trading.domain.entities import InstrumentEntity

    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="005930",
        market_code="KRX",
        asset_class="stock",
        currency="KRW",
        name="Samsung Electronics",
    )
    await repos.instruments.add(instrument)
    return repos


# ---------------------------------------------------------------------------
# 2-a. create_order() — inquiry budget exhaustion blocks new entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_blocks_when_inquiry_exhausted(repos, reconciliation_service, sample_request):
    """create_order() raises BudgetExhaustedError when inquiry budget < 20%."""
    budget = RateLimitBudgetManager(
        inquiry_capacity=1,
        inquiry_refill_rate=0.0,
    )
    # Consume the only inquiry token → utilization = 0/1 = 0% (< 20%).
    budget.consume_or_raise(BucketType.INQUIRY, tokens=1)

    manager = OrderManager(
        repos=repos,
        reconciliation_service=reconciliation_service,
        budget_manager=budget,
    )

    with pytest.raises(BudgetExhaustedError) as exc_info:
        await manager.create_order(sample_request)

    assert "inquiry" in str(exc_info.value).lower() or "inquiry" in exc_info.value.message


# ---------------------------------------------------------------------------
# 2-b. create_order() — reconciliation reserve exhaustion blocks new entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_blocks_when_reconciliation_exhausted(repos, reconciliation_service, sample_request):
    """create_order() raises BudgetExhaustedError when reconciliation reserve < 50%."""
    budget = RateLimitBudgetManager(
        reconciliation_capacity=2,
        reconciliation_refill_rate=0.0,
    )
    # Consume both tokens → utilization = 0/2 = 0% (< 50%).
    budget.consume_or_raise(BucketType.RECONCILIATION, tokens=2)

    manager = OrderManager(
        repos=repos,
        reconciliation_service=reconciliation_service,
        budget_manager=budget,
    )

    with pytest.raises(BudgetExhaustedError) as exc_info:
        await manager.create_order(sample_request)

    assert "reconciliation" in str(exc_info.value).lower() or "reconciliation" in exc_info.value.message


# ---------------------------------------------------------------------------
# 2-c. create_order() — healthy budget allows new entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_allows_when_budget_healthy(seeded_repos, reconciliation_service, sample_request):
    """create_order() succeeds when both inquiry and reconciliation budgets are healthy."""
    budget = RateLimitBudgetManager(
        inquiry_capacity=60,
        inquiry_refill_rate=5.0,
        reconciliation_capacity=20,
        reconciliation_refill_rate=1.0,
    )

    manager = OrderManager(
        repos=seeded_repos,
        reconciliation_service=reconciliation_service,
        budget_manager=budget,
    )

    order = await manager.create_order(sample_request)
    assert isinstance(order, OrderRequestEntity)
    assert order.status == OrderStatus.DRAFT
    assert order.client_order_id == "test-001"


# ---------------------------------------------------------------------------
# 2-d. KIS inquiry fallback to reconciliation reserve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kis_inquiry_fallback_to_reconciliation_reserve():
    """resolve_unknown_state() falls back to reconciliation reserve when inquiry is exhausted."""
    budget = RateLimitBudgetManager(
        inquiry_capacity=0,
        inquiry_refill_rate=0.0,
        reconciliation_capacity=5,
        reconciliation_refill_rate=0.0,
    )
    client = KISRestClient(
        api_key="dummy",
        api_secret="dummy",
        account_number="12345678",
        account_product_code="01",
        budget_manager=budget,
    )

    # resolve_unknown_state() calls get_order_status() which consumes INQUIRY.
    # INQUIRY bucket is empty → BudgetExhaustedError → falls back to reserve.
    # The actual HTTP call will fail (no network), but the budget fallback
    # path is exercised before the HTTP call.
    try:
        result = await client.resolve_unknown_state(
            broker_order_id="test-001",
            symbol="005930",
        )
    except Exception:
        # Network error is expected since we have no real KIS API.
        # The important thing is that the reconciliation reserve was consumed.
        pass

    # The reconciliation reserve should have been consumed.
    assert budget.reconciliation.remaining < budget.reconciliation.capacity


# ---------------------------------------------------------------------------
# 2-e. Reserve also exhausted → recovery fails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kis_reserve_exhausted_recovery_fails():
    """resolve_unknown_state() raises BudgetExhaustedError when both inquiry and reserve are exhausted."""
    budget = RateLimitBudgetManager(
        inquiry_capacity=0,
        inquiry_refill_rate=0.0,
        reconciliation_capacity=0,
        reconciliation_refill_rate=0.0,
    )
    client = KISRestClient(
        api_key="dummy",
        api_secret="dummy",
        account_number="12345678",
        account_product_code="01",
        budget_manager=budget,
    )

    with pytest.raises(BudgetExhaustedError) as exc_info:
        await client.resolve_unknown_state(
            broker_order_id="test-001",
            symbol="005930",
        )

    # The error should reference the reconciliation reserve.
    assert "reconciliation" in str(exc_info.value).lower() or "reconciliation" in exc_info.value.message


# ---------------------------------------------------------------------------
# 3. BUDGET_EXHAUSTED BUY → REJECTED (not RECONCILE_REQUIRED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_exhausted_buy_returns_rejected_not_reconcile(
    adapter, mock_rest_client
):
    """BUDGET_EXHAUSTED로 실패한 BUY 주문은 REJECTED로 반환되어야 함."""
    mock_rest_client.submit_order.side_effect = BudgetExhaustedError(
        "ORDER", "BUDGET_EXHAUSTED"
    )
    request = SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="test-client-order-id",
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
    result = await adapter.submit_order(request)
    assert result.normalized_status == OrderStatus.REJECTED
    assert result.broker_status == OrderStatus.REJECTED
    assert result.requires_reconciliation is False


# ---------------------------------------------------------------------------
# 4. Held-position SELL reserve lane preserved after BUDGET_EXHAUSTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_exhausted_sell_reserve_lane_preserved(
    adapter, mock_rest_client
):
    """Held-position SELL reserve lane은 BUDGET_EXHAUSTED 후에도 retry 동작 유지."""
    # 첫 번째 호출은 BUDGET_EXHAUSTED, reserve 후 두 번째 호출 성공
    from datetime import datetime, timezone

    mock_rest_client.submit_order.side_effect = [
        BudgetExhaustedError("ORDER", "BUDGET_EXHAUSTED"),
        SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="test-client-order-id",
            broker_order_id="broker-order-123",
            broker_status=OrderStatus.SUBMITTED,
            ack_timestamp=datetime.now(timezone.utc),
            normalized_status=OrderStatus.SUBMITTED,
            requires_reconciliation=False,
        ),
    ]
    request = SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="test-client-order-id",
        correlation_id="corr-001",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
        metadata={"source_type": "held_position"},
    )
    result = await adapter.submit_order(request)
    # reserve 성공 시 정상 SUBMITTED
    assert result.normalized_status == OrderStatus.SUBMITTED
    assert result.requires_reconciliation is False
