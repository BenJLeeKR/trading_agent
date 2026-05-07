from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

_pool: asyncpg.Pool | None = None
_pool_initialized: bool = False


class DatabaseConfig:
    """PostgreSQL connection configuration.

    Environment variable resolution order (first non-None wins):
      1. Explicit constructor argument
      2. ``DATABASE_*`` env var
      3. ``DB_*`` env var (backward-compatible fallback)
      4. Hard-coded default

    In production, set ``DATABASE_*`` env vars explicitly.
    """

    def __init__(
        self,
        dsn: str | None = None,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        min_size: int = 2,
        max_size: int = 10,
        command_timeout: int = 30,
    ) -> None:
        self.dsn = dsn or os.getenv("DATABASE_DSN")
        self.host = (
            host
            or os.getenv("DATABASE_HOST")
            or os.getenv("DB_HOST")
            or "localhost"
        )
        self.port = port or int(
            os.getenv("DATABASE_PORT") or os.getenv("DB_PORT") or "5432"
        )
        self.user = (
            user
            or os.getenv("DATABASE_USER")
            or os.getenv("DB_USER")
            or "trading"
        )
        self.password = (
            password
            or os.getenv("DATABASE_PASSWORD")
            or os.getenv("DB_PASSWORD")
            or "trading"
        )
        self.database = (
            database
            or os.getenv("DATABASE_NAME")
            or os.getenv("DB_NAME")
            or "trading"
        )
        self.schema = schema or os.getenv("DATABASE_SCHEMA", "trading")
        self.min_size = min_size
        self.max_size = max_size
        self.command_timeout = command_timeout

    @property
    def resolved_dsn(self) -> str:
        if self.dsn:
            return self.dsn
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


async def create_pool(config: DatabaseConfig | None = None) -> asyncpg.Pool:
    """Create and return a connection pool (singleton).

    If a pool is already active it is returned directly.
    """
    global _pool, _pool_initialized

    if _pool_initialized and _pool is not None:
        return _pool

    cfg = config or DatabaseConfig()

    pool: asyncpg.Pool = await asyncpg.create_pool(
        dsn=cfg.resolved_dsn,
        min_size=cfg.min_size,
        max_size=cfg.max_size,
        command_timeout=cfg.command_timeout,
    )

    _pool = pool
    _pool_initialized = True
    return _pool


async def get_pool() -> asyncpg.Pool:
    """Return the active pool.

    Raises:
        RuntimeError: If the pool has not been initialised via ``create_pool()``.
    """
    if not _pool_initialized or _pool is None:
        raise RuntimeError(
            "Database pool is not initialised. Call create_pool() first."
        )
    return _pool


async def close_pool() -> None:
    """Close the active connection pool."""
    global _pool, _pool_initialized

    if _pool_initialized and _pool is not None:
        await _pool.close()

    _pool = None
    _pool_initialized = False
    _pool_initialized = False


async def health_check(config: DatabaseConfig | None = None) -> bool:
    """Check whether the database is reachable.

    Creates a temporary pool (or reuses an existing one), runs ``SELECT 1``,
    and returns ``True`` on success.

    This function is safe to call before or after ``create_pool()``.
    """
    pool: asyncpg.Pool | None = None
    try:
        if _pool_initialized and _pool is not None:
            pool = _pool
        else:
            pool = await asyncpg.create_pool(
                dsn=(config or DatabaseConfig()).resolved_dsn,
                min_size=1,
                max_size=1,
                command_timeout=5,
            )

        async with pool.acquire() as conn:
            row = await conn.fetchval("SELECT 1")
            return row == 1
    except Exception:
        return False
    finally:
        if pool is not None and pool is not _pool:
            await pool.close()


@asynccontextmanager
async def connection() -> AsyncIterator[asyncpg.Connection]:
    """Acquire a single connection from the pool.

    Usage::

        async with connection() as conn:
            row = await conn.fetchrow("SELECT 1")
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
