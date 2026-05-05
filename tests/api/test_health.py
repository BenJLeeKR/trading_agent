"""Health endpoint tests.

``GET /health`` — returns ``200`` with minimal status info.
``GET /health/readyz`` — always returns ``200``.
``/docs`` — Swagger UI HTML is served (endpoint existence check only).
"""

from __future__ import annotations

import os

import pytest
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


def test_admin_ui_static_mount(empty_client: TestClient) -> None:
    """``GET /admin`` returns 200 when ``admin_ui/dist`` exists.

    The static mount is conditional — ``create_app()`` only mounts ``/admin``
    when the built ``admin_ui/dist`` directory is present.  Skip cleanly when
    the dist directory has not been built yet (e.g. fresh checkout).
    """
    _dist_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "admin_ui", "dist"
    )
    if not os.path.isdir(_dist_path):
        pytest.skip("admin_ui/dist not found — run 'npm run build' first")

    response = empty_client.get("/admin")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
