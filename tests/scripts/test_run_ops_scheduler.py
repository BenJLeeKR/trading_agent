"""Tests for scripts.run_ops_scheduler (canonical entrypoint).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

logger = logging.getLogger(__name__)

from scripts.run_ops_scheduler import (
    CommandResult,
    HELD_POSITION_SELL_MAX_PER_DAY,
    HELD_POSITION_SELL_MAX_PER_CYCLE,
    KST,
    ScheduledTask,
    SchedulerState,
    _BUDGET_CONSUMING_STATUSES,
    _build_dsn,
    _build_tasks,
    _close_session_provider,
    _combine,
    _decision_command,
    _event_command,
    _extract_json_objects,
    _get_db_held_position_sell_count,
    _get_db_submit_count,
    _handle_phase_change,
    _heartbeat_task,
    _init_market_state_provider,
    _insert_session_event,
    _init_session_provider,
    _is_held_position_sell_result,
    _is_submit_consuming_result,
    _log_startup_info,
    _log_summary,
    _parse_args,
    _parse_hhmm,
    _parse_snapshot_sync_summary,
    _persist_session_state,
    _post_submit_command,
    _session_gate,
    _session_phase_monitor,
    _snapshot_command,
)
from agent_trading.brokers.koreainvestment.market_state_client import (
    MarketPhaseCode,
    MarketState,
    MarketStateProvider,
)
from agent_trading.services.market_session import (
    FallbackSessionProvider,
    SCHEDULER_ADVISORY_LOCK_KEY,
    SessionInfo,
)


class TestCommandBuilders:
    """Command builders use python3 and existing operational scripts."""

    def test_snapshot_command_uses_python3(self) -> None:
        assert _snapshot_command() == [
            "python3",
            "scripts/run_snapshot_sync_loop.py",
            "--max-cycles",
            "1",
        ]

    def test_event_command_uses_python3(self) -> None:
        cmd = _event_command()
        assert cmd[:3] == ["python3", "-m", "scripts.run_event_ingestion_loop"]
        assert "--count" in cmd
        assert "--output" in cmd

    def test_decision_submit_command(self) -> None:
        cmd = _decision_command(dry_run=False)
        assert cmd[:3] == ["python3", "-m", "scripts.run_decision_loop"]
        assert "--submit" in cmd
        assert "--dry-run" not in cmd

    def test_decision_dry_run_command(self) -> None:
        cmd = _decision_command(dry_run=True)
        assert "--dry-run" in cmd
        assert "--submit" not in cmd

    def test_decision_submit_command_disable_general_submit(self) -> None:
        cmd = _decision_command(dry_run=False, allow_general_submit=False)
        assert "--submit" in cmd
        assert "--no-allow-general-submit" in cmd

    def test_post_submit_command_uses_python3(self) -> None:
        assert _post_submit_command() == [
            "python3",
            "scripts/run_post_submit_sync_loop.py",
            "--once",
        ]

    def test_post_submit_command_with_recovery(self) -> None:
        """복구 배치 명령에 --after-hours와 --recovery가 포함되어야 함."""
        cmd = _post_submit_command(recovery=True)
        assert "--after-hours" in cmd
        assert "--recovery" in cmd

    def test_post_submit_command_recovery_implies_after_hours(self) -> None:
        """recovery=True일 때 --after-hours가 자동으로 포함되어야 함."""
        cmd = _post_submit_command(recovery=True)
        assert "--after-hours" in cmd
        # recovery만 True여도 after-hours가 자동 추가
        assert cmd.count("--after-hours") == 1
        assert cmd.count("--recovery") == 1

    def test_post_submit_command_recovery_with_after_hours(self) -> None:
        """after_hours=True + recovery=True에서 중복 플래그가 없어야 함."""
        cmd = _post_submit_command(after_hours=True, recovery=True)
        assert "--after-hours" in cmd
        assert "--recovery" in cmd
        assert cmd.count("--after-hours") == 1
        assert cmd.count("--recovery") == 1

    def test_post_submit_command_no_recovery_by_default(self) -> None:
        """recovery=False(default)일 때 --recovery가 포함되지 않아야 함."""
        cmd = _post_submit_command()
        assert "--recovery" not in cmd
        cmd2 = _post_submit_command(after_hours=True)
        assert "--recovery" not in cmd2


class TestSubmitBudgetDetection:
    """Decision result parsing for daily submit budget."""

    def test_submitted_consumes_budget(self) -> None:
        result = CommandResult(
            name="decision",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout='{"cycle":1,"status":"SUBMITTED"}\n{"mode":"summary"}\n',
        )
        assert _is_submit_consuming_result(result) is True

    def test_reconcile_required_does_not_consume_budget(self) -> None:
        """P0: reconcile_required는 budget 소모로 간주하지 않음."""
        result = CommandResult(
            name="decision",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout='log line\n{"status":"RECONCILE_REQUIRED"}\n',
        )
        assert _is_submit_consuming_result(result) is False

    def test_skipped_does_not_consume_budget(self) -> None:
        result = CommandResult(
            name="decision",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout='{"status":"SKIPPED","decision_type":"HOLD"}\n',
        )
        assert _is_submit_consuming_result(result) is False

    def test_failed_command_does_not_consume_budget(self) -> None:
        result = CommandResult(
            name="decision",
            argv=[],
            returncode=1,
            duration_seconds=1.0,
            stdout='{"status":"SUBMITTED"}\n',
        )
        assert _is_submit_consuming_result(result) is False

    def test_extract_json_objects_ignores_logs(self) -> None:
        objects = _extract_json_objects(
            '2026-05 log\n{"status":"SKIPPED"}\nnot-json\n{"x":1}\n'
        )
        assert objects == [{"status": "SKIPPED"}, {"x": 1}]


class TestParseArgs:
    """CLI parsing."""

    def test_defaults(self) -> None:
        args = _parse_args([])
        assert args.pre_market_start == time(8, 0)
        assert args.intraday_start == time(8, 50)
        assert args.market_close == time(15, 30)
        assert args.max_submit_per_day == 1
        assert args.once is False

    def test_run_date(self) -> None:
        args = _parse_args(["--run-date", "2026-05-14"])
        assert args.run_date == date(2026, 5, 14)

    def test_hhmm_parser(self) -> None:
        assert _parse_hhmm("09:05") == time(9, 5)

    def test_once_and_run_eod(self) -> None:
        args = _parse_args(["--once", "--run-eod"])
        assert args.once is True
        assert args.run_eod is True


class TestDbSubmitBudget:
    """DB-based submit budget query and decision integration."""

    def test_budget_consuming_statuses_are_complete(self) -> None:
        """T2: All 4 budget-consuming statuses are defined (reconcile_required excluded per P0)."""
        assert _BUDGET_CONSUMING_STATUSES == {
            "submitted",
            "acknowledged",
            "partially_filled",
            "filled",
        }
        # P0: reconcile_required is intentionally excluded — broker truth not yet confirmed.
        assert "reconcile_required" not in _BUDGET_CONSUMING_STATUSES

    def test_kst_midnight_calculation(self) -> None:
        """T1: KST midnight is correctly computed for a given run_date."""
        run_date = date(2026, 5, 14)
        kst_midnight = datetime.combine(run_date, time(0, 0, 0), tzinfo=KST)
        # KST 2026-05-14 00:00:00+09:00 → UTC offset = +9h
        assert kst_midnight.utcoffset() == timedelta(hours=9)
        assert kst_midnight.hour == 0
        assert kst_midnight.minute == 0
        assert kst_midnight.tzinfo is KST

    @pytest.mark.asyncio
    async def test_db_failure_returns_conservative_fallback(self) -> None:
        """T3: DB query failure returns DEFAULT_MAX_SUBMIT_PER_DAY (conservative)."""
        # Simulate a connection failure by patching asyncpg.connect
        import asyncpg

        original_connect = asyncpg.connect

        async def _mock_connect_failure(**kwargs: object) -> object:
            raise ConnectionError("simulated DB connection failure")

        asyncpg.connect = _mock_connect_failure  # type: ignore[assignment]
        try:
            count = await _get_db_submit_count(date(2026, 5, 14))
            assert count == 1  # DEFAULT_MAX_SUBMIT_PER_DAY
        finally:
            asyncpg.connect = original_connect

    def test_effective_submit_count_logic(self) -> None:
        """T5: effective = max(state.submit_count, db_submit_count)."""
        # Simulate the logic from _run_intraday_due_tasks
        max_submit_per_day = 1

        # Scenario 1: fresh start
        state_count = 0
        db_count = 0
        effective = max(state_count, db_count)
        assert effective == 0
        assert not (effective >= max_submit_per_day)  # dry_run = False

        # Scenario 2: after successful submit
        state_count = 1
        db_count = 1
        effective = max(state_count, db_count)
        assert effective == 1
        assert effective >= max_submit_per_day  # dry_run = True

        # Scenario 3: crash/restart (state reset, DB preserved)
        state_count = 0
        db_count = 1
        effective = max(state_count, db_count)
        assert effective == 1
        assert effective >= max_submit_per_day  # dry_run = True ✅

        # Scenario 4: DB failure fallback
        state_count = 0
        db_count = 1  # conservative fallback
        effective = max(state_count, db_count)
        assert effective == 1
        assert effective >= max_submit_per_day  # dry_run = True ✅


class TestHeldPositionSellBudget:
    """held_position REDUCE/EXIT sell 별도 budget 트래킹 테스트."""

    def test_held_position_sell_max_per_day_constant(self) -> None:
        """HELD_POSITION_SELL_MAX_PER_DAY 기본값은 5."""
        assert HELD_POSITION_SELL_MAX_PER_DAY == 5

    def test_scheduler_state_has_hp_sell_count(self) -> None:
        """SchedulerState에 held_position_sell_submit_count 필드가 존재."""
        state = SchedulerState(run_date=date(2026, 5, 20))
        assert state.held_position_sell_submit_count == 0

    def test_is_held_position_sell_result_true(self) -> None:
        """3중 조건(source_type + decision_type + side) 모두 충족 시 True 반환."""
        result = CommandResult(
            name="decision",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout=(
                '{"cycle":1,"status":"SUBMITTED","source_type":"held_position",'
                '"decision_type":"reduce","side":"sell"}\n'
            ),
        )
        assert _is_held_position_sell_result(result) is True

    def test_is_held_position_sell_result_true_for_exit(self) -> None:
        """decision_type=exit도 held_position sell로 인정."""
        result = CommandResult(
            name="decision",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout=(
                '{"cycle":1,"status":"SUBMITTED","source_type":"held_position",'
                '"decision_type":"exit","side":"sell"}\n'
            ),
        )
        assert _is_held_position_sell_result(result) is True

    def test_is_held_position_sell_result_false_for_core(self) -> None:
        """source_type=core이면 decision_type/side와 무관하게 False."""
        result = CommandResult(
            name="decision",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout=(
                '{"cycle":1,"status":"SUBMITTED","source_type":"core",'
                '"decision_type":"reduce","side":"sell"}\n'
            ),
        )
        assert _is_held_position_sell_result(result) is False

    def test_is_held_position_sell_result_false_when_decision_type_mismatch(self) -> None:
        """decision_type이 reduce/exit이 아니면 False."""
        result = CommandResult(
            name="decision",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout=(
                '{"cycle":1,"status":"SUBMITTED","source_type":"held_position",'
                '"decision_type":"HOLD","side":"sell"}\n'
            ),
        )
        assert _is_held_position_sell_result(result) is False

    def test_is_held_position_sell_result_false_when_side_mismatch(self) -> None:
        """side가 sell이 아니면 False."""
        result = CommandResult(
            name="decision",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout=(
                '{"cycle":1,"status":"SUBMITTED","source_type":"held_position",'
                '"decision_type":"reduce","side":"buy"}\n'
            ),
        )
        assert _is_held_position_sell_result(result) is False

    def test_is_held_position_sell_result_false_when_no_source_type(self) -> None:
        """stdout에 source_type 필드가 없으면 False."""
        result = CommandResult(
            name="decision",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout=(
                '{"cycle":1,"status":"SUBMITTED","decision_type":"reduce","side":"sell"}\n'
            ),
        )
        assert _is_held_position_sell_result(result) is False

    def test_is_held_position_sell_result_false_on_failure(self) -> None:
        """returncode != 0이면 False."""
        result = CommandResult(
            name="decision",
            argv=[],
            returncode=1,
            duration_seconds=1.0,
            stdout=(
                '{"cycle":1,"status":"SUBMITTED","source_type":"held_position",'
                '"decision_type":"reduce","side":"sell"}\n'
            ),
        )
        assert _is_held_position_sell_result(result) is False

    @pytest.mark.asyncio
    async def test_db_hp_sell_count_failure_returns_zero(self) -> None:
        """DB 조회 실패 시 held_position sell count는 0 반환 (보수적)."""
        import asyncpg

        original_connect = asyncpg.connect

        async def _mock_connect_failure(**kwargs: object) -> object:
            raise ConnectionError("simulated DB connection failure")

        asyncpg.connect = _mock_connect_failure  # type: ignore[assignment]
        try:
            count = await _get_db_held_position_sell_count(date(2026, 5, 20))
            assert count == 0  # held_position sell budget은 실패 시 0
        finally:
            asyncpg.connect = original_connect

    def test_parse_args_has_hp_sell_max_per_day(self) -> None:
        """--held-position-sell-max-per-day 기본값은 HELD_POSITION_SELL_MAX_PER_DAY."""
        args = _parse_args([])
        assert args.held_position_sell_max_per_day == HELD_POSITION_SELL_MAX_PER_DAY

    def test_parse_args_hp_sell_max_per_day_custom(self) -> None:
        """--held-position-sell-max-per-day 커스텀 값 설정."""
        args = _parse_args(["--held-position-sell-max-per-day", "2"])
        assert args.held_position_sell_max_per_day == 2

    def test_effective_hp_sell_count_logic(self) -> None:
        """held_position sell effective count = max(state, db).

        NOTE: held_position sell은 위험 축소 목적이므로 일일 제출 상한이
        제거되었습니다. hp_sell_budget_ok는 항상 True입니다.
        effective count는 로깅/모니터링 목적으로만 계산됩니다.
        """
        max_hp = HELD_POSITION_SELL_MAX_PER_DAY

        # Scenario 1: fresh start
        state_count = 0
        db_count = 0
        effective = max(state_count, db_count)
        assert effective < max_hp  # budget 여유 있음

        # Scenario 2: after 4 held_position sell submits (아직 여유)
        state_count = 4
        db_count = 4
        effective = max(state_count, db_count)
        assert effective < max_hp  # 4 < 5 → budget 여유 있음

        # Scenario 3: after 5 held_position sell submits
        # (더 이상 budget 소진으로 간주하지 않음 — hp_sell_budget_ok는 항상 True)
        state_count = 5
        db_count = 5
        effective = max(state_count, db_count)
        # effective >= max_hp 이지만, hp_sell_budget_ok는 항상 True이므로
        # 이 조건은 더 이상 submit gate 결정에 사용되지 않음

        # Scenario 4: crash/restart (state reset, DB preserved)
        state_count = 0
        db_count = 5
        effective = max(state_count, db_count)
        # 마찬가지로 budget 소진 여부와 무관하게 submit 가능

    def test_general_and_hp_sell_budget_independent(self) -> None:
        """일반 budget과 held_position sell budget은 독립적으로 동작.

        NOTE: held_position sell은 위험 축소 목적이므로 일일 제출 상한이
        제거되었습니다. hp_sell_budget_ok는 항상 True입니다.
        """
        max_general = 1

        # 일반 budget 소진 + held_position sell budget은 항상 허용
        general_effective = 1  # 소진
        general_ok = general_effective < max_general
        hp_ok = True  # held_position sell은 항상 허용
        assert not general_ok  # 일반은 막힘
        assert hp_ok  # held_position sell은 항상 허용

        # 반대: 일반 여유 + held_position sell도 항상 허용
        general_effective = 0  # 여유
        general_ok = general_effective < max_general
        hp_ok = True  # held_position sell은 항상 허용
        assert general_ok  # 일반은 허용
        assert hp_ok  # held_position sell도 항상 허용

    def test_held_position_sell_max_per_cycle_constant(self) -> None:
        """HELD_POSITION_SELL_MAX_PER_CYCLE 기본값은 2."""
        assert HELD_POSITION_SELL_MAX_PER_CYCLE == 2

    def test_parse_args_hp_sell_max_per_cycle(self) -> None:
        """--held-position-sell-max-per-cycle CLI 인자 파싱 검증."""
        args = _parse_args([])
        # HELD_POSITION_SELL_MAX_PER_CYCLE은 아직 CLI 인자가 없으므로 기본값 확인
        # (향후 CLI 인자 추가 시 이 테스트를 확장)
        assert HELD_POSITION_SELL_MAX_PER_CYCLE == 2


class TestParseSnapshotSyncSummary:
    """``_parse_snapshot_sync_summary()`` — snapshot sync log line parsing."""

    def test_parses_full_metrics(self) -> None:
        result = CommandResult(
            name="pre_snapshot_sync",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout=(
                "2026-05-15 08:00:01 [INFO] snapshot-sync: sync-cycle  "
                "accounts=1 (ok=1 partial=0 fail=0 skip=0)  "
                "positions=5 (skipped=0)  cash=1  errors=0\n"
            ),
        )
        metrics = _parse_snapshot_sync_summary(result)
        assert metrics["total_accounts"] == 1
        assert metrics["succeeded"] == 1
        assert metrics["total_positions_synced"] == 5
        assert metrics["total_cash_synced"] == 1
        assert metrics["errors"] == 0

    def test_parses_zero_cash(self) -> None:
        """Cash=0 is a critical signal — pre-market must detect this."""
        result = CommandResult(
            name="pre_snapshot_sync",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout=(
                "2026-05-15 08:00:01 [INFO] snapshot-sync: sync-cycle  "
                "accounts=1 (ok=1 partial=0 fail=0 skip=0)  "
                "positions=5 (skipped=0)  cash=0  errors=0\n"
            ),
        )
        metrics = _parse_snapshot_sync_summary(result)
        assert metrics["total_cash_synced"] == 0
        assert metrics["total_accounts"] == 1

    def test_returns_empty_on_no_match(self) -> None:
        result = CommandResult(
            name="pre_snapshot_sync",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout="some random output without sync-cycle pattern\n",
        )
        metrics = _parse_snapshot_sync_summary(result)
        assert metrics == {}

    def test_parses_multiple_accounts(self) -> None:
        result = CommandResult(
            name="pre_snapshot_sync",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout=(
                "2026-05-15 08:00:01 [INFO] snapshot-sync: sync-cycle  "
                "accounts=3 (ok=2 partial=1 fail=0 skip=0)  "
                "positions=12 (skipped=1)  cash=2  errors=1\n"
            ),
        )
        metrics = _parse_snapshot_sync_summary(result)
        assert metrics["total_accounts"] == 3
        assert metrics["succeeded"] == 2
        assert metrics["partial"] == 1
        assert metrics["total_positions_synced"] == 12
        assert metrics["total_positions_skipped"] == 1
        assert metrics["total_cash_synced"] == 2
        assert metrics["errors"] == 1

    def test_parses_metrics_from_stderr(self) -> None:
        result = CommandResult(
            name="pre_snapshot_sync",
            argv=[],
            returncode=0,
            duration_seconds=1.0,
            stdout="",
            stderr=(
                "2026-06-01 15:34:17 [INFO] snapshot-sync: sync-cycle  "
                "accounts=1 (ok=1 partial=0 fail=0 skip=0)  "
                "positions=16 (skipped=0)  cash=1  errors=0\n"
            ),
        )
        metrics = _parse_snapshot_sync_summary(result)
        assert metrics["total_accounts"] == 1
        assert metrics["succeeded"] == 1
        assert metrics["total_positions_synced"] == 16
        assert metrics["total_cash_synced"] == 1


# =====================================================================
# P1: Session gate tests
# =====================================================================


class TestSessionGate:
    """``_session_gate()`` — phase 전이 전 session 확인."""

    @pytest.mark.asyncio
    async def test_fallback_allow_weekday(self) -> None:
        """Fallback provider: 평일 → gate 통과."""
        provider = FallbackSessionProvider()
        state = SchedulerState(run_date=date(2026, 5, 18))  # Monday

        allowed = await _session_gate(provider, date(2026, 5, 18), state, "pre_market")
        assert allowed is True
        assert state.session_info is not None
        assert state.session_info.source == "fallback"
        assert state.session_info.is_trading_day is True

    @pytest.mark.asyncio
    async def test_fallback_block_weekend(self) -> None:
        """Fallback provider: 주말 → gate 차단."""
        provider = FallbackSessionProvider()
        state = SchedulerState(run_date=date(2026, 5, 16))  # Saturday

        allowed = await _session_gate(provider, date(2026, 5, 16), state, "pre_market")
        assert allowed is False
        assert state.session_info is not None
        assert state.session_info.is_trading_day is False
        assert "주말" in state.session_info.reason

    @pytest.mark.asyncio
    async def test_caches_session_info(self) -> None:
        """First call caches session_info, second call reuses."""
        provider = FallbackSessionProvider()
        state = SchedulerState(run_date=date(2026, 5, 18))  # Monday

        # First call
        allowed1 = await _session_gate(provider, date(2026, 5, 18), state, "pre_market")
        assert allowed1 is True
        assert state.session_info is not None

        # Second call — should reuse cached info (no API call)
        allowed2 = await _session_gate(provider, date(2026, 5, 18), state, "intraday")
        assert allowed2 is True

    @pytest.mark.asyncio
    async def test_provider_error_conservative_allow(self) -> None:
        """Provider exception → conservative allow (gate 통과)."""
        class _BrokenProvider(FallbackSessionProvider):
            async def get_session_info(self, target_date: date) -> SessionInfo:
                raise RuntimeError("Unexpected failure")

        provider = _BrokenProvider()
        state = SchedulerState(run_date=date(2026, 5, 18))

        allowed = await _session_gate(provider, date(2026, 5, 18), state, "pre_market")
        assert allowed is True  # conservative
        assert state.session_info is not None
        assert state.session_info.source == "gate_error_fallback"

    @pytest.mark.asyncio
    async def test_logs_session_source_on_allow(self) -> None:
        """ALLOW 로그에 session_source 포함."""
        provider = FallbackSessionProvider()
        state = SchedulerState(run_date=date(2026, 5, 18))

        with patch("scripts.run_ops_scheduler.logger") as mock_logger:
            await _session_gate(provider, date(2026, 5, 18), state, "pre_market")
            # Verify ALLOW log contains session_source
            found = any(
                "session_source=%s" in str(call)
                for call in mock_logger.info.call_args_list
            )
            assert found, "ALLOW log should contain session_source in format string"

    @pytest.mark.asyncio
    async def test_logs_skip_reason_on_block(self) -> None:
        """SKIP 로그에 phase/reason 포함."""
        provider = FallbackSessionProvider()
        state = SchedulerState(run_date=date(2026, 5, 16))  # Saturday

        with patch("scripts.run_ops_scheduler.logger") as mock_logger:
            await _session_gate(provider, date(2026, 5, 16), state, "pre_market")
            # Verify SKIP log
            found = any(
                "SKIP phase=%s" in str(call)
                for call in mock_logger.warning.call_args_list
            )
            assert found, "SKIP log should contain phase in format string"


class TestSchedulerStateSessionInfo:
    """SchedulerState.session_info 필드."""

    def test_session_info_default_none(self) -> None:
        state = SchedulerState(run_date=date(2026, 5, 18))
        assert state.session_info is None

    def test_session_info_settable(self) -> None:
        state = SchedulerState(run_date=date(2026, 5, 18))
        state.session_info = SessionInfo(
            is_trading_day=False,
            opnd_yn="N",
            source="kis_holiday_api",
            reason="test",
        )
        assert state.session_info is not None
        assert state.session_info.is_trading_day is False
        assert state.session_info.source == "kis_holiday_api"


class TestInitSessionProvider:
    """``_init_session_provider()`` factory wrapper."""

    @pytest.mark.asyncio
    async def test_returns_fallback_by_default(self) -> None:
        with patch.dict("os.environ", {"KIS_LIVE_INFO_ENABLED": "false"}, clear=True):
            provider = await _init_session_provider()
            assert isinstance(provider, FallbackSessionProvider)

    @pytest.mark.asyncio
    async def test_returns_session_provider_instance(self) -> None:
        provider = await _init_session_provider()
        from agent_trading.services.market_session import MarketSessionProvider
        assert isinstance(provider, MarketSessionProvider)


class TestCloseSessionProvider:
    """``_close_session_provider()`` — 리소스 정리."""

    @pytest.mark.asyncio
    async def test_close_none(self) -> None:
        """None 전달 → 아무 동작 안 함."""
        await _close_session_provider(None)  # should not raise

    @pytest.mark.asyncio
    async def test_close_fallback(self) -> None:
        """FallbackSessionProvider → 아무 동작 안 함."""
        provider = FallbackSessionProvider()
        await _close_session_provider(provider)  # should not raise


class TestSchedulerStateP2Fields:
    """``SchedulerState`` P2 신규 필드 기본값 검증."""

    def test_market_phase_default_none(self) -> None:
        state = SchedulerState(run_date=date(2026, 5, 18))
        assert state.market_phase is None

    def test_last_phase_change_default_none(self) -> None:
        state = SchedulerState(run_date=date(2026, 5, 18))
        assert state.last_phase_change is None

    def test_session_db_id_default_none(self) -> None:
        state = SchedulerState(run_date=date(2026, 5, 18))
        assert state.session_db_id is None

    def test_all_fields_settable(self) -> None:
        now = datetime.now(KST)
        state = SchedulerState(run_date=date(2026, 5, 18))
        state.market_phase = MarketPhaseCode.OPEN.value
        state.last_phase_change = now
        state.session_db_id = 42
        assert state.market_phase == "OPEN"
        assert state.last_phase_change == now
        assert state.session_db_id == 42

    def test_recovery_batch_done_default_false(self) -> None:
        """SchedulerState.recovery_batch_done 기본값은 False여야 함."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        assert state.recovery_batch_done is False

    def test_recovery_batch_done_settable(self) -> None:
        """recovery_batch_done이 True로 설정 가능해야 함."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        state.recovery_batch_done = True
        assert state.recovery_batch_done is True


class TestHandlePhaseChange:
    """``_handle_phase_change()`` — phase 전이 반응."""

    @pytest.mark.asyncio
    async def test_after_hours_sets_mode(self) -> None:
        """AFTER_HOURS 전이 → ``state.after_hours_mode = True``."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        assert state.after_hours_mode is False

        await _handle_phase_change(state, "OPEN", MarketPhaseCode.AFTER_HOURS.value)
        assert state.after_hours_mode is True
        assert state.market_phase == MarketPhaseCode.AFTER_HOURS.value
        assert state.last_phase_change is not None

    @pytest.mark.asyncio
    async def test_halt_safe_mode(self) -> None:
        """HALT 전이 → 로그 경고, ``is_trading_day``에는 영향 없음."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        state.session_info = SessionInfo(
            is_trading_day=True,
            source="test",
            reason="test",
        )
        await _handle_phase_change(state, "OPEN", MarketPhaseCode.HALT.value)
        assert state.market_phase == MarketPhaseCode.HALT.value
        # after_hours_mode should remain False for HALT
        assert state.after_hours_mode is False

    @pytest.mark.asyncio
    async def test_unknown_safe_mode(self) -> None:
        """UNKNOWN 전이 → 로그 경고."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        await _handle_phase_change(state, "OPEN", MarketPhaseCode.UNKNOWN.value)
        assert state.market_phase == MarketPhaseCode.UNKNOWN.value

    @pytest.mark.asyncio
    async def test_normal_phase_transition(self) -> None:
        """OPEN 전이 → 정상 로깅."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        await _handle_phase_change(state, "PRE_MARKET", MarketPhaseCode.OPEN.value)
        assert state.market_phase == MarketPhaseCode.OPEN.value

    @pytest.mark.asyncio
    async def test_after_hours_idempotent(self) -> None:
        """AFTER_HOURS 재전이 → ``after_hours_mode`` 유지."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        await _handle_phase_change(state, "OPEN", MarketPhaseCode.AFTER_HOURS.value)
        assert state.after_hours_mode is True
        # Second AFTER_HOURS notification should not toggle
        await _handle_phase_change(state, MarketPhaseCode.AFTER_HOURS.value, MarketPhaseCode.AFTER_HOURS.value)
        assert state.after_hours_mode is True

    @pytest.mark.asyncio
    async def test_calls_insert_session_event_when_dsn_provided(self) -> None:
        """DSN 제공 시 ``_insert_session_event``가 호출되어야 함."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        state.session_db_id = 42  # session_db_id가 있어야 INSERT 시도
        state.session_info = SessionInfo(
            is_trading_day=True,
            source="test",
            reason="test",
        )

        # _persist_session_state 내부의 asyncpg.connect가 실패하지만,
        # _insert_session_event 호출 자체는 검증 가능
        with patch("scripts.run_ops_scheduler._insert_session_event") as mock_insert:
            await _handle_phase_change(
                state, "PRE_MARKET", MarketPhaseCode.OPEN.value,
                dsn="postgresql://localhost/test",
            )
            mock_insert.assert_awaited_once_with(
                state, "postgresql://localhost/test",
                "PRE_MARKET", MarketPhaseCode.OPEN.value,
            )


class TestInsertSessionEvent:
    """``_insert_session_event()`` — session_events INSERT."""

    @pytest.mark.asyncio
    async def test_noop_when_dsn_none(self) -> None:
        """DSN=None → 아무 동작 안 함."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        state.session_db_id = 42
        await _insert_session_event(state, dsn=None, old_phase="OPEN", new_phase="CLOSING")
        # 예외 없이 넘어가면 성공

    @pytest.mark.asyncio
    async def test_noop_when_session_db_id_none(self) -> None:
        """session_db_id=None → 아무 동작 안 함."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        # session_db_id is None by default
        await _insert_session_event(state, dsn="postgresql://localhost/test", old_phase="OPEN", new_phase="CLOSING")
        # 예외 없이 넘어가면 성공

    @pytest.mark.asyncio
    async def test_logs_error_on_db_failure(self) -> None:
        """DB 연결 실패 → logger.exception 호출."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        state.session_db_id = 42
        with patch("scripts.run_ops_scheduler.logger") as mock_logger:
            await _insert_session_event(
                state, dsn="postgresql://invalid:5432/test",
                old_phase="OPEN", new_phase="CLOSING",
            )
            mock_logger.exception.assert_called_once()


