"""Integration tests for RealTimeEventLoop core paths.

Test matrix
-----------
1. WS fill notification → ExternalEventRepository.add()
2. WS fill notification → FillEventRepository.add()
3. WS fill notification → OrderManager.transition_to() (partial fill)
4. WS fill notification → OrderManager.transition_to() (full fill)
5. Native ID mapping failure → ExternalEvent saved, transition_to skipped
6. Duplicate fill detection → FillEventRepository.add() skipped
7. Gap fill → ExternalEventRepository.add() with correct field mapping
8. Trade price / orderbook ingest → ExternalEventRepository.add()
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    BrokerOrderEntity,
    ExternalEventEntity,
    FillEventEntity,
    OrderRequestEntity,
)
from agent_trading.domain.enums import (
    EventSource,
    OrderSide,
    OrderStatus,
    OrderType,
    SourceReliabilityTier,
    TimeInForce,
)
from agent_trading.domain.models import FillEvent
from agent_trading.services.event_loop import RealTimeEventLoop

pytestmark = pytest.mark.asyncio


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def mock_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.ws_messages = AsyncMock()
    adapter.get_fills = AsyncMock(return_value=[])
    return adapter


@pytest.fixture
def mock_order_manager() -> MagicMock:
    om = MagicMock()
    om.transition_to = AsyncMock()
    return om


@pytest.fixture
def mock_reconciliation_service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_order_repo() -> MagicMock:
    repo = MagicMock()
    repo.get = AsyncMock()
    return repo


@pytest.fixture
def mock_fill_repo() -> MagicMock:
    repo = MagicMock()
    repo.add = AsyncMock()
    return repo


@pytest.fixture
def mock_external_event_repo() -> MagicMock:
    repo = MagicMock()
    repo.add = AsyncMock()
    repo.find_by_dedup_key = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_broker_order_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_by_native_order_id = AsyncMock()
    return repo


@pytest.fixture
def sample_order_entity() -> OrderRequestEntity:
    return OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=uuid4(),
        instrument_id=uuid4(),
        client_order_id="test-client-order-001",
        idempotency_key="test-idem-001",
        correlation_id="test-corr-001",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        requested_quantity=Decimal("10"),
        status=OrderStatus.SUBMITTED,
        requested_price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(tz=timezone.utc),
    )


@pytest.fixture
def sample_broker_order(sample_order_entity: OrderRequestEntity) -> BrokerOrderEntity:
    return BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=sample_order_entity.order_request_id,
        broker_name="koreainvestment",
        broker_status="submitted",
        broker_native_order_id="KIS12345678",
        created_at=datetime.now(tz=timezone.utc),
    )


@pytest.fixture
def event_loop_fixture(
    mock_adapter: MagicMock,
    mock_order_manager: MagicMock,
    mock_reconciliation_service: MagicMock,
    mock_order_repo: MagicMock,
    mock_fill_repo: MagicMock,
    mock_external_event_repo: MagicMock,
    mock_broker_order_repo: MagicMock,
) -> RealTimeEventLoop:
    return RealTimeEventLoop(
        adapter=mock_adapter,
        order_manager=mock_order_manager,
        reconciliation_service=mock_reconciliation_service,
        order_repo=mock_order_repo,
        fill_repo=mock_fill_repo,
        external_event_repo=mock_external_event_repo,
        broker_order_repo=mock_broker_order_repo,
    )


# ======================================================================
# Tests
# ======================================================================


class TestFillNotificationCorePath:
    """Core fill notification path: ExternalEvent → FillEvent → OrderManager."""

    async def test_external_event_persisted(
        self,
        event_loop_fixture: RealTimeEventLoop,
        mock_external_event_repo: MagicMock,
        mock_broker_order_repo: MagicMock,
        mock_order_repo: MagicMock,
        sample_broker_order: BrokerOrderEntity,
        sample_order_entity: OrderRequestEntity,
    ) -> None:
        """Fill notification persists ExternalEventEntity with correct fields."""
        # Arrange
        mock_broker_order_repo.get_by_native_order_id.return_value = sample_broker_order
        mock_order_repo.get.return_value = sample_order_entity

        data = {
            "broker_order_id": "KIS12345678",
            "stock_code": "005930",
            "filled_qty": "5",
            "filled_price": "50500",
            "filled_time": "143025",
            "side": OrderSide.BUY,
            "order_qty": "10",
        }

        # Act
        await event_loop_fixture._handle_fill_notification(data)

        # Assert
        mock_external_event_repo.add.assert_called_once()
        call_args = mock_external_event_repo.add.call_args[0][0]
        assert isinstance(call_args, ExternalEventEntity)
        assert call_args.event_type == "fill_notification"
        assert call_args.source_name == EventSource.BROKER_WS.value
        assert call_args.source_reliability_tier == SourceReliabilityTier.T1_REGULATORY.value
        assert call_args.source_event_id == "H0STCNI0:KIS12345678:143025"
        assert call_args.symbol == "005930"
        assert call_args.dedup_key_hash == "fill:KIS12345678:143025"
        assert call_args.published_at is not None  # broker time parsed
        assert call_args.metadata == data

    async def test_fill_event_persisted(
        self,
        event_loop_fixture: RealTimeEventLoop,
        mock_fill_repo: MagicMock,
        mock_broker_order_repo: MagicMock,
        mock_order_repo: MagicMock,
        sample_broker_order: BrokerOrderEntity,
        sample_order_entity: OrderRequestEntity,
    ) -> None:
        """Fill notification persists FillEventEntity with correct fields."""
        # Arrange
        mock_broker_order_repo.get_by_native_order_id.return_value = sample_broker_order
        mock_order_repo.get.return_value = sample_order_entity

        data = {
            "broker_order_id": "KIS12345678",
            "stock_code": "005930",
            "filled_qty": "5",
            "filled_price": "50500",
            "filled_time": "143025",
            "side": OrderSide.BUY,
            "order_qty": "10",
        }

        # Act
        await event_loop_fixture._handle_fill_notification(data)

        # Assert
        mock_fill_repo.add.assert_called_once()
        call_args = mock_fill_repo.add.call_args[0][0]
        assert isinstance(call_args, FillEventEntity)
        assert call_args.broker_order_id == sample_order_entity.order_request_id  # UUID
        assert call_args.fill_quantity == Decimal("5")
        assert call_args.fill_price == Decimal("50500")
        assert call_args.fill_timestamp is not None
        assert call_args.source_channel == "websocket"
        assert call_args.fill_fee is None

    async def test_partial_fill_transition(
        self,
        event_loop_fixture: RealTimeEventLoop,
        mock_order_manager: MagicMock,
        mock_broker_order_repo: MagicMock,
        mock_order_repo: MagicMock,
        sample_broker_order: BrokerOrderEntity,
        sample_order_entity: OrderRequestEntity,
    ) -> None:
        """Partial fill (filled_qty < order_qty) → PARTIALLY_FILLED."""
        # Arrange
        mock_broker_order_repo.get_by_native_order_id.return_value = sample_broker_order
        mock_order_repo.get.return_value = sample_order_entity

        data = {
            "broker_order_id": "KIS12345678",
            "stock_code": "005930",
            "filled_qty": "3",
            "filled_price": "50000",
            "filled_time": "143025",
            "side": OrderSide.BUY,
            "order_qty": "10",
        }

        # Act
        await event_loop_fixture._handle_fill_notification(data)

        # Assert
        mock_order_manager.transition_to.assert_called_once()
        call_order, call_status = mock_order_manager.transition_to.call_args[0]
        assert call_order is sample_order_entity
        assert call_status == OrderStatus.PARTIALLY_FILLED

    async def test_full_fill_transition(
        self,
        event_loop_fixture: RealTimeEventLoop,
        mock_order_manager: MagicMock,
        mock_broker_order_repo: MagicMock,
        mock_order_repo: MagicMock,
        sample_broker_order: BrokerOrderEntity,
        sample_order_entity: OrderRequestEntity,
    ) -> None:
        """Full fill (filled_qty >= order_qty) → FILLED."""
        # Arrange
        mock_broker_order_repo.get_by_native_order_id.return_value = sample_broker_order
        mock_order_repo.get.return_value = sample_order_entity

        data = {
            "broker_order_id": "KIS12345678",
            "stock_code": "005930",
            "filled_qty": "10",
            "filled_price": "50000",
            "filled_time": "143025",
            "side": OrderSide.BUY,
            "order_qty": "10",
        }

        # Act
        await event_loop_fixture._handle_fill_notification(data)

        # Assert
        mock_order_manager.transition_to.assert_called_once()
        call_order, call_status = mock_order_manager.transition_to.call_args[0]
        assert call_order is sample_order_entity
        assert call_status == OrderStatus.FILLED


class TestNativeIdMappingFailure:
    """Native ID mapping failure → ExternalEvent saved, transition_to skipped."""

    async def test_external_event_saved_when_mapping_fails(
        self,
        event_loop_fixture: RealTimeEventLoop,
        mock_external_event_repo: MagicMock,
        mock_broker_order_repo: MagicMock,
        mock_order_manager: MagicMock,
    ) -> None:
        """ExternalEvent is persisted even when native ID mapping fails."""
        # Arrange
        mock_broker_order_repo.get_by_native_order_id.return_value = None

        data = {
            "broker_order_id": "UNKNOWN_ORDER_ID",
            "stock_code": "005930",
            "filled_qty": "5",
            "filled_price": "50000",
            "filled_time": "143025",
            "side": OrderSide.BUY,
            "order_qty": "10",
        }

        # Act
        await event_loop_fixture._handle_fill_notification(data)

        # Assert
        mock_external_event_repo.add.assert_called_once()
        mock_order_manager.transition_to.assert_not_called()

    async def test_fill_event_not_saved_when_mapping_fails(
        self,
        event_loop_fixture: RealTimeEventLoop,
        mock_fill_repo: MagicMock,
        mock_broker_order_repo: MagicMock,
    ) -> None:
        """FillEventEntity is NOT persisted when native ID mapping fails."""
        # Arrange
        mock_broker_order_repo.get_by_native_order_id.return_value = None

        data = {
            "broker_order_id": "UNKNOWN_ORDER_ID",
            "stock_code": "005930",
            "filled_qty": "5",
            "filled_price": "50000",
            "filled_time": "143025",
            "side": OrderSide.BUY,
            "order_qty": "10",
        }

        # Act
        await event_loop_fixture._handle_fill_notification(data)

        # Assert
        mock_fill_repo.add.assert_not_called()


class TestDuplicateFillDetection:
    """Duplicate fill detection via dedup_key_hash."""

    async def test_duplicate_fill_skips_fill_event(
        self,
        event_loop_fixture: RealTimeEventLoop,
        mock_external_event_repo: MagicMock,
        mock_fill_repo: MagicMock,
        mock_order_manager: MagicMock,
    ) -> None:
        """Duplicate fill → ExternalEvent saved, FillEvent and transition_to skipped."""
        # Arrange
        # Simulate that the ExternalEvent was already persisted (dedup hit)
        existing_event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="fill_notification",
            source_name="broker_ws",
            published_at=datetime.now(tz=timezone.utc),
            source_reliability_tier="T1",
            source_event_id="H0STCNI0:KIS12345678:143025",
            ingested_at=datetime.now(tz=timezone.utc),
            dedup_key_hash="fill:KIS12345678:143025",
        )
        mock_external_event_repo.find_by_dedup_key.return_value = existing_event

        data = {
            "broker_order_id": "KIS12345678",
            "stock_code": "005930",
            "filled_qty": "5",
            "filled_price": "50000",
            "filled_time": "143025",
            "side": OrderSide.BUY,
            "order_qty": "10",
        }

        # Act
        await event_loop_fixture._handle_fill_notification(data)

        # Assert
        # ExternalEvent is still saved (append-only ingest)
        mock_external_event_repo.add.assert_called_once()
        # FillEvent is skipped because dedup hit
        mock_fill_repo.add.assert_not_called()
        # OrderManager transition is skipped
        mock_order_manager.transition_to.assert_not_called()


class TestGapFillFieldMapping:
    """Gap fill path with correct FillEvent model field mapping."""

    async def test_gap_fill_external_event_fields(
        self,
        event_loop_fixture: RealTimeEventLoop,
        mock_adapter: MagicMock,
        mock_external_event_repo: MagicMock,
    ) -> None:
        """Gap fill persists ExternalEventEntity with correct field mapping."""
        # Arrange
        now = datetime.now(tz=timezone.utc)
        fill_event = FillEvent(
            broker_name="koreainvestment",
            broker_order_id="KIS12345678",
            symbol="005930",
            side=OrderSide.BUY,
            fill_quantity=Decimal("5"),
            fill_price=Decimal("50500"),
            fill_timestamp=now,
        )
        mock_adapter.get_fills.return_value = [fill_event]

        # Act
        await event_loop_fixture.trigger_gap_fill(
            symbol="005930",
            account_ref="test-account-01",
            from_time=now,
        )

        # Assert
        mock_external_event_repo.add.assert_called_once()
        call_args = mock_external_event_repo.add.call_args[0][0]
        assert isinstance(call_args, ExternalEventEntity)
        assert call_args.event_type == "gap_fill_fill"
        assert call_args.source_name == EventSource.RECONCILIATION.value
        assert call_args.source_reliability_tier == SourceReliabilityTier.T1_REGULATORY.value
        assert call_args.symbol == "005930"
        assert call_args.dedup_key_hash == f"gap_fill:KIS12345678:{fill_event.fill_timestamp}"
        # Verify FillEvent model fields are used correctly
        metadata = call_args.metadata
        assert metadata["fill_quantity"] == "5"
        assert metadata["fill_price"] == "50500"
        assert metadata["broker_order_id"] == "KIS12345678"


class TestTradePriceAndOrderbook:
    """Trade price and orderbook ingest paths."""

    async def test_trade_price_external_event(
        self,
        event_loop_fixture: RealTimeEventLoop,
        mock_external_event_repo: MagicMock,
    ) -> None:
        """Trade price persists ExternalEventEntity with correct fields."""
        # Arrange
        data = {
            "stock_code": "005930",
            "trade_time": "143025",
            "trade_price": "85000",
            "trade_volume": "1000",
        }

        # Act
        await event_loop_fixture._handle_trade_price(data)

        # Assert
        mock_external_event_repo.add.assert_called_once()
        call_args = mock_external_event_repo.add.call_args[0][0]
        assert call_args.event_type == "trade_price"
        assert call_args.source_name == EventSource.BROKER_WS.value
        assert call_args.source_reliability_tier == SourceReliabilityTier.T1_REGULATORY.value
        assert call_args.source_event_id == "H0STCNT0:005930:143025"
        assert call_args.symbol == "005930"
        assert call_args.dedup_key_hash == "trade:005930:143025:85000"
        assert call_args.published_at is not None

    async def test_orderbook_external_event(
        self,
        event_loop_fixture: RealTimeEventLoop,
        mock_external_event_repo: MagicMock,
    ) -> None:
        """Orderbook persists ExternalEventEntity with correct fields."""
        # Arrange
        data = {
            "stock_code": "005930",
            "time": "143025",
        }

        # Act
        await event_loop_fixture._handle_orderbook(data)

        # Assert
        mock_external_event_repo.add.assert_called_once()
        call_args = mock_external_event_repo.add.call_args[0][0]
        assert call_args.event_type == "orderbook"
        assert call_args.source_name == EventSource.BROKER_WS.value
        assert call_args.source_reliability_tier == SourceReliabilityTier.T1_REGULATORY.value
        assert call_args.source_event_id == "H0STASP0:005930:143025"
        assert call_args.symbol == "005930"
        assert call_args.dedup_key_hash == "orderbook:005930:143025"
        assert call_args.published_at is not None
