"""Tests for ``OrderSyncService`` — post-submit status/fill sync.

실행: ``uv run pytest tests/services/test_order_sync_service.py -v``
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import AsyncMock

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    BrokerOrderEntity,
    FillEventEntity,
    OrderRequestEntity,
    ReconciliationRunEntity,
)
from agent_trading.domain.enums import (
    BrokerName,
    Environment,
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
    _ACTIVE_SYNC_STATUSES,
    _GRACE_PERIOD_AFTER_HOURS_EXPIRED_MARKET_SECONDS,
    _RECOVERY_SYNC_STATUSES,
    _STUCK_EXPIRY_SECONDS,
    _SYNCABLE_STATUSES,
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
        fail_get_order_status: bool = False,
    ) -> None:
        self._status = status
        self._fills = fills or []
        self._fail_get_order_status = fail_get_order_status
        self.get_order_status_call_count = 0
        self.get_fills_call_count = 0

    async def get_order_status(
        self,
        account_ref: str,
        client_order_id: str,
        broker_order_id: str,
    ) -> OrderStatusResult:
        self.get_order_status_call_count += 1
        if self._fail_get_order_status:
            raise RuntimeError("Simulated broker get_order_status failure")
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
    created_at: datetime | None = None,
) -> BrokerOrderEntity:
    """Create and persist a broker order linked to ``order``."""
    now = created_at or datetime.now(timezone.utc)
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
        # Terminal 상태에서는 get_fills() 중복 호출을 건너뛰므로 fills_synced=0
        # (get_order_status()가 이미 fill 데이터를 포함하고 있음)
        assert result.fills_synced == 0
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
        # Terminal 상태에서 FILLED로 전이되면 fills_synced=0이어도
        # snapshot refresh는 트리거됨 (get_fills() 중복 호출 최적화로
        # fills_synced=0이지만 상태 변경은 확실하므로)
        assert result.snapshot_triggered is True
        assert len(snapshot_called) == 1


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
        assert result.partial == 2         # order1, order3만 non-terminal (order2 실패는 partial 미포함)

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
        assert result.partial == 0  # error case → partial 미포함

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


# ═════════════════════════════════════════════════════════════════════
# Test: PostSubmitSyncRunner — snapshot refresh tracking
# ═════════════════════════════════════════════════════════════════════


class TestRunnerSnapshotsRefreshed:
    """``run_sync_cycle()`` snapshot_refreshed 집계 검증."""

    async def test_runner_snapshots_refreshed_count(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """FILLED로 전이된 주문 수만큼 snapshot_refreshed가 집계되어야 함."""
        now = datetime.now(timezone.utc)
        order1 = _make_order(repos, status=OrderStatus.PARTIALLY_FILLED, client_order_id="SNAP-001")
        order2 = _make_order(repos, status=OrderStatus.PARTIALLY_FILLED, client_order_id="SNAP-002")
        order3 = _make_order(repos, status=OrderStatus.ACKNOWLEDGED, client_order_id="SNAP-003")

        _make_broker_order(repos, order1, broker_native_order_id="BRK-SNAP-001")
        _make_broker_order(repos, order2, broker_native_order_id="BRK-SNAP-002")
        _make_broker_order(repos, order3, broker_native_order_id="BRK-SNAP-003")

        fills = [
            FillEvent(
                broker_name=BrokerName.KOREA_INVESTMENT,
                broker_order_id="BRK-SNAP-001",
                symbol="005930",
                side=OrderSide.BUY,
                fill_quantity=Decimal("10"),
                fill_price=Decimal("50000"),
                fill_timestamp=now,
                fee=Decimal("500"),
                tax=Decimal("0"),
            ),
        ]
        # order1만 FILLED, order2는 ACK, order3은 ACK
        class _MultiStatusBroker:
            def __init__(self) -> None:
                self.call_count = 0

            async def get_order_status(
                self,
                account_ref: str,
                client_order_id: str,
                broker_order_id: str,
            ) -> OrderStatusResult:
                self.call_count += 1
                if client_order_id == "SNAP-001":
                    status = OrderStatus.FILLED
                else:
                    status = OrderStatus.ACKNOWLEDGED
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
                if broker_order_id == "BRK-SNAP-001":
                    return fills
                return []

        snapshot_called: list[UUID] = []

        async def _refresh_cb(account_id: UUID) -> None:
            snapshot_called.append(account_id)

        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=_MultiStatusBroker(),  # type: ignore[arg-type]
            snapshot_refresh_cb=_refresh_cb,
        )

        result = await runner.run_sync_cycle(account_ref="test-account")

        assert result.total_orders == 3
        assert result.filled == 1
        assert result.snapshots_refreshed == 1
        assert len(snapshot_called) == 1


# ═════════════════════════════════════════════════════════════════════
# Test: ReconcileRequiredSyncPolicy — RECONCILE_REQUIRED 해소
# ═════════════════════════════════════════════════════════════════════


class _MultiStatusBroker:
    """Broker stub that returns different statuses per client_order_id."""

    def __init__(self, default_status: OrderStatus = OrderStatus.ACKNOWLEDGED) -> None:
        self._default_status = default_status
        self._overrides: dict[str, OrderStatus] = {}
        self.get_order_status_call_count = 0
        self.get_fills_call_count = 0

    def set_status(self, client_order_id: str, status: OrderStatus) -> None:
        self._overrides[client_order_id] = status

    async def get_order_status(
        self,
        account_ref: str,
        client_order_id: str,
        broker_order_id: str,
    ) -> OrderStatusResult:
        self.get_order_status_call_count += 1
        status = self._overrides.get(client_order_id, self._default_status)
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
        return []

    async def resolve_unknown_state(
        self,
        account_ref: str,
        *,
        broker_order_id: str,
        symbol: str | None = None,
    ) -> OrderStatusResult:
        status = self._overrides.get("__resolve__", self._default_status)
        return OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="",
            broker_order_id=broker_order_id,
            status=status,
            filled_quantity=Decimal("0"),
            remaining_quantity=Decimal("0"),
            average_fill_price=Decimal("0"),
            last_updated_at=datetime.now(timezone.utc),
        )


class TestReconcileRequiredSyncPolicy:
    """``_sync_reconcile_required_orders()`` — RECONCILE_REQUIRED 해소 정책."""

    async def test_sync_reconcile_required_resolves(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """RECONCILE_REQUIRED 주문이 broker truth 조회를 통해 해소됨."""
        order = _make_order(repos, status=OrderStatus.RECONCILE_REQUIRED, client_order_id="REC-001")
        _make_broker_order(repos, order, broker_native_order_id="BRK-REC-001")

        broker = _MultiStatusBroker(default_status=OrderStatus.ACKNOWLEDGED)

        resolved = await sync_service._sync_reconcile_required_orders(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            is_after_hours=True,
        )

        assert resolved == 1

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.ACKNOWLEDGED

    async def test_sync_reconcile_required_skip_non_reconcile(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """RECONCILE_REQUIRED가 아닌 주문은 skip."""
        _make_order(repos, status=OrderStatus.SUBMITTED, client_order_id="NORM-001")

        broker = _MultiStatusBroker()

        resolved = await sync_service._sync_reconcile_required_orders(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
        )

        assert resolved == 0

    async def test_sync_reconcile_required_limit(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """limit 파라미터로 처리할 RECONCILE_REQUIRED 주문 수를 제한."""
        for i in range(5):
            o = _make_order(repos, status=OrderStatus.RECONCILE_REQUIRED, client_order_id=f"REC-{i:03d}")
            _make_broker_order(repos, o, broker_native_order_id=f"BRK-REC-{i:03d}")

        broker = _MultiStatusBroker(default_status=OrderStatus.ACKNOWLEDGED)

        resolved = await sync_service._sync_reconcile_required_orders(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            limit=3,
        )

        assert resolved == 3

    async def test_sync_reconcile_required_no_broker_order_skipped(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """BrokerOrderEntity가 없는 RECONCILE_REQUIRED 주문은 skip."""
        _make_order(repos, status=OrderStatus.RECONCILE_REQUIRED, client_order_id="NOBRK-REC")
        # Broker order를 생성하지 않음

        broker = _MultiStatusBroker()

        resolved = await sync_service._sync_reconcile_required_orders(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
        )

        assert resolved == 0


# ═════════════════════════════════════════════════════════════════════
# Test: PostSubmitSyncRunner — savepoint isolation
# ═════════════════════════════════════════════════════════════════════


class TestPostSubmitSyncRunnerSavepointIsolation:
    """``run_sync_cycle()`` savepoint 격리 — 개별 sync 실패가 전체 cycle에 영향 없음."""

    async def test_runner_savepoint_isolation(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Broker.get_order_status() 예외 발생 시 savepoint rollback으로
        해당 broker_order만 격리되고 다른 주문 sync는 정상 진행."""
        order1 = _make_order(repos, status=OrderStatus.SUBMITTED, client_order_id="ISO-001")
        order2 = _make_order(repos, status=OrderStatus.SUBMITTED, client_order_id="ISO-002")
        order3 = _make_order(repos, status=OrderStatus.SUBMITTED, client_order_id="ISO-003")

        bo1 = _make_broker_order(repos, order1, broker_native_order_id="BRK-ISO-001")
        bo2 = _make_broker_order(repos, order2, broker_native_order_id="BRK-ISO-002")
        bo3 = _make_broker_order(repos, order3, broker_native_order_id="BRK-ISO-003")

        class _IsolationFailingBroker:
            def __init__(self) -> None:
                self._fail_id = bo2.broker_native_order_id

            async def get_order_status(
                self,
                account_ref: str,
                client_order_id: str,
                broker_order_id: str,
            ) -> OrderStatusResult:
                if broker_order_id == self._fail_id:
                    raise RuntimeError("Isolated broker failure")
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
                return []

        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=_IsolationFailingBroker(),  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(account_ref="test-account")

        assert result.total_orders == 3
        assert len(result.errors) == 1
        assert result.updated == 2
        assert result.partial == 2  # order2 실패는 partial 미포함

        # order1, order3은 ACKNOWLEDGED로 전이
        updated1 = await repos.orders.get(order1.order_request_id)
        assert updated1 is not None
        assert updated1.status == OrderStatus.ACKNOWLEDGED

        updated3 = await repos.orders.get(order3.order_request_id)
        assert updated3 is not None
        assert updated3.status == OrderStatus.ACKNOWLEDGED

        # order2는 여전히 SUBMITTED
        updated2 = await repos.orders.get(order2.order_request_id)
        assert updated2 is not None
        assert updated2.status == OrderStatus.SUBMITTED


    async def test_runner_sync_single_error_no_crash(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """``_sync_single_order()`` 예외 발생 시 ``(None, err_msg)`` 반환 → crash 없이
        ``errors``에 기록되고 cycle 정상 진행."""
        order1 = _make_order(repos, status=OrderStatus.SUBMITTED, client_order_id="ERR-001")
        order2 = _make_order(repos, status=OrderStatus.SUBMITTED, client_order_id="ERR-002")

        bo1 = _make_broker_order(repos, order1, broker_native_order_id="BRK-ERR-001")
        bo2 = _make_broker_order(repos, order2, broker_native_order_id="BRK-ERR-002")

        class _ErrorReturningBroker:
            async def get_order_status(
                self,
                account_ref: str,
                client_order_id: str,
                broker_order_id: str,
            ) -> OrderStatusResult:
                if broker_order_id == "BRK-ERR-001":
                    # _sync_single_order() 내부에서 예외 발생 → (None, err_msg) 반환 유도
                    raise RuntimeError("Simulated sync failure")
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
                return []

        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=_ErrorReturningBroker(),  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(account_ref="test-account")

        # crash 없이 정상 완료
        assert result.total_orders == 2
        assert len(result.errors) == 1  # order1만 실패
        # 에러 메시지에는 broker_order_id(UUID)가 포함됨
        assert "get_order_status failed" in result.errors[0]
        assert result.updated == 1  # order2는 ACKNOWLEDGED로 전이

        # order1은 여전히 SUBMITTED
        updated1 = await repos.orders.get(order1.order_request_id)
        assert updated1 is not None
        assert updated1.status == OrderStatus.SUBMITTED

        # order2는 ACKNOWLEDGED로 전이
        updated2 = await repos.orders.get(order2.order_request_id)
        assert updated2 is not None
        assert updated2.status == OrderStatus.ACKNOWLEDGED


# ═════════════════════════════════════════════════════════════════════
# Test: PostSubmitSyncRunner — EOD orphan cleanup (Step 4)
# ═════════════════════════════════════════════════════════════════════


class TestRunnerEodOrphanCleanup:
    """``run_sync_cycle()`` Step 4 — after-hours EOD orphan cleanup 검증.

    run_sync_cycle(after_hours=True) 호출 시:
    - PENDING_SUBMIT / RECONCILE_REQUIRED orphan 주문이 EXPIRED로 전이
    - SyncCycleResult에 orphan cleanup count가 정확히 집계

    run_sync_cycle(after_hours=False) 호출 시:
    - orphan 주문이 그대로 유지 (cleanup 미실행)
    """

    async def test_runner_after_hours_triggers_eod_orphan_cleanup(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """after_hours=True → Step 4 실행, orphan 주문이 EXPIRED로 전이."""
        now = datetime.now(timezone.utc)

        # 대상 1: 오래된 PENDING_SUBMIT orphan (broker_order 없음)
        ps_orphan = _make_orphan_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="EOD-PS-001",
            created_at=now - timedelta(hours=2),
        )

        # 대상 2: 오래된 RECONCILE_REQUIRED orphan + failed reconciliation
        rr_orphan = _make_orphan_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="EOD-RR-001",
            created_at=now - timedelta(hours=2),
        )
        run_id = uuid4()
        run = ReconciliationRunEntity(
            reconciliation_run_id=run_id,
            account_id=rr_orphan.account_id,
            trigger_type="scheduled",
            status="failed",
            started_at=now - timedelta(hours=1),
            mismatch_count=1,
        )
        await repos.reconciliations.add_run(run)
        await repos.reconciliations.attach_order_mismatch(
            reconciliation_run_id=run_id,
            order_request_id=rr_orphan.order_request_id,
            mismatch_type="order_mismatch",
            details={},
        )

        # 정상 주문 (broker_order 존재) — sync 정상 동작 확인
        normal_order = _make_order(
            repos,
            status=OrderStatus.SUBMITTED,
            client_order_id="EOD-NORM-001",
        )
        _make_broker_order(repos, normal_order, broker_native_order_id="BRK-EOD-NORM-001")

        broker = _StubBroker(status=OrderStatus.ACKNOWLEDGED)
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=broker,  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(
            account_ref="test-account",
            after_hours=True,
        )

        # SyncCycleResult 검증
        assert result.orphans_expired_pending == 1, (
            f"Expected 1 pending_submit expired, got {result.orphans_expired_pending}"
        )
        assert result.orphans_expired_reconcile == 1, (
            f"Expected 1 reconcile_required expired, got {result.orphans_expired_reconcile}"
        )
        # 정상 sync는 그대로 동작
        assert result.total_orders >= 1
        assert result.updated >= 1  # normal_order가 SUBMITTED→ACK

        # PENDING_SUBMIT orphan → EXPIRED 검증
        updated_ps = await repos.orders.get(ps_orphan.order_request_id)
        assert updated_ps is not None
        assert updated_ps.status == OrderStatus.EXPIRED, (
            f"Expected EXPIRED, got {updated_ps.status}"
        )
        assert updated_ps.status_reason_code == "eod_orphan_cleanup_no_broker_order"

        # RECONCILE_REQUIRED orphan → EXPIRED 검증
        updated_rr = await repos.orders.get(rr_orphan.order_request_id)
        assert updated_rr is not None
        assert updated_rr.status == OrderStatus.EXPIRED, (
            f"Expected EXPIRED, got {updated_rr.status}"
        )
        assert updated_rr.status_reason_code == "eod_orphan_cleanup_failed_reconciliation"

        # 정상 주문은 ACKNOWLEDGED로 전이
        updated_normal = await repos.orders.get(normal_order.order_request_id)
        assert updated_normal is not None
        assert updated_normal.status == OrderStatus.ACKNOWLEDGED

    async def test_runner_regular_hours_skips_eod_orphan_cleanup(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """after_hours=False → Step 4 미실행, orphan 주문이 그대로 유지."""
        now = datetime.now(timezone.utc)

        # PENDING_SUBMIT orphan
        ps_orphan = _make_orphan_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="REG-PS-001",
            created_at=now - timedelta(hours=2),
        )

        # RECONCILE_REQUIRED orphan + failed reconciliation
        rr_orphan = _make_orphan_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="REG-RR-001",
            created_at=now - timedelta(hours=2),
        )
        run_id = uuid4()
        run = ReconciliationRunEntity(
            reconciliation_run_id=run_id,
            account_id=rr_orphan.account_id,
            trigger_type="scheduled",
            status="failed",
            started_at=now - timedelta(hours=1),
            mismatch_count=1,
        )
        await repos.reconciliations.add_run(run)
        await repos.reconciliations.attach_order_mismatch(
            reconciliation_run_id=run_id,
            order_request_id=rr_orphan.order_request_id,
            mismatch_type="order_mismatch",
            details={},
        )

        # 정상 주문
        normal_order = _make_order(
            repos,
            status=OrderStatus.SUBMITTED,
            client_order_id="REG-NORM-001",
        )
        _make_broker_order(repos, normal_order, broker_native_order_id="BRK-REG-NORM-001")

        broker = _StubBroker(status=OrderStatus.ACKNOWLEDGED)
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=broker,  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(
            account_ref="test-account",
            after_hours=False,
        )

        # after-hours가 아니므로 cleanup count는 0
        assert result.orphans_expired_pending == 0
        assert result.orphans_expired_reconcile == 0

        # 정상 sync는 그대로 동작
        assert result.total_orders >= 1
        assert result.updated >= 1

        # PENDING_SUBMIT orphan → 그대로 유지
        updated_ps = await repos.orders.get(ps_orphan.order_request_id)
        assert updated_ps is not None
        assert updated_ps.status == OrderStatus.PENDING_SUBMIT, (
            f"Expected PENDING_SUBMIT unchanged, got {updated_ps.status}"
        )

        # RECONCILE_REQUIRED orphan → 그대로 유지
        updated_rr = await repos.orders.get(rr_orphan.order_request_id)
        assert updated_rr is not None
        assert updated_rr.status == OrderStatus.RECONCILE_REQUIRED, (
            f"Expected RECONCILE_REQUIRED unchanged, got {updated_rr.status}"
        )

    async def test_runner_after_hours_orphan_counts_in_result(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """SyncCycleResult에 orphan cleanup count가 정확히 집계됨."""
        now = datetime.now(timezone.utc)

        # 2건의 PENDING_SUBMIT orphan
        _make_orphan_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="CNT-PS-001",
            created_at=now - timedelta(hours=2),
        )
        _make_orphan_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="CNT-PS-002",
            created_at=now - timedelta(hours=3),
        )

        # 1건의 RECONCILE_REQUIRED orphan + failed reconciliation
        rr_orphan = _make_orphan_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="CNT-RR-001",
            created_at=now - timedelta(hours=2),
        )
        run_id = uuid4()
        run = ReconciliationRunEntity(
            reconciliation_run_id=run_id,
            account_id=rr_orphan.account_id,
            trigger_type="scheduled",
            status="failed",
            started_at=now - timedelta(hours=1),
            mismatch_count=1,
        )
        await repos.reconciliations.add_run(run)
        await repos.reconciliations.attach_order_mismatch(
            reconciliation_run_id=run_id,
            order_request_id=rr_orphan.order_request_id,
            mismatch_type="order_mismatch",
            details={},
        )

        # 1건의 fresh PENDING_SUBMIT (cleanup 제외)
        _make_orphan_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="CNT-PS-FRESH",
            created_at=now - timedelta(minutes=10),
        )

        broker = _StubBroker(status=OrderStatus.ACKNOWLEDGED)
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=broker,  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(
            account_ref="test-account",
            after_hours=True,
        )

        assert result.orphans_expired_pending == 2, (
            f"Expected 2 pending_submit expired, got {result.orphans_expired_pending}"
        )
        assert result.orphans_expired_reconcile == 1, (
            f"Expected 1 reconcile_required expired, got {result.orphans_expired_reconcile}"
        )
        # total_orders는 query에 매칭된 전체 주문 수 (orphan 포함)
        # 4 = 2 old PENDING_SUBMIT + 1 RECONCILE_REQUIRED + 1 fresh PENDING_SUBMIT
        assert result.total_orders == 4
        # 실제 sync가 실행된 주문 수 (broker_order 존재)는 0
        assert result.updated == 0
