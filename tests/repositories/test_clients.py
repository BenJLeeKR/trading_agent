from __future__ import annotations

from uuid import uuid4

import pytest

from agent_trading.domain.entities import ClientEntity


class TestClientRepositoryContract:
    """Verify that ClientRepository implementations satisfy the contract."""

    @pytest.mark.asyncio
    async def test_add_and_get(self, in_memory_repos) -> None:
        client_id = uuid4()
        client = ClientEntity(
            client_id=client_id,
            client_code="C001",
            name="Alpha Client",
            status="active",
            base_currency="KRW",
        )

        created = await in_memory_repos.clients.add(client)
        assert created.client_id == client_id
        assert created.client_code == "C001"

        fetched = await in_memory_repos.clients.get(client_id)
        assert fetched is not None
        assert fetched.client_code == "C001"
        assert fetched.name == "Alpha Client"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, in_memory_repos) -> None:
        result = await in_memory_repos.clients.get(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_code(self, in_memory_repos) -> None:
        client = ClientEntity(
            client_id=uuid4(),
            client_code="UNIQUE-CODE",
            name="Unique Client",
            status="active",
            base_currency="USD",
        )
        await in_memory_repos.clients.add(client)

        fetched = await in_memory_repos.clients.get_by_code("UNIQUE-CODE")
        assert fetched is not None
        assert fetched.client_id == client.client_id

    @pytest.mark.asyncio
    async def test_get_by_code_nonexistent_returns_none(self, in_memory_repos) -> None:
        result = await in_memory_repos.clients.get_by_code("DOES-NOT-EXIST")
        assert result is None
