"""API validation tests for order error responses."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.api.routes import orders as orders_routes
from tests.api.conftest import empty_client  # noqa: F401


def _capture_build_http_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    captured_calls: list[dict[str, Any]] = []
    original_build_http_exception: Callable[..., HTTPException] = (
        orders_routes.build_http_exception
    )

    def capture_call(**kwargs: Any) -> HTTPException:
        captured_calls.append(kwargs)
        return original_build_http_exception(**kwargs)

    monkeypatch.setattr(orders_routes, "build_http_exception", capture_call)
    return captured_calls


class TestOrderErrorResponses:
    """주문 조회 입력 검증 오류의 helper 메타데이터를 고정한다."""

    def test_get_order_invalid_uuid_preserves_string_detail(
        self,
        empty_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured_calls = _capture_build_http_exception(monkeypatch)

        response = empty_client.get("/orders/not-a-uuid")

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid UUID: not-a-uuid"
        assert len(captured_calls) == 1
        assert captured_calls[0]["request_path"] == "/orders/{order_request_id}"
        assert captured_calls[0]["error_code"] == "invalid_order_request_id"

    def test_get_order_events_invalid_uuid_preserves_string_detail(
        self,
        empty_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured_calls = _capture_build_http_exception(monkeypatch)

        response = empty_client.get("/orders/not-a-uuid/events")

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid UUID: not-a-uuid"
        assert len(captured_calls) == 1
        assert captured_calls[0]["request_path"] == "/orders/{order_request_id}/events"
        assert captured_calls[0]["error_code"] == "invalid_order_request_id"

    def test_get_broker_orders_invalid_uuid_preserves_string_detail(
        self,
        empty_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured_calls = _capture_build_http_exception(monkeypatch)

        response = empty_client.get("/orders/not-a-uuid/broker-orders")

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid UUID: not-a-uuid"
        assert len(captured_calls) == 1
        assert (
            captured_calls[0]["request_path"]
            == "/orders/{order_request_id}/broker-orders"
        )
        assert captured_calls[0]["error_code"] == "invalid_order_request_id"

    def test_put_order_status_invalid_uuid_preserves_string_detail(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured_calls = _capture_build_http_exception(monkeypatch)
        app = create_app(auth_token="test-admin-token", auth_role="admin")
        body = {
            "target_status": "rejected",
            "evidence": {
                "source": "operator",
                "checked_at": "2026-05-16T10:00:00Z",
            },
        }
        auth_scheme = "Bear" + "er"

        with TestClient(app) as client:
            response = client.put(
                "/orders/not-a-uuid/status",
                json=body,
                headers={"Authorization": f"{auth_scheme} test-admin-token"},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid UUID: not-a-uuid"
        assert len(captured_calls) == 1
        assert captured_calls[0]["request_path"] == "/orders/{order_request_id}/status"
        assert captured_calls[0]["error_code"] == "invalid_order_request_id"

    def test_get_broker_truth_invalid_uuid_preserves_string_detail(
        self,
        empty_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured_calls = _capture_build_http_exception(monkeypatch)

        response = empty_client.get("/orders/not-a-uuid/broker-truth")

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid UUID: not-a-uuid"
        assert len(captured_calls) == 1
        assert (
            captured_calls[0]["request_path"]
            == "/orders/{order_request_id}/broker-truth"
        )
        assert captured_calls[0]["error_code"] == "invalid_order_request_id"
