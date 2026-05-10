"""API-level contract tests for ``GET /performance-benchmark-history``.

Validates (12 tests, 4 groups):

**Group A — Top-Level + Point Shape (3 tests)**
  * Top-level response: 7 fields present + types + default ``benchmark_code="KOSPI"``
  * Point field shape: all 9 fields present in every point
  * Point field types: non-nullable (``int``, ``bool``) vs nullable (``float | None``)

**Group B — ``total_days`` + Ordering (2 tests)**
  * ``total_days == len(points)`` invariant
  * Points sorted in ascending date order

**Group C — Validation Error (6 tests)**
  * Invalid ``account_id`` UUID → 400
  * Invalid ``start_date`` / ``end_date`` format → 400
  * ``start_date > end_date`` → 400
  * Invalid ``benchmark_code`` → 400
  * Invalid ``strategy_id`` UUID → 400

**Group D — Empty Result (1 test)**
  * Unknown account with ``empty_client`` → 200 + valid shape
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.conftest import client  # noqa: F401
from tests.api.conftest import empty_client  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_account_id(tc: TestClient) -> str:
    """Resolve the seeded account_id via ``/clients`` → ``/accounts`` chain."""
    clients_resp = tc.get("/clients")
    clients = clients_resp.json()
    assert len(clients) >= 1
    cid = clients[0]["client_id"]

    acct_resp = tc.get(f"/accounts?client_id={cid}")
    accounts = acct_resp.json()
    assert len(accounts) >= 1
    return accounts[0]["account_id"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPerformanceBenchmarkHistory:
    """``GET /performance-benchmark-history`` — API 계약 검증."""

    # ------------------------------------------------------------------
    # Group A: Top-Level + Point Shape (3 tests)
    # ------------------------------------------------------------------

    def test_200_response_shape(self, client: TestClient) -> None:
        """정상 200 응답: top-level 7개 필드 존재 및 기본값 KOSPI."""
        acct_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "2026-05-10",
            },
        )
        assert response.status_code == 200
        data = response.json()

        # Top-level 7개 필드 존재
        assert "account_id" in data
        assert "start_date" in data
        assert "end_date" in data
        assert "strategy_id" in data
        assert "benchmark_code" in data
        assert "total_days" in data
        assert "points" in data

        # 타입
        assert isinstance(data["account_id"], str)
        assert isinstance(data["start_date"], str)
        assert isinstance(data["end_date"], str)
        assert data["strategy_id"] is None or isinstance(data["strategy_id"], str)
        assert isinstance(data["benchmark_code"], str)
        assert isinstance(data["total_days"], int)
        assert isinstance(data["points"], list)

        # 기본 benchmark_code = KOSPI
        assert data["benchmark_code"] == "KOSPI"

    def test_point_field_shape(self, client: TestClient) -> None:
        """각 point에 9개 필드가 모두 존재하는지 확인."""
        acct_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "2026-05-13",
            },
        )
        assert response.status_code == 200
        data = response.json()

        for point in data["points"]:
            assert "date" in point
            assert "portfolio_return_pct" in point
            assert "benchmark_return_pct" in point
            assert "excess_return_pct" in point
            assert "portfolio_drawdown_pct" in point
            assert "benchmark_drawdown_pct" in point
            assert "relative_drawdown_pct" in point
            assert "outperformance_streak" in point
            assert "benchmark_data_available" in point

    def test_point_field_types(self, client: TestClient) -> None:
        """각 point 필드의 Python/JSON 타입 검증."""
        acct_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "2026-05-13",
            },
        )
        assert response.status_code == 200
        data = response.json()

        for point in data["points"]:
            # date는 항상 str (ISO format)
            assert isinstance(point["date"], str)

            # outperformance_streak는 항상 int
            assert isinstance(point["outperformance_streak"], int)

            # benchmark_data_available는 항상 bool
            assert isinstance(point["benchmark_data_available"], bool)

            # nullable 6개 필드: None 또는 float
            for field in [
                "portfolio_return_pct",
                "benchmark_return_pct",
                "excess_return_pct",
                "portfolio_drawdown_pct",
                "benchmark_drawdown_pct",
                "relative_drawdown_pct",
            ]:
                assert point[field] is None or isinstance(point[field], (int, float))

    # ------------------------------------------------------------------
    # Group B: total_days + 정렬 (2 tests)
    # ------------------------------------------------------------------

    def test_total_days_matches_points_length(self, client: TestClient) -> None:
        """``total_days``는 항상 ``len(points)``와 일치."""
        acct_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "2026-05-10",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_days"] == len(data["points"])

    def test_points_ascending_order(self, client: TestClient) -> None:
        """points가 날짜 오름차순으로 정렬되어 있어야 함."""
        acct_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "2026-05-13",
            },
        )
        assert response.status_code == 200
        data = response.json()
        dates = [p["date"] for p in data["points"]]
        assert dates == sorted(dates), f"Points not sorted: {dates}"

    # ------------------------------------------------------------------
    # Group C: Validation Error (6 tests)
    # ------------------------------------------------------------------

    def test_invalid_account_id_400(self, client: TestClient) -> None:
        """Invalid account_id UUID → 400."""
        response = client.get(
            "/performance-benchmark-history",
            params={
                "account_id": "not-a-uuid",
                "start_date": "2026-05-01",
                "end_date": "2026-05-10",
            },
        )
        assert response.status_code == 400
        assert "Invalid account_id" in response.json()["detail"]

    def test_invalid_start_date_400(self, client: TestClient) -> None:
        """Invalid start_date format → 400."""
        acct_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history",
            params={
                "account_id": acct_id,
                "start_date": "invalid-date",
                "end_date": "2026-05-10",
            },
        )
        assert response.status_code == 400
        assert "Invalid start_date" in response.json()["detail"]

    def test_invalid_end_date_400(self, client: TestClient) -> None:
        """Invalid end_date format → 400."""
        acct_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "invalid-date",
            },
        )
        assert response.status_code == 400
        assert "Invalid end_date" in response.json()["detail"]

    def test_start_date_after_end_date_400(self, client: TestClient) -> None:
        """start_date > end_date → 400."""
        acct_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-10",
                "end_date": "2026-05-01",
            },
        )
        assert response.status_code == 400
        assert "start_date must be on or before end_date" in response.json()["detail"]

    def test_invalid_benchmark_code_400(self, client: TestClient) -> None:
        """존재하지 않는 benchmark_code → 400."""
        acct_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "2026-05-10",
                "benchmark_code": "INVALID",
            },
        )
        assert response.status_code == 400
        assert "Invalid benchmark_code" in response.json()["detail"]

    def test_invalid_strategy_id_400(self, client: TestClient) -> None:
        """Invalid strategy_id UUID → 400."""
        acct_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "2026-05-10",
                "strategy_id": "not-a-uuid",
            },
        )
        assert response.status_code == 400
        assert "Invalid strategy_id" in response.json()["detail"]

    # ------------------------------------------------------------------
    # Group D: Empty Result (1 test)
    # ------------------------------------------------------------------

    def test_unknown_account_returns_valid_shape(self, empty_client: TestClient) -> None:
        """존재하지 않는 계좌 UUID로 호출해도 200 + valid shape 반환.

        ``empty_client``는 빈 in-memory repos를 사용하지만,
        benchmark price fixture(``_DEFAULT_BENCHMARK_PRICES``)는 항상 존재하고,
        ``get_daily_history()``는 calendar iteration으로 0값 포인트를 생성하므로
        ``total_days=0``은 보장되지 않음.
        대신 endpoint가 200 + valid response shape을 반환하는지만 검증.
        """
        response = empty_client.get(
            "/performance-benchmark-history",
            params={
                "account_id": "00000000-0000-0000-0000-000000000001",
                "start_date": "2026-05-01",
                "end_date": "2026-05-10",
            },
        )
        assert response.status_code == 200
        data = response.json()
        # Top-level shape
        assert "account_id" in data
        assert "start_date" in data
        assert "end_date" in data
        assert "benchmark_code" in data
        assert "total_days" in data
        assert "points" in data
        # total_days는 int, points는 list
        assert isinstance(data["total_days"], int)
        assert isinstance(data["points"], list)
        # total_days == len(points) 일치
        assert data["total_days"] == len(data["points"])
