"""API-level contract tests for ``GET /performance-metrics``.

Validates (3 tests):

1. **Risk-adjusted + explanation fields present**
   - 3 numeric fields: ``sharpe_ratio``, ``sortino_ratio``, ``calmar_ratio``
   - 6 explanation/status fields: ``*_status``, ``*_note`` for each ratio

2. **Status/note default values when data is empty**
   - Numeric fields → ``None``
   - Status → ``"insufficient_data"`` / ``"zero_drawdown"``
   - Note → non-empty ``str``

3. **Existing 19 fields + 9 new fields unchanged** (regression guard)
   - All field types verified (``int``, ``float``, ``str | None``)
   - No regression on previously implemented metrics
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.conftest import empty_client  # noqa: F401


class TestPerformanceMetrics:
    """``GET /performance-metrics`` — risk-adjusted field + explanation field 검증.

    하드코딩된 UUID(``00000000-0000-0000-0000-000000000001``)를 사용하는 이유:
    이 테스트는 empty data / 기본값 검증이 목적이므로, seeded account lookup
    helper(``_get_account_id``)가 불필요함. ``empty_client`` fixture의 빈 저장소에서
    모든 필드가 예상 타입/값을 반환하는지만 확인.
    """

    def test_new_fields_present(self, empty_client: TestClient) -> None:
        """응답에 신규 field 9개 (3 numeric + 6 explanation)가 존재하는지 확인."""
        acct_id = "00000000-0000-0000-0000-000000000001"
        response = empty_client.get(
            "/performance-metrics",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "2026-05-05",
            },
        )
        assert response.status_code == 200
        data = response.json()

        # Numeric risk-adjusted fields (3)
        assert "sharpe_ratio" in data
        assert "sortino_ratio" in data
        assert "calmar_ratio" in data

        # Explanation / Status fields (6)
        assert "sharpe_ratio_status" in data
        assert "sharpe_ratio_note" in data
        assert "sortino_ratio_status" in data
        assert "sortino_ratio_note" in data
        assert "calmar_ratio_status" in data
        assert "calmar_ratio_note" in data

    def test_new_fields_status_values(self, empty_client: TestClient) -> None:
        """데이터 없음 → numeric fields는 None, status/note fields는 기본값."""
        acct_id = "00000000-0000-0000-0000-000000000001"
        response = empty_client.get(
            "/performance-metrics",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "2026-05-05",
            },
        )
        assert response.status_code == 200
        data = response.json()

        # 데이터가 없으므로 신규 numeric field는 모두 null
        assert data["sharpe_ratio"] is None
        assert data["sortino_ratio"] is None
        assert data["calmar_ratio"] is None

        # Explanation fields는 기본 status 값 (nullable 아님)
        assert data["sharpe_ratio_status"] == "insufficient_data"
        assert data["sortino_ratio_status"] == "insufficient_data"
        assert data["calmar_ratio_status"] == "zero_drawdown"
        assert isinstance(data["sharpe_ratio_note"], str)
        assert isinstance(data["sortino_ratio_note"], str)
        assert isinstance(data["calmar_ratio_note"], str)
        # note는 비어있지 않음
        assert data["sharpe_ratio_note"] != ""
        assert data["sortino_ratio_note"] != ""
        assert data["calmar_ratio_note"] != ""

    def test_existing_fields_unchanged(self, empty_client: TestClient) -> None:
        """기존 19개 field가 예상 타입으로 존재하는지 확인 (회귀 방지)."""
        acct_id = "00000000-0000-0000-0000-000000000001"
        response = empty_client.get(
            "/performance-metrics",
            params={
                "account_id": acct_id,
                "start_date": "2026-05-01",
                "end_date": "2026-05-05",
            },
        )
        assert response.status_code == 200
        data = response.json()

        # 기존 19개 field 존재 및 타입 확인 (회귀 방지)
        assert isinstance(data["account_id"], str)
        assert data["strategy_id"] is None
        assert isinstance(data["period_start"], str)
        assert isinstance(data["period_end"], str)
        assert isinstance(data["starting_equity"], float)
        assert isinstance(data["current_equity"], float)
        assert isinstance(data["cumulative_realized_pnl"], float)
        assert isinstance(data["cumulative_return_pct"], float)
        assert isinstance(data["peak_equity"], float)
        assert isinstance(data["current_drawdown_pct"], float)
        assert isinstance(data["max_drawdown_pct"], float)
        assert isinstance(data["total_filled_orders"], int)
        assert isinstance(data["winning_trades"], int)
        assert isinstance(data["losing_trades"], int)
        assert isinstance(data["win_rate"], float)
        assert data["avg_win"] is None
        assert data["avg_loss"] is None
        assert data["profit_factor"] is None

        # 신규 3개 numeric field (회귀 방지)
        assert data["sharpe_ratio"] is None
        assert data["sortino_ratio"] is None
        assert data["calmar_ratio"] is None

        # 신규 6개 explanation field (회귀 방지)
        assert data["sharpe_ratio_status"] == "insufficient_data"
        assert isinstance(data["sharpe_ratio_note"], str)
        assert data["sortino_ratio_status"] == "insufficient_data"
        assert isinstance(data["sortino_ratio_note"], str)
        assert data["calmar_ratio_status"] == "zero_drawdown"
        assert isinstance(data["calmar_ratio_note"], str)
