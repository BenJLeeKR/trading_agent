"""API-level contract tests for ``GET /agent-runs``.

Validates (8 tests, 2 groups):

**Group A — List / Filter (5 tests)**
  1. Empty result — ``empty_client`` → 200 + ``[]``
  2. Seeded data — ``client`` → 200 + 3 runs + DESC ``started_at`` ordering
  3. Filter by ``decision_context_id`` — 200 + all results match filter
  4. Invalid ``decision_context_id`` UUID — 400
  5. No-match ``decision_context_id`` — 200 + ``[]``

**Group B — Detail endpoint (3 tests)**
  6. ``GET /agent-runs/{id}`` — 200 + field shape
  7. Unknown UUID — 404
  8. Invalid UUID — 422
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.conftest import client  # noqa: F401
from tests.api.conftest import empty_client  # noqa: F401


class TestAgentRuns:
    """``GET /agent-runs`` — agent run 목록/필터 조회 API 계약 검증.

    별도 helper 없이 ``client``(seeded repos)와 ``empty_client``(빈 repos)
    fixture로 seeded data 존재 여부에 따른 동작을 검증.
    """

    def test_list_agent_runs_empty(self, empty_client: TestClient) -> None:
        """``GET /agent-runs`` returns empty list when no runs exist."""
        response = empty_client.get("/agent-runs")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_agent_runs(self, client: TestClient) -> None:
        """``GET /agent-runs`` returns seeded agent runs ordered by started_at DESC."""
        response = client.get("/agent-runs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        agent_types = {r["agent_type"] for r in data}
        assert agent_types == {
            "event_interpretation",
            "ai_risk",
            "final_decision_composer",
        }
        # Verify started_at DESC ordering
        started_ats = [r["started_at"] for r in data]
        assert started_ats == sorted(started_ats, reverse=True), (
            f"Expected started_at DESC order, got: {started_ats}"
        )

    def test_list_agent_runs_filter_by_decision_context(
        self, client: TestClient,
    ) -> None:
        """``GET /agent-runs?decision_context_id=...`` filters correctly."""
        # First get the full list to find a decision_context_id
        list_resp = client.get("/agent-runs")
        runs = list_resp.json()
        assert len(runs) >= 1
        ctx_id = runs[0]["decision_context_id"]

        response = client.get(f"/agent-runs?decision_context_id={ctx_id}")
        assert response.status_code == 200
        filtered = response.json()
        assert len(filtered) == 3
        for run in filtered:
            assert run["decision_context_id"] == ctx_id

    def test_list_agent_runs_filter_invalid_uuid(
        self, client: TestClient,
    ) -> None:
        """``GET /agent-runs?decision_context_id=...`` returns 400 for invalid UUID."""
        response = client.get("/agent-runs?decision_context_id=not-a-uuid")
        assert response.status_code == 400

    def test_list_agent_runs_filter_no_match(
        self, client: TestClient,
    ) -> None:
        """``GET /agent-runs?decision_context_id=...`` returns empty for unknown UUID."""
        response = client.get(
            "/agent-runs?decision_context_id=00000000-0000-0000-0000-000000000000",
        )
        assert response.status_code == 200
        assert response.json() == []


class TestAgentRunsDetail:
    """Agent run detail endpoint: ``GET /agent-runs/{id}``."""

    def test_get_agent_run(self, client: TestClient) -> None:
        """``GET /agent-runs/{id}`` returns a single agent run."""
        # First get list to find a run ID
        list_resp = client.get("/agent-runs")
        runs = list_resp.json()
        assert len(runs) >= 1
        run_id = runs[0]["agent_run_id"]

        detail_resp = client.get(f"/agent-runs/{run_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["agent_run_id"] == run_id
        assert detail["agent_type"] in (
            "event_interpretation", "ai_risk", "final_decision_composer",
        )
        assert "decision_context_id" in detail
        assert "started_at" in detail
        assert "status" in detail

    def test_get_agent_run_not_found(self, client: TestClient) -> None:
        """``GET /agent-runs/{id}`` returns 404 for unknown UUID."""
        response = client.get(
            "/agent-runs/00000000-0000-0000-0000-000000000000",
        )
        assert response.status_code == 404

    def test_get_agent_run_invalid_uuid(self, client: TestClient) -> None:
        """``GET /agent-runs/{id}`` returns 422 for invalid UUID (FastAPI validation)."""
        response = client.get("/agent-runs/not-a-uuid")
        assert response.status_code == 422
