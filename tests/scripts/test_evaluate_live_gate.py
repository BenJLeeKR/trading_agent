"""Tests for ``scripts.evaluate_live_gate`` — Live Gate / Canary Readiness evaluation.

Test suites
===========
* :class:`TestDetermineOverall` — :meth:`LiveGateEvaluator._determine_overall` 유닛 테스트 (5 tests)
* :class:`TestLiveGateEvaluator` — :class:`LiveGateEvaluator` 통합 검증 (3 tests)
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
from scripts.evaluate_live_gate import (
    LiveGateCheck,
    LiveGateEvaluator,
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
# Helpers — LiveGateCheck 팩토리 (유닛 테스트용)
# ═══════════════════════════════════════════════════════════════════


def _make_check(code: str, layer: str, status: str) -> LiveGateCheck:
    """Construct a minimal ``LiveGateCheck`` for unit testing."""
    return LiveGateCheck(
        code=code,
        label=code,
        layer=layer,
        status=status,
        measured_value=None,
        threshold=None,
        message="",
    )


def _auto_checks(*statuses: str) -> list[LiveGateCheck]:
    """Build a list of auto ``LiveGateCheck``s with given statuses."""
    codes = [
        "LG_FILLED_ORDERS",
        "LG_MAX_DRAWDOWN",
        "LG_EXCESS_RETURN",
        "LG_WIN_RATE",
        "LG_RECENT_RECONCILE",
        "LG_RECENT_BLOCKING_LOCKS",
        "LG_READYZ",
        "LG_POST_SUBMIT_SYNC",
    ]
    return [
        _make_check(code=c, layer="auto", status=s)
        for c, s in zip(codes, statuses)
    ]


def _manual_checks(*statuses: str) -> list[LiveGateCheck]:
    """Build a list of manual ``LiveGateCheck``s with given statuses."""
    codes = [
        "LG_MANUAL_CREDENTIAL",
        "LG_MANUAL_ACCOUNT_MASKING",
        "LG_MANUAL_OPERATOR_APPROVAL",
        "LG_MANUAL_PAPER_LOG_REVIEW",
        "LG_MANUAL_RATE_LIMIT_REVIEW",
        "LG_MANUAL_FINAL_DECISION",
    ]
    return [
        _make_check(code=c, layer="manual", status=s)
        for c, s in zip(codes, statuses)
    ]


# ═══════════════════════════════════════════════════════════════════
# Helpers — Integration test seed data
# ═══════════════════════════════════════════════════════════════════


def _seed_base(repos: RepositoryContainer) -> None:
    """Seed minimal reference data (client, account, strategy, cash/position snapshots)."""
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


def _build_evaluator(
    repos: RepositoryContainer,
) -> LiveGateEvaluator:
    """Build a ``LiveGateEvaluator`` with default settings and benchmark repo."""
    settings = AppSettings()
    bench_price_repo = InMemoryBenchmarkPriceRepository(
        prices=_DEFAULT_BENCHMARK_PRICES,
    )
    return LiveGateEvaluator(
        repos=repos,
        settings=settings,
        benchmark_price_repo=bench_price_repo,
    )


# ═══════════════════════════════════════════════════════════════════
# _determine_overall — Unit Tests
# ═══════════════════════════════════════════════════════════════════


class TestDetermineOverall:
    """``LiveGateEvaluator._determine_overall()`` — 5가지 규칙 검증."""

    def test_blocked_paper_exit_fail(self) -> None:
        """Rule 1: Paper FAIL → BLOCKED."""
        overall, reason = LiveGateEvaluator._determine_overall(
            paper_exit_status="FAIL",
            live_checks=_auto_checks("PASS", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS"),
            manual_checks=_manual_checks("DONE", "DONE", "DONE", "DONE", "DONE", "DONE"),
        )
        assert overall == "BLOCKED", f"Expected BLOCKED, got {overall}: {reason}"

    def test_blocked_paper_exit_hold(self) -> None:
        """Rule 1: Paper HOLD → BLOCKED."""
        overall, reason = LiveGateEvaluator._determine_overall(
            paper_exit_status="HOLD",
            live_checks=_auto_checks("PASS", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS"),
            manual_checks=_manual_checks("DONE", "DONE", "DONE", "DONE", "DONE", "DONE"),
        )
        assert overall == "BLOCKED", f"Expected BLOCKED, got {overall}: {reason}"

    def test_blocked_live_auto_fail(self) -> None:
        """Rule 2: Paper PASS + auto FAIL → BLOCKED."""
        overall, reason = LiveGateEvaluator._determine_overall(
            paper_exit_status="PASS",
            live_checks=_auto_checks("FAIL", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS"),
            manual_checks=_manual_checks("DONE", "DONE", "DONE", "DONE", "DONE", "DONE"),
        )
        assert overall == "BLOCKED", f"Expected BLOCKED, got {overall}: {reason}"

    def test_hold_live_auto_warn(self) -> None:
        """Rule 3: Paper PASS + auto WARN → HOLD."""
        overall, reason = LiveGateEvaluator._determine_overall(
            paper_exit_status="PASS",
            live_checks=_auto_checks("PASS", "WARN", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS"),
            manual_checks=_manual_checks("DONE", "DONE", "DONE", "DONE", "DONE", "DONE"),
        )
        assert overall == "HOLD", f"Expected HOLD, got {overall}: {reason}"

    def test_hold_manual_pending(self) -> None:
        """Rule 4: Paper PASS + auto PASS + manual PENDING → HOLD."""
        overall, reason = LiveGateEvaluator._determine_overall(
            paper_exit_status="PASS",
            live_checks=_auto_checks("PASS", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS"),
            manual_checks=_manual_checks("PENDING", "PENDING", "PENDING", "PENDING", "PENDING", "PENDING"),
        )
        assert overall == "HOLD", f"Expected HOLD, got {overall}: {reason}"

    def test_ready_all_pass(self) -> None:
        """Rule 5: Paper PASS + auto PASS + manual DONE → READY."""
        overall, reason = LiveGateEvaluator._determine_overall(
            paper_exit_status="PASS",
            live_checks=_auto_checks("PASS", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS"),
            manual_checks=_manual_checks("DONE", "DONE", "DONE", "DONE", "DONE", "DONE"),
        )
        assert overall == "READY", f"Expected READY, got {overall}: {reason}"


# ═══════════════════════════════════════════════════════════════════
# LiveGateEvaluator — Integration Tests
# ═══════════════════════════════════════════════════════════════════


class TestLiveGateEvaluator:
    """``LiveGateEvaluator`` — 통합 검증 (3 tests)."""

    @pytest.mark.asyncio
    async def test_integration_run(self) -> None:
        """12건 체결 + fresh sync → Paper PASS, live auto 평가 정상 동작 확인."""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        for _ in range(12):
            _add_filled_order(repos)

        evaluator = _build_evaluator(repos)

        pe_status, pe_auto = await evaluator.evaluate_paper_exit(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        assert pe_status == "PASS", f"Paper exit should PASS, got {pe_status}"

        live_checks = await evaluator.evaluate_live_auto(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        # LG_FILLED_ORDERS: 12 >= 10 → PASS
        filled_check = next((c for c in live_checks if c.code == "LG_FILLED_ORDERS"), None)
        assert filled_check is not None
        assert filled_check.status == "PASS", (
            f"LG_FILLED_ORDERS should PASS with 12 orders, got {filled_check.status}"
        )
        # LG_EXCESS_RETURN: benchmark 없으므로 WARN
        excess_check = next((c for c in live_checks if c.code == "LG_EXCESS_RETURN"), None)
        assert excess_check is not None
        assert excess_check.status == "WARN", (
            f"LG_EXCESS_RETURN should WARN without benchmark, got {excess_check.status}"
        )

    @pytest.mark.asyncio
    async def test_integration_output_text(self) -> None:
        """Text 출력에 모든 섹션이 포함되는지 확인."""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        for _ in range(12):
            _add_filled_order(repos)

        evaluator = _build_evaluator(repos)

        pe_status, pe_auto = await evaluator.evaluate_paper_exit(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        live_checks = await evaluator.evaluate_live_auto(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        manual_checks = evaluator.build_manual_template(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        overall, reason = evaluator._determine_overall(
            paper_exit_status=pe_status,
            live_checks=live_checks,
            manual_checks=manual_checks,
        )

        text = evaluator.to_text(
            paper_exit_status=pe_status,
            paper_exit_auto=pe_auto,
            live_checks=live_checks,
            manual_checks=manual_checks,
            overall_status=overall,
            summary_reason=reason,
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )

        assert "Live Gate" in text
        assert "Paper Exit Status" in text
        assert "Live-Specific Auto Checks" in text
        assert "Manual Checks" in text
        assert "Overall:" in text
        assert len(text) > 100

    @pytest.mark.asyncio
    async def test_integration_output_json(self) -> None:
        """JSON 출력 구조 검증."""
        repos = build_in_memory_repositories()
        _seed_base(repos)
        for _ in range(12):
            _add_filled_order(repos)

        evaluator = _build_evaluator(repos)

        pe_status, pe_auto = await evaluator.evaluate_paper_exit(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        live_checks = await evaluator.evaluate_live_auto(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        manual_checks = evaluator.build_manual_template(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        overall, reason = evaluator._determine_overall(
            paper_exit_status=pe_status,
            live_checks=live_checks,
            manual_checks=manual_checks,
        )

        json_str = evaluator.to_json(
            paper_exit_status=pe_status,
            paper_exit_auto=pe_auto,
            live_checks=live_checks,
            manual_checks=manual_checks,
            overall_status=overall,
            summary_reason=reason,
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )

        doc = json.loads(json_str)
        assert "metadata" in doc
        assert doc["metadata"]["evaluation_type"] == "live_gate"
        assert doc["metadata"]["overall"] in ("READY", "HOLD", "BLOCKED")
        assert doc["paper_exit"]["status"] in ("PASS", "HOLD", "FAIL")
        assert "auto_checks" in doc["live_gate"]
        assert "manual_checks" in doc["live_gate"]
        assert "auto_summary" in doc["live_gate"]
        assert "manual_summary" in doc["live_gate"]
        assert len(doc["live_gate"]["auto_checks"]) == 8
        assert len(doc["live_gate"]["manual_checks"]) == 6

    @pytest.mark.asyncio
    async def test_manual_template_output(self) -> None:
        """``build_manual_template()`` — 6개 PENDING 항목 반환 확인."""
        repos = build_in_memory_repositories()
        evaluator = _build_evaluator(repos)

        manual = evaluator.build_manual_template(
            account_id=_ACCOUNT_ID,
            start_date=_START,
            end_date=_END,
        )
        assert len(manual) == 6, f"Expected 6 manual checks, got {len(manual)}"
        assert all(c.layer == "manual" for c in manual), "All must be manual layer"
        assert all(c.status == "PENDING" for c in manual), "All must be PENDING"
        codes = [c.code for c in manual]
        expected = [
            "LG_MANUAL_CREDENTIAL",
            "LG_MANUAL_ACCOUNT_MASKING",
            "LG_MANUAL_OPERATOR_APPROVAL",
            "LG_MANUAL_PAPER_LOG_REVIEW",
            "LG_MANUAL_RATE_LIMIT_REVIEW",
            "LG_MANUAL_FINAL_DECISION",
        ]
        assert codes == expected, f"Unexpected codes: {codes}"
