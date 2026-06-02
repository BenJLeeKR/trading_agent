"""Tests for ``GET /clients`` and ``GET /clients/default`` endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    ClientEntity,
)
from agent_trading.domain.enums import Environment
from agent_trading.repositories.bootstrap import build_in_memory_repositories


class TestListClients:
    """``GET /clients`` — list all clients."""

    def test_list_clients(self) -> None:
        """Returns all seeded clients."""
        repos = build_in_memory_repositories()
        cid1 = uuid4()
        cid2 = uuid4()
        repos.clients._items[cid1] = ClientEntity(
            client_id=cid1,
            client_code="CLIENT-A",
            name="Client A",
            status="active",
            base_currency="KRW",
            created_at=datetime.now(timezone.utc),
        )
        repos.clients._items[cid2] = ClientEntity(
            client_id=cid2,
            client_code="CLIENT-B",
            name="Client B",
            status="inactive",
            base_currency="USD",
            created_at=datetime.now(timezone.utc),
        )

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as tc:
            resp = tc.get("/clients")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        codes = {c["client_code"] for c in data}
        assert codes == {"CLIENT-A", "CLIENT-B"}


class TestGetDefaultClient:
    """``GET /clients/default`` — resolution chain tests.

    Resolution chain::

        settings.kis_account_number
        → broker_accounts.get_by_ref(broker_name, account_ref, environment)
        → accounts.find_one(broker_account_id)
        → clients.get(account.client_id)
    """

    DEFAULT_ACCOUNT_REF = "50186448"

    def test_get_default_client_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Seed broker_account + account + client → expect 200 with correct client."""
        monkeypatch.setenv("KIS_ACCOUNT_NO", self.DEFAULT_ACCOUNT_REF)
        monkeypatch.setenv("KIS_ENV", "paper")

        repos = build_in_memory_repositories()
        client_id = uuid4()
        broker_account_id = uuid4()
        account_id = uuid4()

        # Seed broker account linked to the .env account ref
        repos.broker_accounts._items[broker_account_id] = BrokerAccountEntity(
            broker_account_id=broker_account_id,
            broker_name="koreainvestment",
            account_ref=self.DEFAULT_ACCOUNT_REF,
            environment=Environment.PAPER,
            credential_ref="test-cred",
            created_at=datetime.now(timezone.utc),
        )
        # Seed internal account linked to the broker account
        repos.accounts._items[account_id] = AccountEntity(
            account_id=account_id,
            client_id=client_id,
            broker_account_id=broker_account_id,
            environment=Environment.PAPER,
            account_alias="TEST-ACCT-001",
            account_masked="****1234",
            status="active",
            created_at=datetime.now(timezone.utc),
        )
        # Seed client that owns the account
        repos.clients._items[client_id] = ClientEntity(
            client_id=client_id,
            client_code="DEFAULT-CLIENT",
            name="Default Client",
            status="active",
            base_currency="KRW",
            created_at=datetime.now(timezone.utc),
        )

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as tc:
            resp = tc.get("/clients/default")

        assert resp.status_code == 200
        data = resp.json()
        assert data["client_id"] == str(client_id)
        assert data["client_code"] == "DEFAULT-CLIENT"
        assert data["name"] == "Default Client"

    def test_get_default_client_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No broker account seeded for the .env account ref → expect 404."""
        monkeypatch.setenv("KIS_ACCOUNT_NO", self.DEFAULT_ACCOUNT_REF)
        monkeypatch.setenv("KIS_ENV", "paper")

        repos = build_in_memory_repositories()
        # Seed an unrelated broker account that won't match
        other_id = uuid4()
        repos.broker_accounts._items[other_id] = BrokerAccountEntity(
            broker_account_id=other_id,
            broker_name="koreainvestment",
            account_ref="99999999",  # different ref
            environment=Environment.PAPER,
            credential_ref="test-cred",
            created_at=datetime.now(timezone.utc),
        )

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as tc:
            resp = tc.get("/clients/default")

        assert resp.status_code == 404

    def test_get_default_client_no_kis_account(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KIS_ACCOUNT_NO not set → expect 404."""
        monkeypatch.delenv("KIS_ACCOUNT_NO", raising=False)
        monkeypatch.delenv("KIS_ACCOUNT_NUMBER", raising=False)

        repos = build_in_memory_repositories()
        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as tc:
            resp = tc.get("/clients/default")

        assert resp.status_code == 404
        data = resp.json()
        assert "not configured" in data.get("detail", "").lower()
