"""API validation tests for client error responses."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_trading.api.routes import clients as clients_routes
from tests.api.conftest import empty_client  # noqa: F401


def _capture_build_http_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    captured_calls: list[dict[str, Any]] = []
    original_build_http_exception: Callable[..., HTTPException] = (
        clients_routes.build_http_exception
    )

    def capture_call(**kwargs: Any) -> HTTPException:
        captured_calls.append(kwargs)
        return original_build_http_exception(**kwargs)

    monkeypatch.setattr(clients_routes, "build_http_exception", capture_call)
    return captured_calls


class TestClientErrorResponses:
    """클라이언트 조회 입력 검증 오류의 helper 메타데이터를 고정한다."""

    def test_get_client_invalid_uuid_preserves_string_detail(
        self,
        empty_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured_calls = _capture_build_http_exception(monkeypatch)

        response = empty_client.get("/clients/not-a-uuid")

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid client_id UUID"
        assert len(captured_calls) == 1
        assert captured_calls[0]["request_path"] == "/clients/{client_id}"
        assert captured_calls[0]["error_code"] == "invalid_client_id"
