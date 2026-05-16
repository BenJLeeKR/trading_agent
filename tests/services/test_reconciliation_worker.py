from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    BrokerOrderEntity,
    ReconciliationOrderLinkEntity,
    ReconciliationRunEntity,
)
from agent_trading.config.settings import AppSettings
from agent_trading.domain.enums import Environment, OrderStatus
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.reconciliation_service import ReconciliationService
from agent_trading.services.reconciliation_worker import (
    ProcessingResult,
    ReconciliationRunProcessor,
)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def repos() -> RepositoryContainer:
    return build_in_memory_repositories()


@pytest.fixture
def service(repos: RepositoryContainer) -> ReconciliationService:
    return ReconciliationService(repos)


@pytest.fixture
def account_id() -> UUID:
    return uuid4()


@pytest.fixture
def broker_account_id() -> UUID:
    return uuid4()


@pytest.fixture
def order_request_id() -> UUID:
    return uuid4()


@pytest.fixture
def run_id() -> UUID:
    return uuid4()


@pytest.fixture
async def seeded_run(
    repos: RepositoryContainer,
    service: ReconciliationService,
    account_id: UUID,
    order_request_id: UUID,
) -> ReconciliationRunEntity:
    """Create a run with an order link via trigger_and_link()."""
    # Pre-seed account + broker_account so trigger_and_link can resolve
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-account-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)

    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    return await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=order_request_id,
    )


@pytest.fixture
async def worker(
    repos: RepositoryContainer,
    service: ReconciliationService,
    settings: AppSettings,
) -> ReconciliationRunProcessor:
    """Worker with in-memory repositories and dry-run disabled."""
    return ReconciliationRunProcessor(
        repos=repos,
        reconciliation_service=service,
        settings=settings,
        dry_run=False,
    )


@pytest.fixture
async def dry_worker(
    repos: RepositoryContainer,
    service: ReconciliationService,
    settings: AppSettings,
) -> ReconciliationRunProcessor:
    """Worker with dry_run=True."""
    return ReconciliationRunProcessor(
        repos=repos,
        reconciliation_service=service,
        settings=settings,
        dry_run=True,
    )


# =========================================================================
# Phase 0: Service Layer — trigger_and_link()
# =========================================================================


@pytest.mark.asyncio
async def test_trigger_and_link_creates_run_and_link(
    repos: RepositoryContainer,
    service: ReconciliationService,
    account_id: UUID,
    order_request_id: UUID,
) -> None:
    """trigger_and_link() creates a run + attaches order mismatch link."""
    # Given: pre-seeded account + broker_account
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    # When
    run = await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=order_request_id,
    )

    # Then: run created
    assert run.account_id == account_id
    assert run.trigger_type == "requires_reconciliation"
    assert run.status == "started"

    # Then: order link created
    links = await repos.reconciliations.get_run_order_links(run.reconciliation_run_id)
    assert len(links) == 1
    assert links[0].order_request_id == order_request_id
    assert links[0].mismatch_type == "pending_inquiry"


@pytest.mark.asyncio
async def test_trigger_and_link_without_order_request_id(
    repos: RepositoryContainer,
    service: ReconciliationService,
    account_id: UUID,
) -> None:
    """trigger_and_link() with order_request_id=None creates run only."""
    # Given: pre-seeded account + broker_account
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    # When
    run = await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=None,
    )

    # Then: run created, no link
    assert run.status == "started"
    links = await repos.reconciliations.get_run_order_links(run.reconciliation_run_id)
    assert len(links) == 0


# =========================================================================
# Phase 1: Repository Read Path — list_pending_runs()
# =========================================================================


@pytest.mark.asyncio
async def test_list_pending_runs_returns_started_only(
    repos: RepositoryContainer,
    service: ReconciliationService,
    account_id: UUID,
) -> None:
    """list_pending_runs() only returns runs with status='started'."""
    # Given: pre-seeded account + broker_account
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    # Create a run and resolve it
    run1 = await service.trigger(account_id, trigger_type="first")
    await service.mark_resolved(run1.reconciliation_run_id)

    # Create another run (still started)
    run2 = await service.trigger(account_id, trigger_type="second")

    # When
    pending = await repos.reconciliations.list_pending_runs()

    # Then: only the started run is returned
    assert len(pending) == 1
    assert pending[0].reconciliation_run_id == run2.reconciliation_run_id
    assert pending[0].status == "started"


