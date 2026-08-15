"""Unit tests for the migration ledger / exception handling.

SPPV-2.152 후속(attnum 1600 한도 도달) 대응과 `0062` stale-record 사고
후속 대응을 실제 Postgres 없이 fake connection/pool로 검증한다:

1. ``TooManyColumnsError``는 다른 ``Duplicate*Error``와 달리 "이미 적용됨"으로
   간주되지 않고 그대로 raise된다(실패 은폐 방지).
2. 참조 무결성 위반(``InvalidForeignKeyError``) 등 진짜 DDL 실패는 더 이상
   "이미 적용됐을 수 있음"으로 삼켜지지 않고 그대로 raise된다 — `0062`가
   `config_versions`에 PK가 없어 FK 생성에 실패했는데도 원장에는 성공으로
   남았던 stale-record 사고의 재발 방지.
3. 그런 실패가 나면 ``run_all_migrations``는 해당 파일을 원장(``trading.
   schema_migrations``)에 기록하지 않는다 — "실체 없이 원장만 성공으로
   남는" 상태를 만들지 않는다.
4. 이력이 비어 있을 때 기존 스키마(``trading.clients`` 존재)면 현재 파일
   전체를 백필하고, 완전히 새 DB면 백필하지 않는다(이번 수정과 무관한
   기존 계약, 회귀 방지용으로 유지).
5. ``run_all_migrations``는 이력에 이미 기록된 파일을 재실행하지 않는다.

실제 DB 연결(``asyncpg.create_pool``)은 fake로 대체해 하네스의
"신규 KIS 호출 금지 / 외부 API 호출 금지" 원칙과 무관하게 완전히 오프라인으로
검증한다.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from agent_trading.db.migrations import run as migrations_run


class _FakeConn:
    """execute/fetchval/fetch/executemany 호출을 기록하고, 설정된 응답/예외를
    돌려주는 가짜 asyncpg 커넥션."""

    def __init__(
        self,
        *,
        execute_raises: dict[str, Exception] | None = None,
        fetchval_returns: dict[str, Any] | None = None,
        fetch_returns: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.execute_raises = execute_raises or {}
        self.fetchval_returns = fetchval_returns or {}
        self.fetch_returns = fetch_returns or {}
        self.executed: list[str] = []
        self.executemany_calls: list[tuple[str, list[tuple[Any, ...]]]] = []

    async def execute(self, sql: str, *args: Any) -> None:
        self.executed.append(sql)
        for marker, exc in self.execute_raises.items():
            if marker in sql:
                raise exc

    async def fetchval(self, query: str, *args: Any) -> Any:
        for marker, value in self.fetchval_returns.items():
            if marker in query:
                return value
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        for marker, rows in self.fetch_returns.items():
            if marker in query:
                return rows
        return []

    async def executemany(self, query: str, args_list: list[tuple[Any, ...]]) -> None:
        self.executemany_calls.append((query, list(args_list)))


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


def _patch_pool(monkeypatch: pytest.MonkeyPatch, conn: _FakeConn) -> None:
    async def _fake_create_pool(config: Any = None) -> _FakePool:
        return _FakePool(conn)

    monkeypatch.setattr(migrations_run, "create_pool", _fake_create_pool)


class TestTooManyColumnsErrorNotSwallowed:
    """attnum 고갈은 '이미 적용됨'이 아니라 실제 실패로 취급해야 한다."""

    @pytest.mark.asyncio
    async def test_too_many_columns_error_reraises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        sql_file = tmp_path / "0099_add_column.sql"
        sql_file.write_text("ALTER TABLE trading.trade_decisions ADD COLUMN x INT;")

        conn = _FakeConn(
            execute_raises={
                "ADD COLUMN": asyncpg.exceptions.TooManyColumnsError(
                    "tables can have at most 1600 columns"
                )
            }
        )
        _patch_pool(monkeypatch, conn)

        with pytest.raises(asyncpg.exceptions.TooManyColumnsError):
            await migrations_run.run_migration(sql_file)

    @pytest.mark.asyncio
    async def test_duplicate_column_error_still_swallowed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """회귀: 기존 Duplicate*Error 흡수 동작은 그대로 유지돼야 한다."""
        sql_file = tmp_path / "0099_add_column.sql"
        sql_file.write_text("ALTER TABLE trading.trade_decisions ADD COLUMN x INT;")

        conn = _FakeConn(
            execute_raises={
                "ADD COLUMN": asyncpg.exceptions.DuplicateColumnError("column exists")
            }
        )
        _patch_pool(monkeypatch, conn)

        await migrations_run.run_migration(sql_file)  # raise하지 않아야 한다


class TestStaleRecordRegressionNotSwallowed:
    """0062 사고 재발 방지 — 진짜 DDL 실패는 '이미 적용됨'으로 삼켜지면
    안 되고, 원장에도 기록되면 안 된다."""

    @pytest.mark.asyncio
    async def test_invalid_foreign_key_error_reraises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """0062 실사고 재현: 참조 대상에 PK/UNIQUE가 없어 FK 생성이
        실패하는 경우, 예전 코드는 이걸 '이미 적용됐을 수 있음'으로 보고
        삼켰다. 지금은 그대로 raise돼야 한다."""
        sql_file = tmp_path / "0062_add_historical_buy_fee_overlays.sql"
        sql_file.write_text(
            "ALTER TABLE trading.historical_buy_fee_overlays "
            "ADD CONSTRAINT fk FOREIGN KEY (basis_config_version_id) "
            "REFERENCES trading.config_versions (config_version_id);"
        )

        conn = _FakeConn(
            execute_raises={
                "FOREIGN KEY": asyncpg.exceptions.InvalidForeignKeyError(
                    "there is no unique constraint matching given keys "
                    'for referenced table "config_versions"'
                )
            }
        )
        _patch_pool(monkeypatch, conn)

        with pytest.raises(asyncpg.exceptions.InvalidForeignKeyError):
            await migrations_run.run_migration(sql_file)

    @pytest.mark.asyncio
    async def test_unique_violation_error_reraises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        sql_file = tmp_path / "0099_add_constraint.sql"
        sql_file.write_text(
            "ALTER TABLE trading.clients ADD CONSTRAINT uq UNIQUE (client_id);"
        )

        conn = _FakeConn(
            execute_raises={
                "ADD CONSTRAINT": asyncpg.exceptions.UniqueViolationError(
                    "duplicate key value violates unique constraint"
                )
            }
        )
        _patch_pool(monkeypatch, conn)

        with pytest.raises(asyncpg.exceptions.UniqueViolationError):
            await migrations_run.run_migration(sql_file)

    @pytest.mark.asyncio
    async def test_undefined_table_error_reraises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        sql_file = tmp_path / "0099_broken_reference.sql"
        sql_file.write_text("ALTER TABLE trading.does_not_exist ADD COLUMN x INT;")

        conn = _FakeConn(
            execute_raises={
                "ALTER TABLE": asyncpg.exceptions.UndefinedTableError(
                    "relation does not exist"
                )
            }
        )
        _patch_pool(monkeypatch, conn)

        with pytest.raises(asyncpg.exceptions.UndefinedTableError):
            await migrations_run.run_migration(sql_file)

    @pytest.mark.asyncio
    async def test_generic_postgres_error_reraises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """개별 서브클래스로 분류되지 않는 일반 PostgresError도 더 이상
        삼켜지면 안 된다 — 예전의 광범위 catch가 커버하던 케이스."""
        sql_file = tmp_path / "0099_generic_failure.sql"
        sql_file.write_text("CREATE TABLE trading.broken ( ; )")

        conn = _FakeConn(
            execute_raises={"CREATE TABLE": asyncpg.exceptions.PostgresError("boom")}
        )
        _patch_pool(monkeypatch, conn)

        with pytest.raises(asyncpg.exceptions.PostgresError):
            await migrations_run.run_migration(sql_file)

    @pytest.mark.asyncio
    async def test_timeout_error_reraises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """timeout도 더 이상 '이미 적용됐을 수 있음'으로 추정하지 않는다 —
        모르면 실패로 남기는 것이 가장 보수적인 방향이다."""
        sql_file = tmp_path / "0099_slow_migration.sql"
        sql_file.write_text("CREATE INDEX CONCURRENTLY idx ON trading.fill_events (fill_price);")

        conn = _FakeConn(
            execute_raises={"CREATE INDEX": TimeoutError("statement timeout")}
        )
        _patch_pool(monkeypatch, conn)

        with pytest.raises(TimeoutError):
            await migrations_run.run_migration(sql_file)

    @pytest.mark.asyncio
    async def test_failed_migration_never_recorded_in_ledger(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """0062 사고의 핵심 증상 재현: FK 생성 실패가 원장에는 절대 성공
        으로 남지 않아야 한다 — '실체 없이 원장만 성공'인 stale record를
        다시 만들지 않는다는 것을 run_all_migrations 레벨에서 확인한다."""
        (tmp_path / "0062_add_historical_buy_fee_overlays.sql").write_text(
            "ALTER TABLE trading.historical_buy_fee_overlays "
            "ADD CONSTRAINT fk FOREIGN KEY (basis_config_version_id) "
            "REFERENCES trading.config_versions (config_version_id);"
        )

        conn = _FakeConn(
            fetchval_returns={"count(*) FROM trading.schema_migrations": 1},
            fetch_returns={"SELECT filename FROM trading.schema_migrations": []},
            execute_raises={
                "FOREIGN KEY": asyncpg.exceptions.InvalidForeignKeyError(
                    "there is no unique constraint matching given keys "
                    'for referenced table "config_versions"'
                )
            },
        )
        _patch_pool(monkeypatch, conn)

        with pytest.raises(asyncpg.exceptions.InvalidForeignKeyError):
            await migrations_run.run_all_migrations(migrations_dir=tmp_path)

        insert_calls = [
            sql for sql in conn.executed if "INSERT INTO trading.schema_migrations" in sql
        ]
        assert insert_calls == []  # 실패한 migration은 원장에 기록되지 않는다


class TestLedgerBootstrap:
    """이력이 비어 있을 때의 백필 분기."""

    @pytest.mark.asyncio
    async def test_backfills_when_schema_already_exists(self) -> None:
        conn = _FakeConn(
            fetchval_returns={
                "count(*) FROM trading.schema_migrations": 0,
                "to_regclass": True,
            }
        )
        files = [Path("0001_a.sql"), Path("0002_b.sql")]

        await migrations_run._bootstrap_ledger_if_needed(conn, files)

        assert len(conn.executemany_calls) == 1
        _, args = conn.executemany_calls[0]
        assert {a[0] for a in args} == {"0001_a.sql", "0002_b.sql"}

    @pytest.mark.asyncio
    async def test_backfill_excludes_files_past_cutoff(self) -> None:
        """SPPV-2.153 실사고 재현: 같은 배포에서 이력과 함께 추가된 새
        마이그레이션(컷오프보다 뒤)은 백필 대상이 아니라 실제로 실행돼야
        한다."""
        conn = _FakeConn(
            fetchval_returns={
                "count(*) FROM trading.schema_migrations": 0,
                "to_regclass": True,
            }
        )
        files = [
            Path("0001_a.sql"),
            Path(migrations_run._LEDGER_BOOTSTRAP_CUTOFF_FILENAME),
            Path("0051_new_migration_in_same_deploy.sql"),
        ]

        await migrations_run._bootstrap_ledger_if_needed(conn, files)

        assert len(conn.executemany_calls) == 1
        _, args = conn.executemany_calls[0]
        backfilled = {a[0] for a in args}
        assert "0051_new_migration_in_same_deploy.sql" not in backfilled
        assert migrations_run._LEDGER_BOOTSTRAP_CUTOFF_FILENAME in backfilled
        assert "0001_a.sql" in backfilled

    @pytest.mark.asyncio
    async def test_no_backfill_for_fresh_db(self) -> None:
        conn = _FakeConn(
            fetchval_returns={
                "count(*) FROM trading.schema_migrations": 0,
                "to_regclass": False,
            }
        )
        files = [Path("0001_a.sql")]

        await migrations_run._bootstrap_ledger_if_needed(conn, files)

        assert conn.executemany_calls == []

    @pytest.mark.asyncio
    async def test_no_backfill_when_ledger_already_populated(self) -> None:
        conn = _FakeConn(
            fetchval_returns={"count(*) FROM trading.schema_migrations": 5}
        )
        files = [Path("0001_a.sql")]

        await migrations_run._bootstrap_ledger_if_needed(conn, files)

        assert conn.executemany_calls == []


class TestRunAllMigrationsSkipsLedgeredFiles:
    @pytest.mark.asyncio
    async def test_skips_files_already_recorded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "0001_a.sql").write_text("SELECT 1;")
        (tmp_path / "0002_b.sql").write_text("SELECT 1;")

        conn = _FakeConn(
            fetchval_returns={"count(*) FROM trading.schema_migrations": 2},
            fetch_returns={
                "SELECT filename FROM trading.schema_migrations": [
                    {"filename": "0001_a.sql"},
                    {"filename": "0002_b.sql"},
                ]
            },
        )
        _patch_pool(monkeypatch, conn)

        called: list[Path] = []

        async def _fake_run_migration(path: Path, config: Any = None) -> None:
            called.append(path)

        monkeypatch.setattr(migrations_run, "run_migration", _fake_run_migration)

        await migrations_run.run_all_migrations(migrations_dir=tmp_path)

        assert called == []  # 이력에 있으므로 실제 실행은 한 번도 없어야 한다

    @pytest.mark.asyncio
    async def test_runs_new_file_not_in_ledger(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "0001_a.sql").write_text("SELECT 1;")

        conn = _FakeConn(
            fetchval_returns={"count(*) FROM trading.schema_migrations": 0},
            fetch_returns={"SELECT filename FROM trading.schema_migrations": []},
        )
        _patch_pool(monkeypatch, conn)

        called: list[Path] = []

        async def _fake_run_migration(path: Path, config: Any = None) -> None:
            called.append(path)

        monkeypatch.setattr(migrations_run, "run_migration", _fake_run_migration)

        await migrations_run.run_all_migrations(migrations_dir=tmp_path)

        assert called == [tmp_path / "0001_a.sql"]
        # 실행 후 이력에 기록됐는지 확인
        insert_calls = [
            sql for sql in conn.executed if "INSERT INTO trading.schema_migrations" in sql
        ]
        assert len(insert_calls) == 1
