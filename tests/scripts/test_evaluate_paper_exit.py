"""Tests for ``scripts.evaluate_paper_exit`` — Paper Exit Criteria evaluation.

Test suites
===========
* :class:`TestPaperExitEvaluator` — :class:`PaperExitEvaluator` 통합 검증 (7 tests)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.config.settings import AppSettings
from agent_trading.domain.entities import (
    AccountEntity,
    CashBalanceSnapshotEntity,
    ClientEntity,
    FillEventEntity,
    BrokerOrderEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
    SnapshotSyncRunEntity,
    StrategyEntity,
)
from agent_trading.domain.enums import (
    AssetClass,
    Environment,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.benchmark_comparison import (
    InMemoryBenchmarkPriceRepository,
    _DEFAULT_BENCHMARK_PRICES,
)
from scripts.evaluate_paper_exit import (
    AutoCheckResult,
    FinalOverall,
    LayerAResult,
    LayerBResult,
    LayerCResult,
    ManualCheckResult,
    PaperExitEvaluator,
    SemiCheckResult,
)


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

_ACCOUNT_ID = UUID("11111111-1111-1111-1111-111111111111")
_CLIENT_ID = UUID("33333333-3333-3333-3333-333333333333")
_STRATEGY_ID = UUID("22222222-2222-2222-2222-222222222222")
_NOW = datetime(2026, 5, 8, 15, 30, 0, tzinfo=timezone.utc)
_START = date(2026, 5, 1)
_END = date(2026, 5, 8)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _add_equity_snapshots(repos: RepositoryContainer) -> None:
    """Add cash snapshots for sufficient equity history (risk metric computation).

    ``_seed_base()`` creates only 1 cash snapshot, which with BUY-only orders
    produces 0 starting_equity and <2 daily returns → risk metrics are ``None``.
    This helper adds snapshots so Sharpe/Sortino/Calmar are valid (non-None).
    """
    snapshots: list[tuple[datetime, str]] = [
        (_NOW - timedelta(days=9), "10000000"),  # Apr 29: starting_equity
        (_NOW - timedelta(days=7), "10000000"),  # May 1: range start
        (_NOW - timedelta(days=4), "9500000"),   # May 4: equity decline
        (_NOW - timedelta(days=2), "9200000"),   # May 6: further decline
    ]
    for ts, cash in snapshots:
        repos.cash_balance_snapshots._items[uuid4()] = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=_ACCOUNT_ID,
            currency="KRW",
            available_cash=Decimal(cash),
            settled_cash=Decimal(cash),
            unsettled_cash=Decimal("0"),
            source_of_truth="test",
            snapshot_at=ts,
        )


def _seed_base(repos: RepositoryContainer) -> None:
    """Seed minimal reference data."""
    repos.clients._items[_CLIENT_ID] = ClientEntity(
        client_id=_CLIENT_ID,
        client_code="TEST",
        name="Test Client",
        status="active",
    )
    repos.accounts._items[_ACCOUNT_ID] = AccountEntity(
        account_id=_ACCOUNT_ID,
        client_id=_CLIENT_ID,
        broker_account_id=uuid4(),
        environment=Environment.PAPER,
        account_alias="Test Paper",
        account_masked="TEST-****",
        status="active",
    )
    repos.strategies._items[_STRATEGY_ID] = StrategyEntity(
        strategy_id=_STRATEGY_ID,
        client_id=_CLIENT_ID,
        strategy_code="TEST_STRAT",
        name="Test Strategy",
        asset_class=AssetClass.KR_STOCK,
        status="active",
    )
    # Cash snapshot (10M starting cash)
    repos.cash_balance_snapshots._items[uuid4()] = CashBalanceSnapshotEntity(
        cash_balance_snapshot_id=uuid4(),
        account_id=_ACCOUNT_ID,
        currency="KRW",
        available_cash=Decimal("10000000"),
        settled_cash=Decimal("10000000"),
        unsettled_cash=Decimal("0"),
        source_of_truth="test",
        snapshot_at=_NOW - timedelta(days=1),
    )
    # Empty position snapshot
    repos.position_snapshots._items[uuid4()] = PositionSnapshotEntity(
        position_snapshot_id=uuid4(),
        account_id=_ACCOUNT_ID,
        instrument_id=uuid4(),
        quantity=Decimal("0"),
        average_price=Decimal("0"),
        market_price=None,
        unrealized_pnl=None,
        source_of_truth="test",
        snapshot_at=_NOW - timedelta(days=1),
    )


def _add_filled_order(
    repos: RepositoryContainer,
    side: OrderSide = OrderSide.BUY,
    quantity: str = "10",
    price: str = "50000",
    fill_timestamp: datetime | None = None,
) -> None:
    """Add a filled order with broker order + fill event."""
    order_id = uuid4()
    broker_order_id = uuid4()
    ts = fill_timestamp or _NOW

    order = OrderRequestEntity(
        order_request_id=order_id,
        account_id=_ACCOUNT_ID,
        instrument_id=uuid4(),
        client_order_id=f"CLI-{order_id}",
        idempotency_key=f"IDEM-{order_id}",
        correlation_id=f"CORR-{order_id}",
        side=side,
        order_type=OrderType.MARKET,
        requested_quantity=Decimal(quantity),
        requested_price=Decimal(price),
        status=OrderStatus.FILLED,
        time_in_force=TimeInForce.DAY,
        decision_context_id=uuid4(),
        submitted_at=ts,
    )
    repos.orders._items[order_id] = order

    bo = BrokerOrderEntity(
        broker_order_id=broker_order_id,
        order_request_id=order_id,
        broker_name="test",
        broker_status="FILLED",
        broker_native_order_id=f"NATIVE-{order_id}",
    )
    repos.broker_orders._items[broker_order_id] = bo

    fill = FillEventEntity(
        fill_event_id=uuid4(),
        broker_order_id=broker_order_id,
        fill_timestamp=ts,
        fill_price=Decimal(price),
        fill_quantity=Decimal(quantity),
        source_channel="test",
        fill_fee=Decimal("0"),
        fill_tax=Decimal("0"),
    )
    repos.fill_events._items[fill.fill_event_id] = fill


def _add_fresh_sync_run(repos: RepositoryContainer) -> None:
    """Add a recent successful snapshot sync run."""
    run = SnapshotSyncRunEntity(
        snapshot_sync_run_id=uuid4(),
        trigger_type="scheduler",
        scope="all",
        dry_run=False,
        total_accounts=1,
        succeeded_accounts=1,
        partial_accounts=0,
        failed_accounts=0,
        skipped_accounts=0,
        positions_synced_total=5,
        positions_skipped_total=0,
        cash_synced_count=1,
        error_count=0,
        status="completed",
        started_at=_NOW - timedelta(minutes=5),
        completed_at=_NOW,
        env_filter=None,
        status_filter=None,
    )
    repos.snapshot_sync_runs._items[run.snapshot_sync_run_id] = run


def _add_stale_sync_run(repos: RepositoryContainer) -> None:
    """Add a very old sync run → stale."""
    run = SnapshotSyncRunEntity(
        snapshot_sync_run_id=uuid4(),
        trigger_type="scheduler",
        scope="all",
        dry_run=False,
        total_accounts=1,
        succeeded_accounts=1,
        partial_accounts=0,
        failed_accounts=0,
        skipped_accounts=0,
        positions_synced_total=5,
        positions_skipped_total=0,
        cash_synced_count=1,
        error_count=0,
        status="completed",
        started_at=_NOW - timedelta(hours=24),
        completed_at=_NOW - timedelta(hours=24),
        env_filter=None,
        status_filter=None,
    )
    repos.snapshot_sync_runs._items[run.snapshot_sync_run_id] = run


# ═══════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════


class TestPaperExitEvaluator:
    """``PaperExitEvaluator`` — 통합 검증."""

    # ------------------------------------------------------------------
    # 1. PASS — 모든 조건 충족
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_all_pass_returns_pass(self) -> None:
        """모든 지표 양호, Gate GO, semi not_run → HOLD (수동 대기)"""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        _add_equity_snapshots(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_fresh_sync_run(repos)

        settings = AppSettings()
        evaluator = PaperExitEvaluator(repos=repos, settings=settings)

        auto = await evaluator.evaluate_auto(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        semi = await evaluator.evaluate_semi(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
            run_semi=False,
        )
        manual = evaluator.build_manual_template(auto_result=auto, semi_result=semi)
        overall = PaperExitEvaluator._determine_overall(auto, semi, manual)

        # Layer A: Auto all pass
        assert auto.status == "PASS", f"Expected PASS, got {auto.status}"
        assert all(c.status == "PASS" for c in auto.checks), (
            f"Some auto checks not PASS: {[c.code for c in auto.checks if c.status != 'PASS']}"
        )

        # Layer B: CHECK due to NOT_RUN items
        assert semi.status == "CHECK", f"Expected CHECK, got {semi.status}"
        not_run = [c for c in semi.checks if c.status == "NOT_RUN"]
        assert len(not_run) >= 3, f"Expected ≥3 NOT_RUN, got {len(not_run)}"

        # Layer C: PENDING
        assert manual.status == "PENDING"

        # Overall: HOLD (수동 미완료)
        assert overall.status == "HOLD", f"Expected HOLD, got {overall.status}"
        assert overall.exit_code == 1

    # ------------------------------------------------------------------
    # 2. HOLD — Layer A PASS, Layer B FAIL (with --run-semi mock)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_semi_fail_returns_hold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Layer A는 PASS, Layer B에 FAIL → HOLD"""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        _add_equity_snapshots(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_fresh_sync_run(repos)

        settings = AppSettings()
        evaluator = PaperExitEvaluator(repos=repos, settings=settings)

        auto = await evaluator.evaluate_auto(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        # Force Layer B FAIL by injecting a FAIL check
        semi = LayerBResult(
            status="FAIL",
            checks=[
                SemiCheckResult(
                    code="SERVICE_TESTS",
                    status="FAIL",
                    detail="mock failure: 1 test failed",
                ),
                SemiCheckResult(
                    code="SNAPSHOT_SYNC_SCHEDULER",
                    status="OK",
                    detail="snapshot_sync fresh",
                ),
            ],
        )
        manual = evaluator.build_manual_template(auto_result=auto, semi_result=semi)
        overall = PaperExitEvaluator._determine_overall(auto, semi, manual)

        assert auto.status == "PASS"
        assert semi.status == "FAIL"
        assert overall.status == "HOLD"
        assert overall.exit_code == 1

    # ------------------------------------------------------------------
    # 3. FAIL — Gate NO_GO (채결 건수 미달로 FAIL 유도)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_insufficient_orders_returns_fail(self) -> None:
        """MIN_FILLED_ORDERS 미달 → Gate FAIL → 최종 FAIL"""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        # 1 order only (min_filled_orders default = 3) → FAIL
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))

        # 최근 sync run
        now = datetime.now(timezone.utc)
        fresh_run = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="scheduler",
            scope="all",
            dry_run=False,
            total_accounts=1,
            succeeded_accounts=1,
            partial_accounts=0,
            failed_accounts=0,
            skipped_accounts=0,
            positions_synced_total=5,
            positions_skipped_total=0,
            cash_synced_count=1,
            error_count=0,
            status="completed",
            started_at=now - timedelta(minutes=5),
            completed_at=now,
            env_filter=None,
            status_filter=None,
        )
        repos.snapshot_sync_runs._items[fresh_run.snapshot_sync_run_id] = fresh_run

        settings = AppSettings()
        evaluator = PaperExitEvaluator(repos=repos, settings=settings)

        auto = await evaluator.evaluate_auto(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        semi = await evaluator.evaluate_semi(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
            run_semi=False,
        )
        manual = evaluator.build_manual_template(auto_result=auto, semi_result=semi)
        overall = PaperExitEvaluator._determine_overall(auto, semi, manual)

        assert auto.status == "FAIL", f"Expected FAIL, got {auto.status}"
        orders_check = next(c for c in auto.checks if c.code == "MIN_FILLED_ORDERS")
        assert orders_check.status == "FAIL"

        # Rule 1: Layer A FAIL → overall FAIL
        assert overall.status == "FAIL", f"Expected FAIL, got {overall.status}"
        assert overall.exit_code == 2

    # ------------------------------------------------------------------
    # 4. FAIL — Snapshot stale
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_stale_snapshot_fail(self) -> None:
        """Snapshot stale → SNAPSHOT_FRESHNESS FAIL → 최종 FAIL"""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))

        # build_in_memory_repositories()가 seed한 fresh sync run 제거
        repos.snapshot_sync_runs._items.clear()

        # 오래된 sync run (실제 현재 시간 기준 24h 전 → stale)
        now = datetime.now(timezone.utc)
        stale_run = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="scheduler",
            scope="all",
            dry_run=False,
            total_accounts=1,
            succeeded_accounts=1,
            partial_accounts=0,
            failed_accounts=0,
            skipped_accounts=0,
            positions_synced_total=5,
            positions_skipped_total=0,
            cash_synced_count=1,
            error_count=0,
            status="completed",
            started_at=now - timedelta(hours=24),
            completed_at=now - timedelta(hours=24),
            env_filter=None,
            status_filter=None,
        )
        repos.snapshot_sync_runs._items[stale_run.snapshot_sync_run_id] = stale_run

        settings = AppSettings()
        evaluator = PaperExitEvaluator(repos=repos, settings=settings)

        auto = await evaluator.evaluate_auto(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        semi = await evaluator.evaluate_semi(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
            run_semi=False,
        )
        manual = evaluator.build_manual_template(auto_result=auto, semi_result=semi)
        overall = PaperExitEvaluator._determine_overall(auto, semi, manual)

        assert auto.status == "FAIL", f"Expected FAIL, got {auto.status}"

        # SNAPSHOT_FRESHNESS should FAIL from Gate
        freshness_check = next(c for c in auto.checks if c.code == "SNAPSHOT_FRESHNESS")
        assert freshness_check.status == "FAIL", (
            f"Expected SNAPSHOT_FRESHNESS FAIL, got {freshness_check.status}"
        )

        # HEALTH_ENDPOINT should also FAIL (stale)
        health_check = next(c for c in auto.checks if c.code == "HEALTH_ENDPOINT")
        assert health_check.status == "FAIL", (
            f"Expected HEALTH_ENDPOINT FAIL, got {health_check.status}"
        )

        # READYZ_ENDPOINT should be WARN (degraded → HOLD)
        readyz_check = next(c for c in auto.checks if c.code == "READYZ_ENDPOINT")
        assert readyz_check.status == "WARN", (
            f"Expected READYZ_ENDPOINT WARN, got {readyz_check.status}"
        )

        assert overall.status == "FAIL"
        assert overall.exit_code == 2

    # ------------------------------------------------------------------
    # 5. JSON 출력 검증
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_json_output_format(self) -> None:
        """JSON 출력 스키마 정합성 검증"""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_fresh_sync_run(repos)

        settings = AppSettings()
        evaluator = PaperExitEvaluator(
            repos=repos,
            settings=settings,
            benchmark_price_repo=InMemoryBenchmarkPriceRepository(
                prices=_DEFAULT_BENCHMARK_PRICES,
            ),
        )

        auto = await evaluator.evaluate_auto(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
            benchmark_code="KOSPI",
        )
        semi = await evaluator.evaluate_semi(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
            run_semi=False,
        )
        manual = evaluator.build_manual_template(auto_result=auto, semi_result=semi)

        json_str = evaluator.to_json(
            auto=auto,
            semi=semi,
            manual=manual,
            overall=PaperExitEvaluator._determine_overall(auto, semi, manual),
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
            strategy_id=_STRATEGY_ID,
            benchmark_code="KOSPI",
        )

        parsed = json.loads(json_str)

        # Check metadata
        assert parsed["metadata"]["account_id"] == str(_ACCOUNT_ID)
        assert parsed["metadata"]["start_date"] == _START.isoformat()
        assert parsed["metadata"]["end_date"] == _END.isoformat()
        assert parsed["metadata"]["benchmark_code"] == "KOSPI"
        assert "overall" in parsed["metadata"]
        assert "exit_code" in parsed["metadata"]

        # Check layers structure
        assert "layers" in parsed
        assert "auto" in parsed["layers"]
        assert "semi" in parsed["layers"]
        assert "manual" in parsed["layers"]

        # Check auto checks have required fields
        for check in parsed["layers"]["auto"]["checks"]:
            assert "code" in check
            assert "status" in check
            assert "message" in check

        # Check semi checks have required fields
        for check in parsed["layers"]["semi"]["checks"]:
            assert "code" in check
            assert "status" in check
            assert "detail" in check

        # Check manual checks have required fields
        for check in parsed["layers"]["manual"]["checks"]:
            assert "code" in check
            assert "label" in check
            assert "checklist" in check
            assert "status" in check

    # ------------------------------------------------------------------
    # 6. Manual Template 출력 검증
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_manual_template_output(self) -> None:
        """Manual checklist 마크다운 템플릿 형식 검증"""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_fresh_sync_run(repos)

        settings = AppSettings()
        evaluator = PaperExitEvaluator(repos=repos, settings=settings)

        auto = await evaluator.evaluate_auto(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        semi = await evaluator.evaluate_semi(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
            run_semi=False,
        )
        manual = evaluator.build_manual_template(auto_result=auto, semi_result=semi)
        overall = PaperExitEvaluator._determine_overall(auto, semi, manual)

        template = evaluator.to_manual_template(
            auto=auto,
            semi=semi,
            manual=manual,
            overall=overall,
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )

        # Verify template structure
        assert "# Paper Exit Criteria — Manual Checklist" in template
        assert f"Account ID: `{_ACCOUNT_ID}`" in template
        assert f"Period: {_START.isoformat()} ~ {_END.isoformat()}" in template
        assert "## Layer A: Auto" in template
        assert "## Layer B: Semi-Auto" in template
        assert "## Layer C: Manual Verification" in template
        assert "BROKER_SUBMIT_SMOKE" in template
        assert "PIPELINE_ERROR_RATE" in template
        assert "RECONCILIATION_DEGRADE" in template
        assert "AUDIT_LOG_CONTINUITY" in template
        assert "FINAL_OPERATOR_DECISION" in template
        assert "- [ ]" in template  # Checklist format
        assert "Decision: GO / NO-GO" in template

    # ------------------------------------------------------------------
    # 7. Layer B NOT_RUN 상태 검증
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_semi_not_run_without_flag(self) -> None:
        """--run-semi 없이 실행 시 B1~B3/B5가 NOT_RUN"""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_fresh_sync_run(repos)

        settings = AppSettings()
        evaluator = PaperExitEvaluator(repos=repos, settings=settings)

        semi = await evaluator.evaluate_semi(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
            run_semi=False,
        )

        # B1, B2, B3, B5 should be NOT_RUN
        not_run_codes = [
            c.code for c in semi.checks if c.status == "NOT_RUN"
        ]
        assert "SERVICE_TESTS" in not_run_codes
        assert "VERIFY_PAPER_LOOP" in not_run_codes
        assert "DECISION_LOOP_DRY" in not_run_codes
        assert "TEST_SUITE_DETAIL" in not_run_codes

        # B4 should be OK or CHECK (always evaluated)
        b4 = next(c for c in semi.checks if c.code == "SNAPSHOT_SYNC_SCHEDULER")
        assert b4.status in ("OK", "CHECK")
    # ------------------------------------------------------------------
    # 8. READYZ_ENDPOINT WARN 검증 (degraded → HOLD)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_readyz_degraded_warns(self) -> None:
        """Stale snapshot → HEALTH_ENDPOINT FAIL, READYZ_ENDPOINT WARN"""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))

        # build_in_memory_repositories()가 seed한 fresh sync run 제거
        repos.snapshot_sync_runs._items.clear()

        # 오래된 sync run (실제 현재 시간 기준 24h 전 → stale)
        now = datetime.now(timezone.utc)
        stale_run = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="scheduler",
            scope="all",
            dry_run=False,
            total_accounts=1,
            succeeded_accounts=1,
            partial_accounts=0,
            failed_accounts=0,
            skipped_accounts=0,
            positions_synced_total=5,
            positions_skipped_total=0,
            cash_synced_count=1,
            error_count=0,
            status="completed",
            started_at=now - timedelta(hours=24),
            completed_at=now - timedelta(hours=24),
            env_filter=None,
            status_filter=None,
        )
        repos.snapshot_sync_runs._items[stale_run.snapshot_sync_run_id] = stale_run

        settings = AppSettings()
        evaluator = PaperExitEvaluator(repos=repos, settings=settings)

        auto = await evaluator.evaluate_auto(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )

        # HEALTH_ENDPOINT should be FAIL
        health = next(c for c in auto.checks if c.code == "HEALTH_ENDPOINT")
        assert health.status == "FAIL", f"Expected FAIL, got {health.status}"

        # READYZ_ENDPOINT should be WARN (degraded → HOLD)
        readyz = next(c for c in auto.checks if c.code == "READYZ_ENDPOINT")
        assert readyz.status == "WARN", f"Expected WARN, got {readyz.status}"

    # ------------------------------------------------------------------
    # 9. Layer A 자동 확장 — risk-adjusted check 포함 (new)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_auto_includes_risk_checks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """evaluate_auto() 결과에 MIN_SHARPE_RATIO/MIN_SORTINO_RATIO/MIN_CALMAR_RATIO 포함"""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=3))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=2))
        _add_filled_order(repos, OrderSide.BUY, fill_timestamp=_NOW - timedelta(days=1))
        _add_fresh_sync_run(repos)

        # BUY orders → negative risk metrics; override thresholds so they PASS
        monkeypatch.setenv("PAPER_GATE_MIN_SHARPE_RATIO", "-99")
        monkeypatch.setenv("PAPER_GATE_MIN_SORTINO_RATIO", "-99")
        monkeypatch.setenv("PAPER_GATE_MIN_CALMAR_RATIO", "-99")

        settings = AppSettings()
        evaluator = PaperExitEvaluator(repos=repos, settings=settings)

        auto = await evaluator.evaluate_auto(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )

        codes = {c.code for c in auto.checks}
        for code in ("MIN_SHARPE_RATIO", "MIN_SORTINO_RATIO", "MIN_CALMAR_RATIO"):
            assert code in codes, (
                f"Expected {code} in Layer A checks, got codes={codes}"
            )
