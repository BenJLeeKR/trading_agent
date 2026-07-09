"""Tests for ``/realtime-quotes/*`` — Phase 1 mock-backed realtime quote API.

Phase 1 scope: API contract + in-memory mock ``RealtimeQuoteSource``.
No KIS WebSocket connection is made in this test suite.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.api.routes.realtime_quotes import stream_quote


@pytest.fixture
def client() -> TestClient:
    """FastAPI ``TestClient`` with auth disabled (fresh mock quote source per app)."""
    app = create_app(auth_enabled=False)
    with TestClient(app) as tc:
        yield tc


class TestBootstrap:
    def test_returns_200_with_empty_subscriptions_initially(self, client: TestClient) -> None:
        resp = client.get("/realtime-quotes/bootstrap")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["subscriptions"] == []
        assert data["connection"]["connection_state"] == "connected"
        assert data["connection"]["environment"] == "mock"
        assert data["connection"]["registered_count"] == 0
        assert data["connection"]["max_registrations"] == 30
        assert data["connection"]["registrations_per_symbol"] == 2
        assert data["connection"]["symbol_capacity"] == 15
        assert "generated_at" in data


class TestSubscribe:
    def test_subscribe_adds_symbol(self, client: TestClient) -> None:
        resp = client.post("/realtime-quotes/subscriptions", json={"symbols": ["005930"]})
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert len(data["subscriptions"]) == 1
        assert data["subscriptions"][0]["symbol"] == "005930"
        assert data["subscriptions"][0]["name"] == "삼성전자"
        assert data["subscriptions"][0]["market"] == "KOSPI"
        assert data["connection"]["registered_count"] == 2  # 체결가 + 호가

    def test_subscribe_duplicate_is_idempotent(self, client: TestClient) -> None:
        """Re-subscribing to the same symbol must not accumulate a ref count."""
        resp = client.post("/realtime-quotes/subscriptions", json={"symbols": ["005930"]})
        assert resp.status_code == 201
        resp2 = client.post("/realtime-quotes/subscriptions", json={"symbols": ["005930"]})
        assert resp2.status_code == 201
        assert len(resp2.json()["subscriptions"]) == 1
        assert resp2.json()["connection"]["registered_count"] == 2

        # A single unsubscribe must fully remove it, regardless of the
        # duplicate subscribe above — no dangling backend subscription.
        resp3 = client.request(
            "DELETE",
            "/realtime-quotes/subscriptions",
            json={"symbols": ["005930"]},
        )
        assert resp3.status_code == 200
        assert resp3.json()["subscriptions"] == []
        assert resp3.json()["connection"]["registered_count"] == 0

    def test_subscribe_multiple_symbols(self, client: TestClient) -> None:
        resp = client.post(
            "/realtime-quotes/subscriptions",
            json={"symbols": ["005930", "000660", "035420"]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["subscriptions"]) == 3
        assert data["connection"]["registered_count"] == 6

    def test_subscribe_invalid_symbol_returns_422(self, client: TestClient) -> None:
        resp = client.post("/realtime-quotes/subscriptions", json={"symbols": ["ABC"]})
        assert resp.status_code == 422, resp.text

    def test_subscribe_etn_prefix_returns_422(self, client: TestClient) -> None:
        """ETN codes (``Q`` prefix) are out of scope for this 국내주식 screen."""
        resp = client.post("/realtime-quotes/subscriptions", json={"symbols": ["Q00001"]})
        assert resp.status_code == 422, resp.text

    def test_subscribe_wrong_length_returns_422(self, client: TestClient) -> None:
        resp = client.post("/realtime-quotes/subscriptions", json={"symbols": ["12345"]})
        assert resp.status_code == 422, resp.text

    def test_subscribe_empty_list_returns_422(self, client: TestClient) -> None:
        resp = client.post("/realtime-quotes/subscriptions", json={"symbols": []})
        assert resp.status_code == 422

    def test_subscribe_beyond_symbol_capacity_returns_409(self, client: TestClient) -> None:
        # Symbol capacity is 30 // 2 = 15. Subscribe 15 distinct symbols first.
        symbols = [f"{100000 + i:06d}" for i in range(15)]
        resp = client.post("/realtime-quotes/subscriptions", json={"symbols": symbols})
        assert resp.status_code == 201, resp.text
        assert resp.json()["connection"]["registered_count"] == 30

        # The 16th distinct symbol would exceed the 30-registration budget.
        resp2 = client.post("/realtime-quotes/subscriptions", json={"symbols": ["999999"]})
        assert resp2.status_code == 409, resp2.text


class TestUnsubscribe:
    def test_unsubscribe_removes_symbol(self, client: TestClient) -> None:
        client.post("/realtime-quotes/subscriptions", json={"symbols": ["005930"]})
        resp = client.request(
            "DELETE",
            "/realtime-quotes/subscriptions",
            json={"symbols": ["005930"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["subscriptions"] == []
        assert resp.json()["connection"]["registered_count"] == 0

    def test_unsubscribe_unknown_symbol_is_a_noop(self, client: TestClient) -> None:
        resp = client.request(
            "DELETE",
            "/realtime-quotes/subscriptions",
            json={"symbols": ["005930"]},
        )
        assert resp.status_code == 200
        assert resp.json()["subscriptions"] == []


class TestListSubscriptions:
    def test_list_reflects_current_state(self, client: TestClient) -> None:
        client.post("/realtime-quotes/subscriptions", json={"symbols": ["005930", "000660"]})
        resp = client.get("/realtime-quotes/subscriptions")
        assert resp.status_code == 200
        symbols = {s["symbol"] for s in resp.json()["subscriptions"]}
        assert symbols == {"005930", "000660"}


class TestSnapshot:
    def test_snapshot_for_subscribed_symbol(self, client: TestClient) -> None:
        client.post("/realtime-quotes/subscriptions", json={"symbols": ["138040"]})
        resp = client.get("/realtime-quotes/snapshot", params={"symbols": "138040"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "138040" in data["quotes"]
        quote = data["quotes"]["138040"]
        assert quote["name"] == "메리츠금융지주"
        assert quote["market"] == "KOSPI"
        assert quote["data_source"] == "mock"
        assert len(quote["ask_levels"]) == 10
        assert len(quote["bid_levels"]) == 10
        assert quote["per"] is not None
        assert quote["upper_limit"] > quote["last_price"] > quote["lower_limit"]
        assert 0 < len(quote["recent_trades"]) <= 30
        assert quote["recent_trades"][0]["price"] > 0

    def test_snapshot_omits_unsubscribed_symbol(self, client: TestClient) -> None:
        resp = client.get("/realtime-quotes/snapshot", params={"symbols": "005930"})
        assert resp.status_code == 200
        assert resp.json()["quotes"] == {}

    def test_snapshot_multiple_symbols(self, client: TestClient) -> None:
        client.post("/realtime-quotes/subscriptions", json={"symbols": ["005930", "000660"]})
        resp = client.get("/realtime-quotes/snapshot", params={"symbols": "005930,000660"})
        assert resp.status_code == 200
        quotes = resp.json()["quotes"]
        assert set(quotes.keys()) == {"005930", "000660"}

    def test_snapshot_empty_symbols_returns_422(self, client: TestClient) -> None:
        resp = client.get("/realtime-quotes/snapshot", params={"symbols": ""})
        assert resp.status_code == 422


class TestDailyPrice:
    def test_returns_bars_for_any_symbol(self, client: TestClient) -> None:
        # No subscription required — pure REST-equivalent lookup.
        resp = client.get("/realtime-quotes/daily-price", params={"symbol": "005930"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["symbol"] == "005930"
        assert len(data["bars"]) == 30
        assert all(bar["date"] for bar in data["bars"])
        assert all(bar["close"] > 0 for bar in data["bars"])

    def test_invalid_symbol_returns_422(self, client: TestClient) -> None:
        resp = client.get("/realtime-quotes/daily-price", params={"symbol": "ABC"})
        assert resp.status_code == 422, resp.text

    def test_missing_symbol_returns_422(self, client: TestClient) -> None:
        resp = client.get("/realtime-quotes/daily-price")
        assert resp.status_code == 422


class TestStream:
    """``GET /realtime-quotes/stream`` — Phase 4 SSE push relay.

    These tests call the route function directly (with a real, lifespan-built
    ``QuoteBroadcaster``) rather than driving it over HTTP. Starlette's
    ``StreamingResponse`` spawns a concurrent "listen for client disconnect"
    task that awaits ``receive()`` — httpx's ``ASGITransport`` only resolves
    that ``receive()`` once the response body is fully drained, which never
    happens for a deliberately-infinite SSE stream. That's a test-transport
    limitation, not a product bug (browsers/real ASGI servers don't have this
    problem), so we exercise the actual production code path — router
    function → ``QuoteBroadcaster`` → SSE encoding — without going through
    that incompatible transport.
    """

    async def test_returns_streaming_response_with_initial_event(self) -> None:
        app = create_app(auth_enabled=False)
        async with app.router.lifespan_context(app):
            broadcaster = app.state.realtime_quote_broadcaster
            response = await stream_quote(symbol="005930", broadcaster=broadcaster)
            assert isinstance(response, StreamingResponse)
            assert response.media_type == "text/event-stream"

            chunk = await asyncio.wait_for(response.body_iterator.__anext__(), timeout=2.0)
            line = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            assert line.startswith("data: ")
            payload = json.loads(line[len("data: "):].strip())
            assert payload["symbol"] == "005930"
            assert payload["status"] == "no_data_yet"
            assert payload["snapshot"] is None
            await response.body_iterator.aclose()

    async def test_reflects_connected_status_once_data_exists(self) -> None:
        app = create_app(auth_enabled=False)
        async with app.router.lifespan_context(app):
            source = app.state.realtime_quote_source
            await source.subscribe("005930")
            source.get_snapshots(["005930"])  # prime the mock's per-call generator
            broadcaster = app.state.realtime_quote_broadcaster

            response = await stream_quote(symbol="005930", broadcaster=broadcaster)
            seen = []
            try:
                for _ in range(6):
                    chunk = await asyncio.wait_for(
                        response.body_iterator.__anext__(), timeout=3.0
                    )
                    line = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                    payload = json.loads(line[len("data: "):].strip())
                    seen.append(payload)
                    if payload["status"] == "connected":
                        break
            finally:
                await response.body_iterator.aclose()
            assert any(p["status"] == "connected" for p in seen)
            assert any(p["snapshot"] is not None for p in seen)

    def test_invalid_symbol_returns_422(self, client: TestClient) -> None:
        resp = client.get("/realtime-quotes/stream", params={"symbol": "ABC"})
        assert resp.status_code == 422

    async def test_generator_close_cleans_up_broadcaster_subscription(self) -> None:
        app = create_app(auth_enabled=False)
        async with app.router.lifespan_context(app):
            broadcaster = app.state.realtime_quote_broadcaster
            response = await stream_quote(symbol="005930", broadcaster=broadcaster)
            await asyncio.wait_for(response.body_iterator.__anext__(), timeout=2.0)
            assert "005930" in broadcaster._subscribers

            await response.body_iterator.aclose()
            assert "005930" not in broadcaster._subscribers


class TestAuthRequired:
    def test_endpoints_require_auth_when_enabled(self) -> None:
        app = create_app(auth_token="test-token")
        with TestClient(app) as tc:
            resp = tc.get("/realtime-quotes/bootstrap")
            assert resp.status_code in (401, 403)
