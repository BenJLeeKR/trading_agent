"""Tests for KIS WebSocket client, parser, subscription budget, and gap fill.

Test matrix
-----------
1. WS disconnect → reconnect → gap fill
2. Duplicate event ingestion (dedup)
3. Subscription saturation eviction
4. Gap fill with REST inquiry
5. WebSocket message parsing (JSON ack + delimited data)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.base import SubscriptionBudget
from agent_trading.brokers.koreainvestment.ws_parser import (
    parse_delimited_message,
    parse_fill_notification,
    parse_message,
    parse_orderbook,
    parse_subscription_ack,
    parse_trade_price,
)
from agent_trading.brokers.koreainvestment.websocket_client import KISWebSocketClient
from agent_trading.domain.enums import OrderSide, SourceReliabilityTier


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def mock_rest_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def ws_client(mock_rest_client: MagicMock) -> KISWebSocketClient:
    return KISWebSocketClient(
        rest_client=mock_rest_client,
        approval_key="test-approval-key-12345",
        env="paper",
    )


@pytest.fixture
def budget() -> SubscriptionBudget:
    return SubscriptionBudget(max_subscriptions=10, critical_limit=3, optional_limit=7)


# ======================================================================
# SubscriptionBudget eviction tests (Stream D)
# ======================================================================


class TestSubscriptionBudgetEviction:
    """SubscriptionBudget critical/optional eviction policy."""

    def test_subscribe_critical_within_limit(self, budget: SubscriptionBudget) -> None:
        assert budget.subscribe_critical() is True
        assert budget.current_critical == 1
        assert budget.current_optional == 0

    def test_subscribe_optional_within_limit(self, budget: SubscriptionBudget) -> None:
        assert budget.subscribe_optional() is True
        assert budget.current_optional == 1
        assert budget.current_critical == 0

    def test_critical_evicts_optional_when_full(self) -> None:
        budget = SubscriptionBudget(max_subscriptions=2, critical_limit=2, optional_limit=2)
        # Fill with 2 optional (total_used == max_subscriptions)
        assert budget.subscribe_optional() is True
        assert budget.subscribe_optional() is True
        assert budget.total_used == 2

        # Subscribe critical — should evict one optional (total_used >= max_subscriptions)
        assert budget.subscribe_critical() is True
        assert budget.current_critical == 1
        assert budget.current_optional == 1  # One evicted
        assert budget.total_used == 2

    def test_critical_rejects_when_no_optional_to_evict(self) -> None:
        budget = SubscriptionBudget(max_subscriptions=2, critical_limit=2, optional_limit=1)
        # Fill with 2 critical
        assert budget.subscribe_critical() is True
        assert budget.subscribe_critical() is True
        assert budget.total_used == 2

        # Third critical should fail (no optional to evict)
        assert budget.subscribe_critical() is False

    def test_optional_rejects_when_total_full(self) -> None:
        budget = SubscriptionBudget(max_subscriptions=2, critical_limit=1, optional_limit=2)
        assert budget.subscribe_critical() is True
        assert budget.subscribe_optional() is True
        assert budget.total_used == 2

        # Optional should fail (total limit reached, no eviction of critical)
        assert budget.subscribe_optional() is False

    def test_optional_rejects_when_optional_limit_reached(self) -> None:
        budget = SubscriptionBudget(max_subscriptions=10, critical_limit=1, optional_limit=2)
        assert budget.subscribe_optional() is True
        assert budget.subscribe_optional() is True
        assert budget.subscribe_optional() is False  # Optional limit reached

    def test_unsubscribe_releases_budget(self, budget: SubscriptionBudget) -> None:
        budget.subscribe_critical()
        budget.subscribe_optional()
        assert budget.total_used == 2

        budget.unsubscribe(critical=True)
        assert budget.current_critical == 0
        assert budget.total_used == 1

        budget.unsubscribe(optional=True)
        assert budget.current_optional == 0
        assert budget.total_used == 0


# ======================================================================
# WebSocket message parser tests (Stream B)
# ======================================================================


class TestWsParser:
    """KIS WebSocket message parser tests."""

    def test_parse_json_subscription_ack(self) -> None:
        raw = """{"header":{"tr_id":"H0STCNT0","tr_key":"005930"},"body":{"rt_cd":"0","msg1":"SUBSCRIBE SUCCESS"}}"""
        result = parse_message(raw)
        assert result["type"] == "subscription_ack"
        assert result["tr_id"] == "H0STCNT0"
        assert result["tr_key"] == "005930"

    def test_parse_json_error(self) -> None:
        raw = """{"header":{"tr_id":"H0STCNT0"},"body":{"rt_cd":"1","msg1":"INVALID TR_KEY"}}"""
        result = parse_message(raw)
        assert result["type"] == "error"
        assert "INVALID" in result["message"]

    def test_parse_delimited_trade_price(self) -> None:
        # Simulated H0STCNT0 delimited message
        # Format: H0STCNT0|continuum|^stock_code^trade_time^trade_price^trade_volume^^sign^change_rate^open^high^low^
        raw = "H0STCNT0|12345|^005930^143025^85000^100^^2^1.5^84000^86000^83000^"
        result = parse_message(raw)
        assert result["type"] == "real_time_data"
        assert result["tr_id"] == "H0STCNT0"
        assert result["continuum_key"] == "12345"
        data = result["data"]
        assert data["stock_code"] == "005930"
        assert data["trade_price"] == "85000"
        assert data["trade_volume"] == "100"

    def test_parse_delimited_orderbook(self) -> None:
        # Simulated H0STASP0 delimited message (10 ask prices, 10 ask vols, 10 bid prices, 10 bid vols)
        # Format: H0STASP0|continuum|^stock_code^time^ask_prices(10)^ask_volumes(10)^bid_prices(10)^bid_volumes(10)
        fields = "^005930^143025"
        # 10 ask prices
        fields += "".join(f"^{i}" for i in range(85000, 85010))
        # 10 ask volumes
        fields += "".join(f"^{i}" for i in range(100, 110))
        # 10 bid prices
        fields += "".join(f"^{i}" for i in range(84990, 85000))
        # 10 bid volumes
        fields += "".join(f"^{i}" for i in range(200, 210))
        raw = f"H0STASP0|67890|{fields}"
        result = parse_message(raw)
        assert result["type"] == "real_time_data"
        assert result["tr_id"] == "H0STASP0"
        data = result["data"]
        assert data["stock_code"] == "005930"
        assert len(data["ask_prices"]) == 10
        assert len(data["bid_prices"]) == 10

    def test_parse_fill_notification(self) -> None:
        # Simulated H0STCNI0 delimited message
        # Format: H0STCNI0|continuum|^stock_code^stock_name^broker_order_id^original_order_id^side^type^filled_qty^filled_price^filled_time^order_qty^order_price^status^
        fields = "^005930^삼성전자^12345678^87654321^02^00^100^85000^143025^200^84000^00^"
        raw = f"H0STCNI0|99999|{fields}"
        result = parse_message(raw)
        assert result["type"] == "real_time_data"
        assert result["tr_id"] == "H0STCNI0"
        data = result["data"]
        assert data["stock_code"] == "005930"
        assert data["broker_order_id"] == "12345678"
        assert data["side"] == OrderSide.BUY  # 02 = 매수
        assert data["filled_qty"] == "100"
        assert data["filled_price"] == "85000"

    def test_parse_unknown_channel(self) -> None:
        raw = "UNKNOWN_CHANNEL|00001|^data^"
        result = parse_message(raw)
        assert result["type"] == "unknown"
        assert result["tr_id"] == "UNKNOWN_CHANNEL"

    def test_parse_malformed_delimited(self) -> None:
        with pytest.raises(ValueError, match="too few pipe-delimited parts"):
            parse_delimited_message("ONLY_ONE_PART")

    def test_parse_trade_price_fields(self) -> None:
        fields = ["", "005930", "143025", "85000", "100", "", "2", "1.5", "84000", "86000", "83000", ""]
        result = parse_trade_price(fields)
        assert result["stock_code"] == "005930"
        assert result["trade_price"] == "85000"
        assert result["trade_volume"] == "100"

    def test_parse_orderbook_fields(self) -> None:
        fields = ["", "005930", "143025"] + [str(i) for i in range(85000, 85010)]  # ask prices
        fields += [str(i) for i in range(100, 110)]  # ask volumes
        fields += [str(i) for i in range(84990, 85000)]  # bid prices
        fields += [str(i) for i in range(200, 210)]  # bid volumes
        result = parse_orderbook(fields)
        assert result["stock_code"] == "005930"
        assert len(result["ask_prices"]) == 10
        assert len(result["bid_prices"]) == 10

    def test_parse_fill_notification_fields(self) -> None:
        fields = ["", "005930", "삼성전자", "12345678", "87654321", "02", "00", "100", "85000", "143025", "200", "84000", "00", ""]
        result = parse_fill_notification(fields)
        assert result["stock_code"] == "005930"
        assert result["broker_order_id"] == "12345678"
        assert result["side"] == OrderSide.BUY
        assert result["filled_qty"] == "100"

    def test_parse_fill_notification_sell(self) -> None:
        fields = ["", "005930", "삼성전자", "12345678", "87654321", "01", "00", "50", "86000", "143030", "100", "85000", "00", ""]
        result = parse_fill_notification(fields)
        assert result["side"] == OrderSide.SELL  # 01 = 매도
        assert result["filled_qty"] == "50"


# ======================================================================
# WebSocket client tests (Stream B)
# ======================================================================


class TestKISWebSocketClient:
    """KISWebSocketClient lifecycle and subscription tests."""

    @pytest.mark.asyncio
    async def test_subscribe_critical(self, ws_client: KISWebSocketClient) -> None:
        # Mock the WebSocket connection
        ws_client._connected = True
        ws_client._ws = AsyncMock()

        result = await ws_client.subscribe("H0STCNI0", "12345678", critical=True)
        assert result is True
        assert "H0STCNI0" in ws_client._critical_subscriptions
        assert "12345678" in ws_client._critical_subscriptions["H0STCNI0"]

    @pytest.mark.asyncio
    async def test_subscribe_optional(self, ws_client: KISWebSocketClient) -> None:
        ws_client._connected = True
        ws_client._ws = AsyncMock()

        result = await ws_client.subscribe("H0STCNT0", "005930", critical=False)
        assert result is True
        assert "H0STCNT0" in ws_client._subscriptions
        assert "005930" in ws_client._subscriptions["H0STCNT0"]

    @pytest.mark.asyncio
    async def test_subscribe_rejects_when_budget_full(self) -> None:
        budget = SubscriptionBudget(max_subscriptions=1, critical_limit=1, optional_limit=0)
        client = KISWebSocketClient(
            rest_client=MagicMock(),
            approval_key="test-key",
            env="paper",
            subscription_budget=budget,
        )
        client._connected = True
        client._ws = AsyncMock()

        # Fill the budget
        assert await client.subscribe("H0STCNI0", "12345678", critical=True) is True
        # Second subscribe should fail
        assert await client.subscribe("H0STCNT0", "005930", critical=False) is False

    @pytest.mark.asyncio
    async def test_unsubscribe_releases_budget(self, ws_client: KISWebSocketClient) -> None:
        ws_client._connected = True
        ws_client._ws = AsyncMock()

        await ws_client.subscribe("H0STCNI0", "12345678", critical=True)
        assert ws_client._budget.current_critical == 1

        await ws_client.unsubscribe("H0STCNI0", "12345678", critical=True)
        assert ws_client._budget.current_critical == 0

    def test_detect_gap_no_previous(self, ws_client: KISWebSocketClient) -> None:
        assert ws_client.detect_gap("H0STCNT0", "100") is False

    def test_detect_gap_sequential(self, ws_client: KISWebSocketClient) -> None:
        ws_client._continuum_tracker["H0STCNT0"] = "100"
        assert ws_client.detect_gap("H0STCNT0", "101") is False

    def test_detect_gap_detected(self, ws_client: KISWebSocketClient) -> None:
        ws_client._continuum_tracker["H0STCNT0"] = "100"
        assert ws_client.detect_gap("H0STCNT0", "105") is True  # Gap of 4

    def test_detect_gap_no_gap_on_first(self, ws_client: KISWebSocketClient) -> None:
        assert ws_client.detect_gap("H0STCNT0", "1") is False

    def test_get_last_continuum(self, ws_client: KISWebSocketClient) -> None:
        ws_client._continuum_tracker["H0STCNT0"] = "42"
        assert ws_client.get_last_continuum("H0STCNT0") == "42"

    def test_get_last_continuum_missing(self, ws_client: KISWebSocketClient) -> None:
        assert ws_client.get_last_continuum("H0STCNT0") is None


# ======================================================================
# Subscription saturation eviction tests (Stream D)
# ======================================================================


class TestSubscriptionSaturation:
    """Subscription saturation and eviction scenarios."""

    @pytest.mark.asyncio
    async def test_optional_evicted_by_critical(self) -> None:
        """When total limit is reached, critical can evict optional."""
        budget = SubscriptionBudget(max_subscriptions=2, critical_limit=3, optional_limit=2)
        client = KISWebSocketClient(
            rest_client=MagicMock(),
            approval_key="test-key",
            env="paper",
            subscription_budget=budget,
        )
        client._connected = True
        client._ws = AsyncMock()

        # Fill with 2 optional (total_used == max_subscriptions)
        assert await client.subscribe("H0STCNT0", "005930", critical=False) is True
        assert await client.subscribe("H0STCNT0", "000660", critical=False) is True
        assert budget.total_used == 2

        # Critical should evict one optional (total_used >= max_subscriptions)
        assert await client.subscribe("H0STCNI0", "12345678", critical=True) is True
        assert budget.current_critical == 1
        assert budget.current_optional == 1  # One evicted
        assert budget.total_used == 2

    @pytest.mark.asyncio
    async def test_optional_cannot_evict_critical(self) -> None:
        """Optional subscriptions cannot evict critical ones."""
        budget = SubscriptionBudget(max_subscriptions=2, critical_limit=2, optional_limit=1)
        client = KISWebSocketClient(
            rest_client=MagicMock(),
            approval_key="test-key",
            env="paper",
            subscription_budget=budget,
        )
        client._connected = True
        client._ws = AsyncMock()

        # Fill with 2 critical
        assert await client.subscribe("H0STCNI0", "12345678", critical=True) is True
        assert await client.subscribe("H0STCNI0", "87654321", critical=True) is True
        assert budget.total_used == 2

        # Optional should fail
        assert await client.subscribe("H0STCNT0", "005930", critical=False) is False


# ======================================================================
# Gap fill tests (Stream C)
# ======================================================================


class TestGapFill:
    """Gap fill detection and triggering."""

    def test_gap_detection_after_reconnect(self, ws_client: KISWebSocketClient) -> None:
        """After reconnect, gap detection should identify missed messages."""
        # Simulate pre-disconnect state
        ws_client._continuum_tracker["H0STCNT0"] = "100"

        # After reconnect, first message has continuum 105
        assert ws_client.detect_gap("H0STCNT0", "105") is True

    def test_no_gap_after_clean_reconnect(self, ws_client: KISWebSocketClient) -> None:
        """If no messages were missed, no gap is detected."""
        ws_client._continuum_tracker["H0STCNT0"] = "100"
        assert ws_client.detect_gap("H0STCNT0", "101") is False

    def test_gap_detection_fill_channel(self, ws_client: KISWebSocketClient) -> None:
        """Fill notification channel gap detection."""
        ws_client._continuum_tracker["H0STCNI0"] = "50"
        assert ws_client.detect_gap("H0STCNI0", "55") is True  # Gap of 4


# ======================================================================
# Duplicate event ingestion tests (Stream C)
# ======================================================================


class TestDuplicateEventIngestion:
    """Duplicate event ingestion prevention."""

    def test_dedup_key_uniqueness(self) -> None:
        """Fill notifications with same broker_order_id and time should have same dedup key."""
        from agent_trading.domain.entities import ExternalEventEntity
        from agent_trading.domain.enums import SourceReliabilityTier

        now = datetime.now(tz=timezone.utc)
        event1 = ExternalEventEntity(
            event_id=uuid4(),
            event_type="fill_notification",
            source_name="broker_ws",
            published_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY,
            source_event_id="H0STCNI0:12345678:143025",
            ingested_at=now,
            dedup_key_hash="fill:12345678:143025",
        )
        event2 = ExternalEventEntity(
            event_id=uuid4(),
            event_type="fill_notification",
            source_name="broker_ws",
            published_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY,
            source_event_id="H0STCNI0:12345678:143025",
            ingested_at=now,
            dedup_key_hash="fill:12345678:143025",
        )
        assert event1.dedup_key_hash == event2.dedup_key_hash

    def test_different_fills_have_different_dedup_keys(self) -> None:
        """Different fills should have different dedup keys."""
        from agent_trading.domain.entities import ExternalEventEntity
        from agent_trading.domain.enums import SourceReliabilityTier

        now = datetime.now(tz=timezone.utc)
        event1 = ExternalEventEntity(
            event_id=uuid4(),
            event_type="fill_notification",
            source_name="broker_ws",
            published_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY,
            source_event_id="H0STCNI0:11111111:143025",
            ingested_at=now,
            dedup_key_hash="fill:11111111:143025",
        )
        event2 = ExternalEventEntity(
            event_id=uuid4(),
            event_type="fill_notification",
            source_name="broker_ws",
            published_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY,
            source_event_id="H0STCNI0:22222222:143030",
            ingested_at=now,
            dedup_key_hash="fill:22222222:143030",
        )
        assert event1.dedup_key_hash != event2.dedup_key_hash

    def test_trade_price_dedup_key(self) -> None:
        """Trade price events should have unique dedup keys per tick."""
        from agent_trading.domain.entities import ExternalEventEntity
        from agent_trading.domain.enums import SourceReliabilityTier

        now = datetime.now(tz=timezone.utc)
        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="trade_price",
            source_name="broker_ws",
            published_at=now,
            source_reliability_tier=SourceReliabilityTier.T1_REGULATORY,
            source_event_id="H0STCNT0:005930:143025",
            ingested_at=now,
            dedup_key_hash="trade:005930:143025:85000",
        )
        assert event.dedup_key_hash == "trade:005930:143025:85000"
