"""Tests for scripts.run_realized_pnl_recompute_worker (recompute queue 소비 워커).

계산/replay 로직 자체는 test_realized_pnl_recompute_service.py에서 이미
검증되었으므로 여기서는 반복하지 않는다. 이 스크립트는 그 서비스를 실제
운영 경로에서 호출하는 얇은 wrapper이므로, 테스트도 그 연결(호출 여부,
limit 전달, 성공/실패 집계, 큐가 비어있는 경우)만 검증한다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agent_trading.domain.entities import RealizedPnlComputationRunEntity
from agent_trading.domain.enums import RealizedPnlComputationRunType
from scripts.run_realized_pnl_recompute_worker import (
    RecomputeOutcome,
    _log_cycle_summary,
    _run_one_cycle,
)


def _make_outcome(*, status: str, resolved_count: int = 0) -> RecomputeOutcome:
    account_id = uuid4()
    instrument_id = uuid4()
    run = RealizedPnlComputationRunEntity(
        computation_run_id=uuid4(),
        run_type=RealizedPnlComputationRunType.BACKFILL_REPLAY,
        status=status,
        fills_applied=0,
        fills_skipped_duplicate=0,
        fills_replayed=3 if status == "completed" else 0,
        anomalies_detected=0 if status == "completed" else 1,
        started_at=datetime.now(timezone.utc),
        account_id=account_id,
        summary_json={"phase": "replay", "error": "boom"} if status == "failed" else None,
    )
    return RecomputeOutcome(
        account_id=account_id,
        instrument_id=instrument_id,
        computation_run=run,
        resolved_queue_item_ids=tuple(uuid4() for _ in range(resolved_count)),
    )


class TestRunOneCycle:
    """``_run_one_cycle``이 실제로 ``process_pending_queue()``를 호출하는지 검증한다."""

    @pytest.mark.asyncio
    async def test_calls_process_pending_queue_with_limit(self) -> None:
        repos = object()
        fake_service = AsyncMock()
        fake_service.process_pending_queue.return_value = ()

        with patch(
            "scripts.run_realized_pnl_recompute_worker.RealizedPnlRecomputeService",
            return_value=fake_service,
        ) as service_cls:
            result = await _run_one_cycle(repos, limit=42)

        service_cls.assert_called_once_with(repos)
        fake_service.process_pending_queue.assert_awaited_once_with(limit=42)
        assert result == ()

    @pytest.mark.asyncio
    async def test_returns_no_pending_items(self) -> None:
        repos = object()
        fake_service = AsyncMock()
        fake_service.process_pending_queue.return_value = ()

        with patch(
            "scripts.run_realized_pnl_recompute_worker.RealizedPnlRecomputeService",
            return_value=fake_service,
        ):
            result = await _run_one_cycle(repos, limit=100)

        assert result == ()

    @pytest.mark.asyncio
    async def test_aggregates_mixed_success_and_failure(self) -> None:
        repos = object()
        outcomes = (
            _make_outcome(status="completed", resolved_count=2),
            _make_outcome(status="failed"),
        )
        fake_service = AsyncMock()
        fake_service.process_pending_queue.return_value = outcomes

        with patch(
            "scripts.run_realized_pnl_recompute_worker.RealizedPnlRecomputeService",
            return_value=fake_service,
        ):
            result = await _run_one_cycle(repos, limit=100)

        assert result == outcomes
        assert result[0].computation_run.status == "completed"
        assert result[1].computation_run.status == "failed"


class TestLogCycleSummary:
    """실패 케이스가 조용히 사라지지 않고 로그로 남는지 검증한다."""

    def test_summary_counts_and_failure_log(self, caplog: pytest.LogCaptureFixture) -> None:
        outcomes = (
            _make_outcome(status="completed", resolved_count=2),
            _make_outcome(status="completed", resolved_count=1),
            _make_outcome(status="failed"),
        )

        with caplog.at_level(logging.INFO, logger="realized_pnl_recompute_worker"):
            _log_cycle_summary(outcomes, cycle_start=0.0)

        summary_lines = [r.message for r in caplog.records if "cycle-complete" in r.message]
        assert len(summary_lines) == 1
        assert "recompute_processed_count=3" in summary_lines[0]
        assert "recompute_completed_count=2" in summary_lines[0]
        assert "recompute_failed_count=1" in summary_lines[0]
        assert "recompute_queue_resolved_count=3" in summary_lines[0]

        failure_lines = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "recompute-failed" in r.message
        ]
        assert len(failure_lines) == 1
        assert str(outcomes[2].account_id) in failure_lines[0].message
        assert str(outcomes[2].instrument_id) in failure_lines[0].message

    def test_empty_outcomes_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="realized_pnl_recompute_worker"):
            _log_cycle_summary((), cycle_start=0.0)

        assert not any("cycle-complete" in r.message for r in caplog.records)
