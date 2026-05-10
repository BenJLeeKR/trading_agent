"""API-level contract tests for ``GET /risk-limit-snapshots``.

Validates (4 tests):

1. **List snapshots** — ``GET /risk-limit-snapshots?account_id=...``
   - 200 + non-empty array + ``nav`` / ``kill_switch_active`` field shape

2. **Missing account_id** — ``GET /risk-limit-snapshots`` (no param)
   - 422 validation error

3. **Latest snapshot** — ``GET /risk-limit-snapshots/latest?account_id=...``
   - 200 + ``account_id`` match + ``nav`` present

4. **Latest snapshot not found** — ``GET /risk-limit-snapshots/latest?account_id=...``
   - 404 for unknown account UUID
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api.conftest import client  # noqa: F401


class TestRiskLimitSnapshots:
    """Risk limit snapshot inspection endpoints.

    ``_get_account_id`` — local class-method helper that discovers the seeded
    account ID via ``GET /clients`` → ``GET /accounts?client_id=...`` chain.
    Kept inside this class because it is specific to risk-limit-snapshot tests;
    no other file uses this helper pattern.
    """

    def _get_account_id(self, client: TestClient) -> str:
        """Helper: get the seeded account_id via /clients then /accounts."""
        clients_resp = client.get("/clients")
        clients = clients_resp.json()
        assert len(clients) >= 1
        cid = clients[0]["client_id"]

        acct_resp = client.get(f"/accounts?client_id={cid}")
        accounts = acct_resp.json()
        assert len(accounts) >= 1
        return accounts[0]["account_id"]

    def test_list_risk_limit_snapshots(
        self, client: TestClient,
    ) -> None:
        """``GET /risk-limit-snapshots?account_id=...`` returns snapshots."""
        acct_id = self._get_account_id(client)

        response = client.get(
            f"/risk-limit-snapshots?account_id={acct_id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["nav"] is not None
        assert data[0]["kill_switch_active"] is False

    def test_list_risk_limit_snapshots_requires_account(
        self, client: TestClient,
    ) -> None:
        """``GET /risk-limit-snapshots`` returns 422 without account_id."""
        response = client.get("/risk-limit-snapshots")
        assert response.status_code == 422

    def test_get_latest_risk_limit_snapshot(
        self, client: TestClient,
    ) -> None:
        """``GET /risk-limit-snapshots/latest?account_id=...`` returns latest."""
        acct_id = self._get_account_id(client)

        response = client.get(
            f"/risk-limit-snapshots/latest?account_id={acct_id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["account_id"] == acct_id
        assert data["nav"] is not None

    def test_get_latest_risk_limit_snapshot_not_found(
        self, client: TestClient,
    ) -> None:
        """``GET /risk-limit-snapshots/latest`` returns 404 for unknown account."""
        response = client.get(
            "/risk-limit-snapshots/latest"
            "?account_id=00000000-0000-0000-0000-000000000000"
        )
        assert response.status_code == 404
