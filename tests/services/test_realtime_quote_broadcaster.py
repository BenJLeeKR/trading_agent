"""Unit tests for ``QuoteBroadcaster`` (Phase 4 push relay fan-out layer)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from agent_trading.services.realtime_quote_broadcaster import QuoteBroadcaster
from agent_trading.services.realtime_quote_source import (
    ConnectionState,
    InMemoryMockQuoteSource,
    QuoteSnapshot,
)


def _make_snapshot(symbol: str, *, updated_at: datetime | None = None) -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol=symbol,
        market="KOSPI",
        name="테스트종목",
        last_price=100.0,
        prev_close=99.0,
        change=1.0,
        change_rate=1.01,
        change_sign="up",
        open_price=99.5,
        high_price=101.0,
        low_price=98.0,
        upper_limit=130.0,
        lower_limit=70.0,
        accumulated_volume=1000,
        accumulated_value=100000,
        per=10.0,
        pbr=1.0,
        eps=10.0,
        bps=100.0,
        ask_levels=[],
        bid_levels=[],
        total_ask_quantity=0,
        total_bid_quantity=0,
        trade_time="093000",
        hour_class="장중",
        trading_halted=False,
        data_source="websocket",
        updated_at=updated_at or datetime.now(timezone.utc),
    )


class _FakePushSource:
    """Minimal source stand-in exposing ``add_listener``/``remove_listener``
    (true-push path — mirrors ``KisRealtimeQuoteSource``'s public surface)."""

    def __init__(self) -> None:
        self._state = ConnectionState.CONNECTED
        self._listeners: list = []

    def add_listener(self, callback) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        self._listeners.remove(callback)

    def connection_state(self) -> ConnectionState:
        return self._state

    def get_snapshots(self, symbols):
        return {}

    def push(self, symbol: str, snapshot: QuoteSnapshot) -> None:
        for cb in list(self._listeners):
            cb(symbol, snapshot)


class TestTruePushPath:
    async def test_supports_push_true_for_source_with_add_listener(self) -> None:
        broadcaster = QuoteBroadcaster(_FakePushSource())
        assert broadcaster.supports_push is True
        broadcaster.close()

    async def test_stream_yields_initial_no_data_event(self) -> None:
        source = _FakePushSource()
        broadcaster = QuoteBroadcaster(source)
        try:
            gen = broadcaster.stream("005930")
            first = await gen.__anext__()
            assert first.status == "no_data_yet"
            assert first.snapshot is None
            await gen.aclose()
        finally:
            broadcaster.close()

    async def test_push_from_source_is_fanned_out_to_subscriber(self) -> None:
        source = _FakePushSource()
        broadcaster = QuoteBroadcaster(source)
        try:
            gen = broadcaster.stream("005930")
            await gen.__anext__()  # initial no_data_yet

            snapshot = _make_snapshot("005930")
            source.push("005930", snapshot)

            event = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
            assert event.status == "connected"
            assert event.snapshot is not None
            assert event.snapshot.last_price == 100.0
            await gen.aclose()
        finally:
            broadcaster.close()

    async def test_multiple_subscribers_receive_same_push(self) -> None:
        source = _FakePushSource()
        broadcaster = QuoteBroadcaster(source)
        try:
            gen1 = broadcaster.stream("005930")
            gen2 = broadcaster.stream("005930")
            await gen1.__anext__()
            await gen2.__anext__()

            source.push("005930", _make_snapshot("005930"))

            e1 = await asyncio.wait_for(gen1.__anext__(), timeout=1.0)
            e2 = await asyncio.wait_for(gen2.__anext__(), timeout=1.0)
            assert e1.snapshot.last_price == e2.snapshot.last_price == 100.0
            await gen1.aclose()
            await gen2.aclose()
        finally:
            broadcaster.close()

    async def test_reconnect_immediately_gets_cached_latest(self) -> None:
        """A fresh stream() call after a drop must not wait for the next tick —
        it should immediately see the last-known snapshot (reconnect UX)."""
        source = _FakePushSource()
        broadcaster = QuoteBroadcaster(source)
        try:
            gen1 = broadcaster.stream("005930")
            await gen1.__anext__()
            source.push("005930", _make_snapshot("005930"))
            await asyncio.wait_for(gen1.__anext__(), timeout=1.0)
            await gen1.aclose()  # simulate disconnect

            gen2 = broadcaster.stream("005930")
            first = await gen2.__anext__()
            assert first.status == "connected"
            assert first.snapshot is not None
            await gen2.aclose()
        finally:
            broadcaster.close()

    async def test_unsubscribe_removes_from_fanout(self) -> None:
        source = _FakePushSource()
        broadcaster = QuoteBroadcaster(source)
        try:
            gen = broadcaster.stream("005930")
            await gen.__anext__()
            await gen.aclose()
            assert "005930" not in broadcaster._subscribers
        finally:
            broadcaster.close()

    async def test_reconnecting_source_state_reflected_in_status(self) -> None:
        source = _FakePushSource()
        source._state = ConnectionState.RECONNECTING
        broadcaster = QuoteBroadcaster(source)
        try:
            gen = broadcaster.stream("005930")
            event = await gen.__anext__()
            assert event.status == "reconnecting"
            await gen.aclose()
        finally:
            broadcaster.close()

    async def test_disconnected_source_state_reflected_in_status(self) -> None:
        source = _FakePushSource()
        source._state = ConnectionState.DISCONNECTED
        broadcaster = QuoteBroadcaster(source)
        try:
            gen = broadcaster.stream("005930")
            event = await gen.__anext__()
            assert event.status == "disconnected"
            await gen.aclose()
        finally:
            broadcaster.close()

    async def test_stale_status_when_snapshot_is_old(self) -> None:
        source = _FakePushSource()
        broadcaster = QuoteBroadcaster(source, stale_after_seconds=0.01)
        try:
            gen = broadcaster.stream("005930")
            await gen.__anext__()
            old_snapshot = _make_snapshot(
                "005930", updated_at=datetime.now(timezone.utc) - timedelta(seconds=5)
            )
            source.push("005930", old_snapshot)
            event = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
            assert event.status == "stale"
            await gen.aclose()
        finally:
            broadcaster.close()


class TestFallbackPollPath:
    async def test_mock_source_has_no_push_support(self) -> None:
        broadcaster = QuoteBroadcaster(InMemoryMockQuoteSource())
        assert broadcaster.supports_push is False
        broadcaster.close()

    async def test_mock_source_gets_polled_events(self) -> None:
        source = InMemoryMockQuoteSource()
        await source.subscribe("005930")
        broadcaster = QuoteBroadcaster(source, poll_interval_seconds=0.05)
        try:
            gen = broadcaster.stream("005930")
            first = await gen.__anext__()
            assert first.status == "no_data_yet"  # nothing polled yet on the very first yield

            event = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
            assert event.snapshot is not None
            await gen.aclose()
        finally:
            broadcaster.close()

    async def test_poll_task_cancelled_after_last_unsubscribe(self) -> None:
        source = InMemoryMockQuoteSource()
        await source.subscribe("005930")
        broadcaster = QuoteBroadcaster(source, poll_interval_seconds=0.05)
        try:
            gen = broadcaster.stream("005930")
            await gen.__anext__()
            assert "005930" in broadcaster._poll_tasks
            await gen.aclose()
            assert "005930" not in broadcaster._poll_tasks
        finally:
            broadcaster.close()


class TestClose:
    async def test_close_cancels_all_tasks_and_detaches_listener(self) -> None:
        source = _FakePushSource()
        broadcaster = QuoteBroadcaster(source)
        gen = broadcaster.stream("005930")
        await gen.__anext__()
        broadcaster.close()
        assert source._listeners == []
        await gen.aclose()
