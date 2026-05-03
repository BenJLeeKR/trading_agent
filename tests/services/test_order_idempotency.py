from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.domain.enums import OrderSide, OrderType, TimeInForce
from agent_trading.services.order_manager import DuplicateOrderError, OrderManager


class TestOrderIdempotency:
    """Verify that duplicate client_order_id is blocked at the application layer."""

    @pytest.mark.asyncio
    async def test_duplicate_client_order_id_raises_error(
        self, order_manager: OrderManager, seeded_repos
    ) -> None:
        request = SubmitOrderRequest(
            client_order_id="DUPLICATE-CLI-001",
            correlation_id="corr-001",
            account_ref="Test Account",
            strategy_id="strat-001",
            symbol="005930",
            market="KRX",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            price=Decimal("50000"),
            time_in_force=TimeInForce.DAY,
        )

        # First call should succeed
        await order_manager.create_order(request)

        # Second call with same client_order_id should fail
        with pytest.raises(DuplicateOrderError) as exc_info:
            await order_manager.create_order(request)

        assert "client_order_id" in str(exc_info.value)
        assert "DUPLICATE-CLI-001" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_different_client_order_id_succeeds(
        self, order_manager: OrderManager, seeded_repos
    ) -> None:
        req1 = SubmitOrderRequest(
            client_order_id="CLI-001",
            correlation_id="corr-001",
            account_ref="Test Account",
            strategy_id="strat-001",
            symbol="005930",
            market="KRX",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            price=Decimal("50000"),
            time_in_force=TimeInForce.DAY,
        )
        req2 = SubmitOrderRequest(
            client_order_id="CLI-002",
            correlation_id="corr-002",
            account_ref="Test Account",
            strategy_id="strat-001",
            symbol="005930",
            market="KRX",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("5"),
            price=Decimal("51000"),
            time_in_force=TimeInForce.DAY,
        )

        order1 = await order_manager.create_order(req1)
        order2 = await order_manager.create_order(req2)

        assert order1.order_request_id != order2.order_request_id
        assert order1.client_order_id == "CLI-001"
        assert order2.client_order_id == "CLI-002"

    @pytest.mark.asyncio
    async def test_create_order_returns_draft_status(
        self, order_manager: OrderManager, seeded_repos
    ) -> None:
        request = SubmitOrderRequest(
            client_order_id="CLI-DRAFT-TEST",
            correlation_id="corr-draft-test",
            account_ref="Test Account",
            strategy_id="strat-001",
            symbol="005930",
            market="KRX",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            price=Decimal("50000"),
            time_in_force=TimeInForce.DAY,
        )

        order = await order_manager.create_order(request)
        assert order.status.value == "draft"
        assert order.requested_quantity == Decimal("10")