@pytest.mark.asyncio
async def test_list_pending_runs_filter_by_account_id(
    repos: RepositoryContainer,
    service: ReconciliationService,
    account_id: UUID,
) -> None:
    """list_pending_runs(account_id=...) filters by account."""
    # Given: pre-seeded accounts
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    another_account_id = uuid4()
    another_broker_account_id = uuid4()
    another_broker_account = BrokerAccountEntity(
        broker_account_id=another_broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref-2",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****0002",
    )
    await repos.broker_accounts.add(another_broker_account)
    another_account = AccountEntity(
        account_id=another_account_id,
        client_id=uuid4(),
        broker_account_id=another_broker_account_id,
        environment=Environment.PAPER,
        account_alias="Another Account",
        account_masked="****9999",
        status="active",
    )
    await repos.accounts.add(another_account)

    # Create runs for both accounts
    await service.trigger(account_id, trigger_type="a")
    await service.trigger(another_account_id, trigger_type="b")

    # When: filter by first account
    pending = await repos.reconciliations.list_pending_runs(account_id=account_id)

    # Then: only first account's run
    assert len(pending) == 1
    assert pending[0].account_id == account_id


@pytest.mark.asyncio
async def test_list_pending_runs_limit(
    repos: RepositoryContainer,
    service: ReconciliationService,
    account_id: UUID,
) -> None:
    """list_pending_runs(limit=N) limits the result set."""
    # Given: pre-seeded accounts
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    # Create 3 runs — the first 2 are resolved, last is started
    # trigger() reuses active runs, so we resolve after each
    run1 = await service.trigger(account_id, trigger_type="a")
    await service.mark_resolved(run1.reconciliation_run_id)
    run2 = await service.trigger(account_id, trigger_type="b")
    await service.mark_resolved(run2.reconciliation_run_id)
    run3 = await service.trigger(account_id, trigger_type="c")

    # When: limit=1
    pending = await repos.reconciliations.list_pending_runs(limit=1)

    # Then: only 1 result
    assert len(pending) == 1
    assert pending[0].reconciliation_run_id == run3.reconciliation_run_id


# =========================================================================
# Phase 1: Repository Read Path — get_run_order_links()
# =========================================================================


@pytest.mark.asyncio
async def test_get_run_order_links_returns_links(
    seeded_run: ReconciliationRunEntity,
    repos: RepositoryContainer,
    order_request_id: UUID,
) -> None:
    """get_run_order_links() returns order links for a run."""
    links = await repos.reconciliations.get_run_order_links(
        seeded_run.reconciliation_run_id,
    )
    assert len(links) == 1
    assert links[0].order_request_id == order_request_id
    assert links[0].mismatch_type == "pending_inquiry"


@pytest.mark.asyncio
async def test_get_run_order_links_empty_for_unknown_run(
    repos: RepositoryContainer,
    run_id: UUID,
) -> None:
    """get_run_order_links() returns empty list for non-existent run."""
    links = await repos.reconciliations.get_run_order_links(run_id)
    assert len(links) == 0


# =========================================================================
# Phase 2: Worker — process_run()
# =========================================================================


@pytest.mark.asyncio
async def test_process_run_no_links(
    repos: RepositoryContainer,
    service: ReconciliationService,
    worker: ReconciliationRunProcessor,
    account_id: UUID,
) -> None:
    """Run with no order links returns skipped_no_links."""
    # Given: account + broker_account seed
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    run = await service.trigger(account_id, trigger_type="no_links")  # no order link

    result = await worker.process_run(run)

    assert result.status == "skipped_no_links"
    assert result.orders_processed == 0
    assert result.run_id == run.reconciliation_run_id


@pytest.mark.asyncio
async def test_process_run_no_account_found(
    repos: RepositoryContainer,
    worker: ReconciliationRunProcessor,
    run_id: UUID,
    order_request_id: UUID,
) -> None:
    """Run with non-existent account → retained (not failed)."""
    now = datetime.now(timezone.utc)
    account_id = uuid4()  # account does not exist
    run = ReconciliationRunEntity(
        reconciliation_run_id=run_id,
        account_id=account_id,
        trigger_type="test",
        status="started",
        started_at=now,
    )
    # Add an order link so the worker proceeds past the "no links" check
    await repos.reconciliations.attach_order_mismatch(
        reconciliation_run_id=run_id,
        order_request_id=order_request_id,
        mismatch_type="pending_inquiry",
        details={"trigger_type": "test"},
    )

    result = await worker.process_run(run)

    assert result.status == "retained"
    assert result.error is not None


