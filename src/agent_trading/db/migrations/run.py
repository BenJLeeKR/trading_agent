"""Migration runner for plain SQL migration files.

All SQL files in ``db/migrations/`` are executed in lexicographic order.
Each file runs in its own connection so that DDL inside each file is atomic.

Usage (CLI)::

    python -m agent_trading.db.migrations.run

Usage (Python)::

    from agent_trading.db.migrations.run import ensure_schema
    await ensure_schema()
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import asyncpg

from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool

logger = logging.getLogger(__name__)

# Resolve the migrations directory relative to the project root.
# Project root is two levels up from this file:
#   src/agent_trading/db/migrations/run.py  →  project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
MIGRATIONS_DIR = _PROJECT_ROOT / "db" / "migrations"


async def run_migration(
    sql_path: str | Path,
    config: DatabaseConfig | None = None,
) -> None:
    """Execute a single SQL migration file against the database.

    The file is read and executed as a single script.  All statements
    within the file share the same connection (transaction boundaries
    are controlled by the SQL itself via ``BEGIN`` / ``COMMIT``).

    Args:
        sql_path: Path to the ``.sql`` migration file.
        config: Optional database configuration.  If omitted, defaults
            are read from environment variables.

    Raises:
        FileNotFoundError: If the migration file does not exist.
    """
    path = Path(sql_path)
    if not path.exists():
        raise FileNotFoundError(f"Migration file not found: {path}")

    sql = path.read_text(encoding="utf-8")
    if not sql.strip():
        logger.warning("Migration file is empty: %s", path)
        return

    pool = await create_pool(config)
    async with pool.acquire() as conn:
        logger.info("Running migration: %s", path.name)
        try:
            await conn.execute(sql)
        except asyncpg.exceptions.DuplicateTableError:
            # Table already exists — migration was already applied.
            # This is safe to ignore in test environments where the
            # schema is shared across multiple test sessions.
            logger.info("Migration already applied (table exists): %s", path.name)
        except asyncpg.exceptions.DuplicateObjectError:
            # Index, sequence, or other object already exists.
            # Handles CREATE INDEX IF NOT EXISTS fallback, etc.
            logger.info("Migration already applied (object exists): %s", path.name)
        except asyncpg.exceptions.DuplicateColumnError:
            # Column already exists — ALTER TABLE ADD COLUMN was already applied.
            logger.info("Migration already applied (column exists): %s", path.name)
        except Exception as exc:
            logger.error(
                "Migration failed: %s — %s: %s",
                path.name,
                type(exc).__name__,
                exc,
            )
            raise
        else:
            logger.info("Migration completed: %s", path.name)


async def run_all_migrations(
    migrations_dir: str | Path = MIGRATIONS_DIR,
    config: DatabaseConfig | None = None,
) -> None:
    """Run all ``.sql`` migration files in a directory, ordered by filename.

    Files are executed in lexicographic order (e.g. ``0001_*.sql``,
    ``0002_*.sql``, …).  Each file is executed in its own connection
    so that the DDL inside each file is atomic.

    Args:
        migrations_dir: Directory containing ``.sql`` migration files.
        config: Optional database configuration.

    Raises:
        NotADirectoryError: If ``migrations_dir`` is not a directory.
    """
    directory = Path(migrations_dir)
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    sql_files = sorted(directory.glob("*.sql"))
    if not sql_files:
        logger.warning("No SQL migration files found in %s", directory)
        return

    for sql_file in sql_files:
        await run_migration(sql_file, config=config)


async def ensure_schema(config: DatabaseConfig | None = None) -> None:
    """Convenience: create pool, run all migrations, close pool.

    This is the main entry point for initialising the database schema
    from a script or CLI.
    """
    cfg = config or DatabaseConfig()
    await create_pool(cfg)
    try:
        await run_all_migrations(config=cfg)
    finally:
        await close_pool()


def _load_dotenv() -> None:
    """Load ``.env`` file from the project root if ``python-dotenv`` is available."""
    try:
        from dotenv import load_dotenv

        dotenv_path = _PROJECT_ROOT / ".env"
        if dotenv_path.exists():
            load_dotenv(dotenv_path)
            logger.info("Loaded environment from %s", dotenv_path)
    except ImportError:
        pass


def main() -> None:
    """CLI entry point for running migrations.

    Loads ``.env`` if available, then runs ``ensure_schema()``.
    Exits with code 1 on failure.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    _load_dotenv()

    import asyncio

    try:
        asyncio.run(ensure_schema())
    except Exception as exc:
        logger.error("Migration failed: %s: %s", type(exc).__name__, exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
