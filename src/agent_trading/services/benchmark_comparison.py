"""Benchmark comparison service — portfolio vs benchmark excess return.

**Mode-agnostic**: This module works identically in both paper and live
modes.  It reads performance data from repositories and compares against
benchmark price series without any broker-env-specific logic.  The "Paper"
in the legacy filename reflects the initial implementation context only.

Pure function
=============
* :func:`_calc_benchmark_metrics` — daily price series → return/drawdown

Protocol
========
* :class:`BenchmarkPriceRepository` — daily price series lookup

InMemory implementation
=======================
* :class:`InMemoryBenchmarkPriceRepository` — fixture-based

Service class
=============
* :class:`BenchmarkComparisonService` — benchmark comparison assembly
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.performance_summary import (
    DailyPerformancePoint,
    PerformanceSummaryService,
)


# ---------------------------------------------------------------------------
# Benchmark code constants
# ---------------------------------------------------------------------------

BENCHMARK_KOSPI = "KOSPI"
BENCHMARK_KOSDAQ = "KOSDAQ"
VALID_BENCHMARK_CODES = frozenset({BENCHMARK_KOSPI, BENCHMARK_KOSDAQ})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class BenchmarkComparison:
    """Single-summary comparison between a portfolio and a benchmark index.

    All return/drawdown values are in **percentage points** (e.g. 3.5 means
    3.5 %).  Fields that cannot be calculated yet (volatility) are set to
    ``None`` and reserved for a follow-up.
    """

    account_id: UUID
    strategy_id: UUID | None
    benchmark_code: str
    period_start: date
    period_end: date

    # -- Portfolio (from existing PerformanceMetrics) --
    portfolio_return_pct: Decimal
    benchmark_return_pct: Decimal
    excess_return_pct: Decimal

    # -- Drawdown --
    portfolio_max_drawdown_pct: Decimal
    benchmark_max_drawdown_pct: Decimal | None
    relative_drawdown_pct: Decimal | None

    # -- Volatility (reserved, always None in this iteration) --
    portfolio_volatility_pct: Decimal | None = None
    benchmark_volatility_pct: Decimal | None = None


# ---------------------------------------------------------------------------
# Relative Benchmark Point (daily history)
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class RelativeBenchmarkPoint:
    """단일 일별 portfolio-vs-benchmark 상대 성과 포인트.

    All return/drawdown values are in **percentage points** (e.g. 3.5 means
    3.5 %).  Fields that cannot be calculated are set to ``None``.

    Parameters
    ----------
    date:
        관측일.
    portfolio_return_pct:
        Portfolio 누적 수익률 (기준선 대비).  데이터 없음 시 ``None``.
    benchmark_return_pct:
        Benchmark 누적 수익률 (기준선 대비).  데이터 없음 시 ``None``.
    excess_return_pct:
        ``portfolio_return_pct - benchmark_return_pct``.  둘 중 하나라도
        ``None``이면 ``None``.
    portfolio_drawdown_pct:
        Portfolio 현재 drawdown (rolling peak 대비).  ``None`` 가능.
    benchmark_drawdown_pct:
        Benchmark 현재 drawdown (rolling peak 대비).  ``None`` 가능.
    relative_drawdown_pct:
        ``portfolio_drawdown_pct - benchmark_drawdown_pct``.
        양수 → portfolio가 benchmark보다 더 많이 하락 (상대 성과 나쁨).
        음수 → portfolio 하락이 benchmark보다 적음 (방어 잘함).
    outperformance_streak:
        양수 = 연속 outperformance 일수, 음수 = 연속 underperformance 일수.
        ``excess_return_pct``가 ``None``이거나 0이면 0.
    benchmark_data_available:
        해당 일자의 benchmark 가격 데이터 존재 여부.
    """

    date: date
    portfolio_return_pct: Decimal | None
    benchmark_return_pct: Decimal | None
    excess_return_pct: Decimal | None
    portfolio_drawdown_pct: Decimal | None
    benchmark_drawdown_pct: Decimal | None
    relative_drawdown_pct: Decimal | None
    outperformance_streak: int
    benchmark_data_available: bool


# ---------------------------------------------------------------------------
# Benchmark price repository protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class BenchmarkPriceRepository(Protocol):
    """Protocol for fetching benchmark daily closing prices."""

    async def get_price_series(
        self,
        benchmark_code: str,
        start_date: date,
        end_date: date,
    ) -> Sequence[tuple[date, Decimal]]:
        """Return (date, close_price) pairs sorted ascending for the given range.

        If no data is available for *benchmark_code* an empty sequence is
        returned.  The implementation is responsible for filtering by the
        requested date window.
        """
        ...


# ---------------------------------------------------------------------------
# Default fixture prices
# ---------------------------------------------------------------------------

_DEFAULT_BENCHMARK_PRICES: dict[str, Sequence[tuple[date, Decimal]]] = {
    "KOSPI": [
        (date(2026, 5, 1), Decimal("2600.00")),
        (date(2026, 5, 4), Decimal("2620.00")),
        (date(2026, 5, 5), Decimal("2645.00")),
        (date(2026, 5, 6), Decimal("2630.00")),
        (date(2026, 5, 7), Decimal("2660.00")),
        (date(2026, 5, 8), Decimal("2680.00")),
        (date(2026, 5, 11), Decimal("2700.00")),
        (date(2026, 5, 12), Decimal("2690.00")),
        (date(2026, 5, 13), Decimal("2710.00")),
    ],
    "KOSDAQ": [
        (date(2026, 5, 1), Decimal("850.00")),
        (date(2026, 5, 4), Decimal("855.00")),
        (date(2026, 5, 5), Decimal("860.00")),
        (date(2026, 5, 6), Decimal("858.00")),
        (date(2026, 5, 7), Decimal("865.00")),
        (date(2026, 5, 8), Decimal("870.00")),
        (date(2026, 5, 11), Decimal("875.00")),
        (date(2026, 5, 12), Decimal("872.00")),
        (date(2026, 5, 13), Decimal("880.00")),
    ],
}


# ---------------------------------------------------------------------------
# InMemory benchmark price repository
# ---------------------------------------------------------------------------

class InMemoryBenchmarkPriceRepository:
    """In-memory implementation backed by a dict fixture.

    Primarily intended for tests and API default usage.
    """

    def __init__(
        self,
        prices: dict[str, Sequence[tuple[date, Decimal]]] | None = None,
    ) -> None:
        self._prices: dict[str, Sequence[tuple[date, Decimal]]] = prices or {}

    async def get_price_series(
        self,
        benchmark_code: str,
        start_date: date,
        end_date: date,
    ) -> Sequence[tuple[date, Decimal]]:
        series = self._prices.get(benchmark_code, [])
        return [(d, p) for d, p in series if start_date <= d <= end_date]


# ---------------------------------------------------------------------------
# Pure helper: benchmark metrics from daily price series
# ---------------------------------------------------------------------------

def _calc_benchmark_metrics(
    prices: Sequence[tuple[date, Decimal]],
) -> tuple[Decimal, Decimal | None]:
    """Calculate benchmark return and max drawdown from a daily price series.

    Parameters
    ----------
    prices :
        Ascending (date, close_price) pairs.  May be empty.

    Returns
    -------
    tuple[Decimal, Decimal | None]
        ``(return_pct, max_drawdown_pct)``.

    * Return is calculated as ``(last / first - 1) × 100``.
    * If fewer than 2 prices → return 0 %, drawdown ``None``.
    * If start price is 0 → return 0 %.
    * Drawdown uses rolling-peak logic; if only 1 price → drawdown ``None``.
    """
    if len(prices) < 2:
        return Decimal("0.00"), None

    first_price = prices[0][1]
    last_price = prices[-1][1]

    if first_price == Decimal("0"):
        return Decimal("0.00"), None

    # Return %
    benchmark_return = ((last_price - first_price) / first_price) * Decimal("100")
    benchmark_return = benchmark_return.quantize(Decimal("0.01"))

    # Max drawdown % — rolling peak
    peak = first_price
    max_drawdown = Decimal("0.00")

    for _, p in prices:
        if p > peak:
            peak = p
        drawdown = ((peak - p) / peak) * Decimal("100")
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    max_drawdown = max_drawdown.quantize(Decimal("0.01"))

    return benchmark_return, max_drawdown


# ---------------------------------------------------------------------------
# Pure helper: relative benchmark daily points
# ---------------------------------------------------------------------------

def _calc_relative_benchmark_points(
    portfolio_points: Sequence[DailyPerformancePoint],
    benchmark_prices: Sequence[tuple[date, Decimal]],
    start_date: date,
    end_date: date,
) -> list[RelativeBenchmarkPoint]:
    """Calculate daily portfolio-vs-benchmark relative performance points.

    Parameters
    ----------
    portfolio_points :
        일별 portfolio 성과 포인트 (ascending by date).
        :meth:`PerformanceSummaryService.get_daily_history` 출력.
    benchmark_prices :
        (date, close_price) pairs sorted ascending.
    start_date, end_date :
        분석 대상 기간 (inclusive).

    Returns
    -------
    list[RelativeBenchmarkPoint]
        일별 상대 성과 포인트 목록 (date ascending).
        Portfolio 데이터가 전혀 없으면 빈 list.

    Notes
    -----
    * **기준선 (Starting Point)** — ``start_date`` 당일 또는 이후 첫 유효
      equity/price를 기준으로 누적 수익률 계산. 데이터가 전혀 없으면
      모든 return 값이 ``None``.
    * **Missing Data** — 특정 일자에 benchmark/equity 데이터가 없으면
      해당 필드는 ``None``, ``outperformance_streak``는 0.
    * **보간 금지** — 누락된 데이터를 보간하지 않음.
    * **Outperformance Streak** — ``excess_return_pct``의 부호를 기준으로
      연속 일수 누적. ``> 0``이면 +1 (또는 리셋 후 1), ``< 0``이면 -1
      (또는 리셋 후 -1), ``== 0`` 또는 ``None``이면 0.
    """
    # Build date-indexed lookups
    portfolio_by_date: dict[date, DailyPerformancePoint] = {}
    for p in portfolio_points:
        portfolio_by_date[p.date] = p

    benchmark_by_date: dict[date, Decimal] = dict(benchmark_prices)

    # Collect sorted union of dates within range
    all_dates = sorted(
        set(portfolio_by_date.keys()) | set(benchmark_by_date.keys())
    )
    all_dates = [d for d in all_dates if start_date <= d <= end_date]

    if not all_dates:
        return []

    # Portfolio 데이터가 전혀 없으면 빈 결과
    if not portfolio_points:
        return []

    # Find starting equity (first portfolio point on or after start_date)
    starting_equity: Decimal | None = None
    for d in all_dates:
        pp = portfolio_by_date.get(d)
        if pp is not None and pp.total_equity is not None:
            starting_equity = pp.total_equity
            break

    # Find starting benchmark price (first price on or after start_date)
    starting_price: Decimal | None = None
    for d in all_dates:
        bp = benchmark_by_date.get(d)
        if bp is not None:
            starting_price = bp
            break

    # Nothing to calculate
    if starting_equity is None and starting_price is None:
        return []

    # Rolling peaks
    peak_equity: Decimal | None = None
    peak_price: Decimal | None = None
    streak = 0

    result: list[RelativeBenchmarkPoint] = []

    for d in all_dates:
        pp = portfolio_by_date.get(d)
        bp = benchmark_by_date.get(d)

        # ── Portfolio fields ──────────────────────────────────────
        portfolio_return_pct: Decimal | None = None
        portfolio_drawdown_pct: Decimal | None = None

        if pp is not None and pp.total_equity is not None:
            eq = pp.total_equity

            # Cumulative return vs starting equity
            if starting_equity is not None and starting_equity != Decimal("0"):
                portfolio_return_pct = (
                    (eq - starting_equity) / starting_equity * Decimal("100")
                ).quantize(Decimal("0.01"))

            # Rolling peak drawdown
            if peak_equity is None or eq > peak_equity:
                peak_equity = eq
            if peak_equity is not None and peak_equity != Decimal("0"):
                portfolio_drawdown_pct = (
                    (peak_equity - eq) / peak_equity * Decimal("100")
                ).quantize(Decimal("0.01"))

        # ── Benchmark fields ──────────────────────────────────────
        benchmark_return_pct: Decimal | None = None
        benchmark_drawdown_pct: Decimal | None = None
        benchmark_data_available = bp is not None

        if bp is not None:
            # Cumulative return vs starting price
            if starting_price is not None and starting_price != Decimal("0"):
                benchmark_return_pct = (
                    (bp - starting_price) / starting_price * Decimal("100")
                ).quantize(Decimal("0.01"))

            # Rolling peak drawdown
            if peak_price is None or bp > peak_price:
                peak_price = bp
            if peak_price is not None and peak_price != Decimal("0"):
                benchmark_drawdown_pct = (
                    (peak_price - bp) / peak_price * Decimal("100")
                ).quantize(Decimal("0.01"))

        # ── Cross fields ──────────────────────────────────────────
        excess_return_pct: Decimal | None = None
        if portfolio_return_pct is not None and benchmark_return_pct is not None:
            excess_return_pct = (portfolio_return_pct - benchmark_return_pct).quantize(
                Decimal("0.01")
            )

        relative_drawdown_pct: Decimal | None = None
        if portfolio_drawdown_pct is not None and benchmark_drawdown_pct is not None:
            relative_drawdown_pct = (
                portfolio_drawdown_pct - benchmark_drawdown_pct
            ).quantize(Decimal("0.01"))

        # Outperformance streak (sign / reset rules)
        if excess_return_pct is not None:
            if excess_return_pct > Decimal("0"):
                streak = streak + 1 if streak > 0 else 1
            elif excess_return_pct < Decimal("0"):
                streak = streak - 1 if streak < 0 else -1
            else:
                streak = 0
        else:
            streak = 0

        result.append(
            RelativeBenchmarkPoint(
                date=d,
                portfolio_return_pct=portfolio_return_pct,
                benchmark_return_pct=benchmark_return_pct,
                excess_return_pct=excess_return_pct,
                portfolio_drawdown_pct=portfolio_drawdown_pct,
                benchmark_drawdown_pct=benchmark_drawdown_pct,
                relative_drawdown_pct=relative_drawdown_pct,
                outperformance_streak=streak,
                benchmark_data_available=benchmark_data_available,
            )
        )

    return result


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class BenchmarkComparisonService:
    """Assembles a portfolio-vs-benchmark comparison for a given period.

    Portfolio metrics are delegated to :class:`PerformanceSummaryService`;
    benchmark metrics are calculated locally via :func:`_calc_benchmark_metrics`.
    """

    def __init__(
        self,
        repos: RepositoryContainer,
        benchmark_price_repo: BenchmarkPriceRepository,
    ) -> None:
        self._repos = repos
        self._benchmark_price_repo = benchmark_price_repo

    async def get_benchmark_comparison(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
        benchmark_code: str,
        strategy_id: UUID | None = None,
    ) -> BenchmarkComparison:
        """Build a single portfolio-vs-benchmark comparison.

        Parameters
        ----------
        account_id :
            Target paper account.
        start_date :
            Period start (inclusive).
        end_date :
            Period end (inclusive).
        benchmark_code :
            One of :const:`VALID_BENCHMARK_CODES`.
        strategy_id :
            Optional strategy filter — when provided, portfolio metrics are
            scoped to that strategy's orders.

        Returns
        -------
        BenchmarkComparison
            Fully populated comparison summary.

        Raises
        ------
        ValueError
            If *benchmark_code* is not in :const:`VALID_BENCHMARK_CODES`.
        """
        if benchmark_code not in VALID_BENCHMARK_CODES:
            raise ValueError(
                f"Unknown benchmark_code={benchmark_code!r}. "
                f"Valid codes: {sorted(VALID_BENCHMARK_CODES)}"
            )

        # 1. Portfolio metrics via existing service
        perf_service = PerformanceSummaryService(self._repos)
        metrics = await perf_service.get_performance_metrics(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            strategy_id=strategy_id,
        )

        # 2. Benchmark price series
        prices = await self._benchmark_price_repo.get_price_series(
            benchmark_code=benchmark_code,
            start_date=start_date,
            end_date=end_date,
        )

        # 3. Benchmark metrics
        benchmark_return, benchmark_max_dd = _calc_benchmark_metrics(prices)

        # 4. Excess / relative values
        excess_return = metrics.cumulative_return_pct - benchmark_return

        relative_dd: Decimal | None = None
        if benchmark_max_dd is not None:
            relative_dd = metrics.max_drawdown_pct - benchmark_max_dd

        return BenchmarkComparison(
            account_id=account_id,
            strategy_id=strategy_id,
            benchmark_code=benchmark_code,
            period_start=start_date,
            period_end=end_date,
            portfolio_return_pct=metrics.cumulative_return_pct,
            benchmark_return_pct=benchmark_return,
            excess_return_pct=excess_return,
            portfolio_max_drawdown_pct=metrics.max_drawdown_pct,
            benchmark_max_drawdown_pct=benchmark_max_dd,
            relative_drawdown_pct=relative_dd,
        )

    async def get_benchmark_daily_history(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
        benchmark_code: str,
        strategy_id: UUID | None = None,
    ) -> list[RelativeBenchmarkPoint]:
        """일별 portfolio-vs-benchmark 상대 성과 히스토리 반환.

        Parameters
        ----------
        account_id :
            Target paper account.
        start_date :
            Period start (inclusive).
        end_date :
            Period end (inclusive).
        benchmark_code :
            One of :const:`VALID_BENCHMARK_CODES`.
        strategy_id :
            Optional strategy filter.

        Returns
        -------
        list[RelativeBenchmarkPoint]
            일별 상대 성과 포인트 목록 (date ascending).

        Raises
        ------
        ValueError
            If *benchmark_code* is not in :const:`VALID_BENCHMARK_CODES`.
        """
        if benchmark_code not in VALID_BENCHMARK_CODES:
            raise ValueError(
                f"Unknown benchmark_code={benchmark_code!r}. "
                f"Valid codes: {sorted(VALID_BENCHMARK_CODES)}"
            )

        # 1. Portfolio daily history via existing service
        perf_service = PerformanceSummaryService(self._repos)
        portfolio_points = await perf_service.get_daily_history(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            strategy_id=strategy_id,
        )

        # 2. Benchmark price series
        prices = await self._benchmark_price_repo.get_price_series(
            benchmark_code=benchmark_code,
            start_date=start_date,
            end_date=end_date,
        )

        # 3. Pure calculation
        return _calc_relative_benchmark_points(
            portfolio_points=portfolio_points,
            benchmark_prices=prices,
            start_date=start_date,
            end_date=end_date,
        )
