from __future__ import annotations

import asyncpg


def is_postgres_error(exc: BaseException) -> bool:
    """저장소 계층에서 DB driver의 PostgreSQL 예외를 판정한다."""
    return isinstance(exc, asyncpg.PostgresError)


def is_unique_violation(exc: BaseException) -> bool:
    """저장소 계층에서 DB driver의 unique constraint 예외를 판정한다."""
    return isinstance(exc, asyncpg.exceptions.UniqueViolationError)
