"""Auth / RBAC tests for the Inspection API.

Test categories
---------------
* **Public endpoints** — accessible without any token (health, docs, openapi).
* **Protected endpoints without auth** — expect 401.
* **Protected endpoints with valid token** — expect 200.
* **Invalid / malformed token** — expect 401.
* **Startup validation** — ``ValueError`` on bad config (whitespace token,
  invalid role).
* **OpenAPI security scheme** — BearerAuth scheme present in spec.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from agent_trading.api.app import create_app

# ── Helpers ────────────────────────────────────────────────────────────────────

_VALID_TOKEN = "test-token"
_INVALID_TOKEN = "invalid-token"
_WRONG_SCHEME = "Basic dGVzdC10b2tlbjo="  # "test-token:" base64 (Basic auth)


def _auth_header(token: str = _VALID_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════════════════
# A. Public endpoints — no token required
# ═══════════════════════════════════════════════════════════════════════════════


class TestPublicEndpoints:
    """Endpoints that must be accessible without any authentication."""

    def test_health_public_without_token(self, empty_client: TestClient) -> None:
        """``GET /health`` returns 200 without auth."""
        resp = empty_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_health_readyz_public_without_token(self, empty_client: TestClient) -> None:
        """``GET /health/readyz`` returns 200 without auth."""
        resp = empty_client.get("/health/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_docs_public_without_token(self, empty_client: TestClient) -> None:
        """``GET /docs`` (Swagger UI) returns 200 without auth."""
        resp = empty_client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json_public_without_token(self, empty_client: TestClient) -> None:
        """``GET /openapi.json`` returns 200 without auth."""
        resp = empty_client.get("/openapi.json")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# B. Protected endpoints without auth — expect 401
# ═══════════════════════════════════════════════════════════════════════════════


class TestProtectedEndpointsUnauthenticated:
    """Protected endpoints called without any Authorization header → 401."""

    def _assert_unauthorized(self, client: TestClient, path: str) -> None:
        resp = client.get(path)
        assert resp.status_code == 401, f"Expected 401 for GET {path}"

    def test_orders_unauthorized(self, auth_client: TestClient) -> None:
        self._assert_unauthorized(auth_client, "/orders")

    def test_audit_logs_unauthorized(self, auth_client: TestClient) -> None:
        self._assert_unauthorized(auth_client, "/audit-logs")

    def test_reconciliation_runs_unauthorized(self, auth_client: TestClient) -> None:
        self._assert_unauthorized(auth_client, "/reconciliation/runs")

    def test_reconciliation_locks_unauthorized(self, auth_client: TestClient) -> None:
        self._assert_unauthorized(auth_client, "/reconciliation/locks")

    def test_trade_decisions_unauthorized(self, auth_client: TestClient) -> None:
        self._assert_unauthorized(auth_client, "/trade-decisions")

    def test_accounts_unauthorized(self, auth_client: TestClient) -> None:
        self._assert_unauthorized(auth_client, "/accounts")

    def test_instruments_unauthorized(self, auth_client: TestClient) -> None:
        self._assert_unauthorized(auth_client, "/instruments/00000000-0000-0000-0000-000000000001")

    def test_positions_unauthorized(self, auth_client: TestClient) -> None:
        self._assert_unauthorized(auth_client, "/positions")

    def test_cash_balances_unauthorized(self, auth_client: TestClient) -> None:
        self._assert_unauthorized(auth_client, "/cash-balances")

    def test_clients_unauthorized(self, auth_client: TestClient) -> None:
        self._assert_unauthorized(auth_client, "/clients/00000000-0000-0000-0000-000000000001")


# ═══════════════════════════════════════════════════════════════════════════════
# C. Protected endpoints with valid Bearer token — expect 200
# ═══════════════════════════════════════════════════════════════════════════════


class TestProtectedEndpointsAuthenticated:
    """Protected endpoints called with a valid Bearer token → 200."""

    def test_orders_authorized(self, auth_client: TestClient) -> None:
        """``GET /orders`` with valid Bearer token → 200."""
        resp = auth_client.get("/orders", headers=_auth_header())
        assert resp.status_code == 200

    def test_trade_decisions_authorized(self, auth_client: TestClient) -> None:
        """``GET /trade-decisions`` with valid Bearer token → 200 (empty list)."""
        resp = auth_client.get(
            "/trade-decisions?decision_context_id=00000000-0000-0000-0000-000000000000",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_health_still_public_with_token(self, empty_client: TestClient) -> None:
        """Health still works even with Bearer token (no auth dependency)."""
        resp = empty_client.get("/health", headers=_auth_header())
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# D. Invalid / malformed token — expect 401
# ═══════════════════════════════════════════════════════════════════════════════


class TestInvalidToken:
    """Endpoints called with invalid or malformed tokens → 401."""

    def test_invalid_token(self, auth_client: TestClient) -> None:
        """Wrong Bearer token value → 401."""
        resp = auth_client.get("/orders", headers=_auth_header(_INVALID_TOKEN))
        assert resp.status_code == 401

    def test_wrong_scheme(self, auth_client: TestClient) -> None:
        """Basic auth instead of Bearer → 401."""
        resp = auth_client.get("/orders", headers={"Authorization": _WRONG_SCHEME})
        assert resp.status_code == 401

    def test_missing_header(self, auth_client: TestClient) -> None:
        """No Authorization header at all → 401."""
        resp = auth_client.get("/orders")
        assert resp.status_code == 401

    def test_empty_token(self, auth_client: TestClient) -> None:
        """Bearer token with empty value → 401."""
        resp = auth_client.get("/orders", headers={"Authorization": "Bearer "})
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# E. OpenAPI security scheme validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestOpenAPISecurityScheme:
    """Verify the OpenAPI spec includes the BearerAuth security scheme."""

    def test_openapi_security_scheme_exists(self, empty_client: TestClient) -> None:
        """OpenAPI spec contains ``BearerAuth`` in ``components.securitySchemes``."""
        resp = empty_client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()

        schemes = spec.get("components", {}).get("securitySchemes", {})
        assert "BearerAuth" in schemes, (
            f"Expected BearerAuth in securitySchemes, got {list(schemes.keys())}"
        )
        bearer = schemes["BearerAuth"]
        assert bearer["type"] == "http"
        assert bearer["scheme"] == "bearer"

    def test_openapi_global_security_not_set(self, empty_client: TestClient) -> None:
        """Global ``security`` is NOT set — public endpoints stay unlocked."""
        resp = empty_client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()

        # Global security should not be present, or should be an empty list
        assert "security" not in spec or spec["security"] == [], (
            "Global security should not be set, otherwise public endpoints "
            "show lock icons in Swagger UI"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# F. Startup validation — create_app() reject bad config
# ═══════════════════════════════════════════════════════════════════════════════


class TestStartupValidation:
    """``create_app()`` raises ``ValueError`` on invalid configuration."""

    def test_whitespace_only_token_raises_value_error(self) -> None:
        """Whitespace-only token is rejected at startup."""
        with pytest.raises(ValueError, match="auth_token must be a non-empty string"):
            create_app(auth_enabled=True, auth_token="   ")

    def test_empty_token_raises_value_error(self) -> None:
        """Empty string token is rejected at startup."""
        with pytest.raises(ValueError, match="auth_token must be a non-empty string"):
            create_app(auth_enabled=True, auth_token="")

    def test_none_token_raises_value_error(self) -> None:
        """``None`` token is rejected at startup."""
        with pytest.raises(ValueError, match="auth_token must be a non-empty string"):
            create_app(auth_enabled=True, auth_token=None)

    def test_invalid_role_raises_value_error(self) -> None:
        """Role other than ``viewer`` or ``admin`` is rejected."""
        with pytest.raises(ValueError, match="Invalid auth_role"):
            create_app(auth_enabled=True, auth_token="valid-token", auth_role="superadmin")

    def test_valid_admin_role_succeeds(self) -> None:
        """``auth_role="admin"`` is accepted."""
        app = create_app(auth_enabled=True, auth_token="valid-token", auth_role="admin")
        assert app is not None

    def test_auth_disabled_ignores_token_validation(self) -> None:
        """``auth_enabled=False`` skips token validation entirely."""
        app = create_app(
            auth_enabled=False, auth_token=None, auth_role="viewer"
        )
        assert app is not None
