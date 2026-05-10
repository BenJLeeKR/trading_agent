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
from agent_trading.repositories.filters import OrderQuery
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.order_sync_service import (
    OrderSyncService,
    PostSubmitSyncRunner,
    SyncCycleResult,
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
    """Fill dedup — broker_fill_id 우선, composite key fallback."""

    async def test_fill_dedup_composite_key_fallback(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """``broker_fill_id=None`` fill → composite key dedup (기존 방식 유지)."""
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
                broker_fill_id=None,
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

        # 2nd call — broker returns same fills → composite key dedup
        r2 = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )
        assert r2.fills_synced == 0, "Same fills should be deduplicated"
        assert r2.fills_skipped >= 1

    async def test_fill_dedup_by_broker_fill_id(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """동일 ``broker_fill_id`` fill 2회 sync → broker_fill_id 기반 dedup."""
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
                broker_fill_id="CCLD001",
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

        # 2nd call — broker returns same fills → broker_fill_id dedup
        r2 = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )
        assert r2.fills_synced == 0, "Same broker_fill_id should be deduplicated"
        assert r2.fills_skipped >= 1

    async def test_fill_dedup_broker_fill_id_preferred(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """동일 timestamp/price/qty지만 다른 broker_fill_id → 별개 fill (broker_fill_id 우선)."""
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
                broker_fill_id="CCLD001",
                fee=Decimal("250"),
                tax=Decimal("0"),
            ),
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=broker_order.broker_native_order_id,
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("5"),
                fill_price=Decimal("50000"),
                fill_timestamp=now,
                broker_fill_id="CCLD002",  # 다른 fill ID
                fee=Decimal("250"),
                tax=Decimal("0"),
            ),
        ]
        broker = _StubBroker(status=OrderStatus.PARTIALLY_FILLED, fills=fills)

        # Composite key만 보면 둘이 동일하지만, broker_fill_id가 다르므로 둘 다 sync
        r = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )
        assert r.fills_synced == 2, "Different broker_fill_id → both synced"
        assert r.fills_skipped == 0

    async def test_fill_dedup_broker_fill_id_overrides_timestamp(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """동일 ``broker_fill_id`` + 다른 timestamp/price/qty → broker_fill_id 우선 dedup (skip)."""
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
                broker_fill_id="CCLD001",
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

        # 2nd call — 동일 broker_fill_id지만 timestamp/price/qty가 다름
        later = datetime.now(timezone.utc)
        fills2 = [
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=broker_order.broker_native_order_id,
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("10"),      # 다른 수량
                fill_price=Decimal("51000"),       # 다른 가격
                fill_timestamp=later,              # 다른 시간
                broker_fill_id="CCLD001",          # 동일 broker_fill_id
                fee=Decimal("300"),
                tax=Decimal("0"),
            ),
        ]
        broker2 = _StubBroker(status=OrderStatus.PARTIALLY_FILLED, fills=fills2)
        r2 = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker2,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )
        assert r2.fills_synced == 0, "Same broker_fill_id → deduped despite different values"
        assert r2.fills_skipped >= 1

    async def test_fill_dedup_mixed(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """일부 fill은 broker_fill_id 보유, 일부는 None → 각각 dedup 정상."""
        now = datetime.now(timezone.utc)
        order = _make_order(repos, status=OrderStatus.ACKNOWLEDGED)
        broker_order = _make_broker_order(
            repos, order, broker_status="acknowledged",
        )

        # Fill A: has broker_fill_id, Fill B: no broker_fill_id
        fills = [
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=broker_order.broker_native_order_id,
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("3"),
                fill_price=Decimal("49000"),
                fill_timestamp=now,
                broker_fill_id="CCLD-A",
                fee=Decimal("100"),
                tax=Decimal("0"),
            ),
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=broker_order.broker_native_order_id,
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("7"),
                fill_price=Decimal("51000"),
                fill_timestamp=now,
                broker_fill_id=None,
                fee=Decimal("200"),
                tax=Decimal("0"),
            ),
        ]
        broker = _StubBroker(status=OrderStatus.PARTIALLY_FILLED, fills=fills)

        # 1st call — both synced
        r1 = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )
        assert r1.fills_synced == 2

        # 2nd call — broker returns identical fills → both deduped
        r2 = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )
        assert r2.fills_synced == 0
        assert r2.fills_skipped >= 2

    async def test_fill_empty_broker_fill_id_normalized_to_none(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """빈 문자열 broker_fill_id는 None으로 정규화되고 composite fallback을 사용한다."""
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
                broker_fill_id="",
                fee=Decimal("250"),
                tax=Decimal("0"),
            ),
        ]
        broker = _StubBroker(status=OrderStatus.PARTIALLY_FILLED, fills=fills)

        r1 = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )
        assert r1.fills_synced == 1
        assert r1.fills_skipped == 0

        saved = await repos.fill_events.list_by_broker_order(
            broker_order.broker_order_id,
        )
        assert len(saved) == 1
        assert saved[0].broker_fill_id is None
        assert saved[0].source_channel == "rest_poll"

        r2 = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )
        assert r2.fills_synced == 0
        assert r2.fills_skipped >= 1


