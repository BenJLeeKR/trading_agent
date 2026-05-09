"""Performance summary service — read-only PnL/equity aggregation.

**Mode-agnostic**: This module works identically in both paper and live
modes.  It reads fills, positions, and cash balance from repositories
without any broker-env-specific logic.  The "Paper" in the legacy filename
reflects the initial implementation context only.

Pure functions
==============
* :func:`calc_realized_pnl_for_order` — fill 집합 → 실현 손익
* :func:`calc_unrealized_pnl_from_positions` — position snapshot → 미실현 손익
* :func:`calc_position_market_value` — position snapshot → 평가액

Service class
=============
* :class:`PerformanceSummaryService` — repository access + summary assembly
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID

from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    FillEventEntity,
    PositionSnapshotEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery


# =========================================================================
# Pure functions — 결정론적 PnL 계산, 테스트 용이
# =========================================================================


def calc_realized_pnl_for_order(
    fills: Sequence[FillEventEntity],
    side: OrderSide,
) -> Decimal:
    """단일 주문의 realized PnL을 계산합니다.

    Parameters
    ----------
    fills:
        이 주문에 속한 체결 내역.
    side:
        주문 방향 (BUY / SELL).

    Returns
    -------
    Decimal
        실현 손익 합계. BUY는 음수 현금 흐름, SELL은 양수 현금 흐름.
        fee/tax가 있으면 차감합니다.
    """
    total = Decimal("0")
    multiplier = Decimal("-1") if side == OrderSide.BUY else Decimal("1")

    for fill in fills:
        trade_value = fill.fill_price * fill.fill_quantity * multiplier
        fee = fill.fill_fee or Decimal("0")
        tax = fill.fill_tax or Decimal("0")
        total += trade_value - fee - tax

    return total


def calc_unrealized_pnl_from_positions(
    positions: Sequence[PositionSnapshotEntity],
) -> Decimal:
    """포지션 snapshot 기반 미실현 손익을 계산합니다.

    ``market_price``가 ``None``인 포지션은 계산에서 제외됩니다
    (가격 정보 부족 → 0으로 간주).
    """
    total = Decimal("0")
    for pos in positions:
        if pos.market_price is None:
            continue
        total += pos.quantity * (pos.market_price - pos.average_price)
    return total


def _calc_per_fill_pnl(fill: FillEventEntity, side: OrderSide) -> Decimal:
    """단일 체결의 realized PnL을 계산합니다.

    Parameters
    ----------
    fill:
        체결 내역.
    side:
        주문 방향 (BUY / SELL).

    Returns
    -------
    Decimal
        이 체결의 실현 손익. BUY는 음수 현금 흐름, SELL은 양수 현금 흐름.
        fee/tax가 있으면 차감합니다.
    """
    multiplier = Decimal("-1") if side == OrderSide.BUY else Decimal("1")
    trade_value = fill.fill_price * fill.fill_quantity * multiplier
    fee = fill.fill_fee or Decimal("0")
    tax = fill.fill_tax or Decimal("0")
    return trade_value - fee - tax


def _latest_cash_on_or_before(
    cash_snapshots: Sequence[CashBalanceSnapshotEntity],
    target_date: date,
) -> CashBalanceSnapshotEntity | None:
    """``target_date`` 이하 시각의 가장 최신 현금 snapshot을 반환합니다.

    ``cash_snapshots``는 ``snapshot_at`` DESC 정렬되어 있어야 합니다.
    조건에 맞는 snapshot이 없으면 ``None``을 반환합니다.
    """
    for snap in cash_snapshots:
        if snap.snapshot_at.date() <= target_date:
            return snap
    return None


def _latest_positions_on_or_before(
    positions: Sequence[PositionSnapshotEntity],
    target_date: date,
) -> Sequence[PositionSnapshotEntity]:
    """``target_date`` 이하 시각의 가장 최신 position snapshot을
    instrument_id별로 하나씩 반환합니다.

    ``positions``는 ``snapshot_at`` DESC 정렬되어 있어야 합니다.
    조건에 맞는 snapshot이 없으면 빈 시퀀스를 반환합니다.
    """
    selected: dict[UUID, PositionSnapshotEntity] = {}
    for pos in positions:
        if pos.snapshot_at.date() <= target_date and pos.instrument_id not in selected:
            selected[pos.instrument_id] = pos
    return tuple(selected.values())


def calc_position_market_value(
    positions: Sequence[PositionSnapshotEntity],
) -> Decimal:
    """포지션 평가액을 계산합니다.

    ``market_price``가 ``None``인 포지션은 제외됩니다.
    평가액 = Σ |quantity| × market_price (절대값, 숏 포지션도 양수 평가액)
    """
    total = Decimal("0")
    for pos in positions:
        if pos.market_price is None:
            continue
        total += abs(pos.quantity) * pos.market_price
    return total


# =========================================================================
# Summary models
# =========================================================================


@dataclass(slots=True, frozen=True)
class AccountPerformanceSummary:
    """계좌 수준 성과 요약 — paper 운용 성과 평가용 Read Model."""

    account_id: UUID
    """계좌 ID."""

    as_of: datetime
    """집계 기준 시점 (최신 cash snapshot 시각)."""

    cash_balance: Decimal
    """최신 현금 잔고 (``CashBalanceSnapshotEntity.available_cash``)."""

    position_market_value: Decimal
    """포지션 평가액 (snapshot market price 기준)."""

    total_equity: Decimal
    """총 평가액 = ``cash_balance + position_market_value``."""

    realized_pnl: Decimal
    """실현 손익 (누적, 모든 FILLED/PARTIALLY_FILLED 주문 체결 합계)."""

    unrealized_pnl: Decimal
    """미실현 손익 (최신 position snapshot 기준)."""

    total_pnl: Decimal = field(init=False)
    """총 손익 = ``realized_pnl + unrealized_pnl``."""

    filled_order_count: int
    """FILLED 또는 PARTIALLY_FILLED 상태인 주문 수."""

    open_position_count: int
    """미결제 포지션 수 (snapshot에 존재하는 position 수)."""

    winning_trade_count: int
    """이익이 발생한 체결 그룹 수 (realized_pnl > 0)."""

    losing_trade_count: int
    """손실이 발생한 체결 그룹 수 (realized_pnl < 0)."""

    def __post_init__(self) -> None:
        # total_pnl은 realized + unrealized로 항상 결정
        object.__setattr__(self, "total_pnl", self.realized_pnl + self.unrealized_pnl)


@dataclass(slots=True, frozen=True)
class StrategyPerformanceSummary:
    """전략 수준 성과 요약 — 전략별 기여도 평가용 Read Model."""

    account_id: UUID
    strategy_id: UUID
    as_of: datetime
    realized_pnl: Decimal
    filled_order_count: int
    winning_trade_count: int
    losing_trade_count: int


@dataclass(slots=True, frozen=True)
class DailyPerformancePoint:
    """일별 성과 포인트 — paper 운용 성과 시계열의 단일 데이터 포인트.

    하나의 날짜에 대해 realized/unrealized PnL, 현금 잔고, 포지션 평가액,
    총 평가액을 포함합니다. snapshot 기반 필드는 데이터가 없으면 ``None``입니다.
    """

    date: date
    """데이터 포인트 기준 날짜."""

    realized_pnl: Decimal
    """해당일 체결 기준 실현 손익 (fill_timestamp.date() 귀속).
    체결이 없는 날짜는 ``Decimal("0")``입니다."""

    cumulative_realized_pnl: Decimal
    """``start_date``부터 해당일까지 누적 실현 손익."""

    cash_balance: Decimal | None = None
    """해당일 마지막 현금 snapshot의 ``available_cash``.
    snapshot이 없으면 ``None``."""

    position_market_value: Decimal | None = None
    """해당일 마지막 position snapshot 기준 포지션 평가액.
    snapshot이 없으면 ``None``."""

    unrealized_pnl: Decimal | None = None
    """해당일 미실현 손익.
    snapshot이 없으면 ``None``."""

    total_equity: Decimal | None = None
    """해당일 총 평가액 = ``cash_balance + position_market_value``.
    두 값 중 하나라도 없으면 ``None``."""


@dataclass(slots=True, frozen=True)
class PerformanceMetrics:
    """기간 기반 성과 지표 — cumulative return / drawdown / win-rate 등.

    ``get_performance_metrics()``의 반환 타입으로,
    주어진 기간(start_date ~ end_date)에 대해 계산된 핵심 성과 지표를 담습니다.
    """

    account_id: UUID
    strategy_id: UUID | None
    period_start: date
    period_end: date

    starting_equity: Decimal
    """기간 시작 시점 평가액 (period_start - 1일 기준 snapshot)."""

    current_equity: Decimal
    """기간 종료 시점 평가액 (period_end 기준 equity history 마지막 값)."""

    cumulative_realized_pnl: Decimal
    """기간 내 realized PnL 합계 (per-order 기준)."""

    cumulative_return_pct: Decimal
    """기간 누적 수익률 = (current_equity - starting_equity) / starting_equity * 100.
    starting_equity가 0이면 0."""

    peak_equity: Decimal
    """기간 중 최고 equity (starting_equity 포함)."""

    current_drawdown_pct: Decimal
    """현재 drawdown = (peak_equity - current_equity) / peak_equity * 100."""

    max_drawdown_pct: Decimal
    """기간 중 최대 drawdown (peak 대비 낙폭 최대치)."""

    total_filled_orders: int
    """FILLED/PARTIALLY_FILLED 주문 수."""

    winning_trades: int
    """realized_pnl > 0인 주문 수."""

    losing_trades: int
    """realized_pnl < 0인 주문 수."""

    win_rate: Decimal
    """승률 = winning_trades / total_filled_orders * 100 (percentage).
    total_filled_orders가 0이면 0."""

    avg_win: Decimal | None
    """평균 승리 금액 = sum(winning_pnl) / winning_trades.
    winning_trades가 0이면 None."""

    avg_loss: Decimal | None
    """평균 손실 금액 = sum(losing_pnl) / losing_trades (음수).
    losing_trades가 0이면 None."""

    profit_factor: Decimal | None
    """Profit factor = sum(winning_pnl) / abs(sum(losing_pnl)).
    losing_trades가 0이면 None (0으로 나누기 방지)."""


# =========================================================================
# Pure helpers — metrics 계산
# =========================================================================


def _calc_equity_metrics(
    points: Sequence[DailyPerformancePoint],
    starting_equity: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """equity history에서 return/drawdown 지표를 계산합니다.

    Parameters
    ----------
    points:
        일별 성과 포인트 목록 (start_date→end_date 순).
    starting_equity:
        기간 시작 시점 평가액.

    Returns
    -------
    tuple[Decimal, Decimal, Decimal, Decimal, Decimal]
        (cumulative_return_pct, current_equity, peak_equity,
         current_drawdown_pct, max_drawdown_pct)
    """
    equities = [
        p.total_equity for p in points if p.total_equity is not None
    ]

    if not equities:
        current_equity = starting_equity
        peak_equity = starting_equity
        cumulative_return_pct = Decimal("0")
        current_drawdown_pct = Decimal("0")
        max_drawdown_pct = Decimal("0")
        return (
            cumulative_return_pct,
            current_equity,
            peak_equity,
            current_drawdown_pct,
            max_drawdown_pct,
        )

    current_equity = equities[-1]

    # Cumulative return
    if starting_equity > 0:
        cumulative_return_pct = (
            (current_equity - starting_equity) / starting_equity * 100
        )
    else:
        cumulative_return_pct = Decimal("0")

    # Drawdown (rolling peak)
    peak_equity = starting_equity
    max_drawdown_pct = Decimal("0")

    for eq in equities:
        if eq > peak_equity:
            peak_equity = eq
        if peak_equity > 0:
            drawdown = (peak_equity - eq) / peak_equity * 100
            if drawdown > max_drawdown_pct:
                max_drawdown_pct = drawdown

    current_drawdown_pct = (
        (peak_equity - current_equity) / peak_equity * 100
        if peak_equity > 0
        else Decimal("0")
    )

    return (
        cumulative_return_pct,
        current_equity,
        peak_equity,
        current_drawdown_pct,
        max_drawdown_pct,
    )


def _calc_win_loss_metrics(
    per_order_pnls: Sequence[Decimal],
) -> tuple[int, int, int, Decimal, Decimal | None, Decimal | None, Decimal | None]:
    """per-order PnL 목록에서 win/loss 지표를 계산합니다.

    Parameters
    ----------
    per_order_pnls:
        각 filled order의 realized PnL. 0인 항목은 win/loss에 포함되지 않습니다.

    Returns
    -------
    tuple[int, int, int, Decimal, Decimal | None, Decimal | None, Decimal | None]
        (total_filled_orders, winning_trades, losing_trades,
         win_rate, avg_win, avg_loss, profit_factor)
    """
    total = len(per_order_pnls)
    winning = sum(1 for pnl in per_order_pnls if pnl > 0)
    losing = sum(1 for pnl in per_order_pnls if pnl < 0)

    win_rate: Decimal
    if total > 0:
        win_rate = Decimal(str(winning)) / Decimal(str(total)) * 100
    else:
        win_rate = Decimal("0")

    winning_pnls = [pnl for pnl in per_order_pnls if pnl > 0]
    losing_pnls = [pnl for pnl in per_order_pnls if pnl < 0]

    avg_win: Decimal | None = (
        sum(winning_pnls) / Decimal(str(len(winning_pnls)))
        if winning_pnls
        else None
    )

    avg_loss: Decimal | None = (
        sum(losing_pnls) / Decimal(str(len(losing_pnls)))
        if losing_pnls
        else None
    )

    profit_factor: Decimal | None = None
    losing_sum = sum(losing_pnls) if losing_pnls else Decimal("0")
    if losing_sum != 0 and winning_pnls:
        winning_sum = sum(winning_pnls)
        profit_factor = winning_sum / abs(losing_sum)

    return (total, winning, losing, win_rate, avg_win, avg_loss, profit_factor)


# =========================================================================
# Service
# =========================================================================


class PerformanceSummaryService:
    """Read-only performance summary service.

    모든 PnL 계산은 pure function에 위임하며,
    이 서비스는 repository access와 assembly만 담당합니다.
    """

    def __init__(self, repos: RepositoryContainer) -> None:
        self._repos = repos

    async def get_account_summary(
        self,
        account_id: UUID,
    ) -> AccountPerformanceSummary:
        """계좌 수준 성과 요약을 반환합니다.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.

        Returns
        -------
        AccountPerformanceSummary
            계산 가능한 모든 지표가 채워진 요약.
        """
        # 1. Cash
        cash_snap = await self._repos.cash_balance_snapshots.get_latest_by_account(
            account_id
        )
        cash = cash_snap.available_cash if cash_snap else Decimal("0")
        as_of = cash_snap.snapshot_at if cash_snap else datetime.now(timezone.utc)

        # 2. Positions → unrealized PnL
        positions = await self._repos.position_snapshots.list_latest_by_account(
            account_id
        )
        unrealized = calc_unrealized_pnl_from_positions(positions)
        pos_market_value = calc_position_market_value(positions)

        # 3. Orders → fills → realized PnL
        all_orders = await self._repos.orders.list(
            OrderQuery(account_id=account_id)
        )
        filled_orders = [
            o
            for o in all_orders
            if o.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
        ]

        realized_pnl = Decimal("0")
        winning = 0
        losing = 0

        for order in filled_orders:
            broker_orders = (
                await self._repos.broker_orders.list_by_order_request(
                    order.order_request_id
                )
            )
            order_fills: list[FillEventEntity] = []
            for bo in broker_orders:
                fills = await self._repos.fill_events.list_by_broker_order(
                    bo.broker_order_id
                )
                order_fills.extend(fills)

            if order_fills:
                pnl = calc_realized_pnl_for_order(order_fills, order.side)
                realized_pnl += pnl
                if pnl > 0:
                    winning += 1
                elif pnl < 0:
                    losing += 1

        total_equity = cash + pos_market_value

        return AccountPerformanceSummary(
            account_id=account_id,
            as_of=as_of,
            cash_balance=cash,
            position_market_value=pos_market_value,
            total_equity=total_equity,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized,
            filled_order_count=len(filled_orders),
            open_position_count=len(positions),
            winning_trade_count=winning,
            losing_trade_count=losing,
        )

    async def get_strategy_summary(
        self,
        account_id: UUID,
        strategy_id: UUID,
    ) -> StrategyPerformanceSummary:
        """전략 수준 성과 요약을 반환합니다.

        decision_context → trade_decision 체인을 통해
        특정 strategy에 속한 주문만 필터링합니다.
        """
        all_orders = await self._repos.orders.list(
            OrderQuery(account_id=account_id)
        )
        as_of = datetime.now(timezone.utc)

        realized_pnl = Decimal("0")
        winning = 0
        losing = 0
        filled_count = 0

        for order in all_orders:
            if order.status not in (
                OrderStatus.FILLED,
                OrderStatus.PARTIALLY_FILLED,
            ):
                continue

            # decision_context를 통해 strategy 확인
            if order.decision_context_id is None:
                continue
            ctx = await self._repos.decision_contexts.get(
                order.decision_context_id
            )
            if ctx is None or ctx.strategy_id != strategy_id:
                continue

            # 이 주문은 대상 strategy에 속함
            broker_orders = (
                await self._repos.broker_orders.list_by_order_request(
                    order.order_request_id
                )
            )
            order_fills: list[FillEventEntity] = []
            for bo in broker_orders:
                fills = await self._repos.fill_events.list_by_broker_order(
                    bo.broker_order_id
                )
                order_fills.extend(fills)

            if order_fills:
                pnl = calc_realized_pnl_for_order(order_fills, order.side)
                realized_pnl += pnl
                filled_count += 1
                if pnl > 0:
                    winning += 1
                elif pnl < 0:
                    losing += 1

        return StrategyPerformanceSummary(
            account_id=account_id,
            strategy_id=strategy_id,
            as_of=as_of,
            realized_pnl=realized_pnl,
            filled_order_count=filled_count,
            winning_trade_count=winning,
            losing_trade_count=losing,
        )

    async def get_daily_history(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
        strategy_id: UUID | None = None,
    ) -> Sequence[DailyPerformancePoint]:
        """계좌의 일별 성과 히스토리를 반환합니다.

        ``start_date``부터 ``end_date``까지 각 날짜에 대해:

        - realized_pnl: 체결일 기준 실현 손익
        - cumulative_realized_pnl: ``start_date``부터 해당일까지 누적
        - cash_balance / position_market_value / unrealized_pnl: snapshot 기준
        - total_equity: 현금 + 포지션 평가액

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.
        start_date:
            집계 시작일 (이 날짜 포함).
        end_date:
            집계 종료일 (이 날짜 포함).
        strategy_id:
            특정 전략으로 필터링할 경우 전략 UUID. ``None``이면 전체.
        """
        # ── 1. Orders → strategy filter ──
        all_orders = await self._repos.orders.list(
            OrderQuery(account_id=account_id)
        )

        if strategy_id is not None:
            strategy_orders: list = []
            for order in all_orders:
                if order.decision_context_id is None:
                    continue
                ctx = await self._repos.decision_contexts.get(
                    order.decision_context_id
                )
                if ctx is not None and ctx.strategy_id == strategy_id:
                    strategy_orders.append(order)
            all_orders = strategy_orders

        filled_orders = [
            o
            for o in all_orders
            if o.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
        ]

        # ── 2. Per-fill realized PnL → daily buckets ──
        daily_realized: dict[date, Decimal] = {}

        for order in filled_orders:
            broker_orders = (
                await self._repos.broker_orders.list_by_order_request(
                    order.order_request_id
                )
            )
            for bo in broker_orders:
                fills = await self._repos.fill_events.list_by_broker_order(
                    bo.broker_order_id
                )
                for fill in fills:
                    pnl = _calc_per_fill_pnl(fill, order.side)
                    day = fill.fill_timestamp.date()
                    daily_realized[day] = daily_realized.get(day, Decimal("0")) + pnl

        # ── 3. Position snapshots (all, per-day selection) ──
        all_positions = (
            await self._repos.position_snapshots.list_latest_by_account(account_id)
        )

        # ── 4. Cash snapshots (all, per-day selection) ──
        all_cash = await self._repos.cash_balance_snapshots.list_by_account(
            account_id
        )

        # ── 5. Build daily points ──
        points: list[DailyPerformancePoint] = []
        cumulative_realized = Decimal("0")
        current_date = start_date

        while current_date <= end_date:
            realized = daily_realized.get(current_date, Decimal("0"))
            cumulative_realized += realized

            # Cash: latest on or before current_date
            cash_snap = _latest_cash_on_or_before(all_cash, current_date)
            cash = cash_snap.available_cash if cash_snap else None

            # Positions: per-instrument latest on or before current_date
            day_positions = _latest_positions_on_or_before(
                all_positions, current_date
            )
            if day_positions:
                pos_market_value = calc_position_market_value(day_positions)
                unrealized = calc_unrealized_pnl_from_positions(day_positions)
            else:
                pos_market_value = None
                unrealized = None

            total_equity: Decimal | None = None
            if cash is not None and pos_market_value is not None:
                total_equity = cash + pos_market_value
            elif cash is not None:
                total_equity = cash

            points.append(
                DailyPerformancePoint(
                    date=current_date,
                    realized_pnl=realized,
                    cumulative_realized_pnl=cumulative_realized,
                    cash_balance=cash,
                    position_market_value=pos_market_value,
                    unrealized_pnl=unrealized,
                    total_equity=total_equity,
                )
            )

            current_date += timedelta(days=1)

        return tuple(points)

    async def get_performance_metrics(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
        strategy_id: UUID | None = None,
    ) -> PerformanceMetrics:
        """기간 기반 성과 지표를 계산합니다.

        ``start_date``부터 ``end_date``까지의 equity history와
        per-order PnL을 기반으로 cumulative return / drawdown / win-rate /
        avg win-loss / profit factor를 계산합니다.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.
        start_date:
            집계 시작일 (이 날짜 포함).
        end_date:
            집계 종료일 (이 날짜 포함).
        strategy_id:
            특정 전략으로 필터링할 경우 전략 UUID. ``None``이면 전체.

        Returns
        -------
        PerformanceMetrics
            계산 가능한 모든 성과 지표.
        """
        # ── 1. Equity history ──
        points = await self.get_daily_history(
            account_id, start_date, end_date, strategy_id
        )

        # ── 2. Starting equity (start_date - 1일 기준) ──
        all_cash = await self._repos.cash_balance_snapshots.list_by_account(
            account_id
        )
        all_positions = (
            await self._repos.position_snapshots.list_latest_by_account(account_id)
        )

        day_before = start_date - timedelta(days=1)
        cash_snap = _latest_cash_on_or_before(all_cash, day_before)
        cash = cash_snap.available_cash if cash_snap else Decimal("0")

        day_before_positions = _latest_positions_on_or_before(
            all_positions, day_before
        )
        pos_market_value = calc_position_market_value(day_before_positions)

        starting_equity = cash + pos_market_value

        # ── 3. Equity metrics (return / drawdown) ──
        (
            cumulative_return_pct,
            current_equity,
            peak_equity,
            current_drawdown_pct,
            max_drawdown_pct,
        ) = _calc_equity_metrics(points, starting_equity)

        # ── 4. Per-order PnL → win/loss metrics ──
        all_orders = await self._repos.orders.list(
            OrderQuery(account_id=account_id)
        )

        if strategy_id is not None:
            strategy_orders: list = []
            for order in all_orders:
                if order.decision_context_id is None:
                    continue
                ctx = await self._repos.decision_contexts.get(
                    order.decision_context_id
                )
                if ctx is not None and ctx.strategy_id == strategy_id:
                    strategy_orders.append(order)
            all_orders = strategy_orders

        filled_orders = [
            o
            for o in all_orders
            if o.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
        ]

        per_order_pnls: list[Decimal] = []
        cumulative_realized = Decimal("0")

        for order in filled_orders:
            broker_orders = (
                await self._repos.broker_orders.list_by_order_request(
                    order.order_request_id
                )
            )
            order_fills: list[FillEventEntity] = []
            for bo in broker_orders:
                fills = await self._repos.fill_events.list_by_broker_order(
                    bo.broker_order_id
                )
                order_fills.extend(fills)

            if order_fills:
                pnl = calc_realized_pnl_for_order(order_fills, order.side)
                cumulative_realized += pnl
                per_order_pnls.append(pnl)

        (
            total_filled,
            winning,
            losing,
            win_rate,
            avg_win,
            avg_loss,
            profit_factor,
        ) = _calc_win_loss_metrics(per_order_pnls)

        return PerformanceMetrics(
            account_id=account_id,
            strategy_id=strategy_id,
            period_start=start_date,
            period_end=end_date,
            starting_equity=starting_equity,
            current_equity=current_equity,
            cumulative_realized_pnl=cumulative_realized,
            cumulative_return_pct=cumulative_return_pct,
            peak_equity=peak_equity,
            current_drawdown_pct=current_drawdown_pct,
            max_drawdown_pct=max_drawdown_pct,
            total_filled_orders=total_filled,
            winning_trades=winning,
            losing_trades=losing,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
        )
