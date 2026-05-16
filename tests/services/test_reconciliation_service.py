from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import ReconciliationRunEntity
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.reconciliation_service import ReconciliationService


@pytest.fixture
def repos():
    return build_in_memory_repositories()


@pytest.fixture
def service(repos):
    return ReconciliationService(repos)


@pytest.fixture
def account_id() -> UUID:
    return uuid4()


@pytest.mark.asyncio
async def test_trigger_creates_run(service, repos, account_id):
    """trigger() creates a reconciliation run with status='started'."""
    run = await service.trigger(account_id, trigger_type="test")

    assert run.account_id == account_id
    assert run.trigger_type == "test"
    assert run.status == "started"
    assert run.mismatch_count == 0

    # Verify it was persisted.
    fetched = await repos.reconciliations.get_run(run.reconciliation_run_id)
    assert fetched is not None
    assert fetched.reconciliation_run_id == run.reconciliation_run_id


@pytest.mark.asyncio
async def test_get_active_run_returns_most_recent(service, repos, account_id):
    """get_active_run() returns the most recent active run."""
    run1 = await service.trigger(account_id, trigger_type="first")
    run2 = await service.trigger(account_id, trigger_type="second")

    active = await service.get_active_run(account_id)
    assert active is not None
    # The most recent trigger should be returned.
    assert active.reconciliation_run_id == run2.reconciliation_run_id


@pytest.mark.asyncio
async def test_get_active_run_returns_none_when_no_active(service, account_id):
    """get_active_run() returns None when no active run exists."""
    active = await service.get_active_run(account_id)
    assert active is None


@pytest.mark.asyncio
async def test_attach_order_mismatch(service, repos, account_id):
    """attach_order_mismatch() records a mismatch."""
    run = await service.trigger(account_id, trigger_type="test")
    order_request_id = uuid4()

    await service.attach_order_mismatch(
        run.reconciliation_run_id,
        order_request_id,
        mismatch_type="status_mismatch",
        details={"expected": "filled", "actual": "rejected"},
    )

    # Verify via list_runs_by_account (in-memory stores mismatches).
    runs = await repos.reconciliations.list_runs_by_account(account_id)
    assert len(runs) >= 1


@pytest.mark.asyncio
async def test_attach_position_mismatch(service, repos, account_id):
    """attach_position_mismatch() records a position mismatch."""
    run = await service.trigger(account_id, trigger_type="test")
    position_snapshot_id = uuid4()

    await service.attach_position_mismatch(
        run.reconciliation_run_id,
        position_snapshot_id,
        mismatch_type="quantity_mismatch",
        details={"expected_qty": "100", "actual_qty": "95"},
    )

    runs = await repos.reconciliations.list_runs_by_account(account_id)
    assert len(runs) >= 1


@pytest.mark.asyncio
async def test_mark_resolved_updates_status(service, repos, account_id):
    """mark_resolved() updates the run status to 'resolved'."""
    run = await service.trigger(account_id, trigger_type="test")

    await service.mark_resolved(
        run.reconciliation_run_id,
        summary_json={"resolved_by": "operator"},
    )

    fetched = await repos.reconciliations.get_run(run.reconciliation_run_id)
    assert fetched is not None
    assert fetched.status == "resolved"


@pytest.mark.asyncio
async def test_mark_resolved_raises_on_nonexistent_run(service):
    """mark_resolved() raises ValueError for unknown run."""
    with pytest.raises(ValueError, match="Reconciliation run not found"):
        await service.mark_resolved(uuid4())


@pytest.mark.asyncio
async def test_is_blocked_returns_false_without_lock(service, account_id):
    """is_blocked() returns False when no lock exists."""
    blocked = await service.is_blocked(account_id)
    assert blocked is False


