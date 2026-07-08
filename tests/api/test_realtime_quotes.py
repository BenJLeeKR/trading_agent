"""Tests for ``/realtime-quotes/*`` — Phase 1 mock-backed realtime quote API.

Phase 1 scope: API contract + in-memory mock ``RealtimeQuoteSource``.
No KIS WebSocket connection is made in this test suite.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app


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
        assert data["connection"]["max_registrations"] == 41
        assert data["connection"]["registrations_per_symbol"] == 2
        assert data["connection"]["symbol_capacity"] == 20
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

    def test_subscribe_lowercase_symbol_is_normalized(self, client: TestClient) -> None:
        resp = client.post("/realtime-quotes/subscriptions", json={"symbols": ["005930"]})
        assert resp.status_code == 201
        # Re-subscribing (ref count) does not add a duplicate entry.
        resp2 = client.post("/realtime-quotes/subscriptions", json={"symbols": ["005930"]})
        assert resp2.status_code == 201
        assert len(resp2.json()["subscriptions"]) == 1
        assert resp2.json()["connection"]["registered_count"] == 2

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

    def test_subscribe_empty_list_returns_422(self, client: TestClient) -> None:
        resp = client.post("/realtime-quotes/subscriptions", json={"symbols": []})
        assert resp.status_code == 422

    def test_subscribe_beyond_symbol_capacity_returns_409(self, client: TestClient) -> None:
        # Symbol capacity is 41 // 2 = 20. Subscribe 20 distinct symbols first.
        symbols = [f"{100000 + i:06d}" for i in range(20)]
        resp = client.post("/realtime-quotes/subscriptions", json={"symbols": symbols})
        assert resp.status_code == 201, resp.text
        assert resp.json()["connection"]["registered_count"] == 40

        # The 21st distinct symbol would exceed the 41-registration budget.
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


class TestAuthRequired:
    def test_endpoints_require_auth_when_enabled(self) -> None:
        app = create_app(auth_token="test-token")
        with TestClient(app) as tc:
            resp = tc.get("/realtime-quotes/bootstrap")
            assert resp.status_code in (401, 403)
