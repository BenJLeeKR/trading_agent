from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import asyncpg

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import (
    BrokerOrderEntity,
    FillEventEntity,
    InstrumentEntity,
    OrderRequestEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus, OrderType
from agent_trading.domain.models import FillEvent, OrderStatusResult
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery
from agent_trading.services.order_manager import OrderManager

logger = logging.getLogger(__name__)

# ── Statuses that OrderSyncService will attempt to sync ──
_SYNCABLE_STATUSES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.SUBMITTED,
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.RECONCILE_REQUIRED,
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

# SELL 주문이 RECONCILE_REQUIRED 상태로 stuck된 채
# position decrease 감지가 불가능할 때 EXPIRED fallback을 적용하는 timeout (초)
# 2시간 = 7200초 (장중 2시간 이상 해소되지 않으면 EXPIRED)
_STUCK_EXPIRY_SECONDS: int = 7200

# EXPIRED → FILLED/PARTIALLY_FILLED 후행 복구 관련 상수
# 최근 N시간 이내에 EXPIRED된 주문만 broker truth 재조회 대상
_RECENT_EXPIRY_WINDOW_SECONDS: int = 86400  # 24시간
# 한 sync cycle당 최대 복구 처리 건수 (KIS API 비용 통제)
_MAX_EXPIRY_RECOVERY_PER_CYCLE: int = 10

# After-hours EXPIRED fallback 시 young order 보호 Grace Period (초).
# 장 종료 직전(15:20~15:30) 제출된 주문이 after-hours 첫 sync cycle(15:30~)에서
# 잘못 EXPIRED되는 것을 방지하기 위해, 생성 후 30분 미만이면 EXPIRED fallback을 금지한다.
_GRACE_PERIOD_AFTER_HOURS_EXPIRED_SECONDS: int = 1800  # 30분

# 시장가 + broker_native_order_id 존재 주문에 대한 after-hours Grace Period 연장 (초).
# Paper 환경에서 inquire-daily-ccld의 ODNO 미반환으로 인한 false EXPIRED를 방지하기 위해
# 30분 → 60분으로 연장한다. Live 환경에도 안전하게 적용 가능.
_GRACE_PERIOD_AFTER_HOURS_EXPIRED_MARKET_SECONDS: int = 3600  # 60분

# Stale PENDING_SUBMIT 주문 자동 REJECTED 기준 시간 (초).
# submit_order_to_broker() 호출 전에 실패하여 PENDING_SUBMIT에 stuck된
# orphan 주문을 정리하기 위한 timeout. broker_native_order_id가 없는
# PENDING_SUBMIT 주문이 이 시간 이상 경과하면 REJECTED로 전이한다.
_PENDING_SUBMIT_STALE_SECONDS: int = 1800  # 30분


@dataclass(slots=True, frozen=True)
class FillInferenceResult:
    """Result of a KIS truth fallback fill inference."""

    inferred_fill_qty: Decimal
    source: str


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

    Reconciliation 경로와 충돌하지 않도록 설계되며,
    ``SUBMITTED`` / ``ACKNOWLEDGED`` / ``PARTIALLY_FILLED`` /
    ``RECONCILE_REQUIRED`` 상태의 주문에 대해서 동작한다.

    ``RECONCILE_REQUIRED`` 주문은 broker truth 조회 후
    ``transition_to()``를 통해 정상 상태로 전이된다.
    broker truth 미확인 시 현재 상태를 유지한다 (자동 reject 금지).
    """

    repos: RepositoryContainer
    order_manager: OrderManager

    # ── KIS inquiry rate limit guard ──────────────────────────────────
    # 동일 account에 대한 inquire-balance 호출 간격 제한 (초)
    _INQUIRY_COOLDOWN_SECONDS: float = 30.0

    # 마지막 KIS inquiry 호출 시각 (account_id → datetime)
    _last_kis_inquiry_at: dict[UUID, datetime] = field(default_factory=dict)

    # 주문당 KIS inquiry 1회 제한 (order_request_id_str → True)
    _kis_inquiry_seen: dict[str, bool] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Backfill API (position-delta based EXPIRED SELL recovery)
    # ------------------------------------------------------------------

    async def recover_expired_sell_by_position(
        self,
        order: OrderRequestEntity,
        broker_order: BrokerOrderEntity,
        *,
        snapshot_refresh_cb: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> SyncOrderResult | None:
        """Backfill: position-delta 기반 EXPIRED SELL 시장가 주문 복구.

        이미 broker truth 조회 없이 EXPIRED된 SELL market 주문에 대해
        position snapshot delta를 증거로 FILLED/PARTIALLY_FILLED로 복구한다.

        ``sync_order_post_submit()``의 position-delta recovery 로직과
        동일한 ``_infer_sell_order_fill_via_position()``을 사용하지만,
        broker truth 재조회 단계를 거치지 않고 곧바로 position-delta를
        확인한다는 점이 다르다.

        Args:
            order: EXPIRED 상태의 SELL market 주문
            broker_order: 해당 order의 BrokerOrderEntity
            snapshot_refresh_cb: (선택) FILLED 복구 후 snapshot refresh 콜백

        Returns:
            SyncOrderResult (복구 성공 시) | None (추론 실패/조건 불만족)
        """
        # Step 1: SELL + expired + market 사전 조건 검증
        if order.side != OrderSide.SELL:
            logger.warning("[BACKFILL] not SELL, skip: order=%s", order.order_request_id)
            return None
        if order.status != OrderStatus.EXPIRED:
            logger.warning("[BACKFILL] not EXPIRED, skip: order=%s", order.order_request_id)
            return None
        if order.order_type != OrderType.MARKET:
            logger.warning("[BACKFILL] not MARKET, skip: order=%s type=%s", order.order_request_id, order.order_type)
            return None

        # Step 2: Broker order 상태 확인 (거절/취소된 주문은 복구 불가)
        if broker_order.broker_status in ('rejected', 'cancelled'):
            logger.warning(
                "[BACKFILL] broker_status=%s, skip: order=%s",
                broker_order.broker_status, order.order_request_id,
            )
            return None

        # Step 3: 안전 조건 검증 (_can_recover_expired)
        if not self._can_recover_expired(order, OrderStatus.FILLED):
            logger.warning(
                "[BACKFILL] _can_recover_expired=False, skip: order=%s age=%s",
                order.order_request_id,
                datetime.now(timezone.utc) - order.created_at,
            )
            return None

        # Step 4: Position-delta inference
        try:
            inferred: OrderStatus | None = await self._infer_sell_order_fill_via_position(
                order, broker_order, snapshot_refresh_cb=snapshot_refresh_cb,
            )
        except Exception:
            logger.exception(
                "[BACKFILL] _infer_sell_order_fill_via_position failed: order=%s",
                order.order_request_id,
            )
            return None

        if inferred not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            logger.info(
                "[BACKFILL] position-delta no inference, skip: order=%s inferred=%s",
                order.order_request_id, inferred,
            )
            return None

        previous_status = order.status
        now = datetime.now(timezone.utc)

        # Step 5: 상태 전이
        try:
            updated_order = await self._try_transition(order, inferred)
        except Exception:
            logger.exception(
                "[BACKFILL] _try_transition failed: order=%s status=%s",
                order.order_request_id, inferred,
            )
            return None

        status_changed = updated_order.status != previous_status

        # Step 6: broker_status 동기화
        await self.repos.broker_orders.update(
            broker_order.broker_order_id,
            broker_status=inferred.value,
            updated_at=now,
        )

        # Step 7: FILLED 도달 시 snapshot refresh (실패해도 복구는 성공)
        snapshot_triggered = False
        if inferred == OrderStatus.FILLED and snapshot_refresh_cb is not None:
            try:
                await snapshot_refresh_cb(order.account_id)
                snapshot_triggered = True
            except Exception:
                logger.exception(
                    "[BACKFILL] snapshot_refresh_cb failed (non-fatal): order=%s",
                    order.order_request_id,
                )

        logger.info(
            "[BACKFILL] recovered: order=%s %s→%s",
            order.order_request_id,
            OrderStatus.EXPIRED.value,
            inferred.value,
        )

        return SyncOrderResult(
            broker_order_id=broker_order.broker_order_id,
            previous_status=previous_status,
            current_status=updated_order.status,
            status_changed=status_changed,
            fills_synced=0,
            fills_skipped=0,
            terminal=updated_order.status in _TERMINAL_STATUSES,
            snapshot_triggered=snapshot_triggered,
            last_synced_at=now,
        )

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
            # EXPIRED 복구: 최근 N시간 이내 EXPIRED 주문에 한해 복구 시도
            if (
                order.status == OrderStatus.EXPIRED
                and order.updated_at is not None
                and (datetime.now(timezone.utc) - order.updated_at).total_seconds()
                    < _RECENT_EXPIRY_WINDOW_SECONDS
            ):
                recovered = False

                # 시도 1: broker truth 직접 확인 (기존 경로)
                try:
                    status_result = await broker.get_order_status(
                        account_ref,
                        client_order_id=order.client_order_id or "",
                        broker_order_id=broker_order.broker_native_order_id,
                    )
                    broker_recovered: OrderStatus = status_result.status
                    # 안전 조건 검증 후 복구
                    if (
                        broker_recovered in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
                        and self._can_recover_expired(order, broker_recovered)
                    ):
                        logger.info(
                            "EXPIRED 복구 시도 (broker truth): order_id=%s broker_reported=%s",
                            order.order_request_id, broker_recovered.value,
                        )
                        order = await self._try_transition(order, broker_recovered)
                        previous_status = order.status  # 갱신
                        recovered = True
                except Exception:
                    logger.debug(
                        "EXPIRED 복구 재조회 실패: broker_order=%s — 기존 terminal 유지",
                        broker_order_id, exc_info=True,
                    )

                # 시도 2: SELL position-delta 기반 후행 복구 (broker truth 실패 시)
                if not recovered and order.side == OrderSide.SELL:
                    try:
                        inferred: OrderStatus | None = (
                            await self._infer_sell_order_fill_via_position(
                                order=order,
                                broker_order=broker_order,
                                snapshot_refresh_cb=snapshot_refresh_cb,
                            )
                        )
                        if (
                            inferred is not None
                            and inferred in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
                            and self._can_recover_expired(order, inferred)
                        ):
                            logger.info(
                                "EXPIRED 복구 시도 (position-delta): order_id=%s inferred=%s",
                                order.order_request_id, inferred.value,
                            )
                            order = await self._try_transition(order, inferred)
                            # broker_status 동기화
                            await self.repos.broker_orders.update(
                                broker_order_id,
                                broker_status=inferred.value,
                                updated_at=datetime.now(timezone.utc),
                            )
                            previous_status = order.status  # 갱신
                            # FILLED 도달 시 snapshot refresh
                            if inferred == OrderStatus.FILLED and snapshot_refresh_cb is not None:
                                try:
                                    await snapshot_refresh_cb(order.account_id)
                                except Exception:
                                    logger.exception(
                                        "snapshot_refresh_cb failed after position-delta recovery "
                                        "for order_id=%s", order.order_request_id,
                                    )
                    except Exception:
                        logger.debug(
                            "EXPIRED position-delta 복구 실패: broker_order=%s — 기존 terminal 유지",
                            broker_order_id, exc_info=True,
                        )

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
        # Optimization: if order is terminal (FILLED/CANCELLED/REJECTED/EXPIRED),
        # get_order_status() already has all fill data from inquire-daily-ccld.
        # Skip separate get_fills() call to preserve inquiry budget.
        if broker_status in _TERMINAL_STATUSES:
            fills_synced = 0
            fills_skipped = 0
            logger.debug(
                "Skipping get_fills for terminal order broker_order=%s "
                "(status=%s) — data already captured by get_order_status()",
                broker_order_id, broker_status.value,
            )
        else:
            # Paper 1 RPS pacing: ensure at least 1s between consecutive KIS calls
            await asyncio.sleep(1.0)
            fills_synced, fills_skipped = await self._sync_fills(
                broker_order,
                broker,
                account_ref,
                since=broker_order.last_synced_at,
            )

        # ── 7. Update last_synced_at ──
        await self._update_last_synced_at(broker_order_id, now)

        # ── 8. Snapshot refresh if newly FILLED ──
        # Terminal 상태에서 get_fills()를 건너뛰더라도(fills_synced=0)
        # FILLED 상태 변경 시 snapshot은 트리거되어야 함.
        current_status = order.status
        terminal = current_status in _TERMINAL_STATUSES
        snapshot_triggered = False
        if (
            status_changed
            and current_status == OrderStatus.FILLED
            and (fills_synced > 0 or status_changed)
            and snapshot_refresh_cb is not None
        ):
            try:
                await snapshot_refresh_cb(order.account_id)
                snapshot_triggered = True
                logger.info(
                    "Snapshot refresh triggered for account=%s "
                    "broker_order=%s (status: %s→%s, fills_synced=%d)",
                    order.account_id, broker_order_id,
                    previous_status.value, current_status.value,
                    fills_synced,
                )
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
        """Attempt to order to target status.

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
        - RECONCILE_REQUIRED → ACKNOWLEDGED → PARTIALLY_FILLED → FILLED

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
        # RECONCILE_REQUIRED → FILLED: broker truth 확인 후 chain 전이
        if current == OrderStatus.RECONCILE_REQUIRED and target == OrderStatus.FILLED:
            return [
                OrderStatus.ACKNOWLEDGED,
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

        Dedup priority
        --------------
        1. broker_fill_id (when available) — authoritative broker-native fill
           identifier.  If the incoming ``FillEvent`` carries a non-empty
           ``broker_fill_id`` and that ID already exists in the repository
           under the same ``broker_order_id``, the fill is treated as a
           duplicate regardless of timestamp/price/quantity.
        2. Composite key ``(broker_order_id, fill_timestamp, fill_price,
           fill_quantity)`` — fallback for fills without a broker fill ID.

        Returns
        -------
        tuple[int, int]
            (fills_synced, fills_skipped)
        """
        try:
            from_ts: str | None = None
            if since is not None:
                from_ts = since.strftime("%Y%m%d")
            elif broker_order.created_at is not None:
                from_ts = broker_order.created_at.strftime("%Y%m%d")

            fill_events: Sequence[FillEvent] = await broker.get_fills(
                account_ref,
                broker_order.broker_native_order_id,
                from_ts=from_ts,
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

        # Split existing fills by broker_fill_id presence.
        # Fills with broker_fill_id use authoritative broker-native dedup.
        # Fills without broker_fill_id fall back to composite key dedup.
        existing_by_fill_id: dict[str, FillEventEntity] = {}
        existing_composite: set[tuple[UUID, datetime, Decimal, Decimal]] = set()
        for f in existing:
            if f.broker_fill_id:
                existing_by_fill_id[f.broker_fill_id] = f
            else:
                existing_composite.add(
                    (f.broker_order_id, f.fill_timestamp, f.fill_price, f.fill_quantity),
                )

        synced = 0
        skipped = 0
        for fill in fill_events:
            # Normalise broker_fill_id: empty string → None
            broker_fill_id: str | None = fill.broker_fill_id or None

            if broker_fill_id and broker_fill_id in existing_by_fill_id:
                # Authoritative dedup: same broker_fill_id → duplicate
                skipped += 1
                continue

            if not broker_fill_id:
                # Composite key fallback (broker_order_id included for safety).
                key = (
                    broker_order.broker_order_id,
                    fill.fill_timestamp,
                    fill.fill_price,
                    fill.fill_quantity,
                )
                if key in existing_composite:
                    skipped += 1
                    continue

            entity = FillEventEntity(
                fill_event_id=uuid4(),
                broker_order_id=broker_order.broker_order_id,
                fill_timestamp=fill.fill_timestamp,
                fill_price=fill.fill_price,
                fill_quantity=fill.fill_quantity,
                source_channel="rest_poll",
                broker_fill_id=broker_fill_id,
                fill_fee=fill.fee,
                fill_tax=fill.tax,
            )
            await self.repos.fill_events.add(entity)
            if broker_fill_id:
                existing_by_fill_id[broker_fill_id] = entity
            else:
                existing_composite.add(
                    (broker_order.broker_order_id, fill.fill_timestamp, fill.fill_price, fill.fill_quantity),
                )
            synced += 1

        return synced, skipped

    async def _update_last_synced_at(
        self,
        broker_order_id: UUID,
        sync_time: datetime,
    ) -> None:
        """Update ``BrokerOrderEntity.last_synced_at``.

        Raises
        ------
        asyncpg.PostgresError
            Re-raised so the caller (or savepoint boundary) can handle
            transaction-aborting DB errors rather than silently hiding them.
        """
        try:
            await self.repos.broker_orders.update(
                broker_order_id,
                last_synced_at=sync_time,
                updated_at=sync_time,
            )
        except asyncpg.PostgresError:
            logger.error(
                "DB write failed in _update_last_synced_at for "
                "broker_order=%s — transaction may be aborted",
                broker_order_id,
                exc_info=True,
            )
            raise
        except Exception:
            logger.error(
                "DB write failed in _update_last_synced_at for "
                "broker_order=%s — re-raising to trigger savepoint rollback",
                broker_order_id,
                exc_info=True,
            )
            raise

    # ------------------------------------------------------------------
    # RECONCILE_REQUIRED 해소
    # ------------------------------------------------------------------

    async def _sync_reconcile_required_orders(
        self,
        account_ref: str,
        broker: BrokerAdapter,
        *,
        limit: int = 5,
        is_after_hours: bool = False,
        snapshot_refresh_cb: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> int:
        """Discover and resolve RECONCILE_REQUIRED orders via broker truth.

        Sync cycle 내에서 ``RECONCILE_REQUIRED`` 상태 주문을 발견하면
        broker truth 조회를 통해 정상 상태로 전이시킨다.

        Parameters
        ----------
        account_ref:
            Broker account reference.
        broker:
            Broker adapter for truth inquiry.
        limit:
            Maximum number of reconcile-required orders to process.

        Returns
        -------
        int
            Number of orders successfully resolved.
        """
        reconcile_orders = await self.repos.orders.list(
            OrderQuery(
                statuses=[OrderStatus.RECONCILE_REQUIRED],
                limit=limit,
            )
        )

        if not reconcile_orders:
            logger.debug("_sync_reconcile_required_orders: no RECONCILE_REQUIRED orders found")
            return 0

        logger.info(
            "_sync_reconcile_required_orders: found %d RECONCILE_REQUIRED orders (limit=%d)",
            len(reconcile_orders), limit,
        )

        resolved = 0
        for order in reconcile_orders:
            broker_orders = await self.repos.broker_orders.list_by_order_request(
                order.order_request_id,
            )
            if not broker_orders:
                logger.debug(
                    "_sync_reconcile_required_orders: no broker_orders for order_id=%s",
                    order.order_request_id,
                )
                continue

            for bo in broker_orders:
                try:
                    result = await self.transition_to_authoritative(
                        account_ref=account_ref,
                        broker=broker,
                        order=order,
                        broker_order=bo,
                        is_after_hours=is_after_hours,
                        snapshot_refresh_cb=snapshot_refresh_cb,
                    )
                    if result is not None:
                        resolved += 1
                        logger.info(
                            "RECONCILE_REQUIRED resolved: order_id=%s "
                            "broker_order_id=%s new_status=%s",
                            order.order_request_id,
                            bo.broker_order_id,
                            result.status.value,
                        )
                except Exception as exc:
                    logger.warning(
                        "RECONCILE_REQUIRED resolution failed for "
                        "order_id=%s broker_order_id=%s: %s",
                        order.order_request_id,
                        bo.broker_order_id,
                        exc,
                    )

        logger.info(
            "_sync_reconcile_required_orders: resolved %d/%d orders",
            resolved, len(reconcile_orders),
        )
        return resolved

    async def transition_to_authoritative(
        self,
        account_ref: str,
        broker: BrokerAdapter,
        order: OrderRequestEntity,
        broker_order: BrokerOrderEntity,
        *,
        is_after_hours: bool = False,
        snapshot_refresh_cb: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> OrderStatusResult | None:
        """Resolve a RECONCILE_REQUIRED order via authoritative broker truth.

        Flow
        ----
        1. ``broker.resolve_unknown_state()`` 호출 (reconciliation reserve 사용)
        2. 결과가 ``RECONCILE_REQUIRED``가 아니면 ``_try_transition()``으로 전이
        3. ``RECONCILE_REQUIRED`` 유지면 ``_is_genuine_manual_reconciliation()`` 판단
        4. 진짜 manual 대상이면 skip, 아니면 현재 상태 유지

        Parameters
        ----------
        account_ref:
            Broker account reference.
        broker:
            Broker adapter for truth inquiry.
        order:
            The order request entity in RECONCILE_REQUIRED status.
        broker_order:
            The associated broker order entity.

        Returns
        -------
        OrderStatusResult | None
            The resolved status result, or ``None`` if still unresolved.
        """
        if order.status != OrderStatus.RECONCILE_REQUIRED:
            return None

        # 1. Resolve symbol from instrument_id (OrderRequestEntity has no 'symbol' field)
        symbol: str | None = None
        if order.instrument_id is not None:
            instrument = await self.repos.instruments.get(order.instrument_id)
            if instrument is not None:
                symbol = instrument.symbol

        # 2. Broker truth inquiry via resolve_unknown_state
        #    RECONCILIATION bucket을 사용하므로 일반 INQUIRY budget과 독립적.
        #    BudgetExhaustedError 발생 시에도 로깅하여 budget 상태 추적.
        try:
            status_result = await broker.resolve_unknown_state(
                account_ref,
                broker_order_id=broker_order.broker_native_order_id,
                symbol=symbol,
            )
        except Exception as exc:
            logger.warning(
                "resolve_unknown_state failed for broker_order=%s: %s "
                "[trying position-based inference for sell orders]",
                broker_order.broker_order_id, exc,
            )
            # Before falling back to EXPIRED, try position-based inference
            # for sell orders (false positive correction).
            if order.side == OrderSide.SELL:
                inferred_status = await self._infer_sell_order_fill_via_position(
                    order, broker_order,
                    snapshot_refresh_cb=snapshot_refresh_cb,
                )
                if inferred_status is not None:
                    try:
                        updated_order = await self._try_transition(
                            order, inferred_status,
                        )
                        if updated_order.status != order.status:
                            # ── broker_status 동기화: position-derived fill 추론 성공 시 ──
                            if inferred_status == OrderStatus.FILLED:
                                now_broker = datetime.now(timezone.utc)
                                await self.repos.broker_orders.update(
                                    broker_order.broker_order_id,
                                    broker_status="filled",
                                    updated_at=now_broker,
                                )
                                logger.info(
                                    "[BROKER_STATUS_SYNC] order_request_id=%s "
                                    "broker_status set to filled (position-derived) "
                                    "[exception handler path]",
                                    order.order_request_id,
                                )
                                # ── snapshot_refresh_cb 호출 ──
                                if snapshot_refresh_cb is not None:
                                    try:
                                        await snapshot_refresh_cb(order.account_id)
                                    except Exception:
                                        logger.exception(
                                            "snapshot_refresh_cb failed after fill inference "
                                            "for order_id=%s",
                                            order.order_request_id,
                                        )

                            logger.info(
                                "transition_to_authoritative: %s → %s (order_id=%s) "
                                "[position_delta_inferred_fill]",
                                order.status.value,
                                updated_order.status.value,
                                order.order_request_id,
                            )
                            return OrderStatusResult(
                                broker_name=broker_order.broker_name,
                                client_order_id=None,
                                broker_order_id=broker_order.broker_native_order_id,
                                status=inferred_status,
                                filled_quantity=order.requested_quantity
                                if inferred_status == OrderStatus.FILLED
                                else Decimal("0"),
                                remaining_quantity=Decimal("0")
                                if inferred_status == OrderStatus.FILLED
                                else order.requested_quantity,
                                raw_code="",
                                raw_message=(
                                    f"Position-delta inferred {inferred_status.value}: "
                                    f"resolve_unknown_state failed: {exc}"
                                ),
                            )
                    except Exception as transition_exc:
                        logger.error(
                            "Position-inferred transition to %s failed for "
                            "order_id=%s broker_order_id=%s: %s",
                            inferred_status.value,
                            order.order_request_id,
                            broker_order.broker_order_id,
                            transition_exc,
                            exc_info=True,
                        )
                        return None

            # Broker truth 조회 실패 시 EXPIRED로 fallback 전이.
            # (Phase 4 fix: budget exhaustion/rate limit 등으로 broker 조회가
            #  불가능한 경우에도 RECONCILE_REQUIRED 상태를 해소)
            # Intraday (08:50~15:30 KST) 중에는 EXPIRED fallback 금지.
            # 장마감 후 after-hours(15:30~)에만 허용.
            if not is_after_hours:
                logger.warning(
                    "Intraday: EXPIRED fallback suppressed for order %s "
                    "[resolve_unknown_state failed: %s] — keeping RECONCILE_REQUIRED",
                    broker_order.broker_order_id, exc,
                )
                return None  # RECONCILE_REQUIRED 유지, 다음 sync cycle에 재시도

            # After-hours: young order 보호 — 생성 후 grace period 미만이면 EXPIRED 금지
            # 장 종료 직전(15:20~15:30) 제출된 주문이 after-hours 첫 sync cycle에서
            # 잘못 EXPIRED되는 것을 방지한다.
            # 시장가 + broker_native_order_id 존재 주문은 grace period 60분 적용.
            if order.created_at is not None:
                # ── MARKET_PROTECT: broker_native_order_id + 시장가 → grace period 60분 ──
                grace_period = _GRACE_PERIOD_AFTER_HOURS_EXPIRED_SECONDS
                if (broker_order.broker_native_order_id
                    and order.order_type == OrderType.MARKET):
                    grace_period = _GRACE_PERIOD_AFTER_HOURS_EXPIRED_MARKET_SECONDS

                age_seconds = (datetime.now(timezone.utc) - order.created_at).total_seconds()
                if age_seconds < grace_period:
                    logger.warning(
                        "After-hours: EXPIRED fallback suppressed for recent order %s "
                        "[age=%.0fs < %ds, resolve_unknown_state failed: %s, "
                        "broker_native_order_id=%s, order_type=%s] — "
                        "keeping RECONCILE_REQUIRED",
                        broker_order.broker_order_id,
                        age_seconds,
                        grace_period,
                        exc,
                        broker_order.broker_native_order_id or "none",
                        order.order_type.value,
                    )
                    return None  # 다음 sync cycle에 재시도

            logger.warning(
                "Falling back to EXPIRED for order %s (broker=%s) "
                "[resolve_unknown_state failed: %s]",
                broker_order.broker_order_id,
                broker_order.broker_name,
                exc,
            )
            try:
                updated_order = await self._try_transition(
                    order, OrderStatus.EXPIRED,
                )
                if updated_order.status != order.status:
                    logger.info(
                        "transition_to_authoritative: %s → %s (order_id=%s) "
                        "[fallback: resolve_unknown_state failed: %s]",
                        order.status.value,
                        updated_order.status.value,
                        order.order_request_id,
                        exc,
                    )
                    return OrderStatusResult(
                        broker_name=broker_order.broker_name,
                        client_order_id=None,
                        broker_order_id=broker_order.broker_native_order_id,
                        status=OrderStatus.EXPIRED,
                        filled_quantity=Decimal("0"),
                        remaining_quantity=Decimal("0"),
                        raw_code="",
                        raw_message=f"Fallback EXPIRED: resolve_unknown_state failed: {exc}",
                    )
            except Exception as fallback_exc:
                logger.error(
                    "Fallback transition to EXPIRED failed for "
                    "order_id=%s broker_order_id=%s: %s",
                    order.order_request_id,
                    broker_order.broker_order_id,
                    fallback_exc,
                    exc_info=True,
                )
            return None

        # 2. Update broker-side status on BrokerOrderEntity
        now = datetime.now(timezone.utc)
        if broker_order.broker_status != status_result.status.value:
            await self.repos.broker_orders.update(
                broker_order.broker_order_id,
                broker_status=status_result.status.value,
                updated_at=now,
            )

        # 3. If broker returned a definitive status, transition
        if status_result.status != OrderStatus.RECONCILE_REQUIRED:
            updated_order = await self._try_transition(order, status_result.status)
            if updated_order.status != order.status:
                logger.info(
                    "transition_to_authoritative: %s → %s (order_id=%s)",
                    order.status.value,
                    updated_order.status.value,
                    order.order_request_id,
                )
            return status_result

        # 4. Still RECONCILE_REQUIRED — check if genuine manual reconciliation
        if self._is_genuine_manual_reconciliation(order, broker_order, status_result):
            logger.info(
                "Genuine manual reconciliation detected for order_id=%s "
                "broker_order_id=%s — leaving as RECONCILE_REQUIRED",
                order.order_request_id,
                broker_order.broker_order_id,
            )
            return None

        # 4.5 KIS truth fallback: inquire-daily-ccld matching failed,
        #     try position-based inference via local snapshots as fallback.
        #     This catches cases where the broker has no record in daily-ccld
        #     but the position has actually decreased (paper API limitation).
        if order.side == OrderSide.SELL:
            # Try KIS truth fallback before position inference
            kis_fill_result = await self._try_kis_truth_fallback(
                order=order,
                broker_order=broker_order,
                account_id=order.account_id,
                pre_qty=None,  # Will be computed inside
                broker=broker,
            )
            if kis_fill_result is not None and kis_fill_result.inferred_fill_qty > Decimal("0"):
                inferred_status = (
                    OrderStatus.FILLED
                    if kis_fill_result.inferred_fill_qty >= order.requested_quantity
                    else OrderStatus.PARTIALLY_FILLED
                )
                try:
                    updated_order = await self._try_transition(
                        order, inferred_status,
                    )
                    if updated_order.status != order.status:
                        if inferred_status == OrderStatus.FILLED:
                            now_broker = datetime.now(timezone.utc)
                            await self.repos.broker_orders.update(
                                broker_order.broker_order_id,
                                broker_status="filled",
                                updated_at=now_broker,
                            )
                            logger.info(
                                "[BROKER_STATUS_SYNC] order_request_id=%s "
                                "broker_status set to filled (KIS truth fallback) "
                                "[reconcile_required path]",
                                order.order_request_id,
                            )
                            if snapshot_refresh_cb is not None:
                                try:
                                    await snapshot_refresh_cb(order.account_id)
                                except Exception:
                                    logger.exception(
                                        "snapshot_refresh_cb failed after KIS truth fallback "
                                        "for order_id=%s",
                                        order.order_request_id,
                                    )

                        logger.info(
                            "transition_to_authoritative: %s → %s (order_id=%s) "
                            "[kis_truth_fallback]",
                            order.status.value,
                            updated_order.status.value,
                            order.order_request_id,
                        )
                        return OrderStatusResult(
                            broker_name=broker_order.broker_name,
                            client_order_id=None,
                            broker_order_id=broker_order.broker_native_order_id,
                            status=inferred_status,
                            filled_quantity=order.requested_quantity
                            if inferred_status == OrderStatus.FILLED
                            else Decimal("0"),
                            remaining_quantity=Decimal("0")
                            if inferred_status == OrderStatus.FILLED
                            else order.requested_quantity,
                            raw_code="",
                            raw_message=(
                                f"KIS truth fallback {inferred_status.value}: "
                                f"position decrease detected"
                            ),
                        )
                except Exception as transition_exc:
                    logger.error(
                        "KIS truth fallback transition to %s failed for "
                        "order_id=%s broker_order_id=%s: %s",
                        inferred_status.value,
                        order.order_request_id,
                        broker_order.broker_order_id,
                        transition_exc,
                        exc_info=True,
                    )
                    return None

        # 5. Not genuine — broker has no record of this order.
        #    resolve_unknown_state()가 RECONCILE_REQUIRED를 반환했다는 것은
        #    broker가 일일 결제 내역과 포지션에서 이 주문을 찾지 못했다는 의미.
        #    Before falling back to EXPIRED, try position-based inference
        #    for sell orders (false positive correction).
        if order.side == OrderSide.SELL:
            inferred_status = await self._infer_sell_order_fill_via_position(
                order, broker_order,
                snapshot_refresh_cb=snapshot_refresh_cb,
            )
            if inferred_status is not None:
                try:
                    updated_order = await self._try_transition(
                        order, inferred_status,
                    )
                    if updated_order.status != order.status:
                        # ── broker_status 동기화: position-derived fill 추론 성공 시 ──
                        if inferred_status == OrderStatus.FILLED:
                            now_broker = datetime.now(timezone.utc)
                            await self.repos.broker_orders.update(
                                broker_order.broker_order_id,
                                broker_status="filled",
                                updated_at=now_broker,
                            )
                            logger.info(
                                "[BROKER_STATUS_SYNC] order_request_id=%s "
                                "broker_status set to filled (position-derived) "
                                "[reconcile_required path]",
                                order.order_request_id,
                            )
                            # ── snapshot_refresh_cb 호출 ──
                            if snapshot_refresh_cb is not None:
                                try:
                                    await snapshot_refresh_cb(order.account_id)
                                except Exception:
                                    logger.exception(
                                        "snapshot_refresh_cb failed after fill inference "
                                        "for order_id=%s",
                                        order.order_request_id,
                                    )

                        logger.info(
                            "transition_to_authoritative: %s → %s (order_id=%s) "
                            "[position_delta_inferred_fill]",
                            order.status.value,
                            updated_order.status.value,
                            order.order_request_id,
                        )
                        return OrderStatusResult(
                            broker_name=broker_order.broker_name,
                            client_order_id=None,
                            broker_order_id=broker_order.broker_native_order_id,
                            status=inferred_status,
                            filled_quantity=order.requested_quantity
                            if inferred_status == OrderStatus.FILLED
                            else Decimal("0"),
                            remaining_quantity=Decimal("0")
                            if inferred_status == OrderStatus.FILLED
                            else order.requested_quantity,
                            raw_code="",
                            raw_message=(
                                f"Position-delta inferred {inferred_status.value}: "
                                f"broker has no record of order"
                            ),
                        )
                except Exception as transition_exc:
                    logger.error(
                        "Position-inferred transition to %s failed for "
                        "order_id=%s broker_order_id=%s: %s",
                        inferred_status.value,
                        order.order_request_id,
                        broker_order.broker_order_id,
                        transition_exc,
                        exc_info=True,
                    )
                    return None

        # Stage 2.5: Stuck timeout → EXPIRED fallback (intraday suppression + BUY/SELL)
        # Paper broker에서 position decrease가 감지되지 않아 RECONCILE_REQUIRED가
        # 장시간 해소되지 않는 경우, stuck timeout 기준으로 EXPIRED 처리한다.
        #
        # 장중 intraday(08:50~15:30 KST)에는 EXPIRED fallback을 금지하고
        # after-hours(15:30~)에만 허용한다.
        # BUY/SELL 모두 적용하되, 근거 우선순위가 다르다:
        #   SELL: KIS truth fallback (position-delta) → EXPIRED
        #   BUY:  broker truth 직접 조회 → 체결 이벤트 확인 → stuck duration → EXPIRED
        if order.created_at is not None:
            stuck_duration = (datetime.now(timezone.utc) - order.created_at).total_seconds()
            if stuck_duration > _STUCK_EXPIRY_SECONDS:
                # Intraday: EXPIRED fallback 금지
                if not is_after_hours:
                    logger.warning(
                        "Intraday: STUCK_EXPIRY suppressed for order %s side=%s "
                        "[stuck=%.0fs] — keeping RECONCILE_REQUIRED",
                        broker_order.broker_order_id, order.side.value, stuck_duration,
                    )
                    # ── MARKET_PROTECT: broker_native_order_id + 시장가 주문 보호 ──
                    if (broker_order.broker_native_order_id
                        and order.order_type == OrderType.MARKET):
                        logger.info(
                            "[MARKET_PROTECT] Intraday STUCK_EXPIRY: "
                            "broker_native_order_id=%s + 시장가 → EXPIRED 차단, "
                            "RECONCILE_REQUIRED 유지 [recovery batch에서 복구 시도]",
                            broker_order.broker_native_order_id,
                        )
                        return None  # RECONCILE_REQUIRED 유지
                    # RECONCILE_REQUIRED 유지, 다음 sync cycle에 재시도
                    # stage 2.5를 빠져나가면 경로 D(broker has no record)로 이어짐

                # After-hours: BUY/SELL 각각 근거 우선순위 적용
                else:
                    # SELL: KIS truth fallback 시도 (position-delta 기반)
                    if order.side == OrderSide.SELL:
                        kis_fill = await self._try_kis_truth_fallback(
                            order=order,
                            broker_order=broker_order,
                            account_id=order.account_id,
                            broker=broker,
                        )
                        if kis_fill is not None and kis_fill.inferred_fill_qty > Decimal("0"):
                            # KIS truth confirms fill — update to filled, not expired
                            inferred_status = (
                                OrderStatus.FILLED
                                if kis_fill.inferred_fill_qty >= order.requested_quantity
                                else OrderStatus.PARTIALLY_FILLED
                            )
                            logger.info(
                                "[STUCK_EXPIRY_KIS_TRUTH] order %s: KIS truth confirms fill=%s, "
                                "updating to %s instead of expired",
                                order.order_request_id, kis_fill.inferred_fill_qty,
                                inferred_status.value,
                            )
                            try:
                                updated_order = await self._try_transition(
                                    order, inferred_status,
                                )
                                if updated_order.status != order.status:
                                    if inferred_status == OrderStatus.FILLED:
                                        await self.repos.broker_orders.update(
                                            broker_order.broker_order_id,
                                            broker_status="filled",
                                            updated_at=datetime.now(timezone.utc),
                                        )
                                        if snapshot_refresh_cb is not None:
                                            try:
                                                await snapshot_refresh_cb(order.account_id)
                                            except Exception:
                                                logger.exception(
                                                    "snapshot_refresh_cb failed after KIS truth "
                                                    "fallback for order_id=%s",
                                                    order.order_request_id,
                                                )

                                    logger.info(
                                        "transition_to_authoritative: %s → %s (order_id=%s) "
                                        "[stuck_expiry_kis_truth]",
                                        order.status.value,
                                        updated_order.status.value,
                                        order.order_request_id,
                                    )
                                    return OrderStatusResult(
                                        broker_name=broker_order.broker_name,
                                        client_order_id=None,
                                        broker_order_id=broker_order.broker_native_order_id,
                                        status=inferred_status,
                                        filled_quantity=order.requested_quantity
                                        if inferred_status == OrderStatus.FILLED
                                        else Decimal("0"),
                                        remaining_quantity=Decimal("0")
                                        if inferred_status == OrderStatus.FILLED
                                        else order.requested_quantity,
                                        raw_code="",
                                        raw_message=(
                                            f"Stuck expiry KIS truth {inferred_status.value}: "
                                            f"fill={kis_fill.inferred_fill_qty}"
                                        ),
                                    )
                            except Exception as exc:
                                logger.error(
                                    "Stuck expiry KIS truth transition to %s failed for "
                                    "order_id=%s broker_order_id=%s: %s",
                                    inferred_status.value,
                                    order.order_request_id,
                                    broker_order.broker_order_id,
                                    exc,
                                    exc_info=True,
                                )
                                return None

                    # BUY: KIS truth fallback 불가 (SELL 전용) → 체결 이벤트 확인
                    elif order.side == OrderSide.BUY:
                        # 체결 이벤트 확인 (FillEventEntity 조회)
                        fill_events = await self.repos.fill_events.list_by_broker_order(
                            broker_order.broker_order_id,
                        )
                        if fill_events:
                            total_filled = sum(f.fill_quantity for f in fill_events)
                            inferred_status = (
                                OrderStatus.FILLED
                                if total_filled >= order.requested_quantity
                                else OrderStatus.PARTIALLY_FILLED
                            )
                            logger.info(
                                "[STUCK_EXPIRY_BUY_FILL] order %s: found %d fill events "
                                "(total=%s) → updating to %s instead of expired",
                                order.order_request_id, len(fill_events), total_filled,
                                inferred_status.value,
                            )
                            try:
                                updated_order = await self._try_transition(
                                    order, inferred_status,
                                )
                                if updated_order.status != order.status:
                                    if inferred_status == OrderStatus.FILLED:
                                        await self.repos.broker_orders.update(
                                            broker_order.broker_order_id,
                                            broker_status="filled",
                                            updated_at=datetime.now(timezone.utc),
                                        )
                                        if snapshot_refresh_cb is not None:
                                            try:
                                                await snapshot_refresh_cb(order.account_id)
                                            except Exception:
                                                logger.exception(
                                                    "snapshot_refresh_cb failed after fill "
                                                    "inference for order_id=%s",
                                                    order.order_request_id,
                                                )
                                    logger.info(
                                        "transition_to_authoritative: %s → %s (order_id=%s) "
                                        "[stuck_expiry_buy_fill]",
                                        order.status.value,
                                        updated_order.status.value,
                                        order.order_request_id,
                                    )
                                    return OrderStatusResult(
                                        broker_name=broker_order.broker_name,
                                        client_order_id=None,
                                        broker_order_id=broker_order.broker_native_order_id,
                                        status=inferred_status,
                                        filled_quantity=total_filled,
                                        remaining_quantity=order.requested_quantity - total_filled,
                                        raw_code="",
                                        raw_message=(
                                            f"BUY fill recovery: {len(fill_events)} fill events "
                                            f"(total={total_filled})"
                                        ),
                                    )
                            except Exception as exc:
                                logger.error(
                                    "BUY fill recovery transition to %s failed for "
                                    "order_id=%s broker_order_id=%s: %s",
                                    inferred_status.value,
                                    order.order_request_id,
                                    broker_order.broker_order_id,
                                    exc,
                                    exc_info=True,
                                )
                                return None

                    # After-hours: KIS truth/fill 미확인 → EXPIRED fallback (BUY/SELL 공통)
                    logger.warning(
                        "[STUCK_EXPIRY] order_request_id=%s symbol=%s side=%s "
                        "stuck_duration=%.0fs > threshold=%ds → EXPIRED fallback "
                        "(after-hours, no fill evidence)",
                        order.order_request_id, symbol, order.side,
                        stuck_duration, _STUCK_EXPIRY_SECONDS,
                    )
                    try:
                        updated_order = await self._try_transition(
                            order, OrderStatus.EXPIRED,
                        )
                        if updated_order.status != order.status:
                            await self.repos.broker_orders.update(
                                broker_order.broker_order_id,
                                broker_status="expired",
                                updated_at=datetime.now(timezone.utc),
                            )
                            logger.info(
                                "transition_to_authoritative: %s → %s (order_id=%s) "
                                "[stuck_timeout_expired]",
                                order.status.value,
                                updated_order.status.value,
                                order.order_request_id,
                            )
                            return OrderStatusResult(
                                broker_name=broker_order.broker_name,
                                client_order_id=None,
                                broker_order_id=broker_order.broker_native_order_id,
                                status=OrderStatus.EXPIRED,
                                filled_quantity=Decimal("0"),
                                remaining_quantity=Decimal("0"),
                                raw_code="",
                                raw_message=(
                                    f"Stuck timeout EXPIRED: "
                                    f"RECONCILE_REQUIRED for {stuck_duration:.0f}s "
                                    f"(threshold={_STUCK_EXPIRY_SECONDS}s)"
                                ),
                            )
                    except Exception as exc:
                        logger.error(
                            "Stuck timeout transition to EXPIRED failed for "
                            "order_id=%s broker_order_id=%s: %s",
                            order.order_request_id,
                            broker_order.broker_order_id,
                            exc,
                            exc_info=True,
                        )
                        return None

        #    이런 경우 EXPIRED로 fallback 전이하여 RECONCILE_REQUIRED 상태를 해소한다.
        #    (Phase 4 fix: broker truth 부재 시 자동 해소)
        # Intraday (08:50~15:30 KST) 중에는 EXPIRED fallback 금지.
        # 장마감 후 after-hours(15:30~)에만 허용.
        if not is_after_hours:
            logger.warning(
                "Intraday: EXPIRED fallback suppressed for order %s "
                "[broker has no record] — keeping RECONCILE_REQUIRED",
                broker_order.broker_order_id,
            )
            return None  # RECONCILE_REQUIRED 유지

        # After-hours: young order 보호 — 생성 후 grace period 미만이면 EXPIRED 금지
        # 장 종료 직전(15:20~15:30) 제출된 주문이 after-hours 첫 sync cycle에서
        # 잘못 EXPIRED되는 것을 방지한다.
        # 시장가 + broker_native_order_id 존재 주문은 grace period 60분 적용.
        if order.created_at is not None:
            # ── MARKET_PROTECT: broker_native_order_id + 시장가 → grace period 60분 ──
            grace_period = _GRACE_PERIOD_AFTER_HOURS_EXPIRED_SECONDS
            if (broker_order.broker_native_order_id
                and order.order_type == OrderType.MARKET):
                grace_period = _GRACE_PERIOD_AFTER_HOURS_EXPIRED_MARKET_SECONDS

            age_seconds = (datetime.now(timezone.utc) - order.created_at).total_seconds()
            if age_seconds < grace_period:
                logger.warning(
                    "After-hours: EXPIRED fallback suppressed for recent order %s "
                    "[age=%.0fs < %ds, broker has no record, "
                    "broker_native_order_id=%s, order_type=%s] — "
                    "keeping RECONCILE_REQUIRED",
                    broker_order.broker_order_id,
                    age_seconds,
                    grace_period,
                    broker_order.broker_native_order_id or "none",
                    order.order_type.value,
                )
                return None  # 다음 sync cycle에 재시도

        logger.warning(
            "RECONCILE_REQUIRED persists after broker truth inquiry "
            "for order_id=%s broker_order_id=%s — broker has no record, "
            "falling back to EXPIRED",
            order.order_request_id,
            broker_order.broker_order_id,
        )
        try:
            updated_order = await self._try_transition(
                order, OrderStatus.EXPIRED,
            )
            if updated_order.status != order.status:
                logger.info(
                    "transition_to_authoritative: %s → %s (order_id=%s) "
                    "[fallback: broker no record]",
                    order.status.value,
                    updated_order.status.value,
                    order.order_request_id,
                )
                # Return a result indicating EXPIRED so the caller
                # counts this as resolved.
                return OrderStatusResult(
                    broker_name=broker_order.broker_name,
                    client_order_id=None,
                    broker_order_id=broker_order.broker_native_order_id,
                    status=OrderStatus.EXPIRED,
                    filled_quantity=Decimal("0"),
                    remaining_quantity=Decimal("0"),
                    raw_code="",
                    raw_message="Fallback EXPIRED: broker has no record of order",
                )
        except Exception as exc:
            logger.error(
                "Fallback transition to EXPIRED failed for "
                "order_id=%s broker_order_id=%s: %s",
                order.order_request_id,
                broker_order.broker_order_id,
                exc,
                exc_info=True,
            )
        return None

    async def _infer_sell_order_fill_via_position(
        self,
        order: OrderRequestEntity,
        broker_order: BrokerOrderEntity,
        *,
        snapshot_refresh_cb: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> OrderStatus | None:
        """Position-delta based sell fill inference with retry.

        When KIS ``inquire-daily-ccld`` returns 0 records (paper API limitation)
        or ``resolve_unknown_state()`` raises an exception, this method attempts
        to infer whether a SELL order was actually filled by comparing position
        snapshots before and after the order.

        Retry logic: if delta=0 on first attempt, force snapshot refresh
        via ``snapshot_refresh_cb`` (if provided) and retry up to 2 more times
        with backoff.

        Parameters
        ----------
        snapshot_refresh_cb:
            Optional callback to trigger a snapshot sync for the account.
            When provided, called before each retry attempt to ensure the
            latest position data is available from the broker.

        Returns
        -------
        OrderStatus | None
            ``FILLED``, ``PARTIALLY_FILLED``, or ``None`` if cannot infer.
        """
        # 1. Sell-only policy
        if order.side != OrderSide.SELL:
            return None

        # 2. Resolve account_id from order
        account_id = order.account_id

        # 3. Resolve instrument_id (already on OrderRequestEntity)
        instrument_id = order.instrument_id

        # 4. Query pre-order position snapshot (latest before broker_order.created_at)
        try:
            pre_order_snapshot = await self.repos.position_snapshots.get_latest_by_account_and_instrument_before(
                account_id=account_id,
                instrument_id=instrument_id,
                before=broker_order.created_at,
            )
        except Exception:
            logger.exception(
                "Failed to query pre-order position snapshot for "
                "order_id=%s broker_order_id=%s",
                order.order_request_id,
                broker_order.broker_order_id,
            )
            return None

        if pre_order_snapshot is None:
            logger.info(
                "No pre-order position snapshot found for order_id=%s "
                "(account=%s, instrument=%s) — cannot infer",
                order.order_request_id, account_id, instrument_id,
            )
            return None

        pre_order_qty = pre_order_snapshot.quantity

        # 5. Query current (latest overall) position snapshot
        current_qty = await self._get_latest_position_qty(
            account_id=account_id,
            instrument_id=instrument_id,
        )

        # 6. If pre_order_qty is None → cannot compare
        if pre_order_qty is None:
            return None

        # 7. If current_qty is None → treat as 0
        if current_qty is None:
            current_qty = Decimal("0")

        # 8. Calculate position delta
        position_delta = pre_order_qty - current_qty

        # 9. If delta > 0 on first attempt, return immediately
        if position_delta > Decimal("0"):
            return self._infer_status_from_delta(
                order=order,
                broker_order=broker_order,
                pre_order_qty=pre_order_qty,
                current_qty=current_qty,
                position_delta=position_delta,
            )

        # 10. delta=0: force snapshot refresh and retry up to 2 times
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            logger.info(
                "[SELL_FILL_RETRY] delta=0 for order %s (pre_qty=%s, current_qty=%s), "
                "forcing snapshot refresh (attempt %d/%d)",
                order.order_request_id, pre_order_qty, current_qty, attempt, max_retries,
            )
            # Force snapshot refresh via callback (if provided) before re-reading.
            # This ensures the latest position data is fetched from the broker
            # rather than relying on stale cached snapshots.
            if snapshot_refresh_cb is not None:
                try:
                    await snapshot_refresh_cb(account_id)
                except Exception:
                    logger.exception(
                        "snapshot_refresh_cb failed during SELL_FILL_RETRY "
                        "for order_id=%s (attempt %d/%d)",
                        order.order_request_id, attempt, max_retries,
                    )
            current_qty = await self._get_latest_position_qty(
                account_id=account_id,
                instrument_id=instrument_id,
            )
            if current_qty is None:
                current_qty = Decimal("0")

            position_delta = pre_order_qty - current_qty
            if position_delta > Decimal("0"):
                logger.info(
                    "[SELL_FILL_RETRY] delta=%s detected after refresh attempt %d for order %s",
                    position_delta, attempt, order.order_request_id,
                )
                return self._infer_status_from_delta(
                    order=order,
                    broker_order=broker_order,
                    pre_order_qty=pre_order_qty,
                    current_qty=current_qty,
                    position_delta=position_delta,
                )

            # Small backoff before next retry
            if attempt < max_retries:
                await asyncio.sleep(1.0 * attempt)

        logger.warning(
            "[SELL_FILL_RETRY] all %d retries exhausted for order %s, delta=0",
            max_retries, order.order_request_id,
        )
        return None

    async def _get_latest_position_qty(
        self,
        account_id: UUID,
        instrument_id: UUID,
    ) -> Decimal | None:
        """Query the latest position quantity for a given account and instrument."""
        try:
            current_snapshots = await self.repos.position_snapshots.list_latest_by_account(
                account_id=account_id,
            )
        except Exception:
            logger.exception(
                "Failed to query current position snapshots for "
                "account_id=%s instrument_id=%s",
                account_id, instrument_id,
            )
            return None

        for snap in current_snapshots:
            if snap.instrument_id == instrument_id:
                return snap.quantity
        return None

    def _infer_status_from_delta(
        self,
        order: OrderRequestEntity,
        broker_order: BrokerOrderEntity,
        pre_order_qty: Decimal,
        current_qty: Decimal,
        position_delta: Decimal,
    ) -> OrderStatus | None:
        """Infer fill status from a positive position delta."""
        if position_delta >= order.requested_quantity:
            logger.info(
                "Position-delta inferred FILLED for sell order %s "
                "(broker=%s, symbol=%s, pre_qty=%s, current_qty=%s, "
                "delta=%s, order_qty=%s) [reason: position_delta_inferred_fill]",
                order.order_request_id,
                broker_order.broker_order_id,
                order.instrument_id,
                pre_order_qty,
                current_qty,
                position_delta,
                order.requested_quantity,
            )
            return OrderStatus.FILLED

        if position_delta > Decimal("0"):
            logger.info(
                "Position-delta inferred PARTIALLY_FILLED for sell order %s "
                "(broker=%s, symbol=%s, pre_qty=%s, current_qty=%s, "
                "delta=%s, order_qty=%s) [reason: position_delta_inferred_fill]",
                order.order_request_id,
                broker_order.broker_order_id,
                order.instrument_id,
                pre_order_qty,
                current_qty,
                position_delta,
                order.requested_quantity,
            )
            return OrderStatus.PARTIALLY_FILLED

        return None

    async def _try_kis_truth_fallback(
        self,
        order: OrderRequestEntity,
        broker_order: BrokerOrderEntity,
        account_id: UUID,
        pre_qty: Decimal | None = None,
        *,
        broker: BrokerAdapter | None = None,
    ) -> FillInferenceResult | None:
        """KIS truth 기반 SELL fill 추론 (KIS API 직접 호출 + rate limit 보호).

        실제 KIS ``inquire-balance`` API를 직접 호출하여 실시간 포지션을 확인한다.
        KIS API 호출은 rate limit(cooldown + 주문당 1회)으로 보호된다.
        KIS API 실패 시 로컬 position snapshot으로 fallback한다.

        Parameters
        ----------
        order:
            The order request entity.
        broker_order:
            The associated broker order entity.
        account_id:
            The account UUID.
        pre_qty:
            Optional pre-order quantity. If None, it will be queried.
        broker:
            Optional ``BrokerAdapter`` instance. When provided, used for
            KIS ``inquire-balance`` API call. When ``None``, falls back
            to local snapshot only (backward-compatible).

        Returns
        -------
        FillInferenceResult | None
            The inferred fill result, or None if cannot infer.
        """
        if order.side != OrderSide.SELL:
            return None

        # 1. Resolve pre_qty if not provided
        if pre_qty is None:
            try:
                pre_order_snapshot = await self.repos.position_snapshots.get_latest_by_account_and_instrument_before(
                    account_id=account_id,
                    instrument_id=order.instrument_id,
                    before=broker_order.created_at,
                )
            except Exception:
                logger.exception(
                    "Failed to query pre-order position snapshot for "
                    "order_id=%s broker_order_id=%s",
                    order.order_request_id,
                    broker_order.broker_order_id,
                )
                return None

            if pre_order_snapshot is None or pre_order_snapshot.quantity is None:
                return None
            pre_qty = pre_order_snapshot.quantity

        if pre_qty == Decimal("0"):
            return None

        # 2. KIS API 직접 호출 (rate limit 보호 + 1회 제한)
        #    broker 파라미터가 없으면 로컬 snapshot fallback
        kis_qty: Decimal | None = None
        if broker is not None:
            kis_qty = await self._fetch_kis_current_position_qty(
                account_id=account_id,
                instrument_id=order.instrument_id,
                broker=broker,
                _caller_order_id=str(order.order_request_id),
            )

        # 3. KIS API 결과 우선, 실패/미제공 시 로컬 snapshot fallback
        if kis_qty is not None:
            current_qty = kis_qty
        else:
            current_qty = await self._get_latest_position_qty(
                account_id=account_id,
                instrument_id=order.instrument_id,
            )
        if current_qty is None:
            current_qty = Decimal("0")

        # 4. delta 계산
        delta = pre_qty - current_qty
        if delta > Decimal("0"):
            logger.info(
                "[KIS_TRUTH_FALLBACK] order %s: pre_qty=%s, current_qty=%s, delta=%s "
                "(source=%s)",
                order.order_request_id, pre_qty, current_qty, delta,
                "kis_api" if kis_qty is not None else "local_snapshot",
            )
            return FillInferenceResult(
                inferred_fill_qty=delta,
                source="kis_truth_fallback",
            )

        return None

    async def _check_kis_inquiry_cooldown(self, account_id: UUID) -> bool:
        """동일 account에 대한 inquire-balance 호출 간격 확인.

        ``_INQUIRY_COOLDOWN_SECONDS``(기본 30초) 이내에 동일 account로
        KIS inquiry가 발생했으면 ``False``를 반환하여 호출을 건너뛴다.
        """
        now = datetime.now(timezone.utc)
        last = self._last_kis_inquiry_at.get(account_id)
        if last is not None:
            elapsed = (now - last).total_seconds()
            if elapsed < self._INQUIRY_COOLDOWN_SECONDS:
                logger.debug(
                    "KIS inquiry cooldown active for account_id=%s "
                    "(last=%.1fs ago, cooldown=%.1fs)",
                    account_id, elapsed, self._INQUIRY_COOLDOWN_SECONDS,
                )
                return False
        return True

    async def _fetch_kis_current_position_qty(
        self,
        account_id: UUID,
        instrument_id: UUID,
        *,
        broker: BrokerAdapter | None = None,
        _caller_order_id: str | None = None,
    ) -> Decimal | None:
        """Rate limit 보호 하에 KIS inquire-balance API를 직접 호출.

        실패 시 ``None``을 반환하며, 호출자에서 로컬 snapshot으로 fallback한다.
        예외를 버블링하지 않는다 (항상 ``try/except``로 감쌈).

        Parameters
        ----------
        account_id:
            대상 계정 UUID.
        instrument_id:
            대상 종목 UUID.
        broker:
            ``BrokerAdapter`` 인스턴스. ``None``이면 KIS API 호출을 건너뛴다.
        _caller_order_id:
            호출한 주문 ID (문자열). 주문당 1회 호출 제한에 사용.

        Returns
        -------
        Decimal | None
            KIS API에서 확인된 position 수량. API 실패 또는 broker 미제공 시 ``None``.
        """
        # 0. BrokerAdapter가 없으면 KIS API 호출 불가
        if broker is None:
            return None

        # 1. 주문당 1회 호출 제한 (중복 방지)
        if _caller_order_id is not None:
            if _caller_order_id in self._kis_inquiry_seen:
                logger.debug(
                    "KIS inquiry already performed for order %s — skipping",
                    _caller_order_id,
                )
                return None
            self._kis_inquiry_seen[_caller_order_id] = True

        # 2. Cooldown 확인
        if not await self._check_kis_inquiry_cooldown(account_id):
            return None

        # 3. KIS API 호출 (1회, 장애 시 조용한 fallback)
        try:
            account = await self.repos.accounts.get(account_id)
            if account is None:
                logger.warning(
                    "Account %s not found — cannot fetch KIS position",
                    account_id,
                )
                return None

            broker_account = await self.repos.broker_accounts.get(
                account.broker_account_id,
            )
            if broker_account is None:
                return None

            # KIS API 호출 시각 기록 (cooldown용)
            self._last_kis_inquiry_at[account_id] = datetime.now(timezone.utc)

            # BrokerAdapter.fetch_positions()를 통해 KIS inquire-balance 호출
            positions = await broker.fetch_positions(broker_account)
            for pos in positions:
                if pos.instrument_id == instrument_id:
                    return pos.quantity
            # KIS 응답에 해당 종목이 없음 → 전량 매도
            return Decimal("0")

        except Exception:
            logger.warning(
                "KIS inquiry failed for account_id=%s instrument_id=%s "
                "(rate limit or network) — falling back to local snapshot",
                account_id, instrument_id,
                exc_info=True,
            )
            return None  # 실패 → 로컬 snapshot fallback

    @staticmethod
    def _is_genuine_manual_reconciliation(
        order: OrderRequestEntity,
        broker_order: BrokerOrderEntity,
        status_result: OrderStatusResult,
    ) -> bool:
        """Heuristic: is this a genuine manual reconciliation case?

        Genuine manual reconciliation = operator-initiated action that
        the system cannot auto-resolve.  Examples:

        - Order was placed outside the system (no matching broker record)
        - Order was manually cancelled/modified by operator
        - Broker has no record of the order at all

        Returns ``True`` if the order should be left for manual handling.
        """
        # If broker has no record of this order at all
        if not status_result.broker_order_id:
            return True

        # If the order is very old (>24h) and still unresolved
        age = datetime.now(timezone.utc) - order.created_at
        if age.total_seconds() > 86400:  # 24 hours
            return True

        # If the broker returned a cancelled/rejected status
        if status_result.status in (
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        ):
            return False  # These can be auto-resolved via transition

        # Default: not genuine manual — system should keep trying
        return False

    @staticmethod
    def _can_recover_expired(
        order: OrderRequestEntity,
        target_status: OrderStatus,
    ) -> bool:
        """EXPIRED → FILLED/PARTIALLY_FILLED 복구 안전 조건 검증.

        ``sync_order_post_submit()``에서 broker truth 재조회 결과
        ``FILLED``/``PARTIALLY_FILLED``가 반환된 경우에만 호출된다.

        안전 조건
        --------
        1. 명시적 broker reject/cancel이 아닐 것
           → 호출자가 broker.get_order_status()로 FILLED 확인 (이미 통과)
        2. after-hours 또는 강한 후행 증거(fill event)가 있을 것
           → broker truth 자체가 가장 강한 증거이므로 통과
        3. 최근 24시간 이내 생성된 주문만 복구 대상
        4. BUY는 position inference 불가 → broker truth 직접 확인 (호출자가 이미 확인)

        Parameters
        ----------
        order:
            대상 OrderRequestEntity.
        target_status:
            복구하려는 목표 상태 (FILLED 또는 PARTIALLY_FILLED).

        Returns
        -------
        ``True`` if recovery is safe.
        """
        # 안전 조건 3: 최근 24시간 이내 생성된 주문만 복구
        if order.created_at is not None:
            age_seconds = (datetime.now(timezone.utc) - order.created_at).total_seconds()
            if age_seconds > 86400:  # 24시간 초과
                logger.warning(
                    "EXPIRED 복구 거부 (24h 초과): order_id=%s age=%.0fs",
                    order.order_request_id, age_seconds,
                )
                return False

        return True

    # ------------------------------------------------------------------
    # EOD orphan cleanup
    # ------------------------------------------------------------------

    async def expire_eod_orphan_orders(
        self,
        age_threshold: timedelta = timedelta(hours=1),
    ) -> tuple[int, int]:
        """EOD orphan cleanup: expire pending_submit and reconcile_required
        orders that never reached the broker.

        Safety conditions (ALL must be true):
        1. broker_orders.count = 0 — no broker order record exists
        2. broker_native_order_id IS NULL — never assigned by broker
        3. submitted_at IS NULL — never submitted to broker
        4. created_at < NOW() - age_threshold — older than threshold
        5. (reconcile_required only) reconciliation run is ``failed``
           or no reconciliation run exists

        State transitions:
        - ``pending_submit`` → ``EXPIRED``
          (reason_code: eod_orphan_cleanup_no_broker_order)
        - ``reconcile_required`` → ``EXPIRED``
          (reason_code: eod_orphan_cleanup_failed_reconciliation
           or eod_orphan_cleanup_no_reconciliation)

        Returns
        -------
        tuple[int, int]
            (expired_pending_submit_count, expired_reconcile_required_count)
        """
        now = datetime.now(timezone.utc)
        cutoff = now - age_threshold

        expired_pending = 0
        expired_reconcile = 0

        # --------------------------------------------------------------
        # 1. Process pending_submit orphans
        # --------------------------------------------------------------
        pending_orders = await self.repos.orders.list(
            OrderQuery(statuses=[OrderStatus.PENDING_SUBMIT], limit=500),
        )

        # Filter by safety conditions and expire
        for order in pending_orders:
            if not await self._is_eod_orphan(order, cutoff, now):
                continue

            age_hours = (now - order.created_at).total_seconds() / 3600
            try:
                await self.order_manager.transition_to(
                    order,
                    OrderStatus.EXPIRED,
                    reason_code="eod_orphan_cleanup_no_broker_order",
                    reason_message=(
                        f"EOD orphan cleanup: broker_orders=0, "
                        f"native_order_id=null, submitted_at=null, "
                        f"age={age_hours:.1f}h"
                    ),
                    actor_type="system",
                    actor_id="eod_orphan_cleanup",
                )
                expired_pending += 1
                logger.info(
                    "  expire order %s: status=pending_submit "
                    "reason=eod_orphan_cleanup_no_broker_order",
                    order.order_request_id,
                )
            except Exception as exc:
                logger.error(
                    "Failed to expire pending_submit order %s: %s",
                    order.order_request_id, exc,
                    exc_info=True,
                )

        # --------------------------------------------------------------
        # 2. Process reconcile_required orphans
        # --------------------------------------------------------------
        reconcile_orders = await self.repos.orders.list(
            OrderQuery(statuses=[OrderStatus.RECONCILE_REQUIRED], limit=500),
        )

        for order in reconcile_orders:
            if not await self._is_eod_orphan(order, cutoff, now):
                continue

            age_hours = (now - order.created_at).total_seconds() / 3600

            # Determine reason_code based on reconciliation status
            reason_code: str
            try:
                rec_status = (
                    await self.repos.reconciliations
                    .get_latest_reconciliation_status_by_order(
                        order.order_request_id,
                    )
                )
            except Exception:
                logger.exception(
                    "Failed to query reconciliation status for order %s",
                    order.order_request_id,
                )
                rec_status = None

            if rec_status == "failed":
                reason_code = "eod_orphan_cleanup_failed_reconciliation"
            else:
                reason_code = "eod_orphan_cleanup_no_reconciliation"

            try:
                await self.order_manager.transition_to(
                    order,
                    OrderStatus.EXPIRED,
                    reason_code=reason_code,
                    reason_message=(
                        f"EOD orphan cleanup: broker_orders=0, "
                        f"native_order_id=null, submitted_at=null, "
                        f"age={age_hours:.1f}h, "
                        f"reconciliation_status={rec_status or 'none'}"
                    ),
                    actor_type="system",
                    actor_id="eod_orphan_cleanup",
                )
                expired_reconcile += 1
                logger.info(
                    "  expire order %s: status=reconcile_required "
                    "reason=%s",
                    order.order_request_id,
                    reason_code,
                )
            except Exception as exc:
                logger.error(
                    "Failed to expire reconcile_required order %s: %s",
                    order.order_request_id, exc,
                    exc_info=True,
                )

        # --------------------------------------------------------------
        # 3. Audit summary
        # --------------------------------------------------------------
        logger.info(
            "EOD orphan cleanup: expired %d orders "
            "(pending_submit=%d, reconcile_required=%d)",
            expired_pending + expired_reconcile,
            expired_pending,
            expired_reconcile,
        )

        return expired_pending, expired_reconcile

    async def _is_eod_orphan(
        self,
        order: OrderRequestEntity,
        cutoff: datetime,
        now: datetime,
    ) -> bool:
        """Check EOD orphan safety conditions for a single order.

        Returns ``True`` if the order is safe to expire.
        """
        # Condition 1: created_at must exist and be older than cutoff
        if order.created_at is None or order.created_at > cutoff:
            return False

        # Condition 2: submitted_at must be NULL (never submitted to broker)
        if order.submitted_at is not None:
            return False

        # Condition 3: broker_orders must be empty
        broker_orders = await self.repos.broker_orders.list_by_order_request(
            order.order_request_id,
        )
        if len(broker_orders) > 0:
            return False

        # All conditions met
        return True


# ------------------------------------------------------------------
# Batch runner
# ------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class SyncCycleResult:
    """Summary of a single post-submit sync cycle.

    Attributes
    ----------
    total_orders:
        Total number of ``OrderRequestEntity`` records polled.
    updated:
        Number of orders whose internal status changed.
    filled:
        Number of orders that reached FILLED (terminal).
    partial:
        Number of orders still in a non-terminal syncable status
        (SUBMITTED / ACKNOWLEDGED / PARTIALLY_FILLED) after this cycle.
    errors:
        Human-readable error descriptions for any per-order failures.
    snapshots_refreshed:
        Number of orders for which a snapshot refresh was triggered
        upon reaching FILLED with new fills.
    orphans_expired_pending:
        Number of PENDING_SUBMIT orphan orders expired by EOD cleanup
        (after-hours only).
    orphans_expired_reconcile:
        Number of RECONCILE_REQUIRED orphan orders expired by EOD cleanup
        (after-hours only).
    """

    total_orders: int
    updated: int
    filled: int
    partial: int
    errors: list[str]
    snapshots_refreshed: int = 0
    orphans_expired_pending: int = 0
    orphans_expired_reconcile: int = 0


_DEFAULT_BATCH_LIMIT = 200

_ACTIVE_SYNC_STATUSES: list[OrderStatus] = [
    OrderStatus.SUBMITTED,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.RECONCILE_REQUIRED,
    OrderStatus.PENDING_SUBMIT,  # broker 미도달 orphan polling
]

# Recovery 모드(16:00 KST after-hours 복구 배치)에서 sync 대상 상태 — EXPIRED 포함
_RECOVERY_SYNC_STATUSES: list[OrderStatus] = [
    OrderStatus.SUBMITTED,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.RECONCILE_REQUIRED,
    OrderStatus.PENDING_SUBMIT,
    OrderStatus.EXPIRED,  # ← 복구 대상에 EXPIRED 포함
]


@dataclass(slots=True)
class PostSubmitSyncRunner:
    """Batch runner that discovers active orders and syncs each one.

    Designed for use by ``scripts/run_post_submit_sync_loop.py`` or any
    scheduler that wishes to periodically converge pending orders toward
    their terminal broker state.

    Typical usage::

        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=OrderSyncService(repos=repos, order_manager=order_manager),
            broker=broker_adapter,
        )
        summary = await runner.run_sync_cycle(account_ref="...")
        logger.info("sync-cycle  orders=%d updated=%d filled=%d errors=%d",
                     summary.total_orders, summary.updated,
                     summary.filled, len(summary.errors))
    """

    @staticmethod
    def _is_after_hours() -> bool:
        """현재 시간이 KIS after-hours(15:30 KST~)인지 판별."""
        kst = ZoneInfo("Asia/Seoul")
        now = datetime.now(kst)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return now >= market_close

    repos: RepositoryContainer
    sync_service: OrderSyncService
    broker: BrokerAdapter
    snapshot_refresh_cb: Callable[[UUID], Awaitable[None]] | None = None

    async def _reject_stale_pending_submit_orders(self) -> list[OrderRequestEntity]:
        """30분 이상 PENDING_SUBMIT에 stuck된 orphan 주문을 REJECTED로 전이.

        Stale 판정 기준 (ALL):
        1. status = PENDING_SUBMIT
        2. broker_native_order_id IS NULL (broker에 도달하지 않음)
        3. created_at < (now - 30분) (30분 이상 경과)
        4. side = sell (매도 주문)

        처리:
        - OrderStatus.PENDING_SUBMIT → OrderStatus.REJECTED
        - order_state_event 레코드 생성 (reason: submission_failed_no_broker_id)

        Returns:
            REJECTED로 전이된 주문 목록
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=_PENDING_SUBMIT_STALE_SECONDS)

        # PENDING_SUBMIT 상태의 모든 주문 조회
        pending_orders = await self.repos.orders.list(
            OrderQuery(statuses=[OrderStatus.PENDING_SUBMIT], limit=500),
        )

        rejected_orders: list[OrderRequestEntity] = []
        for order in pending_orders:
            # SELL 주문만 처리
            if order.side != OrderSide.SELL:
                continue

            # created_at이 None이거나 30분 미만이면 skip
            if order.created_at is None or order.created_at > cutoff:
                continue

            # broker_native_order_id 존재 여부 확인 (broker에 도달했으면 skip)
            broker_orders = await self.repos.broker_orders.list_by_order_request(
                order.order_request_id,
            )
            has_broker_order = any(
                bo.broker_native_order_id is not None for bo in broker_orders
            )
            if has_broker_order:
                continue

            # Stale PENDING_SUBMIT → REJECTED 전이
            try:
                await self.sync_service.order_manager.transition_to(
                    order,
                    OrderStatus.REJECTED,
                    reason_code="submission_failed_no_broker_id",
                    reason_message=(
                        f"Stale PENDING_SUBMIT rejected after "
                        f"{_PENDING_SUBMIT_STALE_SECONDS}s: "
                        f"created_at={order.created_at.isoformat()}, "
                        f"side={order.side.value}"
                    ),
                    actor_type="system",
                    actor_id="post_submit_sync",
                )
                rejected_orders.append(order)
                logger.info(
                    "Rejected stale PENDING_SUBMIT: order_id=%s created_at=%s side=%s",
                    order.order_request_id, order.created_at, order.side.value,
                )
            except Exception as exc:
                logger.error(
                    "Failed to reject stale PENDING_SUBMIT: order_id=%s: %s",
                    order.order_request_id, exc,
                    exc_info=True,
                )

        if rejected_orders:
            logger.info(
                "Stale PENDING_SUBMIT cleanup: rejected %d orders (submission_failed_no_broker_id)",
                len(rejected_orders),
            )

        return rejected_orders

    async def run_sync_cycle(
        self,
        account_ref: str | None = None,
        *,
        limit: int = _DEFAULT_BATCH_LIMIT,
        tx_manager: TransactionManager | None = None,
        after_hours: bool | None = None,
        recovery_mode: bool = False,
    ) -> SyncCycleResult:
        """Query active (non-terminal) orders and sync each one.

        Each order is synced within its own savepoint so that a single
        order failure (e.g. DB constraint violation, broker timeout) does
        **not** abort the entire transaction.  The savepoint is rolled
        back on failure, undoing only that order's DB writes while
        preserving the outer transaction for remaining orders.

        Parameters
        ----------
        account_ref:
            Broker account reference passed to each
            ``sync_order_post_submit()`` call.  If ``None``, an empty
            string is used (caller must override as needed).
        limit:
            Maximum number of orders to poll in a single cycle.
        tx_manager:
            Optional ``TransactionManager`` instance.  If provided, the
            cycle uses savepoints on this transaction for per-order
            isolation.  If ``None``, no savepoint isolation is applied
            (fallback for callers that don't use transactions).
        recovery_mode:
            If ``True``, also includes EXPIRED orders and filters
            to today's orders only (used for after-hours recovery batch).

        Returns
        -------
        SyncCycleResult
            Aggregated summary of the cycle.
        """
        # ── 0. Stale PENDING_SUBMIT 정리 (sync 전에 먼저 실행) ──────────
        await self._reject_stale_pending_submit_orders()

        # ── 1. Query orders ───────────────────────────────────────────────
        # recovery_mode=True → EXPIRED 포함 + 당일 주문만 필터
        active_statuses = _RECOVERY_SYNC_STATUSES if recovery_mode else _ACTIVE_SYNC_STATUSES

        if recovery_mode:
            now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
            today_start = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            # NOTE: expired / pending_submit 주문은 submitted_at=NULL이므로
            # submitted_at 대신 created_at으로 필터링해야 함.
            order_query = OrderQuery(
                statuses=active_statuses,
                limit=limit,
                created_from=today_start.astimezone(timezone.utc),
                created_to=today_end.astimezone(timezone.utc),
            )
        else:
            order_query = OrderQuery(statuses=active_statuses, limit=limit)

        orders = await self.repos.orders.list(order_query)

        if not orders:
            return SyncCycleResult(
                total_orders=0,
                updated=0,
                filled=0,
                partial=0,
                errors=[],
            )

        updated = 0
        filled = 0
        partial = 0
        snapshots_refreshed = 0
        orphans_expired_pending = 0
        orphans_expired_reconcile = 0
        errors: list[str] = []

        # ── 2. Sync each order with per-order savepoint isolation ─────────
        resolved_account_ref = account_ref or ""

        for order in orders:
            broker_orders = await self.repos.broker_orders.list_by_order_request(
                order.order_request_id,
            )
            if not broker_orders:
                continue

            for broker_order in broker_orders:
                # ── Per-order savepoint ───────────────────────────────
                # If tx_manager is available, wrap each order sync in a
                # savepoint.  On failure, only the savepoint is rolled
                # back; the outer transaction stays valid.
                if tx_manager is not None:
                    try:
                        async with tx_manager.savepoint(
                            name=f"order_sync_{broker_order.broker_order_id.hex[:8]}",
                        ):
                            order_result = await self._sync_single_order(
                                order=order,
                                broker_order=broker_order,
                                resolved_account_ref=resolved_account_ref,
                            )
                    except asyncpg.PostgresError as exc:
                        # Savepoint rolled back the failed order's writes.
                        # The outer transaction remains valid for remaining orders.
                        err_msg = (
                            f"{broker_order.broker_order_id}: "
                            f"DB error isolated by savepoint: {exc}"
                        )
                        errors.append(err_msg)
                        logger.warning(
                            "Savepoint rolled back for broker_order=%s: %s",
                            broker_order.broker_order_id, exc,
                        )
                        continue
                else:
                    # Fallback: no savepoint isolation (legacy path).
                    order_result = await self._sync_single_order(
                        order=order,
                        broker_order=broker_order,
                        resolved_account_ref=resolved_account_ref,
                    )

                # ── Aggregate result ──────────────────────────────────
                if order_result is None:
                    continue

                result, err_msg = order_result
                if err_msg is not None:
                    errors.append(err_msg)
                    continue
                if result.status_changed:
                    updated += 1
                if result.terminal and result.current_status == OrderStatus.FILLED:
                    filled += 1
                    if result.snapshot_triggered:
                        snapshots_refreshed += 1
                elif not result.terminal:
                    partial += 1

        # ── 3. Resolve any remaining RECONCILE_REQUIRED orders ────────────
        # Reconcile path는 RECONCILIATION bucket을 사용하므로 일반 polling과
        # budget이 분리되어 있다. 여기서는 reconcile 전용 reserve를 먼저
        # 확보한 후 reconcile을 실행한다.
        # limit=50: 25건의 RECONCILE_REQUIRED 주문을 모두 처리할 수 있도록
        # 기본값 5에서 50으로 상향 (Phase 4 fix).
        # is_after_hours: 장중(08:50~15:30 KST)에는 EXPIRED fallback을
        # 억제하고 RECONCILE_REQUIRED를 유지한다.
        # after_hours 파라미터가 None이면 자동 감지, 명시적 값이면 그대로 사용.
        _is_after_hours = self._is_after_hours() if after_hours is None else after_hours
        try:
            resolved = await self.sync_service._sync_reconcile_required_orders(
                account_ref=resolved_account_ref,
                broker=self.broker,
                limit=50,
                is_after_hours=_is_after_hours,
                snapshot_refresh_cb=self.snapshot_refresh_cb,
            )
            if resolved > 0:
                logger.info(
                    "sync-cycle: resolved %d RECONCILE_REQUIRED orders",
                    resolved,
                )
        except Exception as exc:
            logger.error(
                "sync-cycle: _sync_reconcile_required_orders failed: %s",
                exc,
                exc_info=True,
            )

        # ── 4. EOD orphan cleanup (after-hours only) ────────────────────────
        # 장중(after_hours=False)에는 실행하지 않고,
        # after-hours(15:30 KST~)에만 PENDING_SUBMIT / RECONCILE_REQUIRED
        # orphan 주문을 EXPIRED로 정리한다.
        if _is_after_hours:
            try:
                orphans_expired_pending, orphans_expired_reconcile = (
                    await self.sync_service.expire_eod_orphan_orders()
                )
                if orphans_expired_pending > 0 or orphans_expired_reconcile > 0:
                    logger.info(
                        "sync-cycle: EOD orphan cleanup complete — "
                        "pending_submit=%d reconcile_required=%d",
                        orphans_expired_pending,
                        orphans_expired_reconcile,
                    )
            except Exception as exc:
                logger.error(
                    "sync-cycle: EOD orphan cleanup failed: %s",
                    exc,
                    exc_info=True,
                )

        # ── 5. Return summary ─────────────────────────────────────────────
        return SyncCycleResult(
            total_orders=len(orders),
            updated=updated,
            filled=filled,
            partial=partial,
            snapshots_refreshed=snapshots_refreshed,
            orphans_expired_pending=orphans_expired_pending,
            orphans_expired_reconcile=orphans_expired_reconcile,
            errors=errors,
        )

    async def _sync_single_order(
        self,
        order: OrderRequestEntity,
        broker_order: BrokerOrderEntity,
        resolved_account_ref: str,
    ) -> tuple[SyncOrderResult, str | None] | None:
        """Sync a single broker order and return (result, error_message).

        Returns ``None`` if the broker order should be skipped.
        """
        try:
            result = await self.sync_service.sync_order_post_submit(
                account_ref=resolved_account_ref,
                broker=self.broker,
                broker_order_id=broker_order.broker_order_id,
                snapshot_refresh_cb=self.snapshot_refresh_cb,
            )
        except asyncpg.PostgresError as exc:
            # DB-level error (e.g. constraint violation, aborted transaction).
            # Re-raise so the savepoint boundary can roll back and isolate
            # this failure from the rest of the cycle.
            err_msg = (
                f"{broker_order.broker_order_id}: DB error during sync: {exc}"
            )
            logger.error(
                "DB error syncing broker_order=%s order_id=%s: %s — "
                "re-raising for savepoint rollback",
                broker_order.broker_order_id,
                order.order_request_id,
                exc,
                exc_info=True,
            )
            raise
        except Exception as exc:
            err_msg = (
                f"{broker_order.broker_order_id}: {exc}"
            )
            logger.warning(
                "sync_order_post_submit failed for broker_order=%s: %s",
                broker_order.broker_order_id, exc,
            )
            return None, err_msg

        err_msg: str | None = None
        if result.error is not None:
            err_msg = f"{broker_order.broker_order_id}: {result.error}"
        return result, err_msg
