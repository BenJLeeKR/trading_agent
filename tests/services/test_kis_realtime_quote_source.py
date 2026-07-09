"""Unit tests for ``KisRealtimeQuoteSource`` (Step 3 — KIS-backed realtime quote source).

No real network calls are made. ``KISWebSocketClient`` is replaced with a
lightweight in-memory fake, and ``KISRestClient`` is a ``MagicMock`` with
``AsyncMock`` methods for ``get_approval_key`` / ``get_quote`` / ``close``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_trading.services import kis_realtime_quote_source as kqs
from agent_trading.services.kis_realtime_quote_source import KisRealtimeQuoteSource
from agent_trading.services.realtime_quote_source import (
    ConnectionState,
    InvalidSymbolError,
    SubscriptionLimitExceededError,
)


class FakeWSClient:
    """Minimal stand-in for ``KISWebSocketClient`` — no network, no asyncio.Queue timing."""

    def __init__(self, *, rest_client, approval_key, env, subscription_budget, ws_url):
        self.rest_client = rest_client
        self.approval_key = approval_key
        self.env = env
        self.subscription_budget = subscription_budget
        self.ws_url = ws_url
        self._connected = False
        self._reconnecting = False
        self.subscribe_calls: list[tuple[str, str]] = []
        self.unsubscribe_calls: list[tuple[str, str]] = []
        self.subscribe_result = True
        self.subscribe_result_queue: list[bool] = []
        self.connect_should_fail = False
        self._queue: asyncio.Queue = asyncio.Queue()

    async def connect(self) -> None:
        if self.connect_should_fail:
            raise ConnectionError("simulated KIS WebSocket connect failure")
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_reconnecting(self) -> bool:
        return self._reconnecting

    async def subscribe(self, channel: str, tr_key: str, *, critical: bool = False) -> bool:
        self.subscribe_calls.append((channel, tr_key))
        if self.subscribe_result_queue:
            return self.subscribe_result_queue.pop(0)
        return self.subscribe_result

    async def unsubscribe(self, channel: str, tr_key: str, *, critical: bool = False) -> None:
        self.unsubscribe_calls.append((channel, tr_key))

    async def messages(self):
        while True:
            msg = await self._queue.get()
            if msg is None:
                return
            yield msg

    async def push(self, msg: dict) -> None:
        await self._queue.put(msg)

    async def stop_messages(self) -> None:
        await self._queue.put(None)


def _make_rest_client() -> MagicMock:
    rest_client = MagicMock()
    rest_client.get_approval_key = AsyncMock(return_value="test-approval-key")
    rest_client.get_quote = AsyncMock(return_value={})
    rest_client.close = AsyncMock()
    return rest_client


@pytest.fixture
def fake_ws_client_factory(monkeypatch: pytest.MonkeyPatch):
    """Patch ``KISWebSocketClient`` used inside the module under test.

    ``created.should_fail_connect["value"] = True`` (set *before* calling
    ``source.connect()``) makes the next-constructed ``FakeWSClient.connect()``
    raise, to exercise the connect-failure cleanup path.
    """
    class _Created(list):
        """Plain list subclass — allows attaching ``should_fail_connect`` for tests."""

    created = _Created()
    should_fail_connect = {"value": False}

    def _factory(**kwargs):
        client = FakeWSClient(**kwargs)
        client.connect_should_fail = should_fail_connect["value"]
        created.append(client)
        return client

    monkeypatch.setattr(kqs, "KISWebSocketClient", _factory)
    created.should_fail_connect = should_fail_connect
    return created


@pytest.fixture
async def connected_source(fake_ws_client_factory) -> KisRealtimeQuoteSource:
    rest_client = _make_rest_client()
    source = KisRealtimeQuoteSource(rest_client=rest_client, ws_url="ws://fake")
    await source.connect()
    yield source
    await source.aclose()


def _fake_ws(source: KisRealtimeQuoteSource) -> FakeWSClient:
    assert source._ws_client is not None
    return source._ws_client  # type: ignore[return-value]


class TestConnectLifecycle:
    async def test_connect_fetches_approval_key_and_connects_ws(
        self, fake_ws_client_factory
    ) -> None:
        rest_client = _make_rest_client()
        source = KisRealtimeQuoteSource(rest_client=rest_client, ws_url="ws://fake")
        await source.connect()
        try:
            rest_client.get_approval_key.assert_awaited_once()
            assert len(fake_ws_client_factory) == 1
            assert fake_ws_client_factory[0].approval_key == "test-approval-key"
            assert fake_ws_client_factory[0].ws_url == "ws://fake"
            assert source.connection_state() == ConnectionState.CONNECTED
            assert source.environment == "live"
        finally:
            await source.aclose()

    async def test_connect_is_idempotent(self, connected_source: KisRealtimeQuoteSource) -> None:
        rest_client = connected_source._rest_client
        await connected_source.connect()  # second call while already connected
        assert rest_client.get_approval_key.await_count == 1

    async def test_aclose_disconnects_and_closes_rest_client(
        self, fake_ws_client_factory
    ) -> None:
        rest_client = _make_rest_client()
        source = KisRealtimeQuoteSource(rest_client=rest_client, ws_url="ws://fake")
        await source.connect()
        ws = _fake_ws(source)
        await source.aclose()
        assert ws.is_connected is False
        rest_client.close.assert_awaited_once()
        assert source.connection_state() == ConnectionState.DISCONNECTED

    async def test_connection_state_reflects_reconnecting(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        ws = _fake_ws(connected_source)
        ws._connected = False
        ws._reconnecting = True
        assert connected_source.connection_state() == ConnectionState.RECONNECTING

    async def test_connect_failure_during_ws_connect_cleans_up(
        self, fake_ws_client_factory
    ) -> None:
        """WS-level connect() failure must self-clean, not leak the rest client/ws client."""
        fake_ws_client_factory.should_fail_connect["value"] = True
        rest_client = _make_rest_client()
        source = KisRealtimeQuoteSource(rest_client=rest_client, ws_url="ws://fake")

        with pytest.raises(ConnectionError):
            await source.connect()

        rest_client.close.assert_awaited_once()
        assert source._ws_client is None
        assert source._consumer_task is None
        assert source.connection_state() == ConnectionState.DISCONNECTED

    async def test_connect_failure_during_approval_key_cleans_up(self) -> None:
        """Failure before the WS client is even constructed must still close the REST client."""
        rest_client = _make_rest_client()
        rest_client.get_approval_key = AsyncMock(side_effect=RuntimeError("approval failed"))
        source = KisRealtimeQuoteSource(rest_client=rest_client, ws_url="ws://fake")

        with pytest.raises(RuntimeError):
            await source.connect()

        rest_client.close.assert_awaited_once()
        assert source._ws_client is None

    async def test_retry_after_connect_failure_succeeds(
        self, fake_ws_client_factory
    ) -> None:
        """After a failed connect(), the instance must be retryable."""
        fake_ws_client_factory.should_fail_connect["value"] = True
        rest_client = _make_rest_client()
        source = KisRealtimeQuoteSource(rest_client=rest_client, ws_url="ws://fake")

        with pytest.raises(ConnectionError):
            await source.connect()

        fake_ws_client_factory.should_fail_connect["value"] = False
        await source.connect()  # retry — should succeed now
        try:
            assert source.connection_state() == ConnectionState.CONNECTED
        finally:
            await source.aclose()

    async def test_aclose_is_idempotent_after_success(
        self, fake_ws_client_factory
    ) -> None:
        rest_client = _make_rest_client()
        source = KisRealtimeQuoteSource(rest_client=rest_client, ws_url="ws://fake")
        await source.connect()

        await source.aclose()
        await source.aclose()  # second call must not raise

        assert rest_client.close.await_count == 2
        assert source.connection_state() == ConnectionState.DISCONNECTED

    async def test_aclose_is_safe_on_never_connected_instance(self) -> None:
        rest_client = _make_rest_client()
        source = KisRealtimeQuoteSource(rest_client=rest_client, ws_url="ws://fake")
        await source.aclose()  # must not raise even though connect() was never called
        rest_client.close.assert_awaited_once()


class TestSubscribe:
    async def test_subscribe_registers_both_channels(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        await connected_source.subscribe("005930")
        ws = _fake_ws(connected_source)
        assert ("H0STCNT0", "005930") in ws.subscribe_calls
        assert ("H0STASP0", "005930") in ws.subscribe_calls
        assert connected_source.list_subscriptions() == ["005930"]
        assert connected_source.registered_count() == 2

    async def test_subscribe_is_idempotent(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        await connected_source.subscribe("005930")
        await connected_source.subscribe("005930")
        ws = _fake_ws(connected_source)
        assert len(ws.subscribe_calls) == 2  # not 4 — no duplicate registration
        assert connected_source.registered_count() == 2

    async def test_subscribe_invalid_symbol_raises_without_calling_ws(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        with pytest.raises(InvalidSymbolError):
            await connected_source.subscribe("ABC")
        ws = _fake_ws(connected_source)
        assert ws.subscribe_calls == []

    async def test_subscribe_beyond_capacity_raises_without_calling_ws(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        for i in range(20):
            await connected_source.subscribe(f"{100000 + i:06d}")
        ws = _fake_ws(connected_source)
        call_count_before = len(ws.subscribe_calls)

        with pytest.raises(SubscriptionLimitExceededError):
            await connected_source.subscribe("999999")

        # Our own precheck must reject before ever calling the WS client —
        # mirrors the 41-registration / 2-per-symbol capacity model.
        assert len(ws.subscribe_calls) == call_count_before

    async def test_subscribe_rolls_back_on_full_transport_rejection(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        ws = _fake_ws(connected_source)
        ws.subscribe_result = False  # both channels rejected by KIS WS budget

        with pytest.raises(SubscriptionLimitExceededError):
            await connected_source.subscribe("005930")

        assert connected_source.list_subscriptions() == []
        assert ws.unsubscribe_calls == []  # neither channel succeeded — nothing to roll back

    async def test_subscribe_rolls_back_on_partial_transport_rejection(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        """Price channel accepted, orderbook channel rejected — must unsubscribe price."""
        ws = _fake_ws(connected_source)
        ws.subscribe_result_queue = [True, False]

        with pytest.raises(SubscriptionLimitExceededError):
            await connected_source.subscribe("005930")

        assert connected_source.list_subscriptions() == []
        assert ws.unsubscribe_calls == [("H0STCNT0", "005930")]

    async def test_subscribe_applies_static_reference(
        self, fake_ws_client_factory
    ) -> None:
        rest_client = _make_rest_client()
        rest_client.get_quote = AsyncMock(
            return_value={
                "stck_sdpr": "100500",
                "stck_mxpr": "120000",
                "stck_llam": "80000",
                "per": "8.2",
                "pbr": "0.9",
                "eps": "12543.0",
                "bps": "112430.0",
            }
        )
        source = KisRealtimeQuoteSource(rest_client=rest_client, ws_url="ws://fake")
        await source.connect()
        try:
            await source.subscribe("138040")
            state = source._state["138040"]
            assert state.prev_close == 100500.0
            assert state.upper_limit == 120000.0
            assert state.lower_limit == 80000.0
            assert state.per == 8.2
            assert state.bps == 112430.0
        finally:
            await source.aclose()

    async def test_subscribe_survives_static_reference_failure(
        self, fake_ws_client_factory
    ) -> None:
        rest_client = _make_rest_client()
        rest_client.get_quote = AsyncMock(side_effect=RuntimeError("REST unavailable"))
        source = KisRealtimeQuoteSource(rest_client=rest_client, ws_url="ws://fake")
        await source.connect()
        try:
            await source.subscribe("138040")  # must not raise
            assert source.list_subscriptions() == ["138040"]
            assert source._state["138040"].prev_close == 0.0
        finally:
            await source.aclose()


class TestUnsubscribe:
    async def test_unsubscribe_removes_both_channels(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        await connected_source.subscribe("005930")
        await connected_source.unsubscribe("005930")
        ws = _fake_ws(connected_source)
        assert ("H0STCNT0", "005930") in ws.unsubscribe_calls
        assert ("H0STASP0", "005930") in ws.unsubscribe_calls
        assert connected_source.list_subscriptions() == []

    async def test_unsubscribe_unknown_symbol_is_noop(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        await connected_source.unsubscribe("005930")
        ws = _fake_ws(connected_source)
        assert ws.unsubscribe_calls == []


class TestMessageHandlingAndSnapshots:
    async def test_trade_message_updates_snapshot(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        await connected_source.subscribe("005930")
        ws = _fake_ws(connected_source)

        trade_body = (
            "005930^093354^71900^5^-100^-0.14^72023.83^72100^72400^71700^71900^71800^1^3052507"
            "^219853241700^5105^6937^1832^84.90^1366314^1159996^1^0.39^20.28^090020^5^-200"
            "^090820^5^-500^092619^2^200^20230612^20^N^65945^216924^1118750^2199206^0.05"
            "^2424142^125.92^0^^72100"
        )
        await ws.push(
            {
                "type": "unknown",
                "tr_id": "0",
                "raw": f"0|H0STCNT0|001|{trade_body}",
            }
        )
        await asyncio.sleep(0.05)  # let the consumer task process the message

        snapshots = connected_source.get_snapshots(["005930"])
        assert "005930" in snapshots
        quote = snapshots["005930"]
        assert quote.last_price == 71900.0
        assert quote.change == -100.0
        assert quote.change_sign == "down"
        assert quote.trading_halted is False
        assert quote.hour_class == "장중"
        assert quote.accumulated_volume == 3052507
        assert quote.data_source == "websocket"

    async def test_orderbook_message_updates_snapshot(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        await connected_source.subscribe("005930")
        ws = _fake_ws(connected_source)

        ask_prices = "^".join(str(71900 + i * 100) for i in range(10))
        bid_prices = "^".join(str(71800 - i * 100) for i in range(10))
        ask_qty = "^".join(str(100 * (i + 1)) for i in range(10))
        bid_qty = "^".join(str(90 * (i + 1)) for i in range(10))
        book_body = f"005930^093730^0^{ask_prices}^{bid_prices}^{ask_qty}^{bid_qty}^500^400^0^0^0^0^0^0^0^0^0^0"

        await ws.push(
            {
                "type": "unknown",
                "tr_id": "0",
                "raw": f"0|H0STASP0|001|{book_body}",
            }
        )
        await asyncio.sleep(0.05)

        snapshots = connected_source.get_snapshots(["005930"])
        quote = snapshots["005930"]
        assert len(quote.ask_levels) == 10
        assert len(quote.bid_levels) == 10
        assert quote.ask_levels[0].price == 71900.0
        assert quote.bid_levels[0].price == 71800.0
        assert quote.total_ask_quantity == 500
        assert quote.total_bid_quantity == 400

    async def test_snapshot_omitted_before_any_data_received(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        await connected_source.subscribe("005930")
        snapshots = connected_source.get_snapshots(["005930"])
        assert snapshots == {}

    async def test_snapshot_omitted_for_unsubscribed_symbol(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        snapshots = connected_source.get_snapshots(["005930"])
        assert snapshots == {}

    async def test_message_for_unsubscribed_symbol_is_ignored(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        """A late message for a since-unsubscribed symbol must not resurrect state."""
        await connected_source.subscribe("005930")
        await connected_source.unsubscribe("005930")
        ws = _fake_ws(connected_source)

        await ws.push(
            {
                "type": "unknown",
                "tr_id": "0",
                "raw": "0|H0STCNT0|001|005930^093354^71900^5^-100^-0.14",
            }
        )
        await asyncio.sleep(0.05)

        assert connected_source.list_subscriptions() == []
        assert connected_source.get_snapshots(["005930"]) == {}


class TestBuildRealtimeQuoteSource:
    """``runtime.bootstrap.build_realtime_quote_source()`` — factory isolation."""

    def test_returns_none_when_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_trading.config.settings import AppSettings
        from agent_trading.runtime.bootstrap import build_realtime_quote_source

        monkeypatch.delenv("KIS_REALTIME_QUOTE_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_REALTIME_QUOTE_APP_SECRET", raising=False)
        settings = AppSettings()
        assert build_realtime_quote_source(settings) is None

    def test_builds_source_with_isolated_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_trading.config.settings import AppSettings
        from agent_trading.runtime.bootstrap import build_realtime_quote_source

        monkeypatch.setenv("KIS_REALTIME_QUOTE_APP_KEY", "rq-app-key")
        monkeypatch.setenv("KIS_REALTIME_QUOTE_APP_SECRET", "rq-app-secret")
        monkeypatch.setenv("KIS_APP_KEY", "trading-app-key")
        monkeypatch.setenv("KIS_API_SECRET", "trading-app-secret")
        settings = AppSettings()

        source = build_realtime_quote_source(settings)
        assert source is not None
        assert isinstance(source, KisRealtimeQuoteSource)

        rest_client = source._rest_client
        assert rest_client.api_key == "rq-app-key"
        assert rest_client.api_secret == "rq-app-secret"
        assert rest_client.api_key != settings.kis_api_key
        assert rest_client.account_number == ""
        assert rest_client.approval_cache_path == ".cache/kis_realtime_quote_approval_key.json"
        assert rest_client.approval_cache_path != settings.kis_approval_key_cache_path