@pytest.mark.asyncio
async def test_process_run_all_resolved(
    repos: RepositoryContainer,
    service: ReconciliationService,
    worker: ReconciliationRunProcessor,
    account_id: UUID,
    order_request_id: UUID,
    run_id: UUID,
) -> None:
    """All orders resolve successfully → run status becomes resolved."""
    # Given: seeded koreainvestment run with link
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="koreainvestment",
        account_ref="test-account-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="KIS-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    run = await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=order_request_id,
    )

    # Add a broker order so _process_order_link can find it
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order_request_id,
        broker_name="koreainvestment",
        broker_status="FILLED",
        broker_native_order_id="NATIVE-001",
        last_synced_at=datetime.now(timezone.utc),
    )
    await repos.broker_orders.add(broker_order)

    # Mock adapter to return FILLED (terminal)
    mock_adapter = AsyncMock()
    mock_result = AsyncMock()
    mock_result.status = OrderStatus.FILLED
    mock_adapter.resolve_unknown_state = AsyncMock(return_value=mock_result)

    with patch.object(
        worker,
        "_build_adapter_for_broker_account",
        new_callable=AsyncMock,
        return_value=mock_adapter,
    ):
        result = await worker.process_run(run)

    # Then: run resolved
    assert result.status == "resolved"
    assert result.orders_processed == 1
    assert result.orders_resolved == 1

    # Verify the run was actually marked resolved in the repo
    fetched = await repos.reconciliations.get_run(run.reconciliation_run_id)
    assert fetched is not None
    assert fetched.status == "resolved"


@pytest.mark.asyncio
async def test_process_run_order_fails(
    repos: RepositoryContainer,
    service: ReconciliationService,
    worker: ReconciliationRunProcessor,
    account_id: UUID,
    order_request_id: UUID,
) -> None:
    """Order resolution failure → run status becomes failed."""
    # Given: seeded koreainvestment account
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="koreainvestment",
        account_ref="test-account-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="KIS-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    run = await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=order_request_id,
    )

    # Add broker order with mock adapter that raises
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order_request_id,
        broker_name="koreainvestment",
        broker_status="UNKNOWN",
        broker_native_order_id="NATIVE-001",
        last_synced_at=datetime.now(timezone.utc),
    )
    await repos.broker_orders.add(broker_order)

    mock_adapter = AsyncMock()
    mock_adapter.resolve_unknown_state = AsyncMock(
        side_effect=RuntimeError("Broker API unavailable"),
    )

    with patch.object(
        worker,
        "_build_adapter_for_broker_account",
        new_callable=AsyncMock,
        return_value=mock_adapter,
    ):
        result = await worker.process_run(run)

    # Then: run failed
    assert result.status == "failed"
    assert result.orders_processed == 1
    assert result.orders_resolved == 0

    fetched = await repos.reconciliations.get_run(run.reconciliation_run_id)
    assert fetched is not None
    assert fetched.status == "failed"


@pytest.mark.asyncio
async def test_process_run_no_broker_orders(
    repos: RepositoryContainer,
    service: ReconciliationService,
    worker: ReconciliationRunProcessor,
    account_id: UUID,
    order_request_id: UUID,
) -> None:
    """Order link with no broker orders → run fails."""
    # Given: seeded koreainvestment account (but NO broker_order added)
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="koreainvestment",
        account_ref="test-account-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="KIS-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    run = await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=order_request_id,
    )
    # Intentionally NOT adding a broker order

    # Mock adapter (not reached, but needed to pass broker resolution)
    mock_adapter = AsyncMock()

    with patch.object(
        worker,
        "_build_adapter_for_broker_account",
        new_callable=AsyncMock,
        return_value=mock_adapter,
    ):
        result = await worker.process_run(run)

    # Then: run failed because no broker orders
    assert result.status == "failed"
    fetched = await repos.reconciliations.get_run(run.reconciliation_run_id)
    assert fetched is not None
    assert fetched.status == "failed"