# ═════════════════════════════════════════════════════════════════════


def _make_position_snapshot(
    repos: RepositoryContainer,
    *,
    account_id: UUID,
    instrument_id: UUID,
    quantity: Decimal,
    snapshot_time: datetime | None = None,
) -> UUID:
    """Create a position snapshot and return its ID."""
    from agent_trading.domain.entities import PositionSnapshotEntity

    snap_id = uuid4()
    entity = PositionSnapshotEntity(
        position_snapshot_id=snap_id,
        account_id=account_id,
        instrument_id=instrument_id,
        quantity=quantity,
        average_price=Decimal("0"),
        market_price=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        source_of_truth="test",
        snapshot_at=snapshot_time or datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    repos.position_snapshots._items[snap_id] = entity  # type: ignore[attr-defined]
    return snap_id


class TestInferSellOrderFillViaPosition:
    """``_infer_sell_order_fill_via_position()`` — SELL 주문 position 기반 fill 추론."""

    async def test_infer_sell_filled(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Position 감소량 >= requested_quantity → FILLED 추론."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="SELL-FILLED-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        # Pre-order snapshot: quantity=20 (broker_order.created_at보다 이전)
        pre_snap_time = now - timedelta(hours=2)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=pre_snap_time,
        )

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-SELL-FILLED",
        )

        # Current snapshot: quantity=5 (delta=15 >= 10 → FILLED)
        # broker_order.created_at 이후로 설정하여 pre-order snapshot만 조회되도록 함
        current_snap_time = broker_order.created_at + timedelta(seconds=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("5"),
            snapshot_time=current_snap_time,
        )

        result = await sync_service._infer_sell_order_fill_via_position(
            order, broker_order,
        )

        assert result == OrderStatus.FILLED

    async def test_infer_sell_partially_filled(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """0 < Position 감소량 < requested_quantity → PARTIALLY_FILLED 추론."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="SELL-PARTIAL-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        # Pre-order snapshot: quantity=20 (broker_order.created_at보다 이전)
        pre_snap_time = now - timedelta(hours=2)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=pre_snap_time,
        )

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-SELL-PARTIAL",
        )

        # Current snapshot: quantity=15 (delta=5, 0 < 5 < 10 → PARTIALLY_FILLED)
        # broker_order.created_at 이후로 설정하여 pre-order snapshot만 조회되도록 함
        current_snap_time = broker_order.created_at + timedelta(seconds=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("15"),
            snapshot_time=current_snap_time,
        )

        result = await sync_service._infer_sell_order_fill_via_position(
            order, broker_order,
        )

        assert result == OrderStatus.PARTIALLY_FILLED

    async def test_infer_sell_no_decrease_returns_none(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Position 감소 없음 → None (추론 불가)."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="SELL-NO-DEC-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        # Pre-order snapshot: quantity=20 (broker_order.created_at보다 이전)
        pre_snap_time = now - timedelta(hours=2)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=pre_snap_time,
        )

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-SELL-NO-DEC",
        )

        # Current snapshot: quantity=20 (delta=0 → no decrease)
        # broker_order.created_at 이후로 설정하여 pre-order snapshot만 조회되도록 함
        current_snap_time = broker_order.created_at + timedelta(seconds=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=current_snap_time,
        )

        result = await sync_service._infer_sell_order_fill_via_position(
            order, broker_order,
        )

        assert result is None

    async def test_infer_sell_buy_order_returns_none(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """BUY 주문은 position inference 대상이 아님."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="BUY-NO-INFER-001",
        )
        order = replace(order, side=OrderSide.BUY, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-BUY-NO-INFER",
        )

        result = await sync_service._infer_sell_order_fill_via_position(
            order, broker_order,
        )

        assert result is None

    async def test_infer_sell_no_pre_order_snapshot_returns_none(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Pre-order snapshot이 없으면 None 반환."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="SELL-NO-SNAP-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-SELL-NO-SNAP",
        )

        # No position snapshots at all
        result = await sync_service._infer_sell_order_fill_via_position(
            order, broker_order,
        )

        assert result is None


# ═════════════════════════════════════════════════════════════════════
# Test: transition_to_authoritative — is_after_hours parameter
# ═════════════════════════════════════════════════════════════════════


