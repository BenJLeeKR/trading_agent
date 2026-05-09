"""Tests for ``agent_trading.services.performance_summary`` — PnL/performance 집계.

검증 범위
---------
1. ``calc_realized_pnl_for_order()`` — pure function: BUY/SELL/fee/tax
2. ``calc_unrealized_pnl_from_positions()`` — pure function: long/short/missing price
3. ``calc_position_market_value()`` — pure function: multiple positions
4. ``PerformanceSummaryService.get_account_summary()`` — cash-only / mixed / no data
5. ``PerformanceSummaryService.get_strategy_summary()`` — strategy filter
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    AccountEntity,
    BrokerOrderEntity,
    CashBalanceSnapshotEntity,
    ClientEntity,
    DecisionContextEntity,
    FillEventEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
    StrategyEntity,
)
from agent_trading.domain.enums import (
    AssetClass,
    EntryStyle,
    Environment,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.performance_summary import (
    AccountPerformanceSummary,
    DailyPerformancePoint,
    PerformanceMetrics,
    PerformanceSummaryService,
    StrategyPerformanceSummary,
    _calc_equity_metrics,
    _calc_per_fill_pnl,
    _calc_win_loss_metrics,
    _latest_cash_on_or_before,
    _latest_positions_on_or_before,
    calc_position_market_value,
    calc_realized_pnl_for_order,
    calc_unrealized_pnl_from_positions,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_ACCOUNT_ID = uuid4()
_CLIENT_ID = uuid4()
_STRATEGY_ID = uuid4()
_NOW = datetime.now(timezone.utc)


def _seed_repos(repos: RepositoryContainer) -> None:
    """Seed minimal reference data into an in-memory repo container."""
    # Client
    from agent_trading.domain.entities import ClientEntity as Client

    repos.clients._items[_CLIENT_ID] = Client(
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


def _make_fill(
    *,
    fill_price: str = "50000",
    fill_quantity: str = "10",
    fill_fee: str | None = None,
    fill_tax: str | None = None,
    broker_order_id: UUID | None = None,
    fill_timestamp: datetime | None = None,
) -> FillEventEntity:
    return FillEventEntity(
        fill_event_id=uuid4(),
        broker_order_id=broker_order_id or uuid4(),
        fill_timestamp=fill_timestamp or _NOW,
        fill_price=Decimal(fill_price),
        fill_quantity=Decimal(fill_quantity),
        source_channel="test",
        fill_fee=Decimal(fill_fee) if fill_fee else None,
        fill_tax=Decimal(fill_tax) if fill_tax else None,
    )


def _make_position(
    *,
    quantity: str = "10",
    average_price: str = "50000",
    market_price: str | None = "51000",
) -> PositionSnapshotEntity:
    return PositionSnapshotEntity(
        position_snapshot_id=uuid4(),
        account_id=_ACCOUNT_ID,
        instrument_id=uuid4(),
        quantity=Decimal(quantity),
        average_price=Decimal(average_price),
        market_price=Decimal(market_price) if market_price else None,
        unrealized_pnl=None,
        source_of_truth="test",
        snapshot_at=_NOW,
    )


# ---------------------------------------------------------------------------
# TestCalcRealizedPnl
# ---------------------------------------------------------------------------


class TestCalcRealizedPnl:
    """``calc_realized_pnl_for_order()`` — 순수 함수 검증."""

    def test_buy_order_negative_cash_flow(self) -> None:
        """매수는 음수 현금 흐름 → realized_pnl < 0."""
        fills = [
            _make_fill(fill_price="50000", fill_quantity="10"),
        ]
        result = calc_realized_pnl_for_order(fills, OrderSide.BUY)
        # BUY: -50000 * 10 = -500000
        assert result == Decimal("-500000")

    def test_sell_order_positive_cash_flow(self) -> None:
        """매도는 양수 현금 흐름 → realized_pnl > 0."""
        fills = [
            _make_fill(fill_price="52000", fill_quantity="10"),
        ]
        result = calc_realized_pnl_for_order(fills, OrderSide.SELL)
        # SELL: +52000 * 10 = +520000
        assert result == Decimal("520000")

    def test_with_fee_and_tax(self) -> None:
        """fee/tax 차감 확인."""
        fills = [
            _make_fill(
                fill_price="50000",
                fill_quantity="10",
                fill_fee="500",
                fill_tax="150",
            ),
        ]
        result = calc_realized_pnl_for_order(fills, OrderSide.SELL)
        # SELL: +50000*10 - 500 - 150 = 499350
        assert result == Decimal("499350")

    def test_multiple_fills_same_order(self) -> None:
        """동일 주문에 여러 체결 → 합계."""
        fills = [
            _make_fill(fill_price="50000", fill_quantity="5"),
            _make_fill(fill_price="51000", fill_quantity="5"),
        ]
        result = calc_realized_pnl_for_order(fills, OrderSide.SELL)
        # SELL: 50000*5 + 51000*5 = 505000
        assert result == Decimal("505000")

    def test_empty_fills(self) -> None:
        """체결 내역 없음 → 0."""
        result = calc_realized_pnl_for_order([], OrderSide.BUY)
        assert result == Decimal("0")


# ---------------------------------------------------------------------------
# TestCalcUnrealizedPnl
# ---------------------------------------------------------------------------


class TestCalcUnrealizedPnl:
    """``calc_unrealized_pnl_from_positions()`` — 순수 함수 검증."""

    def test_long_position_profit(self) -> None:
        """Long position, market > avg → 양수 unrealized PnL."""
        pos = _make_position(quantity="10", average_price="50000", market_price="51000")
        result = calc_unrealized_pnl_from_positions([pos])
        # 10 * (51000 - 50000) = 10000
        assert result == Decimal("10000")

    def test_long_position_loss(self) -> None:
        """Long position, market < avg → 음수 unrealized PnL."""
        pos = _make_position(quantity="10", average_price="50000", market_price="49000")
        result = calc_unrealized_pnl_from_positions([pos])
        # 10 * (49000 - 50000) = -10000
        assert result == Decimal("-10000")

    def test_market_price_none_skipped(self) -> None:
        """market_price=None → 해당 position 제외 (0)."""
        pos = _make_position(quantity="10", average_price="50000", market_price=None)
        result = calc_unrealized_pnl_from_positions([pos])
        assert result == Decimal("0")

    def test_empty_positions(self) -> None:
        """포지션 없음 → 0."""
        result = calc_unrealized_pnl_from_positions([])
        assert result == Decimal("0")


# ---------------------------------------------------------------------------
# TestCalcPositionMarketValue
# ---------------------------------------------------------------------------


class TestCalcPositionMarketValue:
    """``calc_position_market_value()`` — 순수 함수 검증."""

    def test_single_position(self) -> None:
        """단일 포지션 평가액."""
        pos = _make_position(quantity="10", market_price="51000")
        result = calc_position_market_value([pos])
        assert result == Decimal("510000")

    def test_multiple_positions(self) -> None:
        """여러 포지션 합계."""
        positions = [
            _make_position(quantity="10", market_price="51000"),
            _make_position(quantity="5", market_price="25000"),
        ]
        result = calc_position_market_value(positions)
        # 10*51000 + 5*25000 = 510000 + 125000 = 635000
        assert result == Decimal("635000")

    def test_skips_missing_market_price(self) -> None:
        """market_price=None 포지션 제외."""
        positions = [
            _make_position(quantity="10", market_price="51000"),
            _make_position(quantity="5", market_price=None),
        ]
        result = calc_position_market_value(positions)
        assert result == Decimal("510000")

    def test_empty(self) -> None:
        """포지션 없음 → 0."""
        result = calc_position_market_value([])
        assert result == Decimal("0")


# ---------------------------------------------------------------------------
# Helpers for service tests
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _setup_service() -> AsyncIterator[PerformanceSummaryService]:
    """Create a seeded in-memory PerformanceSummaryService."""
    repos = build_in_memory_repositories()
    _seed_repos(repos)
    service = PerformanceSummaryService(repos)
    yield service


def _add_cash_snapshot(
    repos: RepositoryContainer,
    available: str,
    snapshot_at: datetime | None = None,
) -> None:
    """Add a cash balance snapshot for the test account."""
    from agent_trading.domain.entities import CashBalanceSnapshotEntity

    repos.cash_balance_snapshots._items[uuid4()] = CashBalanceSnapshotEntity(
        cash_balance_snapshot_id=uuid4(),
        account_id=_ACCOUNT_ID,
        currency="KRW",
        available_cash=Decimal(available),
        settled_cash=Decimal(available),
        unsettled_cash=Decimal("0"),
        source_of_truth="test",
        snapshot_at=snapshot_at or _NOW,
    )


def _add_position(
    repos: RepositoryContainer,
    *,
    quantity: str = "10",
    average_price: str = "50000",
    market_price: str | None = "51000",
) -> None:
    """Add a position snapshot for the test account."""
    pos = _make_position(
        quantity=quantity,
        average_price=average_price,
        market_price=market_price,
    )
    repos.position_snapshots._items[pos.position_snapshot_id] = pos


def _add_order_with_fills(
    repos: RepositoryContainer,
    side: OrderSide,
    *,
    fill_price: str = "50000",
    fill_quantity: str = "10",
    fill_fee: str | None = None,
    decision_context_id: UUID | None = None,
    fill_timestamp: datetime | None = None,
) -> None:
    """Add an order + broker_order + fill for the test account."""
    order_id = uuid4()
    broker_order_id = uuid4()

    order = OrderRequestEntity(
        order_request_id=order_id,
        account_id=_ACCOUNT_ID,
        instrument_id=uuid4(),
        client_order_id=f"CLI-{order_id}",
        idempotency_key=f"IDEM-{order_id}",
        correlation_id=f"CORR-{order_id}",
        side=side,
        order_type=OrderType.MARKET,
        requested_quantity=Decimal(fill_quantity),
        status=OrderStatus.FILLED,
        decision_context_id=decision_context_id,
        submitted_at=_NOW,
        time_in_force=TimeInForce.DAY,
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

    fill = _make_fill(
        fill_price=fill_price,
        fill_quantity=fill_quantity,
        fill_fee=fill_fee,
        broker_order_id=broker_order_id,
        fill_timestamp=fill_timestamp,
    )
    repos.fill_events._items[fill.fill_event_id] = fill


# ---------------------------------------------------------------------------
# TestPerformanceSummaryService
# ---------------------------------------------------------------------------


class TestPerformanceSummaryService:
    """``PerformanceSummaryService`` — repository access + summary assembly."""

    @pytest.mark.asyncio
    async def test_cash_only_account(self) -> None:
        """현금만 있는 계좌 → total_equity=cash, unrealized=0."""
        async with _setup_service() as service:
            repos = service._repos
            _add_cash_snapshot(repos, "1000000")

            summary = await service.get_account_summary(_ACCOUNT_ID)

            assert isinstance(summary, AccountPerformanceSummary)
            assert summary.cash_balance == Decimal("1000000")
            assert summary.position_market_value == Decimal("0")
            assert summary.total_equity == Decimal("1000000")
            assert summary.realized_pnl == Decimal("0")
            assert summary.unrealized_pnl == Decimal("0")
            assert summary.total_pnl == Decimal("0")
            assert summary.filled_order_count == 0
            assert summary.open_position_count == 0

    @pytest.mark.asyncio
    async def test_with_open_position_and_fill(self) -> None:
        """포지션 + 체결 내역 → realized/unrealized/total 정확성."""
        async with _setup_service() as service:
            repos = service._repos
            _add_cash_snapshot(repos, "500000")
            _add_position(
                repos,
                quantity="5",
                average_price="50000",
                market_price="52000",
            )
            # 매수 10주 @ 50000 → realized: -500000
            _add_order_with_fills(
                repos,
                OrderSide.BUY,
                fill_price="50000",
                fill_quantity="10",
            )
            # 매도 10주 @ 55000 → realized: +550000
            _add_order_with_fills(
                repos,
                OrderSide.SELL,
                fill_price="55000",
                fill_quantity="10",
            )

            summary = await service.get_account_summary(_ACCOUNT_ID)

            # unrealized: 5 * (52000 - 50000) = 10000
            assert summary.unrealized_pnl == Decimal("10000")
            # realized: -500000 + 550000 = 50000
            assert summary.realized_pnl == Decimal("50000")
            # total: 10000 + 50000 = 60000
            assert summary.total_pnl == Decimal("60000")
            # position_market_value: 5 * 52000 = 260000
            assert summary.position_market_value == Decimal("260000")
            # total_equity: 500000 + 260000 = 760000
            assert summary.total_equity == Decimal("760000")
            # 2 filled orders
            assert summary.filled_order_count == 2
            # 1 open position
            assert summary.open_position_count == 1
            # 1 winning (SELL), 1 losing (BUY)
            assert summary.winning_trade_count == 1
            assert summary.losing_trade_count == 1

    @pytest.mark.asyncio
    async def test_no_data_empty_account(self) -> None:
        """데이터 없는 계좌 → zero-filled summary."""
        async with _setup_service() as service:
            summary = await service.get_account_summary(_ACCOUNT_ID)

            assert summary.cash_balance == Decimal("0")
            assert summary.position_market_value == Decimal("0")
            assert summary.total_equity == Decimal("0")
            assert summary.realized_pnl == Decimal("0")
            assert summary.unrealized_pnl == Decimal("0")
            assert summary.total_pnl == Decimal("0")
            assert summary.filled_order_count == 0
            assert summary.open_position_count == 0
            assert summary.winning_trade_count == 0
            assert summary.losing_trade_count == 0

    @pytest.mark.asyncio
    async def test_strategy_summary(self) -> None:
        """전략 필터 → 해당 전략의 filled order만 집계."""
        async with _setup_service() as service:
            repos = service._repos

            # 다른 전략의 decision context
            other_strategy_id = uuid4()
            repos.strategies._items[other_strategy_id] = StrategyEntity(
                strategy_id=other_strategy_id,
                client_id=_CLIENT_ID,
                strategy_code="OTHER",
                name="Other Strategy",
                asset_class=AssetClass.KR_STOCK,
                status="active",
            )

            # Context for target strategy
            ctx_id = uuid4()
            repos.decision_contexts._items[ctx_id] = DecisionContextEntity(
                decision_context_id=ctx_id,
                account_id=_ACCOUNT_ID,
                strategy_id=_STRATEGY_ID,
                config_version_id=uuid4(),
                market_timestamp=_NOW,
                correlation_id="CORR-TARGET",
            )

            # Context for other strategy
            other_ctx_id = uuid4()
            repos.decision_contexts._items[other_ctx_id] = DecisionContextEntity(
                decision_context_id=other_ctx_id,
                account_id=_ACCOUNT_ID,
                strategy_id=other_strategy_id,
                config_version_id=uuid4(),
                market_timestamp=_NOW,
                correlation_id="CORR-OTHER",
            )

            # Target strategy: 매수 50000 * 10 → -500000
            _add_order_with_fills(
                repos,
                OrderSide.BUY,
                fill_price="50000",
                fill_quantity="10",
                decision_context_id=ctx_id,
            )
            # Target strategy: 매도 52000 * 10 → +520000
            _add_order_with_fills(
                repos,
                OrderSide.SELL,
                fill_price="52000",
                fill_quantity="10",
                decision_context_id=ctx_id,
            )
            # Other strategy: 매수 30000 * 5 → -150000 (무시되어야 함)
            _add_order_with_fills(
                repos,
                OrderSide.BUY,
                fill_price="30000",
                fill_quantity="5",
                decision_context_id=other_ctx_id,
            )

            summary = await service.get_strategy_summary(_ACCOUNT_ID, _STRATEGY_ID)

            assert isinstance(summary, StrategyPerformanceSummary)
            assert summary.strategy_id == _STRATEGY_ID
            # realized: -500000 + 520000 = 20000
            assert summary.realized_pnl == Decimal("20000")
            # 2 filled (target strategy only)
            assert summary.filled_order_count == 2
            # 1 winning, 1 losing
            assert summary.winning_trade_count == 1
            assert summary.losing_trade_count == 1

    @pytest.mark.asyncio
    async def test_strategy_summary_no_orders(self) -> None:
        """전략에 주문이 없음 → zero-filled summary."""
        async with _setup_service() as service:
            repos = service._repos

            ctx_id = uuid4()
            repos.decision_contexts._items[ctx_id] = DecisionContextEntity(
                decision_context_id=ctx_id,
                account_id=_ACCOUNT_ID,
                strategy_id=_STRATEGY_ID,
                config_version_id=uuid4(),
                market_timestamp=_NOW,
                correlation_id="CORR-TEST",
            )

            # 주문 없음
            summary = await service.get_strategy_summary(_ACCOUNT_ID, _STRATEGY_ID)

            assert summary.realized_pnl == Decimal("0")
            assert summary.filled_order_count == 0
            assert summary.winning_trade_count == 0
            assert summary.losing_trade_count == 0
    
    
    # ---------------------------------------------------------------------------
    # TestCalcPerFillPnl
    # ---------------------------------------------------------------------------
    
    
    class TestCalcPerFillPnl:
        """``_calc_per_fill_pnl()`` — 단일 체결 realized PnL 순수 함수 검증."""
    
        def test_buy_fill_negative_cash_flow(self) -> None:
            """매수 체결 → 음수 현금 흐름."""
            fill = _make_fill(fill_price="50000", fill_quantity="10")
            result = _calc_per_fill_pnl(fill, OrderSide.BUY)
            # BUY: -50000 * 10 = -500000
            assert result == Decimal("-500000")
    
        def test_sell_fill_positive_cash_flow(self) -> None:
            """매도 체결 → 양수 현금 흐름."""
            fill = _make_fill(fill_price="52000", fill_quantity="10")
            result = _calc_per_fill_pnl(fill, OrderSide.SELL)
            # SELL: +52000 * 10 = +520000
            assert result == Decimal("520000")
    
        def test_with_fee_and_tax(self) -> None:
            """수수료/세금 차감 확인."""
            fill = _make_fill(
                fill_price="50000",
                fill_quantity="10",
                fill_fee="500",
                fill_tax="150",
            )
            result = _calc_per_fill_pnl(fill, OrderSide.SELL)
            # SELL: +50000*10 - 500 - 150 = 499350
            assert result == Decimal("499350")
    
    
    # ---------------------------------------------------------------------------
    # TestLatestCashOnOrBefore
    # ---------------------------------------------------------------------------
    
    
    class TestLatestCashOnOrBefore:
        """``_latest_cash_on_or_before()`` — 현금 snapshot 선택 순수 함수 검증."""
    
        def test_exact_date_match(self) -> None:
            """target_date와 같은 날의 snapshot 반환."""
            target = date(2026, 5, 5)
            snap = CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(),
                account_id=_ACCOUNT_ID,
                currency="KRW",
                available_cash=Decimal("1000000"),
                settled_cash=Decimal("1000000"),
                unsettled_cash=Decimal("0"),
                source_of_truth="test",
                snapshot_at=datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc),
            )
            result = _latest_cash_on_or_before([snap], target)
            assert result is not None
            assert result.available_cash == Decimal("1000000")
    
        def test_carry_forward_from_earlier(self) -> None:
            """target_date 이전 snapshot → carry-forward."""
            target = date(2026, 5, 6)
            snap = CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(),
                account_id=_ACCOUNT_ID,
                currency="KRW",
                available_cash=Decimal("500000"),
                settled_cash=Decimal("500000"),
                unsettled_cash=Decimal("0"),
                source_of_truth="test",
                snapshot_at=datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc),
            )
            result = _latest_cash_on_or_before([snap], target)
            assert result is not None
            assert result.available_cash == Decimal("500000")
    
        def test_no_snapshot_before_date(self) -> None:
            """target_date 이전 snapshot 없음 → None."""
            target = date(2026, 5, 3)
            snap = CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(),
                account_id=_ACCOUNT_ID,
                currency="KRW",
                available_cash=Decimal("1000000"),
                settled_cash=Decimal("1000000"),
                unsettled_cash=Decimal("0"),
                source_of_truth="test",
                snapshot_at=datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc),
            )
            result = _latest_cash_on_or_before([snap], date(2026, 5, 3))
            assert result is None
    
        def test_multiple_snapshots_returns_latest(self) -> None:
            """여러 snapshot 중 가장 최신 반환."""
            target = date(2026, 5, 6)
            older = CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(),
                account_id=_ACCOUNT_ID,
                currency="KRW",
                available_cash=Decimal("500000"),
                settled_cash=Decimal("500000"),
                unsettled_cash=Decimal("0"),
                source_of_truth="test",
                snapshot_at=datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc),
            )
            newer = CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(),
                account_id=_ACCOUNT_ID,
                currency="KRW",
                available_cash=Decimal("1000000"),
                settled_cash=Decimal("1000000"),
                unsettled_cash=Decimal("0"),
                source_of_truth="test",
                snapshot_at=datetime(2026, 5, 5, 15, 0, 0, tzinfo=timezone.utc),
            )
            # Sorted DESC
            result = _latest_cash_on_or_before([newer, older], target)
            assert result is not None
            # Should pick the latest on or before target
            assert result.available_cash == Decimal("1000000")
    
    
    # ---------------------------------------------------------------------------
    # TestLatestPositionsOnOrBefore
    # ---------------------------------------------------------------------------
    
    
    class TestLatestPositionsOnOrBefore:
        """``_latest_positions_on_or_before()`` — position snapshot 선택 검증."""
    
        def test_per_instrument_latest(self) -> None:
            """instrument_id별 최신 snapshot 하나씩 선택."""
            target = date(2026, 5, 6)
            inst_a = uuid4()
            inst_b = uuid4()
    
            pos_a = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=_ACCOUNT_ID,
                instrument_id=inst_a,
                quantity=Decimal("10"),
                average_price=Decimal("50000"),
                market_price=Decimal("51000"),
                unrealized_pnl=None,
                source_of_truth="test",
                snapshot_at=datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc),
            )
            pos_b = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=_ACCOUNT_ID,
                instrument_id=inst_b,
                quantity=Decimal("5"),
                average_price=Decimal("20000"),
                market_price=Decimal("21000"),
                unrealized_pnl=None,
                source_of_truth="test",
                snapshot_at=datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc),
            )
            result = _latest_positions_on_or_before([pos_a, pos_b], target)
            assert len(result) == 2
    
        def test_prefers_latest_per_instrument(self) -> None:
            """같은 instrument에 여러 snapshot → 최신만 선택."""
            target = date(2026, 5, 8)
            inst = uuid4()
    
            old = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=_ACCOUNT_ID,
                instrument_id=inst,
                quantity=Decimal("10"),
                average_price=Decimal("50000"),
                market_price=Decimal("51000"),
                unrealized_pnl=None,
                source_of_truth="test",
                snapshot_at=datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc),
            )
            new = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=_ACCOUNT_ID,
                instrument_id=inst,
                quantity=Decimal("15"),
                average_price=Decimal("52000"),
                market_price=Decimal("53000"),
                unrealized_pnl=None,
                source_of_truth="test",
                snapshot_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc),
            )
            # Sorted DESC
            result = _latest_positions_on_or_before([new, old], target)
            assert len(result) == 1
            assert result[0].quantity == Decimal("15")
    
        def test_skips_future_snapshots(self) -> None:
            """target_date 이후 snapshot은 제외."""
            target = date(2026, 5, 5)
            inst = uuid4()
            future = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=_ACCOUNT_ID,
                instrument_id=inst,
                quantity=Decimal("10"),
                average_price=Decimal("50000"),
                market_price=Decimal("51000"),
                unrealized_pnl=None,
                source_of_truth="test",
                snapshot_at=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
            )
            result = _latest_positions_on_or_before([future], target)
            assert len(result) == 0
    
    
    # ---------------------------------------------------------------------------
    # TestGetDailyHistory
    # ---------------------------------------------------------------------------
    
    
    class TestGetDailyHistory:
        """``PerformanceSummaryService.get_daily_history()`` — 통합 검증."""
    
        @pytest.mark.asyncio
        async def test_single_day_realized_only(self) -> None:
            """1일치 체결만 → realized_pnl 정확성, snapshot 필드는 None."""
            async with _setup_service() as service:
                repos = service._repos
                day = date(2026, 5, 5)
                ts = datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc)
    
                # 매수 10주 @ 50000 → realized: -500000
                _add_order_with_fills(
                    repos,
                    OrderSide.BUY,
                    fill_price="50000",
                    fill_quantity="10",
                    fill_timestamp=ts,
                )
                # 매도 10주 @ 55000 → realized: +550000
                _add_order_with_fills(
                    repos,
                    OrderSide.SELL,
                    fill_price="55000",
                    fill_quantity="10",
                    fill_timestamp=ts,
                )
    
                points = await service.get_daily_history(
                    _ACCOUNT_ID,
                    start_date=day,
                    end_date=day,
                )
    
                assert len(points) == 1
                p = points[0]
                assert p.date == day
                # realized: -500000 + 550000 = 50000
                assert p.realized_pnl == Decimal("50000")
                assert p.cumulative_realized_pnl == Decimal("50000")
                # No snapshots → None
                assert p.cash_balance is None
                assert p.position_market_value is None
                assert p.unrealized_pnl is None
                assert p.total_equity is None
    
        @pytest.mark.asyncio
        async def test_multi_day_with_snapshots(self) -> None:
            """여러 날 체결 + snapshot → 일별/누적 정확성."""
            async with _setup_service() as service:
                repos = service._repos
                d1 = date(2026, 5, 5)
                d2 = date(2026, 5, 6)
                ts1 = datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc)
                ts2 = datetime(2026, 5, 6, 10, 0, 0, tzinfo=timezone.utc)
    
                # Day 1: 매수 10주 @ 50000 → -500000
                _add_order_with_fills(
                    repos, OrderSide.BUY,
                    fill_price="50000", fill_quantity="10",
                    fill_timestamp=ts1,
                )
                # Day 2: 매도 10주 @ 55000 → +550000
                _add_order_with_fills(
                    repos, OrderSide.SELL,
                    fill_price="55000", fill_quantity="10",
                    fill_timestamp=ts2,
                )
                # Cash snapshot on day 1
                _add_cash_snapshot(repos, "1000000", snapshot_at=ts1)
                # Position snapshot on day 2
                pos = _make_position(
                    quantity="10",
                    average_price="50000",
                    market_price="52000",
                )
                repos.position_snapshots._items[pos.position_snapshot_id] = PositionSnapshotEntity(
                    position_snapshot_id=pos.position_snapshot_id,
                    account_id=pos.account_id,
                    instrument_id=pos.instrument_id,
                    quantity=pos.quantity,
                    average_price=pos.average_price,
                    market_price=pos.market_price,
                    unrealized_pnl=pos.unrealized_pnl,
                    source_of_truth=pos.source_of_truth,
                    snapshot_at=ts2,
                )
    
                points = await service.get_daily_history(
                    _ACCOUNT_ID,
                    start_date=d1,
                    end_date=d2,
                )
    
                assert len(points) == 2
    
                # Day 1
                assert points[0].date == d1
                assert points[0].realized_pnl == Decimal("-500000")
                assert points[0].cumulative_realized_pnl == Decimal("-500000")
                assert points[0].cash_balance == Decimal("1000000")
                # Day 1 has no position snapshots → None
                assert points[0].position_market_value is None
                assert points[0].unrealized_pnl is None
                # total_equity = cash only (no positions)
                assert points[0].total_equity == Decimal("1000000")
    
                # Day 2
                assert points[1].date == d2
                assert points[1].realized_pnl == Decimal("550000")
                # cumulative: -500000 + 550000 = 50000
                assert points[1].cumulative_realized_pnl == Decimal("50000")
                # Cash carries forward from day 1
                assert points[1].cash_balance == Decimal("1000000")
                # Position: 10 * 52000 = 520000
                assert points[1].position_market_value == Decimal("520000")
                # total_equity: 1000000 + 520000 = 1520000
                assert points[1].total_equity == Decimal("1520000")
    
        @pytest.mark.asyncio
        async def test_date_range_no_data(self) -> None:
            """데이터 없는 기간 → realized=0, snapshot=None."""
            async with _setup_service() as service:
                d1 = date(2026, 5, 1)
                d2 = date(2026, 5, 3)
    
                points = await service.get_daily_history(
                    _ACCOUNT_ID,
                    start_date=d1,
                    end_date=d2,
                )
    
                assert len(points) == 3
                for p in points:
                    assert p.realized_pnl == Decimal("0")
                    assert p.cumulative_realized_pnl == Decimal("0")
                    assert p.cash_balance is None
                    assert p.position_market_value is None
                    assert p.unrealized_pnl is None
                    assert p.total_equity is None
    
        @pytest.mark.asyncio
        async def test_strategy_filter_history(self) -> None:
            """전략 필터 → 해당 전략의 fill만 집계."""
            async with _setup_service() as service:
                repos = service._repos
                day = date(2026, 5, 5)
                ts = datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc)
    
                # Target strategy context
                ctx_id = uuid4()
                repos.decision_contexts._items[ctx_id] = DecisionContextEntity(
                    decision_context_id=ctx_id,
                    account_id=_ACCOUNT_ID,
                    strategy_id=_STRATEGY_ID,
                    config_version_id=uuid4(),
                    market_timestamp=ts,
                    correlation_id="CORR-TARGET",
                )
    
                # 다른 전략
                other_strategy_id = uuid4()
                repos.strategies._items[other_strategy_id] = StrategyEntity(
                    strategy_id=other_strategy_id,
                    client_id=_CLIENT_ID,
                    strategy_code="OTHER",
                    name="Other",
                    asset_class=AssetClass.KR_STOCK,
                    status="active",
                )
                other_ctx_id = uuid4()
                repos.decision_contexts._items[other_ctx_id] = DecisionContextEntity(
                    decision_context_id=other_ctx_id,
                    account_id=_ACCOUNT_ID,
                    strategy_id=other_strategy_id,
                    config_version_id=uuid4(),
                    market_timestamp=ts,
                    correlation_id="CORR-OTHER",
                )
    
                # Target: 매수 50000 * 10 → -500000
                _add_order_with_fills(
                    repos, OrderSide.BUY,
                    fill_price="50000", fill_quantity="10",
                    decision_context_id=ctx_id,
                    fill_timestamp=ts,
                )
                # Other: 매도 60000 * 5 → +300000 (무시)
                _add_order_with_fills(
                    repos, OrderSide.SELL,
                    fill_price="60000", fill_quantity="5",
                    decision_context_id=other_ctx_id,
                    fill_timestamp=ts,
                )
    
                points = await service.get_daily_history(
                    _ACCOUNT_ID,
                    start_date=day,
                    end_date=day,
                    strategy_id=_STRATEGY_ID,
                )
    
                assert len(points) == 1
                # Only target strategy's fill: -500000
                assert points[0].realized_pnl == Decimal("-500000")
    
        @pytest.mark.asyncio
        async def test_empty_account(self) -> None:
            """빈 계좌 → 모든 날짜 realized=0, snapshot=None."""
            async with _setup_service() as service:
                day = date(2026, 5, 5)
                points = await service.get_daily_history(
                    _ACCOUNT_ID,
                    start_date=day,
                    end_date=day,
                )
    
                assert len(points) == 1
                p = points[0]
                assert p.realized_pnl == Decimal("0")
                assert p.cumulative_realized_pnl == Decimal("0")
                assert p.cash_balance is None


# ---------------------------------------------------------------------------
# TestCalcEquityMetrics
# ---------------------------------------------------------------------------


class TestCalcEquityMetrics:
    """``_calc_equity_metrics()`` — return/drawdown 순수 함수 검증."""

    def test_monotonic_increasing_equity(self) -> None:
        """Equity 계속 상승 → drawdown 0, return 양수."""
        points = [
            DailyPerformancePoint(
                date=date(2026, 5, 1),
                realized_pnl=Decimal("0"),
                cumulative_realized_pnl=Decimal("0"),
                total_equity=Decimal("1000000"),
            ),
            DailyPerformancePoint(
                date=date(2026, 5, 2),
                realized_pnl=Decimal("50000"),
                cumulative_realized_pnl=Decimal("50000"),
                total_equity=Decimal("1050000"),
            ),
            DailyPerformancePoint(
                date=date(2026, 5, 3),
                realized_pnl=Decimal("30000"),
                cumulative_realized_pnl=Decimal("80000"),
                total_equity=Decimal("1080000"),
            ),
        ]
        starting_equity = Decimal("1000000")

        (cum_return, current_eq, peak_eq,
         curr_dd, max_dd) = _calc_equity_metrics(points, starting_equity)

        # (1080000 - 1000000) / 1000000 * 100 = 8.0
        assert cum_return == Decimal("8.0")
        assert current_eq == Decimal("1080000")
        assert peak_eq == Decimal("1080000")
        assert curr_dd == Decimal("0")
        assert max_dd == Decimal("0")

    def test_peak_then_decline(self) -> None:
        """Peak 이후 하락 → current_drawdown / max_drawdown 정확성."""
        points = [
            DailyPerformancePoint(
                date=date(2026, 5, 1),
                realized_pnl=Decimal("0"),
                cumulative_realized_pnl=Decimal("0"),
                total_equity=Decimal("1000000"),
            ),
            DailyPerformancePoint(
                date=date(2026, 5, 2),
                realized_pnl=Decimal("0"),
                cumulative_realized_pnl=Decimal("0"),
                total_equity=Decimal("1100000"),  # peak
            ),
            DailyPerformancePoint(
                date=date(2026, 5, 3),
                realized_pnl=Decimal("0"),
                cumulative_realized_pnl=Decimal("0"),
                total_equity=Decimal("990000"),   # -10% from peak
            ),
        ]
        starting_equity = Decimal("1000000")

        (cum_return, current_eq, peak_eq,
         curr_dd, max_dd) = _calc_equity_metrics(points, starting_equity)

        # cumulative return: (990000 - 1000000) / 1000000 * 100 = -1.0
        assert cum_return == Decimal("-1.0")
        assert current_eq == Decimal("990000")
        assert peak_eq == Decimal("1100000")
        # current drawdown: (1100000 - 990000) / 1100000 * 100 ≈ 10.0
        assert curr_dd == Decimal("10.0")
        # max drawdown also 10% (single decline)
        assert max_dd == Decimal("10.0")

    def test_empty_or_all_none(self) -> None:
        """Equity history가 비었거나 전부 None → safe defaults."""
        points: list[DailyPerformancePoint] = [
            DailyPerformancePoint(
                date=date(2026, 5, 1),
                realized_pnl=Decimal("0"),
                cumulative_realized_pnl=Decimal("0"),
                total_equity=None,
            ),
        ]
        starting_equity = Decimal("1000000")

        (cum_return, current_eq, peak_eq,
         curr_dd, max_dd) = _calc_equity_metrics(points, starting_equity)

        # No valid equity data → use starting_equity as fallback
        assert cum_return == Decimal("0")
        assert current_eq == Decimal("1000000")
        assert peak_eq == Decimal("1000000")
        assert curr_dd == Decimal("0")
        assert max_dd == Decimal("0")


# ---------------------------------------------------------------------------
# TestCalcWinLossMetrics
# ---------------------------------------------------------------------------


class TestCalcWinLossMetrics:
    """``_calc_win_loss_metrics()`` — win/loss 순수 함수 검증."""

    def test_mixed_pnls(self) -> None:
        """양수/음수 혼합 → win_rate/avg_win/avg_loss 정확성."""
        pnls = [
            Decimal("1000"),   # win
            Decimal("-500"),   # loss
            Decimal("2000"),   # win
            Decimal("-300"),   # loss
            Decimal("0"),      # neutral (not counted as win or loss)
        ]
        (total, winning, losing, win_rate,
         avg_win, avg_loss, pf) = _calc_win_loss_metrics(pnls)

        assert total == 5
        assert winning == 2
        assert losing == 2
        # win_rate = 2/5 * 100 = 40.0
        assert win_rate == Decimal("40.0")
        # avg_win = (1000 + 2000) / 2 = 1500
        assert avg_win == Decimal("1500")
        # avg_loss = (-500 + -300) / 2 = -400
        assert avg_loss == Decimal("-400")
        # profit_factor = (1000 + 2000) / abs(-500 + -300) = 3000/800 = 3.75
        assert pf == Decimal("3.75")

    def test_all_wins(self) -> None:
        """전부 양수 PnL → profit_factor=None, avg_loss=None."""
        pnls = [Decimal("1000"), Decimal("2000"), Decimal("500")]
        (total, winning, losing, win_rate,
         avg_win, avg_loss, pf) = _calc_win_loss_metrics(pnls)

        assert total == 3
        assert winning == 3
        assert losing == 0
        assert win_rate == Decimal("100.0")
        assert avg_win == Decimal("1166.666666666666666666666667")  # 3500/3
        assert avg_loss is None
        assert pf is None

    def test_all_losses(self) -> None:
        """전부 음수 PnL → profit_factor=None, avg_win=None."""
        pnls = [Decimal("-100"), Decimal("-200")]
        (total, winning, losing, win_rate,
         avg_win, avg_loss, pf) = _calc_win_loss_metrics(pnls)

        assert total == 2
        assert winning == 0
        assert losing == 2
        assert win_rate == Decimal("0")
        assert avg_win is None
        assert avg_loss == Decimal("-150")  # (-100 + -200) / 2
        assert pf is None

    def test_empty_pnls(self) -> None:
        """PnL 목록 없음 → zero-filled."""
        (total, winning, losing, win_rate,
         avg_win, avg_loss, pf) = _calc_win_loss_metrics([])

        assert total == 0
        assert winning == 0
        assert losing == 0
        assert win_rate == Decimal("0")
        assert avg_win is None
        assert avg_loss is None
        assert pf is None


# ---------------------------------------------------------------------------
# TestGetPerformanceMetrics
# ---------------------------------------------------------------------------


class TestGetPerformanceMetrics:
    """``PerformanceSummaryService.get_performance_metrics()`` — 통합 검증."""

    @pytest.mark.asyncio
    async def test_basic_metrics(self) -> None:
        """단순 시나리오: 1 winning order + equity 변화 → 모든 지표 정확성."""
        async with _setup_service() as service:
            repos = service._repos
            d1 = date(2026, 5, 1)
            d2 = date(2026, 5, 2)
            ts1 = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)

            # Cash snapshot at day before start (starting equity)
            day_before = d1 - timedelta(days=1)
            _add_cash_snapshot(repos, "1000000",
                               snapshot_at=datetime.combine(day_before, datetime.min.time(), tzinfo=timezone.utc))

            # Position snapshot at day before start
            pos_before = _make_position(quantity="10", average_price="50000", market_price="50000")
            repos.position_snapshots._items[pos_before.position_snapshot_id] = PositionSnapshotEntity(
                position_snapshot_id=pos_before.position_snapshot_id,
                account_id=pos_before.account_id,
                instrument_id=pos_before.instrument_id,
                quantity=pos_before.quantity,
                average_price=pos_before.average_price,
                market_price=pos_before.market_price,
                unrealized_pnl=pos_before.unrealized_pnl,
                source_of_truth=pos_before.source_of_truth,
                snapshot_at=datetime.combine(day_before, datetime.min.time(), tzinfo=timezone.utc),
            )

            # Day 1: 매도 10주 @ 55000 → +550000 (winning order)
            _add_order_with_fills(
                repos, OrderSide.SELL,
                fill_price="55000", fill_quantity="10",
                fill_timestamp=ts1,
            )

            metrics = await service.get_performance_metrics(
                _ACCOUNT_ID,
                start_date=d1,
                end_date=d2,
            )

            # starting_equity = cash(1000000) + position(10*50000=500000) = 1500000
            assert metrics.starting_equity == Decimal("1500000")
            # cumulative_realized_pnl = +550000
            assert metrics.cumulative_realized_pnl == Decimal("550000")
            # total_filled_orders = 1
            assert metrics.total_filled_orders == 1
            # winning_trades = 1 (550000 > 0)
            assert metrics.winning_trades == 1
            assert metrics.losing_trades == 0
            # win_rate = 100%
            assert metrics.win_rate == Decimal("100.0")
            assert metrics.avg_win == Decimal("550000")
            assert metrics.avg_loss is None
            assert metrics.profit_factor is None
            # period
            assert metrics.period_start == d1
            assert metrics.period_end == d2

    @pytest.mark.asyncio
    async def test_drawdown_scenario(self) -> None:
        """Equity peak → decline 구간 → max_drawdown 검증."""
        async with _setup_service() as service:
            repos = service._repos
            d1 = date(2026, 5, 1)
            d2 = date(2026, 5, 3)
            ts1 = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)

            # Cash snapshot before start
            day_before = d1 - timedelta(days=1)
            _add_cash_snapshot(repos, "1000000",
                               snapshot_at=datetime.combine(day_before, datetime.min.time(), tzinfo=timezone.utc))

            # Cash snapshot at day 1 (higher)
            _add_cash_snapshot(repos, "1200000",
                               snapshot_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc))

            # Cash snapshot at day 3 (decline)
            _add_cash_snapshot(repos, "900000",
                               snapshot_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc))

            # Day 1: order to make it "non-empty"
            _add_order_with_fills(
                repos, OrderSide.BUY,
                fill_price="50000", fill_quantity="1",
                fill_timestamp=ts1,
            )

            metrics = await service.get_performance_metrics(
                _ACCOUNT_ID,
                start_date=d1,
                end_date=d2,
            )

            # starting_equity = cash(1000000) + 0 positions = 1000000
            assert metrics.starting_equity == Decimal("1000000")
            # peak_equity = max(1000000, 1200000, 900000) = 1200000
            assert metrics.peak_equity == Decimal("1200000")
            # current_equity = 900000
            assert metrics.current_equity == Decimal("900000")
            # current_drawdown = (1200000 - 900000) / 1200000 * 100 = 25.0
            assert metrics.current_drawdown_pct == Decimal("25.0")
            # max_drawdown = same (single decline)
            assert metrics.max_drawdown_pct == Decimal("25.0")
            # cumulative return = (900000 - 1000000) / 1000000 * 100 = -10.0
            assert metrics.cumulative_return_pct == Decimal("-10.0")

    @pytest.mark.asyncio
    async def test_empty_account(self) -> None:
        """데이터 없음 → zero-filled metrics."""
        async with _setup_service() as service:
            d1 = date(2026, 5, 1)
            d2 = date(2026, 5, 3)

            metrics = await service.get_performance_metrics(
                _ACCOUNT_ID,
                start_date=d1,
                end_date=d2,
            )

            assert metrics.starting_equity == Decimal("0")
            assert metrics.current_equity == Decimal("0")
            assert metrics.cumulative_realized_pnl == Decimal("0")
            assert metrics.cumulative_return_pct == Decimal("0")
            assert metrics.peak_equity == Decimal("0")
            assert metrics.current_drawdown_pct == Decimal("0")
            assert metrics.max_drawdown_pct == Decimal("0")
            assert metrics.total_filled_orders == 0
            assert metrics.winning_trades == 0
            assert metrics.losing_trades == 0
            assert metrics.win_rate == Decimal("0")
            assert metrics.avg_win is None
            assert metrics.avg_loss is None
            assert metrics.profit_factor is None

    @pytest.mark.asyncio
    async def test_strategy_filter_metrics(self) -> None:
        """전략 필터 → 해당 전략 주문만 집계."""
        async with _setup_service() as service:
            repos = service._repos
            d1 = date(2026, 5, 1)
            d2 = date(2026, 5, 1)
            ts = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)

            # Cash snapshot
            _add_cash_snapshot(repos, "1000000")

            # Target strategy context
            ctx_id = uuid4()
            repos.decision_contexts._items[ctx_id] = DecisionContextEntity(
                decision_context_id=ctx_id,
                account_id=_ACCOUNT_ID,
                strategy_id=_STRATEGY_ID,
                config_version_id=uuid4(),
                market_timestamp=ts,
                correlation_id="CORR-TARGET",
            )

            # Other strategy
            other_strategy_id = uuid4()
            repos.strategies._items[other_strategy_id] = StrategyEntity(
                strategy_id=other_strategy_id,
                client_id=_CLIENT_ID,
                strategy_code="OTHER",
                name="Other",
                asset_class=AssetClass.KR_STOCK,
                status="active",
            )
            other_ctx_id = uuid4()
            repos.decision_contexts._items[other_ctx_id] = DecisionContextEntity(
                decision_context_id=other_ctx_id,
                account_id=_ACCOUNT_ID,
                strategy_id=other_strategy_id,
                config_version_id=uuid4(),
                market_timestamp=ts,
                correlation_id="CORR-OTHER",
            )

            # Target: winning order (+550000)
            _add_order_with_fills(
                repos, OrderSide.SELL,
                fill_price="55000", fill_quantity="10",
                decision_context_id=ctx_id,
                fill_timestamp=ts,
            )
            # Other: losing order (-500000) — should be excluded
            _add_order_with_fills(
                repos, OrderSide.BUY,
                fill_price="50000", fill_quantity="10",
                decision_context_id=other_ctx_id,
                fill_timestamp=ts,
            )

            metrics = await service.get_performance_metrics(
                _ACCOUNT_ID,
                start_date=d1,
                end_date=d2,
                strategy_id=_STRATEGY_ID,
            )

            # Only target strategy's order
            assert metrics.total_filled_orders == 1
            assert metrics.winning_trades == 1
            assert metrics.losing_trades == 0
            assert metrics.cumulative_realized_pnl == Decimal("550000")
            assert metrics.win_rate == Decimal("100.0")