@pytest.mark.asyncio
async def test_process_run_dry_run_retains_status(
    repos: RepositoryContainer,
    service: ReconciliationService,
    dry_worker: ReconciliationRunProcessor,
    account_id: UUID,
    order_request_id: UUID,
) -> None:
    """dry_run=True does not change the run status."""
    # Given: seeded koreainvestment account
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="koreainvestment",
        account_ref="test-account-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="KIS-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    run = await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=order_request_id,
    )

    # Add broker order
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order_request_id,
        broker_name="koreainvestment",
        broker_status="FILLED",
        broker_native_order_id="NATIVE-001",
        last_synced_at=datetime.now(timezone.utc),
    )
    await repos.broker_orders.add(broker_order)

    mock_adapter = AsyncMock()
    mock_result = AsyncMock()
    mock_result.status = OrderStatus.FILLED
    mock_adapter.resolve_unknown_state = AsyncMock(return_value=mock_result)

    with patch.object(
        dry_worker,
        "_build_adapter_for_broker_account",
        new_callable=AsyncMock,
        return_value=mock_adapter,
    ):
        result = await dry_worker.process_run(run)

    # Then: result says resolved...
    assert result.status == "resolved"
    assert result.orders_processed == 1

    # But the run status was NOT changed (dry run)
    fetched = await repos.reconciliations.get_run(run.reconciliation_run_id)
    assert fetched is not None
    assert fetched.status == "started"


@pytest.mark.asyncio
async def test_process_run_multiple_orders_partial_fail(
    repos: RepositoryContainer,
    service: ReconciliationService,
    worker: ReconciliationRunProcessor,
    account_id: UUID,
) -> None:
    """Partial resolution (some succeed, some fail) → run fails."""
    # Given: seeded koreainvestment account
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="koreainvestment",
        account_ref="test-account-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="KIS-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    # Create run with two order links
    order_a = uuid4()
    order_b = uuid4()
    run = await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=order_a,
    )
    # Manually attach a second link
    await service.attach_order_mismatch(
        reconciliation_run_id=run.reconciliation_run_id,
        order_request_id=order_b,
        mismatch_type="pending_inquiry",
        details={"trigger_type": "requires_reconciliation"},
    )

    # Add broker orders for both
    for oid in (order_a, order_b):
        bo = BrokerOrderEntity(
            broker_order_id=uuid4(),
            order_request_id=oid,
            broker_name="koreainvestment",
            broker_status="UNKNOWN",
            broker_native_order_id=f"NATIVE-{oid}",
            last_synced_at=datetime.now(timezone.utc),
        )
        await repos.broker_orders.add(bo)

    # Mock adapter: first succeeds, second raises
    mock_adapter = AsyncMock()
    mock_result = AsyncMock()
    mock_result.status = OrderStatus.FILLED
    mock_adapter.resolve_unknown_state = AsyncMock(
        side_effect=[mock_result, RuntimeError("Broker error")],
    )

    with patch.object(
        worker,
        "_build_adapter_for_broker_account",
        new_callable=AsyncMock,
        return_value=mock_adapter,
    ):
        result = await worker.process_run(run)

    # Then: run failed
    assert result.status == "failed"
    assert result.orders_processed == 2
    assert result.orders_resolved == 1

    fetched = await repos.reconciliations.get_run(run.reconciliation_run_id)
    assert fetched is not None
    assert fetched.status == "failed"


# =========================================================================
# Edge Cases
# =========================================================================


@pytest.mark.asyncio
async def test_process_run_idempotent_started_only(
    repos: RepositoryContainer,
    service: ReconciliationService,
    worker: ReconciliationRunProcessor,
    account_id: UUID,
) -> None:
    """list_pending_runs only returns 'started' runs, ensuring idempotency."""
    # Given: pre-seeded account
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    run = await service.trigger(account_id, trigger_type="test")
    await service.mark_resolved(run.reconciliation_run_id)

    # When: already resolved
    pending = await repos.reconciliations.list_pending_runs()

    # Then: not returned
    assert len(pending) == 0