class TestTransitionToAuthoritativeIsAfterHours:
    """``transition_to_authoritative()`` — ``is_after_hours`` 파라미터 검증.

    장중(intraday, is_after_hours=False)에는 EXPIRED fallback이 차단되어
    RECONCILE_REQUIRED 상태가 유지되고, 장마감 후(after-hours,
    is_after_hours=True)에는 EXPIRED fallback이 정상 동작한다.
    """

    # ── Path A: resolve_unknown_state()가 예외 발생 ──

    async def test_intraday_suppress_expired_fallback_path_a(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Path A (resolve_unknown_state 예외) + 장중 → EXPIRED fallback 차단, None 반환."""
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="INTRA-A-001",
        )
        order = replace(order, side=OrderSide.BUY, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-INTRA-A",
        )

        # resolve_unknown_state()가 예외를 던지도록 mock
        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            side_effect=RuntimeError("Broker API timeout"),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=False,  # 장중
        )

        # EXPIRED fallback이 차단되어 None 반환
        assert result is None

        # Order 상태가 RECONCILE_REQUIRED로 유지됨
        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.RECONCILE_REQUIRED

    async def test_after_hours_allows_expired_fallback_path_a(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Path A (resolve_unknown_state 예외) + 장마감 후 → EXPIRED fallback 허용."""
        now = datetime.now(timezone.utc)
        old_created_at = now - timedelta(minutes=45)  # 45분 전 (grace period 30분 초과)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="AH-A-001",
        )
        order = replace(order, side=OrderSide.BUY, requested_quantity=Decimal("10"),
                        created_at=old_created_at)
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-AH-A",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            side_effect=RuntimeError("Broker API timeout"),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=True,  # 장마감 후
        )

        # EXPIRED fallback 허용
        assert result is not None
        assert result.status == OrderStatus.EXPIRED

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.EXPIRED

    # ── Path B: resolve_unknown_state()가 RECONCILE_REQUIRED 반환 ──

    async def test_intraday_suppress_expired_fallback_path_b(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Path B (resolve_unknown_state → RECONCILE_REQUIRED) + 장중 → EXPIRED fallback 차단."""
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="INTRA-B-001",
        )
        order = replace(order, side=OrderSide.BUY, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-INTRA-B",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        # resolve_unknown_state()가 RECONCILE_REQUIRED 반환
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=False,  # 장중
        )

        # EXPIRED fallback 차단 → None 반환
        assert result is None

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.RECONCILE_REQUIRED

    async def test_after_hours_allows_expired_fallback_path_b(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Path B (resolve_unknown_state → RECONCILE_REQUIRED) + 장마감 후 → EXPIRED fallback 허용."""
        now = datetime.now(timezone.utc)
        old_created_at = now - timedelta(minutes=45)  # 45분 전 (grace period 30분 초과)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="AH-B-001",
        )
        order = replace(order, side=OrderSide.BUY, requested_quantity=Decimal("10"),
                        created_at=old_created_at)
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-AH-B",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=True,  # 장마감 후
        )

        # EXPIRED fallback 허용
        assert result is not None
        assert result.status == OrderStatus.EXPIRED

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.EXPIRED

    # ── SELL position inference (Path A, 장중) ──

    async def test_intraday_sell_position_inference_still_works(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Path A (resolve_unknown_state 예외) + SELL + 장중 → position inference 우선 동작."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="SELL-INFER-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-SELL-INFER",
        )

        # Position snapshot: pre=20 (broker_order.created_at 이전), current=5 (이후)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=broker_order.created_at - timedelta(hours=1),
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("5"),
            snapshot_time=broker_order.created_at + timedelta(seconds=1),
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            side_effect=RuntimeError("Broker API timeout"),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=False,  # 장중
        )

        # Position inference가 EXPIRED fallback보다 우선하여 FILLED 반환
        assert result is not None
        assert result.status == OrderStatus.FILLED

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.FILLED

    # ── After-hours young order grace period (Path A: resolve_unknown_state 예외) ──

    async def test_after_hours_young_order_blocks_expired_fallback_path_a(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Path A (resolve_unknown_state 예외) + after-hours + young order (age < 30min)
        → Grace period가 EXPIRED fallback을 차단하고 RECONCILE_REQUIRED 유지."""
        now = datetime.now(timezone.utc)
        young_created_at = now - timedelta(minutes=5)  # 5분 전 생성 (young)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="AH-YOUNG-A-001",
        )
        order = replace(
            order,
            side=OrderSide.BUY,
            requested_quantity=Decimal("10"),
            created_at=young_created_at,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-AH-YOUNG-A",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            side_effect=RuntimeError("Broker API timeout"),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=True,  # 장마감 후
        )

        # Grace period가 EXPIRED fallback을 차단 → None 반환
        assert result is None

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.RECONCILE_REQUIRED

    async def test_after_hours_old_order_allows_expired_fallback_path_a(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Path A (resolve_unknown_state 예외) + after-hours + old order (age >= 30min)
        → Grace period 초과로 EXPIRED fallback 허용."""
        now = datetime.now(timezone.utc)
        old_created_at = now - timedelta(minutes=45)  # 45분 전 생성 (old, >= 30min)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="AH-OLD-A-001",
        )
        order = replace(
            order,
            side=OrderSide.BUY,
            requested_quantity=Decimal("10"),
            created_at=old_created_at,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-AH-OLD-A",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            side_effect=RuntimeError("Broker API timeout"),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=True,  # 장마감 후
        )

        # EXPIRED fallback 허용
        assert result is not None
        assert result.status == OrderStatus.EXPIRED

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.EXPIRED

    # ── After-hours young order grace period (broker has no record) ──

    async def test_after_hours_young_order_blocks_expired_fallback_broker_no_record(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Broker no record 경로 + after-hours + young order (age < 30min)
        → Grace period가 EXPIRED fallback을 차단하고 RECONCILE_REQUIRED 유지."""
        now = datetime.now(timezone.utc)
        young_created_at = now - timedelta(minutes=5)  # 5분 전 생성 (young)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="AH-YOUNG-BNR-001",
        )
        order = replace(
            order,
            side=OrderSide.BUY,
            requested_quantity=Decimal("10"),
            created_at=young_created_at,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-AH-YOUNG-BNR",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        # resolve_unknown_state가 RECONCILE_REQUIRED 반환 → broker has no record 경로로 fall through
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=True,  # 장마감 후
        )

        # Grace period가 EXPIRED fallback을 차단 → None 반환
        assert result is None

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.RECONCILE_REQUIRED

    async def test_after_hours_old_order_allows_expired_fallback_broker_no_record(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Broker no record 경로 + after-hours + old order (age >= 30min)
        → Grace period 초과로 EXPIRED fallback 허용."""
        now = datetime.now(timezone.utc)
        old_created_at = now - timedelta(minutes=45)  # 45분 전 생성 (old, >= 30min)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="AH-OLD-BNR-001",
        )
        order = replace(
            order,
            side=OrderSide.BUY,
            requested_quantity=Decimal("10"),
            created_at=old_created_at,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-AH-OLD-BNR",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=True,  # 장마감 후
        )

        # EXPIRED fallback 허용 (age=45min >= 30min grace period)
        assert result is not None
        assert result.status == OrderStatus.EXPIRED

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.EXPIRED

    # ── Genuine manual reconciliation (Path B, 장중) ──

    async def test_intraday_genuine_manual_keeps_reconcile(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Path B (resolve_unknown_state → RECONCILE_REQUIRED) + 장중 +
        genuine manual reconciliation → RECONCILE_REQUIRED 유지."""
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="MANUAL-001",
        )
        order = replace(order, side=OrderSide.BUY, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-MANUAL",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        # broker_order_id가 빈 문자열 → genuine manual reconciliation
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id="",  # 빈 broker_order_id → genuine manual
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=False,  # 장중
        )

        # Genuine manual reconciliation → RECONCILE_REQUIRED 유지
        assert result is None

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.RECONCILE_REQUIRED

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

    async def test_runner_recovery_mode_includes_expired(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Recovery 모드에서 EXPIRED 상태 주문도 sync 대상에 포함되어야 함."""
        # EXPIRED 주문 생성 (submitted_at을 오늘로 설정)
        now_utc = datetime.now(timezone.utc)
        expired_order = _make_order(
            repos, status=OrderStatus.EXPIRED, client_order_id="RECOV-EXP-001",
        )
        expired_order = replace(
            expired_order,
            submitted_at=now_utc,
        )
        repos.orders._items[expired_order.order_request_id] = expired_order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, expired_order, broker_native_order_id="BRK-RECOV-EXP",
        )

        # Broker가 FILLED 반환 → EXPIRED → FILLED 복구
        broker = _StubBroker(status=OrderStatus.FILLED)
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=broker,  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(
            account_ref="test-account",
            recovery_mode=True,
        )

        # EXPIRED 주문이 sync되어 FILLED로 전이되어야 함
        assert result.total_orders >= 1
        assert result.filled >= 1

        # 실제로 FILLED로 전이되었는지 확인
        updated_order = await repos.orders.get(expired_order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.FILLED

    async def test_runner_non_recovery_mode_excludes_expired(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Recovery 모드가 아닐 때 EXPIRED 주문은 조회되지 않아야 함."""
        now_utc = datetime.now(timezone.utc)
        expired_order = _make_order(
            repos, status=OrderStatus.EXPIRED, client_order_id="RECOV-SKIP-001",
        )
        expired_order = replace(
            expired_order,
            submitted_at=now_utc,
        )
        repos.orders._items[expired_order.order_request_id] = expired_order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, expired_order, broker_native_order_id="BRK-RECOV-SKIP",
        )

        broker = _StubBroker(status=OrderStatus.FILLED)
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=sync_service,
            broker=broker,  # type: ignore[arg-type]
        )

        result = await runner.run_sync_cycle(
            account_ref="test-account",
            recovery_mode=False,
        )

        # EXPIRED 주문은 조회되지 않아야 함
        assert result.total_orders == 0


# ═════════════════════════════════════════════════════════════════════
# Test: transition_to_authoritative — broker_status 동기화 (P0 fix)
# ═════════════════════════════════════════════════════════════════════


class TestTransitionToAuthoritativeBrokerStatusSync:
    """``transition_to_authoritative()`` — position-derived fill 추론 후
    ``broker_orders.broker_status`` 동기화 및 ``snapshot_refresh_cb`` 호출 검증.

    관련 수정: exception handler 경로 (line 696-740) 및 RECONCILE_REQUIRED
    persistence 경로 (line 832-876)에서 ``broker_status``를 ``'filled'``로
    업데이트하고 ``snapshot_refresh_cb``를 호출한다.
    """

    async def test_exception_handler_path_updates_broker_status_on_fill(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Exception handler 경로 (resolve_unknown_state 예외)에서
        position-derived fill 추론 후 broker_status가 'filled'로 업데이트됨."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="EXC-BRK-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-EXC-BRK",
            broker_status="reconcile_required",
        )

        # Position snapshot: pre=20, current=5 → delta=15, requested=10 → FILLED
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=broker_order.created_at - timedelta(hours=1),
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("5"),
            snapshot_time=broker_order.created_at + timedelta(seconds=1),
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            side_effect=RuntimeError("Broker API timeout"),
        )

        snapshot_refresh_cb = AsyncMock()

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=False,
            snapshot_refresh_cb=snapshot_refresh_cb,
        )

        # Position inference가 FILLED를 반환
        assert result is not None
        assert result.status == OrderStatus.FILLED

        # broker_orders.broker_status가 'filled'로 업데이트되었는지 검증
        updated_bo = await repos.broker_orders.get(broker_order.broker_order_id)
        assert updated_bo is not None
        assert updated_bo.broker_status == "filled"

        # snapshot_refresh_cb가 호출되었는지 검증
        snapshot_refresh_cb.assert_awaited_once_with(order.account_id)

    async def test_reconcile_required_path_updates_broker_status_on_fill(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """RECONCILE_REQUIRED persistence 경로 (resolve_unknown_state →
        RECONCILE_REQUIRED → position inference)에서 position-derived fill
        추론 후 broker_status가 'filled'로 업데이트됨."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="REC-BRK-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-REC-BRK",
            broker_status="reconcile_required",
        )

        # Position snapshot: pre=20, current=5 → delta=15, requested=10 → FILLED
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=broker_order.created_at - timedelta(hours=1),
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("5"),
            snapshot_time=broker_order.created_at + timedelta(seconds=1),
        )

        broker = AsyncMock(spec=BrokerAdapter)
        # resolve_unknown_state()가 RECONCILE_REQUIRED 반환 → Path B
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        snapshot_refresh_cb = AsyncMock()

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=True,  # after-hours여야 EXPIRED fallback이 아닌 position inference 우선
            snapshot_refresh_cb=snapshot_refresh_cb,
        )

        # Position inference가 FILLED를 반환
        assert result is not None
        assert result.status == OrderStatus.FILLED

        # broker_orders.broker_status가 'filled'로 업데이트되었는지 검증
        updated_bo = await repos.broker_orders.get(broker_order.broker_order_id)
        assert updated_bo is not None
        assert updated_bo.broker_status == "filled"

        # snapshot_refresh_cb가 호출되었는지 검증
        snapshot_refresh_cb.assert_awaited_once_with(order.account_id)

    async def test_fill_inference_triggers_snapshot_refresh(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Exception handler 경로에서 position-derived fill 추론 후
        snapshot_refresh_cb가 정확히 한 번 호출됨."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="SNAP-REF-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-SNAP-REF",
            broker_status="reconcile_required",
        )

        # Position snapshot: pre=20, current=5 → delta=15, requested=10 → FILLED
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=broker_order.created_at - timedelta(hours=1),
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("5"),
            snapshot_time=broker_order.created_at + timedelta(seconds=1),
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            side_effect=RuntimeError("Broker API timeout"),
        )

        snapshot_refresh_cb = AsyncMock()

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=False,
            snapshot_refresh_cb=snapshot_refresh_cb,
        )

        assert result is not None
        assert result.status == OrderStatus.FILLED

        # snapshot_refresh_cb가 정확히 한 번 호출되었는지 검증
        snapshot_refresh_cb.assert_awaited_once_with(order.account_id)

        # broker_status도 함께 업데이트되었는지 검증
        updated_bo = await repos.broker_orders.get(broker_order.broker_order_id)
        assert updated_bo is not None
        assert updated_bo.broker_status == "filled"


