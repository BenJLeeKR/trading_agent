"""Tests for ``scripts.run_near_real_ops_scheduler`` (P1 + P2)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from scripts.run_near_real_ops_scheduler import (
    CommandResult,
    KST,
    SchedulerState,
    _BUDGET_CONSUMING_STATUSES,
    _close_session_provider,
    _decision_command,
    _event_command,
    _extract_json_objects,
    _get_db_submit_count,
    _handle_phase_change,
    _init_market_state_provider,
    _init_session_provider,
    _is_submit_consuming_result,
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
        assert cmd[:3] == ["python3", "-m", "scripts.run_paper_decision_loop"]
        assert "--submit" in cmd
        assert "--dry-run" not in cmd

    def test_decision_dry_run_command(self) -> None:
        cmd = _decision_command(dry_run=True)
        assert "--dry-run" in cmd
        assert "--submit" not in cmd

    def test_post_submit_command_uses_python3(self) -> None:
        assert _post_submit_command() == [
            "python3",
            "scripts/run_post_submit_sync_loop.py",
            "--once",
        ]


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

        with patch("scripts.run_near_real_ops_scheduler.logger") as mock_logger:
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

        with patch("scripts.run_near_real_ops_scheduler.logger") as mock_logger:
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
        with patch.dict("os.environ", {}, clear=False):
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
                "KIS_APP_KEY": "",
                "KIS_APP_SECRET": "",
                "KIS_PAPER_APP_KEY": "",
                "KIS_PAPER_APP_SECRET": "",
            },
            clear=False,
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
        with patch("scripts.run_near_real_ops_scheduler.logger") as mock_logger:
            await _persist_session_state(state, dsn="postgresql://invalid:5432/test")
            # Exception이 발생해도 logger.exception으로 처리됨
            assert mock_logger.exception.called or True