@pytest.mark.asyncio
async def test_service_list_pending_runs(
    repos: RepositoryContainer,
    service: ReconciliationService,
    account_id: UUID,
) -> None:
    """Service-level list_pending_runs() delegates to repository."""
    # Given: pre-seeded account
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="TEST_BROKER",
        account_ref="test-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.broker/api",
        status="active",
        broker_account_code="TEST-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)
    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    await service.trigger(account_id, trigger_type="test")

    pending = await service.list_pending_runs()
    assert len(pending) == 1
    assert pending[0].status == "started"


@pytest.mark.asyncio
async def test_service_get_run_order_links(
    seeded_run: ReconciliationRunEntity,
    service: ReconciliationService,
    order_request_id: UUID,
) -> None:
    """Service-level get_run_order_links() delegates to repository."""
    links = await service.get_run_order_links(seeded_run.reconciliation_run_id)
    assert len(links) == 1
    assert links[0].order_request_id == order_request_id


# =========================================================================
# Phase 3: Worker — KIS BrokerAdapter Integration
# =========================================================================


@pytest.fixture
def settings() -> AppSettings:
    """AppSettings with test-safe defaults (real env not needed)."""
    return AppSettings()


@pytest.fixture
async def worker_with_settings(
    repos: RepositoryContainer,
    service: ReconciliationService,
    settings: AppSettings,
) -> ReconciliationRunProcessor:
    """Worker with in-memory repos + settings; dry_run=False."""
    return ReconciliationRunProcessor(
        repos=repos,
        reconciliation_service=service,
        settings=settings,
        dry_run=False,
    )


@pytest.fixture
async def seeded_kis_run(
    repos: RepositoryContainer,
    service: ReconciliationService,
    account_id: UUID,
    order_request_id: UUID,
) -> ReconciliationRunEntity:
    """Create a reconciliation run with a koreainvestment broker account."""
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="koreainvestment",
        account_ref="12345678-01",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.kis.com",
        status="active",
        broker_account_code="KIS-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)

    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="KIS Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    return await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=order_request_id,
    )


# ── Test 1: _build_adapter_for_broker_account ────────────────────────────


@pytest.mark.asyncio
async def test_build_adapter_for_broker_account(
    repos: RepositoryContainer,
    worker_with_settings: ReconciliationRunProcessor,
) -> None:
    """_build_adapter_for_broker_account creates & authenticates a KIS adapter."""
    # Given: a koreainvestment broker account in the repo
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="koreainvestment",
        account_ref="12345678-01",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.kis.com",
        status="active",
        broker_account_code="KIS-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)

    # When: building adapter → mock the lazy imports inside the method
    with (
        patch(
            "agent_trading.brokers.koreainvestment.rest_client.KISRestClient",
        ) as MockKISRestClient,
        patch(
            "agent_trading.brokers.koreainvestment.adapter.KoreaInvestmentAdapter",
        ) as MockKISAdapter,
    ):
        mock_rest_client = AsyncMock()
        MockKISRestClient.return_value = mock_rest_client

        mock_session = AsyncMock()
        mock_session.metadata = {"token_prefix": "test-token"}

        mock_adapter = AsyncMock()
        mock_adapter.authenticate = AsyncMock(return_value=mock_session)
        MockKISAdapter.return_value = mock_adapter

        result = await worker_with_settings._build_adapter_for_broker_account(
            broker_account_id=broker_account_id,
            broker_name="koreainvestment",
        )

    # Then: adapter is created, authenticated, and returned
    assert result is mock_adapter

    # Verify REST client constructed with correct settings-driven params
    MockKISRestClient.assert_called_once_with(
        api_key=worker_with_settings.settings.kis_api_key,
        api_secret=worker_with_settings.settings.kis_api_secret,
        account_number="12345678-01",
        account_product_code=worker_with_settings.settings.kis_account_product_code,
        env=worker_with_settings.settings.kis_env,
        base_url=worker_with_settings.settings.kis_base_url,
    )
    MockKISAdapter.assert_called_once_with(rest_client=mock_rest_client)
    mock_adapter.authenticate.assert_awaited_once()


# ── Test 2: broker account not found ─────────────────────────────────────


@pytest.mark.asyncio
async def test_build_adapter_for_broker_account_not_found(
    worker_with_settings: ReconciliationRunProcessor,
) -> None:
    """_build_adapter_for_broker_account returns None when entity not found."""
    result = await worker_with_settings._build_adapter_for_broker_account(
        broker_account_id=uuid4(),
        broker_name="koreainvestment",
    )
    assert result is None


