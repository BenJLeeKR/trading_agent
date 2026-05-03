from __future__ import annotations

from uuid import uuid4

import pytest

from agent_trading.domain.entities import OrderRequestEntity
from agent_trading.domain.enums import OrderStatus
from agent_trading.repositories.filters import OrderQuery


class TestOrderRepositoryContract:
    """Verify that OrderRepository implementations satisfy the contract."""

    @pytest.mark.asyncio
    async def test_add_and_get(self, in_memory_repos, sample_order) -> None:
        created = await in_memory_repos.orders.add(sample_order)
        assert created.order_request_id == sample_order.order_request_id
        assert created.status == OrderStatus.DRAFT

        fetched = await in_memory_repos.orders.get(sample_order.order_request_id)
        assert fetched is not None
        assert fetched.client_order_id == "CLI-001"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, in_memory_repos) -> None:
        result = await in_memory_repos.orders.get(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_client_order_id(self, in_memory_repos, sample_order) -> None:
        await in_memory_repos.orders.add(sample_order)

        fetched = await in_memory_repos.orders.get_by_client_order_id("CLI-001")
        assert fetched is not None
        assert fetched.order_request_id == sample_order.order_request_id

    @pytest.mark.asyncio
    async def test_get_by_client_order_id_nonexistent_returns_none(
        self, in_memory_repos
    ) -> None:
        result = await in_memory_repos.orders.get_by_client_order_id("DOES-NOT-EXIST")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_with_filters(self, in_memory_repos, sample_order) -> None:
        await in_memory_repos.orders.add(sample_order)

        # Filter by account_id
        query = OrderQuery(account_id=sample_order.account_id)
        results = await in_memory_repos.orders.list(query)
        assert len(results) >= 1
        assert any(r.order_request_id == sample_order.order_request_id for r in results)

        # Filter by status
        query = OrderQuery(status=OrderStatus.DRAFT)
        results = await in_memory_repos.orders.list(query)
        assert len(results) >= 1

        # Filter by non-matching status
        query = OrderQuery(status=OrderStatus.FILLED)
        results = await in_memory_repos.orders.list(query)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_update_status(self, in_memory_repos, sample_order) -> None:
        await in_memory_repos.orders.add(sample_order)

        await in_memory_repos.orders.update_status(
            sample_order.order_request_id,
            OrderStatus.VALIDATED,
        )

        updated = await in_memory_repos.orders.get(sample_order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.VALIDATED

    @pytest.mark.asyncio
    async def test_update_status_with_reason(self, in_memory_repos, sample_order) -> None:
        await in_memory_repos.orders.add(sample_order)

        await in_memory_repos.orders.update_status(
            sample_order.order_request_id,
            OrderStatus.REJECTED,
            reason_code="INSUFFICIENT_BALANCE",
            reason_message="Account balance too low",
        )

        updated = await in_memory_repos.orders.get(sample_order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.REJECTED
        assert updated.status_reason_code == "INSUFFICIENT_BALANCE"
        assert updated.status_reason_message == "Account balance too low"