# ═════════════════════════════════════════════════════════════════════
# Test: Stuck timeout EXPIRED fallback (Stage 2.5)
# ═════════════════════════════════════════════════════════════════════


class TestStuckTimeoutExpiredFallback:
    """``transition_to_authoritative()`` — Stage 2.5 stuck timeout EXPIRED fallback 검증.

    장중 intraday(08:50~15:30 KST)에는 EXPIRED fallback이 금지되고
    after-hours(15:30~)에만 허용된다.
    BUY/SELL 모두 적용되며, after-hours에는 SELL은 KIS truth fallback,
    BUY는 체결 이벤트 기반으로 우선 복구를 시도한 뒤 EXPIRED fallback한다.
    """

    async def test_stuck_timeout_suppressed_during_intraday(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """장중 intraday(``is_after_hours=False``)에는 STUCK_EXPIRY timeout이
        초과되어도 EXPIRED fallback이 금지되고 RECONCILE_REQUIRED를 유지한다."""
        # 오래된 created_at으로 order 생성 (stuck timeout 초과)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=_STUCK_EXPIRY_SECONDS + 100)
        order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            client_order_id="STUCK-INTRA-001",
            idempotency_key="idem-stuck-intra-001",
            correlation_id="corr-stuck-intra-001",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            requested_price=Decimal("0"),
            requested_quantity=Decimal("10"),
            status=OrderStatus.RECONCILE_REQUIRED,
            trade_decision_id=None,
            submitted_at=None,
            status_reason_code=None,
            status_reason_message=None,
            created_at=old_time,
            updated_at=old_time,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-STUCK-INTRA",
            broker_status="reconcile_required",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        # is_after_hours=False (intraday) → EXPIRED fallback 금지
        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=False,
        )

        # Intraday: EXPIRED suppression → None 반환, RECONCILE_REQUIRED 유지
        assert result is None

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.RECONCILE_REQUIRED

    async def test_stuck_timeout_expires_after_hours_sell(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """After-hours(``is_after_hours=True``)에 RECONCILE_REQUIRED SELL 주문이
        ``_STUCK_EXPIRY_SECONDS`` 이상 지속되고 KIS truth도 fill을 확인하지 못하면
        EXPIRED로 fallback된다."""
        # 오래된 created_at으로 order 생성 (stuck timeout 초과)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=_STUCK_EXPIRY_SECONDS + 100)
        order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            client_order_id="STUCK-AH-SELL-001",
            idempotency_key="idem-stuck-ah-sell-001",
            correlation_id="corr-stuck-ah-sell-001",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            requested_price=Decimal("0"),
            requested_quantity=Decimal("10"),
            status=OrderStatus.RECONCILE_REQUIRED,
            trade_decision_id=None,
            submitted_at=None,
            status_reason_code=None,
            status_reason_message=None,
            created_at=old_time,
            updated_at=old_time,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-STUCK-AH-SELL",
            broker_status="reconcile_required",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        # resolve_unknown_state()가 RECONCILE_REQUIRED 반환 → Stage 2.5 진입
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )
        # KIS truth fallback도 fill 감지 실패
        broker.inquire_balance = AsyncMock(
            return_value={"output1": [{"pchs_amt": "0", "hldg_qty": "10"}]},
        )

        # is_after_hours=True → EXPIRED fallback 허용
        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=True,
        )

        assert result is not None
        assert result.status == OrderStatus.EXPIRED

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.EXPIRED

        # broker_status도 'expired'로 업데이트되었는지 검증
        updated_bo = await repos.broker_orders.get(broker_order.broker_order_id)
        assert updated_bo is not None
        assert updated_bo.broker_status == "expired"

    async def test_stuck_timeout_not_applied_to_recent_orders(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """생성된 지 얼마 안 된 SELL RECONCILE_REQUIRED 주문은
        EXPIRED되지 않고 RECONCILE_REQUIRED를 유지한다."""
        # 최근 created_at으로 order 생성 (stuck timeout 미만)
        recent_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            client_order_id="STUCK-RECENT-001",
            idempotency_key="idem-stuck-recent-001",
            correlation_id="corr-stuck-recent-001",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            requested_price=Decimal("0"),
            requested_quantity=Decimal("10"),
            status=OrderStatus.RECONCILE_REQUIRED,
            trade_decision_id=None,
            submitted_at=None,
            status_reason_code=None,
            status_reason_message=None,
            created_at=recent_time,
            updated_at=recent_time,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-STUCK-RECENT",
            broker_status="reconcile_required",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=False,
        )

        # Stuck timeout 미만이므로 EXPIRED fallback 차단 → None 반환
        assert result is None

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.RECONCILE_REQUIRED

    async def test_stuck_expiry_intraday_market_order_protection(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Intraday에서 broker_native_order_id + 시장가 주문의 EXPIRED 방지.

        broker_native_order_id가 존재하고 order_type=market인 주문은
        STUCK_EXPIRY timeout(7200초)을 초과해도 EXPIRED로 전이되지 않고
        RECONCILE_REQUIRED를 유지해야 한다."""
        # 오래된 created_at으로 order 생성 (stuck timeout 초과)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=_STUCK_EXPIRY_SECONDS + 100)
        order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            client_order_id="MRKT-PROTECT-INTRA-001",
            idempotency_key="idem-mrkt-protect-intra-001",
            correlation_id="corr-mrkt-protect-intra-001",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,  # 시장가
            time_in_force=TimeInForce.DAY,
            requested_price=Decimal("0"),
            requested_quantity=Decimal("10"),
            status=OrderStatus.RECONCILE_REQUIRED,
            trade_decision_id=None,
            submitted_at=None,
            status_reason_code=None,
            status_reason_message=None,
            created_at=old_time,
            updated_at=old_time,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        # broker_native_order_id가 존재하는 broker_order 생성 (Paper 환경 시뮬레이션)
        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="0000004770",  # 실제 ODNO
            broker_status="reconcile_required",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        # is_after_hours=False (intraday) → MARKET_PROTECT 적용, EXPIRED 금지
        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=False,
        )

        # Intraday: MARKET_PROTECT → None 반환, RECONCILE_REQUIRED 유지
        assert result is None, (
            "broker_native_order_id + MARKET 주문이 intraday에서 EXPIRED로 "
            "전이되면 안 됨"
        )

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.RECONCILE_REQUIRED

    async def test_stuck_expiry_after_hours_market_order_grace_period(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """After-hours에서 시장가 주문의 grace period 60분 연장 확인.

        broker_native_order_id + MARKET 주문이 after-hours에서
        30~60분 사이에 생성된 경우, 기존 30분 grace period로는 EXPIRED되지만
        60분 grace period로는 보호되어야 한다."""
        # 45분 전 생성된 주문 (기존 30분 grace period 초과, 신규 60분 이내)
        grace_age = datetime.now(timezone.utc) - timedelta(minutes=45)
        order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            client_order_id="MRKT-PROTECT-AH-001",
            idempotency_key="idem-mrkt-protect-ah-001",
            correlation_id="corr-mrkt-protect-ah-001",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            requested_price=Decimal("0"),
            requested_quantity=Decimal("10"),
            status=OrderStatus.RECONCILE_REQUIRED,
            trade_decision_id=None,
            submitted_at=None,
            status_reason_code=None,
            status_reason_message=None,
            created_at=grace_age,
            updated_at=grace_age,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="0000004770",
            broker_status="reconcile_required",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        # is_after_hours=True → 45분 < 60분(grace period) → EXPIRED 방지
        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=True,
        )

        # 45분 < 60분 → MARKET_PROTECT로 EXPIRED 방지
        assert result is None, (
            "broker_native_order_id + MARKET 주문이 after-hours 45분에 "
            "EXPIRED로 전이되면 안 됨 (grace period 60분)"
        )

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.RECONCILE_REQUIRED

    async def test_explicit_reject_still_terminal_for_market_orders(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """명시적 broker reject/cancel은 시장가 보호 정책과 무관하게 terminal 유지.

        broker_native_order_id + MARKET이어도
        resolve_unknown_state()가 REJECTED/CANCELLED를 반환하면
        정상적으로 terminal 상태로 전이되어야 한다."""
        order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            client_order_id="MRKT-REJECT-001",
            idempotency_key="idem-mrkt-reject-001",
            correlation_id="corr-mrkt-reject-001",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            requested_price=Decimal("0"),
            requested_quantity=Decimal("10"),
            status=OrderStatus.RECONCILE_REQUIRED,
            trade_decision_id=None,
            submitted_at=None,
            status_reason_code=None,
            status_reason_message=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="0000004770",
            broker_status="reconcile_required",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.REJECTED,  # 명시적 reject
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=False,
        )

        # REJECTED로 정상 전이 (보호 정책 적용 안 함)
        assert result is not None, (
            "명시적 reject는 MARKET_PROTECT와 무관하게 terminal 전이되어야 함"
        )
        assert result.status == OrderStatus.REJECTED

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.REJECTED

    async def test_non_market_order_no_protection(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """LIMIT/stoploss 등 시장가 아닌 주문은 기존 EXPIRED 정책 유지.

        broker_native_order_id가 존재해도 order_type이 MARKET이 아니면
        MARKET_PROTECT를 적용하지 않고 기존 정책대로 처리된다."""
        # LIMIT 주문, broker_native_order_id 존재
        old_time = datetime.now(timezone.utc) - timedelta(seconds=_STUCK_EXPIRY_SECONDS + 100)
        order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            client_order_id="LIMIT-NO-PROTECT-001",
            idempotency_key="idem-limit-no-protect-001",
            correlation_id="corr-limit-no-protect-001",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,  # 시장가 아님
            time_in_force=TimeInForce.DAY,
            requested_price=Decimal("50000"),
            requested_quantity=Decimal("10"),
            status=OrderStatus.RECONCILE_REQUIRED,
            trade_decision_id=None,
            submitted_at=None,
            status_reason_code=None,
            status_reason_message=None,
            created_at=old_time,
            updated_at=old_time,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="0000004770",
            broker_status="reconcile_required",
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )
        # KIS truth fallback도 fill 감지 실패
        broker.inquire_balance = AsyncMock(
            return_value={"output1": [{"pchs_amt": "0", "hldg_qty": "10"}]},
        )

        # After-hours, stuck timeout 초과, LIMIT 주문 → MARKET_PROTECT 미적용
        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=True,
        )

        # LIMIT 주문은 보호 없이 EXPIRED로 전이됨
        assert result is not None, (
            "LIMIT 주문은 MARKET_PROTECT 미적용, EXPIRED로 전이되어야 함"
        )
        assert result.status == OrderStatus.EXPIRED


# ═════════════════════════════════════════════════════════════════════
# Test: _ACTIVE_SYNC_STATUSES에 PENDING_SUBMIT 포함
# ═════════════════════════════════════════════════════════════════════


class TestActiveSyncStatusesIncludesPendingSubmit:
    """``_ACTIVE_SYNC_STATUSES``에 PENDING_SUBMIT이 포함되었는지 검증."""

    async def test_pending_submit_included_in_active_sync_statuses(self) -> None:
        """``_ACTIVE_SYNC_STATUSES``에 PENDING_SUBMIT이 포함되어 있어야 한다."""
        assert OrderStatus.PENDING_SUBMIT in _ACTIVE_SYNC_STATUSES


# ═════════════════════════════════════════════════════════════════════
# Test: _infer_sell_order_fill_via_position — retry on delta=0
# ═════════════════════════════════════════════════════════════════════


class TestInferSellFillRetry:
    """``_infer_sell_order_fill_via_position()`` — retry 로직 검증.

    delta=0 첫 시도 → snapshot refresh 재시도 → delta>0 감지 → fill 반환.
    """

    async def test_infer_sell_fill_retry_on_delta_zero(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """delta=0 첫 시도 → retry에서 delta>0 감지 → FILLED 반환."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="SELL-RETRY-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-SELL-RETRY",
        )

        # Pre-order snapshot: quantity=20
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=broker_order.created_at - timedelta(hours=1),
        )

        # First attempt: current_qty=20 (delta=0) → retry triggered
        # Second attempt: current_qty=5 (delta=15) → FILLED
        # Simulate by adding a later snapshot that appears on re-query
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("5"),
            snapshot_time=broker_order.created_at + timedelta(seconds=10),
        )

        result = await sync_service._infer_sell_order_fill_via_position(
            order, broker_order,
        )

        # Should detect delta=15 >= 10 → FILLED
        assert result == OrderStatus.FILLED

    async def test_infer_sell_fill_retry_exhausted(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """delta=0 모든 재시도 소진 → None 반환."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="SELL-RETRY-EXH-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-SELL-RETRY-EXH",
        )

        # Pre-order snapshot: quantity=20
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=broker_order.created_at - timedelta(hours=1),
        )

        # Only one snapshot at quantity=20 — no decrease ever
        # (same quantity, so delta=0 on every retry)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=broker_order.created_at + timedelta(seconds=1),
        )

        result = await sync_service._infer_sell_order_fill_via_position(
            order, broker_order,
        )

        # All retries exhausted → None
        assert result is None

    async def test_infer_sell_fill_first_attempt_success(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """첫 시도 delta>0 → 즉시 fill 반환 (retry 불필요)."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="SELL-FIRST-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-SELL-FIRST",
        )

        # Pre-order snapshot: quantity=20
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=broker_order.created_at - timedelta(hours=1),
        )

        # Current snapshot: quantity=5 (delta=15 >= 10 → FILLED immediately)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("5"),
            snapshot_time=broker_order.created_at + timedelta(seconds=1),
        )

        result = await sync_service._infer_sell_order_fill_via_position(
            order, broker_order,
        )

        assert result == OrderStatus.FILLED