# ═════════════════════════════════════════════════════════════════════
# Test: InMemoryFillEventRepository.get_by_broker_fill_id
# ═════════════════════════════════════════════════════════════════════


class TestInMemoryFillEventRepository:
    """``InMemoryFillEventRepository.get_by_broker_fill_id()`` 동작 검증."""

    async def test_get_by_broker_fill_id_found(
        self,
        repos: RepositoryContainer,
    ) -> None:
        """broker_fill_id로 등록된 fill을 찾을 수 있음."""
        fill_id = uuid4()
        entity = FillEventEntity(
            fill_event_id=fill_id,
            broker_order_id=uuid4(),
            fill_timestamp=datetime.now(timezone.utc),
            fill_price=Decimal("50000"),
            fill_quantity=Decimal("5"),
            source_channel="rest_poll",
            broker_fill_id="CCLD-XYZ",
        )
        await repos.fill_events.add(entity)

        found = await repos.fill_events.get_by_broker_fill_id("CCLD-XYZ")
        assert found is not None
        assert found.fill_event_id == fill_id
        assert found.broker_fill_id == "CCLD-XYZ"

    async def test_get_by_broker_fill_id_not_found(
        self,
        repos: RepositoryContainer,
    ) -> None:
        """존재하지 않는 broker_fill_id → None."""
        found = await repos.fill_events.get_by_broker_fill_id("NONEXISTENT")
        assert found is None

    async def test_get_by_broker_fill_id_ignores_none(
        self,
        repos: RepositoryContainer,
    ) -> None:
        """``broker_fill_id=None``으로 저장된 fill은 get_by_broker_fill_id로 찾을 수 없음."""
        fill_id = uuid4()
        entity = FillEventEntity(
            fill_event_id=fill_id,
            broker_order_id=uuid4(),
            fill_timestamp=datetime.now(timezone.utc),
            fill_price=Decimal("50000"),
            fill_quantity=Decimal("5"),
            source_channel="rest_poll",
            broker_fill_id=None,
        )
        await repos.fill_events.add(entity)

        # InMemory는 _by_fill_id 인덱스에 None을 저장하지 않음
        found = await repos.fill_events.get_by_broker_fill_id("")  # 빈 문자열은 None과 다름
        assert found is None


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
# Test: FILLED 도달 but fills_synced == 0 → refresh 미호출
# ═════════════════════════════════════════════════════════════════════