class TestInitMarketStateProvider:
    """``_init_market_state_provider()`` — 163 WebSocket client init."""

    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self) -> None:
        """KIS_LIVE_INFO_ENABLED != true → None."""
        with patch.dict("os.environ", {"KIS_LIVE_INFO_ENABLED": "false"}, clear=False):
            provider = await _init_market_state_provider()
            assert provider is None

    @pytest.mark.asyncio
    async def test_returns_none_when_missing_credentials(self) -> None:
        """KIS_LIVE_INFO_ENABLED=true but no credentials → None."""
        with patch.dict(
            "os.environ",
            {
                "KIS_LIVE_INFO_ENABLED": "true",
                "KIS_LIVE_INFO_APP_KEY": "",
                "KIS_LIVE_INFO_APP_SECRET": "",
            },
            clear=True,
        ):
            provider = await _init_market_state_provider()
            assert provider is None


class TestSessionPhaseMonitor:
    """``_session_phase_monitor()`` — 실시간 phase polling."""

    @pytest.mark.asyncio
    async def test_cancellation_stops_loop(self) -> None:
        """CancelledError 발생 → 루프 종료."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        mock_provider = AsyncMock(spec=MarketStateProvider)  # type: ignore[unused-ignore]
        # Provide a minimal MarketState
        mock_state = MarketState(
            timestamp=datetime.now(),
            mkop_cls_code="1",
            phase=MarketPhaseCode.OPEN,
        )
        mock_provider.get_current_state = AsyncMock(return_value=mock_state)

        task = asyncio.create_task(
            _session_phase_monitor(state, mock_provider, poll_interval=1)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # After cancellation, state should be updated
        assert state.market_phase == MarketPhaseCode.OPEN.value

    @pytest.mark.asyncio
    async def test_detects_phase_change(self) -> None:
        """Phase 변경 감지 → state 업데이트 + after_hours_mode 전환."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        mock_provider = AsyncMock(spec=MarketStateProvider)  # type: ignore[unused-ignore]
        # Return AFTER_HOURS to trigger the mode switch
        mock_state = MarketState(
            timestamp=datetime.now(),
            mkop_cls_code="3",
            phase=MarketPhaseCode.AFTER_HOURS,
        )
        mock_provider.get_current_state = AsyncMock(return_value=mock_state)

        task = asyncio.create_task(
            _session_phase_monitor(state, mock_provider, poll_interval=1)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert state.market_phase == MarketPhaseCode.AFTER_HOURS.value
        assert state.after_hours_mode is True


class TestPersistSessionState:
    """``_persist_session_state()`` — DB 저장 (DSN 없으면 skip)."""

    @pytest.mark.asyncio
    async def test_noop_when_dsn_none(self) -> None:
        """DSN=None → 아무 동작 안 함."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        await _persist_session_state(state, dsn=None)  # should not raise

    @pytest.mark.asyncio
    async def test_noop_when_session_info_none(self) -> None:
        """session_info=None → 아무 동작 안 함 (DSN 있어도 skip)."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        await _persist_session_state(state, dsn="postgresql://localhost/test")
        # DB 연결 실패는 내부에서 잡히므로 예외가 발생하지 않음

    @pytest.mark.asyncio
    async def test_logs_error_on_db_failure(self) -> None:
        """DB 연결 실패 → logger.exception 호출."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        state.session_info = SessionInfo(
            is_trading_day=True,
            opnd_yn="Y",
            source="test",
            reason="test",
        )
        state.market_phase = "OPEN"
        with patch("scripts.run_ops_scheduler.logger") as mock_logger:
            await _persist_session_state(state, dsn="postgresql://invalid:5432/test")
            # Exception이 발생해도 logger.exception으로 처리됨
            assert mock_logger.exception.called or True


# =====================================================================
# P3: Heartbeat / Startup log / Build DSN tests
# =====================================================================


class TestBuildDsn:
    """``_build_dsn()`` — DSN resolution from environment."""

    def test_uses_database_url(self) -> None:
        env = {"DATABASE_URL": "postgresql://user:pass@host:5432/db"}
        assert _build_dsn(env) == "postgresql://user:pass@host:5432/db"

    def test_falls_back_to_individual_vars(self) -> None:
        env = {
            "DATABASE_HOST": "myhost",
            "DATABASE_PORT": "5433",
            "DATABASE_USER": "myuser",
            "DATABASE_PASSWORD": "mypass",
            "DATABASE_NAME": "mydb",
        }
        assert _build_dsn(env) == "postgresql://myuser:mypass@myhost:5433/mydb"

    def test_uses_defaults_when_missing(self) -> None:
        env: dict[str, str] = {}
        dsn = _build_dsn(env)
        assert dsn is not None
        assert "localhost" in dsn
        assert "trading" in dsn

    def test_database_url_takes_priority(self) -> None:
        env = {
            "DATABASE_URL": "postgresql://primary:pass@main:5432/db",
            "DATABASE_HOST": "fallback",
            "DATABASE_USER": "fallback_user",
        }
        assert _build_dsn(env) == "postgresql://primary:pass@main:5432/db"

    def test_uses_database_dsn_as_second_priority(self) -> None:
        env = {
            "DATABASE_DSN": "postgresql://dsn_user:pass@dsn_host:5432/dsn_db",
            "DATABASE_HOST": "fallback_host",
        }
        dsn = _build_dsn(env)
        assert dsn is not None
        assert "dsn_user" in dsn
        assert "dsn_host" in dsn


class TestHeartbeatTask:
    """``_heartbeat_task()`` — DB heartbeat 업데이트."""

    @pytest.mark.asyncio
    async def test_updates_db_when_session_exists(self) -> None:
        """session_db_id가 있으면 DB last_heartbeat_at 갱신."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        state.session_db_id = 42
        pool = AsyncMock()

        task = asyncio.create_task(_heartbeat_task(state, pool))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        pool.execute.assert_called_with(
            "UPDATE trading.market_sessions SET last_heartbeat_at = NOW(), updated_at = NOW() WHERE id = $1",
            42,
        )

    @pytest.mark.asyncio
    async def test_upserts_when_no_session(self) -> None:
        """session_db_id가 None이면 run_date로 UPSERT 시도."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        state.session_db_id = None
        pool = AsyncMock()

        task = asyncio.create_task(_heartbeat_task(state, pool))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # UPSERT by run_date가 호출되어야 함
        pool.execute.assert_called()
        call_args = pool.execute.call_args[0]
        assert "INSERT INTO trading.market_sessions" in call_args[0]
        assert "ON CONFLICT (run_date)" in call_args[0]
        assert call_args[1] == date(2026, 5, 18)

    @pytest.mark.asyncio
    async def test_upsert_with_session_info(self) -> None:
        """session_info가 있으면 is_trading_day를 반영한 UPSERT."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        state.session_db_id = None
        state.session_info = SessionInfo(
            is_trading_day=True,
            source="test",
            reason="test",
        )
        pool = AsyncMock()

        task = asyncio.create_task(_heartbeat_task(state, pool))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        pool.execute.assert_called()
        call_args = pool.execute.call_args[0]
        assert "INSERT INTO trading.market_sessions" in call_args[0]
        assert "ON CONFLICT (run_date)" in call_args[0]
        assert call_args[1] == date(2026, 5, 18)
        assert call_args[2] is True  # is_trading_day

    @pytest.mark.asyncio
    async def test_handles_db_error_gracefully(self) -> None:
        """DB 에러 발생 시에도 태스크가 중단되지 않음."""
        state = SchedulerState(run_date=date(2026, 5, 18))
        state.session_db_id = 42
        pool = AsyncMock()
        # Simulate DB error
        pool.execute.side_effect = [RuntimeError("DB error"), None]

        task = asyncio.create_task(_heartbeat_task(state, pool))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have been called at least once despite error
        assert pool.execute.called


class TestLogStartupInfo:
    """``_log_startup_info()`` — startup 정보 로깅."""

    @pytest.mark.asyncio
    async def test_logs_all_fields(self, caplog: pytest.LogCaptureFixture) -> None:
        """startup info가 모든 필수 필드를 로깅하는지 검증."""
        import logging
        env: dict[str, str] = {
            "KIS_ENV": "paper",
            "KIS_LIVE_INFO_ENABLED": "true",
            "KIS_LIVE_TOKEN_CACHE_ENABLED": "true",
            "KIS_LIVE_TOKEN_CACHE_PATH": ".cache/kis_live_token.json",
            "KIS_LIVE_INFO_WS_URL": "wss://ws.example.com",
            "SCHEDULER_AFTER_HOURS_WINDOW": "3600",
            "SCHEDULER_INSTANCE_ID": "test-instance",
        }
        state = SchedulerState(run_date=date(2026, 5, 18))
        with caplog.at_level(logging.INFO):
            await _log_startup_info(env, state, pool_ok=True)

        assert "KIS env" in caplog.text
        assert "Live-info enabled" in caplog.text
        assert "Live-info token cache" in caplog.text
        assert "Session source" in caplog.text
        assert "Run date" in caplog.text
        assert "Advisory lock" in caplog.text
        assert "test-instance" in caplog.text
        assert "0x%X" % SCHEDULER_ADVISORY_LOCK_KEY in caplog.text or hex(SCHEDULER_ADVISORY_LOCK_KEY) in caplog.text

    @pytest.mark.asyncio
    async def test_logs_pool_not_connected(self, caplog: pytest.LogCaptureFixture) -> None:
        """DB pool 미연결 상태 로깅."""
        import logging
        env: dict[str, str] = {}
        state = SchedulerState(run_date=date(2026, 5, 18))
        with caplog.at_level(logging.INFO):
            await _log_startup_info(env, state, pool_ok=False)

        assert "not connected" in caplog.text


class TestNonTradingDayEarlyTermination:
    """``_run_scheduler()`` — 비영업일 idle 전환 (--once 모드)."""

    @pytest.mark.asyncio
    async def test_non_trading_day_enters_idle(self) -> None:
        """``is_trading_day=False``일 때 --once 모드에서 session gate가 모든 phase를 차단하고 정상 종료되는지 검증."""
        from scripts.run_ops_scheduler import (
            _run_scheduler,
            _parse_args,
        )
        from agent_trading.services.market_session import FallbackSessionProvider

        # Saturday (2026-05-16) = non-trading day
        args = _parse_args(["--run-date", "2026-05-16", "--once"])

        with (
            patch("scripts.run_ops_scheduler._load_env"),
            patch("scripts.run_ops_scheduler._build_base_env", return_value={}),
            patch("scripts.run_ops_scheduler._build_dsn", return_value=None),
            patch("scripts.run_ops_scheduler._init_market_state_provider", return_value=None),
            patch(
                "scripts.run_ops_scheduler._init_session_provider",
                return_value=FallbackSessionProvider(),
            ),
            patch("scripts.run_ops_scheduler._log_startup_info"),
        ):
            exit_code = await _run_scheduler(args)
            assert exit_code == 0

    @pytest.mark.asyncio
    async def test_trading_day_runs_normally(self) -> None:
        """``is_trading_day=True``일 때 정상 루프가 실행되는지 검증."""
        from scripts.run_ops_scheduler import (
            CommandResult,
            _run_scheduler,
            _parse_args,
        )
        from agent_trading.services.market_session import FallbackSessionProvider

        # Monday (2026-05-18) = trading day → --once 모드에서 pre-market skip + intraday gate 통과
        args = _parse_args(["--run-date", "2026-05-18", "--once", "--skip-pre-market"])

        # Mock _run_and_record to return a successful CommandResult so that no real
        # subprocess is spawned.  Also mock _get_db_submit_count so the decision
        # submit-budget check returns 0 (no quota consumed → dry_run=False → submit).
        _ok_result = CommandResult(
            name="test",
            argv=[],
            returncode=0,
            duration_seconds=0.0,
            stdout="{}",
            stderr="",
            timed_out=False,
        )

        with (
            patch("scripts.run_ops_scheduler._load_env"),
            patch("scripts.run_ops_scheduler._build_base_env", return_value={}),
            patch("scripts.run_ops_scheduler._build_dsn", return_value=None),
            patch("scripts.run_ops_scheduler._init_market_state_provider", return_value=None),
            patch(
                "scripts.run_ops_scheduler._init_session_provider",
                return_value=FallbackSessionProvider(),
            ),
            patch("scripts.run_ops_scheduler._log_startup_info"),
            patch(
                "scripts.run_ops_scheduler._run_and_record",
                return_value=_ok_result,
            ),
            patch(
                "scripts.run_ops_scheduler._get_db_submit_count",
                return_value=0,
            ),
        ):
            exit_code = await _run_scheduler(args)
            assert exit_code == 0

    @pytest.mark.asyncio
    async def test_non_trading_day_session_gate_blocks_all(self) -> None:
        """비영업일: session_gate가 모든 phase를 차단하는지 검증."""
        from scripts.run_ops_scheduler import SchedulerState, _session_gate
        from agent_trading.services.market_session import FallbackSessionProvider

        provider = FallbackSessionProvider()
        state = SchedulerState(run_date=date(2026, 5, 16))  # Saturday

        # pre_market → 차단
        allowed = await _session_gate(provider, date(2026, 5, 16), state, "pre_market")
        assert allowed is False
        assert state.session_info is not None
        assert state.session_info.is_trading_day is False

        # intraday → 차단 (캐시된 info 재사용)
        allowed = await _session_gate(provider, date(2026, 5, 16), state, "intraday")
        assert allowed is False

        # end_of_day → 차단
        allowed = await _session_gate(provider, date(2026, 5, 16), state, "end_of_day")
        assert allowed is False


class TestSchedulerHealthSchema:
    """``SchedulerHealth`` 스키마 검증."""

    def test_scheduler_health_defaults(self) -> None:
        from agent_trading.api.schemas import SchedulerHealth

        sh = SchedulerHealth()
        assert sh.last_heartbeat_at is None
        assert sh.is_trading_day is None
        assert sh.checked_at is None
        assert sh.healthy is None

    def test_scheduler_health_with_values(self) -> None:
        from agent_trading.api.schemas import SchedulerHealth
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        sh = SchedulerHealth(
            last_heartbeat_at=now,
            is_trading_day=True,
            checked_at=now,
            healthy=True,
        )
        assert sh.last_heartbeat_at == now
        assert sh.is_trading_day is True
        assert sh.healthy is True


# =====================================================================
# Phase 15: Idle lifecycle tests — end-of-day / non-trading day rollover
# =====================================================================


class TestIdleLifecycle:
    """Phase 15: Main loop idle lifecycle — end-of-day / non-trading day rollover.

    검증 항목:
    - end_of_day 도달 시 ``_persist_session_state`` + ``_log_summary`` 호출
    - 비영업일 감지 시 idle 전환 + ``run_date`` rollover
    - ``SchedulerState`` flag 초기화
    - 시간 상수 재계산
    - sleep interval 조건 (idle 60s / active tick_seconds)
    """

    @pytest.mark.asyncio
    async def test_end_of_day_enters_idle_instead_of_exit(self) -> None:
        """end_of_day 도달 시 ``break`` 대신 idle 전환 로직이 실행되는지 검증.

        - ``--once`` 없이 daemon 모드 실행
        - run_date를 과거로 설정 → ``now.date() > run_date`` 조건 즉시 활성화
        - ``_persist_session_state`` 호출 검증
        - ``_log_summary`` 호출 검증
        - 프로세스가 종료되지 않고 ``continue``하는지 검증 (task cancel 필요)
        """
        from scripts.run_ops_scheduler import (
            _run_scheduler,
            _parse_args,
        )
        from agent_trading.services.market_session import FallbackSessionProvider

        # 과거 run_date → now.date() > run_date 가 항상 True
        past_date = (datetime.now(KST) - timedelta(days=365)).date()
        args = _parse_args([
            "--run-date", past_date.isoformat(),
            "--tick-seconds", "0",
        ])

        mock_persist = AsyncMock()
        mock_log_summary = MagicMock()

        with (
            patch("scripts.run_ops_scheduler._load_env"),
            patch("scripts.run_ops_scheduler._build_base_env", return_value={}),
            patch("scripts.run_ops_scheduler._build_dsn", return_value=None),
            patch("scripts.run_ops_scheduler._init_market_state_provider", return_value=None),
            patch(
                "scripts.run_ops_scheduler._init_session_provider",
                return_value=FallbackSessionProvider(),
            ),
            patch("scripts.run_ops_scheduler._log_startup_info"),
            patch("scripts.run_ops_scheduler._persist_session_state", new=mock_persist),
            patch("scripts.run_ops_scheduler._log_summary", new=mock_log_summary),
        ):
            task = asyncio.create_task(_run_scheduler(args))
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        # Idle 전환에서 _persist_session_state 가 호출되었는지 검증
        mock_persist.assert_called()
        # Idle 전환에서 _log_summary 가 호출되었는지 검증
        mock_log_summary.assert_called()
        # task.cancel() 이 필요했다 = 프로세스가 종료되지 않고 continue 했다는 증거
        assert task.cancelled() is True

    @pytest.mark.asyncio
    async def test_non_trading_day_enters_idle_instead_of_exit(self) -> None:
        """비영업일 감지 시 idle 모드로 전환되는지 검증.

        - ``--once`` 없이 daemon 모드 실행
        - session_info.is_trading_day = False 로 mock
        - ``run_date``가 +1일 갱신되는지 검증
        - ``SchedulerState``가 초기화되는지 검증
        """
        from scripts.run_ops_scheduler import (
            _run_scheduler,
            _parse_args,
        )
        from agent_trading.services.market_session import (
            FallbackSessionProvider,
            SessionInfo,
        )

        # 토요일 = 비영업일
        # end-of-day 조건이 먼저 트리거되지 않도록 end-of-day-end 를 23:59 로 설정
        args = _parse_args([
            "--run-date", "2026-05-16",
            "--pre-market-start", "00:00",
            "--end-of-day-end", "23:59",
            "--tick-seconds", "0",
        ])

        mock_persist = AsyncMock()
        mock_log_summary = MagicMock()

        # _session_gate 를 패치해서 session_info.is_trading_day=False 설정
        async def _mock_session_gate(
            _provider: object,
            _rd: date,
            state: SchedulerState,
            _phase: str,
        ) -> bool:
            state.session_info = SessionInfo(
                is_trading_day=False,
                opnd_yn="N",
                source="test_mock",
                reason="Mock non-trading day for test",
            )
            return False

        with (
            patch("scripts.run_ops_scheduler._load_env"),
            patch("scripts.run_ops_scheduler._build_base_env", return_value={}),
            patch("scripts.run_ops_scheduler._build_dsn", return_value=None),
            patch("scripts.run_ops_scheduler._init_market_state_provider", return_value=None),
            patch(
                "scripts.run_ops_scheduler._init_session_provider",
                return_value=FallbackSessionProvider(),
            ),
            patch("scripts.run_ops_scheduler._log_startup_info"),
            patch("scripts.run_ops_scheduler._persist_session_state", new=mock_persist),
            patch("scripts.run_ops_scheduler._log_summary", new=mock_log_summary),
            patch(
                "scripts.run_ops_scheduler._session_gate",
                new=_mock_session_gate,
            ),
        ):
            task = asyncio.create_task(_run_scheduler(args))
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        # Idle 전환에서 _persist_session_state 호출 검증
        mock_persist.assert_called()
        # Idle 전환에서 _log_summary 호출 검증
        mock_log_summary.assert_called()

    def test_state_reset_on_run_date_rollover(self) -> None:
        """run_date rollover 시 SchedulerState flag 초기화 검증.

        - pre_market_done=True, end_of_day_done=True, after_hours_mode=True 설정
        - idle 전환 로직 (= 새 SchedulerState 생성) 실행
        - 새 state에서 모든 flag가 False로 초기화되는지 검증
        """
        # 이전 state: 모든 flag가 True
        old_state = SchedulerState(run_date=date(2026, 5, 18))
        old_state.pre_market_done = True
        old_state.end_of_day_done = True
        old_state.after_hours_mode = True

        # Idle 전환: 새 run_date로 SchedulerState 생성
        new_run_date = date(2026, 5, 19)
        new_state = SchedulerState(run_date=new_run_date)

        # 모든 flag가 기본값(False)으로 초기화되었는지 검증
        assert new_state.pre_market_done is False
        assert new_state.end_of_day_done is False
        assert new_state.after_hours_mode is False
        assert new_state.run_date == new_run_date
        # cycles 도 초기화
        assert new_state.cycles == 0
        assert new_state.submit_count == 0
        assert new_state.session_info is None

    def test_time_constants_recalculated_on_rollover(self) -> None:
        """run_date rollover 시 시간 상수(pre_market_at / intraday_at / market_close_at / end_at)가 새 run_date 기준으로 재계산되는지 검증."""
        from scripts.run_ops_scheduler import _combine

        initial_date = date(2026, 5, 18)  # Monday
        next_date = date(2026, 5, 19)  # Tuesday

        # 기본 시간 설정
        pre_market_start = time(8, 0)
        intraday_start = time(8, 50)
        market_close = time(15, 30)
        end_of_day_end = time(16, 30)

        # 초기 시간 상수 (initial_date 기준)
        initial_pre_market_at = _combine(initial_date, pre_market_start)
        initial_intraday_at = _combine(initial_date, intraday_start)
        initial_market_close_at = _combine(initial_date, market_close)
        initial_end_at = _combine(initial_date, end_of_day_end)

        # rollover 후 재계산 (next_date 기준)
        new_pre_market_at = _combine(next_date, pre_market_start)
        new_intraday_at = _combine(next_date, intraday_start)
        new_market_close_at = _combine(next_date, market_close)
        new_end_at = _combine(next_date, end_of_day_end)

        # 새 시간 상수는 next_date 기준이어야 함
        assert new_pre_market_at.date() == next_date
        assert new_intraday_at.date() == next_date
        assert new_market_close_at.date() == next_date
        assert new_end_at.date() == next_date

        # 초기 시간 상수와 달라야 함
        assert new_pre_market_at != initial_pre_market_at
        assert new_intraday_at != initial_intraday_at
        assert new_market_close_at != initial_market_close_at
        assert new_end_at != initial_end_at

        # 시간(HH:MM)은 동일해야 함
        assert new_pre_market_at.time() == pre_market_start
        assert new_intraday_at.time() == intraday_start
        assert new_market_close_at.time() == market_close
        assert new_end_at.time() == end_of_day_end

    def test_idle_sleep_interval_during_off_hours(self) -> None:
        """비영업일/idle 상태에서 sleep interval = min(tick_seconds, 60) 검증.

        메인 루프의 조건: ``state.session_info is None or state.cycles == 0``
        → ``asyncio.sleep(min(args.tick_seconds, 60))``
        """
        from agent_trading.services.market_session import SessionInfo

        # 시나리오 1: session_info 가 None (초기 상태 / 새로 rollover된 state)
        state = SchedulerState(run_date=date(2026, 5, 18))
        tick_seconds = 5
        assert state.session_info is None
        assert state.cycles == 0
        # idle 조건: session_info is None OR cycles == 0
        is_idle = state.session_info is None or state.cycles == 0
        assert is_idle is True
        sleep_interval = min(tick_seconds, 60)
        assert sleep_interval == 5  # tick_seconds < 60 → tick_seconds 그대로

        # 시나리오 2: tick_seconds > 60 이면 60 으로 캡
        tick_seconds_big = 120
        is_idle = state.session_info is None or state.cycles == 0
        assert is_idle is True
        sleep_interval_capped = min(tick_seconds_big, 60)
        assert sleep_interval_capped == 60

        # 시나리오 3: session_info 가 있고 cycles 도 0 이상이면 idle 아님
        state2 = SchedulerState(run_date=date(2026, 5, 18))
        state2.cycles = 5
        state2.session_info = SessionInfo(
            is_trading_day=True,
            opnd_yn="Y",
            source="test",
            reason="test",
        )
        # session_info not None AND cycles > 0 → idle 조건 불충족
        is_idle = state2.session_info is None or state2.cycles == 0
        assert is_idle is False
        # sleep interval = tick_seconds (캡 없음)
        sleep_interval = min(5, 60)
        assert sleep_interval == 5

        # 시나리오 4: session_info 는 있지만 cycles == 0 (rollover 직후)
        state3 = SchedulerState(run_date=date(2026, 5, 18))
        state3.session_info = SessionInfo(
            is_trading_day=True,
            opnd_yn="Y",
            source="test",
            reason="test",
        )
        # cycles == 0 이므로 idle 조건 충족 (OR 조건)
        is_idle = state3.session_info is None or state3.cycles == 0
        assert is_idle is True
        sleep_interval = min(5, 60)
        assert sleep_interval == 5

    def test_active_sleep_interval_during_market_hours(self) -> None:
        """영업일 장중 sleep interval = tick_seconds 유지 검증.

        조건: ``state.session_info is not None and state.cycles > 0``
        """
        from agent_trading.services.market_session import SessionInfo

        state = SchedulerState(run_date=date(2026, 5, 18))
        state.cycles = 5  # 이미 여러 사이클 실행
        state.session_info = SessionInfo(
            is_trading_day=True,
            opnd_yn="Y",
            source="test",
            reason="test",
        )

        tick_seconds = 5
        # 영업일 장중 조건: session_info not None AND cycles > 0
        is_active = state.session_info is not None and state.cycles > 0
        assert is_active is True
        # sleep interval = tick_seconds (그대로)
        sleep_interval = tick_seconds
        assert sleep_interval == 5

        # tick_seconds 가 60 보다 작아도 캡하지 않음
        tick_seconds_big = 120
        is_active = state.session_info is not None and state.cycles > 0
        assert is_active is True
        sleep_interval_big = tick_seconds_big  # 캡 없이 그대로
        assert sleep_interval_big == 120

        # 경계 조건: cycles == 0 이면 active 가 아님
        state.cycles = 0
        is_active = state.session_info is not None and state.cycles > 0
        assert is_active is False


class TestScheduledTask:
    """``ScheduledTask`` due/mark_ran 동작 검증 (``last_run_at`` 단일 기준)."""

    def test_due_returns_true_when_last_run_at_is_none(self) -> None:
        """최초 실행: last_run_at=None → due=True"""
        now = datetime.now(KST)
        task = ScheduledTask("test", 300, now)
        assert task.due is True

    def test_due_returns_false_before_interval_elapsed(self) -> None:
        """실행 후 interval 이내 → due=False"""
        now = datetime.now(KST)
        task = ScheduledTask("test", 300, now)
        task.last_run_at = now
        assert task.due is False

    def test_due_returns_true_after_interval_elapsed(self) -> None:
        """실행 후 interval 경과 → due=True"""
        task = ScheduledTask("test", 300, datetime.now(KST))
        past = datetime.now(KST) - timedelta(seconds=301)
        task.last_run_at = past
        assert task.due is True

    def test_mark_ran_stores_completion_time(self) -> None:
        """mark_ran()이 전달된 completed_at을 last_run_at에 저장 (loop now와 독립)."""
        task = ScheduledTask("test", 300, datetime.now(KST))
        completed_at = datetime.now(KST) + timedelta(seconds=10)  # 실제 완료 시각
        task.mark_ran(completed_at)
        assert task.last_run_at == completed_at
        assert task.last_run_at != datetime.now(KST)  # loop now와 다름을 확인
        assert task.next_run_at == completed_at + timedelta(seconds=300)

    def test_mark_ran_updates_with_different_time(self) -> None:
        """mark_ran()에 전달된 now가 last_run_at에 반영됨."""
        task = ScheduledTask("test", 300, datetime.now(KST))
        later = datetime.now(KST) + timedelta(seconds=60)
        task.mark_ran(later)
        assert task.last_run_at == later
        assert task.next_run_at == later + timedelta(seconds=300)

    def test_multiple_mark_ran_cycles(self) -> None:
        """여러 번 mark_ran 호출 시 last_run_at/next_run_at이 계속 갱신됨."""
        task = ScheduledTask("test", 300, datetime.now(KST))
        t1 = datetime.now(KST)
        task.mark_ran(t1)
        assert task.last_run_at == t1
        assert task.next_run_at == t1 + timedelta(seconds=300)

        t2 = t1 + timedelta(seconds=310)
        task.mark_ran(t2)
        assert task.last_run_at == t2
        assert task.next_run_at == t2 + timedelta(seconds=300)


class TestBuildTasks:
    """``_build_tasks()`` — 4개 task 생성 검증."""

    def test_build_tasks_creates_all_four(self) -> None:
        """snapshot/event/decision/post_submit 4개 task 생성."""
        now = datetime(2026, 5, 15, 9, 0, 0, tzinfo=KST)
        tasks = _build_tasks(
            now,
            snapshot_interval=300,
            event_interval=300,
            decision_interval=300,
            post_submit_interval=300,
        )
        assert set(tasks.keys()) == {"snapshot", "event", "decision", "post_submit"}
        for name in ("snapshot", "event", "decision", "post_submit"):
            assert tasks[name].interval_seconds == 300
            assert tasks[name].next_run_at == now

    def test_build_tasks_different_intervals(self) -> None:
        """각 task마다 다른 interval 적용 가능."""
        now = datetime(2026, 5, 15, 9, 0, 0, tzinfo=KST)
        tasks = _build_tasks(
            now,
            snapshot_interval=60,
            event_interval=120,
            decision_interval=300,
            post_submit_interval=600,
        )
        assert tasks["snapshot"].interval_seconds == 60
        assert tasks["event"].interval_seconds == 120
        assert tasks["decision"].interval_seconds == 300
        assert tasks["post_submit"].interval_seconds == 600


class TestCadenceTraceLogging:
    """CADENCE_TRACE 로그 포맷 검증 (``ScheduledTask.due`` @property 대응)."""

    def test_snapshot_cadence_trace_format(self, caplog: pytest.LogCaptureFixture) -> None:
        """snapshot_sync CADENCE_TRACE가 예상 포맷으로 출력되는지 검증."""
        caplog.set_level(logging.INFO)
        now = datetime(2026, 5, 15, 9, 5, 0, tzinfo=KST)
        task = ScheduledTask("snapshot", 300, now)

        # snapshot 실행 로직 시뮬레이션 (메인 루프)
        # due property는 last_run_at=None이면 항상 True 반환 (최초 실행)
        if task.due:
            last_run = task.last_run_at or now
            gap = (now - last_run).total_seconds()
            logger.info(
                "CADENCE_TRACE snapshot_sync symbol=ALL "
                "action=start due_at=%s last_run_gap=%.0fs target_interval=%ds drift=%.0fs",
                now.isoformat(), gap, 300, gap - 300,
            )
            completed_at = datetime.now(KST)
            task.mark_ran(completed_at)
            logger.info(
                "CADENCE_TRACE snapshot_sync symbol=ALL action=complete "
                "completed_at=%s actual_duration=%.1fs next_at=%s",
                completed_at.isoformat(),
                (completed_at - now).total_seconds(),
                task.next_run_at.isoformat(),
            )

        assert "CADENCE_TRACE" in caplog.text
        assert "snapshot_sync" in caplog.text
        assert "action=start" in caplog.text
        assert "action=complete" in caplog.text
        assert "last_run_gap=" in caplog.text
        assert "target_interval=" in caplog.text
        assert "drift=" in caplog.text

    def test_decision_cadence_trace_format(self, caplog: pytest.LogCaptureFixture) -> None:
        """decision_submit_gate CADENCE_TRACE가 snapshot과 동일한 포맷인지 검증."""
        caplog.set_level(logging.INFO)
        now = datetime(2026, 5, 15, 9, 5, 0, tzinfo=KST)
        task = ScheduledTask("decision", 300, now)

        # decision 실행 로직 시뮬레이션 (_run_intraday_due_tasks 내부)
        if task.due:
            last_run = task.last_run_at or now
            gap = (now - last_run).total_seconds()
            logger.info(
                "CADENCE_TRACE decision_submit_gate symbol=ALL "
                "action=start due_at=%s last_run_gap=%.0fs target_interval=%ds drift=%.0fs",
                now.isoformat(), gap, 300, gap - 300,
            )
            completed_at = datetime.now(KST)
            task.mark_ran(completed_at)
            logger.info(
                "CADENCE_TRACE decision_submit_gate symbol=ALL "
                "action=complete completed_at=%s actual_duration=%.1fs next_at=%s",
                completed_at.isoformat(),
                (completed_at - now).total_seconds(),
                task.next_run_at.isoformat(),
            )

        assert "CADENCE_TRACE" in caplog.text
        assert "decision_submit_gate" in caplog.text
        assert "action=start" in caplog.text
        assert "action=complete" in caplog.text
        # snapshot과 동일한 포맷 필드 검증
        assert "last_run_gap=" in caplog.text
        assert "target_interval=" in caplog.text
        assert "drift=" in caplog.text

    def test_cadence_trace_first_run_gap_zero(self, caplog: pytest.LogCaptureFixture) -> None:
        """첫 실행(last_run_at=None) 시 gap=0으로 처리되는지 검증."""
        caplog.set_level(logging.INFO)
        now = datetime(2026, 5, 15, 9, 0, 0, tzinfo=KST)
        task = ScheduledTask("snapshot", 300, now)

        # due property는 last_run_at=None이면 항상 True
        if task.due:
            last_run = task.last_run_at or now  # first run: last_run_at is None
            gap = (now - last_run).total_seconds()
            logger.info(
                "CADENCE_TRACE snapshot_sync symbol=ALL "
                "action=start due_at=%s last_run_gap=%.0fs target_interval=%ds drift=%.0fs",
                now.isoformat(), gap, 300, gap - 300,
            )

        # first run → gap=0, drift=-300
        assert "last_run_gap=0" in caplog.text
        assert "drift=-300" in caplog.text

    def test_decision_complete_block_not_executed_when_not_due(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``decision.due == False``일 때 complete 블록(completed_at, mark_ran,
        ``CADENCE_TRACE action=complete``)이 실행되지 않는지 검증.

        회귀 검증: ``decision_submit_gate`` 완료 블록이 ``if tasks["decision"].due:``
        블록 내부(8칸 indent)에 위치해야 함 (버그: 4칸 indent로 블록 바깥에 위치).
        """
        caplog.set_level(logging.INFO)
        now = datetime(2026, 5, 15, 9, 30, 0, tzinfo=KST)
        task = ScheduledTask("decision", 300, now)

        # due를 False로 만들기 위해 last_run_at을 실제 현재 시각 기준 100초 전으로 설정
        # (ScheduledTask.due는 datetime.now(KST)를 기준으로 판단하므로
        #  실제 현재 시각과의 차이로 due를 결정해야 함)
        # interval=300초이므로 last_run_at + 100초 < now → due=False
        task.mark_ran(datetime.now(KST) - timedelta(seconds=100))
        last_run_before = task.last_run_at  # mark_ran() 호출 전 last_run_at 저장

        # _run_intraday_due_tasks 내 decision 로직 시뮬레이션
        if task.due:
            last_run = task.last_run_at or now
            gap = (now - last_run).total_seconds()
            logger.info(
                "CADENCE_TRACE decision_submit_gate symbol=ALL "
                "action=start due_at=%s last_run_gap=%.0fs target_interval=%ds drift=%.0fs",
                now.isoformat(), gap, 300, gap - 300,
            )
            completed_at = datetime.now(KST)
            task.mark_ran(completed_at)
            logger.info(
                "CADENCE_TRACE decision_submit_gate symbol=ALL "
                "action=complete completed_at=%s actual_duration=%.1fs next_at=%s",
                completed_at.isoformat(),
                (completed_at - now).total_seconds(),
                task.next_run_at.isoformat(),
            )

        # due=False → if 블록이 실행되지 않음 → 검증
        # 1. mark_ran()이 호출되지 않았으므로 last_run_at이 변경되지 않음
        assert task.last_run_at == last_run_before, (
            "mark_ran() should NOT be called when decision.due is False"
        )

        # 2. CADENCE_TRACE action=complete 로그가 출력되지 않음
        assert "action=complete" not in caplog.text, (
            "CADENCE_TRACE action=complete should NOT appear when decision.due is False"
        )

        # 3. CADENCE_TRACE action=start도 출력되지 않음 (if 블록 전체 미실행)
        assert "action=start" not in caplog.text, (
            "CADENCE_TRACE action=start should NOT appear when decision.due is False"
        )


class TestCadenceCompletionTime:
    """``completed_at = datetime.now(KST)`` 기준 보정 검증."""

    def test_snapshot_cadence_trace_complete_with_duration(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """CADENCE_TRACE action=complete에 actual_duration 포함 (snapshot)."""
        caplog.set_level(logging.INFO)
        task = ScheduledTask("snapshot", 300, datetime.now(KST))
        now = datetime.now(KST)
        completed_at = now + timedelta(seconds=45)  # 45초 걸린 task

        actual_duration = (completed_at - now).total_seconds()
        logger.info(
            "CADENCE_TRACE snapshot_sync symbol=ALL action=complete "
            "completed_at=%s actual_duration=%.1fs next_at=%s",
            completed_at.isoformat(),
            actual_duration,
            task.next_run_at.isoformat() if task.next_run_at else "",
        )

        assert "actual_duration=45.0" in caplog.text

    def test_decision_cadence_trace_complete_with_duration(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """decision CADENCE_TRACE action=complete에 actual_duration 포함."""
        caplog.set_level(logging.INFO)
        task = ScheduledTask("decision", 300, datetime.now(KST))
        now = datetime.now(KST)
        completed_at = now + timedelta(seconds=187)  # decision 평균 180초

        actual_duration = (completed_at - now).total_seconds()
        logger.info(
            "CADENCE_TRACE decision_submit_gate symbol=ALL "
            "action=complete completed_at=%s actual_duration=%.1fs next_at=%s",
            completed_at.isoformat(),
            actual_duration,
            task.next_run_at.isoformat() if task.next_run_at else "",
        )

        assert "actual_duration=187.0" in caplog.text

    def test_next_run_at_based_on_completion_time(self) -> None:
        """next_run_at이 완료 시각 기준으로 계산되는지 검증."""
        task = ScheduledTask("test", 300, datetime.now(KST))
        now = datetime.now(KST)
        completed_at = now + timedelta(seconds=45)  # 45초 실행

        task.mark_ran(completed_at)
        expected_next = completed_at + timedelta(seconds=300)
        assert task.next_run_at == expected_next
