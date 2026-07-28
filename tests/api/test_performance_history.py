"""API validation tests for ``GET /performance-history``."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent_trading.api.routes import performance as performance_routes  # noqa: F401
from tests.api.conftest import empty_client  # noqa: F401


class TestPerformanceHistoryValidation:
    """``GET /performance-history`` 입력 검증 오류의 호환성을 고정한다."""

    def test_invalid_account_id_preserves_string_detail(
        self, empty_client: TestClient
    ) -> None:
        response = empty_client.get(
            "/performance-history",
            params={
                "account_id": "not-a-uuid",
                "start_date": "2026-05-01",
                "end_date": "2026-05-05",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid account_id UUID"

    def test_invalid_start_date_preserves_string_detail(
        self, empty_client: TestClient
    ) -> None:
        acct_id = "00000000-0000-0000-0000-000000000001"
        response = empty_client.get(
            "/performance-history",
            params={
                "account_id": acct_id,
                "start_date": "invalid-date",
                "end_date": "2026-05-05",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid start_date (use YYYY-MM-DD)"

    def test_invalid_end_date_preserves_string_detail(
        self, empty_client: TestClient
    ) -> None:
        acct_id = "00000000-0000-0000-0000-000000000001"
        response = empty_client.get(
            "/performance-history",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "invalid-date",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid end_date (use YYYY-MM-DD)"

    def test_invalid_date_range_preserves_string_detail(
        self, empty_client: TestClient
    ) -> None:
        acct_id = "00000000-0000-0000-0000-000000000001"
        response = empty_client.get(
            "/performance-history",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-06",
                "end_date": "2026-05-05",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "start_date must be on or before end_date"

    def test_invalid_strategy_id_preserves_string_detail(
        self, empty_client: TestClient
    ) -> None:
        acct_id = "00000000-0000-0000-0000-000000000001"
        response = empty_client.get(
            "/performance-history",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "2026-05-05",
                "strategy_id": "not-a-uuid",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid strategy_id UUID"