# ── Test 3: broker_name != "koreainvestment" ──────────────────────────────


@pytest.mark.asyncio
async def test_build_adapter_for_broker_name_not_kis(
    worker_with_settings: ReconciliationRunProcessor,
) -> None:
    """_build_adapter_for_broker_account returns None for non-KIS brokers."""
    result = await worker_with_settings._build_adapter_for_broker_account(
        broker_account_id=uuid4(),
        broker_name="some_other_broker",
    )
    assert result is None


# ── Test 4: account-level adapter cache reuse ────────────────────────────


@pytest.mark.asyncio
async def test_account_level_auth_reuse(
    repos: RepositoryContainer,
    worker_with_settings: ReconciliationRunProcessor,
    account_id: UUID,
) -> None:
    """_get_or_create_broker returns cached adapter on second call."""
    # Given: a seeded broker account
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="koreainvestment",
        account_ref="12345678-01",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.kis.com",
        status="active",
        broker_account_code="KIS-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)

    with (
        patch(
            "agent_trading.brokers.koreainvestment.rest_client.KISRestClient",
        ) as MockKISRestClient,
        patch(
            "agent_trading.brokers.koreainvestment.adapter.KoreaInvestmentAdapter",
        ) as MockKISAdapter,
    ):
        MockKISRestClient.return_value = AsyncMock()
        mock_adapter = AsyncMock()
        mock_adapter.authenticate = AsyncMock(return_value=AsyncMock())
        MockKISAdapter.return_value = mock_adapter

        # First call → builds adapter
        result1 = await worker_with_settings._get_or_create_broker(
            account_id, broker_account,
        )
        # Second call → should return cached adapter
        result2 = await worker_with_settings._get_or_create_broker(
            account_id, broker_account,
        )

    # Then: same object, only one creation
    assert result1 is result2
    assert MockKISRestClient.call_count == 1
    assert mock_adapter.authenticate.call_count == 1


# ── Test 5: resolve_unknown_state → terminal status → resolved ────────────


@pytest.mark.asyncio
async def test_resolve_unknown_state_success(
    repos: RepositoryContainer,
    worker_with_settings: ReconciliationRunProcessor,
    account_id: UUID,
    order_request_id: UUID,
    run_id: UUID,
) -> None:
    """_process_order_link returns "resolved" when broker returns terminal status."""
    # Given: a broker order with unknown status
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order_request_id,
        broker_name="koreainvestment",
        broker_status="UNKNOWN",
        broker_native_order_id="NATIVE-001",
        last_synced_at=datetime.now(timezone.utc),
    )
    await repos.broker_orders.add(broker_order)

    run = ReconciliationRunEntity(
        reconciliation_run_id=run_id,
        account_id=account_id,
        trigger_type="test",
        status="started",
        started_at=datetime.now(timezone.utc),
    )
    link = ReconciliationOrderLinkEntity(
        reconciliation_run_id=run_id,
        order_request_id=order_request_id,
        mismatch_type="pending_inquiry",
    )

    # Mock adapter returns FILLED (terminal)
    adapter = AsyncMock()
    mock_result = AsyncMock()
    mock_result.status = OrderStatus.FILLED
    adapter.resolve_unknown_state = AsyncMock(return_value=mock_result)

    # When
    result = await worker_with_settings._process_order_link(
        run, link, adapter, "12345678-01",
    )

    # Then
    assert result == "resolved"
    adapter.resolve_unknown_state.assert_awaited_once_with(
        account_ref="12345678-01",
        client_order_id=None,
        broker_order_id="NATIVE-001",
    )


# ── Test 6: resolve_unknown_state → non-terminal → failed ─────────────────


