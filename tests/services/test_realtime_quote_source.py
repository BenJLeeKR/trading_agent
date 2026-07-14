"""Unit tests for ``InMemoryMockQuoteSource`` (Phase 1 mock realtime quote source)."""

from __future__ import annotations

import pytest

from agent_trading.services.realtime_quote_source import (
    MAX_DAILY_PRICE_HISTORY,
    MAX_TRADE_HISTORY,
    ConnectionState,
    InMemoryMockQuoteSource,
    InstrumentInfo,
    InvalidSymbolError,
    SubscriptionLimitExceededError,
)


@pytest.fixture
def source() -> InMemoryMockQuoteSource:
    return InMemoryMockQuoteSource()


class TestConnectionAndCapacity:
    def test_defaults(self, source: InMemoryMockQuoteSource) -> None:
        assert source.environment == "mock"
        assert source.max_registrations == 30
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
        for i in range(15):
            await source.subscribe(f"{100000 + i:06d}")
        assert source.registered_count() == 30
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

    async def test_snapshot_includes_recent_trades(
        self, source: InMemoryMockQuoteSource
    ) -> None:
        await source.subscribe("005930")
        snapshot = source.get_snapshots(["005930"])["005930"]
        assert 0 < len(snapshot.recent_trades) <= MAX_TRADE_HISTORY
        first = snapshot.recent_trades[0]
        assert first.trade_time
        assert first.price > 0


class TestInstrumentInfoLookup:
    """``instruments`` 테이블 조회 배선 — ``InstrumentInfoResolver`` 연동."""

    async def test_subscribe_uses_instrument_lookup_over_placeholder(self) -> None:
        """조회 콜백이 채워지면 하드코딩된 mock dict 대신 그 결과를 쓴다."""
        calls: list[str] = []

        async def lookup(symbol: str) -> InstrumentInfo | None:
            calls.append(symbol)
            return InstrumentInfo(symbol=symbol, name="DB종목명", market="KOSDAQ")

        source = InMemoryMockQuoteSource(instrument_info_lookup=lookup)
        # "005930" is one of the seeded mock instruments (삼성전자/KOSPI) — the
        # real lookup result must win over that hardcoded fallback.
        await source.subscribe("005930")

        info = source.instrument_info("005930")
        assert info.name == "DB종목명"
        assert info.market == "KOSDAQ"
        assert calls == ["005930"]

    async def test_subscribe_calls_lookup_at_most_once_per_symbol(self) -> None:
        """같은 심볼을 여러 번 조회해도 DB lookup은 1회만 호출된다(N+1 방지)."""
        calls: list[str] = []

        async def lookup(symbol: str) -> InstrumentInfo | None:
            calls.append(symbol)
            return InstrumentInfo(symbol=symbol, name="DB종목명", market="KOSPI")

        source = InMemoryMockQuoteSource(instrument_info_lookup=lookup)
        await source.subscribe("005930")
        # Repeated snapshot/instrument_info reads must never re-trigger the lookup.
        source.get_snapshots(["005930"])
        source.get_snapshots(["005930"])
        source.instrument_info("005930")

        assert calls == ["005930"]

    async def test_lookup_miss_falls_back_to_placeholder(self) -> None:
        """DB에 없는 심볼(lookup이 ``None`` 반환)은 기존 placeholder로 폴백한다."""

        async def lookup(symbol: str) -> InstrumentInfo | None:
            return None

        source = InMemoryMockQuoteSource(instrument_info_lookup=lookup)
        await source.subscribe("999999")

        info = source.instrument_info("999999")
        assert info.market == "UNKNOWN"
        assert "999999" in info.name

    async def test_lookup_exception_falls_back_to_placeholder(self) -> None:
        """조회 콜백이 예외를 던져도 구독 자체는 실패하지 않고 placeholder로 폴백한다."""

        async def lookup(symbol: str) -> InstrumentInfo | None:
            raise RuntimeError("DB down")

        source = InMemoryMockQuoteSource(instrument_info_lookup=lookup)
        await source.subscribe("005930")  # must not raise

        info = source.instrument_info("005930")
        assert info.name == "삼성전자"
        assert info.market == "KOSPI"

    async def test_unsubscribe_then_resubscribe_refreshes_stale_cache(self) -> None:
        """구독 취소 후 재구독하면 DB를 다시 조회한다(최초 조회 이후 DB에 값이 생긴 경우).

        회귀 버그: ``warm()``은 캐시가 있으면 무조건 스킵하는데,
        ``unsubscribe()``가 캐시를 지우지 않으면 최초 구독 시점에
        instruments 테이블에 없어 placeholder로 캐싱된 심볼은 나중에 DB에
        실제 데이터가 생겨도 재구독 시 계속 placeholder만 반환한다
        (실측: 069500을 instruments에 추가하기 전에 구독한 적이 있으면,
        추가 후 구독취소/재구독을 해도 종목정보가 갱신되지 않음).
        """
        calls: list[str] = []

        async def lookup(symbol: str) -> InstrumentInfo | None:
            calls.append(symbol)
            if len(calls) == 1:
                return None  # 최초 구독 시점 — 아직 instruments 테이블에 없음
            return InstrumentInfo(symbol=symbol, name="KODEX 200", market="KOSPI")

        source = InMemoryMockQuoteSource(instrument_info_lookup=lookup)
        await source.subscribe("069500")
        assert source.instrument_info("069500").market == "UNKNOWN"  # placeholder 캐싱됨

        await source.unsubscribe("069500")
        await source.subscribe("069500")  # DB에 이제 실제 데이터가 있음

        info = source.instrument_info("069500")
        assert info.name == "KODEX 200"
        assert info.market == "KOSPI"
        assert calls == ["069500", "069500"]  # 재구독 시 다시 조회했어야 함

    def test_no_lookup_configured_preserves_existing_behavior(
        self, source: InMemoryMockQuoteSource
    ) -> None:
        """lookup을 주지 않으면(기본값) 기존 mock dict/placeholder 그대로 동작한다."""
        info = source.instrument_info("138040")
        assert info.name == "메리츠금융지주"
        assert info.market == "KOSPI"


class TestDailyPrice:
    async def test_returns_bars_up_to_max_history(
        self, source: InMemoryMockQuoteSource
    ) -> None:
        bars = await source.get_daily_price("005930")
        assert len(bars) == MAX_DAILY_PRICE_HISTORY
        assert all(bar.date for bar in bars)
        assert all(bar.close > 0 for bar in bars)

    async def test_respects_count_below_max(self, source: InMemoryMockQuoteSource) -> None:
        bars = await source.get_daily_price("005930", count=5)
        assert len(bars) == 5

    async def test_count_above_max_is_capped(self, source: InMemoryMockQuoteSource) -> None:
        bars = await source.get_daily_price("005930", count=1000)
        assert len(bars) == MAX_DAILY_PRICE_HISTORY

    async def test_invalid_symbol_raises(self, source: InMemoryMockQuoteSource) -> None:
        with pytest.raises(InvalidSymbolError):
            await source.get_daily_price("ABC")
