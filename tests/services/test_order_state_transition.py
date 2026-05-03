from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import OrderRequestEntity
from agent_trading.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.order_manager import (
    InvalidStateTransitionError,
    OrderManager,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_order(status: OrderStatus = OrderStatus.DRAFT) -> OrderRequestEntity:
    now = datetime.now(timezone.utc)
    return OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=uuid4(),
        instrument_id=uuid4(),
        client_order_id=f"CLI-{uuid4().hex[:8]}",
        idempotency_key=f"idem-{uuid4().hex[:8]}",
        correlation_id=f"corr-{uuid4().hex[:8]}",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        requested_price=Decimal("50000"),
        requested_quantity=Decimal("10"),
        status=status,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Allowed transitions
# ---------------------------------------------------------------------------


class TestAllowedTransitions:
    """Verify that every allowed transition in the state machine succeeds."""

    @pytest.mark.asyncio
    async def test_draft_to_validated(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.DRAFT)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.VALIDATED)
        assert result.status == OrderStatus.VALIDATED

    @pytest.mark.asyncio
    async def test_validated_to_pending_submit(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.VALIDATED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.PENDING_SUBMIT)
        assert result.status == OrderStatus.PENDING_SUBMIT

    @pytest.mark.asyncio
    async def test_pending_submit_to_submitted(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.PENDING_SUBMIT)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.SUBMITTED)
        assert result.status == OrderStatus.SUBMITTED

    @pytest.mark.asyncio
    async def test_pending_submit_to_reconcile_required(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.PENDING_SUBMIT)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.RECONCILE_REQUIRED)
        assert result.status == OrderStatus.RECONCILE_REQUIRED

    @pytest.mark.asyncio
    async def test_submitted_to_acknowledged(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.SUBMITTED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.ACKNOWLEDGED)
        assert result.status == OrderStatus.ACKNOWLEDGED

    @pytest.mark.asyncio
    async def test_acknowledged_to_partially_filled(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.ACKNOWLEDGED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.PARTIALLY_FILLED)
        assert result.status == OrderStatus.PARTIALLY_FILLED

    @pytest.mark.asyncio
    async def test_acknowledged_to_filled(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.ACKNOWLEDGED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.FILLED)
        assert result.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_acknowledged_to_cancelled(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.ACKNOWLEDGED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.CANCELLED)
        assert result.status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_acknowledged_to_rejected(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.ACKNOWLEDGED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.REJECTED)
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_partially_filled_to_filled(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.PARTIALLY_FILLED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.FILLED)
        assert result.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_partially_filled_to_cancel_pending(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.PARTIALLY_FILLED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.CANCEL_PENDING)
        assert result.status == OrderStatus.CANCEL_PENDING

    @pytest.mark.asyncio
    async def test_cancel_pending_to_cancelled(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.CANCEL_PENDING)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.CANCELLED)
        assert result.status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_reconcile_required_to_acknowledged(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.RECONCILE_REQUIRED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.ACKNOWLEDGED)
        assert result.status == OrderStatus.ACKNOWLEDGED

    @pytest.mark.asyncio
    async def test_reconcile_required_to_filled(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.RECONCILE_REQUIRED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.FILLED)
        assert result.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_reconcile_required_to_cancelled(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.RECONCILE_REQUIRED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.CANCELLED)
        assert result.status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_reconcile_required_to_rejected(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.RECONCILE_REQUIRED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.REJECTED)
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_reconcile_required_to_expired(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.RECONCILE_REQUIRED)
        await in_memory_repos.orders.add(order)
        result = await order_manager.transition_to(order, OrderStatus.EXPIRED)
        assert result.status == OrderStatus.EXPIRED


# ---------------------------------------------------------------------------
# Forbidden transitions
# ---------------------------------------------------------------------------


class TestForbiddenTransitions:
    """Verify that every forbidden transition raises InvalidStateTransitionError."""

    @pytest.mark.asyncio
    async def test_filled_to_cancelled(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.FILLED)
        await in_memory_repos.orders.add(order)
        with pytest.raises(InvalidStateTransitionError):
            await order_manager.transition_to(order, OrderStatus.CANCELLED)

    @pytest.mark.asyncio
    async def test_filled_to_rejected(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.FILLED)
        await in_memory_repos.orders.add(order)
        with pytest.raises(InvalidStateTransitionError):
            await order_manager.transition_to(order, OrderStatus.REJECTED)

    @pytest.mark.asyncio
    async def test_filled_to_partially_filled(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.FILLED)
        await in_memory_repos.orders.add(order)
        with pytest.raises(InvalidStateTransitionError):
            await order_manager.transition_to(order, OrderStatus.PARTIALLY_FILLED)

    @pytest.mark.asyncio
    async def test_cancelled_to_filled(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.CANCELLED)
        await in_memory_repos.orders.add(order)
        with pytest.raises(InvalidStateTransitionError):
            await order_manager.transition_to(order, OrderStatus.FILLED)

    @pytest.mark.asyncio
    async def test_rejected_to_acknowledged(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.REJECTED)
        await in_memory_repos.orders.add(order)
        with pytest.raises(InvalidStateTransitionError):
            await order_manager.transition_to(order, OrderStatus.ACKNOWLEDGED)

    @pytest.mark.asyncio
    async def test_expired_to_submitted(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.EXPIRED)
        await in_memory_repos.orders.add(order)
        with pytest.raises(InvalidStateTransitionError):
            await order_manager.transition_to(order, OrderStatus.SUBMITTED)

    @pytest.mark.asyncio
    async def test_draft_to_submitted(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.DRAFT)
        await in_memory_repos.orders.add(order)
        with pytest.raises(InvalidStateTransitionError):
            await order_manager.transition_to(order, OrderStatus.SUBMITTED)

    @pytest.mark.asyncio
    async def test_validated_to_filled(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        order = _make_order(OrderStatus.VALIDATED)
        await in_memory_repos.orders.add(order)
        with pytest.raises(InvalidStateTransitionError):
            await order_manager.transition_to(order, OrderStatus.FILLED)

    @pytest.mark.asyncio
    async def test_terminal_state_any_transition(
        self, order_manager: OrderManager, in_memory_repos: RepositoryContainer
    ) -> None:
        """No transition from any terminal state should be allowed."""
        for terminal in [
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        ]:
            order = _make_order(terminal)
            await in_memory_repos.orders.add(order)
            for target in OrderStatus:
                if target == terminal:
                    continue
                with pytest.raises(InvalidStateTransitionError):
                    await order_manager.transition_to(order, target)
