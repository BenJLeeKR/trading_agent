"""Tests for ``OrderSyncService`` — post-submit status/fill sync.

실행: ``uv run pytest tests/services/test_order_sync_service.py -v``
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    BrokerOrderEntity,
    FillEventEntity,
    OrderRequestEntity,
)
from agent_trading.domain.enums import (
    BrokerName,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.domain.models import FillEvent, OrderStatusResult
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.order_sync_service import (
    OrderSyncService,
    SyncOrderResult,
)

pytestmark = pytest.mark.asyncio


# ── Stub Broker ──


class _StubBroker:
    """Stub broker adapter that returns canned status/fill results.

    Implements only the methods needed by ``OrderSyncService``:
    - ``get_order_status``
    - ``get_fills``
    """

    def __init__(
        self,
        status: OrderStatus,
        fills: list[FillEvent] | None = None,
    ) -> None:
        self._status = status
        self._fills = fills or []
        self.get_order_status_call_count = 0
        self.get_fills_call_count = 0

    async def get_order_status(
        self,
        account_ref: str,
        client_order_id: str,
        broker_order_id: str,
    ) -> OrderStatusResult:
        self.get_order_status_call_count += 1
        return OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            status=self._status,
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("0"),
            average_fill_price=Decimal("0"),
            last_updated_at=datetime.now(timezone.utc),
        )

    async def get_fills(
        self,
        account_ref: str,
        broker_order_id: str,
        from_ts: datetime | None = None,
    ) -> Sequence[FillEvent]:
        self.get_fills_call_count += 1
        return self._fills


# ── Fixtures ──


@pytest.fixture
def repos() -> RepositoryContainer:
    return build_in_memory_repositories()


@pytest.fixture
def order_manager(repos: RepositoryContainer) -> OrderManager:
    return OrderManager(repos=repos)


@pytest.fixture
def sync_service(
    repos: RepositoryContainer,
    order_manager: OrderManager,
) -> OrderSyncService:
    return OrderSyncService(repos=repos, order_manager=order_manager)


def _make_order(
    repos: RepositoryContainer,
    *,
    status: OrderStatus = OrderStatus.SUBMITTED,
    client_order_id: str = "SYNC-TEST-001",
) -> OrderRequestEntity:
    """Create and persist an order with the given status."""
    now = datetime.now(timezone.utc)
    order = OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=uuid4(),
        instrument_id=uuid4(),
        client_order_id=client_order_id,
        idempotency_key="idem-sync-001",
        correlation_id="corr-sync-001",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        requested_price=Decimal("50000"),
        requested_quantity=Decimal("10"),
        status=status,
        trade_decision_id=None,
        submitted_at=None,
        status_reason_code=None,
        status_reason_message=None,
        created_at=now,
        updated_at=now,
    )
    # Direct in-memory insert to bypass OrderManager.create_order
    repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]
    return order


def _make_broker_order(
    repos: RepositoryContainer,
    order: OrderRequestEntity,
    *,
    broker_native_order_id: str = "BRK-SYNC-001",
    broker_status: str = "submitted",
    last_synced_at: datetime | None = None,
) -> BrokerOrderEntity:
    """Create and persist a broker order linked to ``order``."""
    now = datetime.now(timezone.utc)
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order.order_request_id,
        broker_name=BrokerName.KOREA_INVESTMENT.value,
        broker_status=broker_status,
        broker_native_order_id=broker_native_order_id,
        created_at=now,
        updated_at=now,
        last_synced_at=last_synced_at,
    )
    repos.broker_orders._items[broker_order.broker_order_id] = broker_order  # type: ignore[attr-defined]
    return broker_order


# ═════════════════════════════════════════════════════════════════════
# Test: SUBMITTED → ACKNOWLEDGED
# ═════════════════════════════════════════════════════════════════════


class TestSyncAcknowledged:
    """Broker가 ACKNOWLEDGED를 반환 → SUBMITTED에서 ACKNOWLEDGED로 전이."""

    async def test_submitted_to_acknowledged(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        order = _make_order(repos, status=OrderStatus.SUBMITTED)
        broker_order = _make_broker_order(
            repos, order, broker_status="submitted",
        )
        broker = _StubBroker(status=OrderStatus.ACKNOWLEDGED)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        assert result.status_changed is True
        assert result.current_status == OrderStatus.ACKNOWLEDGED
        assert result.fills_synced == 0
        assert result.terminal is False

        # Verify broker order entity was updated
        updated_bo = await repos.broker_orders.get(broker_order.broker_order_id)
        assert updated_bo is not None
        assert updated_bo.broker_status == "acknowledged"
        assert updated_bo.last_synced_at is not None


# ═════════════════════════════════════════════════════════════════════
# Test: ACKNOWLEDGED → PARTIALLY_FILLED + fills
# ═════════════════════════════════════════════════════════════════════


class TestSyncPartiallyFilled:
    """Broker가 PARTIALLY_FILLED + 체결 내역 반환."""

    async def test_acknowledged_to_partially_filled_with_fills(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        now = datetime.now(timezone.utc)
        order = _make_order(repos, status=OrderStatus.ACKNOWLEDGED)
        broker_order = _make_broker_order(
            repos, order, broker_status="acknowledged",
        )
        fills = [
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=broker_order.broker_native_order_id,
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("3"),
                fill_price=Decimal("50000"),
                fill_timestamp=now,
                fee=Decimal("150"),
                tax=Decimal("0"),
            ),
        ]
        broker = _StubBroker(status=OrderStatus.PARTIALLY_FILLED, fills=fills)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        assert result.status_changed is True
        assert result.current_status == OrderStatus.PARTIALLY_FILLED
        assert result.fills_synced == 1
        assert result.fills_skipped == 0
        assert result.terminal is False
        assert broker.get_fills_call_count >= 1


# ═════════════════════════════════════════════════════════════════════
# Test: PARTIALLY_FILLED → FILLED + terminal
# ═════════════════════════════════════════════════════════════════════


class TestSyncFilled:
    """Broker가 FILLED 반환 → terminal state 도달 + snapshot refresh."""

    async def test_partially_filled_to_filled_terminal(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        now = datetime.now(timezone.utc)
        order = _make_order(repos, status=OrderStatus.PARTIALLY_FILLED)
        broker_order = _make_broker_order(
            repos, order, broker_status="partially_filled",
        )
        fills = [
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=broker_order.broker_native_order_id,
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("7"),
                fill_price=Decimal("50000"),
                fill_timestamp=now,
                fee=Decimal("350"),
                tax=Decimal("0"),
            ),
        ]
        broker = _StubBroker(status=OrderStatus.FILLED, fills=fills)

        snapshot_called: list[UUID] = []

        async def _refresh_cb(account_id: UUID) -> None:
            snapshot_called.append(account_id)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
            snapshot_refresh_cb=_refresh_cb,
        )

        assert result.status_changed is True
        assert result.current_status == OrderStatus.FILLED
        assert result.fills_synced == 1
        assert result.terminal is True
        assert result.snapshot_triggered is True
        assert len(snapshot_called) == 1
        assert snapshot_called[0] == order.account_id


# ═════════════════════════════════════════════════════════════════════
# Test: SUBMITTED → FILLED chain transition
# ═════════════════════════════════════════════════════════════════════


class TestSyncChainTransition:
    """SUBMITTED → FILLED: 3단계 chain 전이."""

    async def test_submitted_to_filled_chain(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        order = _make_order(repos, status=OrderStatus.SUBMITTED)
        broker_order = _make_broker_order(
            repos, order, broker_status="submitted",
        )
        broker = _StubBroker(status=OrderStatus.FILLED)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        assert result.status_changed is True
        assert result.current_status == OrderStatus.FILLED
        assert result.terminal is True

        # Verify final order state
        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.FILLED


# ═════════════════════════════════════════════════════════════════════
# Test: Fill deduplication
# ═════════════════════════════════════════════════════════════════════


class TestSyncFillDedup:
    """동일 fill이 2회차 sync에서 skip되는지 검증."""

    async def test_fill_dedup(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        now = datetime.now(timezone.utc)
        order = _make_order(repos, status=OrderStatus.ACKNOWLEDGED)
        broker_order = _make_broker_order(
            repos, order, broker_status="acknowledged",
        )

        fills = [
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=broker_order.broker_native_order_id,
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("5"),
                fill_price=Decimal("50000"),
                fill_timestamp=now,
                fee=Decimal("250"),
                tax=Decimal("0"),
            ),
        ]
        broker = _StubBroker(status=OrderStatus.PARTIALLY_FILLED, fills=fills)

        # 1st call — sync fill
        r1 = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )
        assert r1.fills_synced == 1
        assert r1.fills_skipped == 0

        # 2nd call — broker returns same fills → dedup
        r2 = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )
        assert r2.fills_synced == 0, "Same fills should be deduplicated"
        assert r2.fills_skipped >= 1


# ═════════════════════════════════════════════════════════════════════
# Test: Already terminal → no-op
# ═════════════════════════════════════════════════════════════════════


class TestSyncAlreadyTerminal:
    """이미 terminal state인 주문 → get_order_status 호출 없음."""

    async def test_already_filled_no_op(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        order = _make_order(repos, status=OrderStatus.FILLED)
        broker_order = _make_broker_order(
            repos, order, broker_status="filled",
        )
        broker = _StubBroker(status=OrderStatus.FILLED)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        assert result.status_changed is False
        assert result.current_status == OrderStatus.FILLED
        assert result.terminal is True
        assert result.error is None
        # broker should NOT have been called
        assert broker.get_order_status_call_count == 0


# ═════════════════════════════════════════════════════════════════════
# Test: No status change
# ═════════════════════════════════════════════════════════════════════


class TestSyncNoChange:
    """Broker 상태가 현재와 동일 → 상태 변화 없음, fill만 sync."""

    async def test_no_status_change_but_fills_synced(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        now = datetime.now(timezone.utc)
        order = _make_order(repos, status=OrderStatus.ACKNOWLEDGED)
        broker_order = _make_broker_order(
            repos, order, broker_status="acknowledged",
        )
        fills = [
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=broker_order.broker_native_order_id,
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("2"),
                fill_price=Decimal("50000"),
                fill_timestamp=now,
                fee=Decimal("100"),
                tax=Decimal("0"),
            ),
        ]
        broker = _StubBroker(status=OrderStatus.ACKNOWLEDGED, fills=fills)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        assert result.status_changed is False
        assert result.current_status == OrderStatus.ACKNOWLEDGED
        assert result.fills_synced == 1
        assert result.terminal is False


# ═════════════════════════════════════════════════════════════════════
# Test: Unknown status → RECONCILE_REQUIRED
# ═════════════════════════════════════════════════════════════════════


class TestSyncUnknownStatus:
    """Broker가 알 수 없는 상태 반환 → RECONCILE_REQUIRED 안전망."""

    async def test_unknown_broker_status_reconcile(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        order = _make_order(repos, status=OrderStatus.SUBMITTED)
        broker_order = _make_broker_order(
            repos, order, broker_status="submitted",
        )
        broker = _StubBroker(status=OrderStatus.RECONCILE_REQUIRED)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        assert result.status_changed is True
        assert result.current_status == OrderStatus.RECONCILE_REQUIRED
        assert result.terminal is False


# ═════════════════════════════════════════════════════════════════════
# Test: CANCELLED from ACKNOWLEDGED
# ═════════════════════════════════════════════════════════════════════


class TestSyncCancelled:
    """Broker가 CANCELLED 반환 → terminal state."""

    async def test_acknowledged_to_cancelled(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        order = _make_order(repos, status=OrderStatus.ACKNOWLEDGED)
        broker_order = _make_broker_order(
            repos, order, broker_status="acknowledged",
        )
        broker = _StubBroker(status=OrderStatus.CANCELLED)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        assert result.status_changed is True
        assert result.current_status == OrderStatus.CANCELLED
        assert result.terminal is True
        # CANCELLED는 FILLED가 아니므로 snapshot refresh 없음
        assert result.snapshot_triggered is False


# ═════════════════════════════════════════════════════════════════════
# Test: Broker order not found
# ═════════════════════════════════════════════════════════════════════


class TestSyncBrokerOrderNotFound:
    """존재하지 않는 broker_order_id → 에러 결과."""

    async def test_broker_order_not_found(
        self,
        sync_service: OrderSyncService,
    ) -> None:
        broker = _StubBroker(status=OrderStatus.ACKNOWLEDGED)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=uuid4(),  # 존재하지 않는 ID
        )

        assert result.error is not None
        assert "BrokerOrder not found" in result.error


# ═════════════════════════════════════════════════════════════════════
# Test: Broker get_order_status raises
# ═════════════════════════════════════════════════════════════════════


class TestSyncBrokerError:
    """Broker 호출 실패 → graceful error handling."""

    async def test_get_order_status_raises(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        order = _make_order(repos, status=OrderStatus.SUBMITTED)
        broker_order = _make_broker_order(
            repos, order, broker_status="submitted",
        )

        class _FailingBroker:
            async def get_order_status(
                self, account_ref: str, client_order_id: str, broker_order_id: str
            ) -> OrderStatusResult:
                raise RuntimeError("Broker unavailable")

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=_FailingBroker(),  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        assert result.error is not None
        assert "get_order_status failed" in result.error
        assert result.status_changed is False
        assert result.current_status == OrderStatus.SUBMITTED
