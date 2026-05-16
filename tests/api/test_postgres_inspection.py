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
        """``GET /reconciliation/runs`` returns 200 (empty list) without account_id."""
        resp = postgres_client.get("/reconciliation/runs")
        assert resp.status_code == 200
        assert resp.json() == []

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

    async def test_agent_runs_list_all(self, postgres_client: TestClient) -> None:
        """``GET /agent-runs`` returns seeded rows from Postgres in started_at DESC."""
        import asyncpg
        import os
        from uuid import uuid4
        from datetime import datetime, timezone, timedelta

        dsn = (
            f"postgresql://{os.environ['DATABASE_USER']}:{os.environ['DATABASE_PASSWORD']}"
            f"@{os.environ['DATABASE_HOST']}:{os.environ['DATABASE_PORT']}"
            f"/{os.environ['DATABASE_NAME']}"
        )

        ctx_id = uuid4()
        now = datetime.now(timezone.utc)

        conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
        try:
            # Satisfy FK: agent_runs -> decision_contexts
            await conn.execute(
                "INSERT INTO trading.decision_contexts (decision_context_id, correlation_id, "
                "decision_type, triggered_by, status, created_at) "
                "VALUES ($1, $2, 'order', 'test', 'active', $3)",
                ctx_id, f"PG_AR_LIST_{ctx_id.hex[:8]}", now,
            )
            # Insert 3 agent runs with different started_at values
            run_ids = [uuid4() for _ in range(3)]
            agent_types = ["event_interpretation", "ai_risk", "final_decision_composer"]
            started_ats = [
                now - timedelta(seconds=2),
                now - timedelta(seconds=1),
                now,
            ]
            for rid, atype, sat in zip(run_ids, agent_types, started_ats):
                await conn.execute(
                    "INSERT INTO trading.agent_runs (agent_run_id, decision_context_id, agent_type, "
                    "started_at, status, completed_at, created_at) "
                    "VALUES ($1, $2, $3, $4, 'completed', $5, $6)",
                    rid, ctx_id, atype, sat, sat, sat,
                )
        finally:
            await conn.close()

        seed_ids = {str(rid) for rid in run_ids}

        resp = postgres_client.get("/agent-runs")
        assert resp.status_code == 200
        data = resp.json()

        # Filter to only our seeded runs — avoids dependency on global DB state
        our_runs = [r for r in data if r["agent_run_id"] in seed_ids]

        # Cleanup runs even if assertions below fail
        cleanup_conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
        try:
            assert len(our_runs) == 3, f"Expected 3 seeded runs, found {len(our_runs)}"
            # Verify started_at DESC ordering among our seeded runs
            our_ats = [r["started_at"] for r in our_runs]
            assert our_ats == sorted(our_ats, reverse=True), (
                f"Expected started_at DESC order, got: {our_ats}"
            )
            # Verify all 3 agent types present
            returned_types = {r["agent_type"] for r in our_runs}
            assert returned_types == set(agent_types)
        finally:
            for rid in run_ids:
                await cleanup_conn.execute("DELETE FROM trading.agent_runs WHERE agent_run_id = $1", rid)
            await cleanup_conn.execute("DELETE FROM trading.decision_contexts WHERE decision_context_id = $1", ctx_id)
            await cleanup_conn.close()

    async def test_agent_runs_filter_by_decision_context(
        self, postgres_client: TestClient,
    ) -> None:
        """``GET /agent-runs?decision_context_id=...`` filters correctly."""
        import asyncpg
        import os
        from uuid import uuid4
        from datetime import datetime, timezone, timedelta

        dsn = (
            f"postgresql://{os.environ['DATABASE_USER']}:{os.environ['DATABASE_PASSWORD']}"
            f"@{os.environ['DATABASE_HOST']}:{os.environ['DATABASE_PORT']}"
            f"/{os.environ['DATABASE_NAME']}"
        )

        ctx_a = uuid4()
        ctx_b = uuid4()
        now = datetime.now(timezone.utc)

        conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
        try:
            # Insert 2 decision contexts
            for ctx_id, suffix in [(ctx_a, "A"), (ctx_b, "B")]:
                await conn.execute(
                    "INSERT INTO trading.decision_contexts (decision_context_id, correlation_id, "
                    "decision_type, triggered_by, status, created_at) "
                    "VALUES ($1, $2, 'order', 'test', 'active', $3)",
                    ctx_id, f"PG_AR_FILTER_{suffix}_{ctx_id.hex[:8]}", now,
                )
            # Insert 1 run for ctx_a, 2 runs for ctx_b
            run_a = uuid4()
            run_b1 = uuid4()
            run_b2 = uuid4()
            await conn.execute(
                "INSERT INTO trading.agent_runs (agent_run_id, decision_context_id, agent_type, "
                "started_at, status, completed_at, created_at) "
                "VALUES ($1, $2, 'event_interpretation', $3, 'completed', $4, $5)",
                run_a, ctx_a, now, now, now,
            )
            for rid, atype, sat in [
                (run_b1, "ai_risk", now - timedelta(seconds=1)),
                (run_b2, "final_decision_composer", now),
            ]:
                await conn.execute(
                    "INSERT INTO trading.agent_runs (agent_run_id, decision_context_id, agent_type, "
                    "started_at, status, completed_at, created_at) "
                    "VALUES ($1, $2, $3, $4, 'completed', $5, $6)",
                    rid, ctx_b, atype, sat, sat, sat,
                )
        finally:
            await conn.close()

        all_run_ids = (run_a, run_b1, run_b2)
        all_ctx_ids = (ctx_a, ctx_b)

        # Open cleanup connection upfront so it runs even if assertions fail
        cleanup_conn = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
        try:
            # Filter by ctx_a — should return 1 row
            resp_a = postgres_client.get(f"/agent-runs?decision_context_id={ctx_a}")
            assert resp_a.status_code == 200
            data_a = resp_a.json()
            assert len(data_a) == 1
            assert data_a[0]["agent_type"] == "event_interpretation"
            assert data_a[0]["decision_context_id"] == str(ctx_a)

            # Filter by ctx_b — should return 2 rows in DESC order
            resp_b = postgres_client.get(f"/agent-runs?decision_context_id={ctx_b}")
            assert resp_b.status_code == 200
            data_b = resp_b.json()
            assert len(data_b) == 2
            started_ats = [r["started_at"] for r in data_b]
            assert started_ats == sorted(started_ats, reverse=True)
        finally:
            for rid in all_run_ids:
                await cleanup_conn.execute("DELETE FROM trading.agent_runs WHERE agent_run_id = $1", rid)
            for ctx_id in all_ctx_ids:
                await cleanup_conn.execute("DELETE FROM trading.decision_contexts WHERE decision_context_id = $1", ctx_id)
            await cleanup_conn.close()

    async def test_agent_runs_filter_invalid_uuid(
        self, postgres_client: TestClient,
    ) -> None:
        """``GET /agent-runs?decision_context_id=invalid`` returns 400."""
        resp = postgres_client.get("/agent-runs?decision_context_id=not-a-uuid")
        assert resp.status_code == 400

    async def test_agent_runs_filter_no_match(
        self, postgres_client: TestClient,
    ) -> None:
        """``GET /agent-runs?decision_context_id=<unknown>`` returns empty list."""
        from uuid import uuid4

        unknown_id = uuid4()
        resp = postgres_client.get(f"/agent-runs?decision_context_id={unknown_id}")
        assert resp.status_code == 200
        assert resp.json() == []

    # ── Guardrail Evaluation smoke tests ───────────────────────────────

    async def test_guardrail_evaluations_requires_filter(
        self, postgres_client: TestClient,
    ) -> None:
        """``GET /guardrail-evaluations`` returns empty list without filter."""
        resp = postgres_client.get("/guardrail-evaluations")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_guardrail_evaluations_by_decision_context(
        self, postgres_client: TestClient,
    ) -> None:
        """``GET /guardrail-evaluations?decision_context_id=<unknown>`` returns empty."""
        from uuid import uuid4

        unknown_id = uuid4()
        resp = postgres_client.get(
            f"/guardrail-evaluations?decision_context_id={unknown_id}"
        )
        assert resp.status_code == 200
        assert resp.json() == []

    # ── Risk Limit Snapshot smoke tests ────────────────────────────────

    async def test_risk_limit_snapshots_requires_account(
        self, postgres_client: TestClient,
    ) -> None:
        """``GET /risk-limit-snapshots`` returns 422 without account_id."""
        resp = postgres_client.get("/risk-limit-snapshots")
        assert resp.status_code == 422

    async def test_risk_limit_snapshots_unknown_account(
        self, postgres_client: TestClient,
    ) -> None:
        """``GET /risk-limit-snapshots?account_id=<unknown>`` returns empty list."""
        from uuid import uuid4

        unknown_id = uuid4()
        resp = postgres_client.get(
            f"/risk-limit-snapshots?account_id={unknown_id}"
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_risk_limit_snapshots_latest_unknown_account(
        self, postgres_client: TestClient,
    ) -> None:
        """``GET /risk-limit-snapshots/latest?account_id=<unknown>`` returns 404."""
        from uuid import uuid4

        unknown_id = uuid4()
        resp = postgres_client.get(
            f"/risk-limit-snapshots/latest?account_id={unknown_id}"
        )
        assert resp.status_code == 404