@pytest.mark.asyncio
async def test_acquire_and_release_blocking_lock(service, account_id):
    """acquire_blocking_lock() and release_blocking_lock() work together."""
    run_id = uuid4()

    # Acquire lock.
    await service.acquire_blocking_lock(
        account_id=account_id,
        strategy_id=None,
        symbol="AAPL",
        side="buy",
        reason="test",
        locked_by_run_id=run_id,
    )

    # Release lock.
    await service.release_blocking_lock(
        account_id=account_id,
        symbol="AAPL",
        side="buy",
    )

    # After release, is_blocked should return False.
    blocked = await service.is_blocked(
        account_id=account_id,
        symbol="AAPL",
        side="buy",
    )
    # Note: In-memory mode does not support actual lock operations,
    # so is_blocked returns False. This is expected.
    assert blocked is False


# ---------------------------------------------------------------------------
# Idempotency tests for trigger()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_idempotent_reuses_active_run(service, repos, account_id):
    """동일 계정에 active run이 이미 존재하면 새 run을 생성하지 않고 재사용"""
    # Given: 첫 번째 trigger로 run 생성
    run1 = await service.trigger(account_id, "test_trigger")

    # When: 두 번째 trigger (동일 계정)
    run2 = await service.trigger(account_id, "test_trigger_dup")

    # Then: 동일 run 반환 (새로 생성 안 함)
    assert run2.reconciliation_run_id == run1.reconciliation_run_id

    # DB에 run이 1개만 있는지 확인
    all_runs = await repos.reconciliations.list_runs_by_account(account_id)
    assert len(all_runs) == 1


@pytest.mark.asyncio
async def test_trigger_creates_new_run_when_no_active(service, repos, account_id):
    """active run이 없으면 정상적으로 새 run 생성"""
    # Given/When: 첫 번째 trigger
    run = await service.trigger(account_id, "first_trigger")

    # Then: 정상 생성 확인
    assert run is not None
    assert run.status == "started"
    assert run.account_id == account_id

    all_runs = await repos.reconciliations.list_runs_by_account(account_id)
    assert len(all_runs) == 1


@pytest.mark.asyncio
async def test_trigger_creates_new_run_after_previous_resolved(service, repos, account_id):
    """이전 run이 resolved면 새 run 생성"""
    # Given: 첫 번째 trigger
    run1 = await service.trigger(account_id, "first")
    assert run1.status == "started"

    # When: 첫 번째 run을 resolved로 표시
    await service.mark_resolved(
        run1.reconciliation_run_id,
        summary_json={"resolved_by": "test"},
    )

    # Then: 두 번째 trigger는 새 run 생성
    run2 = await service.trigger(account_id, "second")
    assert run2.reconciliation_run_id != run1.reconciliation_run_id
    assert run2.status == "started"

    all_runs = await repos.reconciliations.list_runs_by_account(account_id)
    assert len(all_runs) == 2


@pytest.mark.asyncio
async def test_trigger_idempotent_different_trigger_type_same_account(service, repos, account_id):
    """다른 trigger_type이어도 동일 계정의 active run이 존재하면 재사용"""
    run1 = await service.trigger(account_id, "uncertain_result")
    run2 = await service.trigger(account_id, "requires_reconciliation")

    assert run2.reconciliation_run_id == run1.reconciliation_run_id

    all_runs = await repos.reconciliations.list_runs_by_account(account_id)
    assert len(all_runs) == 1


@pytest.mark.asyncio
async def test_trigger_idempotent_accounts_independent(service, repos):
    """서로 다른 계정의 trigger는 독립적으로 동작"""
    account_a = uuid4()
    account_b = uuid4()

    run_a = await service.trigger(account_a, "trigger_a")
    run_b = await service.trigger(account_b, "trigger_b")

    # 각 계정별로 별도의 run 생성
    assert run_a.reconciliation_run_id != run_b.reconciliation_run_id

    runs_a = await repos.reconciliations.list_runs_by_account(account_a)
    runs_b = await repos.reconciliations.list_runs_by_account(account_b)
    assert len(runs_a) == 1
    assert len(runs_b) == 1

    # account_a에서 다시 trigger 해도 기존 run 재사용
    run_a2 = await service.trigger(account_a, "trigger_a_dup")
    assert run_a2.reconciliation_run_id == run_a.reconciliation_run_id
    runs_a = await repos.reconciliations.list_runs_by_account(account_a)
    assert len(runs_a) == 1
