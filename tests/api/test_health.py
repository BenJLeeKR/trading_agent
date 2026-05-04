"""Health endpoint tests.

``GET /health`` — returns ``200`` with minimal status info.
``GET /health/readyz`` — always returns ``200``.
``/docs`` — Swagger UI HTML is served (endpoint existence check only).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.conftest import client, empty_client  # noqa: F401


def test_health_returns_ok(empty_client: TestClient) -> None:
    """``GET /health`` returns 200 with expected fields."""
    response = empty_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert data["database"] == "in_memory"
    assert data["runtime_mode"] == "in_memory"
    assert "timestamp" in data


def test_health_readyz(empty_client: TestClient) -> None:
    """``GET /health/readyz`` returns 200."""
    response = empty_client.get("/health/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_docs_endpoint(empty_client: TestClient) -> None:
    """``GET /docs`` returns Swagger UI HTML; ``/openapi.json`` lists health endpoint."""
    # Check docs page returns HTML
    docs_response = empty_client.get("/docs")
    assert docs_response.status_code == 200
    assert "text/html" in docs_response.headers.get("content-type", "")

    # Check OpenAPI spec contains the health endpoint
    spec_response = empty_client.get("/openapi.json")
    assert spec_response.status_code == 200
    spec = spec_response.json()
    assert "/health" in spec.get("paths", {})
    assert spec["info"]["title"] == "Agent Trading Inspection API"
