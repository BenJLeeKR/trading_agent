from __future__ import annotations

"""Integration tests for ``PostgresBrokerAccountRepository``.

These tests verify that broker account records are persisted to the
PostgreSQL ``trading.broker_accounts`` table and can be queried back.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import BrokerAccountEntity
from agent_trading.domain.enums import Environment
from agent_trading.repositories.container import RepositoryContainer


@pytest.fixture
def broker_account_id() -> UUID:
    return uuid4()


@pytest.fixture
def sample_broker_account(broker_account_id: UUID) -> BrokerAccountEntity:
    return BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="KoreaInvestment",
        account_ref="TEST-ACCT-001",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url=None,
        status="active",
        broker_account_code="KIS-PAPER-****0001",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_add_and_get(
    postgres_repos: RepositoryContainer,
    sample_broker_account: BrokerAccountEntity,
    broker_account_id: UUID,
) -> None:
    saved = await postgres_repos.broker_accounts.add(sample_broker_account)
    assert saved.broker_account_id == broker_account_id
    assert saved.broker_name == "KoreaInvestment"
    assert saved.account_ref == "TEST-ACCT-001"
    assert saved.environment == Environment.PAPER

    fetched = await postgres_repos.broker_accounts.get(broker_account_id)
    assert fetched is not None
    assert fetched.broker_account_id == broker_account_id
    assert fetched.broker_name == "KoreaInvestment"


@pytest.mark.asyncio
async def test_get_nonexistent(
    postgres_repos: RepositoryContainer,
) -> None:
    result = await postgres_repos.broker_accounts.get(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_by_ref(
    postgres_repos: RepositoryContainer,
    sample_broker_account: BrokerAccountEntity,
) -> None:
    await postgres_repos.broker_accounts.add(sample_broker_account)

    fetched = await postgres_repos.broker_accounts.get_by_ref(
        "KoreaInvestment",
        "TEST-ACCT-001",
        Environment.PAPER,
    )
    assert fetched is not None
    assert fetched.broker_account_id == sample_broker_account.broker_account_id

    # Wrong environment should return None
    not_found = await postgres_repos.broker_accounts.get_by_ref(
        "KoreaInvestment",
        "TEST-ACCT-001",
        Environment.LIVE,
    )
    assert not_found is None


@pytest.mark.asyncio
async def test_get_by_ref_nonexistent(
    postgres_repos: RepositoryContainer,
) -> None:
    result = await postgres_repos.broker_accounts.get_by_ref(
        "KoreaInvestment",
        "NONEXISTENT",
        Environment.PAPER,
    )
    assert result is None


@pytest.mark.asyncio
async def test_list_by_broker(
    postgres_repos: RepositoryContainer,
    broker_account_id: UUID,
) -> None:
    acct1 = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="KoreaInvestment",
        account_ref="ACCT-001",
        environment=Environment.PAPER,
        credential_ref="cred-1",
        base_url=None,
        status="active",
        broker_account_code="KIS-PAPER-****0001",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    acct2 = BrokerAccountEntity(
        broker_account_id=uuid4(),
        broker_name="KoreaInvestment",
        account_ref="ACCT-002",
        environment=Environment.LIVE,
        credential_ref="cred-2",
        base_url=None,
        status="active",
        broker_account_code="KIS-LIVE-****0002",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    acct3 = BrokerAccountEntity(
        broker_account_id=uuid4(),
        broker_name="Kiwoom",
        account_ref="ACCT-003",
        environment=Environment.PAPER,
        credential_ref="cred-3",
        base_url=None,
        status="active",
        broker_account_code="KIWO-PAPER-****0003",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    await postgres_repos.broker_accounts.add(acct1)
    await postgres_repos.broker_accounts.add(acct2)
    await postgres_repos.broker_accounts.add(acct3)

    # KoreaInvestment should return 2 accounts
    ki_accounts = await postgres_repos.broker_accounts.list_by_broker("KoreaInvestment")
    assert len(ki_accounts) == 2
    assert all(a.broker_name == "KoreaInvestment" for a in ki_accounts)

    # Kiwoom should return 1 account
    kw_accounts = await postgres_repos.broker_accounts.list_by_broker("Kiwoom")
    assert len(kw_accounts) == 1
    assert kw_accounts[0].account_ref == "ACCT-003"

    # Unknown broker should return empty
    empty = await postgres_repos.broker_accounts.list_by_broker("Unknown")
    assert len(empty) == 0


@pytest.mark.asyncio
async def test_add_duplicate_ref_raises(
    postgres_repos: RepositoryContainer,
    sample_broker_account: BrokerAccountEntity,
) -> None:
    await postgres_repos.broker_accounts.add(sample_broker_account)

    duplicate = BrokerAccountEntity(
        broker_account_id=uuid4(),
        broker_name="KoreaInvestment",
        account_ref="TEST-ACCT-001",
        environment=Environment.PAPER,
        credential_ref="other-cred",
        base_url=None,
        status="active",
        broker_account_code="KIS-PAPER-****0001",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(Exception):
        await postgres_repos.broker_accounts.add(duplicate)
