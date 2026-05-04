"""Postgres ``ReconciliationRepository.list_locks()`` integration tests.

Requires ``DATABASE_*`` environment variables.
Uses the same ``skipif`` pattern as other Postgres repository tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from agent_trading.repositories.container import RepositoryContainer


@pytest.mark.skipif(
    not __import__("os").getenv("DATABASE_HOST"),
    reason="requires DATABASE_* env vars",
)
class TestPostgresBlockingLocks:
    """``list_locks()`` integration tests using the ``seeded_postgres_data`` fixture.

    Each test gets a clean, rolled-back transaction via ``force_rollback=True``.
    FK requirements are satisfied by ``seeded_postgres_data`` (client, account,
    broker_account, instrument, strategy already seeded).
    """

    @pytest.mark.asyncio
    async def test_list_locks_empty(
        self, seeded_postgres_data: RepositoryContainer,
    ) -> None:
        """``list_locks()`` returns empty list when no locks exist."""
        repos = seeded_postgres_data
        other_id = uuid4()
        results = await repos.reconciliations.list_locks(other_id)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_list_locks_with_lock(
        self, seeded_postgres_data: RepositoryContainer,
    ) -> None:
        """``list_locks()`` returns a lock row that was directly inserted."""
        repos = seeded_postgres_data
        conn = repos.unit_of_work.connection
        now = datetime.now(timezone.utc)

        # Get the seeded account_id
        row = await conn.fetchrow(
            "SELECT account_id FROM trading.accounts LIMIT 1"
        )
        assert row is not None
        account_id: UUID = row["account_id"]

        # Get a seeded strategy_id
        row = await conn.fetchrow(
            "SELECT strategy_id FROM trading.strategies LIMIT 1"
        )
        assert row is not None
        strategy_id: UUID = row["strategy_id"]

        # Insert a reconciliation run (FK target for locked_by_run_id)
        run_id = uuid4()
        await conn.execute(
            """
            INSERT INTO trading.reconciliation_runs
                (reconciliation_run_id, account_id, trigger_type, status, started_at)
            VALUES ($1, $2, 'manual', 'started', $3)
            """,
            run_id, account_id, now,
        )

        # Insert an active lock row
        lock_id = uuid4()
        await conn.execute(
            """
            INSERT INTO trading.order_blocking_locks
                (lock_id, account_id, strategy_id, symbol, side, reason,
                 locked_by_run_id, locked_at, expires_at)
            VALUES ($1, $2, $3, 'AAPL', 'buy', 'reconciliation',
                    $4, $5, $6)
            """,
            lock_id, account_id, strategy_id, run_id, now,
            now.replace(year=9999),  # far future = active
        )

        results = await repos.reconciliations.list_locks(account_id)
        assert len(results) >= 1
        lock = results[0]
        assert lock.lock_id == lock_id
        assert lock.account_id == account_id
        assert lock.strategy_id == strategy_id
        assert lock.symbol == "AAPL"
        assert lock.side == "buy"
        assert lock.reason == "reconciliation"
        assert lock.locked_by_run_id == run_id
        assert lock.locked_at is not None
        assert lock.expires_at is not None

    @pytest.mark.asyncio
    async def test_list_locks_expired_filtered(
        self, seeded_postgres_data: RepositoryContainer,
    ) -> None:
        """``list_locks()`` excludes expired locks (``expires_at <= NOW()``)."""
        repos = seeded_postgres_data
        conn = repos.unit_of_work.connection
        now = datetime.now(timezone.utc)

        # Get the seeded account_id
        row = await conn.fetchrow(
            "SELECT account_id FROM trading.accounts LIMIT 1"
        )
        assert row is not None
        account_id: UUID = row["account_id"]

        # Get a seeded strategy_id
        row = await conn.fetchrow(
            "SELECT strategy_id FROM trading.strategies LIMIT 1"
        )
        assert row is not None
        strategy_id: UUID = row["strategy_id"]

        # Insert a reconciliation run
        run_id = uuid4()
        await conn.execute(
            """
            INSERT INTO trading.reconciliation_runs
                (reconciliation_run_id, account_id, trigger_type, status, started_at)
            VALUES ($1, $2, 'manual', 'started', $3)
            """,
            run_id, account_id, now,
        )

        # Insert an expired lock (expires_at in the past)
        lock_id = uuid4()
        past = datetime(2020, 1, 1, tzinfo=timezone.utc)
        await conn.execute(
            """
            INSERT INTO trading.order_blocking_locks
                (lock_id, account_id, strategy_id, symbol, side, reason,
                 locked_by_run_id, locked_at, expires_at)
            VALUES ($1, $2, $3, 'AAPL', 'buy', 'reconciliation',
                    $4, $5, $6)
            """,
            lock_id, account_id, strategy_id, run_id, past, past,
        )

        results = await repos.reconciliations.list_locks(account_id)
        # The expired lock should not appear
        for lock in results:
            assert lock.lock_id != lock_id

    @pytest.mark.asyncio
    async def test_list_locks_account_filter(
        self, seeded_postgres_data: RepositoryContainer,
    ) -> None:
        """``list_locks()`` only returns locks for the requested account."""
        repos = seeded_postgres_data
        conn = repos.unit_of_work.connection
        now = datetime.now(timezone.utc)

        # Get the seeded account_id
        row = await conn.fetchrow(
            "SELECT account_id FROM trading.accounts LIMIT 1"
        )
        assert row is not None
        account_id_a: UUID = row["account_id"]

        # Create a second account
        account_id_b = uuid4()
        client_id = uuid4()
        broker_acct_id = uuid4()
        await conn.execute(
            "INSERT INTO trading.clients (client_id, client_code, name, status, base_currency, created_at) "
            "VALUES ($1, 'LOCK_B', 'Lock Account B', 'active', 'KRW', $2)",
            client_id, now,
        )
        await conn.execute(
            "INSERT INTO trading.broker_accounts (broker_account_id, broker_name, account_ref, "
            "environment, credential_ref, status, created_at) "
            "VALUES ($1, 'TEST', 'LOCK_B_REF', 'paper', 'test-cred', 'active', $2)",
            broker_acct_id, now,
        )
        await conn.execute(
            "INSERT INTO trading.accounts (account_id, client_id, broker_account_id, environment, "
            "account_alias, account_masked, status, created_at) "
            "VALUES ($1, $2, $3, 'paper', 'LOCK-ACCT-B', '****0002', 'active', $4)",
            account_id_b, client_id, broker_acct_id, now,
        )

        # Get a strategy_id
        row = await conn.fetchrow(
            "SELECT strategy_id FROM trading.strategies LIMIT 1"
        )
        assert row is not None
        strategy_id: UUID = row["strategy_id"]

        # Insert reconciliation runs for both accounts
        run_id_a = uuid4()
        run_id_b = uuid4()
        await conn.execute(
            "INSERT INTO trading.reconciliation_runs (reconciliation_run_id, account_id, "
            "trigger_type, status, started_at) VALUES ($1, $2, 'manual', 'started', $3)",
            run_id_a, account_id_a, now,
        )
        await conn.execute(
            "INSERT INTO trading.reconciliation_runs (reconciliation_run_id, account_id, "
            "trigger_type, status, started_at) VALUES ($1, $2, 'manual', 'started', $3)",
            run_id_b, account_id_b, now,
        )

        # Insert locks for both accounts
        lock_id_a = uuid4()
        lock_id_b = uuid4()
        far_future = now.replace(year=9999)
        await conn.execute(
            "INSERT INTO trading.order_blocking_locks (lock_id, account_id, strategy_id, symbol, side, "
            "reason, locked_by_run_id, locked_at, expires_at) "
            "VALUES ($1, $2, $3, 'AAPL', 'buy', 'reconciliation', $4, $5, $6)",
            lock_id_a, account_id_a, strategy_id, run_id_a, now, far_future,
        )
        await conn.execute(
            "INSERT INTO trading.order_blocking_locks (lock_id, account_id, strategy_id, symbol, side, "
            "reason, locked_by_run_id, locked_at, expires_at) "
            "VALUES ($1, $2, $3, 'GOOGL', 'sell', 'reconciliation', $4, $5, $6)",
            lock_id_b, account_id_b, strategy_id, run_id_b, now, far_future,
        )

        # Query for account A only
        results_a = await repos.reconciliations.list_locks(account_id_a)
        assert len(results_a) == 1
        assert results_a[0].lock_id == lock_id_a
        assert results_a[0].account_id == account_id_a

        # Query for account B only
        results_b = await repos.reconciliations.list_locks(account_id_b)
        assert len(results_b) == 1
        assert results_b[0].lock_id == lock_id_b
        assert results_b[0].account_id == account_id_b
