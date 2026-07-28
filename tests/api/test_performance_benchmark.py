"""API validation tests for ``GET /performance-benchmark``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_trading.api.routes import performance as performance_routes
from tests.api.conftest import empty_client  # noqa: F401


def _capture_build_http_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    captured_calls: list[dict[str, Any]] = []
    original_build_http_exception: Callable[..., HTTPException] = (
        performance_routes.build_http_exception
    )

    def capture_call(**kwargs: Any) -> HTTPException:
        captured_calls.append(kwargs)
        return original_build_http_exception(**kwargs)

    monkeypatch.setattr(performance_routes, "build_http_exception", capture_call)
    return captured_calls


class TestPerformanceBenchmarkValidation:
    """``GET /performance-benchmark`` 입력 검증 오류의 helper 메타데이터를 고정한다."""

    @pytest.mark.parametrize(
        ("params", "expected_detail", "expected_error_code"),
        [
            (
                {
                    "account_id": "not-a-uuid",
                    "start_date": "2026-05-01",
                    "end_date": "2026-05-05",
                    "benchmark_code": "KOSPI",
                },
                "Invalid account_id UUID",
                "invalid_account_id",
            ),
            (
                {
                    "account_id": "00000000-0000-0000-0000-000000000001",
                    "start_date": "invalid-date",
                    "end_date": "2026-05-05",
                    "benchmark_code": "KOSPI",
                },
                "Invalid start_date (use YYYY-MM-DD)",
                "invalid_start_date",
            ),
            (
                {
                    "account_id": "00000000-0000-0000-0000-000000000001",
                    "start_date": "2026-05-01",
                    "end_date": "invalid-date",
                    "benchmark_code": "KOSPI",
                },
                "Invalid end_date (use YYYY-MM-DD)",
                "invalid_end_date",
            ),
            (
                {
                    "account_id": "00000000-0000-0000-0000-000000000001",
                    "start_date": "2026-05-06",
                    "end_date": "2026-05-05",
                    "benchmark_code": "KOSPI",
                },
                "start_date must be on or before end_date",
                "invalid_date_range",
            ),
            (
                {
                    "account_id": "00000000-0000-0000-0000-000000000001",
                    "start_date": "2026-05-01",
                    "end_date": "2026-05-05",
                    "benchmark_code": "INVALID",
                },
                "Invalid benchmark_code='INVALID'. Valid codes: ['KOSDAQ', 'KOSPI']",
                "invalid_benchmark_code",
            ),
            (
                {
                    "account_id": "00000000-0000-0000-0000-000000000001",
                    "start_date": "2026-05-01",
                    "end_date": "2026-05-05",
                    "benchmark_code": "KOSPI",
                    "strategy_id": "not-a-uuid",
                },
                "Invalid strategy_id UUID",
                "invalid_strategy_id",
            ),
        ],
    )
    def test_validation_error_uses_benchmark_request_path(
        self,
        empty_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        params: dict[str, str],
        expected_detail: str,
        expected_error_code: str,
    ) -> None:
        captured_calls = _capture_build_http_exception(monkeypatch)

        response = empty_client.get("/performance-benchmark", params=params)

        assert response.status_code == 400
        assert response.json()["detail"] == expected_detail
        assert len(captured_calls) == 1
        assert captured_calls[0]["request_path"] == "/performance-benchmark"
        assert captured_calls[0]["error_code"] == expected_error_code