@pytest.mark.asyncio
async def test_resolve_unknown_state_truth_unavailable(
    repos: RepositoryContainer,
    worker_with_settings: ReconciliationRunProcessor,
    account_id: UUID,
    order_request_id: UUID,
    run_id: UUID,
) -> None:
    """_process_order_link returns "failed" when broker returns non-terminal status."""
    # Given: a broker order
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order_request_id,
        broker_name="koreainvestment",
        broker_status="UNKNOWN",
        broker_native_order_id="NATIVE-001",
        last_synced_at=datetime.now(timezone.utc),
    )
    await repos.broker_orders.add(broker_order)

    run = ReconciliationRunEntity(
        reconciliation_run_id=run_id,
        account_id=account_id,
        trigger_type="test",
        status="started",
        started_at=datetime.now(timezone.utc),
    )
    link = ReconciliationOrderLinkEntity(
        reconciliation_run_id=run_id,
        order_request_id=order_request_id,
        mismatch_type="pending_inquiry",
    )

    # Mock adapter returns SUBMITTED (non-terminal)
    adapter = AsyncMock()
    mock_result = AsyncMock()
    mock_result.status = OrderStatus.SUBMITTED
    adapter.resolve_unknown_state = AsyncMock(return_value=mock_result)

    # When
    result = await worker_with_settings._process_order_link(
        run, link, adapter, "12345678-01",
    )

    # Then
    assert result == "failed"


# ── Test 7: resolve_unknown_state → exception → failed ────────────────────


@pytest.mark.asyncio
async def test_resolve_unknown_state_inquiry_failure(
    repos: RepositoryContainer,
    worker_with_settings: ReconciliationRunProcessor,
    account_id: UUID,
    order_request_id: UUID,
    run_id: UUID,
) -> None:
    """_process_order_link returns "failed" when adapter raises."""
    # Given: a broker order
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order_request_id,
        broker_name="koreainvestment",
        broker_status="UNKNOWN",
        broker_native_order_id="NATIVE-001",
        last_synced_at=datetime.now(timezone.utc),
    )
    await repos.broker_orders.add(broker_order)

    run = ReconciliationRunEntity(
        reconciliation_run_id=run_id,
        account_id=account_id,
        trigger_type="test",
        status="started",
        started_at=datetime.now(timezone.utc),
    )
    link = ReconciliationOrderLinkEntity(
        reconciliation_run_id=run_id,
        order_request_id=order_request_id,
        mismatch_type="pending_inquiry",
    )

    # Mock adapter raises
    adapter = AsyncMock()
    adapter.resolve_unknown_state = AsyncMock(
        side_effect=RuntimeError("KIS API timeout"),
    )

    # When
    result = await worker_with_settings._process_order_link(
        run, link, adapter, "12345678-01",
    )

    # Then: gracefully returns "failed"
    assert result == "failed"


# ── Test 8: authentication failure → retained + worker continues ──────────


@pytest.mark.asyncio
async def test_authenticate_failure_worker_continues(
    repos: RepositoryContainer,
    service: ReconciliationService,
    worker_with_settings: ReconciliationRunProcessor,
    account_id: UUID,
    order_request_id: UUID,
) -> None:
    """Adapter auth failure → run is retained; worker continues."""
    # Given: a seeded KIS run
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="koreainvestment",
        account_ref="12345678-01",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.kis.com",
        status="active",
        broker_account_code="KIS-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)

    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="KIS Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    run = await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=order_request_id,
    )

    # When: _build_adapter_for_broker_account returns None (auth failure)
    with patch.object(
        worker_with_settings,
        "_build_adapter_for_broker_account",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await worker_with_settings.process_run(run)

    # Then: run retained (not failed)
    assert result.status == "retained"
    assert result.error == "broker_adapter_creation_failed"

    # Verify run status is still 'started' (retained, not failed)
    fetched = await repos.reconciliations.get_run(run.reconciliation_run_id)
    assert fetched is not None
    assert fetched.status == "started"


# ── Test 9: adapter creation exception → graceful degradation ─────────────


@pytest.mark.asyncio
async def test_broker_adapter_creation_failure_graceful(
    repos: RepositoryContainer,
    service: ReconciliationService,
    worker_with_settings: ReconciliationRunProcessor,
    account_id: UUID,
    order_request_id: UUID,
) -> None:
    """Exception during adapter creation → graceful degradation (retained)."""
    # Given: a seeded KIS run
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="koreainvestment",
        account_ref="12345678-01",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.kis.com",
        status="active",
        broker_account_code="KIS-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)

    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="KIS Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    run = await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=order_request_id,
    )

    # When: _build_adapter_for_broker_account raises
    with patch.object(
        worker_with_settings,
        "_build_adapter_for_broker_account",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Unexpected adapter error"),
    ):
        result = await worker_with_settings.process_run(run)

    # Then: run retained (exception caught by process_run try/except)
    assert result.status == "retained"
    assert result.error is not None
    assert "broker_adapter_creation_failed" in (result.error or "")

    fetched = await repos.reconciliations.get_run(run.reconciliation_run_id)
    assert fetched is not None
    assert fetched.status == "started"


