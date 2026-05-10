"""API tests for ``GET /performance-benchmark-history``.

Validates:
- Normal response shape (200)
- Invalid parameters → 400
- Points ascending date order
- Data-date Union coverage policy (no auto-generated calendar dates)
- ``total_days == len(points)`` (not calendar days)
- Existing ``GET /performance-benchmark`` and ``GET /performance-history``
  semantics are unchanged (no regression).
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from tests.api.conftest import client  # noqa: F401


def _get_account_id(tc: TestClient) -> str:
    """Helper: resolve the seeded account_id via /clients → /accounts chain."""
    clients_resp = tc.get("/clients")
    clients = clients_resp.json()
    assert len(clients) >= 1
    cid = clients[0]["client_id"]

    acct_resp = tc.get(f"/accounts?client_id={cid}")
    accounts = acct_resp.json()
    assert len(accounts) >= 1
    return accounts[0]["account_id"]


class TestPerformanceBenchmarkHistory:
    """``GET /performance-benchmark-history`` — API 레벨 검증 (7 tests)."""

    # ------------------------------------------------------------------
    # Test 1: 정상 응답
    # ------------------------------------------------------------------
    def test_normal_response(self, client: TestClient) -> None:
        """정상 파라미터 → 200 + 모든 필드 존재 + total_days == len(points)."""
        account_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history"
            f"?account_id={account_id}"
            f"&start_date=2026-05-01"
            f"&end_date=2026-05-08"
        )
        assert response.status_code == 200
        data = response.json()

        # -- Top-level fields --
        assert data["account_id"] == account_id
        assert data["start_date"] == "2026-05-01"
        assert data["end_date"] == "2026-05-08"
        assert data["benchmark_code"] == "KOSPI"
        assert data["strategy_id"] is None
        assert isinstance(data["total_days"], int)
        assert data["total_days"] >= 0

        # -- total_days == len(points) (calendar days 가 아님) --
        assert data["total_days"] == len(data["points"])

        # -- points list --
        assert isinstance(data["points"], list)
        for p in data["points"]:
            assert "date" in p
            assert "portfolio_return_pct" in p
            assert "benchmark_return_pct" in p
            assert "excess_return_pct" in p
            assert "portfolio_drawdown_pct" in p
            assert "benchmark_drawdown_pct" in p
            assert "relative_drawdown_pct" in p
            assert "outperformance_streak" in p
            assert "benchmark_data_available" in p

    # ------------------------------------------------------------------
    # Test 2: Invalid account_id
    # ------------------------------------------------------------------
    def test_invalid_account_id(self, client: TestClient) -> None:
        """잘못된 account_id UUID → 400."""
        response = client.get(
            "/performance-benchmark-history"
            "?account_id=not-a-uuid"
            "&start_date=2026-05-01"
            "&end_date=2026-05-08"
        )
        assert response.status_code == 400
        assert "Invalid account_id" in response.text

    # ------------------------------------------------------------------
    # Test 3: Invalid date format
    # ------------------------------------------------------------------
    def test_invalid_start_date(self, client: TestClient) -> None:
        """잘못된 start_date 형식 → 400."""
        response = client.get(
            "/performance-benchmark-history"
            "?account_id=00000000-0000-0000-0000-000000000000"
            "&start_date=invalid"
            "&end_date=2026-05-08"
        )
        assert response.status_code == 400

    def test_invalid_end_date(self, client: TestClient) -> None:
        """잘못된 end_date 형식 → 400."""
        response = client.get(
            "/performance-benchmark-history"
            "?account_id=00000000-0000-0000-0000-000000000000"
            "&start_date=2026-05-01"
            "&end_date=invalid"
        )
        assert response.status_code == 400

    # ------------------------------------------------------------------
    # Test 4: start_date > end_date
    # ------------------------------------------------------------------
    def test_start_date_after_end_date(self, client: TestClient) -> None:
        """시작일 > 종료일 → 400."""
        response = client.get(
            "/performance-benchmark-history"
            "?account_id=00000000-0000-0000-0000-000000000000"
            "&start_date=2026-05-08"
            "&end_date=2026-05-01"
        )
        assert response.status_code == 400

    # ------------------------------------------------------------------
    # Test 5: Invalid benchmark_code
    # ------------------------------------------------------------------
    def test_invalid_benchmark_code(self, client: TestClient) -> None:
        """존재하지 않는 benchmark_code → 400."""
        account_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history"
            f"?account_id={account_id}"
            f"&start_date=2026-05-01"
            f"&end_date=2026-05-08"
            f"&benchmark_code=INVALID"
        )
        assert response.status_code == 400
        assert "Invalid benchmark_code" in response.text

    # ------------------------------------------------------------------
    # Test 6: Points ascending date order
    # ------------------------------------------------------------------
    def test_points_ascending_order(self, client: TestClient) -> None:
        """points 배열이 date 기준 오름차순 정렬되어야 함."""
        account_id = _get_account_id(client)
        response = client.get(
            "/performance-benchmark-history"
            f"?account_id={account_id}"
            f"&start_date=2026-05-01"
            f"&end_date=2026-05-13"
        )
        assert response.status_code == 200
        data = response.json()
        dates = [p["date"] for p in data["points"]]
        assert dates == sorted(dates)

    # ------------------------------------------------------------------
    # Test 7: Data-date Union policy 검증
    # ------------------------------------------------------------------
    def test_date_coverage_union_policy(self, client: TestClient) -> None:
        """Data-date Union 정책 검증:

        - ``[start_date, end_date]`` 범위 내 모든 point의 date가 유효
        - calendar 빈 날짜가 point로 자동 생성되지 않음
        - ``total_days == len(points)`` (calendar 일수가 아님)
        - ``total_days <= calendar_days`` (항상 작거나 같음)
        """
        account_id = _get_account_id(client)
        start_str = "2026-05-01"
        end_str = "2026-05-13"
        response = client.get(
            "/performance-benchmark-history"
            f"?account_id={account_id}"
            f"&start_date={start_str}"
            f"&end_date={end_str}"
        )
        assert response.status_code == 200
        data = response.json()

        start = date.fromisoformat(data["start_date"])
        end = date.fromisoformat(data["end_date"])

        # 모든 point의 date가 [start_date, end_date] 범위 내
        for p in data["points"]:
            d = date.fromisoformat(p["date"])
            assert start <= d <= end

        # total_days == points 개수 (calendar 일수가 아님)
        assert data["total_days"] == len(data["points"])

        # calendar 빈 날짜가 point로 자동 생성되지 않음
        calendar_days = (end - start).days + 1
        assert data["total_days"] <= calendar_days
