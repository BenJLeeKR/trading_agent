"""Enum metadata endpoint tests.

Covers: ``GET /metadata/enums``, ``GET /metadata/enums/{field}``.

P0 — ``order_type``:  registered + tested.
P1 — ``side``, ``order_status``, ``decision_type``, ``entry_style``:
     registered + tested in this file.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.conftest import client  # noqa: F401


class TestEnumMetadataList:
    """``GET /metadata/enums`` — list all registered enum fields."""

    def test_list_all_fields(self, client: TestClient) -> None:
        """Returns 200 with a ``fields`` list containing ``order_type``."""
        response = client.get("/metadata/enums")
        assert response.status_code == 200
        body = response.json()
        assert "fields" in body
        assert isinstance(body["fields"], list)
        assert len(body["fields"]) >= 1

        field_names = [f["field"] for f in body["fields"]]
        assert "order_type" in field_names

    def test_list_response_shape(self, client: TestClient) -> None:
        """Each field entry has the expected top-level keys."""
        response = client.get("/metadata/enums")
        assert response.status_code == 200
        fields = response.json()["fields"]

        for entry in fields:
            assert "field" in entry
            assert "type" in entry
            assert "values" in entry
            assert isinstance(entry["values"], list)

    def test_list_order_type_values_count(self, client: TestClient) -> None:
        """``order_type`` has exactly 4 values (limit, market, stop, stop_limit)."""
        response = client.get("/metadata/enums")
        fields = response.json()["fields"]
        ot = next(f for f in fields if f["field"] == "order_type")
        assert len(ot["values"]) == 4

    # ── P1 field presence ──────────────────────────────────────────

    def test_list_contains_side(self, client: TestClient) -> None:
        """Response includes ``side`` field."""
        response = client.get("/metadata/enums")
        field_names = [f["field"] for f in response.json()["fields"]]
        assert "side" in field_names

    def test_list_contains_order_status(self, client: TestClient) -> None:
        """Response includes ``order_status`` field."""
        response = client.get("/metadata/enums")
        field_names = [f["field"] for f in response.json()["fields"]]
        assert "order_status" in field_names

    def test_list_contains_decision_type(self, client: TestClient) -> None:
        """Response includes ``decision_type`` field."""
        response = client.get("/metadata/enums")
        field_names = [f["field"] for f in response.json()["fields"]]
        assert "decision_type" in field_names

    def test_list_contains_entry_style(self, client: TestClient) -> None:
        """Response includes ``entry_style`` field."""
        response = client.get("/metadata/enums")
        field_names = [f["field"] for f in response.json()["fields"]]
        assert "entry_style" in field_names

    # ── P1 field value counts ──────────────────────────────────────

    def test_side_values_count(self, client: TestClient) -> None:
        """``side`` has exactly 3 values (buy, sell, hold)."""
        response = client.get("/metadata/enums")
        fields = response.json()["fields"]
        side = next(f for f in fields if f["field"] == "side")
        assert len(side["values"]) == 3

    def test_order_status_values_count(self, client: TestClient) -> None:
        """``order_status`` has exactly 12 values."""
        response = client.get("/metadata/enums")
        fields = response.json()["fields"]
        os = next(f for f in fields if f["field"] == "order_status")
        assert len(os["values"]) == 12

    def test_decision_type_values_count(self, client: TestClient) -> None:
        """``decision_type`` has exactly 6 values."""
        response = client.get("/metadata/enums")
        fields = response.json()["fields"]
        dt = next(f for f in fields if f["field"] == "decision_type")
        assert len(dt["values"]) == 6

    def test_entry_style_values_count(self, client: TestClient) -> None:
        """``entry_style`` has exactly 5 values."""
        response = client.get("/metadata/enums")
        fields = response.json()["fields"]
        es = next(f for f in fields if f["field"] == "entry_style")
        assert len(es["values"]) == 5


class TestEnumMetadataSingleField:
    """``GET /metadata/enums/{field}`` — single field lookup."""

    def test_get_order_type(self, client: TestClient) -> None:
        """Returns 200 with full ``order_type`` metadata."""
        response = client.get("/metadata/enums/order_type")
        assert response.status_code == 200
        body = response.json()
        assert body["field"] == "order_type"
        assert body["type"] == "enum"
        assert len(body["values"]) == 4

    def test_limit_value(self, client: TestClient) -> None:
        """``limit`` → label=지정가, broker_code=00, supported=true."""
        response = client.get("/metadata/enums/order_type")
        values = response.json()["values"]
        limit = next(v for v in values if v["value"] == "limit")
        assert limit["label"] == "지정가"
        assert limit["broker_code"] == "00"
        assert limit["supported"] is True
        assert limit["description"] is None

    def test_market_value(self, client: TestClient) -> None:
        """``market`` → label=시장가, broker_code=01, supported=true."""
        response = client.get("/metadata/enums/order_type")
        values = response.json()["values"]
        market = next(v for v in values if v["value"] == "market")
        assert market["label"] == "시장가"
        assert market["broker_code"] == "01"
        assert market["supported"] is True
        assert market["description"] is None

    def test_stop_unsupported(self, client: TestClient) -> None:
        """``stop`` → supported=false, broker_code=02, description present."""
        response = client.get("/metadata/enums/order_type")
        values = response.json()["values"]
        stop = next(v for v in values if v["value"] == "stop")
        assert stop["label"] == "조건부지정가"
        assert stop["broker_code"] == "02"
        assert stop["supported"] is False
        assert stop["description"] is not None

    def test_stop_limit_unsupported(self, client: TestClient) -> None:
        """``stop_limit`` → supported=false, broker_code=03, description present."""
        response = client.get("/metadata/enums/order_type")
        values = response.json()["values"]
        sl = next(v for v in values if v["value"] == "stop_limit")
        assert sl["label"] == "조건부지정가"
        assert sl["broker_code"] == "03"
        assert sl["supported"] is False
        assert sl["description"] is not None

    def test_field_not_found(self, client: TestClient) -> None:
        """Returns 404 with ``detail`` for an unknown field."""
        response = client.get("/metadata/enums/nonexistent_field")
        assert response.status_code == 404
        body = response.json()
        assert "detail" in body
        assert "nonexistent_field" in body["detail"]

    # ── P1 single-field lookups ────────────────────────────────────

    def test_get_side(self, client: TestClient) -> None:
        """Returns 200 with ``side`` metadata."""
        response = client.get("/metadata/enums/side")
        assert response.status_code == 200
        body = response.json()
        assert body["field"] == "side"
        assert len(body["values"]) == 3

    def test_get_order_status(self, client: TestClient) -> None:
        """Returns 200 with ``order_status`` metadata."""
        response = client.get("/metadata/enums/order_status")
        assert response.status_code == 200
        body = response.json()
        assert body["field"] == "order_status"
        assert len(body["values"]) == 12

    def test_get_decision_type(self, client: TestClient) -> None:
        """Returns 200 with ``decision_type`` metadata."""
        response = client.get("/metadata/enums/decision_type")
        assert response.status_code == 200
        body = response.json()
        assert body["field"] == "decision_type"
        assert len(body["values"]) == 6

    def test_get_entry_style(self, client: TestClient) -> None:
        """Returns 200 with ``entry_style`` metadata."""
        response = client.get("/metadata/enums/entry_style")
        assert response.status_code == 200
        body = response.json()
        assert body["field"] == "entry_style"
        assert len(body["values"]) == 5

    # ── P1 label mapping ───────────────────────────────────────────

    def test_side_buy_label(self, client: TestClient) -> None:
        """``buy`` → label=매수."""
        response = client.get("/metadata/enums/side")
        values = response.json()["values"]
        buy = next(v for v in values if v["value"] == "buy")
        assert buy["label"] == "매수"

    def test_side_sell_label(self, client: TestClient) -> None:
        """``sell`` → label=매도."""
        response = client.get("/metadata/enums/side")
        values = response.json()["values"]
        sell = next(v for v in values if v["value"] == "sell")
        assert sell["label"] == "매도"

    def test_side_hold_label(self, client: TestClient) -> None:
        """``hold`` → label=보류."""
        response = client.get("/metadata/enums/side")
        values = response.json()["values"]
        hold = next(v for v in values if v["value"] == "hold")
        assert hold["label"] == "보류"

    def test_order_status_submitted_label(self, client: TestClient) -> None:
        """``submitted`` → label=제출됨."""
        response = client.get("/metadata/enums/order_status")
        values = response.json()["values"]
        s = next(v for v in values if v["value"] == "submitted")
        assert s["label"] == "제출됨"

    def test_order_status_filled_label(self, client: TestClient) -> None:
        """``filled`` → label=체결."""
        response = client.get("/metadata/enums/order_status")
        values = response.json()["values"]
        f = next(v for v in values if v["value"] == "filled")
        assert f["label"] == "체결"

    def test_decision_type_approve_label(self, client: TestClient) -> None:
        """``approve`` → label=승인."""
        response = client.get("/metadata/enums/decision_type")
        values = response.json()["values"]
        a = next(v for v in values if v["value"] == "approve")
        assert a["label"] == "승인"

    def test_decision_type_hold_label(self, client: TestClient) -> None:
        """``hold`` → label=보류."""
        response = client.get("/metadata/enums/decision_type")
        values = response.json()["values"]
        h = next(v for v in values if v["value"] == "hold")
        assert h["label"] == "보류"

    def test_entry_style_limit_label(self, client: TestClient) -> None:
        """``limit`` → label=지정가."""
        response = client.get("/metadata/enums/entry_style")
        values = response.json()["values"]
        l = next(v for v in values if v["value"] == "limit")
        assert l["label"] == "지정가"

    def test_entry_style_vwap_label(self, client: TestClient) -> None:
        """``vwap`` → label=VWAP."""
        response = client.get("/metadata/enums/entry_style")
        values = response.json()["values"]
        v = next(v for v in values if v["value"] == "vwap")
        assert v["label"] == "VWAP"


class TestEnumMetadataRegression:
    """Regression checks — existing API endpoints are unaffected."""

    def test_orders_still_work(self, client: TestClient) -> None:
        """``GET /orders`` still returns 200 after metadata router is added."""
        response = client.get("/orders")
        assert response.status_code == 200
        # May be empty or seeded; just verify it's a list
        assert isinstance(response.json(), list)
