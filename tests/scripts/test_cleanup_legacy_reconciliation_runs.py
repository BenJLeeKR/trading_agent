"""Tests for ``scripts.cleanup_legacy_reconciliation_runs``.

검증 범위
---------
1. ``list_legacy_runs`` — link 없는 started run 식별
2. ``halt_run`` — halted 상태 전이 + summary_json
3. ``cleanup_with_replacement`` — 관련 주문 있을 때 replacement 생성
4. ``dry_run_no_changes`` — dry-run 시 변경 없음
5. ``idempotency`` — 이미 처리된 run 재처리 금지
6. ``linked_run_unaffected`` — 기존 linked run 영향 없음
7. ``run_id_filter`` — 특정 run_id 필터
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    InstrumentEntity,
    OrderRequestEntity,
    ReconciliationRunEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.reconciliation_service import ReconciliationService
from scripts.cleanup_legacy_reconciliation_runs import parse_args, cleanup_legacy_runs

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repos() -> RepositoryContainer:
    return build_in_memory_repositories()


@pytest.fixture
def service(repos: RepositoryContainer) -> ReconciliationService:
    return ReconciliationService(repos)


def _legacy_run(
    repos: RepositoryContainer,
    account_id: UUID | None = None,
    run_id: UUID | None = None,
    trigger_type: str = "manual",
) -> ReconciliationRunEntity:
    """Create a legacy run (started, no order links)."""
    now = datetime.now(timezone.utc)
    run = ReconciliationRunEntity(
        reconciliation_run_id=run_id or uuid4(),
        account_id=account_id or uuid4(),
        trigger_type=trigger_type,
        status="started",
        started_at=now,
        mismatch_count=0,
        summary_json={},
        created_at=now,
    )
    repos.reconciliations._runs[run.reconciliation_run_id] = run  # type: ignore[attr-defined]
    return run


def _linked_run(
    repos: RepositoryContainer,
    account_id: UUID | None = None,
) -> ReconciliationRunEntity:
    """Create a run WITH an order link (not legacy)."""
    now = datetime.now(timezone.utc)
    run = ReconciliationRunEntity(
        reconciliation_run_id=uuid4(),
        account_id=account_id or uuid4(),
        trigger_type="requires_reconciliation",
        status="started",
        started_at=now,
        mismatch_count=0,
        summary_json={},
        created_at=now,
    )
    repos.reconciliations._runs[run.reconciliation_run_id] = run  # type: ignore[attr-defined]
    # Attach an order link
    repos.reconciliations._order_links[run.reconciliation_run_id].append(  # type: ignore[attr-defined]
        {
            "order_request_id": uuid4(),
            "mismatch_type": "pending_inquiry",
            "details": {},
        }
    )
    return run


def _stuck_order(
    repos: RepositoryContainer,
    account_id: UUID | None = None,
    status: OrderStatus = OrderStatus.RECONCILE_REQUIRED,
) -> OrderRequestEntity:
    """Create a stuck RECONCILE_REQUIRED order."""
    now = datetime.now(timezone.utc)
    order = OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id or uuid4(),
        instrument_id=uuid4(),
        client_order_id=f"test-{uuid4().hex[:8]}",
        idempotency_key=f"ik-{uuid4().hex[:12]}",
        correlation_id=f"corr-{uuid4().hex[:8]}",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        requested_quantity=10,
        status=status,
        time_in_force=TimeInForce.DAY,
        created_at=now,
        updated_at=now,
    )
    repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]
    return order


def _add_instrument(
    repos: RepositoryContainer,
    instrument_id: UUID,
    symbol: str = "005930",
) -> None:
    """Add an instrument to the in-memory repository."""
    instr = InstrumentEntity(
        instrument_id=instrument_id,
        symbol=symbol,
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="Test Instrument",
    )
    repos.instruments._items[instrument_id] = instr  # type: ignore[attr-defined]


def _halt_run(
    repos: RepositoryContainer,
    run_id: UUID,
) -> None:
    """Directly halt a run in the in-memory repo (for test setup)."""
    run = repos.reconciliations._runs.get(run_id)  # type: ignore[attr-defined]
    if run is not None:
        from dataclasses import replace
        repos.reconciliations._runs[run_id] = replace(  # type: ignore[attr-defined]
            run,
            status="halted",
            completed_at=datetime.now(timezone.utc),
        )


# ---------------------------------------------------------------------------
# CLI 인자 파싱 테스트
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_defaults(self):
        """기본값 확인."""
        args = parse_args([])
        assert args.dry_run is False
        assert args.limit == 50
        assert args.run_id is None
        assert args.account_id is None
        assert args.verbose is False

    def test_dry_run(self):
        """--dry-run 플래그."""
        args = parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_limit(self):
        """--limit 인자."""
        args = parse_args(["--limit", "10"])
        assert args.limit == 10

    def test_run_id(self):
        """--run-id 인자."""
        uid = str(uuid4())
        args = parse_args(["--run-id", uid])
        assert args.run_id == uid

    def test_account_id(self):
        """--account-id 인자."""
        uid = str(uuid4())
        args = parse_args(["--account-id", uid])
        assert args.account_id == uid

    def test_verbose(self):
        """--verbose 플래그."""
        args = parse_args(["--verbose"])
        assert args.verbose is True


# ---------------------------------------------------------------------------
# 1. list_legacy_runs — link 없는 started run 식별
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_legacy_runs(repos, service):
    """list_legacy_runs는 link 없는 started run만 반환한다."""
    account_id = uuid4()
    # Legacy run (started + no links)
    legacy = _legacy_run(repos, account_id=account_id)
    # Linked run (started + with link) — 제외되어야 함
    linked = _linked_run(repos, account_id=account_id)

    runs = await service.list_legacy_runs(limit=50)

    # Legacy run만 포함되어야 함
    run_ids = {r.reconciliation_run_id for r in runs}
    assert legacy.reconciliation_run_id in run_ids
    assert linked.reconciliation_run_id not in run_ids


# ---------------------------------------------------------------------------
# 2. halt_run — halted 상태 전이 + summary_json
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_halt_run(repos, service):
    """halt_run은 run을 halted로 마감하고 summary_json에 이유를 기록한다."""
    account_id = uuid4()
    run = _legacy_run(repos, account_id=account_id)

    updated = await service.halt_run(
        reconciliation_run_id=run.reconciliation_run_id,
        summary_json={"reason": "test_halt", "foo": "bar"},
    )

    assert updated.status == "halted"
    assert updated.completed_at is not None
    assert updated.summary_json.get("reason") == "test_halt"
    assert updated.summary_json.get("foo") == "bar"
    assert "halted_at" in updated.summary_json

    # Repository에서 다시 읽어도 동일
    reloaded = await repos.reconciliations.get_run(run.reconciliation_run_id)
    assert reloaded is not None
    assert reloaded.status == "halted"
    assert reloaded.completed_at is not None

    # 존재하지 않는 run → ValueError
    with pytest.raises(ValueError, match="not found"):
        await service.halt_run(reconciliation_run_id=uuid4())


# ---------------------------------------------------------------------------
# 3. cleanup_with_replacement — 관련 주문 있을 때 replacement 생성
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_with_replacement(repos, service):
    """RECONCILE_REQUIRED 주문이 있으면 replacement run을 생성하고 legacy run을 halted로 마감한다."""
    account_id = uuid4()
    legacy = _legacy_run(repos, account_id=account_id)
    order = _stuck_order(repos, account_id=account_id)
    _add_instrument(repos, order.instrument_id)

    args = parse_args([])  # dry-run=false
    exit_code = await cleanup_legacy_runs(repos, args)

    assert exit_code == 0

    # Legacy run이 halted 상태인지 확인
    halted_run = await repos.reconciliations.get_run(legacy.reconciliation_run_id)
    assert halted_run is not None
    assert halted_run.status == "halted"
    assert halted_run.completed_at is not None
    assert halted_run.summary_json.get("reason") == "legacy_run_replaced"
    assert "superseded_by" in halted_run.summary_json

    # Replacement run이 생성되었는지 확인
    superseded_by = halted_run.summary_json["superseded_by"]
    replacement_run = await repos.reconciliations.get_run(UUID(superseded_by))
    assert replacement_run is not None
    assert replacement_run.status == "started"  # trigger_and_link로 생성
    assert replacement_run.account_id == account_id


# ---------------------------------------------------------------------------
# 4. dry_run_no_changes — dry-run 시 변경 없음
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_no_changes(repos, service):
    """Dry-run 모드에서는 어떤 run도 변경되지 않는다."""
    account_id = uuid4()
    legacy = _legacy_run(repos, account_id=account_id)
    order = _stuck_order(repos, account_id=account_id)
    _add_instrument(repos, order.instrument_id)

    args = parse_args(["--dry-run"])
    exit_code = await cleanup_legacy_runs(repos, args)

    assert exit_code == 0

    # Legacy run이 그대로 started 상태인지 확인
    unchanged_run = await repos.reconciliations.get_run(legacy.reconciliation_run_id)
    assert unchanged_run is not None
    assert unchanged_run.status == "started"
    assert unchanged_run.completed_at is None

    # Replacement run이 생성되지 않음
    runs = await repos.reconciliations.list_runs_by_account(account_id)
    assert len(runs) == 1  # legacy run만 존재


# ---------------------------------------------------------------------------
# 5. idempotency — 이미 처리된 run 재처리 금지
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency(repos, service):
    """이미 halted 상태인 run은 list_legacy_runs에서 제외되어 재처리되지 않는다."""
    account_id = uuid4()
    # 이미 halted 상태인 run
    run = _legacy_run(repos, account_id=account_id)
    _halt_run(repos, run.reconciliation_run_id)

    # list_legacy_runs에서 제외됨
    runs = await service.list_legacy_runs(limit=50)
    run_ids = {r.reconciliation_run_id for r in runs}
    assert run.reconciliation_run_id not in run_ids


# ---------------------------------------------------------------------------
# 6. linked_run_unaffected — 기존 linked run 영향 없음
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_linked_run_unaffected(repos, service):
    """기존에 link가 있는 reconciliation run은 영향을 받지 않는다."""
    account_id = uuid4()
    # Link 있는 run
    linked = _linked_run(repos, account_id=account_id)

    # Link 없는 legacy run도 하나 생성
    legacy = _legacy_run(repos, account_id=account_id)

    args = parse_args([])
    exit_code = await cleanup_legacy_runs(repos, args)

    assert exit_code == 0

    # Linked run은 그대로 started 상태 유지
    unchanged_run = await repos.reconciliations.get_run(linked.reconciliation_run_id)
    assert unchanged_run is not None
    assert unchanged_run.status == "started"

    # Legacy run만 처리됨 (주문이 없으므로 단순 halted)
    halted_run = await repos.reconciliations.get_run(legacy.reconciliation_run_id)
    # The legacy may or may not be halted depending on whether there are
    # pending RECONCILE_REQUIRED orders for this account.
    # Since there are no stuck orders, it should be cleaned.
    assert halted_run is not None
    assert halted_run.status == "halted"


# ---------------------------------------------------------------------------
# 7. run_id_filter — 특정 run_id 필터
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_id_filter(repos, service):
    """특정 run_id 필터로 해당 run만 처리된다."""
    account_a = uuid4()
    account_b = uuid4()

    run_a = _legacy_run(repos, account_id=account_a)  # 처리 대상
    run_b = _legacy_run(repos, account_id=account_b)  # 필터에서 제외됨

    # 두 계정 모두 주문 없음 → 단순 halted

    # run_a만 필터링
    args = parse_args(["--run-id", str(run_a.reconciliation_run_id)])
    exit_code = await cleanup_legacy_runs(repos, args)

    assert exit_code == 0

    # run_a가 halted됨
    halted_a = await repos.reconciliations.get_run(run_a.reconciliation_run_id)
    assert halted_a is not None
    assert halted_a.status == "halted"

    # run_b는 변경되지 않음
    unchanged_b = await repos.reconciliations.get_run(run_b.reconciliation_run_id)
    assert unchanged_b is not None
    assert unchanged_b.status == "started"
