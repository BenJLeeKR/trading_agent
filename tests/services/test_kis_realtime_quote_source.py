"""Unit tests for ``KisRealtimeQuoteSource`` (Step 3 — KIS-backed realtime quote source).

No real network calls are made. ``KISWebSocketClient`` is replaced with a
lightweight in-memory fake, and ``KISRestClient`` is a ``MagicMock`` with
``AsyncMock`` methods for ``get_approval_key`` / ``get_quote`` / ``close``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
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
    rest_client.get_daily_price = AsyncMock(return_value=[])
    rest_client.close = AsyncMock()
    return rest_client


def _make_real_rest_client_with_stubbed_transport(
    monkeypatch: pytest.MonkeyPatch, *, quote_responses: list[dict]
) -> tuple[KISRestClient, list[dict]]:
    """실제 ``KISRestClient``(진짜 ``get_quote()``/TTL 캐시 로직 포함)를 만들되,
    HTTP를 실제로 나가는 ``_request()``만 순차 응답 stub으로 대체한다.

    ``get_quote(symbol)`` 자체를 mock으로 갈아끼우면 캐시 hit/miss 판정 자체가
    테스트에서 빠지므로, "캐시를 우회하는지"를 검증할 수 없다 — 여기서는 실제
    ``_quote_cache``/``_get_quote_from_cache()``/``_set_quote_cache()``가 그대로
    실행되는 상태에서, 캐시 hit 시나리오(구독 시점 응답)와 캐시 miss/bypass
    시나리오(fallback 시점 응답)가 실제로 다른 값을 반환하는지 재현한다.

    ``KISRestClient``는 ``@dataclass(slots=True)``라 인스턴스에 새 속성을 붙일
    수 없으므로(선언되지 않은 attr 할당 자체가 막힘), 호출 기록(``request_calls``)은
    별도 리스트로 반환한다. 패치도 인스턴스가 아니라 클래스 레벨에 건다.
    """
    rest_client = KISRestClient(
        api_key="test-key",
        api_secret="test-secret",
        account_number="00000000",
        account_product_code="01",
        env="live",
    )
    request_calls: list[dict] = []
    responses = iter(quote_responses)

    async def _fake_request(self, method, endpoint_key, tr_id_key, bucket, body=None, params=None, **kwargs):
        request_calls.append({"endpoint_key": endpoint_key, "params": params})
        if endpoint_key == "inquire_price":
            return {"output": next(responses)}
        raise AssertionError(f"unexpected endpoint_key in test stub: {endpoint_key}")

    async def _fake_get_approval_key(self) -> str:
        return "test-approval-key"

    async def _fake_close(self) -> None:
        return None

    monkeypatch.setattr(KISRestClient, "_request", _fake_request)
    monkeypatch.setattr(KISRestClient, "get_approval_key", _fake_get_approval_key)
    monkeypatch.setattr(KISRestClient, "close", _fake_close)
    return rest_client, request_calls


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


@pytest.fixture
async def fallback_source(fake_ws_client_factory) -> KisRealtimeQuoteSource:
    """Step 4(REST fallback) 전용 — 헬스체크/트리거/쿨다운 간격을 실제 테스트가
    감당할 수 있는 수준(수십 ms)으로 줄여, 실제 ``asyncio.sleep()``으로 시간 경과를
    기다리는 것만으로 fallback 동작을 검증할 수 있게 한다."""
    rest_client = _make_rest_client()
    source = KisRealtimeQuoteSource(
        rest_client=rest_client,
        ws_url="ws://fake",
        fallback_trigger_after_seconds=0.03,
        fallback_cooldown_seconds=0.05,
        health_check_interval_seconds=0.02,
    )
    await source.connect()
    yield source
    await source.aclose()


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
        for i in range(15):
            await connected_source.subscribe(f"{100000 + i:06d}")
        ws = _fake_ws(connected_source)
        call_count_before = len(ws.subscribe_calls)

        with pytest.raises(SubscriptionLimitExceededError):
            await connected_source.subscribe("999999")

        # Our own precheck must reject before ever calling the WS client —
        # mirrors the 30-registration / 2-per-symbol capacity model.
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


class TestInstrumentInfoLookup:
    """``instruments`` 테이블 조회 배선 — mock 소스와 동일한 ``InstrumentInfoResolver``."""

    async def test_subscribe_uses_instrument_lookup_over_placeholder(
        self, fake_ws_client_factory
    ) -> None:
        from agent_trading.services.realtime_quote_source import InstrumentInfo

        calls: list[str] = []

        async def lookup(symbol: str):
            calls.append(symbol)
            return InstrumentInfo(symbol=symbol, name="DB종목명", market="KOSDAQ")

        rest_client = _make_rest_client()
        source = KisRealtimeQuoteSource(
            rest_client=rest_client, ws_url="ws://fake", instrument_info_lookup=lookup
        )
        await source.connect()
        try:
            # "005930" is one of the hardcoded mock instruments (삼성전자/KOSPI) —
            # the real lookup result must win over that placeholder.
            await source.subscribe("005930")
            info = source.instrument_info("005930")
            assert info.name == "DB종목명"
            assert info.market == "KOSDAQ"
            assert calls == ["005930"]
        finally:
            await source.aclose()

    async def test_lookup_exception_falls_back_to_placeholder(
        self, fake_ws_client_factory
    ) -> None:
        async def lookup(symbol: str):
            raise RuntimeError("DB down")

        rest_client = _make_rest_client()
        source = KisRealtimeQuoteSource(
            rest_client=rest_client, ws_url="ws://fake", instrument_info_lookup=lookup
        )
        await source.connect()
        try:
            await source.subscribe("005930")  # must not raise
            info = source.instrument_info("005930")
            assert info.name == "삼성전자"
            assert info.market == "KOSPI"
        finally:
            await source.aclose()

    def test_no_lookup_configured_preserves_existing_behavior(self) -> None:
        rest_client = _make_rest_client()
        source = KisRealtimeQuoteSource(rest_client=rest_client, ws_url="ws://fake")
        info = source.instrument_info("999999")
        assert info.market == "UNKNOWN"
        assert "999999" in info.name


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
        assert len(quote.recent_trades) == 1
        assert quote.recent_trades[0].price == 71900.0
        assert quote.recent_trades[0].change == -100.0
        assert quote.recent_trades[0].volume == 1  # CNTG_VOL(field 13), not ACML_VOL

    async def test_multiple_trade_messages_accumulate_newest_first(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        await connected_source.subscribe("005930")
        ws = _fake_ws(connected_source)

        for price in (71900, 71950, 72000):
            body = f"005930^093354^{price}^5^-100^-0.14^72023.83^72100^72400^71700^71900^71800^1^3052507"
            await ws.push({"type": "unknown", "tr_id": "0", "raw": f"0|H0STCNT0|001|{body}"})
        await asyncio.sleep(0.05)

        quote = connected_source.get_snapshots(["005930"])["005930"]
        assert [t.price for t in quote.recent_trades] == [72000.0, 71950.0, 71900.0]

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


class TestPushListenerDedup:
    """2026-07-09: 장 마감 후 KIS가 동일한 마지막 값을 반복 전송하는 것이 실측됐다 —
    내용이 실제로 안 바뀐 프레임은 ``add_listener`` 콜백을 다시 안 태우고,
    최초 1회(또는 실제 변경 시)에만 통보한다."""

    async def test_first_frame_after_subscribe_always_notifies(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        """장중엔 미구독 상태였다가 장 종료 후 처음 구독해도, 그 첫 프레임은
        (마감 후 반복되는 동일 값이라도) 반드시 최소 1회는 통보돼야 한다."""
        await connected_source.subscribe("005930")
        ws = _fake_ws(connected_source)
        received: list[str] = []
        connected_source.add_listener(lambda symbol, snapshot: received.append(symbol))

        await ws.push(
            {
                "type": "unknown",
                "tr_id": "0",
                "raw": "0|H0STCNT0|001|005930^093354^71900^5^-100^-0.14",
            }
        )
        await asyncio.sleep(0.05)

        assert received == ["005930"]

    async def test_identical_repeated_frame_is_not_re_notified(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        await connected_source.subscribe("005930")
        ws = _fake_ws(connected_source)
        received: list[str] = []
        connected_source.add_listener(lambda symbol, snapshot: received.append(symbol))

        body = "005930^153002^278000^5^-100^-0.14^72023.83^72100^72400^71700^71900^71800^1^3052507"
        # KIS가 마감 후 완전히 동일한 프레임을 3번 반복 전송하는 상황을 흉내낸다.
        for _ in range(3):
            await ws.push({"type": "unknown", "tr_id": "0", "raw": f"0|H0STCNT0|001|{body}"})
        await asyncio.sleep(0.05)

        # 첫 프레임만 통보되고, 이후 동일 프레임 2건은 스킵된다.
        assert received == ["005930"]

    async def test_content_change_notifies_again(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        await connected_source.subscribe("005930")
        ws = _fake_ws(connected_source)
        received: list[str] = []
        connected_source.add_listener(lambda symbol, snapshot: received.append(symbol))

        same_body = "005930^153002^278000^5^-100^-0.14^72023.83^72100^72400^71700^71900^71800^1^3052507"
        changed_body = "005930^153010^278500^5^-100^-0.14^72023.83^72100^72400^71700^71900^71800^1^3052507"
        await ws.push({"type": "unknown", "tr_id": "0", "raw": f"0|H0STCNT0|001|{same_body}"})
        await ws.push({"type": "unknown", "tr_id": "0", "raw": f"0|H0STCNT0|001|{same_body}"})
        await ws.push({"type": "unknown", "tr_id": "0", "raw": f"0|H0STCNT0|001|{changed_body}"})
        await asyncio.sleep(0.05)

        # 1st(신규) + 3rd(실제 변경) = 2건만 통보. 2nd(동일)은 스킵.
        assert received == ["005930", "005930"]

    async def test_resubscribe_after_unsubscribe_notifies_first_frame_again(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        """구독 해제 후 재구독하면(예: 장중 미구독 → 장 종료 후 재구독) 이전
        signature 캐시가 남아있어 첫 프레임이 잘못 스킵되면 안 된다."""
        await connected_source.subscribe("005930")
        ws = _fake_ws(connected_source)
        received: list[str] = []
        connected_source.add_listener(lambda symbol, snapshot: received.append(symbol))

        body = "005930^153002^278000^5^-100^-0.14^72023.83^72100^72400^71700^71900^71800^1^3052507"
        await ws.push({"type": "unknown", "tr_id": "0", "raw": f"0|H0STCNT0|001|{body}"})
        await asyncio.sleep(0.05)
        assert received == ["005930"]

        await connected_source.unsubscribe("005930")
        await connected_source.subscribe("005930")
        # 재구독 후 동일한 내용의 프레임이 다시 들어와도, signature 캐시가
        # unsubscribe 시점에 지워졌으므로 다시 통보돼야 한다.
        await ws.push({"type": "unknown", "tr_id": "0", "raw": f"0|H0STCNT0|001|{body}"})
        await asyncio.sleep(0.05)

        assert received == ["005930", "005930"]


class TestStaticReferenceRefresh:
    """2026-07-10: 구독이 자정을 넘겨 계속 유지되면(자동 unsubscribe가 없어 실제로
    발생함) subscribe() 시점에 1회만 REST로 가져온 prev_close/기준가가 stale해져,
    '호가'의 클라이언트 계산 대비율과 '실시간 체결가'의 KIS 서버 계산 change_rate가
    서로 다른 기준으로 어긋나는 문제가 실측됐다 — reference_date가 오늘과 다르면
    다음 프레임 처리 시 자동으로 재조회돼야 한다."""

    async def test_stale_reference_date_triggers_refetch(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        rest_client = connected_source._rest_client
        rest_client.get_quote = AsyncMock(
            return_value={"stck_sdpr": "70000", "stck_mxpr": "91000", "stck_llam": "49000"}
        )
        await connected_source.subscribe("005930")
        assert rest_client.get_quote.await_count == 1
        assert connected_source._state["005930"].reference_date != ""

        # 자정을 넘겨 구독이 유지된 상황을 흉내낸다 — reference_date를 과거로 되돌린다.
        connected_source._state["005930"].reference_date = "20200101"

        ws = _fake_ws(connected_source)
        await ws.push(
            {
                "type": "unknown",
                "tr_id": "0",
                "raw": "0|H0STCNT0|001|005930^093354^71900^5^-100^-0.14",
            }
        )
        await asyncio.sleep(0.05)

        assert rest_client.get_quote.await_count == 2
        assert connected_source._state["005930"].reference_date != "20200101"
        assert "005930" not in connected_source._reference_refresh_in_progress

    async def test_fresh_reference_date_does_not_refetch(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        rest_client = connected_source._rest_client
        rest_client.get_quote = AsyncMock(return_value={"stck_sdpr": "70000"})
        await connected_source.subscribe("005930")
        assert rest_client.get_quote.await_count == 1

        ws = _fake_ws(connected_source)
        await ws.push(
            {
                "type": "unknown",
                "tr_id": "0",
                "raw": "0|H0STCNT0|001|005930^093354^71900^5^-100^-0.14",
            }
        )
        await asyncio.sleep(0.05)

        # reference_date가 오늘 그대로면 재조회할 이유가 없다.
        assert rest_client.get_quote.await_count == 1


class TestRestFallback:
    """2026-07-10 (Step 4) — KIS WS 연결이 끊기거나 재연결 중일 때, 구독 중인
    종목의 snapshot을 REST 현재가 조회(``FHKST01010100``)로 보정한다. 브라우저↔API
    간 SSE transport fallback(Phase 4)과는 다른, API↔KIS 간 quote source
    fallback이다."""

    async def test_triggers_after_disconnect_threshold_and_marks_rest_fallback(
        self, fallback_source: KisRealtimeQuoteSource
    ) -> None:
        rest_client = fallback_source._rest_client
        rest_client.get_quote = AsyncMock(
            return_value={
                "stck_prpr": "71500",
                "prdy_vrss": "-500",
                "prdy_ctrt": "-0.69",
                "stck_oprc": "72000",
                "stck_hgpr": "72500",
                "stck_lwpr": "71000",
                "acml_vol": "123456",
                "acml_tr_pbmn": "987654321",
                "temp_stop_yn": "N",
                "stck_sdpr": "72000",
            }
        )
        await fallback_source.subscribe("005930")
        calls_after_subscribe = rest_client.get_quote.await_count  # apply_static_reference 1회

        ws = _fake_ws(fallback_source)
        ws._connected = False  # KIS WS 연결이 끊긴 상황을 흉내낸다

        # health_check(0.02s) 여러 번, trigger_after(0.03s)를 넘도록 충분히 대기.
        await asyncio.sleep(0.15)

        assert rest_client.get_quote.await_count > calls_after_subscribe
        state = fallback_source._state["005930"]
        assert state.data_source == "rest_fallback"
        assert state.last_price == 71500.0
        assert state.change == -500.0
        assert state.trading_halted is False

        # API 계약 검증 — get_snapshots()로 노출되는 값도 동일해야 한다.
        snapshot = fallback_source.get_snapshots(["005930"])["005930"]
        assert snapshot.data_source == "rest_fallback"
        assert snapshot.last_price == 71500.0

    async def test_not_triggered_while_connected(
        self, fallback_source: KisRealtimeQuoteSource
    ) -> None:
        rest_client = fallback_source._rest_client
        rest_client.get_quote = AsyncMock(return_value={"stck_prpr": "71500"})
        await fallback_source.subscribe("005930")
        calls_after_subscribe = rest_client.get_quote.await_count

        # ws._connected는 fixture 기본값 True 그대로 — 연결이 살아있으면 아무리
        # 시간이 지나도 fallback이 발동하면 안 된다.
        await asyncio.sleep(0.15)

        assert rest_client.get_quote.await_count == calls_after_subscribe
        assert fallback_source._state["005930"].data_source == "websocket"

    async def test_websocket_recovery_reverts_to_websocket_data_source(
        self, fallback_source: KisRealtimeQuoteSource
    ) -> None:
        rest_client = fallback_source._rest_client
        rest_client.get_quote = AsyncMock(return_value={"stck_prpr": "71500"})
        await fallback_source.subscribe("005930")

        ws = _fake_ws(fallback_source)
        ws._connected = False
        await asyncio.sleep(0.15)  # fallback 발동 대기
        state = fallback_source._state["005930"]
        assert state.data_source == "rest_fallback"

        # WS가 복구되고(reconnect) 실제 tick이 도착하면, 별도 처리 없이도
        # apply_trade()가 자동으로 data_source를 되돌려야 한다.
        ws._connected = True
        await ws.push(
            {
                "type": "unknown",
                "tr_id": "0",
                "raw": "0|H0STCNT0|001|005930^093354^71900^5^-100^-0.14",
            }
        )
        await asyncio.sleep(0.05)

        assert state.data_source == "websocket"
        assert state.last_price == 71900.0

    async def test_respects_cooldown_between_fallback_calls(
        self, fake_ws_client_factory
    ) -> None:
        # cooldown을 관찰 윈도우보다 훨씬 길게 잡아, 여러 번의 헬스체크 사이클이
        # 지나도 REST 호출이 정확히 1회만 발생하는지("과호출 방지") 검증한다.
        rest_client = _make_rest_client()
        source = KisRealtimeQuoteSource(
            rest_client=rest_client,
            ws_url="ws://fake",
            fallback_trigger_after_seconds=0.01,
            fallback_cooldown_seconds=5.0,
            health_check_interval_seconds=0.02,
        )
        await source.connect()
        try:
            rest_client.get_quote = AsyncMock(return_value={"stck_prpr": "71500"})
            await source.subscribe("005930")
            calls_after_subscribe = rest_client.get_quote.await_count

            ws = _fake_ws(source)
            ws._connected = False
            await asyncio.sleep(0.2)  # health_check_interval 대비 약 10회 사이클

            assert rest_client.get_quote.await_count - calls_after_subscribe == 1
        finally:
            await source.aclose()

    async def test_unsubscribe_clears_fallback_cooldown_state(
        self, fallback_source: KisRealtimeQuoteSource
    ) -> None:
        await fallback_source.subscribe("005930")
        fallback_source._last_fallback_at["005930"] = datetime.now(timezone.utc)

        await fallback_source.unsubscribe("005930")

        assert "005930" not in fallback_source._last_fallback_at

    async def test_fallback_notifies_push_listeners_like_a_normal_update(
        self, fallback_source: KisRealtimeQuoteSource
    ) -> None:
        rest_client = fallback_source._rest_client
        rest_client.get_quote = AsyncMock(return_value={"stck_prpr": "71500"})
        await fallback_source.subscribe("005930")

        received: list[str] = []
        fallback_source.add_listener(lambda symbol, snapshot: received.append(snapshot.data_source))

        ws = _fake_ws(fallback_source)
        ws._connected = False
        await asyncio.sleep(0.15)

        assert "rest_fallback" in received

    async def test_fallback_bypasses_subscribe_time_quote_cache(
        self, fake_ws_client_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2026-07-10 후속 보정 1건 — ``subscribe()``의 정적 참조값 보강과 Step 4
        fallback이 같은 ``KISRestClient.get_quote()``의 3분 TTL 캐시를 공유한다.
        실제 캐시 로직(``_quote_cache``/TTL 체크)이 살아있는 ``KISRestClient``를
        써서, subscribe 시점 응답이 캐시에 남아있는 상태에서 fallback이 정말로
        새 HTTP 호출(``bypass_cache=True``)로 최신값을 가져오는지 검증한다.
        ``bypass_cache``가 빠지면 이 테스트는 last_price가 캐시값(70000)에
        머물러 실패한다."""
        rest_client, request_calls = _make_real_rest_client_with_stubbed_transport(
            monkeypatch,
            quote_responses=[
                {"stck_prpr": "70000"},  # subscribe() 시점 — 캐시에 저장됨
                {"stck_prpr": "68000"},  # fallback 시점의 "실제 최신" 응답
            ],
        )
        source = KisRealtimeQuoteSource(
            rest_client=rest_client,
            ws_url="ws://fake",
            fallback_trigger_after_seconds=0.03,
            fallback_cooldown_seconds=10.0,  # 이 테스트는 정확히 1회만 발동해야 한다
            health_check_interval_seconds=0.02,
        )
        await source.connect()
        try:
            await source.subscribe("005930")
            assert len(request_calls) == 1  # 캐시에 70000 저장됨

            ws = _fake_ws(source)
            ws._connected = False
            await asyncio.sleep(0.15)

            # 캐시를 그대로 썼다면 _request가 재호출되지 않아 len==1, last_price==70000에
            # 머물렀을 것이다 — bypass_cache=True 덕분에 실제로 다시 호출돼 최신값을 반영한다.
            assert len(request_calls) == 2
            state = source._state["005930"]
            assert state.data_source == "rest_fallback"
            assert state.last_price == 68000.0
        finally:
            await source.aclose()

    async def test_fallback_retries_after_failure_and_cools_down_only_on_success(
        self, fake_ws_client_factory
    ) -> None:
        """2026-07-10 후속 보정 2건 — fallback fetch가 실패하면 cooldown을 걸지
        않고 다음 health check에서 곧바로 재시도해야 하며, cooldown은 성공했을
        때만 시작돼야 한다."""
        rest_client = _make_rest_client()
        rest_client.get_quote = AsyncMock(
            side_effect=[
                {"stck_prpr": "70000"},  # subscribe() 정적 참조값 보강 — 성공
                RuntimeError("simulated transient failure"),  # 첫 fallback 시도 — 실패
                {"stck_prpr": "71500"},  # 다음 health check의 재시도 — 성공
            ]
        )
        source = KisRealtimeQuoteSource(
            rest_client=rest_client,
            ws_url="ws://fake",
            fallback_trigger_after_seconds=0.01,
            fallback_cooldown_seconds=10.0,
            health_check_interval_seconds=0.05,
        )
        await source.connect()
        try:
            await source.subscribe("005930")
            ws = _fake_ws(source)
            ws._connected = False

            # 1st health check(0.05s): disconnected_since 기록만, 아직 trigger 안 함.
            # 2nd health check(0.10s): 첫 fallback 시도 — 실패, cooldown 기록 안 됨.
            await asyncio.sleep(0.13)
            assert rest_client.get_quote.await_count == 2  # subscribe(1) + 실패한 시도(1)
            assert source._state["005930"].data_source == "websocket"  # 아직 반영 안 됨

            # 3rd health check(0.15s): cooldown이 없으므로 곧바로 재시도 — 성공.
            await asyncio.sleep(0.08)
            assert rest_client.get_quote.await_count == 3
            assert source._state["005930"].data_source == "rest_fallback"
            assert source._state["005930"].last_price == 71500.0

            # 성공 시점부터 cooldown(10s)이 걸리므로, 이후 health check가 더 돌아도
            # 추가 호출이 없어야 한다.
            await asyncio.sleep(0.15)
            assert rest_client.get_quote.await_count == 3
        finally:
            await source.aclose()

    async def test_data_source_transition_alone_notifies_listeners(
        self, fallback_source: KisRealtimeQuoteSource
    ) -> None:
        """2026-07-10 후속 보정 3건 — price/change 등 실질 값이 완전히 동일해도,
        data_source가 websocket → rest_fallback으로 바뀌면 listener(SSE 구독자
        경로 포함)에 반드시 재통보돼야 한다. ``_content_signature``가
        ``data_source``를 빼먹으면 이 전환이 통째로 누락된다."""
        await fallback_source.subscribe("005930")

        received: list[tuple[str, float]] = []
        fallback_source.add_listener(
            lambda symbol, snapshot: received.append((snapshot.data_source, snapshot.last_price))
        )

        ws = _fake_ws(fallback_source)
        # last_price=71900, change=-100, change_rate=-0.14 — 나머지 필드는 이
        # 짧은 프레임에 없으므로 기본값(0/"")으로 남는다.
        body = "005930^093354^71900^5^-100^-0.14"
        await ws.push({"type": "unknown", "tr_id": "0", "raw": f"0|H0STCNT0|001|{body}"})
        await asyncio.sleep(0.05)
        assert received == [("websocket", 71900.0)]

        # REST fallback 응답이 방금 받은 tick과 완전히 동일한 값을 반환하도록
        # 구성한다 — 값은 그대로, 출처만 websocket → rest_fallback으로 바뀐다.
        rest_client = fallback_source._rest_client
        rest_client.get_quote = AsyncMock(
            return_value={"stck_prpr": "71900", "prdy_vrss": "-100", "prdy_ctrt": "-0.14"}
        )

        ws._connected = False
        await asyncio.sleep(0.15)

        assert ("rest_fallback", 71900.0) in received


