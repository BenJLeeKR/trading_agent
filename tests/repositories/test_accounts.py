from __future__ import annotations

from uuid import uuid4

import pytest

from agent_trading.domain.entities import AccountEntity
from agent_trading.domain.enums import Environment
from agent_trading.repositories.filters import AccountLookup


class TestAccountRepositoryContract:
    """Verify that AccountRepository implementations satisfy the contract."""

    @pytest.mark.asyncio
    async def test_add_and_get(self, in_memory_repos, sample_account) -> None:
        created = await in_memory_repos.accounts.add(sample_account)
        assert created.account_id == sample_account.account_id

        fetched = await in_memory_repos.accounts.get(sample_account.account_id)
        assert fetched is not None
        assert fetched.account_alias == "Test Account"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, in_memory_repos) -> None:
        result = await in_memory_repos.accounts.get(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_find_one_by_account_id(self, in_memory_repos, sample_account) -> None:
        await in_memory_repos.accounts.add(sample_account)

        lookup = AccountLookup(account_id=sample_account.account_id)
        result = await in_memory_repos.accounts.find_one(lookup)
        assert result is not None
        assert result.account_id == sample_account.account_id

    @pytest.mark.asyncio
    async def test_find_one_by_alias(self, in_memory_repos, sample_account) -> None:
        await in_memory_repos.accounts.add(sample_account)

        lookup = AccountLookup(account_alias="Test Account")
        result = await in_memory_repos.accounts.find_one(lookup)
        assert result is not None
        assert result.account_id == sample_account.account_id

    @pytest.mark.asyncio
    async def test_find_one_nonexistent_returns_none(self, in_memory_repos) -> None:
        lookup = AccountLookup(account_alias="NONEXISTENT")
        result = await in_memory_repos.accounts.find_one(lookup)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_by_client(self, in_memory_repos, sample_account) -> None:
        await in_memory_repos.accounts.add(sample_account)

        accounts = await in_memory_repos.accounts.list_by_client(
            sample_account.client_id
        )
        assert len(accounts) >= 1
        assert any(a.account_id == sample_account.account_id for a in accounts)
