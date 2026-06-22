"""Duplicate Sell Guard — 중복 매도 방지 Layer.

``available_sell_qty`` 계산을 통해 시스템이 이미 매도 주문을 제출했거나
부분 체결된 주문이 있는 경우, 추가 매도 주문을 차단한다.

Design
------
``AvailableSellQtyResolver``는 순수 함수(pure function)로 설계되어
외부 I/O 없이 결정론적으로 동작한다. 호출자는 필요한 모든 데이터를
미리 준비하여 ``resolve()``에 전달한다.

계산식
------
    available_sell_qty = current_position_qty
                         - open_sell_qty
                         - partially_filled_remaining_qty

    - current_position_qty: 현재 포지션 수량 (position snapshot)
    - open_sell_qty: PENDING_SUBMIT / SUBMITTED / ACKNOWLEDGED 상태의
      SELL 주문 합계
    - partially_filled_remaining_qty: PARTIALLY_FILLED 상태 SELL 주문의
      미체결 수량 합계

Integration
-----------
``DecisionOrchestratorService.assemble_and_submit()``의 Phase 1.5+에서
SELL 주문에 대해서만 호출된다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from agent_trading.domain.entities import OrderRequestEntity
from agent_trading.domain.enums import OrderSide, OrderStatus, TimeInForce
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery

logger = logging.getLogger(__name__)
_KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# SellAvailability — guard 결과
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class SellAvailability:
    """Result of sell availability check.

    Attributes
    ----------
    available_sell_qty:
        계산된 매도 가능 수량. 0 이하이면 매도 불가.
    current_position_qty:
        현재 포지션 수량.
    open_sell_qty:
        진행 중인 SELL 주문의 합계 수량.
    partially_filled_remaining_qty:
        부분 체결된 SELL 주문의 미체결 수량 합계.
    is_blocked:
        ``True``이면 중복 매도로 간주하여 주문을 차단해야 함.
    blocking_reason:
        차단 사유 (``is_blocked=True``인 경우에만 설정).
    """

    available_sell_qty: Decimal
    current_position_qty: Decimal
    open_sell_qty: Decimal
    partially_filled_remaining_qty: Decimal
    is_blocked: bool
    blocking_reason: str | None = None


# ---------------------------------------------------------------------------
# AvailableSellQtyResolver
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AvailableSellQtyResolver:
    """중복 매도 방지를 위한 매도 가능 수량 계산기.

    Usage::

        resolver = AvailableSellQtyResolver(repos=repos)
        availability = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )
        if availability.is_blocked:
            logger.warning("Sell blocked: %s", availability.blocking_reason)
            # → SKIPPED 처리
    """

    repos: RepositoryContainer

    async def resolve(
        self,
        account_id: UUID,
        symbol: str,
        requested_qty: Decimal,
    ) -> SellAvailability:
        """매도 가능 수량을 계산하고 차단 여부를 반환한다.

        Parameters
        ----------
        account_id:
            계정 UUID.
        symbol:
            종목코드 (ex: ``"005930"``).
        requested_qty:
            요청된 매도 수량.

        Returns
        -------
        SellAvailability
            매도 가능 여부 및 상세 정보.
        """
        # ── 0. Resolve symbol → instrument_id ──
        instrument = await self.repos.instruments.get_by_symbol_any_market(symbol)
        instrument_id: UUID | None = instrument.instrument_id if instrument else None

        if instrument_id is None:
            logger.warning(
                "Instrument not found for symbol=%s, treating as zero position",
                symbol,
            )

        # ── 1. 현재 포지션 수량 조회 ──
        current_position_qty = await self._get_current_position_qty(
            account_id, instrument_id,
        )

        # ── 2. 진행 중인 SELL 주문 합계 ──
        open_sell_qty = await self._get_open_sell_qty(
            account_id, instrument_id,
        )

        # ── 3. 부분 체결된 SELL 주문의 미체결 수량 ──
        partially_filled_remaining_qty = await self._get_partially_filled_remaining_qty(
            account_id, instrument_id,
        )

        # ── 4. 계산 ──
        available_sell_qty = current_position_qty - open_sell_qty - partially_filled_remaining_qty

        # ── 5. 차단 판단 ──
        is_blocked = available_sell_qty < requested_qty
        blocking_reason: str | None = None

        if is_blocked:
            parts: list[str] = []
            if current_position_qty <= 0:
                parts.append(f"position_qty={current_position_qty} (no position)")
            if open_sell_qty > 0:
                parts.append(f"open_sell_qty={open_sell_qty}")
            if partially_filled_remaining_qty > 0:
                parts.append(f"partial_remaining={partially_filled_remaining_qty}")
            parts.append(f"available={available_sell_qty} < requested={requested_qty}")
            blocking_reason = "Sell guard blocked: " + "; ".join(parts)

            logger.info(
                "Sell guard BLOCKED: account_id=%s symbol=%s "
                "position=%s open_sell=%s partial_remaining=%s "
                "available=%s requested=%s",
                account_id, symbol,
                current_position_qty, open_sell_qty,
                partially_filled_remaining_qty,
                available_sell_qty, requested_qty,
            )
        else:
            logger.debug(
                "Sell guard ALLOW: account_id=%s symbol=%s "
                "available=%s requested=%s",
                account_id, symbol,
                available_sell_qty, requested_qty,
            )

        return SellAvailability(
            available_sell_qty=available_sell_qty,
            current_position_qty=current_position_qty,
            open_sell_qty=open_sell_qty,
            partially_filled_remaining_qty=partially_filled_remaining_qty,
            is_blocked=is_blocked,
            blocking_reason=blocking_reason,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_stale_day_order_residual(
        self,
        order: OrderRequestEntity,
        *,
        now: datetime,
    ) -> bool:
        """전일 ``DAY`` 주문의 잔량은 현재 거래일 sell guard에서 제외한다."""
        if order.time_in_force != TimeInForce.DAY:
            return False

        order_time = order.submitted_at or order.created_at
        if order_time is None:
            return False

        return order_time.astimezone(_KST).date() < now.astimezone(_KST).date()

    async def _get_current_position_qty(
        self,
        account_id: UUID,
        instrument_id: UUID | None,
    ) -> Decimal:
        """Get current position quantity from the latest position snapshot."""
        if instrument_id is None:
            return Decimal("0")

        try:
            snapshots = await self.repos.position_snapshots.list_latest_by_account(
                account_id,
            )
            if not snapshots:
                return Decimal("0")

            # Find the snapshot matching this instrument_id
            for snap in snapshots:
                if snap.instrument_id == instrument_id:
                    return snap.quantity
            return Decimal("0")
        except Exception as exc:
            logger.warning(
                "Failed to get position qty for account=%s instrument=%s: %s",
                account_id, instrument_id, exc,
            )
            return Decimal("0")

    async def _get_open_sell_qty(
        self,
        account_id: UUID,
        instrument_id: UUID | None,
    ) -> Decimal:
        """Sum quantities of open SELL orders (non-terminal, non-partial).

        Includes: PENDING_SUBMIT, SUBMITTED, ACKNOWLEDGED, RECONCILE_REQUIRED

        Stale PENDING_SUBMIT 주문 (30분 이상 경과 + broker_native_order_id 없음)은
        broker에 도달하지 못한 orphan으로 간주하여 open_sell_qty에서 제외한다.
        신선한 (30분 미만) PENDING_SUBMIT은 계속 집계하여 중복 매도를 방지한다.
        """
        if instrument_id is None:
            return Decimal("0")

        open_statuses = [
            OrderStatus.PENDING_SUBMIT,
            OrderStatus.SUBMITTED,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.RECONCILE_REQUIRED,
        ]
        orders = await self.repos.orders.list(
            OrderQuery(
                account_id=account_id,
                statuses=open_statuses,
                limit=200,
            )
        )

        now = datetime.now(timezone.utc)
        # 30분 이상 경과한 PENDING_SUBMIT을 stale로 판정
        stale_cutoff = now - timedelta(seconds=1800)

        total = Decimal("0")
        for order in orders:
            if order.instrument_id != instrument_id:
                continue
            if order.side != OrderSide.SELL:
                continue
            if self._is_stale_day_order_residual(order, now=now):
                logger.info(
                    "Excluding stale DAY SELL residual from open_sell_qty: "
                    "order_id=%s status=%s submitted_at=%s created_at=%s",
                    order.order_request_id,
                    order.status,
                    order.submitted_at,
                    order.created_at,
                )
                continue

            # Stale PENDING_SUBMIT 판정: 30분 이상 경과 + broker_native_order_id 없음
            if order.status == OrderStatus.PENDING_SUBMIT:
                if order.created_at is not None and order.created_at < stale_cutoff:
                    # broker_native_order_id 존재 여부 확인
                    broker_orders = await self.repos.broker_orders.list_by_order_request(
                        order.order_request_id,
                    )
                    has_broker_native_id = any(
                        bo.broker_native_order_id is not None for bo in broker_orders
                    )
                    if not has_broker_native_id:
                        # Stale PENDING_SUBMIT — open_sell_qty에서 제외
                        logger.debug(
                            "Excluding stale PENDING_SUBMIT from open_sell_qty: "
                            "order_id=%s created_at=%s",
                            order.order_request_id, order.created_at,
                        )
                        continue

            total += order.requested_quantity

        return total

    async def _get_partially_filled_remaining_qty(
        self,
        account_id: UUID,
        instrument_id: UUID | None,
    ) -> Decimal:
        """Sum remaining quantities of PARTIALLY_FILLED SELL orders.

        remaining_qty = order.quantity - sum(fill_events.fill_quantity)
        """
        if instrument_id is None:
            return Decimal("0")

        now = datetime.now(timezone.utc)
        orders = await self.repos.orders.list(
            OrderQuery(
                account_id=account_id,
                statuses=[OrderStatus.PARTIALLY_FILLED],
                limit=100,
            )
        )

        total_remaining = Decimal("0")
        for order in orders:
            if order.instrument_id != instrument_id:
                continue
            if order.side != OrderSide.SELL:
                continue
            if self._is_stale_day_order_residual(order, now=now):
                logger.info(
                    "Excluding stale DAY SELL residual from partial_remaining: "
                    "order_id=%s submitted_at=%s created_at=%s",
                    order.order_request_id,
                    order.submitted_at,
                    order.created_at,
                )
                continue

            # Get broker orders for this order request
            broker_orders = await self.repos.broker_orders.list_by_order_request(
                order.order_request_id,
            )
            if not broker_orders:
                continue

            for bo in broker_orders:
                # Get fill events for this broker order
                fills = await self.repos.fill_events.list_by_broker_order(
                    bo.broker_order_id,
                )
                filled_qty = sum(f.fill_quantity for f in fills)
                remaining = order.requested_quantity - filled_qty
                if remaining > 0:
                    total_remaining += remaining

        return total_remaining

    async def _sum_sell_order_qty(
        self,
        account_id: UUID,
        instrument_id: UUID | None,
        statuses: list[OrderStatus],
    ) -> Decimal:
        """Sum quantities of SELL orders matching given statuses."""
        if instrument_id is None:
            return Decimal("0")

        orders = await self.repos.orders.list(
            OrderQuery(
                account_id=account_id,
                statuses=statuses,
                limit=200,
            )
        )

        total = Decimal("0")
        for order in orders:
            if order.instrument_id != instrument_id:
                continue
            if order.side != OrderSide.SELL:
                continue
            total += order.requested_quantity

        return total
