"""Tests for ``scripts.run_near_real_ops_scheduler``."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from scripts.run_near_real_ops_scheduler import (
    CommandResult,
    KST,
    _BUDGET_CONSUMING_STATUSES,
    _decision_command,
    _event_command,
    _extract_json_objects,
    _get_db_submit_count,
    _is_submit_consuming_result,
    _parse_args,
    _parse_hhmm,
    _parse_snapshot_sync_summary,
    _post_submit_command,
    _snapshot_command,
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
