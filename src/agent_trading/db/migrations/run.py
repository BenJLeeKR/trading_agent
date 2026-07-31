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

import asyncio
import logging
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

# ── 마이그레이션 이력(ledger) — 근본 원인 재발 방지 ──────────────────────────
#
# 과거에는 이력 테이블이 없어 매 컨테이너 부팅마다 db/migrations/*.sql
# 전체를 재실행했다. ALTER TABLE ADD COLUMN(0021/0022)과 그 컬럼을 DROP하는
# 마이그레이션(0026)이 짝을 이루는 경우, 재부팅마다 "추가 → 삭제"가 반복돼
# 컬럼 수는 순증가 없이 0으로 돌아오지만 Postgres의 attnum(컬럼 슬롯)은 DROP
# 후에도 재사용되지 않고 계속 증가해 결국 하드 리밋(1600)에 도달했다
# (trading.trade_decisions에서 실제 발생 확인). 이 테이블로 파일별 적용
# 여부를 추적해 같은 파일이 두 번 다시 실행되지 않게 한다.
_LEDGER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trading.schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


async def _ensure_migration_ledger(conn: asyncpg.Connection) -> None:
    """``trading.schema_migrations`` 이력 테이블이 없으면 만든다."""
    await conn.execute("CREATE SCHEMA IF NOT EXISTS trading;")
    await conn.execute(_LEDGER_TABLE_SQL)


async def _bootstrap_ledger_if_needed(
    conn: asyncpg.Connection,
    sql_files: list[Path],
) -> None:
    """이력이 비어 있고 스키마가 이미 존재하면, 현재 파일 전체를
    '이미 적용됨'으로 백필한다.

    - **기존 운영/개발 DB**(``trading.clients``가 이미 존재)라면 이력 도입
      이전에 이미 전체 마이그레이션이 누적 적용된 상태이므로, 재실행 없이
      전부 적용됨으로 표시한다. 이게 없으면 이 배포에서 딱 한 번 더 전체
      replay가 일어나 0021/0022가 attnum 고갈로 실패하고
      (`TooManyColumnsError`가 이제는 raise되므로) 부팅이 깨진다.
    - **완전히 새 DB**(테스트 등, ``trading.clients`` 없음)라면 백필하지
      않는다 — 파일들이 정상적으로 한 번씩 실행되며 각자 이력에 기록된다.
    """
    existing = await conn.fetchval(
        "SELECT count(*) FROM trading.schema_migrations"
    )
    if existing:
        return
    schema_exists = await conn.fetchval(
        "SELECT to_regclass('trading.clients') IS NOT NULL"
    )
    if not schema_exists:
        return
    filenames = [f.name for f in sql_files]
    if not filenames:
        return
    await conn.executemany(
        "INSERT INTO trading.schema_migrations (filename) "
        "VALUES ($1) ON CONFLICT (filename) DO NOTHING",
        [(name,) for name in filenames],
    )
    logger.info(
        "Migration ledger bootstrapped for existing schema: %d file(s) "
        "marked as already applied",
        len(filenames),
    )


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
        except asyncpg.exceptions.TooManyColumnsError:
            # "tables can have at most 1600 columns" — 컬럼이 이미 있어서가
            # 아니라 attnum(컬럼 슬롯) 자체가 고갈된 상태다. 이력 테이블 없이
            # 매 부팅마다 전체 마이그레이션을 재생하는 이 러너의 구조상,
            # ADD COLUMN 마이그레이션과 DROP COLUMN 마이그레이션이 짝을 이루면
            # 재부팅마다 attnum을 영구 소모해 결국 1600 한도에 도달할 수 있다
            # (SPPV-2.152 후속 조사에서 trading.trade_decisions가 실제로
            # 이 상태에 도달함을 확인). 다른 Duplicate*Error와 달리 "이미
            # 적용됨"으로 간주하면 안 된다 — 컬럼이 정말로 추가되지 않은
            # 채로 앱 코드가 존재를 가정하게 되는 실패 은폐로 이어진다.
            logger.error(
                "Migration failed (column slot exhausted, NOT already applied): "
                "%s — 대상 테이블의 attnum이 1600 한도에 도달했다. 테이블 재생성"
                "(attnum 리셋)이 필요하다.",
                path.name,
            )
            raise
        except (asyncio.TimeoutError, asyncpg.exceptions.PostgresError) as exc:
            # TimeoutError (asyncio) 또는 PostgresError (asyncpg) 발생 시
            # 스키마가 이미 존재하는 상태에서 DDL이 타임아웃되는 경우가 있음.
            # 이 경우 마이그레이션이 이미 적용된 것으로 간주하고 진행.
            logger.warning(
                "Migration may already be applied (timeout/error): %s — %s: %s",
                path.name,
                type(exc).__name__,
                exc,
            )
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

    pool = await create_pool(config)
    async with pool.acquire() as conn:
        await _ensure_migration_ledger(conn)
        await _bootstrap_ledger_if_needed(conn, sql_files)
        applied = {
            row["filename"]
            for row in await conn.fetch(
                "SELECT filename FROM trading.schema_migrations"
            )
        }

    for sql_file in sql_files:
        if sql_file.name in applied:
            logger.info("Migration already recorded in ledger, skipping: %s", sql_file.name)
            continue
        await run_migration(sql_file, config=config)
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO trading.schema_migrations (filename) "
                "VALUES ($1) ON CONFLICT (filename) DO NOTHING",
                sql_file.name,
            )


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
