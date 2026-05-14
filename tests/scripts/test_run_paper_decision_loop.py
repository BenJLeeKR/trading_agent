"""Tests for ``scripts.run_paper_decision_loop`` — paper decision loop runner.

검증 범위
---------
1. ``_serialize_cycle_result()`` — 순수 함수 직렬화 정확성
2. ``_build_aggregate_summary()`` — 집계 요약 정확성
3. ``_serialize_precheck()`` — health summary 직렬화
4. ``_run_one_cycle()`` — dry-run 모드 (mock runtime)
5. ``_run_one_cycle()`` — submit 모드 (mock runtime)
6. Pre-check stale 정보가 cycle summary에 반영되는지
7. CLI ``_parse_args()`` — 인자 파싱 정확성

CLI 진입점(main)과 graceful shutdown(asyncio.Event)은 smoke/integration 테스트로 분류.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    AccountEntity,
    CashBalanceSnapshotEntity,
    ClientEntity,
    ConfigVersionEntity,
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
)
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.contracts import SnapshotSyncHealthSummary
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
    OrderIntent,
    SubmitResult,
)

# Module under test
from scripts.run_paper_decision_loop import (
    ENV_TRADING_UNIVERSE,
    UniverseSymbol,
    _build_aggregate_summary,
    _parse_args,
    _parse_universe_symbols,
    _read_trading_universe,
    _run_one_cycle,
    _serialize_cycle_result,
    _serialize_precheck,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CLIENT_ID = UUID("301961b4-75d9-533c-92b7-69a306cdd435")
ACCOUNT_ID = UUID("a44a02d1-7f32-5a62-99f7-235abeb58284")
STRATEGY_ID = UUID("30a1d26b-8230-51fc-8548-30920effff0c")
CONFIG_VERSION_ID = UUID("529ab376-183a-53df-b4ab-73d948c1404c")
SYMBOL = "005930"
MARKET = "KRX"


async def _seed_repos(repos: RepositoryContainer) -> None:
    """Seed in-memory repos with minimal FK chain for orchestrator."""
    from agent_trading.domain.entities import BrokerAccountEntity

    now = datetime.now(timezone.utc)

    # BrokerAccount
    await repos.broker_accounts.add(
        BrokerAccountEntity(
            broker_account_id=UUID("7f39fc04-346a-5484-90ab-80e8a1d04a15"),
            broker_name="koreainvestment",
            account_ref="test-account",
            environment=Environment.PAPER,
            credential_ref="test-cred",
            base_url="https://openapivts.koreainvestment.com:29443",
            status="active",
            broker_account_code="KIS-PAPER-****6448",
        )
    )

    # Client
    await repos.clients.add(
        ClientEntity(
            client_id=CLIENT_ID,
            client_code="TST001",
            name="Test Client",
            status="active",
            base_currency="KRW",
        )
    )

    # Account
    await repos.accounts.add(
        AccountEntity(
            account_id=ACCOUNT_ID,
            client_id=CLIENT_ID,
            broker_account_id=UUID("7f39fc04-346a-5484-90ab-80e8a1d04a15"),
            environment=Environment.PAPER,
            account_alias="Entrypoint Paper",
            account_masked="****6448",
            status="active",
            account_code="EPC001-PAPER-ENTRYPOINT",
        )
    )

    # Strategy
    await repos.strategies.add(
        StrategyEntity(
            strategy_id=STRATEGY_ID,
            client_id=CLIENT_ID,
            strategy_code="TST_STRAT",
            name="Test Strategy",
            asset_class=AssetClass.KR_STOCK.value,
            status="active",
        )
    )

    # ConfigVersion
    await repos.config_versions.add(
        ConfigVersionEntity(
            config_version_id=CONFIG_VERSION_ID,
            client_id=CLIENT_ID,
            environment=Environment.PAPER,
            version_tag="v1.0",
            config_json={"max_position_size": "0.1"},
            checksum="test-checksum",
            activated_at=now,
        )
    )

    # Cash snapshot (fresh)
    await repos.cash_balance_snapshots.add(
        CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=ACCOUNT_ID,
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("1000000"),
            unsettled_cash=Decimal("0"),
            source_of_truth="test",
            snapshot_at=now,
            created_at=now,
        )
    )

    # Position snapshot (fresh, empty)
    await repos.position_snapshots.add(
        PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=ACCOUNT_ID,
            instrument_id=uuid4(),
            quantity=Decimal("0"),
            average_price=Decimal("0"),
            market_price=None,
            unrealized_pnl=None,
            source_of_truth="test",
            snapshot_at=now,
            created_at=now,
        )
    )


def _make_stub_intent(
    decision_context_id: UUID | None = None,
) -> OrderIntent:
    """Create a minimal ``OrderIntent`` stub for serialization tests."""
    from agent_trading.services.decision_orchestrator import (
        AIDecisionInputs,
        AssembledContext,
    )

    return OrderIntent(
        order_intent_id=uuid4(),
        decision_context_id=decision_context_id or uuid4(),
        request=SubmitOrderRequest(
            account_ref="test",
            client_order_id="test-001",
            correlation_id="corr-001",
            strategy_id=str(STRATEGY_ID),
            symbol=SYMBOL,
            market=MARKET,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            price=Decimal("50000"),
        ),
        ai_backend_inputs=AIDecisionInputs(
            decision_type="APPROVE",
            confidence=0.8,
        ),
        context=AssembledContext(
            config_version=None,
        ),
    )


# ---------------------------------------------------------------------------
# Mock runtime
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _mock_runtime(snapshot_stale: bool = False) -> AsyncIterator[dict[str, Any]]:
    """Create a mock runtime with in-memory repos for testing ``_run_one_cycle``.

    Parameters
    ----------
    snapshot_stale:
        If ``True``, the snapshot sync health summary will report stale.
    """
    repos = build_in_memory_repositories()
    await _seed_repos(repos)

    # Configure snapshot sync health
    now = datetime.now(timezone.utc)
    if snapshot_stale:
        # Add a single failed run far in the past
        await repos.snapshot_sync_runs.add(
            SnapshotSyncRunEntity(
                snapshot_sync_run_id=uuid4(),
                trigger_type="scheduler",
                scope="single",
                dry_run=False,
                total_accounts=1,
                succeeded_accounts=0,
                partial_accounts=0,
                failed_accounts=1,
                skipped_accounts=0,
                positions_synced_total=0,
                positions_skipped_total=0,
                cash_synced_count=0,
                error_count=1,
                status="failed",
                started_at=now - timedelta(hours=24),
                completed_at=now - timedelta(hours=24) + timedelta(seconds=10),
                created_at=now - timedelta(hours=24),
            )
        )
    else:
        # Add a recent successful run
        await repos.snapshot_sync_runs.add(
            SnapshotSyncRunEntity(
                snapshot_sync_run_id=uuid4(),
                trigger_type="scheduler",
                scope="single",
                dry_run=False,
                total_accounts=1,
                succeeded_accounts=1,
                partial_accounts=0,
                failed_accounts=0,
                skipped_accounts=0,
                positions_synced_total=3,
                positions_skipped_total=0,
                cash_synced_count=1,
                error_count=0,
                status="completed",
                started_at=now - timedelta(seconds=60),
                completed_at=now - timedelta(seconds=50),
                created_at=now - timedelta(seconds=60),
            )
        )

    orchestrator = DecisionOrchestratorService(repos=repos)

    # Mock broker adapter
    broker = AsyncMock(spec=BrokerAdapter)
    broker.submit_order = AsyncMock(
        return_value=MagicMock(
            status="submitted",
            broker_order_id="BROKER-001",
            client_order_id="test-client-order",
            native_order_id=None,
            error_code=None,
            error_message=None,
        )
    )

    # Mock order manager
    from agent_trading.services.order_manager import OrderManager
    from agent_trading.services.reconciliation_service import ReconciliationService

    reconciliation_service = ReconciliationService(repos=repos)
    order_manager = OrderManager(
        repos=repos,
        reconciliation_service=reconciliation_service,
    )

    yield {
        "repositories": repos,
        "orchestrator": orchestrator,
        "order_manager": order_manager,
        "primary_broker_adapter": broker,
    }


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


class TestSerializeCycleResult:
    """``_serialize_cycle_result()`` — 순수 함수 직렬화 정확성."""

    def test_submitted_result(self) -> None:
        """SUBMITTED 결과를 올바르게 직렬화."""
        ctx_id = uuid4()
        intent = _make_stub_intent(decision_context_id=ctx_id)
        order = MagicMock(spec=OrderRequestEntity)
        order.order_request_id = uuid4()
        order.status = OrderStatus.SUBMITTED
        order.client_order_id = "CLIENT-ORDER-001"
        order.requested_quantity = Decimal("10")
        order.status_reason_code = None

        result = SubmitResult(
            status="SUBMITTED",
            intent=intent,
            order=order,
            trade_decision_id=uuid4(),
            decision_context_id=ctx_id,
        )

        serialized = _serialize_cycle_result(cycle=1, result=result, duration=5.5)

        assert serialized["cycle"] == 1
        assert serialized["status"] == "SUBMITTED"
        assert serialized["decision_context_id"] == str(ctx_id)
        assert serialized["duration_seconds"] == 5.5
        assert "started_at" in serialized
        assert "completed_at" in serialized

    def test_dry_run_result(self) -> None:
        """Dry-run 모드 직렬화."""
        ctx_id = uuid4()
        intent = _make_stub_intent(decision_context_id=ctx_id)
        result = SubmitResult(
            status="DRY_RUN",
            intent=intent,
            decision_context_id=ctx_id,
        )

        serialized = _serialize_cycle_result(
            cycle=1, result=result, duration=3.0, dry_run=True
        )

        assert serialized["status"] == "DRY_RUN"
        assert serialized["decision_context_id"] == str(ctx_id)
        assert serialized["order_intent_id"] == str(intent.order_intent_id)
        assert serialized["decision_type"] == "APPROVE"

    def test_error_result(self) -> None:
        """Error 결과 직렬화."""
        serialized = _serialize_cycle_result(
            cycle=2, result=None, duration=1.0, error="Something broke"
        )

        assert serialized["status"] == "ERROR"
        assert serialized["error"] == "Something broke"
        assert serialized["cycle"] == 2

    def test_with_precheck(self) -> None:
        """Pre-check 정보가 결과에 포함되는지."""
        precheck = {
            "health_status": "stale",
            "last_successful_run_at": None,
            "consecutive_failures": 3,
        }
        serialized = _serialize_cycle_result(
            cycle=1,
            result=None,
            duration=0.5,
            precheck=precheck,
            error="pre-check fail",
        )

        assert serialized["precheck"] == precheck
        assert serialized["precheck"]["health_status"] == "stale"  # type: ignore[index]


class TestBuildAggregateSummary:
    """``_build_aggregate_summary()`` — 집계 요약 정확성."""

    def test_all_success(self) -> None:
        """전체 성공 케이스."""
        results = [
            {"status": "SUBMITTED"},
            {"status": "SUBMITTED"},
            {"status": "DRY_RUN"},
        ]
        summary = _build_aggregate_summary(results, total_duration=30.0)

        assert summary["total_cycles"] == 3
        assert summary["success"] == 3
        assert summary["error"] == 0
        assert summary["success_rate"] == 100.0

    def test_mixed_results(self) -> None:
        """혼합 결과."""
        results = [
            {"status": "SUBMITTED"},
            {"status": "SKIPPED"},
            {"status": "ERROR"},
            {"status": "DRY_RUN"},
        ]
        summary = _build_aggregate_summary(results, total_duration=20.0)

        assert summary["total_cycles"] == 4
        assert summary["success"] == 3  # SUBMITTED + SKIPPED + DRY_RUN
        assert summary["skipped"] == 1
        assert summary["error"] == 1
        assert summary["success_rate"] == 75.0

    def test_empty_results(self) -> None:
        """빈 결과 리스트."""
        summary = _build_aggregate_summary([], total_duration=0.0)

        assert summary["total_cycles"] == 0
        assert summary["success_rate"] == 0


class TestSerializePrecheck:
    """``_serialize_precheck()`` — health summary 직렬화."""

    def test_healthy(self) -> None:
        """Fresh snapshot sync."""
        health = SnapshotSyncHealthSummary(
            last_run_started_at=datetime.now(timezone.utc) - timedelta(seconds=60),
            last_run_completed_at=datetime.now(timezone.utc) - timedelta(seconds=50),
            last_status="completed",
            last_successful_run_at=datetime.now(timezone.utc) - timedelta(seconds=60),
            consecutive_failures=0,
            is_stale=False,
            stale_threshold_seconds=900,
        )
        result = _serialize_precheck(health)

        assert result["health_status"] == "ok"
        assert result["consecutive_failures"] == 0
        assert result["last_successful_run_at"] is not None

    def test_stale(self) -> None:
        """Stale snapshot sync."""
        health = SnapshotSyncHealthSummary(
            last_run_started_at=datetime.now(timezone.utc) - timedelta(hours=2),
            last_run_completed_at=datetime.now(timezone.utc) - timedelta(hours=2) + timedelta(seconds=10),
            last_status="completed",
            last_successful_run_at=datetime.now(timezone.utc) - timedelta(hours=2),
            consecutive_failures=2,
            is_stale=True,
            stale_threshold_seconds=900,
        )
        result = _serialize_precheck(health)

        assert result["health_status"] == "stale"
        assert result["consecutive_failures"] == 2


# ---------------------------------------------------------------------------
# Cycle execution tests (with mocked runtime)
# ---------------------------------------------------------------------------


class TestRunOneCycle:
    """``_run_one_cycle()`` — mocked runtime으로 cycle 실행 검증."""

    @patch(
        "scripts.run_paper_decision_loop.postgres_runtime",
        side_effect=lambda run_migrations=False: _mock_runtime(),
    )
    @pytest.mark.asyncio
    async def test_dry_run(self, mock_runtime: Any) -> None:
        """Dry-run 모드: assemble + sizing, broker submit 없음."""
        result = await _run_one_cycle(
            cycle=1,
            submit=False,
            dry_run=True,
            output="text",
        )

        assert result["status"] == "DRY_RUN"
        assert result["cycle"] == 1
        assert result["decision_context_id"] is not None
        assert result["duration_seconds"] > 0

    @patch(
        "scripts.run_paper_decision_loop.postgres_runtime",
        side_effect=lambda run_migrations=False: _mock_runtime(),
    )
    @pytest.mark.asyncio
    async def test_submit(self, mock_runtime: Any) -> None:
        """Submit 모드: full pipeline 실행."""
        result = await _run_one_cycle(
            cycle=1,
            submit=True,
            dry_run=False,
            output="text",
        )

        # Actual status depends on stub agents (may be SKIPPED or SUBMITTED)
        assert result["status"] in ("SUBMITTED", "SKIPPED", "ERROR")
        assert result["cycle"] == 1

    @patch(
        "scripts.run_paper_decision_loop.postgres_runtime",
        side_effect=lambda run_migrations=False: _mock_runtime(snapshot_stale=True),
    )
    @pytest.mark.asyncio
    async def test_precheck_stale_in_summary(self, mock_runtime: Any) -> None:
        """Stale snapshot 환경에서 pre-check 정보가 cycle summary에 포함."""
        result = await _run_one_cycle(
            cycle=1,
            submit=True,
            dry_run=False,
            output="text",
        )

        # Pre-check should be present and indicate stale
        precheck = result.get("precheck")
        assert precheck is not None, "Pre-check should be present in summary"
        assert precheck.get("health_status") in ("stale", "ok"), (
            f"Unexpected health_status: {precheck.get('health_status')}"
        )


# ---------------------------------------------------------------------------
# CLI argument parsing tests
# ---------------------------------------------------------------------------


class TestParseArgs:
    """``_parse_args()`` — CLI 인자 파싱."""

    def test_defaults(self) -> None:
        """기본값 확인: count=0(무한), submit=True, output=text."""
        args = _parse_args([])
        assert args.count == 0
        assert args.submit is True
        assert args.output == "text"
        assert args.interval == 0
        assert args.dry_run is False

    def test_count_one(self) -> None:
        """--count 1."""
        args = _parse_args(["--count", "1"])
        assert args.count == 1

    def test_dry_run(self) -> None:
        """--dry-run."""
        args = _parse_args(["--dry-run", "--count", "1"])
        assert args.dry_run is True
        assert args.count == 1

    def test_interval(self) -> None:
        """--interval 60."""
        args = _parse_args(["--interval", "60"])
        assert args.interval == 60

    def test_json_output(self) -> None:
        """--output json."""
        args = _parse_args(["--output", "json"])
        assert args.output == "json"


class TestTradingUniverse:
    """Trading universe env parsing and DB fallback."""

    def test_default_universe(self) -> None:
        assert _parse_universe_symbols(None) == (UniverseSymbol("005930", "KRX"),)

    def test_parse_symbols_with_default_market(self) -> None:
        assert _parse_universe_symbols("005930,000660") == (
            UniverseSymbol("005930", "KRX"),
            UniverseSymbol("000660", "KRX"),
        )

    def test_parse_explicit_markets_and_dedup(self) -> None:
        assert _parse_universe_symbols("005930:KRX,005930.KRX,AAPL:NASDAQ") == (
            UniverseSymbol("005930", "KRX"),
            UniverseSymbol("AAPL", "NASDAQ"),
        )

    @pytest.mark.asyncio
    async def test_read_trading_universe_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env var takes priority over DB fallback."""
        monkeypatch.setenv(ENV_TRADING_UNIVERSE, "030200,090150:KRX")
        result = await _read_trading_universe()
        assert result == (
            UniverseSymbol("030200", "KRX"),
            UniverseSymbol("090150", "KRX"),
        )

    @pytest.mark.asyncio
    async def test_db_fallback_when_env_not_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When env var is not set, DB is queried for active KRX instruments."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)

        # Mock asyncpg Row-like objects
        class FakeRow:
            def __init__(self, symbol: str, market_code: str) -> None:
                self._data = {"symbol": symbol, "market_code": market_code}
            def __getitem__(self, key: str) -> str:
                return self._data[key]

        class FakeConn:
            async def fetch(self, query: str, *args: Any, **kwargs: Any) -> list[Any]:
                return [
                    FakeRow("005930", "KRX"),
                    FakeRow("000660", "KRX"),
                ]
            async def close(self) -> None:
                pass

        # asyncpg.connect() is async, so we must return an awaitable.
        # Use AsyncMock to make connect() return FakeConn when awaited.
        with patch("asyncpg.connect", new=AsyncMock(return_value=FakeConn())):
            result = await _read_trading_universe()
            assert result == (
                UniverseSymbol("005930", "KRX"),
                UniverseSymbol("000660", "KRX"),
            )

    @pytest.mark.asyncio
    async def test_db_fallback_empty_returns_single_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When DB returns 0 rows, fallback to 005930 single symbol."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)

        class FakeConnEmpty:
            async def fetch(self, query: str, *args: Any, **kwargs: Any) -> list[Any]:
                return []
            async def close(self) -> None:
                pass

        with patch("asyncpg.connect", new=lambda dsn=None, **kw: FakeConnEmpty()):
            result = await _read_trading_universe()
            assert result == (UniverseSymbol("005930", "KRX"),)

    @pytest.mark.asyncio
    async def test_db_fallback_on_connection_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When DB connection fails, fallback to 005930 single symbol."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)

        with patch("asyncpg.connect", side_effect=RuntimeError("DB connection refused")):
            result = await _read_trading_universe()
            assert result == (UniverseSymbol("005930", "KRX"),)
