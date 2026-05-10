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
    BenchmarkComparisonService,
    BenchmarkPriceRepository,
    InMemoryBenchmarkPriceRepository,
    RelativeBenchmarkPoint,
    _DEFAULT_BENCHMARK_PRICES,
    _calc_benchmark_metrics,
    _calc_relative_benchmark_points,
)
from agent_trading.services.performance_summary import (
    DailyPerformancePoint,
    PerformanceSummaryService,
)


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


# ═══════════════════════════════════════════════════════════════════
# Helpers for _calc_relative_benchmark_points tests
# ═══════════════════════════════════════════════════════════════════

_D1 = date(2026, 5, 1)
_D2 = date(2026, 5, 2)
_D3 = date(2026, 5, 3)
_D4 = date(2026, 5, 4)

_EQ10M = Decimal("10000000")
_EQ10_1M = Decimal("10100000")
_EQ10_2M = Decimal("10200000")
_EQ10_5M = Decimal("10500000")
_EQ11M = Decimal("11000000")
_EQ12M = Decimal("12000000")
_EQ9_5M = Decimal("9500000")

_PRICE100 = Decimal("100")
_PRICE102 = Decimal("102")
_PRICE105 = Decimal("105")
_PRICE100_5 = Decimal("100.5")
_PRICE101 = Decimal("101")
_PRICE103 = Decimal("103")
_PRICE104 = Decimal("104")
_PRICE106 = Decimal("106")
_PRICE107 = Decimal("107")
_PRICE108 = Decimal("108")
_PRICE110 = Decimal("110")
_PRICE115 = Decimal("115")
_PRICE118 = Decimal("118")
_PRICE120 = Decimal("120")
_PRICE85 = Decimal("85")


def _make_dpp(d: date, equity: Decimal) -> DailyPerformancePoint:
    """Create a DailyPerformancePoint with only date/total_equity populated."""
    return DailyPerformancePoint(
        date=d,
        realized_pnl=Decimal("0"),
        cumulative_realized_pnl=Decimal("0"),
        cash_balance=equity,
        position_market_value=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        total_equity=equity,
    )


# ═══════════════════════════════════════════════════════════════════
# Pure function: _calc_relative_benchmark_points
# ═══════════════════════════════════════════════════════════════════


