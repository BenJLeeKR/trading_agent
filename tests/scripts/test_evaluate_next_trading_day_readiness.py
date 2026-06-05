from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agent_trading.domain.entities import (
    FillSyncRunEntity,
    MarketSessionEntity,
    OrderRequestEntity,
    SnapshotSyncRunEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from scripts.evaluate_next_trading_day_readiness import (
    NextTradingDayReadinessEvaluator,
    _build_persisted_summary,
)


_NOW = datetime.now(timezone.utc)


def _add_order(
    repos,
    *,
    status: OrderStatus,
    reason_code: str | None = None,
) -> None:
    order_id = uuid4()
    repos.orders._items[order_id] = OrderRequestEntity(
        order_request_id=order_id,
        account_id=uuid4(),
        instrument_id=uuid4(),
        client_order_id=f"CLI-{order_id}",
        idempotency_key=f"IDEM-{order_id}",
        correlation_id=f"CORR-{order_id}",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        requested_quantity=Decimal("1"),
        requested_price=None,
        status=status,
        time_in_force=TimeInForce.DAY,
        status_reason_code=reason_code,
        created_at=_NOW,
        updated_at=_NOW,
        submitted_at=_NOW,
        version=1,
    )


def _seed_fill_sync_completed(repos, *, retries: int = 0) -> None:
    run_id = uuid4()
    repos.fill_sync_runs._items[run_id] = FillSyncRunEntity(
        fill_sync_run_id=run_id,
        trigger_type="interval",
        scope="all",
        dry_run=False,
        total_accounts=1,
        succeeded_accounts=1,
        partial_accounts=0,
        failed_accounts=0,
        skipped_accounts=0,
        fills_synced_total=3,
        fills_skipped_total=0,
        error_count=0,
        status="completed",
        started_at=_NOW,
        completed_at=_NOW + timedelta(seconds=1),
        summary_json={
            "retried_accounts": 1 if retries else 0,
            "retried_days": 1 if retries else 0,
            "total_retries": retries,
        },
        created_at=_NOW,
    )


def _seed_market_session(repos, *, run_date: date, is_trading_day: bool) -> None:
    repos.market_session_repo._sessions.clear()
    repos.market_session_repo._sessions.append(
        MarketSessionEntity(
            id=1,
            run_date=run_date,
            is_trading_day=is_trading_day,
            opnd_yn="Y" if is_trading_day else "N",
            bzdy_yn="Y" if is_trading_day else "N",
            tr_day_yn="Y" if is_trading_day else "N",
            market_phase="AFTER_HOURS" if is_trading_day else "IDLE",
            source="test",
            reason="seeded",
            checked_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )


def _seed_stale_snapshot_sync(repos) -> None:
    repos.snapshot_sync_runs._items.clear()
    run_id = uuid4()
    stale_started = _NOW - timedelta(hours=2)
    repos.snapshot_sync_runs._items[run_id] = SnapshotSyncRunEntity(
        snapshot_sync_run_id=run_id,
        trigger_type="interval",
        scope="all",
        dry_run=False,
        total_accounts=1,
        succeeded_accounts=1,
        partial_accounts=0,
        failed_accounts=0,
        skipped_accounts=0,
        positions_synced_total=1,
        positions_skipped_total=0,
        cash_synced_count=1,
        error_count=0,
        status="completed",
        started_at=stale_started,
        completed_at=stale_started + timedelta(minutes=1),
        created_at=stale_started,
    )


class TestNextTradingDayReadinessEvaluator:
    @pytest.mark.asyncio
    async def test_ready_when_no_blockers(self) -> None:
        repos = build_in_memory_repositories()
        _seed_fill_sync_completed(repos, retries=0)
        _seed_market_session(repos, run_date=date(2026, 6, 3), is_trading_day=False)

        evaluator = NextTradingDayReadinessEvaluator(repos)
        result = await evaluator.evaluate(target_date=date(2026, 6, 3))

        assert result.overall_status == "READY"
        assert result.blocking_unresolved_count == 0
        assert result.warning_unresolved_count == 0
        assert result.truth_probe_pending_count == 0

    @pytest.mark.asyncio
    async def test_blocked_when_unresolved_or_snapshot_stale(self) -> None:
        repos = build_in_memory_repositories()
        _seed_fill_sync_completed(repos, retries=0)
        _seed_market_session(repos, run_date=date(2026, 6, 3), is_trading_day=True)
        _seed_stale_snapshot_sync(repos)
        _add_order(repos, status=OrderStatus.SUBMITTED)

        evaluator = NextTradingDayReadinessEvaluator(repos)
        result = await evaluator.evaluate(target_date=date(2026, 6, 3))

        assert result.overall_status == "BLOCKED"
        assert result.blocking_unresolved_count == 1
        codes = {check.code: check.status for check in result.checks}
        assert codes["NTD_UNRESOLVED_BLOCKING"] == "BLOCKED"
        assert codes["NTD_SNAPSHOT_SYNC"] == "BLOCKED"

    @pytest.mark.asyncio
    async def test_warn_when_truth_probe_pending_or_fill_sync_retried(self) -> None:
        repos = build_in_memory_repositories()
        _seed_fill_sync_completed(repos, retries=1)
        _seed_market_session(repos, run_date=date(2026, 6, 3), is_trading_day=False)
        _add_order(
            repos,
            status=OrderStatus.PARTIALLY_FILLED,
            reason_code="truth_probe_fill_snapshot_incomplete",
        )

        evaluator = NextTradingDayReadinessEvaluator(repos)
        result = await evaluator.evaluate(target_date=date(2026, 6, 3))

        assert result.overall_status == "WARN"
        assert result.warning_unresolved_count == 1
        assert result.truth_probe_pending_count == 1
        codes = {check.code: check.status for check in result.checks}
        assert codes["NTD_TRUTH_PROBE_PENDING"] == "WARN"
        assert codes["NTD_FILL_SYNC_RETRY"] == "READY"

    @pytest.mark.asyncio
    async def test_non_trading_day_does_not_block_on_stale_sync(self) -> None:
        repos = build_in_memory_repositories()
        _seed_fill_sync_completed(repos, retries=1)
        _seed_stale_snapshot_sync(repos)
        _seed_market_session(repos, run_date=date(2026, 6, 3), is_trading_day=False)

        evaluator = NextTradingDayReadinessEvaluator(repos)
        result = await evaluator.evaluate(target_date=date(2026, 6, 3))

        assert result.overall_status == "READY"
        codes = {check.code: check.status for check in result.checks}
        assert codes["NTD_MARKET_SESSION"] == "READY"
        assert codes["NTD_SNAPSHOT_SYNC"] == "READY"
        assert codes["NTD_FILL_SYNC"] == "READY"

    @pytest.mark.asyncio
    async def test_build_persisted_summary_indexes_statuses(self) -> None:
        repos = build_in_memory_repositories()
        _seed_fill_sync_completed(repos, retries=1)
        _seed_market_session(repos, run_date=date(2026, 6, 3), is_trading_day=True)
        _add_order(repos, status=OrderStatus.SUBMITTED)

        evaluator = NextTradingDayReadinessEvaluator(repos)
        result = await evaluator.evaluate(target_date=date(2026, 6, 3))
        payload = _build_persisted_summary(result)

        assert payload["overall_status"] == "BLOCKED"
        assert payload["blocking_unresolved_count"] == 1
        assert "NTD_UNRESOLVED_BLOCKING" in payload["blocked_codes"]
