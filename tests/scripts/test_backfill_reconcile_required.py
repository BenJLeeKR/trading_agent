"""Tests for ``scripts.backfill_reconcile_required_orders``.

검증 범위
---------
1. ``parse_args()`` — CLI 인자 파싱 정확성
2. ``run_backfill()`` — in-memory repository 기반 backfill 로직:
   - stuck 주문 → trigger() 호출 → reconciliation run 생성
   - active run 존재 → skip/재사용 (idempotency)
   - dry-run → trigger() 미호출
   - 특정 order_id 필터 → 대상만 처리
   - stuck 주문 없음 → scanned=0
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    BrokerOrderEntity,
    InstrumentEntity,
    OrderRequestEntity,
    ReconciliationRunEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from scripts.backfill_reconcile_required_orders import TRIGGER_TYPE, parse_args, run_backfill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repos() -> RepositoryContainer:
    return build_in_memory_repositories()


def _stuck_order(
    account_id: UUID | None = None,
    order_request_id: UUID | None = None,
    side: OrderSide = OrderSide.BUY,
) -> OrderRequestEntity:
    """Create a stuck RECONCILE_REQUIRED order."""
    now = datetime.now(timezone.utc)
    return OrderRequestEntity(
        order_request_id=order_request_id or uuid4(),
        account_id=account_id or uuid4(),
        instrument_id=uuid4(),
        client_order_id=f"test-{uuid4().hex[:8]}",
        idempotency_key=f"ik-{uuid4().hex[:12]}",
        correlation_id=f"corr-{uuid4().hex[:8]}",
        side=side,
        order_type=OrderType.MARKET,
        requested_quantity=10,
        status=OrderStatus.RECONCILE_REQUIRED,
        time_in_force=TimeInForce.DAY,
        created_at=now,
        updated_at=now,
    )


def _add_order(repos: RepositoryContainer, order: OrderRequestEntity) -> None:
    """Add an order to the in-memory repository."""
    repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]


def _add_instrument(
    repos: RepositoryContainer,
    instrument_id: UUID,
    symbol: str = "005930",
    market_code: str = "KRX",
) -> InstrumentEntity:
    """Add an instrument to the in-memory repository."""
    instr = InstrumentEntity(
        instrument_id=instrument_id,
        symbol=symbol,
        market_code=market_code,
        asset_class="kr_stock",
        currency="KRW",
        name="Test Instrument",
    )
    repos.instruments._items[instrument_id] = instr  # type: ignore[attr-defined]
    return instr


def _add_broker_order(
    repos: RepositoryContainer,
    order_request_id: UUID,
    broker_native_order_id: str | None = None,
) -> BrokerOrderEntity:
    """Add a broker order to the in-memory repository."""
    bo = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order_request_id,
        broker_name="koreainvestment",
        broker_status="ACKNOWLEDGED",
        broker_native_order_id=broker_native_order_id or f"broker-{uuid4().hex[:8]}",
        created_at=datetime.now(timezone.utc),
    )
    repos.broker_orders._items[bo.broker_order_id] = bo  # type: ignore[attr-defined]
    return bo


def _active_run(
    repos: RepositoryContainer,
    account_id: UUID,
) -> ReconciliationRunEntity:
    """Create an active (status='started') reconciliation run."""
    now = datetime.now(timezone.utc)
    run = ReconciliationRunEntity(
        reconciliation_run_id=uuid4(),
        account_id=account_id,
        trigger_type=TRIGGER_TYPE,
        status="started",
        started_at=now,
        created_at=now,
    )
    repos.reconciliations._runs[run.reconciliation_run_id] = run  # type: ignore[attr-defined]
    return run


# ---------------------------------------------------------------------------
# CLI 인자 파싱 테스트
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_defaults(self):
        """기본값 확인."""
        args = parse_args([])
        assert args.dry_run is False
        assert args.limit is None
        assert args.order_id is None
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

    def test_order_id(self):
        """--order-id 인자."""
        uid = str(uuid4())
        args = parse_args(["--order-id", uid])
        assert args.order_id == uid

    def test_account_id(self):
        """--account-id 인자."""
        uid = str(uuid4())
        args = parse_args(["--account-id", uid])
        assert args.account_id == uid

    def test_verbose(self):
        """--verbose 플래그."""
        args = parse_args(["--verbose"])
        assert args.verbose is True

    def test_verbose_short(self):
        """-v 단축 플래그."""
        args = parse_args(["-v"])
        assert args.verbose is True


# ---------------------------------------------------------------------------
# Backfill 로직 테스트
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_trigger_creates_run(repos):
    """Stuck 주문이 있으면 trigger()를 호출하여 reconciliation run을 생성한다.

    서로 다른 계정의 주문은 각각 독립적인 reconciliation run을 생성한다.
    동일 계정의 주문은 idempotency에 의해 첫 번째만 trigger되고
    나머지는 재사용(reuse)된다.
    """
    # ── 준비: 서로 다른 계정의 stuck 주문 2개 생성 ──
    order1 = _stuck_order(account_id=uuid4())
    order2 = _stuck_order(account_id=uuid4())
    _add_instrument(repos, order1.instrument_id)
    _add_instrument(repos, order2.instrument_id)
    _add_order(repos, order1)
    _add_order(repos, order2)

    # ── 실행 ──
    args = parse_args([])  # dry-run=false
    exit_code = await run_backfill(repos, args)

    # ── 검증 ──
    assert exit_code == 0

    # 각 계정마다 하나씩 reconciliation run 생성
    runs1 = await repos.reconciliations.list_runs_by_account(order1.account_id)
    assert len(runs1) == 1
    assert runs1[0].account_id == order1.account_id
    assert runs1[0].trigger_type == TRIGGER_TYPE
    assert runs1[0].status == "started"

    runs2 = await repos.reconciliations.list_runs_by_account(order2.account_id)
    assert len(runs2) == 1
    assert runs2[0].account_id == order2.account_id
    assert runs2[0].trigger_type == TRIGGER_TYPE
    assert runs2[0].status == "started"

    # 전체 run 개수 = 2
    all_runs = list(repos.reconciliations._runs.values())  # type: ignore[attr-defined]
    assert len(all_runs) == 2


@pytest.mark.asyncio
async def test_backfill_idempotent_skips_active_run(repos):
    """Active reconciliation run이 이미 존재하면 skip/재사용한다."""
    # ── 준비: stuck 주문 1개 + 이미 active run 존재 ──
    account_id = uuid4()
    order = _stuck_order(account_id=account_id)
    _add_instrument(repos, order.instrument_id)
    _add_order(repos, order)
    existing_run = _active_run(repos, account_id)

    # ── 실행 ──
    args = parse_args([])
    exit_code = await run_backfill(repos, args)

    # ── 검증 ──
    assert exit_code == 0

    # 새로운 run이 생성되지 않았는지 확인 (기존 1개만 유지)
    runs = await repos.reconciliations.list_runs_by_account(account_id)
    assert len(runs) == 1
    assert runs[0].reconciliation_run_id == existing_run.reconciliation_run_id


@pytest.mark.asyncio
async def test_backfill_dry_run_skips_trigger(repos):
    """Dry-run 모드에서는 trigger()가 호출되지 않는다."""
    # ── 준비: stuck 주문 2개 생성 ──
    account_id = uuid4()
    order1 = _stuck_order(account_id=account_id)
    order2 = _stuck_order(account_id=account_id)
    _add_instrument(repos, order1.instrument_id)
    _add_instrument(repos, order2.instrument_id)
    _add_order(repos, order1)
    _add_order(repos, order2)

    # ── 실행 (dry-run) ──
    args = parse_args(["--dry-run"])
    exit_code = await run_backfill(repos, args)

    # ── 검증 ──
    assert exit_code == 0

    # reconciliation run이 생성되지 않아야 함
    runs = await repos.reconciliations.list_runs_by_account(account_id)
    assert len(runs) == 0


@pytest.mark.asyncio
async def test_backfill_order_id_filter(repos):
    """특정 order_id 필터가 적용되어 대상 주문만 처리된다."""
    # ── 준비: 3개 주문 (2개는 동일 계정, 1개는 다른 계정) ──
    account_id = uuid4()
    target_order_id = uuid4()
    order1 = _stuck_order(account_id=account_id, order_request_id=target_order_id)
    order2 = _stuck_order(account_id=account_id)  # 필터에서 제외됨
    order3 = _stuck_order(account_id=uuid4())  # 다른 계정
    _add_instrument(repos, order1.instrument_id)
    _add_instrument(repos, order2.instrument_id)
    _add_instrument(repos, order3.instrument_id)
    _add_order(repos, order1)
    _add_order(repos, order2)
    _add_order(repos, order3)

    # ── 실행 (특정 order_id만) ──
    args = parse_args(["--order-id", str(target_order_id)])
    exit_code = await run_backfill(repos, args)

    # ── 검증 ──
    assert exit_code == 0

    # target_order_id에 대한 run만 생성됨
    runs_target = await repos.reconciliations.list_runs_by_account(account_id)
    assert len(runs_target) == 1  # order1만 trigger

    # order2는 trigger되지 않음
    runs_all = list(repos.reconciliations._runs.values())  # type: ignore[attr-defined]
    assert len(runs_all) == 1


@pytest.mark.asyncio
async def test_backfill_no_stuck_orders(repos):
    """Stuck 주문이 없으면 scanned=0, trigger=0."""
    # ── 준비: RECONCILE_REQUIRED가 아닌 주문만 생성 ──
    account_id = uuid4()
    now = datetime.now(timezone.utc)
    non_stuck = OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id,
        instrument_id=uuid4(),
        client_order_id="test-normal",
        idempotency_key=f"ik-{uuid4().hex[:12]}",
        correlation_id=f"corr-{uuid4().hex[:8]}",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        requested_quantity=10,
        status=OrderStatus.ACKNOWLEDGED,  # NOT RECONCILE_REQUIRED
        time_in_force=TimeInForce.DAY,
        created_at=now,
        updated_at=now,
    )
    _add_instrument(repos, non_stuck.instrument_id)
    _add_order(repos, non_stuck)

    # ── 실행 ──
    args = parse_args([])
    exit_code = await run_backfill(repos, args)

    # ── 검증 ──
    assert exit_code == 0

    # run이 생성되지 않음
    runs = await repos.reconciliations.list_runs_by_account(account_id)
    assert len(runs) == 0


@pytest.mark.asyncio
async def test_backfill_account_id_filter(repos):
    """특정 account_id 필터가 적용되어 해당 계정의 주문만 처리된다."""
    # ── 준비: 2개 계정에 각각 stuck 주문 ──
    account_a = uuid4()
    account_b = uuid4()
    order_a = _stuck_order(account_id=account_a)
    order_b = _stuck_order(account_id=account_b)
    _add_instrument(repos, order_a.instrument_id)
    _add_instrument(repos, order_b.instrument_id)
    _add_order(repos, order_a)
    _add_order(repos, order_b)

    # ── 실행 (account_a만) ──
    args = parse_args(["--account-id", str(account_a)])
    exit_code = await run_backfill(repos, args)

    # ── 검증 ──
    assert exit_code == 0

    # account_a에만 run 생성
    runs_a = await repos.reconciliations.list_runs_by_account(account_a)
    assert len(runs_a) == 1

    # account_b에는 run 없음
    runs_b = await repos.reconciliations.list_runs_by_account(account_b)
    assert len(runs_b) == 0


@pytest.mark.asyncio
async def test_backfill_limit_applied(repos):
    """--limit이 적용되어 최대 건수만 처리된다."""
    # ── 준비: 서로 다른 계정의 stuck 주문 5개 생성 ──
    # (동일 계정이면 idempotency에 의해 첫 번째만 trigger되므로)
    for _ in range(5):
        order = _stuck_order(account_id=uuid4())
        _add_instrument(repos, order.instrument_id)
        _add_order(repos, order)

    # ── 실행 (limit=3) ──
    args = parse_args(["--limit", "3"])
    exit_code = await run_backfill(repos, args)

    # ── 검증 ──
    assert exit_code == 0

    # limit=3이므로 3개의 run만 생성됨
    all_runs = list(repos.reconciliations._runs.values())  # type: ignore[attr-defined]
    assert len(all_runs) == 3