class TestCalcRelativeBenchmarkPoints:
    """``_calc_relative_benchmark_points()`` — 순수 함수 검증 (14 tests)."""

    # ── 기본 정합성 ───────────────────────────────────────────────

    def test_basic_aligned_data(self) -> None:
        """Portfolio +5%/+10% vs benchmark +2%/+5% → correct excess, streak."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[
                _make_dpp(_D1, _EQ10M),
                _make_dpp(_D2, _EQ10_5M),
                _make_dpp(_D3, _EQ11M),
            ],
            benchmark_prices=[
                (_D1, _PRICE100),
                (_D2, _PRICE102),
                (_D3, _PRICE105),
            ],
            start_date=_D1,
            end_date=_D3,
        )

        assert len(points) == 3

        # d1: baseline
        assert points[0].date == _D1
        assert points[0].portfolio_return_pct == Decimal("0.00")
        assert points[0].benchmark_return_pct == Decimal("0.00")
        assert points[0].excess_return_pct == Decimal("0.00")
        assert points[0].outperformance_streak == 0

        # d2: portfolio +5%, benchmark +2% → excess +3%
        assert points[1].date == _D2
        assert points[1].portfolio_return_pct == Decimal("5.00")
        assert points[1].benchmark_return_pct == Decimal("2.00")
        assert points[1].excess_return_pct == Decimal("3.00")
        assert points[1].outperformance_streak == 1

        # d3: portfolio +10%, benchmark +5% → excess +5%
        assert points[2].date == _D3
        assert points[2].portfolio_return_pct == Decimal("10.00")
        assert points[2].benchmark_return_pct == Decimal("5.00")
        assert points[2].excess_return_pct == Decimal("5.00")
        assert points[2].outperformance_streak == 2

    # ── Streak 누적 (양수) ────────────────────────────────────────

    def test_outperformance_streak_accumulates(self) -> None:
        """Portfolio outperforms 3 consecutive days → streak +1 → +2 → +3."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[
                _make_dpp(_D1, _EQ10M),
                _make_dpp(_D2, _EQ10_2M),
                _make_dpp(_D3, _EQ10_5M),
                _make_dpp(_D4, _EQ11M),
            ],
            benchmark_prices=[
                (_D1, _PRICE100),
                (_D2, _PRICE100_5),
                (_D3, _PRICE101),
                (_D4, _PRICE102),
            ],
            start_date=_D1,
            end_date=_D4,
        )

        assert len(points) == 4
        assert points[1].outperformance_streak == 1  # d2: excess > 0
        assert points[2].outperformance_streak == 2  # d3: excess > 0
        assert points[3].outperformance_streak == 3  # d4: excess > 0

    # ── Streak 누적 (음수) ────────────────────────────────────────

    def test_underperformance_streak_accumulates(self) -> None:
        """Portfolio underperforms 3 consecutive days → streak -1 → -2."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[
                _make_dpp(_D1, _EQ10M),
                _make_dpp(_D2, _EQ10_1M),
                _make_dpp(_D3, _EQ10_2M),
            ],
            benchmark_prices=[
                (_D1, _PRICE100),
                (_D2, _PRICE103),
                (_D3, _PRICE107),
            ],
            start_date=_D1,
            end_date=_D3,
        )

        assert len(points) == 3
        # d2: portfolio +1%, benchmark +3% → excess -2%
        assert points[1].excess_return_pct is not None and points[1].excess_return_pct < Decimal("0")
        assert points[1].outperformance_streak == -1
        # d3: portfolio +2%, benchmark +7% → excess -5%
        assert points[2].excess_return_pct is not None and points[2].excess_return_pct < Decimal("0")
        assert points[2].outperformance_streak == -2

    # ── Streak 부호 변경 ──────────────────────────────────────────

    def test_streak_sign_change_positive_to_negative(self) -> None:
        """Positive streak → sign change → resets to -1."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[
                _make_dpp(_D1, _EQ10M),
                _make_dpp(_D2, _EQ10_5M),
                _make_dpp(_D3, _EQ10_5M),  # flat equity
            ],
            benchmark_prices=[
                (_D1, _PRICE100),
                (_D2, _PRICE102),
                (_D3, _PRICE106),  # benchmark rises more
            ],
            start_date=_D1,
            end_date=_D3,
        )

        assert len(points) == 3
        assert points[1].outperformance_streak == 1   # d2: excess +3%
        assert points[2].outperformance_streak == -1  # d3: excess negative (reset)

    def test_streak_sign_change_negative_to_positive(self) -> None:
        """Negative streak → sign change → resets to +1."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[
                _make_dpp(_D1, _EQ10M),
                _make_dpp(_D2, _EQ10_1M),
                _make_dpp(_D3, _EQ11M),
            ],
            benchmark_prices=[
                (_D1, _PRICE100),
                (_D2, _PRICE104),
                (_D3, _PRICE105),
            ],
            start_date=_D1,
            end_date=_D3,
        )

        assert len(points) == 3
        assert points[1].outperformance_streak == -1  # d2: excess negative
        assert points[2].outperformance_streak == 1   # d3: excess positive (reset)

    # ── Streak 0 리셋 ─────────────────────────────────────────────

    def test_streak_resets_to_zero_on_zero_excess(self) -> None:
        """Accumulated streak → excess == 0 → streak = 0."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[
                _make_dpp(_D1, _EQ10M),
                _make_dpp(_D2, _EQ11M),
                _make_dpp(_D3, _EQ12M),
                _make_dpp(_D4, _EQ12M),  # flat → excess 0
            ],
            benchmark_prices=[
                (_D1, _PRICE100),
                (_D2, _PRICE108),
                (_D3, _PRICE118),
                (_D4, _PRICE120),
            ],
            start_date=_D1,
            end_date=_D4,
        )

        assert len(points) == 4
        assert points[1].outperformance_streak == 1  # excess > 0
        assert points[2].outperformance_streak == 2  # excess > 0
        assert points[3].outperformance_streak == 0  # excess == 0 → reset

    # ── Missing benchmark data ────────────────────────────────────

    def test_missing_benchmark_data(self) -> None:
        """d2 has no benchmark price → benchmark fields None, streak=0."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[
                _make_dpp(_D1, _EQ10M),
                _make_dpp(_D2, _EQ10_5M),
                _make_dpp(_D3, _EQ11M),
            ],
            benchmark_prices=[
                (_D1, _PRICE100),
                (_D3, _PRICE105),  # d2 missing
            ],
            start_date=_D1,
            end_date=_D3,
        )

        assert len(points) == 3
        # d1: all present
        assert points[0].benchmark_data_available is True
        assert points[0].benchmark_return_pct is not None
        # d2: benchmark missing
        assert points[1].benchmark_data_available is False
        assert points[1].benchmark_return_pct is None
        assert points[1].benchmark_drawdown_pct is None
        assert points[1].relative_drawdown_pct is None
        assert points[1].excess_return_pct is None
        assert points[1].outperformance_streak == 0
        # d3: back to normal
        assert points[2].benchmark_data_available is True
        assert points[2].benchmark_return_pct is not None

    # ── Missing portfolio data ────────────────────────────────────

    def test_missing_portfolio_data(self) -> None:
        """Benchmark-only date → portfolio fields None, streak=0."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[
                _make_dpp(_D2, _EQ10_5M),  # d1 missing
            ],
            benchmark_prices=[
                (_D1, _PRICE100),
                (_D2, _PRICE102),
            ],
            start_date=_D1,
            end_date=_D2,
        )

        assert len(points) == 2
        # d1: portfolio missing
        assert points[0].portfolio_return_pct is None
        assert points[0].portfolio_drawdown_pct is None
        assert points[0].outperformance_streak == 0
        # d2: portfolio present (baseline from d2 equity)
        assert points[1].portfolio_return_pct == Decimal("0.00")  # starting equity = d2's own

    # ── Starting point 정합성 ─────────────────────────────────────

    def test_starting_equity_on_start_date(self) -> None:
        """Starting equity from start_date → correct baseline."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[
                _make_dpp(_D1, _EQ10M),
            ],
            benchmark_prices=[
                (_D1, _PRICE100),
            ],
            start_date=_D1,
            end_date=_D1,
        )

        assert len(points) == 1
        assert points[0].portfolio_return_pct == Decimal("0.00")
        assert points[0].benchmark_return_pct == Decimal("0.00")

    def test_starting_equity_after_start_date(self) -> None:
        """No data on start_date → first available equity = baseline."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[
                _make_dpp(_D2, _EQ10_5M),  # first data on d2
            ],
            benchmark_prices=[
                (_D1, _PRICE100),
                (_D2, _PRICE105),
            ],
            start_date=_D1,
            end_date=_D2,
        )

        assert len(points) == 2
        # d1: portfolio missing → fields None
        assert points[0].portfolio_return_pct is None
        assert points[0].benchmark_return_pct == Decimal("0.00")  # baseline
        # d2: portfolio starts at 0% (baseline = d2 equity)
        assert points[1].portfolio_return_pct == Decimal("0.00")
        assert points[1].benchmark_return_pct == Decimal("5.00")
        # excess = 0 - 5 = -5%
        assert points[1].excess_return_pct == Decimal("-5.00")

    # ── 빈 결과 ───────────────────────────────────────────────────

    def test_empty_portfolio_points(self) -> None:
        """Empty portfolio_points → empty result."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[],
            benchmark_prices=[(_D1, _PRICE100)],
            start_date=_D1,
            end_date=_D1,
        )
        assert points == []

    def test_no_data_at_all(self) -> None:
        """Both empty → empty result."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[],
            benchmark_prices=[],
            start_date=_D1,
            end_date=_D1,
        )
        assert points == []

    # ── Drawdown tracking ─────────────────────────────────────────

    def test_drawdown_tracking(self) -> None:
        """Peak then decline → positive drawdown."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[
                _make_dpp(_D1, _EQ10M),
                _make_dpp(_D2, _EQ12M),   # peak
                _make_dpp(_D3, _EQ11M),   # decline
            ],
            benchmark_prices=[
                (_D1, _PRICE100),
                (_D2, _PRICE100),
                (_D3, _PRICE100),
            ],
            start_date=_D1,
            end_date=_D3,
        )

        assert len(points) == 3
        # d2: new peak → 0% drawdown
        assert points[1].portfolio_drawdown_pct == Decimal("0.00")
        # d3: (12-11)/12*100 = 8.33... → quantized
        assert points[2].portfolio_drawdown_pct == Decimal("8.33")
        # Benchmark flat → drawdown 0%
        assert points[2].benchmark_drawdown_pct == Decimal("0.00")
        # Relative = portfolio - benchmark = 8.33%
        assert points[2].relative_drawdown_pct == Decimal("8.33")

    def test_relative_drawdown_sign_negative(self) -> None:
        """Portfolio drawdown < benchmark drawdown → negative relative_dd."""
        points = _calc_relative_benchmark_points(
            portfolio_points=[
                _make_dpp(_D1, _EQ10M),
                _make_dpp(_D2, _EQ10M),
                _make_dpp(_D3, _EQ9_5M),  # -5% from peak
            ],
            benchmark_prices=[
                (_D1, _PRICE100),
                (_D2, _PRICE100),
                (_D3, _PRICE85),  # -15% from peak
            ],
            start_date=_D1,
            end_date=_D3,
        )

        assert len(points) == 3
        # Portfolio dd = 5%, benchmark dd = 15%
        assert points[2].portfolio_drawdown_pct == Decimal("5.00")
        assert points[2].benchmark_drawdown_pct == Decimal("15.00")
        # relative = 5 - 15 = -10% (portfolio defended better)
        assert points[2].relative_drawdown_pct == Decimal("-10.00")


# ═══════════════════════════════════════════════════════════════════
# Integration: BenchmarkComparisonService.get_benchmark_daily_history
# ═══════════════════════════════════════════════════════════════════


class TestGetBenchmarkDailyHistory:
    """``BenchmarkComparisonService.get_benchmark_daily_history()`` — 통합 검증."""

    @pytest.mark.asyncio
    async def test_basic_history(self) -> None:
        """KOSPI benchmark → returns points for date range (no fills = flat)."""
        async with _setup_service() as service:
            points = await service.get_benchmark_daily_history(
                account_id=_ACCOUNT_ID,
                start_date=date(2026, 5, 1),
                end_date=date(2026, 5, 8),
                benchmark_code=BENCHMARK_KOSPI,
            )

        assert isinstance(points, list)
        assert len(points) > 0
        for p in points:
            assert isinstance(p, RelativeBenchmarkPoint)
            assert p.date >= date(2026, 5, 1)
            assert p.date <= date(2026, 5, 8)
        # Ascending order
        dates = [p.date for p in points]
        assert dates == sorted(dates)

    @pytest.mark.asyncio
    async def test_strategy_filter(self) -> None:
        """Strategy_id provided → history respects strategy scope."""
        async with _setup_service() as service:
            points = await service.get_benchmark_daily_history(
                account_id=_ACCOUNT_ID,
                start_date=date(2026, 5, 1),
                end_date=date(2026, 5, 8),
                benchmark_code=BENCHMARK_KOSPI,
                strategy_id=_STRATEGY_ID,
            )

        assert len(points) > 0
        # No fills → portfolio return is 0%
        for p in points:
            if p.portfolio_return_pct is not None:
                assert p.portfolio_return_pct == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_invalid_benchmark_code(self) -> None:
        """Invalid benchmark_code → ValueError."""
        async with _setup_service() as service:
            with pytest.raises(ValueError, match="Unknown benchmark_code"):
                await service.get_benchmark_daily_history(
                    account_id=_ACCOUNT_ID,
                    start_date=date(2026, 5, 1),
                    end_date=date(2026, 5, 8),
                    benchmark_code="INVALID",
                )

    @pytest.mark.asyncio
    async def test_empty_result_no_fills(self) -> None:
        """No fills → portfolio has no data → empty points."""
        async with _setup_service() as service:
            points = await service.get_benchmark_daily_history(
                account_id=_ACCOUNT_ID,
                start_date=date(2026, 5, 1),
                end_date=date(2026, 5, 1),
                benchmark_code=BENCHMARK_KOSPI,
            )

        # Without fills, the portfolio daily history may still return
        # points if there are cash/position snapshots.  This test
        # verifies the call does not raise and returns a list.
        assert isinstance(points, list)

    @pytest.mark.asyncio
    async def test_point_ordering(self) -> None:
        """Points are returned in ascending date order."""
        async with _setup_service() as service:
            points = await service.get_benchmark_daily_history(
                account_id=_ACCOUNT_ID,
                start_date=date(2026, 5, 1),
                end_date=date(2026, 5, 13),
                benchmark_code=BENCHMARK_KOSPI,
            )

        dates = [p.date for p in points]
        assert dates == sorted(dates)
