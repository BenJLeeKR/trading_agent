from __future__ import annotations

import asyncpg

from agent_trading.repositories.exceptions import is_postgres_error, is_unique_violation


def test_is_postgres_error_detects_asyncpg_postgres_error() -> None:
    exc = asyncpg.PostgresError("database failure")

    assert is_postgres_error(exc) is True


def test_is_postgres_error_rejects_other_exceptions() -> None:
    exc = RuntimeError("different failure")

    assert is_postgres_error(exc) is False


def test_is_unique_violation_detects_asyncpg_unique_violation() -> None:
    exc = asyncpg.exceptions.UniqueViolationError("duplicate")

    assert is_unique_violation(exc) is True


def test_is_unique_violation_rejects_other_exceptions() -> None:
    exc = RuntimeError("different failure")

    assert is_unique_violation(exc) is False