# ── Test 10: full process_run with broker adapter ─────────────────────────


@pytest.mark.asyncio
async def test_process_run_with_broker_adapter(
    repos: RepositoryContainer,
    service: ReconciliationService,
    worker_with_settings: ReconciliationRunProcessor,
    account_id: UUID,
    order_request_id: UUID,
) -> None:
    """Full run processing with mocked broker adapter."""
    # Given: seeded KIS run
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="koreainvestment",
        account_ref="12345678-01",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.kis.com",
        status="active",
        broker_account_code="KIS-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)

    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="KIS Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    run = await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=order_request_id,
    )

    # Add broker order
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order_request_id,
        broker_name="koreainvestment",
        broker_status="UNKNOWN",
        broker_native_order_id="NATIVE-001",
        last_synced_at=datetime.now(timezone.utc),
    )
    await repos.broker_orders.add(broker_order)

    # Mock the adapter returned by _build_adapter_for_broker_account
    mock_adapter = AsyncMock()
    mock_result = AsyncMock()
    mock_result.status = OrderStatus.FILLED
    mock_adapter.resolve_unknown_state = AsyncMock(return_value=mock_result)

    with patch.object(
        worker_with_settings,
        "_build_adapter_for_broker_account",
        new_callable=AsyncMock,
        return_value=mock_adapter,
    ):
        result = await worker_with_settings.process_run(run)

    # Then: run successfully resolved
    assert result.status == "resolved"
    assert result.orders_processed == 1
    assert result.orders_resolved == 1

    # Verify adapter was called with correct params
    mock_adapter.resolve_unknown_state.assert_awaited_once_with(
        account_ref="12345678-01",
        client_order_id=None,
        broker_order_id="NATIVE-001",
    )

    # Verify run status updated in repo
    fetched = await repos.reconciliations.get_run(run.reconciliation_run_id)
    assert fetched is not None
    assert fetched.status == "resolved"


# ── Test 11: process_run reports cycle summary ────────────────────────────


@pytest.mark.asyncio
async def test_process_cycle_summary(
    repos: RepositoryContainer,
    service: ReconciliationService,
    worker_with_settings: ReconciliationRunProcessor,
    account_id: UUID,
    order_request_id: UUID,
) -> None:
    """process_run returns a ProcessingResult with correct summary counts."""
    # Given: seeded KIS run
    broker_account_id = uuid4()
    broker_account = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name="koreainvestment",
        account_ref="12345678-01",
        environment=Environment.PAPER,
        credential_ref="test-cred",
        base_url="https://test.kis.com",
        status="active",
        broker_account_code="KIS-PAPER-****0001",
    )
    await repos.broker_accounts.add(broker_account)

    account = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="KIS Test Account",
        account_masked="****5678",
        status="active",
    )
    await repos.accounts.add(account)

    run = await service.trigger_and_link(
        account_id=account_id,
        trigger_type="requires_reconciliation",
        order_request_id=order_request_id,
    )

    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order_request_id,
        broker_name="koreainvestment",
        broker_status="UNKNOWN",
        broker_native_order_id="NATIVE-001",
        last_synced_at=datetime.now(timezone.utc),
    )
    await repos.broker_orders.add(broker_order)

    mock_adapter = AsyncMock()
    mock_result = AsyncMock()
    mock_result.status = OrderStatus.FILLED
    mock_adapter.resolve_unknown_state = AsyncMock(return_value=mock_result)

    with patch.object(
        worker_with_settings,
        "_build_adapter_for_broker_account",
        new_callable=AsyncMock,
        return_value=mock_adapter,
    ):
        result = await worker_with_settings.process_run(run)

    # Verify ProcessingResult fields
    assert result.run_id == run.reconciliation_run_id
    assert result.status in ("resolved", "failed", "retained", "skipped_no_links", "escalated")
    assert isinstance(result.orders_processed, int)
    assert isinstance(result.orders_resolved, int)
    assert result.orders_processed >= 1
    assert result.orders_resolved >= 0