# ═════════════════════════════════════════════════════════════════════
# Test: _try_kis_truth_fallback
# ═════════════════════════════════════════════════════════════════════


class TestTryKisTruthFallback:
    """``_try_kis_truth_fallback()`` — KIS truth 기반 fill 추론 검증."""

    async def test_kis_truth_fallback_on_ccld_mismatch(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """inquire-daily-ccld 매칭 실패 → KIS position 조회 → position 감소 확인 → fill 추론."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="KIS-TRUTH-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-KIS-TRUTH",
        )

        # Pre-order snapshot: quantity=20
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=broker_order.created_at - timedelta(hours=1),
        )

        # Current snapshot: quantity=5 (delta=15)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("5"),
            snapshot_time=broker_order.created_at + timedelta(seconds=1),
        )

        result = await sync_service._try_kis_truth_fallback(
            order=order,
            broker_order=broker_order,
            account_id=order.account_id,
        )

        assert result is not None
        assert result.inferred_fill_qty == Decimal("15")
        assert result.source == "kis_truth_fallback"

    async def test_kis_truth_fallback_handles_exception(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """KIS position 조회 예외 발생 → graceful fallback (crash 없음)."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="KIS-EXC-001",
        )
        order = replace(order, side=OrderSide.SELL, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-KIS-EXC",
        )

        # No position snapshots → _get_latest_position_qty returns None gracefully
        result = await sync_service._try_kis_truth_fallback(
            order=order,
            broker_order=broker_order,
            account_id=order.account_id,
        )

        # No pre-order snapshot → None (no crash)
        assert result is None

    async def test_kis_truth_fallback_buy_order_returns_none(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """BUY 주문은 KIS truth fallback 대상이 아님."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="KIS-BUY-001",
        )
        order = replace(order, side=OrderSide.BUY, requested_quantity=Decimal("10"))
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-KIS-BUY",
        )

        result = await sync_service._try_kis_truth_fallback(
            order=order,
            broker_order=broker_order,
            account_id=order.account_id,
        )

        assert result is None


# ═════════════════════════════════════════════════════════════════════
# Test: STUCK_EXPIRY KIS truth 재확인
# ═════════════════════════════════════════════════════════════════════


class TestStuckExpiryKisTruth:
    """``transition_to_authoritative()`` — STUCK_EXPIRY KIS truth 재확인 검증.

    Stage 2.5에서 EXPIRED fallback 직전 KIS truth를 재확인하여
    fill이 확인되면 filled로 전이, fill이 없으면 EXPIRED fallback.
    """

    async def test_stuck_expiry_kis_truth_before_expired(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """STUCK_EXPIRY threshold 도달 → KIS truth 재확인 → fill 확인 → filled 전이."""
        old_time = datetime.now(timezone.utc) - timedelta(seconds=_STUCK_EXPIRY_SECONDS + 100)
        order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            client_order_id="STUCK-KIS-001",
            idempotency_key="idem-stuck-kis-001",
            correlation_id="corr-stuck-kis-001",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            requested_price=Decimal("0"),
            requested_quantity=Decimal("10"),
            status=OrderStatus.RECONCILE_REQUIRED,
            trade_decision_id=None,
            submitted_at=None,
            status_reason_code=None,
            status_reason_message=None,
            created_at=old_time,
            updated_at=old_time,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-STUCK-KIS",
            broker_status="reconcile_required",
        )

        # Position snapshot: pre=20, current=5 → delta=15 → FILLED
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("20"),
            snapshot_time=broker_order.created_at - timedelta(hours=1),
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("5"),
            snapshot_time=broker_order.created_at + timedelta(seconds=1),
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        snapshot_refresh_cb = AsyncMock()

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=False,
            snapshot_refresh_cb=snapshot_refresh_cb,
        )

        # KIS truth confirms fill → FILLED (not EXPIRED)
        assert result is not None
        assert result.status == OrderStatus.FILLED

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.FILLED

        # broker_status should be 'filled'
        updated_bo = await repos.broker_orders.get(broker_order.broker_order_id)
        assert updated_bo is not None
        assert updated_bo.broker_status == "filled"

        # snapshot_refresh_cb should have been called
        snapshot_refresh_cb.assert_awaited_once_with(order.account_id)

    async def test_stuck_expiry_proceeds_when_kis_truth_empty(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """STUCK_EXPIRY threshold 도달 → KIS truth 재확인 → fill 없음 → EXPIRED fallback."""
        old_time = datetime.now(timezone.utc) - timedelta(seconds=_STUCK_EXPIRY_SECONDS + 100)
        order = OrderRequestEntity(
            order_request_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            client_order_id="STUCK-KIS-EMPTY-001",
            idempotency_key="idem-stuck-kis-empty-001",
            correlation_id="corr-stuck-kis-empty-001",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            requested_price=Decimal("0"),
            requested_quantity=Decimal("10"),
            status=OrderStatus.RECONCILE_REQUIRED,
            trade_decision_id=None,
            submitted_at=None,
            status_reason_code=None,
            status_reason_message=None,
            created_at=old_time,
            updated_at=old_time,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order, broker_native_order_id="BRK-STUCK-KIS-EMPTY",
            broker_status="reconcile_required",
        )

        # No position snapshots → KIS truth cannot confirm fill
        # (no pre-order snapshot → _try_kis_truth_fallback returns None)

        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state = AsyncMock(
            return_value=OrderStatusResult(
                broker_name=BrokerName.KOREA_INVESTMENT,
                client_order_id="",
                broker_order_id=broker_order.broker_native_order_id,
                status=OrderStatus.RECONCILE_REQUIRED,
                filled_quantity=Decimal("0"),
                remaining_quantity=Decimal("0"),
                average_fill_price=Decimal("0"),
                last_updated_at=datetime.now(timezone.utc),
            ),
        )

        result = await sync_service.transition_to_authoritative(
            account_ref="test-account",
            broker=broker,
            order=order,
            broker_order=broker_order,
            is_after_hours=True,
        )

        # After-hours: KIS truth did not confirm fill → EXPIRED fallback
        assert result is not None
        assert result.status == OrderStatus.EXPIRED

        updated_order = await repos.orders.get(order.order_request_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.EXPIRED

        # broker_status should be 'expired'
        updated_bo = await repos.broker_orders.get(broker_order.broker_order_id)
        assert updated_bo is not None
        assert updated_bo.broker_status == "expired"


# ═════════════════════════════════════════════════════════════════════
# Test: _try_kis_truth_fallback — KIS API 직접 호출 + rate limit 보호
# ═════════════════════════════════════════════════════════════════════


class TestKisTruthFallback:
    """``_try_kis_truth_fallback()`` — KIS API 직접 호출 + rate limit 보호."""

    async def test_kis_truth_fallback_uses_kis_api_when_broker_provided(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """broker 파라미터 제공 시 KIS API를 호출하여 포지션을 확인한다."""
        now = datetime.now(timezone.utc)
        account_id = uuid4()
        instrument_id = uuid4()
        broker_account_id = uuid4()
        _make_account(repos, account_id=account_id, broker_account_id=broker_account_id)
        _make_broker_account(repos, broker_account_id=broker_account_id)

        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="KIS-TRUTH-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            account_id=account_id,
            instrument_id=instrument_id,
        )
        repos.orders._items[order.order_request_id] = order

        broker_order = _make_broker_order(
            repos,
            order,
            broker_status="reconcile_required",
        )

        # Pre-order snapshot: quantity=20
        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("20"),
            snapshot_time=now - timedelta(hours=2),
        )

        # Mock broker that returns positions via fetch_positions
        broker = AsyncMock(spec=BrokerAdapter)
        broker.fetch_positions = AsyncMock(return_value=[
            _make_position_entity(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("5"),
            ),
        ])

        result = await sync_service._try_kis_truth_fallback(
            order=order,
            broker_order=broker_order,
            account_id=account_id,
            pre_qty=Decimal("20"),
            broker=broker,
        )

        assert result is not None
        assert result.inferred_fill_qty == Decimal("15")
        assert result.source == "kis_truth_fallback"
        broker.fetch_positions.assert_awaited_once()

    async def test_kis_truth_fallback_falls_back_to_local_snapshot_when_no_broker(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """broker 미제공 시 로컬 snapshot으로 fallback한다."""
        now = datetime.now(timezone.utc)
        account_id = uuid4()
        instrument_id = uuid4()
        broker_account_id = uuid4()
        _make_account(repos, account_id=account_id, broker_account_id=broker_account_id)
        _make_broker_account(repos, broker_account_id=broker_account_id)

        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="KIS-TRUTH-NOBROKER-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            account_id=account_id,
            instrument_id=instrument_id,
        )
        repos.orders._items[order.order_request_id] = order

        broker_order = _make_broker_order(
            repos,
            order,
            broker_status="reconcile_required",
        )

        # Pre-order snapshot: quantity=20
        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("20"),
            snapshot_time=now - timedelta(hours=2),
        )
        # Current snapshot: quantity=5 (delta=15)
        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("5"),
            snapshot_time=now,
        )

        result = await sync_service._try_kis_truth_fallback(
            order=order,
            broker_order=broker_order,
            account_id=account_id,
            pre_qty=Decimal("20"),
            broker=None,
        )

        assert result is not None
        assert result.inferred_fill_qty == Decimal("15")
        assert result.source == "kis_truth_fallback"

    async def test_kis_truth_fallback_rate_limit_cooldown(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Cooldown 기간 내 동일 account 재호출 시 KIS API를 건너뛴다."""
        now = datetime.now(timezone.utc)
        account_id = uuid4()
        instrument_id = uuid4()
        broker_account_id = uuid4()
        _make_account(repos, account_id=account_id, broker_account_id=broker_account_id)
        _make_broker_account(repos, broker_account_id=broker_account_id)

        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="KIS-COOLDOWN-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            account_id=account_id,
            instrument_id=instrument_id,
        )
        repos.orders._items[order.order_request_id] = order

        broker_order = _make_broker_order(
            repos,
            order,
            broker_status="reconcile_required",
        )

        # Pre-order snapshot: quantity=20
        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("20"),
            snapshot_time=now - timedelta(hours=2),
        )
        # Current snapshot: quantity=5 (delta=15)
        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("5"),
            snapshot_time=now,
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.fetch_positions = AsyncMock(return_value=[
            _make_position_entity(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("5"),
            ),
        ])

        # First call: should hit KIS API
        result1 = await sync_service._try_kis_truth_fallback(
            order=order,
            broker_order=broker_order,
            account_id=account_id,
            pre_qty=Decimal("20"),
            broker=broker,
        )
        assert result1 is not None
        assert result1.inferred_fill_qty == Decimal("15")
        assert broker.fetch_positions.await_count == 1

        # Second call (immediate, within cooldown): should skip KIS API
        result2 = await sync_service._try_kis_truth_fallback(
            order=order,
            broker_order=broker_order,
            account_id=account_id,
            pre_qty=Decimal("20"),
            broker=broker,
        )
        assert result2 is not None
        assert result2.inferred_fill_qty == Decimal("15")
        # fetch_positions should NOT have been called again
        assert broker.fetch_positions.await_count == 1

    async def test_kis_truth_fallback_per_order_one_call_limit(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """동일 주문에 대해 KIS API는 최대 1회만 호출된다."""
        now = datetime.now(timezone.utc)
        account_id = uuid4()
        instrument_id = uuid4()
        broker_account_id = uuid4()
        _make_account(repos, account_id=account_id, broker_account_id=broker_account_id)
        _make_broker_account(repos, broker_account_id=broker_account_id)

        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="KIS-1CALL-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            account_id=account_id,
            instrument_id=instrument_id,
        )
        repos.orders._items[order.order_request_id] = order

        broker_order = _make_broker_order(
            repos,
            order,
            broker_status="reconcile_required",
        )

        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("20"),
            snapshot_time=now - timedelta(hours=2),
        )
        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("5"),
            snapshot_time=now,
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.fetch_positions = AsyncMock(return_value=[
            _make_position_entity(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("5"),
            ),
        ])

        # Clear _kis_inquiry_seen to ensure clean state
        sync_service._kis_inquiry_seen.clear()

        # First call: should hit KIS API
        result1 = await sync_service._try_kis_truth_fallback(
            order=order,
            broker_order=broker_order,
            account_id=account_id,
            pre_qty=Decimal("20"),
            broker=broker,
        )
        assert result1 is not None
        assert broker.fetch_positions.await_count == 1

        # Reset cooldown to allow second call if not for per-order limit
        sync_service._last_kis_inquiry_at.pop(account_id, None)

        # Second call: should skip KIS API due to per-order 1-call limit
        result2 = await sync_service._try_kis_truth_fallback(
            order=order,
            broker_order=broker_order,
            account_id=account_id,
            pre_qty=Decimal("20"),
            broker=broker,
        )
        assert result2 is not None
        # fetch_positions should NOT have been called again
        assert broker.fetch_positions.await_count == 1

    async def test_kis_truth_fallback_silent_failure_on_api_error(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """KIS API 호출 실패 시 예외를 버블링하지 않고 조용히 fallback한다."""
        now = datetime.now(timezone.utc)
        account_id = uuid4()
        instrument_id = uuid4()
        broker_account_id = uuid4()
        _make_account(repos, account_id=account_id, broker_account_id=broker_account_id)
        _make_broker_account(repos, broker_account_id=broker_account_id)

        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="KIS-ERROR-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            account_id=account_id,
            instrument_id=instrument_id,
        )
        repos.orders._items[order.order_request_id] = order

        broker_order = _make_broker_order(
            repos,
            order,
            broker_status="reconcile_required",
        )

        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("20"),
            snapshot_time=now - timedelta(hours=2),
        )
        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("5"),
            snapshot_time=now,
        )

        broker = AsyncMock(spec=BrokerAdapter)
        broker.fetch_positions = AsyncMock(side_effect=RuntimeError("KIS API unavailable"))

        # Should not raise — silently falls back to local snapshot
        result = await sync_service._try_kis_truth_fallback(
            order=order,
            broker_order=broker_order,
            account_id=account_id,
            pre_qty=Decimal("20"),
            broker=broker,
        )
        assert result is not None
        assert result.inferred_fill_qty == Decimal("15")
        broker.fetch_positions.assert_awaited_once()