class TestSyncFilledNoFillIncrease:
    """FILLED 도달했지만 새로운 fill이 없으면 snapshot refresh를 호출하지 않음."""

    async def test_filled_without_new_fills_no_refresh(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        now = datetime.now(timezone.utc)
        order = _make_order(repos, status=OrderStatus.PARTIALLY_FILLED)
        broker_order = _make_broker_order(
            repos, order, broker_status="partially_filled",
        )
        # Broker returns FILLED but with NO fills (fills already synced previously)
        broker = _StubBroker(status=OrderStatus.FILLED, fills=[])

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
        assert result.terminal is True
        assert result.fills_synced == 0
        # 새 조건: fills_synced > 0 을 만족하지 못하므로 refresh 미호출
        assert result.snapshot_triggered is False
        assert len(snapshot_called) == 0


# ═════════════════════════════════════════════════════════════════════
# Test: PARTIALLY_FILLED + fills > 0 → refresh 미호출 (FILLED 아님)
# ═════════════════════════════════════════════════════════════════════


class TestSyncPartialFillNoRefresh:
    """PARTIALLY_FILLED로 전이 + fill 증가 → FILLED가 아니므로 refresh 미호출."""

    async def test_partial_fill_no_refresh(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        now = datetime.now(timezone.utc)
        order = _make_order(repos, status=OrderStatus.SUBMITTED)
        broker_order = _make_broker_order(
            repos, order, broker_status="submitted",
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
        assert result.current_status == OrderStatus.PARTIALLY_FILLED
        assert result.terminal is False
        assert result.fills_synced >= 1
        # FILLED가 아니므로 refresh 미호출
        assert result.snapshot_triggered is False
        assert len(snapshot_called) == 0


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


# ═════════════════════════════════════════════════════════════════════
# Test: PostSubmitSyncRunner — batch post-submit sync cycle
# ═════════════════════════════════════════════════════════════════════


class TestPostSubmitSyncRunner:
    """``PostSubmitSyncRunner`` — 미체결/부분체결 주문 batch sync cycle."""

    async def test_runner_only_active_orders(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Active order(SUBMITTED/ACKNOWLEDGED/PARTIALLY_FILLED)만 polling 대상."""
        # Active orders
        active1 = _make_order(repos, status=OrderStatus.SUBMITTED, client_order_id="ACT-001")
        active2 = _make_order(repos, status=OrderStatus.ACKNOWLEDGED, client_order_id="ACT-002")
        active3 = _make_order(repos, status=OrderStatus.PARTIALLY_FILLED, client_order_id="ACT-003")
        # Terminal order (FILLED) — polling 제외 대상
        terminal = _make_order(repos, status=OrderStatus.FILLED, client_order_id="TERM-001")

        for o in [active1, active2, active3, terminal]:
            _make_broker_order(repos, o, broker_native_order_id=f"BRK-{o.client_order_id}")

        # Broker가 ACKNOWLEDGED 반환 → active1(SUBMITTED→ACK)만 status_changed
        # active2(ACK→ACK)와 active3(PARTIALLY_FILLED→ACK, backward transition)는 변경 없음
        broker = _StubBroker(status=OrderStatus.ACKNOWLEDGED)
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=broker,  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(account_ref="test-account")

        assert result.total_orders == 3  # FILLED는 제외
        assert result.filled == 0        # FILLED 도달 없음
        # active1: SUBMITTED→ACK (changed 1), active2: ACK→ACK (no change),
        # active3: PARTIALLY_FILLED→ACK (backward → no change)
        assert result.updated == 1
        assert result.partial == 3       # 모두 non-terminal
        assert result.errors == []

    async def test_runner_empty_cycle(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Active order가 전혀 없으면 empty summary 반환."""
        # Terminal order만 존재
        _make_order(repos, status=OrderStatus.FILLED, client_order_id="TERM-001")

        broker = _StubBroker(status=OrderStatus.FILLED)
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=broker,  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(account_ref="test-account")

        assert result.total_orders == 0
        assert result.updated == 0
        assert result.filled == 0
        assert result.partial == 0
        assert result.errors == []

    async def test_runner_partial_to_filled(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """PARTIALLY_FILLED → FILLED 수렴을 runner가 정확히 집계."""
        now = datetime.now(timezone.utc)
        order = _make_order(repos, status=OrderStatus.PARTIALLY_FILLED, client_order_id="PF-001")
        broker_order = _make_broker_order(repos, order, broker_native_order_id="BRK-PF-001")
        fills = [
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=broker_order.broker_native_order_id,
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("10"),
                fill_price=Decimal("50000"),
                fill_timestamp=now,
                fee=Decimal("500"),
                tax=Decimal("0"),
            ),
        ]
        broker = _StubBroker(status=OrderStatus.FILLED, fills=fills)
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=broker,  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(account_ref="test-account")

        assert result.total_orders == 1
        assert result.updated == 1       # 상태 변경 발생
        assert result.filled == 1        # FILLED 도달
        assert result.partial == 0       # 더 이상 active 아님
        assert result.errors == []

        # Verify final order state
        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.FILLED

    async def test_runner_filled_triggers_snapshot(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """FILLED 도달 시 snapshot_refresh_cb가 runner를 통해 호출됨."""
        now = datetime.now(timezone.utc)
        order = _make_order(repos, status=OrderStatus.PARTIALLY_FILLED, client_order_id="SNAP-001")
        broker_order = _make_broker_order(repos, order, broker_native_order_id="BRK-SNAP-001")
        fills = [
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=broker_order.broker_native_order_id,
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("10"),
                fill_price=Decimal("50000"),
                fill_timestamp=now,
                fee=Decimal("500"),
                tax=Decimal("0"),
            ),
        ]
        broker = _StubBroker(status=OrderStatus.FILLED, fills=fills)

        snapshot_called: list[UUID] = []

        async def _refresh_cb(account_id: UUID) -> None:
            snapshot_called.append(account_id)

        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=broker,  # type: ignore[arg-type]
            snapshot_refresh_cb=_refresh_cb,
        )

        result = await runner.run_sync_cycle(account_ref="test-account")

        assert result.total_orders == 1
        assert result.filled == 1
        # snapshot_refresh_cb가 sync_service를 통해 호출되었는지 검증
        assert len(snapshot_called) == 1
        assert snapshot_called[0] == order.account_id

    async def test_runner_one_failure_does_not_block_others(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """단일 broker_order sync 실패가 전체 cycle을 중단시키지 않음."""
        order1 = _make_order(repos, status=OrderStatus.SUBMITTED, client_order_id="FAIL-001")
        order2 = _make_order(repos, status=OrderStatus.SUBMITTED, client_order_id="FAIL-002")
        order3 = _make_order(repos, status=OrderStatus.SUBMITTED, client_order_id="FAIL-003")

        bo1 = _make_broker_order(repos, order1, broker_native_order_id="BRK-FAIL-001")
        bo2 = _make_broker_order(repos, order2, broker_native_order_id="BRK-FAIL-002")
        bo3 = _make_broker_order(repos, order3, broker_native_order_id="BRK-FAIL-003")

        # order2의 broker_order → get_order_status에서 RuntimeError 발생
        class _SelectiveFailingBroker:
            def __init__(self) -> None:
                self._fail_id = bo2.broker_native_order_id
                self.get_order_status_call_count = 0
                self.get_fills_call_count = 0

            async def get_order_status(
                self,
                account_ref: str,
                client_order_id: str,
                broker_order_id: str,
            ) -> OrderStatusResult:
                self.get_order_status_call_count += 1
                if broker_order_id == self._fail_id:
                    raise RuntimeError("Broker timeout")
                return OrderStatusResult(
                    broker_name=BrokerName.KOREA_INVESTMENT,
                    client_order_id=client_order_id,
                    broker_order_id=broker_order_id,
                    status=OrderStatus.ACKNOWLEDGED,
                    filled_quantity=Decimal("0"),
                    remaining_quantity=Decimal("10"),
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
                return []

        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=_SelectiveFailingBroker(),  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(account_ref="test-account")

        assert result.total_orders == 3    # 3개 모두 조회됨
        assert len(result.errors) == 1     # order2만 실패
        assert result.updated == 2         # order1, order3은 성공 (SUBMITTED→ACK)
        assert result.partial == 3         # 모두 non-terminal

    async def test_runner_broker_exception_isolation(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Broker.get_order_status() 예외가 SyncOrderResult.error로 처리되어
        runner의 except 분기 대신 정상 error 집계 경로로 수렴."""
        order = _make_order(repos, status=OrderStatus.SUBMITTED, client_order_id="EXC-001")
        _make_broker_order(repos, order, broker_native_order_id="BRK-EXC-001")

        class _FailingBroker:
            async def get_order_status(
                self, account_ref: str, client_order_id: str, broker_order_id: str
            ) -> OrderStatusResult:
                raise RuntimeError("Broker unavailable")

            async def get_fills(
                self,
                account_ref: str,
                broker_order_id: str,
                from_ts: datetime | None = None,
            ) -> Sequence[FillEvent]:
                return []

        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=_FailingBroker(),  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(account_ref="test-account")

        assert result.total_orders == 1
        assert len(result.errors) == 1
        assert "get_order_status failed" in result.errors[0]
        assert result.updated == 0
        assert result.filled == 0
        assert result.partial == 1  # non-terminal (error case)

    async def test_runner_multiple_broker_orders_per_order(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """하나의 OrderRequestEntity에 여러 BrokerOrderEntity가 존재하는 경우
        각 broker_order가 모두 sync되고 집계에 반영됨."""
        order = _make_order(repos, status=OrderStatus.ACKNOWLEDGED, client_order_id="MULTI-001")
        bo1 = _make_broker_order(repos, order, broker_native_order_id="BRK-MULTI-A")
        bo2 = _make_broker_order(repos, order, broker_native_order_id="BRK-MULTI-B")

        broker = _StubBroker(status=OrderStatus.ACKNOWLEDGED)
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=broker,  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(account_ref="test-account")

        assert result.total_orders == 1       # 1개의 order entity
        # 2개의 broker_order 각각에 대해 sync 수행 → partial=2
        assert result.partial == 2
        assert result.updated == 0            # 상태 변화 없음 (ACK→ACK)
        assert result.filled == 0
        assert result.errors == []

    async def test_runner_no_broker_order_skipped(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """BrokerOrderEntity가 없는 OrderRequestEntity는 조용히 skip."""
        _make_order(repos, status=OrderStatus.ACKNOWLEDGED, client_order_id="NOBRK-001")
        # Broker order를 생성하지 않음

        broker = _StubBroker(status=OrderStatus.FILLED)
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=broker,  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(account_ref="test-account")

        # Order는 조회되었지만 broker_order가 없어 skip
        assert result.total_orders == 1
        assert result.updated == 0
        assert result.filled == 0
        assert result.partial == 0   # sync 수행 안 됨 → partial 집계 없음
        assert result.errors == []


class TestRunnerSnapshotsRefreshed:
    """``PostSubmitSyncRunner``가 ``SyncCycleResult.snapshots_refreshed``를
    올바르게 누적하는지 검증."""

    async def test_runner_snapshots_refreshed_counted(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """FILLED 도달 + fill 증가 → snapshots_refreshed=1 누적."""
        now = datetime.now(timezone.utc)

        # Order 1: PARTIALLY_FILLED → broker가 FILLED + fill 반환
        order1 = _make_order(
            repos, status=OrderStatus.PARTIALLY_FILLED,
            client_order_id="SNAP-CNT-001",
        )
        bo1 = _make_broker_order(
            repos, order1, broker_native_order_id="BRK-SNAP-CNT-A",
        )
        fills1 = [
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=bo1.broker_native_order_id,
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("10"),
                fill_price=Decimal("50000"),
                fill_timestamp=now,
                fee=Decimal("500"),
                tax=Decimal("0"),
            ),
        ]

        # Order 2: SUBMITTED → broker가 PARTIALLY_FILLED + fill 반환 (FILLED 아님)
        order2 = _make_order(
            repos, status=OrderStatus.SUBMITTED,
            client_order_id="SNAP-CNT-002",
        )
        bo2 = _make_broker_order(
            repos, order2, broker_native_order_id="BRK-SNAP-CNT-B",
        )
        fills2 = [
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id=bo2.broker_native_order_id,
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("3"),
                fill_price=Decimal("50000"),
                fill_timestamp=now,
                fee=Decimal("150"),
                tax=Decimal("0"),
            ),
        ]

        snapshot_called: list[UUID] = []

        async def _refresh_cb(account_id: UUID) -> None:
            snapshot_called.append(account_id)

        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=_MultiStatusBroker(  # type: ignore[arg-type]
                [(bo1.broker_native_order_id, OrderStatus.FILLED, fills1),
                 (bo2.broker_native_order_id, OrderStatus.PARTIALLY_FILLED, fills2)],
            ),
            snapshot_refresh_cb=_refresh_cb,
        )

        result = await runner.run_sync_cycle(account_ref="test-account")

        assert result.total_orders == 2
        assert result.filled == 1
        assert result.partial == 1
        assert result.snapshots_refreshed == 1
        assert len(snapshot_called) == 1
        assert snapshot_called[0] == order1.account_id


class _MultiStatusBroker:
    """여러 broker_order_id에 대해 서로 다른 status/fills를 반환하는 stub."""

    def __init__(self, entries: list[tuple[str, OrderStatus, list[FillEvent]]]) -> None:
        self._map: dict[str, tuple[OrderStatus, list[FillEvent]]] = {
            native_id: (status, fills) for native_id, status, fills in entries
        }
        self.get_order_status_call_count = 0
        self.get_fills_call_count = 0

    async def get_order_status(
        self,
        account_ref: str,
        client_order_id: str,
        broker_order_id: str,
    ) -> OrderStatusResult:
        self.get_order_status_call_count += 1
        status, _ = self._map.get(broker_order_id, (OrderStatus.SUBMITTED, []))
        return OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            status=status,
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
        _, fills = self._map.get(broker_order_id, (OrderStatus.SUBMITTED, []))
        return fills
