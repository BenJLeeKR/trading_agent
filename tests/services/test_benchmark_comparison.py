"""Tests for ``agent_trading.services.benchmark_comparison``.

Test suites
===========
* :class:`TestCalcBenchmarkMetrics` — :func:`_calc_benchmark_metrics` pure function (5 tests)
* :class:`TestGetBenchmarkComparison` — :class:`BenchmarkComparisonService` 통합 (5 tests)
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import AsyncIterator
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    AccountEntity,
    BrokerOrderEntity,
    CashBalanceSnapshotEntity,
    ClientEntity,
    FillEventEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
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
    BENCHMARK_KOSDAQ,
    VALID_BENCHMARK_CODES,
    BenchmarkComparison,
    BenchmarkPriceRepository,
    InMemoryBenchmarkPriceRepository,
    _DEFAULT_BENCHMARK_PRICES,
    _calc_benchmark_metrics,
    BenchmarkComparisonService,
)
from agent_trading.services.performance_summary import PerformanceSummaryService


# ═══════════════════════════════════════════════════════════════════
# Constants / helpers
# ═══════════════════════════════════════════════════════════════════

_ACCOUNT_ID = UUID("11111111-1111-1111-1111-111111111111")
_CLIENT_ID = UUID("33333333-3333-3333-3333-333333333333")
_STRATEGY_ID = UUID("22222222-2222-2222-2222-222222222222")
_NOW = datetime(2026, 5, 8, 15, 30, 0, tzinfo=timezone.utc)


def _seed_repos(repos: RepositoryContainer) -> None:
    """Seed minimal reference data into an in-memory repo container.

    Mirrors the pattern from ``test_performance_summary._seed_repos``.
    """
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

    # Cash snapshot (starting 10M)
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


def _add_order_with_fills(
    repos: RepositoryContainer,
    order_date: datetime,
    strategy_id: UUID | None = _STRATEGY_ID,
    total_value: Decimal = Decimal("500000"),
) -> None:
    """Create a filled buy order for the test account (no strategy filter)."""
    order_id = uuid4()
    broker_order_id = uuid4()

    order = OrderRequestEntity(
        order_request_id=order_id,
        account_id=_ACCOUNT_ID,
        instrument_id=uuid4(),
        client_order_id=f"CLI-{order_id}",
        idempotency_key=f"IDEM-{order_id}",
        correlation_id=f"CORR-{order_id}",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        requested_quantity=Decimal("10"),
        requested_price=total_value / Decimal("10"),
        status=OrderStatus.FILLED,
        time_in_force=TimeInForce.DAY,
        decision_context_id=uuid4() if strategy_id else None,
        submitted_at=order_date,
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
        fill_timestamp=order_date,
        fill_price=total_value / Decimal("10"),
        fill_quantity=Decimal("10"),
        source_channel="test",
        fill_fee=Decimal("0"),
        fill_tax=Decimal("0"),
    )
    repos.fill_events._items[fill.fill_event_id] = fill


# ═══════════════════════════════════════════════════════════════════
# Pure function: _calc_benchmark_metrics
# ═══════════════════════════════════════════════════════════════════


class TestCalcBenchmarkMetrics:
    """``_calc_benchmark_metrics()`` — 순수 함수 검증."""

    def test_monotonic_increasing_prices(self) -> None:
        """Continuous rising → positive return, zero drawdown."""
        prices: list[tuple[date, Decimal]] = [
            (date(2026, 5, 1), Decimal("100")),
            (date(2026, 5, 2), Decimal("102")),
            (date(2026, 5, 3), Decimal("105")),
            (date(2026, 5, 4), Decimal("108")),
            (date(2026, 5, 5), Decimal("110")),
        ]
        ret, dd = _calc_benchmark_metrics(prices)
        # (110 - 100) / 100 * 100 = 10%
        assert ret == Decimal("10.00")
        # Never declined from peak
        assert dd == Decimal("0.00")

    def test_peak_then_decline(self) -> None:
        """Peak at 110 then decline to 99 → negative return, 10% drawdown."""
        prices: list[tuple[date, Decimal]] = [
            (date(2026, 5, 1), Decimal("100")),
            (date(2026, 5, 2), Decimal("105")),
            (date(2026, 5, 3), Decimal("110")),
            (date(2026, 5, 4), Decimal("105")),
            (date(2026, 5, 5), Decimal("99")),
        ]
        ret, dd = _calc_benchmark_metrics(prices)
        # (99 - 100) / 100 * 100 = -1%
        assert ret == Decimal("-1.00")
        # (110 - 99) / 110 * 100 = 10%
        assert dd == Decimal("10.00")

    def test_insufficient_data(self) -> None:
        """1 price or empty → return 0%, drawdown None."""
        assert _calc_benchmark_metrics([]) == (Decimal("0.00"), None)

        single: list[tuple[date, Decimal]] = [
            (date(2026, 5, 1), Decimal("100")),
        ]
        assert _calc_benchmark_metrics(single) == (Decimal("0.00"), None)

    def test_start_price_zero(self) -> None:
        """Start price 0 → return 0%, drawdown None (division guard)."""
        prices: list[tuple[date, Decimal]] = [
            (date(2026, 5, 1), Decimal("0")),
            (date(2026, 5, 2), Decimal("100")),
        ]
        assert _calc_benchmark_metrics(prices) == (Decimal("0.00"), None)

    def test_two_prices_only(self) -> None:
        """Exactly 2 prices → return calculated, drawdown possible."""
        prices: list[tuple[date, Decimal]] = [
            (date(2026, 5, 1), Decimal("100")),
            (date(2026, 5, 2), Decimal("95")),
        ]
        ret, dd = _calc_benchmark_metrics(prices)
        assert ret == Decimal("-5.00")
        assert dd == Decimal("5.00")


# ═══════════════════════════════════════════════════════════════════
# Integration: BenchmarkComparisonService
# ═══════════════════════════════════════════════════════════════════


@asynccontextmanager
async def _setup_service() -> AsyncIterator[BenchmarkComparisonService]:
    """Create a fresh ``BenchmarkComparisonService`` with seeded repos."""
    repos = build_in_memory_repositories()
    _seed_repos(repos)
    benchmark_repo = InMemoryBenchmarkPriceRepository(
        prices=_DEFAULT_BENCHMARK_PRICES,
    )
    service = BenchmarkComparisonService(
        repos=repos,
        benchmark_price_repo=benchmark_repo,
    )
    yield service


class TestGetBenchmarkComparison:
    """``BenchmarkComparisonService.get_benchmark_comparison()`` — 통합 검증."""

    @pytest.mark.asyncio
    async def test_outperform(self) -> None:
        """Portfolio +10% > benchmark +3% → excess = +7%."""
        async with _setup_service() as service:
            comparison = await service.get_benchmark_comparison(
                account_id=_ACCOUNT_ID,
                start_date=date(2026, 5, 1),
                end_date=date(2026, 5, 8),
                benchmark_code=BENCHMARK_KOSPI,
                strategy_id=_STRATEGY_ID,
            )

        assert isinstance(comparison, BenchmarkComparison)
        assert comparison.account_id == _ACCOUNT_ID
        assert comparison.benchmark_code == BENCHMARK_KOSPI
        # No fills → portfolio return = 0%
        # KOSPI: (2680 - 2600) / 2600 * 100 ≈ +3.08%
        assert comparison.portfolio_return_pct == Decimal("0")
        assert comparison.benchmark_return_pct > Decimal("0")
        assert comparison.excess_return_pct == (
            comparison.portfolio_return_pct - comparison.benchmark_return_pct
        )
        assert comparison.portfolio_max_drawdown_pct >= Decimal("0")
        assert comparison.benchmark_max_drawdown_pct is not None
        # Volatility fields are None in this iteration
        assert comparison.portfolio_volatility_pct is None
        assert comparison.benchmark_volatility_pct is None

    @pytest.mark.asyncio
    async def test_underperform(self) -> None:
        """Portfolio 0% < benchmark +3.53% → excess negative."""
        async with _setup_service() as service:
            comparison = await service.get_benchmark_comparison(
                account_id=_ACCOUNT_ID,
                start_date=date(2026, 5, 1),
                end_date=date(2026, 5, 8),
                benchmark_code=BENCHMARK_KOSDAQ,
                strategy_id=_STRATEGY_ID,
            )

        # No fills → portfolio return = 0%, KOSDAQ rises
        assert comparison.portfolio_return_pct == Decimal("0")
        assert comparison.benchmark_return_pct > Decimal("0")
        assert comparison.excess_return_pct < Decimal("0")

    @pytest.mark.asyncio
    async def test_flat(self) -> None:
        """Both portfolio & benchmark flat → excess = 0%."""
        # Single-day range → benchmark has only 1 price → return 0%
        async with _setup_service() as service:
            comparison = await service.get_benchmark_comparison(
                account_id=_ACCOUNT_ID,
                start_date=date(2026, 5, 1),
                end_date=date(2026, 5, 1),
                benchmark_code=BENCHMARK_KOSPI,
            )

        assert comparison.portfolio_return_pct == Decimal("0")
        assert comparison.benchmark_return_pct == Decimal("0")
        assert comparison.excess_return_pct == Decimal("0")
        # Insufficient benchmark prices → max_drawdown is None
        assert comparison.benchmark_max_drawdown_pct is None
        assert comparison.relative_drawdown_pct is None

    @pytest.mark.asyncio
    async def test_invalid_benchmark_code(self) -> None:
        """Invalid benchmark_code → ValueError."""
        async with _setup_service() as service:
            with pytest.raises(ValueError, match="Unknown benchmark_code"):
                await service.get_benchmark_comparison(
                    account_id=_ACCOUNT_ID,
                    start_date=date(2026, 5, 1),
                    end_date=date(2026, 5, 8),
                    benchmark_code="INVALID",
                )

    @pytest.mark.asyncio
    async def test_strategy_filter(self) -> None:
        """Strategy_id provided → portfolio metrics scoped to that strategy."""
        async with _setup_service() as service:
            comparison = await service.get_benchmark_comparison(
                account_id=_ACCOUNT_ID,
                start_date=date(2026, 5, 1),
                end_date=date(2026, 5, 8),
                benchmark_code=BENCHMARK_KOSPI,
                strategy_id=_STRATEGY_ID,
            )

        assert comparison.strategy_id == _STRATEGY_ID
        assert comparison.portfolio_return_pct == Decimal("0")  # no fills
        assert comparison.benchmark_return_pct > Decimal("0")