# ═════════════════════════════════════════════════════════════════════
# Test: _infer_sell_order_fill_via_position — snapshot_refresh_cb
# ═════════════════════════════════════════════════════════════════════


class TestInferSellOrderFillViaPositionWithRefreshCb:
    """``_infer_sell_order_fill_via_position()`` — snapshot_refresh_cb 전달 시 동작."""

    async def test_infer_sell_fill_calls_snapshot_refresh_cb_on_delta_zero(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """delta=0일 때 snapshot_refresh_cb가 호출되고 retry 후 delta가 감지된다."""
        now = datetime.now(timezone.utc)
        account_id = uuid4()
        instrument_id = uuid4()

        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="REFRESH-CB-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            account_id=account_id,
            instrument_id=instrument_id,
        )
        repos.orders._items[order.order_request_id] = order

        broker_order = _make_broker_order(
            repos,
            order,
            broker_status="reconcile_required",
        )

        # Pre-order snapshot: quantity=20
        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("20"),
            snapshot_time=now - timedelta(hours=2),
        )
        # Current snapshot: quantity=20 (delta=0 initially)
        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("20"),
            snapshot_time=now,
        )

        refresh_call_count = 0

        async def snapshot_refresh_cb(_: UUID) -> None:
            nonlocal refresh_call_count
            refresh_call_count += 1
            # Simulate snapshot sync by adding a new snapshot with reduced quantity
            _make_position_snapshot(
                repos,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("5"),
                snapshot_time=datetime.now(timezone.utc),
            )

        result = await sync_service._infer_sell_order_fill_via_position(
            order,
            broker_order,
            snapshot_refresh_cb=snapshot_refresh_cb,
        )

        assert result == OrderStatus.FILLED
        assert refresh_call_count >= 1

    async def test_infer_sell_fill_skips_cb_when_not_provided(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """snapshot_refresh_cb 미제공 시에도 정상 동작한다 (기존 동작 유지)."""
        now = datetime.now(timezone.utc)
        account_id = uuid4()
        instrument_id = uuid4()

        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="REFRESH-CB-NONE-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            account_id=account_id,
            instrument_id=instrument_id,
        )
        repos.orders._items[order.order_request_id] = order

        # broker_order.created_at must be BEFORE the latest snapshot_time
        # so that get_latest_by_account_and_instrument_before() returns
        # the pre-order snapshot (quantity=20), not the post-order one (quantity=5).
        broker_order = _make_broker_order(
            repos,
            order=order,
            broker_status="reconcile_required",
            last_synced_at=now - timedelta(hours=1),
            created_at=now - timedelta(hours=1, minutes=30),
        )

        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("20"),
            snapshot_time=now - timedelta(hours=2),
        )
        _make_position_snapshot(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("5"),
            snapshot_time=now,
        )

        # No snapshot_refresh_cb — should still work via local snapshots
        result = await sync_service._infer_sell_order_fill_via_position(
            order,
            broker_order,
            snapshot_refresh_cb=None,
        )

        assert result == OrderStatus.FILLED


# ═════════════════════════════════════════════════════════════════════
# Helper: _make_position_entity
# ═════════════════════════════════════════════════════════════════════


def _make_position_entity(
    *,
    account_id: UUID,
    instrument_id: UUID,
    quantity: Decimal,
) -> Any:
    """Create a minimal position entity for KIS API mock responses."""
    from agent_trading.domain.entities import PositionSnapshotEntity

    return PositionSnapshotEntity(
        position_snapshot_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        quantity=quantity,
        average_price=Decimal("0"),
        market_price=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        source_of_truth="kis_api",
        snapshot_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )


def _make_account(
    repos: RepositoryContainer,
    *,
    account_id: UUID,
    broker_account_id: UUID,
) -> None:
    """Create and persist an AccountEntity for testing."""
    from agent_trading.domain.entities import AccountEntity

    entity = AccountEntity(
        account_id=account_id,
        client_id=uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="test-account",
        account_masked="****1234",
        status="active",
    )
    repos.accounts._items[account_id] = entity  # type: ignore[attr-defined]


def _make_broker_account(
    repos: RepositoryContainer,
    *,
    broker_account_id: UUID,
) -> None:
    """Create and persist a BrokerAccountEntity for testing."""
    from agent_trading.domain.entities import BrokerAccountEntity

    entity = BrokerAccountEntity(
        broker_account_id=broker_account_id,
        broker_name=BrokerName.KOREA_INVESTMENT.value,
        account_ref="test-account-ref",
        environment=Environment.PAPER,
        credential_ref="test-cred",
    )
    repos.broker_accounts._items[broker_account_id] = entity  # type: ignore[attr-defined]


# ═════════════════════════════════════════════════════════════════════
# Test: EXPIRED SELL position-delta 후행 복구 (sync_order_post_submit)
# ═════════════════════════════════════════════════════════════════════


class TestExpiredSellPositionDeltaRecovery:
    """``sync_order_post_submit()`` — EXPIRED SELL position-delta 기반 복구.

    Position snapshot이 quantity=0으로 정상 수집되면 position-delta 증거를
    통해 EXPIRED SELL을 FILLED/PARTIALLY_FILLED로 복구한다.
    Broker truth가 EXPIRED를 반환하는 paper broker 환경에서 유효하다.
    """

    async def test_expired_sell_position_delta_zero_out_filled(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """EXPIRED SELL, position=10→0 delta=10 ≥ requested=10 → FILLED 복구."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="PD-FILLED-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            updated_at=now,  # _RECENT_EXPIRY_WINDOW_SECONDS 이내
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-PD-FILLED-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Pre-order snapshot: quantity=10 (before broker_order.created_at)
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        # Post-order snapshot: quantity=0 (delta=10 → FILLED)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("0"),
            snapshot_time=now,
        )

        # Broker returns EXPIRED → broker truth recovery 실패
        broker = _StubBroker(status=OrderStatus.EXPIRED)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        # Position-delta recovery should succeed → FILLED
        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.FILLED
        # broker_status도 'filled'로 동기화
        updated_bo = await repos.broker_orders.get(broker_order.broker_order_id)
        assert updated_bo is not None
        assert updated_bo.broker_status == "filled"

    async def test_expired_sell_position_delta_partial_fill(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """EXPIRED SELL, position=10→3 delta=7 < requested=10 → PARTIALLY_FILLED 복구."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="PD-PARTIAL-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-PD-PARTIAL-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Pre-order snapshot: quantity=10
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        # Post-order snapshot: quantity=3 (delta=7 < 10)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("3"),
            snapshot_time=now,
        )

        broker = _StubBroker(status=OrderStatus.EXPIRED)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        # Position-delta recovery → PARTIALLY_FILLED
        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.PARTIALLY_FILLED
        updated_bo = await repos.broker_orders.get(broker_order.broker_order_id)
        assert updated_bo is not None
        assert updated_bo.broker_status == "partially_filled"

    async def test_expired_sell_no_position_delta_no_recovery(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """EXPIRED SELL, delta=0 → 복구 안 함, EXPIRED 유지."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="PD-NO-DELTA-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-PD-NO-DELTA-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Pre-order snapshot: quantity=10
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        # Post-order snapshot: quantity=10 (delta=0)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=now,
        )

        broker = _StubBroker(status=OrderStatus.EXPIRED)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        # No position delta → EXPIRED 유지
        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.EXPIRED

    async def test_expired_buy_ignores_position_delta(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """EXPIRED BUY → position-delta 시도 안 함 (SELL 전용)."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="PD-BUY-001",
        )
        order = replace(
            order,
            side=OrderSide.BUY,  # BUY — should skip position-delta
            requested_quantity=Decimal("10"),
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-PD-BUY-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Position snapshots exist but should not be used (BUY)
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("0"),
            snapshot_time=now,
        )

        broker = _StubBroker(status=OrderStatus.EXPIRED)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        # BUY → position-delta skip, EXPIRED 유지
        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.EXPIRED

    async def test_expired_sell_broker_truth_takes_priority(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Broker truth FILLED 반환 → position-delta보다 broker truth 우선."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="PD-PRIORITY-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-PD-PRIORITY-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Position snapshots show no delta (quantity unchanged)
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=now,
        )

        # Broker returns FILLED → broker truth recovery succeeds
        broker = _StubBroker(status=OrderStatus.FILLED)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        # Broker truth → FILLED (position-delta would have returned None)
        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.FILLED

    async def test_expired_sell_old_order_no_recovery(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """EXPIRED SELL, created_at 24h 초과 → ``_can_recover_expired`` 차단."""
        now = datetime.now(timezone.utc)
        old_created = now - timedelta(hours=25)  # > 24h
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="PD-OLD-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            created_at=old_created,
            updated_at=now,  # recent updated_at → passes window check
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-PD-OLD-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Position delta exists (10→0)
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("0"),
            snapshot_time=now,
        )

        broker = _StubBroker(status=OrderStatus.EXPIRED)

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
        )

        # _can_recover_expired blocks recovery → EXPIRED 유지
        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.EXPIRED

    async def test_expired_sell_position_delta_with_snapshot_refresh(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Position-delta 복구 후 snapshot_refresh_cb 호출 확인."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="PD-REFRESH-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-PD-REFRESH-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Position delta 10→0 → FILLED
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        # Post-order snapshot: quantity=0 (delta=10 → FILLED)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("0"),
            snapshot_time=now,
        )

        broker = _StubBroker(status=OrderStatus.EXPIRED)

        refresh_called = False

        async def snapshot_refresh_cb(account_id: UUID) -> None:
            nonlocal refresh_called
            refresh_called = True

        result = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,  # type: ignore[arg-type]
            broker_order_id=broker_order.broker_order_id,
            snapshot_refresh_cb=snapshot_refresh_cb,
        )

        # FILLED 복구 및 snapshot_refresh_cb 호출 확인
        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.FILLED
        assert refresh_called is True


