from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    BrokerOrderEntity,
    FillEventEntity,
    OrderRequestEntity,
)
from agent_trading.domain.enums import OrderStatus
from agent_trading.domain.models import FillEvent, OrderStatusResult
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.order_manager import OrderManager

logger = logging.getLogger(__name__)

# ── Statuses that OrderSyncService will attempt to sync ──
_SYNCABLE_STATUSES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.SUBMITTED,
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED,
    }
)

# ── Terminal states (no further sync needed, snapshot refresh may apply) ──
_TERMINAL_STATUSES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)


@dataclass(slots=True, frozen=True)
class SyncOrderResult:
    """Result of a single ``sync_order_post_submit()`` call."""

    broker_order_id: UUID
    previous_status: OrderStatus
    current_status: OrderStatus
    status_changed: bool
    fills_synced: int
    fills_skipped: int
    terminal: bool
    snapshot_triggered: bool
    last_synced_at: datetime
    error: str | None = None


@dataclass(slots=True)
class OrderSyncService:
    """Post-submit order status/fill sync service.

    Broker에 제출된 주문의 상태와 체결 내역을 주기적으로 조회하여
    시스템 내부 상태에 반영한다.

    Reconciliation 경로와 충돌하지 않도록 설계되며, 오직
    ``SUBMITTED`` / ``ACKNOWLEDGED`` / ``PARTIALLY_FILLED`` 상태의
    주문에 대해서만 동작한다.

    ``RECONCILE_REQUIRED`` 상태의 주문은 ``ReconciliationService``가
    담당하므로 이 서비스의 범위를 벗어난다.
    """

    repos: RepositoryContainer
    order_manager: OrderManager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def sync_order_post_submit(
        self,
        account_ref: str,
        broker: BrokerAdapter,
        broker_order_id: UUID,
        *,
        snapshot_refresh_cb: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> SyncOrderResult:
        """Post-submit sync의 단일 진입점.

        1. ``broker_order_id`` → ``BrokerOrderEntity`` 조회
        2. ``broker.get_order_status()`` → ``OrderStatusResult``
        3. Broker status → Internal ``OrderStatus`` 매핑
        4. 상태 변경 필요시 ``OrderManager.transition_to()`` 호출 (chain 전이 지원)
        5. ``broker.get_fills()`` → ``FillEventEntity`` 저장 (since=last_synced_at)
        6. ``BrokerOrderEntity.last_synced_at`` 갱신
        7. Terminal state (FILLED) 도달시 ``snapshot_refresh_cb`` 호출

        Parameters
        ----------
        account_ref:
            Broker account reference string.
        broker:
            The broker adapter to query.
        broker_order_id:
            Internal ``BrokerOrderEntity.broker_order_id`` (UUID).
        snapshot_refresh_cb:
            Optional callback invoked when the order reaches FILLED.
            Receives ``AccountEntity.account_id`` (UUID).

        Returns
        -------
        SyncOrderResult
            Summary of the sync operation.
        """
        now = datetime.now(timezone.utc)

        # ── 1. Resolve broker order entity ──
        broker_order = await self.repos.broker_orders.get(broker_order_id)
        if broker_order is None:
            return SyncOrderResult(
                broker_order_id=broker_order_id,
                previous_status=OrderStatus.RECONCILE_REQUIRED,
                current_status=OrderStatus.RECONCILE_REQUIRED,
                status_changed=False,
                fills_synced=0,
                fills_skipped=0,
                terminal=False,
                snapshot_triggered=False,
                last_synced_at=now,
                error=f"BrokerOrder not found: {broker_order_id}",
            )

        # ── 2. Resolve order request entity ──
        order = await self.repos.orders.get(broker_order.order_request_id)
        if order is None:
            return SyncOrderResult(
                broker_order_id=broker_order_id,
                previous_status=OrderStatus.RECONCILE_REQUIRED,
                current_status=OrderStatus.RECONCILE_REQUIRED,
                status_changed=False,
                fills_synced=0,
                fills_skipped=0,
                terminal=False,
                snapshot_triggered=False,
                last_synced_at=now,
                error=f"OrderRequest not found: {broker_order.order_request_id}",
            )

        previous_status = order.status

        # ── Skip if already terminal or not syncable ──
        if order.status in _TERMINAL_STATUSES:
            # Still update last_synced_at for record-keeping.
            await self._update_last_synced_at(broker_order_id, now)
            return SyncOrderResult(
                broker_order_id=broker_order_id,
                previous_status=previous_status,
                current_status=previous_status,
                status_changed=False,
                fills_synced=0,
                fills_skipped=0,
                terminal=True,
                snapshot_triggered=False,
                last_synced_at=now,
            )

        if order.status not in _SYNCABLE_STATUSES:
            # Not syncable (DRAFT, VALIDATED, PENDING_SUBMIT, RECONCILE_REQUIRED, CANCEL_PENDING).
            return SyncOrderResult(
                broker_order_id=broker_order_id,
                previous_status=previous_status,
                current_status=previous_status,
                status_changed=False,
                fills_synced=0,
                fills_skipped=0,
                terminal=False,
                snapshot_triggered=False,
                last_synced_at=now,
                error=f"Order in non-syncable status: {order.status.value}",
            )

        # ── 3. Inquire broker for current status ──
        try:
            status_result = await broker.get_order_status(
                account_ref,
                client_order_id=order.client_order_id or "",
                broker_order_id=broker_order.broker_native_order_id,
            )
        except Exception as exc:
            logger.warning(
                "get_order_status failed for broker_order=%s: %s",
                broker_order_id, exc,
            )
            return SyncOrderResult(
                broker_order_id=broker_order_id,
                previous_status=previous_status,
                current_status=previous_status,
                status_changed=False,
                fills_synced=0,
                fills_skipped=0,
                terminal=False,
                snapshot_triggered=False,
                last_synced_at=now,
                error=f"get_order_status failed: {exc}",
            )

        broker_status: OrderStatus = status_result.status

        # ── 4. Update broker-side status on BrokerOrderEntity ──
        if broker_order.broker_status != broker_status.value:
            await self.repos.broker_orders.update(
                broker_order_id,
                broker_status=broker_status.value,
                updated_at=now,
            )

        # ── 5. Sync internal order state if status changed ──
        status_changed = False
        if broker_status != previous_status:
            order = await self._try_transition(order, broker_status)
            status_changed = order.status != previous_status

        # ── 6. Sync fill events ──
        fills_synced, fills_skipped = await self._sync_fills(
            broker_order,
            broker,
            account_ref,
            since=broker_order.last_synced_at,
        )

        # ── 7. Update last_synced_at ──
        await self._update_last_synced_at(broker_order_id, now)

        # ── 8. Snapshot refresh if FILLED ──
        current_status = order.status
        terminal = current_status in _TERMINAL_STATUSES
        snapshot_triggered = False
        if terminal and current_status == OrderStatus.FILLED and snapshot_refresh_cb is not None:
            try:
                await snapshot_refresh_cb(order.account_id)
                snapshot_triggered = True
            except Exception as exc:
                logger.warning(
                    "Snapshot refresh callback failed for account=%s: %s",
                    order.account_id, exc,
                )

        return SyncOrderResult(
            broker_order_id=broker_order_id,
            previous_status=previous_status,
            current_status=current_status,
            status_changed=status_changed,
            fills_synced=fills_synced,
            fills_skipped=fills_skipped,
            terminal=terminal,
            snapshot_triggered=snapshot_triggered,
            last_synced_at=now,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _try_transition(
        self,
        order: OrderRequestEntity,
        target_status: OrderStatus,
    ) -> OrderRequestEntity:
        """Attempt to transition order to target status.

        Direct transition이 허용되지 않는 경우 chain 전이를 시도한다.
        예: SUBMITTED → FILLED 는 직접 불가능하지만
        SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED → FILLED 는 가능.

        각 단계는 독립적인 ``OrderManager.transition_to()`` 호출로
        수행되며, optimistic locking이 적용된다.
        중간 단계 실패시 현재까지 성공한 상태를 반환한다.
        """
        # ── Already at target ──
        if order.status == target_status:
            return order

        # ── Direct transition attempt ──
        try:
            return await self.order_manager.transition_to(order, target_status)
        except Exception:
            logger.info(
                "Direct transition %s→%s failed, trying chain",
                order.status.value, target_status.value,
            )

        # ── Chain transition ──
        # Build the chain from current to target based on allowed transitions.
        chain = self._build_transition_chain(order.status, target_status)
        if not chain:
            logger.warning(
                "No transition path from %s to %s — skipping",
                order.status.value, target_status.value,
            )
            return order

        current = order
        for step in chain:
            if current.status == step:
                continue
            try:
                current = await self.order_manager.transition_to(current, step)
            except Exception as exc:
                logger.info(
                    "Chain transition %s→%s failed at step=%s: %s — stopping chain",
                    order.status.value, target_status.value, step.value, exc,
                )
                break
        return current

    @staticmethod
    def _build_transition_chain(
        current: OrderStatus,
        target: OrderStatus,
    ) -> list[OrderStatus]:
        """Build a chain of intermediate states from current to target.

        현재 구현은 잘 알려진 경로만 하드코딩한다:
        - SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED → FILLED
        - SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED

        향후 더 일반적인 chain builder로 확장 가능.
        """
        # Direct path
        if current == OrderStatus.SUBMITTED and target == OrderStatus.FILLED:
            return [
                OrderStatus.ACKNOWLEDGED,
                OrderStatus.PARTIALLY_FILLED,
                OrderStatus.FILLED,
            ]
        if current == OrderStatus.SUBMITTED and target == OrderStatus.PARTIALLY_FILLED:
            return [
                OrderStatus.ACKNOWLEDGED,
                OrderStatus.PARTIALLY_FILLED,
            ]
        if current == OrderStatus.SUBMITTED and target == OrderStatus.ACKNOWLEDGED:
            return [OrderStatus.ACKNOWLEDGED]
        if current == OrderStatus.ACKNOWLEDGED and target == OrderStatus.FILLED:
            return [
                OrderStatus.PARTIALLY_FILLED,
                OrderStatus.FILLED,
            ]
        # Default: target is directly reachable (known from _ALLOWED_TRANSITIONS)
        return [target]

    async def _sync_fills(
        self,
        broker_order: BrokerOrderEntity,
        broker: BrokerAdapter,
        account_ref: str,
        since: datetime | None,
    ) -> tuple[int, int]:
        """Fetch fill events from broker and persist new ones (dedup).

        Returns
        -------
        tuple[int, int]
            (fills_synced, fills_skipped)
        """
        try:
            fill_events: Sequence[FillEvent] = await broker.get_fills(
                account_ref,
                broker_order.broker_native_order_id,
                from_ts=since or broker_order.created_at,
            )
        except Exception as exc:
            logger.warning(
                "get_fills failed for broker_order=%s: %s",
                broker_order.broker_order_id, exc,
            )
            return 0, 0

        if not fill_events:
            return 0, 0

        # Load existing fills for dedup.
        existing = await self.repos.fill_events.list_by_broker_order(
            broker_order.broker_order_id,
        )

        # Dedup key: (fill_timestamp, fill_price, fill_quantity) since
        # FillEvent model does not carry a broker_fill_id.
        existing_keys: set[tuple[datetime, Decimal, Decimal]] = {
            (f.fill_timestamp, f.fill_price, f.fill_quantity)
            for f in existing
        }

        synced = 0
        skipped = 0
        for fill in fill_events:
            key = (fill.fill_timestamp, fill.fill_price, fill.fill_quantity)
            if key in existing_keys:
                skipped += 1
                continue

            entity = FillEventEntity(
                fill_event_id=uuid4(),
                broker_order_id=broker_order.broker_order_id,
                fill_timestamp=fill.fill_timestamp,
                fill_price=fill.fill_price,
                fill_quantity=fill.fill_quantity,
                source_channel="polling",
                broker_fill_id="",
                fill_fee=fill.fee,
                fill_tax=fill.tax,
            )
            await self.repos.fill_events.add(entity)
            existing_keys.add(key)
            synced += 1

        return synced, skipped

    async def _update_last_synced_at(
        self,
        broker_order_id: UUID,
        sync_time: datetime,
    ) -> None:
        """Update ``BrokerOrderEntity.last_synced_at``."""
        try:
            await self.repos.broker_orders.update(
                broker_order_id,
                last_synced_at=sync_time,
                updated_at=sync_time,
            )
        except Exception as exc:
            logger.warning(
                "Failed to update last_synced_at for broker_order=%s: %s",
                broker_order_id, exc,
            )
