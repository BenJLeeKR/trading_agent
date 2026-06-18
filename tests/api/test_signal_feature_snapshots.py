"""API-level contract tests for ``GET /signal-feature-snapshots``."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    StrategyEntity,
)
from agent_trading.domain.enums import Environment
from agent_trading.repositories.bootstrap import build_in_memory_repositories

from tests.api.conftest import client  # noqa: F401


class TestSignalFeatureSnapshots:
    def test_list_signal_feature_snapshots(
        self, client: TestClient,
    ) -> None:
        response = client.get(
            "/signal-feature-snapshots?symbol=AAPL&market=NASDAQ"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["symbol"] == "AAPL"
        assert data[0]["timeframe"] == "1d"
        assert data[0]["overall_score"] is not None

    def test_list_signal_feature_snapshots_requires_symbol(
        self, client: TestClient,
    ) -> None:
        response = client.get("/signal-feature-snapshots")
        assert response.status_code == 422

    def test_get_latest_signal_feature_snapshot(
        self, client: TestClient,
    ) -> None:
        response = client.get(
            "/signal-feature-snapshots/latest?symbol=AAPL&market=NASDAQ"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert data["overall_score"] is not None
        assert "reason_codes" in data

    def test_get_latest_signal_feature_snapshot_not_found(
        self, client: TestClient,
    ) -> None:
        response = client.get(
            "/signal-feature-snapshots/latest?symbol=000000&market=NASDAQ"
        )
        assert response.status_code == 404

    def test_get_signal_feature_decision_context_coverage(self) -> None:
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)

        client_id = uuid4()
        broker_account_id = uuid4()
        account_id = uuid4()
        strategy_id = uuid4()
        config_version_id = uuid4()

        repos.broker_accounts._items[broker_account_id] = BrokerAccountEntity(
            broker_account_id=broker_account_id,
            broker_name="TEST_BROKER",
            account_ref="test-ref-coverage",
            environment=Environment.PAPER,
            credential_ref="test-cred",
            base_url="https://test.broker/api",
            status="active",
            broker_account_code="TEST-PAPER-****2001",
        )
        repos.accounts._items[account_id] = AccountEntity(
            account_id=account_id,
            client_id=client_id,
            broker_account_id=broker_account_id,
            environment=Environment.PAPER,
            account_alias="coverage-account",
            account_masked="****5678",
            status="active",
        )
        repos.strategies._items[strategy_id] = StrategyEntity(
            strategy_id=strategy_id,
            client_id=client_id,
            strategy_code="TEST_COVERAGE",
            name="Coverage Strategy",
            asset_class="KR_STOCK",
            status="active",
        )
        repos.config_versions._items[config_version_id] = ConfigVersionEntity(
            config_version_id=config_version_id,
            client_id=client_id,
            environment=Environment.PAPER,
            version_tag="v1.0",
            config_json={},
            checksum="coverage-abc123",
        )
        anchored_context_id = uuid4()
        missing_context_id = uuid4()
        repos.decision_contexts._items[anchored_context_id] = DecisionContextEntity(
            decision_context_id=anchored_context_id,
            account_id=account_id,
            strategy_id=strategy_id,
            config_version_id=config_version_id,
            market_timestamp=now,
            correlation_id="coverage-anchored",
            signal_feature_snapshot_id=uuid4(),
            created_at=now,
        )
        repos.decision_contexts._items[missing_context_id] = DecisionContextEntity(
            decision_context_id=missing_context_id,
            account_id=account_id,
            strategy_id=strategy_id,
            config_version_id=config_version_id,
            market_timestamp=now,
            correlation_id="coverage-missing",
            created_at=now,
        )

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as tc:
            response = tc.get("/signal-feature-snapshots/decision-context-coverage?limit=10")

        assert response.status_code == 200
        data = response.json()
        assert data["recent_context_count"] == 2
        assert data["anchored_context_count"] == 1
        assert data["missing_context_count"] == 1
        assert data["coverage_rate"] == 0.5
        assert str(missing_context_id) in data["sampled_missing_context_ids"]