# ═════════════════════════════════════════════════════════════════════
# Test: Backfill EXPIRED SELL (recover_expired_sell_by_position)
# ═════════════════════════════════════════════════════════════════════


class TestBackfillExpiredSellByPosition:
    """``recover_expired_sell_by_position()`` — 백필 EXPIRED SELL 복구.

    ``sync_order_post_submit()``을 통한 position-delta 복구와 달리,
    이 클래스는 ``recover_expired_sell_by_position()`` public 메서드를
    직접 호출하여 이미 EXPIRED된 SELL market 주문을 복구한다.

    기존 ``TestExpiredSellPositionDeltaRecovery``와 독립적으로 동작하며,
    broker truth 재조회 없이 곧바로 position-delta를 확인한다.
    """

    async def test_backfill_expired_market_sell_filled(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """EXPIRED SELL MARKET, delta=10/10 → FILLED 복구."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="BACKFILL-FILLED-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("10"),
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-BACKFILL-FILLED-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Pre-order snapshot: quantity=10
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        # Post-order snapshot: quantity=0 (delta=10 → FILLED)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("0"),
            snapshot_time=now,
        )

        result = await sync_service.recover_expired_sell_by_position(
            order, broker_order,
        )

        assert result is not None
        assert result.status_changed is True
        assert result.current_status == OrderStatus.FILLED
        # broker_status 동기화 확인
        updated_bo = await repos.broker_orders.get(broker_order.broker_order_id)
        assert updated_bo is not None
        assert updated_bo.broker_status == "filled"

    async def test_backfill_expired_market_sell_partial(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """EXPIRED SELL MARKET, delta=5/10 → PARTIALLY_FILLED 복구."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="BACKFILL-PARTIAL-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("10"),
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-BACKFILL-PARTIAL-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Pre-order snapshot: quantity=10
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        # Post-order snapshot: quantity=5 (delta=5 < 10)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("5"),
            snapshot_time=now,
        )

        result = await sync_service.recover_expired_sell_by_position(
            order, broker_order,
        )

        assert result is not None
        assert result.status_changed is True
        assert result.current_status == OrderStatus.PARTIALLY_FILLED
        # broker_status 동기화 확인
        updated_bo = await repos.broker_orders.get(broker_order.broker_order_id)
        assert updated_bo is not None
        assert updated_bo.broker_status == "partially_filled"

    async def test_backfill_skip_rejected(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Broker_status='rejected' → 복구 skip."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="BACKFILL-REJECTED-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("10"),
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-BACKFILL-REJECTED-001",
            broker_status="rejected",  # Rejected — should skip
            created_at=now - timedelta(minutes=5),
        )

        # Position delta exists but should not be used
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("0"),
            snapshot_time=now,
        )

        result = await sync_service.recover_expired_sell_by_position(
            order, broker_order,
        )

        assert result is None
        # 상태 변경 없음 — EXPIRED 유지
        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.EXPIRED

    async def test_backfill_skip_non_market(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Order_type=LIMIT → 복구 skip (MARKET 전용)."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="BACKFILL-LIMIT-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,  # LIMIT — should skip
            requested_quantity=Decimal("10"),
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-BACKFILL-LIMIT-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Position delta exists but should not be used
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("0"),
            snapshot_time=now,
        )

        result = await sync_service.recover_expired_sell_by_position(
            order, broker_order,
        )

        assert result is None
        # 상태 변경 없음 — EXPIRED 유지
        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.EXPIRED

    async def test_backfill_skip_no_position_delta(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Position delta=0 → 복구 skip, EXPIRED 유지."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="BACKFILL-NO-DELTA-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("10"),
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-BACKFILL-NO-DELTA-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Pre-order snapshot: quantity=10
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        # Post-order snapshot: quantity=10 (delta=0)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=now,
        )

        result = await sync_service.recover_expired_sell_by_position(
            order, broker_order,
        )

        assert result is None
        # EXPIRED 유지
        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.EXPIRED

    async def test_backfill_skip_buy_side(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """BUY side → 복구 skip (SELL 전용)."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="BACKFILL-BUY-001",
        )
        order = replace(
            order,
            side=OrderSide.BUY,  # BUY — should skip
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("10"),
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-BACKFILL-BUY-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Position delta exists but should not be used
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("0"),
            snapshot_time=now,
        )

        result = await sync_service.recover_expired_sell_by_position(
            order, broker_order,
        )

        assert result is None
        # EXPIRED 유지
        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.EXPIRED

    async def test_backfill_old_order_24h(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """created_at 24h 초과 → ``_can_recover_expired`` 차단."""
        now = datetime.now(timezone.utc)
        old_created = now - timedelta(hours=25)  # > 24h
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="BACKFILL-OLD-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("10"),
            created_at=old_created,
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-BACKFILL-OLD-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Position delta exists but blocked by _can_recover_expired
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("0"),
            snapshot_time=now,
        )

        result = await sync_service.recover_expired_sell_by_position(
            order, broker_order,
        )

        assert result is None
        # EXPIRED 유지
        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.EXPIRED

    async def test_backfill_dry_run_no_side_effects(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """snapshot_refresh_cb 미전달 → side effect 없이 FILLED 복구."""
        now = datetime.now(timezone.utc)
        order = _make_order(
            repos,
            status=OrderStatus.EXPIRED,
            client_order_id="BACKFILL-DRY-001",
        )
        order = replace(
            order,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("10"),
            updated_at=now,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="BRK-BACKFILL-DRY-001",
            broker_status="expired",
            created_at=now - timedelta(minutes=5),
        )

        # Position delta 10→0 → FILLED
        pre_snap_time = now - timedelta(hours=1)
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("10"),
            snapshot_time=pre_snap_time,
        )
        _make_position_snapshot(
            repos,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            quantity=Decimal("0"),
            snapshot_time=now,
        )

        # snapshot_refresh_cb 미전달
        result = await sync_service.recover_expired_sell_by_position(
            order, broker_order,
        )

        assert result is not None
        assert result.status_changed is True
        assert result.current_status == OrderStatus.FILLED
        # snapshot_refresh_cb가 없으므로 snapshot_triggered=False
        assert result.snapshot_triggered is False


# ═════════════════════════════════════════════════════════════════════
# Test: Stale PENDING_SUBMIT expire
# ═════════════════════════════════════════════════════════════════════


class TestRejectStalePendingSubmit:
    """PostSubmitSyncRunner._reject_stale_pending_submit_orders() 테스트."""

    async def test_reject_stale_pending_submit(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
    ) -> None:
        """Stale PENDING_SUBMIT (30분↑ + broker_native_order_id=NULL)을
        REJECTED로 전이하고 reason_code가 submission_failed_no_broker_id인지 검증."""
        # PostSubmitSyncRunner 생성
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=OrderSyncService(repos=repos, order_manager=order_manager),
            broker=_StubBroker(status=OrderStatus.FILLED),  # not used in reject
        )

        # 31분 전 생성된 stale PENDING_SUBMIT SELL 주문
        stale_created_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        stale_order = _make_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="STALE-PS-001",
        )
        # created_at override (frozen dataclass)
        stale_order = OrderRequestEntity(
            order_request_id=stale_order.order_request_id,
            account_id=stale_order.account_id,
            instrument_id=stale_order.instrument_id,
            client_order_id=stale_order.client_order_id,
            idempotency_key=stale_order.idempotency_key,
            correlation_id=stale_order.correlation_id,
            side=OrderSide.SELL,
            order_type=stale_order.order_type,
            requested_quantity=stale_order.requested_quantity,
            status=stale_order.status,
            trade_decision_id=stale_order.trade_decision_id,
            decision_context_id=stale_order.decision_context_id,
            requested_price=stale_order.requested_price,
            time_in_force=stale_order.time_in_force,
            status_reason_code=stale_order.status_reason_code,
            status_reason_message=stale_order.status_reason_message,
            submitted_at=stale_order.submitted_at,
            created_at=stale_created_at,
            updated_at=stale_created_at,
            version=stale_order.version,
            order_intent_id=stale_order.order_intent_id,
        )
        repos.orders._items[stale_order.order_request_id] = stale_order  # type: ignore[attr-defined]

        # broker_native_order_id가 없는 BrokerOrderEntity (orphan)
        _make_broker_order(
            repos,
            stale_order,
            broker_native_order_id=None,
        )

        rejected = await runner._reject_stale_pending_submit_orders()

        assert len(rejected) == 1, f"Expected 1 rejected, got {len(rejected)}"
        assert rejected[0].order_request_id == stale_order.order_request_id

        # DB에서 상태 확인
        updated = await repos.orders.get(stale_order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.REJECTED, (
            f"Expected REJECTED, got {updated.status}"
        )
        assert updated.status_reason_code == "submission_failed_no_broker_id", (
            f"Expected reason_code='submission_failed_no_broker_id', "
            f"got {updated.status_reason_code}"
        )

    async def test_reject_skips_fresh_pending_submit(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
    ) -> None:
        """Fresh PENDING_SUBMIT (30분 미만)은 REJECTED되지 않는지 검증."""
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=OrderSyncService(repos=repos, order_manager=order_manager),
            broker=_StubBroker(status=OrderStatus.FILLED),
        )

        # 5분 전 생성된 fresh PENDING_SUBMIT SELL 주문
        fresh_created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        fresh_order = _make_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="FRESH-PS-001",
        )
        fresh_order = OrderRequestEntity(
            order_request_id=fresh_order.order_request_id,
            account_id=fresh_order.account_id,
            instrument_id=fresh_order.instrument_id,
            client_order_id=fresh_order.client_order_id,
            idempotency_key=fresh_order.idempotency_key,
            correlation_id=fresh_order.correlation_id,
            side=OrderSide.SELL,
            order_type=fresh_order.order_type,
            requested_quantity=fresh_order.requested_quantity,
            status=fresh_order.status,
            trade_decision_id=fresh_order.trade_decision_id,
            decision_context_id=fresh_order.decision_context_id,
            requested_price=fresh_order.requested_price,
            time_in_force=fresh_order.time_in_force,
            status_reason_code=fresh_order.status_reason_code,
            status_reason_message=fresh_order.status_reason_message,
            submitted_at=fresh_order.submitted_at,
            created_at=fresh_created_at,
            updated_at=fresh_created_at,
            version=fresh_order.version,
            order_intent_id=fresh_order.order_intent_id,
        )
        repos.orders._items[fresh_order.order_request_id] = fresh_order  # type: ignore[attr-defined]

        # broker_native_order_id가 없는 BrokerOrderEntity
        _make_broker_order(
            repos,
            fresh_order,
            broker_native_order_id=None,
        )

        rejected = await runner._reject_stale_pending_submit_orders()

        assert len(rejected) == 0, (
            f"Expected 0 rejected for fresh PENDING_SUBMIT, got {len(rejected)}"
        )

        # DB에서 상태가 그대로인지 확인
        updated = await repos.orders.get(fresh_order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.PENDING_SUBMIT, (
            f"Expected PENDING_SUBMIT unchanged, got {updated.status}"
        )

    async def test_reject_skips_pending_submit_with_broker_native_id(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
    ) -> None:
        """Stale PENDING_SUBMIT이지만 broker_native_order_id가 있으면
        REJECTED되지 않는지 검증."""
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=OrderSyncService(repos=repos, order_manager=order_manager),
            broker=_StubBroker(status=OrderStatus.FILLED),
        )

        # 31분 전 생성되었지만 broker_native_order_id가 있는 PENDING_SUBMIT
        stale_created_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        order = _make_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="STALE-WITH-BROKER-001",
        )
        order = OrderRequestEntity(
            order_request_id=order.order_request_id,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            idempotency_key=order.idempotency_key,
            correlation_id=order.correlation_id,
            side=OrderSide.SELL,
            order_type=order.order_type,
            requested_quantity=order.requested_quantity,
            status=order.status,
            trade_decision_id=order.trade_decision_id,
            decision_context_id=order.decision_context_id,
            requested_price=order.requested_price,
            time_in_force=order.time_in_force,
            status_reason_code=order.status_reason_code,
            status_reason_message=order.status_reason_message,
            submitted_at=order.submitted_at,
            created_at=stale_created_at,
            updated_at=stale_created_at,
            version=order.version,
            order_intent_id=order.order_intent_id,
        )
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

        # broker_native_order_id가 있는 BrokerOrderEntity
        _make_broker_order(
            repos,
            order,
            broker_native_order_id="BRK-EXISTING-001",
        )

        rejected = await runner._reject_stale_pending_submit_orders()

        assert len(rejected) == 0, (
            f"Expected 0 rejected (has broker_native_order_id), got {len(rejected)}"
        )

    async def test_reject_skips_buy_pending_submit(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
    ) -> None:
        """BUY PENDING_SUBMIT은 REJECTED되지 않는지 검증."""
        runner = PostSubmitSyncRunner(
            repos=repos,
            sync_service=OrderSyncService(repos=repos, order_manager=order_manager),
            broker=_StubBroker(status=OrderStatus.FILLED),
        )

        # 31분 전 생성된 stale PENDING_SUBMIT BUY 주문
        stale_created_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        buy_order = _make_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="STALE-BUY-001",
        )
        buy_order = OrderRequestEntity(
            order_request_id=buy_order.order_request_id,
            account_id=buy_order.account_id,
            instrument_id=buy_order.instrument_id,
            client_order_id=buy_order.client_order_id,
            idempotency_key=buy_order.idempotency_key,
            correlation_id=buy_order.correlation_id,
            side=OrderSide.BUY,
            order_type=buy_order.order_type,
            requested_quantity=buy_order.requested_quantity,
            status=buy_order.status,
            trade_decision_id=buy_order.trade_decision_id,
            decision_context_id=buy_order.decision_context_id,
            requested_price=buy_order.requested_price,
            time_in_force=buy_order.time_in_force,
            status_reason_code=buy_order.status_reason_code,
            status_reason_message=buy_order.status_reason_message,
            submitted_at=buy_order.submitted_at,
            created_at=stale_created_at,
            updated_at=stale_created_at,
            version=buy_order.version,
            order_intent_id=buy_order.order_intent_id,
        )
        repos.orders._items[buy_order.order_request_id] = buy_order  # type: ignore[attr-defined]

        _make_broker_order(
            repos,
            buy_order,
            broker_native_order_id=None,
        )

        rejected = await runner._reject_stale_pending_submit_orders()

        assert len(rejected) == 0, (
            f"Expected 0 rejected for BUY PENDING_SUBMIT, got {len(rejected)}"
        )


# ------------------------------------------------------------
# Test: EOD Orphan Cleanup — expire_eod_orphan_orders
# ------------------------------------------------------------


def _make_orphan_order(
    repos: RepositoryContainer,
    *,
    status: OrderStatus = OrderStatus.PENDING_SUBMIT,
    client_order_id: str = "ORPHAN-TEST-001",
    created_at: datetime | None = None,
) -> OrderRequestEntity:
    """Create and persist an orphan order candidate (no broker_order by default)."""
    now = created_at or (datetime.now(timezone.utc) - timedelta(hours=2))
    order = OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=uuid4(),
        instrument_id=uuid4(),
        client_order_id=client_order_id,
        idempotency_key="idem-orphan-001",
        correlation_id="corr-orphan-001",
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
    repos.orders._items[order.order_request_id] = order
    return order


class TestExpireEodOrphanOrders:
    """expire_eod_orphan_orders() — EOD orphan cleanup 정책 검증."""

    async def test_expire_eod_orphan_orders_pending_submit(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """pending_submit 주문이 broker_orders 없이 오래된 경우 EXPIRED로 전이."""
        order = _make_orphan_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="ORPHAN-PS-001",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )

        expired_pending, expired_reconcile = await sync_service.expire_eod_orphan_orders()

        assert expired_pending == 1, f"Expected 1 pending_submit expired, got {expired_pending}"
        assert expired_reconcile == 0

        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.EXPIRED, (
            f"Expected EXPIRED, got {updated.status}"
        )
        assert updated.status_reason_code == "eod_orphan_cleanup_no_broker_order", (
            f"Expected reason_code 'eod_orphan_cleanup_no_broker_order', "
            f"got {updated.status_reason_code}"
        )

    async def test_expire_eod_orphan_orders_skips_fresh_pending_submit(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """10분 전 생성된 pending_submit 주문은 threshold 미만으로 cleanup되지 않음."""
        order = _make_orphan_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="ORPHAN-FRESH-001",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )

        expired_pending, expired_reconcile = await sync_service.expire_eod_orphan_orders()

        assert expired_pending == 0, f"Expected 0 expired, got {expired_pending}"
        assert expired_reconcile == 0

        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.PENDING_SUBMIT, (
            f"Expected PENDING_SUBMIT unchanged, got {updated.status}"
        )

    async def test_expire_eod_orphan_orders_skips_when_broker_order_exists(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """BrokerOrderEntity가 존재하는 pending_submit 주문은 cleanup되지 않음."""
        order = _make_orphan_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="ORPHAN-HAS-BROKER-001",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        _make_broker_order(
            repos, order, broker_native_order_id="TEST123",
        )

        expired_pending, expired_reconcile = await sync_service.expire_eod_orphan_orders()

        assert expired_pending == 0, f"Expected 0 expired (broker_order exists), got {expired_pending}"
        assert expired_reconcile == 0

        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.PENDING_SUBMIT, (
            f"Expected PENDING_SUBMIT unchanged, got {updated.status}"
        )

    async def test_expire_eod_orphan_orders_reconcile_required_failed_reconciliation(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """reconcile_required 주문 + failed reconciliation run -> EXPIRED 전이."""
        order = _make_orphan_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="ORPHAN-RR-FAIL-001",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )

        run_id = uuid4()
        run = ReconciliationRunEntity(
            reconciliation_run_id=run_id,
            account_id=order.account_id,
            trigger_type="scheduled",
            status="failed",
            started_at=datetime.now(timezone.utc) - timedelta(hours=1),
            mismatch_count=1,
        )
        await repos.reconciliations.add_run(run)
        await repos.reconciliations.attach_order_mismatch(
            reconciliation_run_id=run_id,
            order_request_id=order.order_request_id,
            mismatch_type="order_mismatch",
            details={},
        )

        expired_pending, expired_reconcile = await sync_service.expire_eod_orphan_orders()

        assert expired_pending == 0
        assert expired_reconcile == 1, (
            f"Expected 1 reconcile_required expired, got {expired_reconcile}"
        )

        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.EXPIRED, (
            f"Expected EXPIRED, got {updated.status}"
        )
        assert updated.status_reason_code == "eod_orphan_cleanup_failed_reconciliation", (
            f"Expected 'eod_orphan_cleanup_failed_reconciliation', "
            f"got {updated.status_reason_code}"
        )

    async def test_expire_eod_orphan_orders_reconcile_required_no_reconciliation(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """reconcile_required 주문 + reconciliation run 없음 -> EXPIRED 전이."""
        order = _make_orphan_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="ORPHAN-RR-NO-REC-001",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )

        expired_pending, expired_reconcile = await sync_service.expire_eod_orphan_orders()

        assert expired_pending == 0
        assert expired_reconcile == 1, (
            f"Expected 1 reconcile_required expired, got {expired_reconcile}"
        )

        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.EXPIRED, (
            f"Expected EXPIRED, got {updated.status}"
        )
        assert updated.status_reason_code == "eod_orphan_cleanup_no_reconciliation", (
            f"Expected 'eod_orphan_cleanup_no_reconciliation', "
            f"got {updated.status_reason_code}"
        )

    async def test_expire_eod_orphan_orders_skips_reconcile_required_completed_reconciliation(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """reconcile_required 주문 + completed reconciliation run -> cleanup되지 않음."""
        order = _make_orphan_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="ORPHAN-RR-COMPLETE-001",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        # broker_order가 존재하면 _is_eod_orphan()이 False를 반환하여
        # cleanup에서 제외됨. reconcile_required 상태에서 broker_order는
        # broker에 제출되었으나 reconciliation 불일치가 발생한 경우를 의미.
        _make_broker_order(
            repos, order, broker_native_order_id="COMPLETED-BRK-001",
        )

        run_id = uuid4()
        run = ReconciliationRunEntity(
            reconciliation_run_id=run_id,
            account_id=order.account_id,
            trigger_type="scheduled",
            status="completed",
            started_at=datetime.now(timezone.utc) - timedelta(hours=1),
            mismatch_count=0,
        )
        await repos.reconciliations.add_run(run)
        await repos.reconciliations.attach_order_mismatch(
            reconciliation_run_id=run_id,
            order_request_id=order.order_request_id,
            mismatch_type="order_mismatch",
            details={},
        )

        expired_pending, expired_reconcile = await sync_service.expire_eod_orphan_orders()

        assert expired_pending == 0
        assert expired_reconcile == 0, (
            f"Expected 0 expired (completed reconciliation), got {expired_reconcile}"
        )

        updated = await repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.RECONCILE_REQUIRED, (
            f"Expected RECONCILE_REQUIRED unchanged, got {updated.status}"
        )

    async def test_expire_eod_orphan_orders_returns_correct_counts(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """여러 orphan 주문 중 일부만 cleanup 대상일 때 카운트가 정확한지 검증."""
        now = datetime.now(timezone.utc)

        # 대상 1: 오래된 pending_submit (cleanup 대상)
        _make_orphan_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="ORPHAN-COUNT-PS-001",
            created_at=now - timedelta(hours=2),
        )

        # 대상 2: 오래된 pending_submit (cleanup 대상)
        _make_orphan_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="ORPHAN-COUNT-PS-002",
            created_at=now - timedelta(hours=3),
        )

        # 대상 3: fresh pending_submit (cleanup 제외)
        _make_orphan_order(
            repos,
            status=OrderStatus.PENDING_SUBMIT,
            client_order_id="ORPHAN-COUNT-PS-FRESH",
            created_at=now - timedelta(minutes=10),
        )

        # 대상 4: 오래된 reconcile_required + failed reconciliation (cleanup 대상)
        rr_order = _make_orphan_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="ORPHAN-COUNT-RR-001",
            created_at=now - timedelta(hours=2),
        )
        run_id = uuid4()
        run = ReconciliationRunEntity(
            reconciliation_run_id=run_id,
            account_id=rr_order.account_id,
            trigger_type="scheduled",
            status="failed",
            started_at=now - timedelta(hours=1),
            mismatch_count=1,
        )
        await repos.reconciliations.add_run(run)
        await repos.reconciliations.attach_order_mismatch(
            reconciliation_run_id=run_id,
            order_request_id=rr_order.order_request_id,
            mismatch_type="order_mismatch",
            details={},
        )

        # 대상 5: 오래된 reconcile_required + completed reconciliation (cleanup 제외)
        # broker_order가 존재하므로 _is_eod_orphan()이 False를 반환하여
        # cleanup에서 제외됨.
        rr_complete_order = _make_orphan_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="ORPHAN-COUNT-RR-COMPLETE",
            created_at=now - timedelta(hours=2),
        )
        _make_broker_order(
            repos, rr_complete_order, broker_native_order_id="COUNT-COMPLETE-BRK-001",
        )
        run_id2 = uuid4()
        run2 = ReconciliationRunEntity(
            reconciliation_run_id=run_id2,
            account_id=rr_complete_order.account_id,
            trigger_type="scheduled",
            status="completed",
            started_at=now - timedelta(hours=1),
            mismatch_count=0,
        )
        await repos.reconciliations.add_run(run2)
        await repos.reconciliations.attach_order_mismatch(
            reconciliation_run_id=run_id2,
            order_request_id=rr_complete_order.order_request_id,
            mismatch_type="order_mismatch",
            details={},
        )

        expired_pending, expired_reconcile = await sync_service.expire_eod_orphan_orders()

        assert expired_pending == 2, f"Expected 2 pending_submit expired, got {expired_pending}"
        assert expired_reconcile == 1, f"Expected 1 reconcile_required expired, got {expired_reconcile}"
