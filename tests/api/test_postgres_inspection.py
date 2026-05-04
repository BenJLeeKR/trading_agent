"""Postgres-backed inspection API tests.

Requires ``DATABASE_*`` environment variables.
Uses the same ``skipif`` pattern as ``test_long_path_e2e.py``
to guard execution when Postgres is unavailable.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app


_REQUIRED_PG_VARS = (
    "DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME",
    "DATABASE_USER", "DATABASE_PASSWORD",
)


def _pg_env_complete() -> bool:
    return all(bool(os.getenv(v)) for v in _REQUIRED_PG_VARS)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
async def postgres_client() -> TestClient:
    """TestClient backed by Postgres (pool-only lifespan, request-scoped repos)."""
    app = create_app(runtime_mode="postgres", auth_enabled=False)
    with TestClient(app) as tc:
        yield tc


# ── Tests (4 representative paths) ───────────────────────────────────


@pytest.mark.skipif(not _pg_env_complete(), reason="requires DATABASE_* env vars")
class TestPostgresInspectionAPI:
    """Postgres-backed inspection API tests.

    Tests 4 representative paths to verify Postgres mode end-to-end.
    Does NOT cover all endpoints — in-memory tests do that.
    """

    async def test_health_postgres_mode(self, postgres_client: TestClient) -> None:
        """``GET /health`` returns postgres runtime mode + DB status."""
        resp = postgres_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["runtime_mode"] == "postgres"
        assert data["database"] in ("connected", "disconnected")

    async def test_list_orders_empty(self, postgres_client: TestClient) -> None:
        """``GET /orders`` returns empty list (clean DB)."""
        resp = postgres_client.get("/orders", params={"limit": 10})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_audit_logs_requires_param(
        self, postgres_client: TestClient,
    ) -> None:
        """``GET /audit-logs`` returns 422 without correlation_id."""
        resp = postgres_client.get("/audit-logs")
        assert resp.status_code == 422

    async def test_reconciliation_runs_requires_param(
        self, postgres_client: TestClient,
    ) -> None:
        """``GET /reconciliation/runs`` returns 422 without account_id."""
        resp = postgres_client.get("/reconciliation/runs")
        assert resp.status_code == 422

    async def test_reconciliation_locks_returns_lock_row(
        self, postgres_client: TestClient,
    ) -> None:
        """``GET /reconciliation/locks`` returns actual lock rows from Postgres.

        This test directly inserts a lock row (with required FK rows) and
        verifies the API returns it — addressing user caveat #3.

        Uses ``asyncpg.connect()`` directly (not ``db_connection()``) to avoid
        event loop conflicts with ``TestClient``'s internal event loop.
        """
        import asyncpg
        import os
        from uuid import uuid4
        from datetime import datetime, timezone

        dsn = (
            f"postgresql://{os.environ['DATABASE_USER']}:{os.environ['DATABASE_PASSWORD']}"
            f"@{os.environ['DATABASE_HOST']}:{os.environ['DATABASE_PORT']}"
            f"/{os.environ['DATABASE_NAME']}"
        )

        lock_id = uuid4()
        acct_id = uuid4()
        client_id = uuid4()
        broker_acct_id = uuid4()
        run_id = uuid4()
        now = datetime.now(timezone.utc)

        conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
        try:
            # Satisfy FK: accounts -> clients -> broker_accounts
            # Use unique client_code per run to avoid ON CONFLICT DO NOTHING
            # silently skipping the INSERT from a previous test run.
            client_code = f"LOCK_TEST_{acct_id.hex[:8]}"
            broker_ref = f"LOCK_REF_{acct_id.hex[:8]}"
            await conn.execute(
                "INSERT INTO trading.clients (client_id, client_code, name, status, base_currency, created_at) "
                "VALUES ($1, $2, 'Lock Test Client', 'active', 'KRW', $3)",
                client_id, client_code, now,
            )
            await conn.execute(
                "INSERT INTO trading.broker_accounts (broker_account_id, broker_name, account_ref, "
                "environment, credential_ref, status, created_at) "
                "VALUES ($1, 'TEST', $2, 'paper', 'test-cred', 'active', $3)",
                broker_acct_id, broker_ref, now,
            )
            await conn.execute(
                "INSERT INTO trading.accounts (account_id, client_id, broker_account_id, environment, "
                "account_alias, account_masked, status, created_at) "
                "VALUES ($1, $2, $3, 'paper', 'LOCK-ACCT', '****0001', 'active', $4)",
                acct_id, client_id, broker_acct_id, now,
            )
            # Satisfy FK: reconciliation_runs
            await conn.execute(
                "INSERT INTO trading.reconciliation_runs (reconciliation_run_id, account_id, "
                "trigger_type, status, started_at) "
                "VALUES ($1, $2, 'manual', 'started', $3) ON CONFLICT DO NOTHING",
                run_id, acct_id, now,
            )
            # Insert the lock row (active: far future expires_at)
            await conn.execute(
                """
                INSERT INTO trading.order_blocking_locks
                    (lock_id, account_id, strategy_id, symbol, side, reason,
                     locked_by_run_id, locked_at, expires_at)
                VALUES ($1, $2, NULL, 'AAPL', 'buy', 'reconciliation',
                        $3, $4, $5)
                ON CONFLICT DO NOTHING
                """,
                lock_id, acct_id, run_id, now,
                now.replace(year=9999),
            )
        finally:
            await conn.close()

        resp = postgres_client.get(f"/reconciliation/locks?account_id={acct_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        lock = data[0]
        assert lock["account_id"] == str(acct_id)
        assert lock["symbol"] == "AAPL"
        assert lock["side"] == "buy"
        assert lock["is_active"] is True
        assert "lock_id" in lock
        assert "locked_at" in lock
        assert "expires_at" in lock

        # Cleanup: use a separate direct connection (not db_connection pool)
        cleanup_conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
        try:
            await cleanup_conn.execute("DELETE FROM trading.order_blocking_locks WHERE lock_id = $1", lock_id)
            await cleanup_conn.execute("DELETE FROM trading.reconciliation_runs WHERE reconciliation_run_id = $1", run_id)
            await cleanup_conn.execute("DELETE FROM trading.accounts WHERE account_id = $1", acct_id)
            await cleanup_conn.execute("DELETE FROM trading.clients WHERE client_id = $1", client_id)
            await cleanup_conn.execute("DELETE FROM trading.broker_accounts WHERE broker_account_id = $1", broker_acct_id)
        finally:
            await cleanup_conn.close()

    async def test_account_by_id(self, postgres_client: TestClient) -> None:
        """``GET /accounts/{id}`` returns account from Postgres."""
        import asyncpg
        import os
        from uuid import uuid4
        from datetime import datetime, timezone

        dsn = (
            f"postgresql://{os.environ['DATABASE_USER']}:{os.environ['DATABASE_PASSWORD']}"
            f"@{os.environ['DATABASE_HOST']}:{os.environ['DATABASE_PORT']}"
            f"/{os.environ['DATABASE_NAME']}"
        )

        acct_id = uuid4()
        client_id = uuid4()
        broker_acct_id = uuid4()
        now = datetime.now(timezone.utc)

        conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
        try:
            client_code = f"ACCT_TEST_{acct_id.hex[:8]}"
            broker_ref = f"ACCT_REF_{acct_id.hex[:8]}"
            await conn.execute(
                "INSERT INTO trading.clients (client_id, client_code, name, status, base_currency, created_at) "
                "VALUES ($1, $2, 'Acct Test Client', 'active', 'KRW', $3)",
                client_id, client_code, now,
            )
            await conn.execute(
                "INSERT INTO trading.broker_accounts (broker_account_id, broker_name, account_ref, "
                "environment, credential_ref, status, created_at) "
                "VALUES ($1, 'TEST', $2, 'paper', 'test-cred', 'active', $3)",
                broker_acct_id, broker_ref, now,
            )
            await conn.execute(
                "INSERT INTO trading.accounts (account_id, client_id, broker_account_id, environment, "
                "account_alias, account_masked, status, created_at) "
                "VALUES ($1, $2, $3, 'paper', 'PG-ACCT-001', '****9999', 'active', $4)",
                acct_id, client_id, broker_acct_id, now,
            )
        finally:
            await conn.close()

        resp = postgres_client.get(f"/accounts/{acct_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_id"] == str(acct_id)
        assert data["account_alias"] == "PG-ACCT-001"
        assert data["status"] == "active"

        cleanup_conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
        try:
            await cleanup_conn.execute("DELETE FROM trading.accounts WHERE account_id = $1", acct_id)
            await cleanup_conn.execute("DELETE FROM trading.clients WHERE client_id = $1", client_id)
            await cleanup_conn.execute("DELETE FROM trading.broker_accounts WHERE broker_account_id = $1", broker_acct_id)
        finally:
            await cleanup_conn.close()

    async def test_instrument_by_id(self, postgres_client: TestClient) -> None:
        """``GET /instruments/{id}`` returns instrument from Postgres."""
        import asyncpg
        import os
        from uuid import uuid4
        from datetime import datetime, timezone

        dsn = (
            f"postgresql://{os.environ['DATABASE_USER']}:{os.environ['DATABASE_PASSWORD']}"
            f"@{os.environ['DATABASE_HOST']}:{os.environ['DATABASE_PORT']}"
            f"/{os.environ['DATABASE_NAME']}"
        )

        instr_id = uuid4()
        now = datetime.now(timezone.utc)

        conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
        try:
            await conn.execute(
                "INSERT INTO trading.instruments (instrument_id, symbol, market_code, asset_class, "
                "currency, name, is_active, created_at) "
                "VALUES ($1, 'TSLA', 'NASDAQ', 'us_stock', 'USD', 'Tesla Inc.', TRUE, $2)",
                instr_id, now,
            )
        finally:
            await conn.close()

        resp = postgres_client.get(f"/instruments/{instr_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["instrument_id"] == str(instr_id)
        assert data["symbol"] == "TSLA"
        assert data["market_code"] == "NASDAQ"
        assert data["is_active"] is True

        cleanup_conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
        try:
            await cleanup_conn.execute("DELETE FROM trading.instruments WHERE instrument_id = $1", instr_id)
        finally:
            await cleanup_conn.close()

    async def test_cash_balance_empty_null(self, postgres_client: TestClient) -> None:
        """``GET /cash-balances`` returns 200 null when no snapshot exists."""
        import asyncpg
        import os
        from uuid import uuid4
        from datetime import datetime, timezone

        dsn = (
            f"postgresql://{os.environ['DATABASE_USER']}:{os.environ['DATABASE_PASSWORD']}"
            f"@{os.environ['DATABASE_HOST']}:{os.environ['DATABASE_PORT']}"
            f"/{os.environ['DATABASE_NAME']}"
        )

        acct_id = uuid4()
        client_id = uuid4()
        broker_acct_id = uuid4()
        now = datetime.now(timezone.utc)

        conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
        try:
            client_code = f"CB_NULL_{acct_id.hex[:8]}"
            broker_ref = f"CB_REF_{acct_id.hex[:8]}"
            await conn.execute(
                "INSERT INTO trading.clients (client_id, client_code, name, status, base_currency, created_at) "
                "VALUES ($1, $2, 'CB Null Client', 'active', 'KRW', $3)",
                client_id, client_code, now,
            )
            await conn.execute(
                "INSERT INTO trading.broker_accounts (broker_account_id, broker_name, account_ref, "
                "environment, credential_ref, status, created_at) "
                "VALUES ($1, 'TEST', $2, 'paper', 'test-cred', 'active', $3)",
                broker_acct_id, broker_ref, now,
            )
            await conn.execute(
                "INSERT INTO trading.accounts (account_id, client_id, broker_account_id, environment, "
                "account_alias, account_masked, status, created_at) "
                "VALUES ($1, $2, $3, 'paper', 'CB-NULL-ACCT', '****0000', 'active', $4)",
                acct_id, client_id, broker_acct_id, now,
            )
            # No cash_balance_snapshot inserted — intentionally empty
        finally:
            await conn.close()

        resp = postgres_client.get(f"/cash-balances?account_id={acct_id}")
        assert resp.status_code == 200
        assert resp.json() is None, "Expected null for account with no cash balance snapshot"

        cleanup_conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
        try:
            await cleanup_conn.execute("DELETE FROM trading.accounts WHERE account_id = $1", acct_id)
            await cleanup_conn.execute("DELETE FROM trading.clients WHERE client_id = $1", client_id)
            await cleanup_conn.execute("DELETE FROM trading.broker_accounts WHERE broker_account_id = $1", broker_acct_id)
        finally:
            await cleanup_conn.close()