class TestDailyPrice:
    """``get_daily_price()`` — REST-only, independent of WS subscription state."""

    async def test_maps_kis_fields_to_daily_price_bar(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        connected_source._rest_client.get_daily_price.return_value = [
            {
                "stck_bsop_date": "20260708",
                "stck_clpr": "128000",
                "prdy_vrss": "3500",
                "prdy_vrss_sign": "2",
                "prdy_ctrt": "2.81",
                "acml_vol": "3908418",
            },
            {
                "stck_bsop_date": "20260707",
                "stck_clpr": "124500",
                "prdy_vrss": "-2500",
                "prdy_vrss_sign": "5",
                "prdy_ctrt": "-1.97",
                "acml_vol": "3449197",
            },
        ]

        bars = await connected_source.get_daily_price("005930")

        assert len(bars) == 2
        assert bars[0].date == "20260708"
        assert bars[0].close == 128000.0
        assert bars[0].change == 3500.0
        assert bars[0].change_rate == 2.81
        assert bars[0].volume == 3908418
        assert bars[1].change == -2500.0  # sign already embedded in prdy_vrss

    async def test_does_not_require_subscription(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        """Unsubscribed symbols can still be queried — pure REST, no WS budget consumed."""
        connected_source._rest_client.get_daily_price.return_value = []
        assert connected_source.list_subscriptions() == []
        bars = await connected_source.get_daily_price("999999")
        assert bars == []

    async def test_invalid_symbol_raises(self, connected_source: KisRealtimeQuoteSource) -> None:
        with pytest.raises(InvalidSymbolError):
            await connected_source.get_daily_price("ABC")

    async def test_count_caps_at_max_history(
        self, connected_source: KisRealtimeQuoteSource
    ) -> None:
        connected_source._rest_client.get_daily_price.return_value = [
            {"stck_bsop_date": f"202607{i:02d}", "stck_clpr": "100", "prdy_vrss": "0",
             "prdy_vrss_sign": "3", "prdy_ctrt": "0.0", "acml_vol": "1"}
            for i in range(1, 32)  # 31 rows — more than MAX_DAILY_PRICE_HISTORY
        ]
        bars = await connected_source.get_daily_price("005930", count=1000)
        assert len(bars) == kqs.MAX_DAILY_PRICE_HISTORY


class TestBuildRealtimeQuoteSource:
    """``runtime.bootstrap.build_realtime_quote_source()`` — factory isolation.

    2026-07-10: 이 화면의 authoritative credential이 ``KIS_REALTIME_QUOTE_*``에서
    ``KIS_LIVE_INFO_*``로 통합됐다 — 아래는 새 authoritative 경로를 검증하고,
    ``test_builds_source_with_legacy_realtime_quote_fallback``은 짧은 하위
    호환 fallback 경로(``KIS_LIVE_INFO_*`` 미설정 + legacy
    ``KIS_REALTIME_QUOTE_*`` 설정)를 검증한다.
    """

    def test_returns_none_when_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_trading.config.settings import AppSettings
        from agent_trading.runtime.bootstrap import build_realtime_quote_source

        monkeypatch.delenv("KIS_LIVE_INFO_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_LIVE_INFO_APP_SECRET", raising=False)
        monkeypatch.delenv("KIS_REALTIME_QUOTE_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_REALTIME_QUOTE_APP_SECRET", raising=False)
        settings = AppSettings()
        assert build_realtime_quote_source(settings) is None

    def test_builds_source_with_isolated_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_trading.config.settings import AppSettings
        from agent_trading.runtime.bootstrap import build_realtime_quote_source

        monkeypatch.delenv("KIS_REALTIME_QUOTE_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_REALTIME_QUOTE_APP_SECRET", raising=False)
        monkeypatch.setenv("KIS_LIVE_INFO_APP_KEY", "live-info-app-key")
        monkeypatch.setenv("KIS_LIVE_INFO_APP_SECRET", "live-info-app-secret")
        monkeypatch.setenv("KIS_APP_KEY", "trading-app-key")
        monkeypatch.setenv("KIS_API_SECRET", "trading-app-secret")
        settings = AppSettings()

        source = build_realtime_quote_source(settings)
        assert source is not None
        assert isinstance(source, KisRealtimeQuoteSource)

        rest_client = source._rest_client
        assert rest_client.api_key == "live-info-app-key"
        assert rest_client.api_secret == "live-info-app-secret"
        assert rest_client.api_key != settings.kis_api_key
        assert rest_client.account_number == ""
        assert rest_client.approval_cache_path == ".cache/kis_live_info_approval_key.json"
        assert rest_client.approval_cache_path != settings.kis_approval_key_cache_path

    def test_builds_source_with_legacy_realtime_quote_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``KIS_LIVE_INFO_*``가 비어 있으면 legacy ``KIS_REALTIME_QUOTE_*``로
        fallback해야 한다(짧은 하위 호환 기간 동안만 유지되는 경로)."""
        from agent_trading.config.settings import AppSettings
        from agent_trading.runtime.bootstrap import build_realtime_quote_source

        monkeypatch.delenv("KIS_LIVE_INFO_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_LIVE_INFO_APP_SECRET", raising=False)
        monkeypatch.setenv("KIS_REALTIME_QUOTE_APP_KEY", "rq-app-key")
        monkeypatch.setenv("KIS_REALTIME_QUOTE_APP_SECRET", "rq-app-secret")
        settings = AppSettings()

        source = build_realtime_quote_source(settings)
        assert source is not None
        rest_client = source._rest_client
        assert rest_client.api_key == "rq-app-key"
        assert rest_client.api_secret == "rq-app-secret"
        assert rest_client.approval_cache_path == ".cache/kis_realtime_quote_approval_key.json"
