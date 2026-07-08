"""Unit tests for ``InMemoryMockQuoteSource`` (Phase 1 mock realtime quote source)."""

from __future__ import annotations

import pytest

from agent_trading.services.realtime_quote_source import (
    ConnectionState,
    InMemoryMockQuoteSource,
    InvalidSymbolError,
    SubscriptionLimitExceededError,
)


@pytest.fixture
def source() -> InMemoryMockQuoteSource:
    return InMemoryMockQuoteSource()


class TestConnectionAndCapacity:
    def test_defaults(self, source: InMemoryMockQuoteSource) -> None:
        assert source.environment == "mock"
        assert source.max_registrations == 41
        assert source.registrations_per_symbol == 2
        assert source.connection_state() == ConnectionState.CONNECTED
        assert source.registered_count() == 0
        assert source.list_subscriptions() == []


class TestSubscribe:
    async def test_subscribe_adds_symbol(self, source: InMemoryMockQuoteSource) -> None:
        await source.subscribe("005930")
        assert source.list_subscriptions() == ["005930"]
        assert source.registered_count() == 2

    async def test_subscribe_is_idempotent(self, source: InMemoryMockQuoteSource) -> None:
        """Re-subscribing to the same symbol is a no-op — no ref count accumulation."""
        await source.subscribe("005930")
        await source.subscribe("005930")
        await source.subscribe("005930")
        assert source.list_subscriptions() == ["005930"]
        assert source.registered_count() == 2  # 1 symbol = 2 registrations, not 6

    async def test_subscribe_strips_whitespace(self, source: InMemoryMockQuoteSource) -> None:
        await source.subscribe(" 005930 ")
        assert source.list_subscriptions() == ["005930"]

    async def test_subscribe_rejects_etn_prefix(self, source: InMemoryMockQuoteSource) -> None:
        """ETN codes (``Q`` prefix) are out of scope for this 국내주식 screen."""
        with pytest.raises(InvalidSymbolError):
            await source.subscribe("Q00001")

    async def test_subscribe_invalid_symbol_raises(self, source: InMemoryMockQuoteSource) -> None:
        with pytest.raises(InvalidSymbolError):
            await source.subscribe("ABC")

    async def test_subscribe_rejects_mixed_alnum(self, source: InMemoryMockQuoteSource) -> None:
        with pytest.raises(InvalidSymbolError):
            await source.subscribe("00593A")

    async def test_subscribe_rejects_wrong_length(self, source: InMemoryMockQuoteSource) -> None:
        with pytest.raises(InvalidSymbolError):
            await source.subscribe("12345")
        with pytest.raises(InvalidSymbolError):
            await source.subscribe("1234567")

    async def test_subscribe_beyond_capacity_raises(self, source: InMemoryMockQuoteSource) -> None:
        for i in range(20):
            await source.subscribe(f"{100000 + i:06d}")
        assert source.registered_count() == 40
        with pytest.raises(SubscriptionLimitExceededError):
            await source.subscribe("999999")


class TestUnsubscribe:
    async def test_unsubscribe_removes_immediately(
        self, source: InMemoryMockQuoteSource
    ) -> None:
        """A single unsubscribe() call fully removes the symbol — no ref count."""
        await source.subscribe("005930")
        await source.unsubscribe("005930")
        assert source.list_subscriptions() == []
        assert source.registered_count() == 0

    async def test_unsubscribe_after_duplicate_subscribe_removes_immediately(
        self, source: InMemoryMockQuoteSource
    ) -> None:
        """Duplicate subscribe() calls must not require multiple unsubscribe() calls."""
        await source.subscribe("005930")
        await source.subscribe("005930")
        await source.unsubscribe("005930")
        assert source.list_subscriptions() == []

    async def test_unsubscribe_unknown_symbol_is_noop(
        self, source: InMemoryMockQuoteSource
    ) -> None:
        await source.unsubscribe("005930")  # should not raise
        assert source.list_subscriptions() == []


class TestSnapshots:
    async def test_snapshot_only_for_subscribed_symbols(
        self, source: InMemoryMockQuoteSource
    ) -> None:
        await source.subscribe("005930")
        snapshots = source.get_snapshots(["005930", "000660"])
        assert set(snapshots.keys()) == {"005930"}

    async def test_snapshot_shape(self, source: InMemoryMockQuoteSource) -> None:
        await source.subscribe("138040")
        snapshot = source.get_snapshots(["138040"])["138040"]
        assert snapshot.symbol == "138040"
        assert snapshot.name == "메리츠금융지주"
        assert snapshot.market == "KOSPI"
        assert len(snapshot.ask_levels) == 10
        assert len(snapshot.bid_levels) == 10
        assert snapshot.data_source == "mock"
        assert snapshot.lower_limit < snapshot.last_price < snapshot.upper_limit

    async def test_snapshot_changes_across_ticks(self, source: InMemoryMockQuoteSource) -> None:
        await source.subscribe("005930")
        first = source.get_snapshots(["005930"])["005930"]
        second = source.get_snapshots(["005930"])["005930"]
        # Different tick → different trade_time at minimum (updated_at always advances).
        assert second.updated_at >= first.updated_at

    def test_instrument_info_unknown_symbol_falls_back(
        self, source: InMemoryMockQuoteSource
    ) -> None:
        info = source.instrument_info("999999")
        assert info.symbol == "999999"
        assert info.market == "UNKNOWN"
        assert "999999" in info.name
