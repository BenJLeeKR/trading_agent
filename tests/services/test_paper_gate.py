"""Tests for ``agent_trading.services.paper_gate`` — Paper Go/No-Go Gate.

Test suites
===========
* :class:`TestPaperGateService` — :class:`PaperGateService` 통합 검증 (7 tests)
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.config.settings import AppSettings
from agent_trading.domain.entities import (
    AccountEntity,
    BlockingLockEntity,
    BrokerOrderEntity,
    CashBalanceSnapshotEntity,
    ClientEntity,
    FillEventEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
    SnapshotSyncRunEntity,
    StrategyEntity,
)
from agent_trading.domain.enums import (
    AssetClass,
    Environment,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.benchmark_comparison import (
    BENCHMARK_KOSPI,
    InMemoryBenchmarkPriceRepository,
    _DEFAULT_BENCHMARK_PRICES,
)
from agent_trading.services.paper_gate import (
    GateStatus,
    OverallStatus,
    PaperGateCheck,
    PaperGoNoGoEvaluation,
    PaperGateService,
)


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

_ACCOUNT_ID = UUID("11111111-1111-1111-1111-111111111111")
_CLIENT_ID = UUID("33333333-3333-3333-3333-333333333333")
_STRATEGY_ID = UUID("22222222-2222-2222-2222-222222222222")
_NOW = datetime(2026, 5, 8, 15, 30, 0, tzinfo=timezone.utc)
_START = date(2026, 5, 1)
_END = date(2026, 5, 8)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


@contextmanager
def _env(**kwargs: object) -> object:
    """Temporarily set environment variables for the duration of the context."""
    old: dict[str, str | None] = {}
    for key, value in kwargs.items():
        env_key = f"PAPER_GATE_{key.upper()}"
        old[env_key] = os.environ.get(env_key)
        os.environ[env_key] = str(value)
    try:
        yield
    finally:
        for env_key, old_value in old.items():
            if old_value is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = old_value


def _seed_base(repos: RepositoryContainer) -> None:
    """Seed minimal reference data (client, account, strategy, cash/position)."""
    # Client
    repos.clients._items[_CLIENT_ID] = ClientEntity(
        client_id=_CLIENT_ID,
        client_code="TEST",
        name="Test Client",
        status="active",
    )

    # Account
    repos.accounts._items[_ACCOUNT_ID] = AccountEntity(
        account_id=_ACCOUNT_ID,
        client_id=_CLIENT_ID,
        broker_account_id=uuid4(),
        environment=Environment.PAPER,
        account_alias="Test Paper",
        account_masked="TEST-****",
        status="active",
    )

    # Strategy
    repos.strategies._items[_STRATEGY_ID] = StrategyEntity(
        strategy_id=_STRATEGY_ID,
        client_id=_CLIENT_ID,
        strategy_code="TEST_STRAT",
        name="Test Strategy",
        asset_class=AssetClass.KR_STOCK,
        status="active",
    )

    # Cash snapshot (10M starting cash, 1 day before start)
    repos.cash_balance_snapshots._items[uuid4()] = CashBalanceSnapshotEntity(
        cash_balance_snapshot_id=uuid4(),
        account_id=_ACCOUNT_ID,
        currency="KRW",
        available_cash=Decimal("10000000"),
        settled_cash=Decimal("10000000"),
        unsettled_cash=Decimal("0"),
        source_of_truth="test",
        snapshot_at=_NOW - timedelta(days=1),
    )

    # Empty position snapshot
    repos.position_snapshots._items[uuid4()] = PositionSnapshotEntity(
        position_snapshot_id=uuid4(),
        account_id=_ACCOUNT_ID,
        instrument_id=uuid4(),
        quantity=Decimal("0"),
        average_price=Decimal("0"),
        market_price=None,
        unrealized_pnl=None,
        source_of_truth="test",
        snapshot_at=_NOW - timedelta(days=1),
    )


def _add_filled_order(
    repos: RepositoryContainer,
    side: OrderSide = OrderSide.BUY,
    quantity: str = "10",
    price: str = "50000",
    fill_timestamp: datetime | None = None,
    strategy_id: UUID | None = _STRATEGY_ID,
) -> None:
    """Add a filled order with broker order + fill event."""
    order_id = uuid4()
    broker_order_id = uuid4()
    ts = fill_timestamp or _NOW

    order = OrderRequestEntity(
        order_request_id=order_id,
        account_id=_ACCOUNT_ID,
        instrument_id=uuid4(),
        client_order_id=f"CLI-{order_id}",
        idempotency_key=f"IDEM-{order_id}",
        correlation_id=f"CORR-{order_id}",
        side=side,
        order_type=OrderType.MARKET,
        requested_quantity=Decimal(quantity),
        requested_price=Decimal(price),
        status=OrderStatus.FILLED,
        time_in_force=TimeInForce.DAY,
        decision_context_id=uuid4() if strategy_id else None,
        submitted_at=ts,
    )
    repos.orders._items[order_id] = order

    bo = BrokerOrderEntity(
        broker_order_id=broker_order_id,
        order_request_id=order_id,
        broker_name="test",
        broker_status="FILLED",
        broker_native_order_id=f"NATIVE-{order_id}",
    )
    repos.broker_orders._items[broker_order_id] = bo

    fill = FillEventEntity(
        fill_event_id=uuid4(),
        broker_order_id=broker_order_id,
        fill_timestamp=ts,
        fill_price=Decimal(price),
        fill_quantity=Decimal(quantity),
        source_channel="test",
        fill_fee=Decimal("0"),
        fill_tax=Decimal("0"),
    )
    repos.fill_events._items[fill.fill_event_id] = fill


def _add_fresh_sync_run(repos: RepositoryContainer) -> None:
    """Add a recent successful snapshot sync run to make health fresh."""
    run = SnapshotSyncRunEntity(
        snapshot_sync_run_id=uuid4(),
        trigger_type="scheduler",
        scope="all",
        dry_run=False,
        total_accounts=1,
        succeeded_accounts=1,
        partial_accounts=0,
        failed_accounts=0,
        skipped_accounts=0,
        positions_synced_total=5,
        positions_skipped_total=0,
        cash_synced_count=1,
        error_count=0,
        status="completed",
        started_at=_NOW - timedelta(minutes=5),
        completed_at=_NOW,
        env_filter=None,
        status_filter=None,
    )
    repos.snapshot_sync_runs._items[run.snapshot_sync_run_id] = run


def _add_stale_sync_run(repos: RepositoryContainer) -> None:
    """Add a successful sync run that is very old → stale."""
    run = SnapshotSyncRunEntity(
        snapshot_sync_run_id=uuid4(),
        trigger_type="scheduler",
        scope="all",
        dry_run=False,
        total_accounts=1,
        succeeded_accounts=1,
        partial_accounts=0,
        failed_accounts=0,
        skipped_accounts=0,
        positions_synced_total=5,
        positions_skipped_total=0,
        cash_synced_count=1,
        error_count=0,
        status="completed",
        started_at=_NOW - timedelta(hours=24),
        completed_at=_NOW - timedelta(hours=24),
        env_filter=None,
        status_filter=None,
    )
    repos.snapshot_sync_runs._items[run.snapshot_sync_run_id] = run


def _add_blocking_lock(repos: RepositoryContainer) -> None:
    """Add an active blocking lock for the test account.

    .. note::

       ``expires_at`` must be far in the future (not just ``_NOW + 1h``)
       because ``list_all_active_locks()`` compares against the **real**
       ``datetime.now()``, not the test constant ``_NOW``.
    """
    repos.reconciliations.acquire_lock(
        account_id=_ACCOUNT_ID,
        strategy_id=_STRATEGY_ID,
        symbol="005930",
        side="BUY",
        reason="test_lock",
        locked_by_run_id=uuid4(),
        expires_at=_NOW + timedelta(days=365),
    )


def _assert_check(
    check: PaperGateCheck,
    *,
    code: str,
    status: GateStatus,
) -> None:
    """Assert basic check fields."""
    assert check.code == code, f"Expected code={code}, got {check.code}"
    assert check.status == status, (
        f"Expected {code}.status={status}, got {check.status}"
    )


# ═══════════════════════════════════════════════════════════════════
# Integration: PaperGateService
# ═══════════════════════════════════════════════════════════════════


class TestPaperGateService:
    """``PaperGateService.evaluate()`` — 통합 검증."""

    # ------------------------------------------------------------------
    # 1. All PASS → GO
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_all_pass_returns_go(self) -> None:
        """모든 지표가 threshold 충족 → GO."""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        # 3 filled orders (meets min_filled_orders=3 default)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_fresh_sync_run(repos)

        settings = AppSettings()
        service = PaperGateService(repos, settings=settings)
        evaluation = await service.evaluate(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )

        assert isinstance(evaluation, PaperGoNoGoEvaluation)
        assert evaluation.overall_status == OverallStatus.GO
        assert evaluation.account_id == _ACCOUNT_ID
        assert evaluation.strategy_id is None
        assert evaluation.generated_at.tzinfo is not None

        # Verify all checks are PASS
        for check in evaluation.checks:
            assert check.status == GateStatus.PASS, (
                f"{check.code} should be PASS, got {check.status}: {check.message}"
            )

        # Summary should indicate all passed
        assert "통과" in evaluation.summary_reason

    # ------------------------------------------------------------------
    # 2. One WARN, no FAIL → HOLD
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_one_warn_returns_hold(self) -> None:
        """승률이 threshold 미달 → HOLD."""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_fresh_sync_run(repos)

        # Set min_win_rate to 100% → 3 winning buys won't hit 100% win_rate
        # (Actually BUY orders have negative realized PnL → they are losses → win_rate=0%)
        with _env(MIN_WIN_RATE_PCT="1"):
            settings = AppSettings()
            service = PaperGateService(repos, settings=settings)
            evaluation = await service.evaluate(
                account_id=_ACCOUNT_ID,
                start_date=_START,
                end_date=_END,
            )

        assert evaluation.overall_status == OverallStatus.HOLD

        # Find the MIN_WIN_RATE check
        win_rate_check = next(c for c in evaluation.checks if c.code == "MIN_WIN_RATE")
        assert win_rate_check.status == GateStatus.WARN

        # Verify no FAILs
        assert not any(c.status == GateStatus.FAIL for c in evaluation.checks)

        # Summary should mention "주의"
        assert "주의" in evaluation.summary_reason

    # ------------------------------------------------------------------
    # 3. One FAIL → NO_GO (stale snapshot)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_stale_snapshot_fails(self) -> None:
        """스냅샷 sync stale → SNAPSHOT_FRESHNESS FAIL, NO_GO."""
        repos = build_in_memory_repositories()
        # build_in_memory_repositories() seeds a fresh sync run;
        # clear it so only the stale run exists.
        repos.snapshot_sync_runs._items.clear()  # type: ignore[attr-defined]
        _seed_base(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        # Only stale run, no fresh run
        _add_stale_sync_run(repos)

        settings = AppSettings()
        service = PaperGateService(repos, settings=settings)
        evaluation = await service.evaluate(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )

        assert evaluation.overall_status == OverallStatus.NO_GO

        snapshot_check = next(c for c in evaluation.checks if c.code == "SNAPSHOT_FRESHNESS")
        _assert_check(snapshot_check, code="SNAPSHOT_FRESHNESS", status=GateStatus.FAIL)

        # Summary should mention "실패"
        assert "실패" in evaluation.summary_reason

    # ------------------------------------------------------------------
    # 4. Insufficient orders → FAIL
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_insufficient_orders_fails(self) -> None:
        """체결 건수 1건 (< default threshold 3) → MIN_FILLED_ORDERS FAIL, NO_GO."""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        # Only 1 filled order
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_fresh_sync_run(repos)

        settings = AppSettings()
        service = PaperGateService(repos, settings=settings)
        evaluation = await service.evaluate(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )

        assert evaluation.overall_status == OverallStatus.NO_GO

        orders_check = next(c for c in evaluation.checks if c.code == "MIN_FILLED_ORDERS")
        _assert_check(orders_check, code="MIN_FILLED_ORDERS", status=GateStatus.FAIL)
        assert orders_check.measured_value == 1
        # Default threshold is 3
        assert orders_check.threshold == 3

    # ------------------------------------------------------------------
    # 5. Blocking lock → FAIL
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_blocking_lock_fails(self) -> None:
        """Active blocking lock 존재 → BLOCKING_LOCKS FAIL, NO_GO."""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_fresh_sync_run(repos)
        _add_blocking_lock(repos)

        settings = AppSettings()
        service = PaperGateService(repos, settings=settings)
        evaluation = await service.evaluate(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )

        assert evaluation.overall_status == OverallStatus.NO_GO

        lock_check = next(c for c in evaluation.checks if c.code == "BLOCKING_LOCKS")
        _assert_check(lock_check, code="BLOCKING_LOCKS", status=GateStatus.FAIL)
        assert lock_check.measured_value == 1

    # ------------------------------------------------------------------
    # 6. With benchmark_code → MIN_EXCESS_RETURN included
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_benchmark_code_included(self) -> None:
        """benchmark_code 제공 → MIN_EXCESS_RETURN check 포함."""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_fresh_sync_run(repos)

        benchmark_repo = InMemoryBenchmarkPriceRepository(
            prices=_DEFAULT_BENCHMARK_PRICES,
        )
        settings = AppSettings()
        service = PaperGateService(
            repos=repos,
            settings=settings,
            benchmark_price_repo=benchmark_repo,
        )
        evaluation = await service.evaluate(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
            benchmark_code=BENCHMARK_KOSPI,
        )

        # MIN_EXCESS_RETURN should be present
        codes = {c.code for c in evaluation.checks}
        assert "MIN_EXCESS_RETURN" in codes, (
            f"Expected MIN_EXCESS_RETURN check, got codes={codes}"
        )

    # ------------------------------------------------------------------
    # 7. Without benchmark_code → MIN_EXCESS_RETURN skipped
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_without_benchmark_code_skips_excess_return(self) -> None:
        """benchmark_code 미제공 → MIN_EXCESS_RETURN check 미포함."""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_fresh_sync_run(repos)

        settings = AppSettings()
        service = PaperGateService(repos, settings=settings)
        evaluation = await service.evaluate(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
            # No benchmark_code
        )

        codes = {c.code for c in evaluation.checks}
        assert "MIN_EXCESS_RETURN" not in codes, (
            f"Expected no MIN_EXCESS_RETURN check, got codes={codes}"
        )
