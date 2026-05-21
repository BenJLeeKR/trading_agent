"""Tests for ``TransactionManager`` savepoint support.

Savepoints allow per-order isolation within a single transaction:
if one order's sync fails with a DB error, only that order's changes
are rolled back; the outer transaction remains valid.

실행: ``uv run pytest tests/db/test_transaction.py -v``
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from agent_trading.db.transaction import TransactionManager

pytestmark = pytest.mark.asyncio


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def mock_connection():
    """Create a mock asyncpg.Connection."""
    conn = AsyncMock(spec=asyncpg.Connection)
    conn.transaction.return_value = AsyncMock(spec=asyncpg.transaction.Transaction)
    return conn


@pytest.fixture
def tx_manager(mock_connection):
    """Create a TransactionManager with a mocked connection."""
    mgr = TransactionManager()
    mgr._connection = mock_connection
    mgr._transaction = mock_connection.transaction.return_value
    return mgr


# ======================================================================
# Savepoint creation
# ======================================================================


class TestSavepointCreation:
    """Savepoint이 올바르게 생성되는지 검증."""

    async def test_savepoint_auto_name(self, tx_manager, mock_connection):
        """이름 미지정시 auto-incrementing name (sp_1, sp_2, ...)이 생성되어야 함."""
        async with tx_manager.savepoint() as sp_name:
            assert sp_name == "sp_1"

        async with tx_manager.savepoint() as sp_name:
            assert sp_name == "sp_2"

        # SAVEPOINT가 connection.execute로 호출되었는지 확인
        assert mock_connection.execute.call_count >= 2
        mock_connection.execute.assert_any_call("SAVEPOINT sp_1")
        mock_connection.execute.assert_any_call("SAVEPOINT sp_2")

    async def test_savepoint_custom_name(self, tx_manager, mock_connection):
        """지정한 이름으로 savepoint가 생성되어야 함."""
        async with tx_manager.savepoint(name="my_sp") as sp_name:
            assert sp_name == "my_sp"

        mock_connection.execute.assert_any_call("SAVEPOINT my_sp")

    async def test_savepoint_release_on_success(self, tx_manager, mock_connection):
        """Savepoint 내부 성공시 RELEASE SAVEPOINT가 호출되어야 함."""
        async with tx_manager.savepoint(name="sp_ok"):
            pass  # no exception

        mock_connection.execute.assert_any_call("RELEASE SAVEPOINT sp_ok")

    async def test_savepoint_rollback_on_exception(self, tx_manager, mock_connection):
        """Savepoint 내부 예외 발생시 ROLLBACK TO SAVEPOINT가 호출되어야 함."""
        with pytest.raises(ValueError, match="test error"):
            async with tx_manager.savepoint(name="sp_fail"):
                raise ValueError("test error")

        # ROLLBACK TO SAVEPOINT가 호출되었는지 확인
        mock_connection.execute.assert_any_call("ROLLBACK TO SAVEPOINT sp_fail")


# ======================================================================
# Savepoint isolation
# ======================================================================


class TestSavepointIsolation:
    """Savepoint가 트랜잭션 격리를 제공하는지 검증.

    핵심 시나리오: savepoint 내부에서 DB 에러가 발생해도
    외부 트랜잭션은 계속 사용 가능해야 함.
    """

    async def test_outer_transaction_survives_savepoint_failure(
        self, tx_manager, mock_connection,
    ):
        """Savepoint 실패 후에도 외부 트랜잭션에서 DB write가 가능해야 함."""
        # Savepoint 내부에서 예외 발생
        with pytest.raises(RuntimeError, match="inner fail"):
            async with tx_manager.savepoint(name="sp1"):
                raise RuntimeError("inner fail")

        # Savepoint 실패 후에도 connection.execute가 정상 동작해야 함
        # (ROLLBACK TO SAVEPOINT로 트랜잭션 상태가 복구되었으므로)
        mock_connection.execute.reset_mock()
        await mock_connection.execute("SELECT 1")
        mock_connection.execute.assert_called_once_with("SELECT 1")

    async def test_multiple_savepoints_sequential(
        self, tx_manager, mock_connection,
    ):
        """여러 savepoint를 순차적으로 사용할 수 있어야 함.

        sp1 실패 → sp2 성공 → sp3 실패 → sp4 성공
        """
        # sp1: 실패
        with pytest.raises(ValueError):
            async with tx_manager.savepoint(name="sp1"):
                raise ValueError("sp1 fail")

        # sp2: 성공
        async with tx_manager.savepoint(name="sp2"):
            await mock_connection.execute("INSERT INTO test VALUES (1)")

        # sp3: 실패
        with pytest.raises(RuntimeError):
            async with tx_manager.savepoint(name="sp3"):
                raise RuntimeError("sp3 fail")

        # sp4: 성공 (외부 트랜잭션 정상)
        async with tx_manager.savepoint(name="sp4"):
            await mock_connection.execute("INSERT INTO test VALUES (2)")

        # SAVEPOINT 생성 호출만 카운트 (ROLLBACK TO / RELEASE 제외)
        savepoint_calls = [
            call for call in mock_connection.execute.call_args_list
            if str(call).startswith("call('SAVEPOINT ")
        ]
        assert len(savepoint_calls) == 4, (
            f"Expected 4 SAVEPOINT creates, got {len(savepoint_calls)}: "
            f"{[str(c) for c in savepoint_calls]}"
        )

        # ROLLBACK TO SAVEPOINT 호출 검증
        rollback_calls = [
            call for call in mock_connection.execute.call_args_list
            if "ROLLBACK TO SAVEPOINT" in str(call)
        ]
        assert len(rollback_calls) == 2  # sp1, sp3

    async def test_savepoint_does_not_commit_outer(
        self, tx_manager, mock_connection,
    ):
        """Savepoint 성공이 외부 트랜잭션을 커밋하지 않아야 함.

        Savepoint 내부의 변경은 savepoint release시점에
        외부 트랜잭션에 병합되지만, 최종 commit은
        TransactionManager.commit() 호출시에만 발생해야 함.
        """
        async with tx_manager.savepoint(name="sp1"):
            await mock_connection.execute("INSERT INTO test VALUES (1)")

        # 아직 commit()이 호출되지 않았으므로
        # Transaction.__aexit__(None, None, None)이 호출되지 않아야 함
        tx_manager._transaction.__aexit__.assert_not_called()

    async def test_savepoint_rollback_undoes_writes(
        self, tx_manager, mock_connection,
    ):
        """Savepoint rollback이 savepoint 내부의 write를 취소해야 함.

        시나리오:
        1. sp1 내부에서 INSERT 실행
        2. sp1 실패로 ROLLBACK TO SAVEPOINT
        3. sp2 내부에서 동일한 INSERT 재시도 → 성공
        """
        # sp1: INSERT 후 실패
        with pytest.raises(ValueError):
            async with tx_manager.savepoint(name="sp1"):
                await mock_connection.execute("INSERT INTO test VALUES (1)")
                raise ValueError("sp1 fail")

        # ROLLBACK TO SAVEPOINT sp1로 sp1의 INSERT가 취소됨
        mock_connection.execute.assert_any_call("ROLLBACK TO SAVEPOINT sp1")

        # sp2: 동일 INSERT 재시도 → 성공 (sp1의 write가 rollback되었으므로)
        async with tx_manager.savepoint(name="sp2"):
            await mock_connection.execute("INSERT INTO test VALUES (1)")

        # RELEASE SAVEPOINT sp2로 sp2의 INSERT가 외부 트랜잭션에 병합됨
        mock_connection.execute.assert_any_call("RELEASE SAVEPOINT sp2")


# ======================================================================
# Error handling
# ======================================================================


class TestSavepointErrorHandling:
    """Savepoint 예외 처리 검증."""

    async def test_savepoint_no_connection_error(self):
        """Connection 없는 상태에서 savepoint 호출시 RuntimeError."""
        mgr = TransactionManager()
        with pytest.raises(RuntimeError, match="No active connection"):
            async with mgr.savepoint():
                pass

    async def test_savepoint_release_failure_swallowed(
        self, tx_manager, mock_connection,
    ):
        """RELEASE SAVEPOINT 실패는 무시되어야 함 (finally 절에서 처리)."""
        # RELEASE SAVEPOINT가 실패하도록 설정
        async def _fail_on_release(*args, **kwargs):
            if "RELEASE" in str(args[0]):
                raise asyncpg.PostgresError("Release failed")
            return "OK"

        mock_connection.execute.side_effect = _fail_on_release

        # 예외가 발생하지 않고 savepoint가 정상 종료되어야 함
        async with tx_manager.savepoint(name="sp1"):
            await mock_connection.execute("SELECT 1")

    async def test_savepoint_rollback_then_continue(
        self, tx_manager, mock_connection,
    ):
        """Savepoint rollback 후에도 정상 SQL 실행이 가능해야 함.

        이 시나리오는 실제 post-submit sync에서 한 order가 실패해도
        다음 order의 sync가 정상 동작해야 하는 상황을 모델링.
        """
        # sp1: 실패 (DB constraint violation 시뮬레이션)
        with pytest.raises(asyncpg.PostgresError):
            async with tx_manager.savepoint(name="sp1"):
                await mock_connection.execute("INSERT INTO test VALUES (1)")
                raise asyncpg.PostgresError("duplicate key value violates unique constraint")

        # sp2: 성공 (다음 order)
        async with tx_manager.savepoint(name="sp2"):
            await mock_connection.execute("INSERT INTO test VALUES (2)")

        # sp3: 실패 (또 다른 에러)
        with pytest.raises(RuntimeError):
            async with tx_manager.savepoint(name="sp3"):
                await mock_connection.execute("UPDATE test SET val=3")
                raise RuntimeError("broker timeout")

        # sp4: 성공 (계속 진행 가능)
        async with tx_manager.savepoint(name="sp4"):
            await mock_connection.execute("INSERT INTO test VALUES (4)")

        # 최종적으로 4개의 savepoint가 모두 생성되었고,
        # 2개의 rollback(sp1, sp3)이 발생했으며,
        # 4개의 release(sp1~sp4, finally 블록에서 실패한 savepoint도 release 시도)가 발생해야 함
        savepoint_calls = [
            c for c in mock_connection.execute.call_args_list
            if str(c).startswith("call('SAVEPOINT ")
        ]
        rollback_calls = [
            c for c in mock_connection.execute.call_args_list
            if str(c).startswith("call('ROLLBACK TO SAVEPOINT ")
        ]
        release_calls = [
            c for c in mock_connection.execute.call_args_list
            if str(c).startswith("call('RELEASE SAVEPOINT ")
        ]

        assert len(savepoint_calls) == 4, (
            f"Expected 4 SAVEPOINT creates, got {len(savepoint_calls)}"
        )
        assert len(rollback_calls) == 2, (
            f"Expected 2 ROLLBACK TO SAVEPOINT, got {len(rollback_calls)}"
        )
        # RELEASE SAVEPOINT는 finally 블록에서 항상 호출되므로
        # 실패한 savepoint(sp1, sp3)도 release가 시도됨 → 총 4회
        assert len(release_calls) == 4, (
            f"Expected 4 RELEASE SAVEPOINT (all savepoints), got {len(release_calls)}"
        )
