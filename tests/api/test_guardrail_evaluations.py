"""API-level contract tests for ``GET /guardrail-evaluations``.

Validates (4 tests):

1. **List by decision_context_id** — ``GET /guardrail-evaluations?decision_context_id=...``
   - 200 + non-empty array + ``overall_passed`` / ``rule_set_version`` field shape
   - Discovers ``decision_context_id`` via ``GET /agent-runs`` (data lookup, not
     an agent-runs test itself)

2. **No filter** — ``GET /guardrail-evaluations`` (no param)
   - 200 + empty list (no default filter)

3. **Get by ID** — ``GET /guardrail-evaluations/{id}``
   - 200 + field shape, discovered via list → detail chain
   - Also uses ``GET /agent-runs`` for ``decision_context_id`` lookup

4. **Not found** — ``GET /guardrail-evaluations/{id}`` for unknown UUID
   - 404
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.conftest import client  # noqa: F401


class TestGuardrailEvaluations:
    """Guardrail evaluation inspection endpoints.

    Tests 1 and 3 call ``GET /agent-runs`` solely to obtain a seeded
    ``decision_context_id`` for filtering guardrail evaluations. This is a
    fixture-level data lookup, not a test of agent-runs itself.
    """

    def test_list_guardrail_evaluations_by_decision_context(
        self, client: TestClient,
    ) -> None:
        """``GET /guardrail-evaluations?decision_context_id=...`` returns results."""
        # Get a decision context ID from agent runs
        runs_resp = client.get("/agent-runs")
        runs = runs_resp.json()
        assert len(runs) >= 1
        ctx_id = runs[0]["decision_context_id"]

        response = client.get(
            f"/guardrail-evaluations?decision_context_id={ctx_id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["overall_passed"] is True
        assert data[0]["rule_set_version"] == "v1.0"

    def test_list_guardrail_evaluations_empty_no_filter(
        self, client: TestClient,
    ) -> None:
        """``GET /guardrail-evaluations`` returns empty list when no filter given."""
        response = client.get("/guardrail-evaluations")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_guardrail_evaluation_by_id(
        self, client: TestClient,
    ) -> None:
        """``GET /guardrail-evaluations/{id}`` returns a single evaluation."""
        # First get list to find an evaluation ID
        runs_resp = client.get("/agent-runs")
        runs = runs_resp.json()
        assert len(runs) >= 1
        ctx_id = runs[0]["decision_context_id"]

        list_resp = client.get(
            f"/guardrail-evaluations?decision_context_id={ctx_id}"
        )
        evaluations = list_resp.json()
        assert len(evaluations) >= 1
        eval_id = evaluations[0]["guardrail_evaluation_id"]

        detail_resp = client.get(f"/guardrail-evaluations/{eval_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["guardrail_evaluation_id"] == eval_id
        assert detail["overall_passed"] is True

    def test_get_guardrail_evaluation_not_found(
        self, client: TestClient,
    ) -> None:
        """``GET /guardrail-evaluations/{id}`` returns 404 for unknown UUID."""
        response = client.get(
            "/guardrail-evaluations/00000000-0000-0000-0000-000000000000"
        )
        assert response.status_code == 404
