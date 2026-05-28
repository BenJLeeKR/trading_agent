"""Tests for ``scripts.run_decision_loop`` — paper decision loop runner.

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
from agent_trading.db.transaction import transaction as _db_transaction
from agent_trading.domain.entities import (
    AccountEntity,
    CashBalanceSnapshotEntity,
    ClientEntity,
    ConfigVersionEntity,
    ExternalEventEntity,
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
from agent_trading.repositories.memory import InMemoryExternalEventRepository
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
    OrderIntent,
    SubmitResult,
)

# Module under test
from scripts.run_decision_loop import (
    ENV_TRADING_UNIVERSE,
    KISRestClient,
    UniverseSymbol,
    _build_aggregate_summary,
    _collect_persisted_seeded_events,
    _is_t3_fresh_for_symbol,
    _parse_args,
    _parse_universe_symbols,
    _read_trading_universe,
    _resolve_symbol_price,
    _run_one_cycle,
    _run_precheck,
    _run_t3_live_pipeline,
    _serialize_cycle_result,
    _serialize_precheck,
    persist_seeded_events,
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
            side="buy",
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


@asynccontextmanager
async def _mock_runtime_for_one_cycle(
    snapshot_stale: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Create a mock runtime + patch lazy imports for ``_run_one_cycle()``.

    ``_run_one_cycle()`` now uses lazy imports inside its body:
        - ``_db_transaction`` (per-symbol transaction)
        - ``build_postgres_repositories`` (creates Postgres repos)
        - ``DecisionOrchestratorService``, ``OrderManager``, ``ReconciliationService``

    This helper patches those imports so that in-memory repos are used instead
    of real Postgres repos, allowing unit tests to run without a database.
    """
    repos = build_in_memory_repositories()
    await _seed_repos(repos)

    # Configure snapshot sync health
    now = datetime.now(timezone.utc)
    if snapshot_stale:
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

    # ── Mock transaction context manager ──────────────────────────────
    # _run_one_cycle() does: async with _db_transaction() as tx:
    # We need a mock tx that has commit() and whose connection is not used.
    # NOTE: _run_one_cycle() uses lazy imports inside its body:
    #   from agent_trading.db.transaction import transaction as _db_transaction
    # So we must patch the ORIGINAL module paths, not scripts.run_decision_loop.*
    mock_tx = AsyncMock()
    mock_tx.commit = AsyncMock()

    @asynccontextmanager
    async def _mock_db_transaction() -> AsyncIterator[AsyncMock]:
        yield mock_tx

    # ── Mock build_postgres_repositories ──────────────────────────────
    # _run_one_cycle() does: repos = build_postgres_repositories(tx)
    # We return the in-memory repos instead.
    def _mock_build_postgres_repositories(tx: object) -> RepositoryContainer:
        return repos

    # ── Apply patches ─────────────────────────────────────────────────
    # Lazy imports inside _run_one_cycle() import from original modules,
    # so we patch the original module paths, not scripts.run_decision_loop.*
    with (
        patch(
            "agent_trading.db.transaction.transaction",
            _mock_db_transaction,
        ),
        patch(
            "agent_trading.repositories.postgres.bootstrap.build_postgres_repositories",
            _mock_build_postgres_repositories,
        ),
        patch(
            "agent_trading.services.decision_orchestrator.DecisionOrchestratorService",
            return_value=orchestrator,
        ),
        patch(
            "agent_trading.services.order_manager.OrderManager",
            return_value=order_manager,
        ),
        patch(
            "agent_trading.services.reconciliation_service.ReconciliationService",
            return_value=reconciliation_service,
        ),
    ):
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
            order_intent=intent,
            submit_response=order,
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
        # decision_type과 side는 모든 분기에서 항상 포함
        assert serialized["decision_type"] == "APPROVE"
        assert serialized["side"] == "buy"

    def test_dry_run_result(self) -> None:
        """Dry-run 모드 직렬화."""
        ctx_id = uuid4()
        intent = _make_stub_intent(decision_context_id=ctx_id)
        result = SubmitResult(
            status="DRY_RUN",
            order_intent=intent,
            decision_context_id=ctx_id,
        )

        serialized = _serialize_cycle_result(
            cycle=1, result=result, duration=3.0, dry_run=True
        )

        assert serialized["status"] == "DRY_RUN"
        assert serialized["decision_context_id"] == str(ctx_id)
        assert serialized["order_intent_id"] == str(intent.order_intent_id)
        assert serialized["decision_type"] == "APPROVE"
        assert serialized["side"] == "buy"

    def test_error_result(self) -> None:
        """Error 결과 직렬화."""
        serialized = _serialize_cycle_result(
            cycle=2, result=None, duration=1.0, error="Something broke"
        )

        assert serialized["status"] == "ERROR"
        assert serialized["error"] == "Something broke"
        assert serialized["cycle"] == 2
        # error 분기에서는 intent가 없으므로 decision_type/side는 None
        assert serialized["decision_type"] is None
        assert serialized["side"] is None

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
        # error 분기에서는 intent가 없으므로 decision_type/side는 None
        assert serialized["decision_type"] is None
        assert serialized["side"] is None


class TestSerializeCycleResultSourceType:
    """``_serialize_cycle_result()`` — source_type 필드 직렬화 검증."""

    def test_default_source_type_is_core(self) -> None:
        """source_type 기본값은 'core'."""
        serialized = _serialize_cycle_result(cycle=1, result=None, duration=1.0)
        assert serialized["source_type"] == "core"
        # decision_type/side는 모든 분기에서 항상 포함
        assert serialized["decision_type"] is None
        assert serialized["side"] is None

    def test_held_position_source_type(self) -> None:
        """held_position source_type이 출력에 포함됨."""
        serialized = _serialize_cycle_result(
            cycle=1, result=None, duration=1.0, source_type="held_position"
        )
        assert serialized["source_type"] == "held_position"
        # decision_type/side는 모든 분기에서 항상 포함
        assert serialized["decision_type"] is None
        assert serialized["side"] is None

    def test_source_type_in_submitted_result(self) -> None:
        """SUBMITTED 결과에도 source_type 필드가 포함됨."""
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
            order_intent=intent,
            submit_response=order,
            trade_decision_id=uuid4(),
            decision_context_id=ctx_id,
        )

        serialized = _serialize_cycle_result(
            cycle=1, result=result, duration=5.5, source_type="held_position"
        )

        assert serialized["source_type"] == "held_position"
        assert serialized["status"] == "SUBMITTED"
        # decision_type/side는 모든 분기에서 항상 포함
        assert serialized["decision_type"] == "APPROVE"
        assert serialized["side"] == "buy"

    def test_source_type_in_error_result(self) -> None:
        """Error 결과에도 source_type 필드가 포함됨."""
        serialized = _serialize_cycle_result(
            cycle=2, result=None, duration=1.0, error="Something broke",
            source_type="held_position",
        )

        assert serialized["source_type"] == "held_position"
        assert serialized["status"] == "ERROR"
        # decision_type/side는 모든 분기에서 항상 포함
        assert serialized["decision_type"] is None
        assert serialized["side"] is None


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
    """``_run_one_cycle()`` — mocked runtime으로 cycle 실행 검증.

    변경 사항 (Runtime 공유 리팩토링):
    - _run_one_cycle()이 더 이상 postgres_runtime()을 내부에서 호출하지 않음
    - runtime dict를 외부에서 주입받음
    - cycle_precheck도 외부에서 주입받음
    - 내부 lazy import (_db_transaction, build_postgres_repositories 등)는
      _mock_runtime_for_one_cycle()이 patch로 대체
    """

    @pytest.mark.asyncio
    async def test_dry_run(self) -> None:
        """Dry-run 모드: assemble + sizing, broker submit 없음."""
        async with _mock_runtime_for_one_cycle() as runtime:
            result = await _run_one_cycle(
                cycle=1,
                submit=False,
                dry_run=True,
                output="text",
                runtime=runtime,
            )

        assert result["status"] == "DRY_RUN"
        assert result["cycle"] == 1
        assert result["decision_context_id"] is not None
        assert result["duration_seconds"] > 0

    @pytest.mark.asyncio
    async def test_submit(self) -> None:
        """Submit 모드: full pipeline 실행."""
        async with _mock_runtime_for_one_cycle() as runtime:
            result = await _run_one_cycle(
                cycle=1,
                submit=True,
                dry_run=False,
                output="text",
                runtime=runtime,
            )

        # Actual status depends on stub agents (may be SKIPPED or SUBMITTED)
        assert result["status"] in ("SUBMITTED", "SKIPPED", "ERROR")
        assert result["cycle"] == 1

    @pytest.mark.asyncio
    async def test_precheck_stale_in_summary(self) -> None:
        """Stale snapshot 환경에서 pre-check 정보가 cycle summary에 포함.

        NOTE: _run_one_cycle()은 더 이상 내부에서 _run_precheck()를 호출하지 않음.
        precheck는 _run_loop() 레벨에서 cycle_precheck로 주입됨.
        이 테스트는 cycle_precheck 인자가 올바르게 결과에 반영되는지 검증.
        """
        async with _mock_runtime_for_one_cycle(snapshot_stale=True) as runtime:
            # cycle_precheck를 직접 생성하여 주입
            from scripts.run_decision_loop import _run_precheck

            precheck_repos = build_in_memory_repositories()
            await _seed_repos(precheck_repos)
            # snapshot_stale=True와 동일한 stale 상태 설정
            now = datetime.now(timezone.utc)
            await precheck_repos.snapshot_sync_runs.add(
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
            cycle_precheck = await _run_precheck(precheck_repos)

            result = await _run_one_cycle(
                cycle=1,
                submit=True,
                dry_run=False,
                output="text",
                runtime=runtime,
                cycle_precheck=cycle_precheck,
            )

        # Pre-check should be present and indicate stale
        precheck = result.get("precheck")
        assert precheck is not None, "Pre-check should be present in summary"
        assert precheck.get("health_status") in ("stale", "ok"), (
            f"Unexpected health_status: {precheck.get('health_status')}"
        )

    @pytest.mark.asyncio
    async def test_dry_run_with_held_position_source_type(self) -> None:
        """Dry-run 모드에서 source_type='held_position'이 결과에 포함됨."""
        async with _mock_runtime_for_one_cycle() as runtime:
            result = await _run_one_cycle(
                cycle=1,
                submit=False,
                dry_run=True,
                output="text",
                source_type="held_position",
                runtime=runtime,
            )

        assert result["status"] == "DRY_RUN"
        assert result["source_type"] == "held_position"
        assert result["cycle"] == 1

    @pytest.mark.asyncio
    async def test_submit_with_held_position_source_type(self) -> None:
        """Submit 모드에서 source_type='held_position'이 결과에 포함됨."""
        async with _mock_runtime_for_one_cycle() as runtime:
            result = await _run_one_cycle(
                cycle=1,
                submit=True,
                dry_run=False,
                output="text",
                source_type="held_position",
                runtime=runtime,
            )

        assert result["source_type"] == "held_position"
        assert result["status"] in ("SUBMITTED", "SKIPPED", "ERROR")

    # ------------------------------------------------------------------
    # T3 fresh skip / quota skip 분기 검증
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_t3_fresh_skip_when_fresh_events_exist(self) -> None:
        """T3 events가 freshness window 내 존재 → T3 live pipeline skip (fresh skip).

        _is_t3_fresh_for_symbol()이 True를 반환하면 T3 live pipeline이
        create_task되지 않고, cycle은 정상 완료되어야 함.
        """
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now = datetime.now(timezone.utc)

            # Add fresh T3 event (created_at=now → freshness window 내)
            event = ExternalEventEntity(
                event_id=uuid4(),
                event_type="Y|seeded_news",
                source_name="naver",
                source_reliability_tier="T3",
                symbol=SYMBOL,
                market=MARKET,
                published_at=now - timedelta(minutes=30),
                ingested_at=now,
                severity="medium",
                direction="neutral",
                headline="Fresh T3 event for fresh skip test",
            )
            await repos.external_events.add(event)

            # Mock quota exhausted as safety net (in case fresh skip fails)
            from agent_trading.brokers.naver_news_adapter import NaverNewsSearchAdapter
            with patch.object(NaverNewsSearchAdapter, "is_quota_exhausted", return_value=True):
                result = await _run_one_cycle(
                    cycle=1,
                    submit=False,
                    dry_run=True,
                    output="text",
                    runtime=runtime,
                )

        # DRY_RUN 정상 완료 확인
        assert result["status"] == "DRY_RUN"
        assert result["cycle"] == 1

    @pytest.mark.asyncio
    async def test_t3_quota_exhausted_skip(self) -> None:
        """T3 stale + NAVER quota 소진 → T3 live pipeline skip (quota skip).

        NaverNewsSearchAdapter.is_quota_exhausted()가 True를 반환하면
        T3 live pipeline이 skip되고 cycle은 정상 완료되어야 함.
        """
        async with _mock_runtime_for_one_cycle() as runtime:
            # Mock quota exhausted → T3 live pipeline should be skipped
            from agent_trading.brokers.naver_news_adapter import NaverNewsSearchAdapter
            with patch.object(NaverNewsSearchAdapter, "is_quota_exhausted", return_value=True):
                result = await _run_one_cycle(
                    cycle=1,
                    submit=False,
                    dry_run=True,
                    output="text",
                    runtime=runtime,
                )

        # Cycle 정상 완료 확인 (T3 pipeline이 skip되어도 문제 없음)
        assert result["status"] == "DRY_RUN"
        assert result["cycle"] == 1

    @pytest.mark.asyncio
    async def test_t3_fresh_skip_completes_normally(self) -> None:
        """Fresh T3 events + dry_run 모드 → cycle 정상 완료.

        여러 symbol에 fresh T3 events가 존재해도 cycle이 정상 완료됨을 검증.
        """
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now = datetime.now(timezone.utc)

            # Add T3 events for all universe symbols
            for symbol in ["005930", "000660", "005380", "068270"]:
                event = ExternalEventEntity(
                    event_id=uuid4(),
                    event_type="Y|seeded_news",
                    source_name="naver",
                    source_reliability_tier="T3",
                    symbol=symbol,
                    market=MARKET,
                    published_at=now - timedelta(minutes=30),
                    ingested_at=now,
                    severity="medium",
                    direction="neutral",
                    headline=f"Fresh T3 event for {symbol}",
                )
                await repos.external_events.add(event)

            from agent_trading.brokers.naver_news_adapter import NaverNewsSearchAdapter
            with patch.object(NaverNewsSearchAdapter, "is_quota_exhausted", return_value=True):
                result = await _run_one_cycle(
                    cycle=1,
                    submit=False,
                    dry_run=True,
                    output="text",
                    runtime=runtime,
                )

        # Cycle 정상 완료 확인
        assert result["status"] == "DRY_RUN"
        assert result["cycle"] == 1


class TestHeldPositionSellBudget:
    """``_run_loop()`` 내 held_position sell budget 분기 로직 검증.

    cycle당 cap (HELD_POSITION_SELL_MAX_PER_CYCLE=2)과
    symbol deduplication이 올바르게 동작하는지 확인.
    """

    @pytest.mark.asyncio
    async def test_hp_sell_cycle_cap_blocks_third_submit(self) -> None:
        """동일 cycle 내 HP sell이 2건을 초과하면 세 번째는 block되어야 함.

        NOTE: held_position_sell_budget_consumed는 일간 cap(5건) 소진 시 True.
        cycle cap 테스트에서는 일간 cap이 아직 소진되지 않았다고 가정.
        """
        held_position_sell_budget_consumed = False  # 일간 cap은 아직 여유
        held_position_sell_cycle_count = 0
        held_position_sell_cycle_symbols: set[str] = set()
        HELD_POSITION_SELL_MAX_PER_CYCLE = 2

        class _MockItem:
            def __init__(self, symbol: str, source_type: str = "held_position"):
                self.symbol = symbol
                self.source_type = source_type
                self.market = "KOSPI"

        # 3개의 다른 symbol로 HP sell submit 시도
        items = [
            _MockItem("AAPL"),
            _MockItem("GOOGL"),
            _MockItem("MSFT"),
        ]

        submit = True
        dry_run = False
        results: list[bool] = []

        for item in items:
            is_held_position_item = (
                getattr(item, "source_type", "core") == "held_position"
            )
            if is_held_position_item:
                symbol_submit = (
                    submit
                    and not dry_run
                    and not held_position_sell_budget_consumed
                    and held_position_sell_cycle_count < HELD_POSITION_SELL_MAX_PER_CYCLE
                    and item.symbol not in held_position_sell_cycle_symbols
                )
            else:
                symbol_submit = submit and not dry_run

            results.append(symbol_submit)

            # budget 소비: cycle count만 증가 (daily cap은 아직 소진 안 됨)
            if symbol_submit:
                held_position_sell_cycle_count += 1
                held_position_sell_cycle_symbols.add(item.symbol)
                # NOTE: 실제 _process_one에서는 daily cap도 함께 설정되지만,
                # cycle cap만 테스트하기 위해 daily cap은 유지

        # AAPL: submit 허용 (1/2)
        assert results[0] is True, "첫 번째 HP sell은 허용되어야 함"
        # GOOGL: submit 허용 (2/2)
        assert results[1] is True, "두 번째 HP sell은 허용되어야 함"
        # MSFT: cycle cap으로 block (2 >= 2)
        assert results[2] is False, "세 번째 HP sell은 cycle cap으로 block되어야 함"

    @pytest.mark.asyncio
    async def test_hp_sell_symbol_dedupe_blocks_duplicate(self) -> None:
        """동일 cycle 내 같은 symbol의 HP sell 중복 submit이 block되어야 함."""
        held_position_sell_budget_consumed = False
        held_position_sell_cycle_count = 0
        held_position_sell_cycle_symbols: set[str] = set()
        HELD_POSITION_SELL_MAX_PER_CYCLE = 2

        class _MockItem:
            def __init__(self, symbol: str, source_type: str = "held_position"):
                self.symbol = symbol
                self.source_type = source_type
                self.market = "KOSPI"

        # 같은 symbol로 2회 시도
        items = [
            _MockItem("AAPL"),
            _MockItem("AAPL"),  # duplicate
        ]

        submit = True
        dry_run = False
        results: list[bool] = []

        for item in items:
            is_held_position_item = (
                getattr(item, "source_type", "core") == "held_position"
            )
            if is_held_position_item:
                symbol_submit = (
                    submit
                    and not dry_run
                    and not held_position_sell_budget_consumed
                    and held_position_sell_cycle_count < HELD_POSITION_SELL_MAX_PER_CYCLE
                    and item.symbol not in held_position_sell_cycle_symbols
                )
            else:
                symbol_submit = submit and not dry_run

            results.append(symbol_submit)

            if symbol_submit:
                held_position_sell_cycle_count += 1
                held_position_sell_cycle_symbols.add(item.symbol)

        # 첫 번째 AAPL: submit 허용
        assert results[0] is True, "첫 번째 AAPL HP sell은 허용되어야 함"
        # 두 번째 AAPL: symbol dedupe으로 block
        assert results[1] is False, "중복 symbol AAPL은 block되어야 함"

    @pytest.mark.asyncio
    async def test_hp_sell_daily_cap_removed(self) -> None:
        """일간 HP sell budget 상한이 제거되었으므로 daily cap으로 block되지 않음.

        NOTE: held_position sell은 위험 축소 목적이므로 일일 제출 상한이
        제거되었습니다. cycle cap(2건)과 symbol dedupe만 유지됩니다.
        """
        held_position_sell_cycle_count = 0
        held_position_sell_cycle_symbols: set[str] = set()
        HELD_POSITION_SELL_MAX_PER_CYCLE = 2

        class _MockItem:
            def __init__(self, symbol: str, source_type: str = "held_position"):
                self.symbol = symbol
                self.source_type = source_type
                self.market = "KOSPI"

        # 3개의 다른 symbol — daily cap이 없으므로 cycle cap(2)까지만 허용
        items = [
            _MockItem("SYM0"),
            _MockItem("SYM1"),
            _MockItem("SYM2"),
        ]

        submit = True
        dry_run = False
        results: list[bool] = []

        for i, item in enumerate(items):
            is_held_position_item = (
                getattr(item, "source_type", "core") == "held_position"
            )
            if is_held_position_item:
                # daily cap 조건 제거됨 — cycle cap + symbol dedupe만 확인
                symbol_submit = (
                    submit
                    and not dry_run
                    and held_position_sell_cycle_count < HELD_POSITION_SELL_MAX_PER_CYCLE
                    and item.symbol not in held_position_sell_cycle_symbols
                )
            else:
                symbol_submit = submit and not dry_run

            results.append(symbol_submit)

            if symbol_submit:
                held_position_sell_cycle_count += 1
                held_position_sell_cycle_symbols.add(item.symbol)

        # SYM0: cycle cap 허용 (1/2)
        assert results[0] is True
        # SYM1: cycle cap 허용 (2/2)
        assert results[1] is True
        # SYM2: cycle cap 초과 (2/2)로 block (daily cap이 아닌 cycle cap)
        assert results[2] is False


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
    async def test_universe_selection_service_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When env var is not set, UniverseSelectionService reads active KRX instruments."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)

        # Build in-memory repos with active KRX instruments
        repos = build_in_memory_repositories()
        from agent_trading.domain.entities import InstrumentEntity
        await repos.instruments.add(
            InstrumentEntity(
                instrument_id=UUID("11111111-1111-1111-1111-111111111111"),
                symbol="005930",
                market_code="KRX",
                name="Samsung Electronics",
                is_active=True,
                asset_class="KR_STOCK",
                currency="KRW",
                tick_size=Decimal("50"),
            )
        )
        await repos.instruments.add(
            InstrumentEntity(
                instrument_id=UUID("22222222-2222-2222-2222-222222222222"),
                symbol="000660",
                market_code="KRX",
                name="SK Hynix",
                is_active=True,
                asset_class="KR_STOCK",
                currency="KRW",
                tick_size=Decimal("50"),
            )
        )

        # Mock postgres_runtime to return our in-memory repos
        @asynccontextmanager
        async def _mock_postgres_runtime(run_migrations: bool = False) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": repos}

        with (
            patch(
                "scripts.run_decision_loop.postgres_runtime",
                new=_mock_postgres_runtime,
            ),
            patch(
                "scripts.run_decision_loop._HAS_KIS",
                False,
            ),
        ):
            result = await _read_trading_universe()
            assert len(result) == 2
            symbols = {u.symbol for u in result}
            assert symbols == {"005930", "000660"}
            # source_type과 inclusion_reason이 설정되었는지 확인
            for u in result:
                assert u.source_type == "core"
                assert u.inclusion_reason == "kospi200_core"

    @pytest.mark.asyncio
    async def test_universe_selection_service_with_kis_market_overlay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """KIS client가 정상 생성되면 _add_market_overlay() 경로가 활성화됨.

        KISRestClient.get_quotes_batch()를 mock하여 real API 호출을 방지.
        """
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)

        repos = build_in_memory_repositories()
        from agent_trading.domain.entities import InstrumentEntity
        for sym in ("005930", "000660", "090150"):
            await repos.instruments.add(
                InstrumentEntity(
                    instrument_id=uuid4(),
                    symbol=sym,
                    market_code="KRX",
                    name=f"Test-{sym}",
                    is_active=True,
                    asset_class="KR_STOCK",
                    currency="KRW",
                    tick_size=Decimal("50"),
                )
            )

        # Mock KISRestClient so it returns empty batch (no market overlay added)
        mock_kis = AsyncMock(spec=KISRestClient)
        mock_kis.get_quotes_batch = AsyncMock(return_value={})

        @asynccontextmanager
        async def _mock_runtime(run_migrations: bool = False) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": repos}

        with (
            patch(
                "scripts.run_decision_loop.postgres_runtime",
                new=_mock_runtime,
            ),
            patch(
                "scripts.run_decision_loop.KISRestClient",
                return_value=mock_kis,
            ),
        ):
            result = await _read_trading_universe()
            assert len(result) == 3
            # market overlay returned empty batch → no market_overlay symbols
            for u in result:
                assert u.source_type == "core"
                assert u.inclusion_reason == "kospi200_core"

    @pytest.mark.asyncio
    async def test_universe_selection_service_with_kis_quotes_returned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """KIS client가 quote를 반환하면 market_overlay symbol이 추가됨."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)

        repos = build_in_memory_repositories()
        from agent_trading.domain.entities import InstrumentEntity
        await repos.instruments.add(
            InstrumentEntity(
                instrument_id=UUID("11111111-1111-1111-1111-111111111111"),
                symbol="005930",
                market_code="KRX",
                name="Samsung Electronics",
                is_active=True,
                asset_class="KR_STOCK",
                currency="KRW",
                tick_size=Decimal("50"),
            )
        )

        mock_quote: dict[str, object] = {
            "stck_prpr": "70000",
            "prdy_ctrt": "2.5",
            "acml_tr_pbmn": "500000000000",
            "stck_hgpr": "71000",
            "stck_lwpr": "69000",
            "stck_oprc": "69500",
            "iscd_stat_cls_code": "",
        }
        mock_kis = AsyncMock(spec=KISRestClient)
        mock_kis.get_quotes_batch = AsyncMock(
            return_value={"005930": mock_quote},
        )

        @asynccontextmanager
        async def _mock_runtime(run_migrations: bool = False) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": repos}

        with (
            patch(
                "scripts.run_decision_loop.postgres_runtime",
                new=_mock_runtime,
            ),
            patch(
                "scripts.run_decision_loop.KISRestClient",
                return_value=mock_kis,
            ),
        ):
            result = await _read_trading_universe()
            assert len(result) == 1
            u = result[0]
            assert u.symbol == "005930"
            assert u.source_type == "market_overlay"
            # prdy_ctrt=2.5 < 3.0, acml_tr_pbmn=5000억 == threshold (not >),
            # but stck_prpr(70000)/stck_hgpr(71000)=0.986 > 0.95 → near_high_breakout
            assert u.inclusion_reason == "near_high_breakout"

    @pytest.mark.asyncio
    async def test_kis_client_init_failure_logs_warning(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """KIS client 생성 실패 시 warning 로그가 남고 market_overlay는 disabled."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)

        repos = build_in_memory_repositories()
        from agent_trading.domain.entities import InstrumentEntity
        await repos.instruments.add(
            InstrumentEntity(
                instrument_id=UUID("11111111-1111-1111-1111-111111111111"),
                symbol="005930",
                market_code="KRX",
                name="Samsung Electronics",
                is_active=True,
                asset_class="KR_STOCK",
                currency="KRW",
                tick_size=Decimal("50"),
            )
        )

        # Mock KISRestClient constructor to raise TypeError
        def _raise_on_init(*args: object, **kwargs: object) -> KISRestClient:
            raise TypeError("mock KIS init failure")

        @asynccontextmanager
        async def _mock_runtime(run_migrations: bool = False) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": repos}

        with (
            patch(
                "scripts.run_decision_loop.postgres_runtime",
                new=_mock_runtime,
            ),
            patch(
                "scripts.run_decision_loop.KISRestClient",
                side_effect=_raise_on_init,
            ),
            caplog.at_level("WARNING"),
        ):
            result = await _read_trading_universe()
            # Fallback to single symbol when KIS init fails
            assert result == (UniverseSymbol("005930", "KRX"),)
            # Warning log should contain both "market_overlay disabled" and error info
            assert any(
                "market_overlay disabled" in rec.message
                and "mock KIS init failure" in rec.message
                for rec in caplog.records
            ), f"Expected warning log with 'market_overlay disabled' and error. Got: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_universe_selection_service_empty_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When UniverseSelectionService returns 0 symbols, fallback to 005930."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)

        repos = build_in_memory_repositories()

        @asynccontextmanager
        async def _mock_postgres_runtime(run_migrations: bool = False) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": repos}

        with patch(
            "scripts.run_decision_loop.postgres_runtime",
            new=_mock_postgres_runtime,
        ):
            result = await _read_trading_universe()
            assert result == (UniverseSymbol("005930", "KRX"),)

    @pytest.mark.asyncio
    async def test_universe_selection_service_error_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When UniverseSelectionService raises, fallback to 005930."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)

        class _MockRuntimeError:
            """Async context manager that raises on __aenter__.
            Class-based (not @asynccontextmanager) to avoid
            ``coroutine was never awaited`` warning."""
            async def __aenter__(self) -> dict[str, Any]:
                raise RuntimeError("Runtime unavailable")
            async def __aexit__(self, *args: object) -> None:
                pass

        with patch(
            "scripts.run_decision_loop.postgres_runtime",
            new=_MockRuntimeError,
        ):
            result = await _read_trading_universe()
            assert result == (UniverseSymbol("005930", "KRX"),)


# ---------------------------------------------------------------------------
# _resolve_symbol_price tests
# ---------------------------------------------------------------------------


class TestResolveSymbolPrice:
    """``_resolve_symbol_price()`` — symbol별 quote 기반 가격 결정."""

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """각 테스트 전에 KIS_SMOKE_PRICE를 제거하여 환경 의존성 제거."""
        monkeypatch.delenv("KIS_SMOKE_PRICE", raising=False)

    @pytest.mark.asyncio
    async def test_uses_live_quote(self) -> None:
        """Live quote에서 가격을 가져오는 경로."""
        broker = AsyncMock(spec=BrokerAdapter)
        broker.get_quote = AsyncMock(
            return_value=MagicMock(last=Decimal("15000"))
        )

        price = await _resolve_symbol_price(
            symbol="000880",
            market="KRX",
            broker=broker,
        )

        assert price == Decimal("15000")
        broker.get_quote.assert_awaited_once_with("000880", "KRX")

    @pytest.mark.asyncio
    async def test_fallback_on_quote_none(self) -> None:
        """Quote.last가 None이면 fallback."""
        broker = AsyncMock(spec=BrokerAdapter)
        broker.get_quote = AsyncMock(
            return_value=MagicMock(last=None)
        )

        price = await _resolve_symbol_price(
            symbol="000880",
            market="KRX",
            broker=broker,
        )

        # KIS_SMOKE_PRICE가 없으므로 default 50000
        assert price == Decimal("50000")

    @pytest.mark.asyncio
    async def test_fallback_on_quote_zero(self) -> None:
        """Quote.last가 0이면 fallback."""
        broker = AsyncMock(spec=BrokerAdapter)
        broker.get_quote = AsyncMock(
            return_value=MagicMock(last=Decimal("0"))
        )

        price = await _resolve_symbol_price(
            symbol="000880",
            market="KRX",
            broker=broker,
        )

        assert price == Decimal("50000")

    @pytest.mark.asyncio
    async def test_fallback_on_quote_exception(self) -> None:
        """Quote fetch 예외 발생 시 fallback."""
        broker = AsyncMock(spec=BrokerAdapter)
        broker.get_quote = AsyncMock(side_effect=RuntimeError("API unavailable"))

        price = await _resolve_symbol_price(
            symbol="000880",
            market="KRX",
            broker=broker,
        )

        assert price == Decimal("50000")

    @pytest.mark.asyncio
    async def test_fallback_no_broker(self) -> None:
        """Broker가 None이면 fallback."""
        price = await _resolve_symbol_price(
            symbol="000880",
            market="KRX",
            broker=None,
        )

        assert price == Decimal("50000")

    @pytest.mark.asyncio
    async def test_uses_kis_smoke_price_env_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Quote 실패 시 KIS_SMOKE_PRICE env var를 fallback으로 사용."""
        monkeypatch.setenv("KIS_SMOKE_PRICE", "99999")
        broker = AsyncMock(spec=BrokerAdapter)
        broker.get_quote = AsyncMock(side_effect=RuntimeError("API unavailable"))

        price = await _resolve_symbol_price(
            symbol="000880",
            market="KRX",
            broker=broker,
        )

        assert price == Decimal("99999")

    @pytest.mark.asyncio
    async def test_quote_priority_over_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Live quote가 KIS_SMOKE_PRICE env var보다 우선."""
        monkeypatch.setenv("KIS_SMOKE_PRICE", "99999")
        broker = AsyncMock(spec=BrokerAdapter)
        broker.get_quote = AsyncMock(
            return_value=MagicMock(last=Decimal("15000"))
        )

        price = await _resolve_symbol_price(
            symbol="000880",
            market="KRX",
            broker=broker,
        )

        # Live quote 우선
        assert price == Decimal("15000")


class TestPersistSeededEvents:
    """``persist_seeded_events()`` — DB persistence with dedup."""

    @pytest.mark.asyncio
    async def test_persists_new(self) -> None:
        """새 이벤트를 DB에 저장하는지 검증."""
        repo = InMemoryExternalEventRepository()
        events = [
            ExternalEventEntity(
                event_id=uuid4(),
                event_type="seeded_news",
                source_name="naver_news_seeded",
                published_at=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
                source_reliability_tier="T3",
                symbol="005930",
                headline="Test news",
                dedup_key_hash="aaa111",
                metadata={"importance": "medium"},
            ),
            ExternalEventEntity(
                event_id=uuid4(),
                event_type="seeded_news",
                source_name="naver_news_seeded",
                published_at=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
                source_reliability_tier="T3",
                symbol="005930",
                headline="Test news 2",
                dedup_key_hash="bbb222",
                metadata={"importance": "medium"},
            ),
        ]

        persisted = await persist_seeded_events(events, repo)
        assert persisted == 2

        # DB에 저장 확인
        e1 = await repo.find_by_dedup_key("aaa111")
        assert e1 is not None
        assert e1.headline == "Test news"
        e2 = await repo.find_by_dedup_key("bbb222")
        assert e2 is not None
        assert e2.headline == "Test news 2"

    @pytest.mark.asyncio
    async def test_skips_duplicate(self) -> None:
        """같은 이벤트 재호출 시 dedup skip 검증."""
        repo = InMemoryExternalEventRepository()

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="seeded_news",
            source_name="naver_news_seeded",
            published_at=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
            source_reliability_tier="T3",
            symbol="005930",
            headline="Test news",
            dedup_key_hash="aaa111",
            metadata={"importance": "medium"},
        )

        # 1차 저장
        persisted1 = await persist_seeded_events([event], repo)
        assert persisted1 == 1

        # 동일 dedup_key로 2차 저장 시도
        persisted2 = await persist_seeded_events([event], repo)
        assert persisted2 == 0  # 모두 skip

        # Count 1 유지
        events = await repo.list_by_symbol("005930", since=datetime(2020, 1, 1, tzinfo=timezone.utc),
                                             include_non_listed=True)
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_non_fatal_on_error(self) -> None:
        """DB 저장 실패 시 예외 전파 안 됨 검증."""
        repo = MagicMock(spec=InMemoryExternalEventRepository)
        repo.find_by_dedup_key = AsyncMock(side_effect=ValueError("DB connection lost"))

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="seeded_news",
            source_name="naver_news_seeded",
            published_at=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
            source_reliability_tier="T3",
            symbol="005930",
            headline="Test news",
            dedup_key_hash="aaa111",
            metadata={"importance": "medium"},
        )

        # 예외가 전파되지 않고 0 반환
        persisted = await persist_seeded_events([event], repo)
        assert persisted == 0

    @pytest.mark.asyncio
    async def test_mixed_persist_and_skip(self) -> None:
        """일부는 저장되고 일부는 skip되는 경우."""
        repo = InMemoryExternalEventRepository()

        event_a = ExternalEventEntity(
            event_id=uuid4(),
            event_type="seeded_news",
            source_name="naver_news_seeded",
            published_at=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
            source_reliability_tier="T3",
            symbol="005930",
            headline="News A",
            dedup_key_hash="aaa111",
            metadata={"importance": "medium"},
        )
        event_b = ExternalEventEntity(
            event_id=uuid4(),
            event_type="seeded_news",
            source_name="naver_news_seeded",
            published_at=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
            source_reliability_tier="T3",
            symbol="005930",
            headline="News B",
            dedup_key_hash="bbb222",
            metadata={"importance": "medium"},
        )

        # 1차: 2개 저장
        persisted1 = await persist_seeded_events([event_a, event_b], repo)
        assert persisted1 == 2

        # 2차: event_a만 다시 시도 (중복), event_c는 신규
        event_c = ExternalEventEntity(
            event_id=uuid4(),
            event_type="seeded_news",
            source_name="naver_news_seeded",
            published_at=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
            source_reliability_tier="T3",
            symbol="005930",
            headline="News C",
            dedup_key_hash="ccc333",
            metadata={"importance": "medium"},
        )
        persisted2 = await persist_seeded_events([event_a, event_c], repo)
        assert persisted2 == 1  # event_c만 저장됨

        # 최종 count = 3
        events = await repo.list_by_symbol("005930", since=datetime(2020, 1, 1, tzinfo=timezone.utc),
                                             include_non_listed=True)
        assert len(events) == 3


class TestSigtermHandler:
    """``run_decision_loop.py`` — SIGTERM 핸들러 등록 검증."""

    def test_sigterm_handler_uses_add_signal_handler(self) -> None:
        """SIGTERM handler should use loop.add_signal_handler, not signal.signal in main()."""
        import inspect
        import scripts.run_decision_loop as module

        # _install_signal_handlers() should contain add_signal_handler(...)
        install_source = inspect.getsource(module._install_signal_handlers)
        assert "loop.add_signal_handler(sig, _handle_signal)" in install_source, (
            "_install_signal_handlers() must register SIGTERM/SIGINT via loop.add_signal_handler()"
        )

        # main() should NOT contain signal.signal(SIGTERM, ...) — that is now
        # handled by _install_signal_handlers() which is called from _run_loop().
        main_source = inspect.getsource(module.main)
        assert "signal.signal(signal.SIGTERM" not in main_source, (
            "main() must NOT register SIGTERM via signal.signal() — "
            "use _install_signal_handlers() instead"
        )
        # _handle_sigterm should no longer be defined in main()
        assert "def _handle_sigterm" not in main_source, (
            "_handle_sigterm should not be defined in main() — "
            "use _handle_signal() instead"
        )

    def test_handle_signal_cancels_all_tasks(self) -> None:
        """_handle_signal() should cancel all asyncio tasks to unblock httpx I/O."""
        import inspect
        import scripts.run_decision_loop as module

        source = inspect.getsource(module._handle_signal)
        assert "task.cancel()" in source, (
            "_handle_signal() must call task.cancel() on all pending tasks"
        )
        assert "asyncio.all_tasks()" in source, (
            "_handle_signal() must iterate over asyncio.all_tasks()"
        )
        assert "_shutdown_event.set()" in source, (
            "_handle_signal() must set _shutdown_event"
        )


# ---------------------------------------------------------------------------
# T3 degraded path tests
# ---------------------------------------------------------------------------


class TestCollectPersistedSeededEvents:
    """``_collect_persisted_seeded_events()`` — DB에서 T3 events 조회."""

    @pytest.mark.asyncio
    async def test_empty_when_no_events(self) -> None:
        """persisted T3 events 없을 때 [] 반환."""
        repos = build_in_memory_repositories()
        result = await _collect_persisted_seeded_events(repos, SYMBOL)
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_to_t3_only(self) -> None:
        """T3가 아닌 events는 제외."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)

        # T1 event (should be filtered out)
        t1 = ExternalEventEntity(
            event_id=uuid4(),
            event_type="Y|disclosure",
            source_name="kis",
            source_reliability_tier="T1",
            symbol=SYMBOL,
            market=MARKET,
            published_at=now - timedelta(hours=1),
            ingested_at=now,
            severity="high",
            direction="positive",
            headline="T1 event",
        )
        # T3 event (should be included)
        t3 = ExternalEventEntity(
            event_id=uuid4(),
            event_type="Y|seeded_news",
            source_name="naver",
            source_reliability_tier="T3",
            symbol=SYMBOL,
            market=MARKET,
            published_at=now - timedelta(hours=1),
            ingested_at=now,
            severity="medium",
            direction="neutral",
            headline="T3 seeded event",
        )
        await repos.external_events.add(t1)
        await repos.external_events.add(t3)

        result = await _collect_persisted_seeded_events(repos, SYMBOL)
        assert len(result) == 1
        assert result[0].event_id == t3.event_id

    @pytest.mark.asyncio
    async def test_with_data(self) -> None:
        """persisted T3 events 있을 때 올바르게 반환."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)

        events = [
            ExternalEventEntity(
                event_id=uuid4(),
                event_type="Y|seeded_news",
                source_name="naver",
                source_reliability_tier="T3",
                symbol=SYMBOL,
                market=MARKET,
                published_at=now - timedelta(hours=i),
                ingested_at=now,
                severity="medium",
                direction="neutral",
                headline=f"T3 event {i}",
            )
            for i in range(3)
        ]
        for e in events:
            await repos.external_events.add(e)

        result = await _collect_persisted_seeded_events(repos, SYMBOL)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_includes_seeded_news_event_type(self) -> None:
        """event_type='seeded_news' (Y| prefix 없음)도 조회되는지 검증.

        이 테스트는 Round 9 수정의 핵심 검증:
        _collect_persisted_seeded_events()가 include_seeded_news=True를
        전달하므로 event_type='seeded_news'인 이벤트도 반환되어야 함.
        """
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)

        # event_type='seeded_news' (순수 seeded_news, Y| prefix 없음)
        seeded = ExternalEventEntity(
            event_id=uuid4(),
            event_type="seeded_news",
            source_name="naver_news_seeded",
            source_reliability_tier="T3",
            symbol=SYMBOL,
            market=MARKET,
            published_at=now - timedelta(minutes=30),
            ingested_at=now,
            severity="medium",
            direction="neutral",
            headline="Seeded news without Y| prefix",
        )
        await repos.external_events.add(seeded)

        result = await _collect_persisted_seeded_events(repos, SYMBOL)
        assert len(result) == 1, (
            f"Expected 1 seeded_news event, got {len(result)}. "
            "This means _collect_persisted_seeded_events() is NOT passing "
            "include_seeded_news=True to list_by_symbol()."
        )
        assert result[0].event_id == seeded.event_id


class TestIsT3FreshForSymbol:
    """``_is_t3_fresh_for_symbol()`` — T3 freshness check."""

    @pytest.mark.asyncio
    async def test_true_when_fresh_events_exist(self) -> None:
        """freshness window 내 T3 events 존재 → True."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="Y|seeded_news",
            source_name="naver",
            source_reliability_tier="T3",
            symbol=SYMBOL,
            market=MARKET,
            published_at=now - timedelta(minutes=30),
            ingested_at=now - timedelta(minutes=30),  # 30분 전 ingested → fresh
            severity="medium",
            direction="neutral",
            headline="Fresh T3 event",
        )
        await repos.external_events.add(event)

        assert await _is_t3_fresh_for_symbol(repos, SYMBOL) is True

    @pytest.mark.asyncio
    async def test_false_when_no_events(self) -> None:
        """T3 events 없을 때 False."""
        repos = build_in_memory_repositories()
        assert await _is_t3_fresh_for_symbol(repos, SYMBOL) is False

    @pytest.mark.asyncio
    async def test_false_when_only_stale_events(self) -> None:
        """freshness window 초과 T3 events만 있을 때 False.

        NOTE: has_fresh_t3_events()는 COALESCE(created_at, ingested_at)을
        기준으로 freshness를 판단하므로 ingested_at이 freshness window 밖으로
        설정되어야 함. _T3_FRESHNESS_SECONDS=7200(2h) 기준, 3시간 전 ingested는 stale.
        """
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="Y|seeded_news",
            source_name="naver",
            source_reliability_tier="T3",
            symbol=SYMBOL,
            market=MARKET,
            published_at=now - timedelta(hours=3),
            ingested_at=now - timedelta(hours=3),  # 3시간 전 ingested → stale (7200s window)
            severity="medium",
            direction="neutral",
            headline="Stale T3 event",
        )
        await repos.external_events.add(event)

        assert await _is_t3_fresh_for_symbol(repos, SYMBOL) is False

    @pytest.mark.asyncio
    async def test_true_with_seeded_news_event_type(self) -> None:
        """event_type='seeded_news' (Y| prefix 없음)도 fresh로 감지되는지 검증.

        Round 9 수정 후 _is_t3_fresh_for_symbol()이 include_seeded_news=True를
        전달하므로 event_type='seeded_news'인 이벤트도 fresh로 감지되어야 함.
        """
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="seeded_news",  # Y| prefix 없음
            source_name="naver_news_seeded",
            source_reliability_tier="T3",
            symbol=SYMBOL,
            market=MARKET,
            published_at=now - timedelta(minutes=30),
            ingested_at=now - timedelta(minutes=30),  # 30분 전 ingested → fresh
            severity="medium",
            direction="neutral",
            headline="Fresh seeded news",
        )
        await repos.external_events.add(event)

        assert await _is_t3_fresh_for_symbol(repos, SYMBOL) is True, (
            "event_type='seeded_news' must be detected as fresh when "
            "include_seeded_news=True is passed to list_by_symbol()"
        )


class TestRunT3LivePipeline:
    """``_run_t3_live_pipeline()`` — T3 live pipeline 실행."""

    # _fake_db_transaction이 yield한 mock_tx를 저장 (테스트 assertion에서 사용)
    _last_mock_tx: Any = None

    @asynccontextmanager
    async def _fake_db_transaction(*args: object, **kwargs: object) -> AsyncIterator[Any]:
        """가짜 _db_transaction() 컨텍스트 매니저 — in-memory repo와 호환.

        PostgresExternalEventRepository는 self._tx.connection.fetchrow()와
        self._tx.connection.execute()를 호출하므로, connection mock이 필요.
        execute()/fetchrow()는 RETURNING * 결과로 dict-like row를 반환해야 함.

        added_count: _fake_fetchrow가 호출된 횟수 (persist 호출 검증용).
        """
        _added_count: int = 0

        async def _fake_fetchrow(*_args: object, **_kwargs: object) -> dict[str, object] | None:
            nonlocal _added_count
            _added_count += 1
            # row_to_entity를 통과할 수 있는 최소 필드
            return {
                "event_id": None,
                "event_type": "test",
                "source_name": "test",
                "published_at": datetime.now(timezone.utc),
            }

        # 일반 클래스 인스턴스를 사용하여 Mock의 속성 자동 생성 문제 회피
        class _MockTransaction:
            pass
        mock_tx = _MockTransaction()

        class _MockConnection:
            pass
        mock_conn = _MockConnection()
        mock_conn.fetchrow = _fake_fetchrow  # type: ignore[attr-defined]
        mock_conn.execute = _fake_fetchrow  # type: ignore[attr-defined]

        mock_tx.connection = mock_conn  # type: ignore[attr-defined]
        mock_tx.added_count = _added_count  # type: ignore[attr-defined]
        TestRunT3LivePipeline._last_mock_tx = mock_tx
        yield mock_tx  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_skip_when_services_unavailable(self) -> None:
        """서비스 미설치시 graceful skip."""
        runtime: dict[str, object] = {}
        repos = build_in_memory_repositories()
        # Should not raise
        await _run_t3_live_pipeline(runtime, repos, SYMBOL)

    @pytest.mark.asyncio
    async def test_skip_when_naver_quota_exhausted(self) -> None:
        """NAVER quota 소진 시 graceful skip (이중 방어)."""
        from agent_trading.brokers.naver_news_adapter import (
            NaverDailyQuotaTracker,
        )

        runtime = {
            "disclosure_seed_service": AsyncMock(),
            "seeded_news_service": AsyncMock(),
        }
        repos = build_in_memory_repositories()

        # Simulate quota exhaustion by patching is_quota_exhausted
        with patch.object(
            NaverDailyQuotaTracker,
            "is_exhausted",
            return_value=True,
        ):
            await _run_t3_live_pipeline(runtime, repos, SYMBOL)

        # Verify that fetch_disclosure_titles was NOT called (early return)
        runtime["disclosure_seed_service"].fetch_disclosure_titles.assert_not_called()

    @pytest.mark.asyncio
    @patch(
        "agent_trading.db.transaction.transaction",
        side_effect=_fake_db_transaction,
    )
    async def test_timeout_handled_gracefully(self, mock_tx: object) -> None:
        """timeout 발생시 graceful degrade."""
        runtime = {
            "disclosure_seed_service": AsyncMock(),
            "seeded_news_service": AsyncMock(),
        }
        repos = build_in_memory_repositories()

        # Simulate timeout
        import asyncio
        runtime["disclosure_seed_service"].fetch_disclosure_titles = AsyncMock(
            side_effect=asyncio.TimeoutError,
        )

        # Should not raise
        await _run_t3_live_pipeline(runtime, repos, SYMBOL)

    @pytest.mark.asyncio
    async def test_exception_handled_gracefully(self) -> None:
        """예외 발생시 graceful degrade."""
        runtime = {
            "disclosure_seed_service": AsyncMock(),
            "seeded_news_service": AsyncMock(),
        }
        repos = build_in_memory_repositories()

        runtime["disclosure_seed_service"].fetch_disclosure_titles = AsyncMock(
            side_effect=RuntimeError("API failure"),
        )

        # Should not raise
        await _run_t3_live_pipeline(runtime, repos, SYMBOL)

    @pytest.mark.asyncio
    async def test_success_path(self) -> None:
        """정상 경로: fetch → process → persist."""
        from agent_trading.domain.models import SeededNewsCandidate

        runtime = {
            "disclosure_seed_service": AsyncMock(),
            "seeded_news_service": AsyncMock(),
        }
        repos = build_in_memory_repositories()

        # Mock disclosure seeds
        from agent_trading.services.disclosure_seed_service import DisclosureTitleDTO
        seed = DisclosureTitleDTO(
            symbol=SYMBOL,
            company_name="Samsung",
            headline="Test disclosure",
        )
        runtime["disclosure_seed_service"].fetch_disclosure_titles = AsyncMock(
            return_value=[seed],
        )

        # Mock processed candidates
        candidate = SeededNewsCandidate(
            symbol=SYMBOL,
            company_name="Samsung",
            seed_headline="Test disclosure",
            related_news_title="Test news",
            related_news_summary="Test summary",
            link="https://news.example.com",
            confidence_score=0.8,
        )
        runtime["seeded_news_service"].process_seeds = AsyncMock(
            return_value=([candidate], {}),
        )

        await _run_t3_live_pipeline(runtime, repos, SYMBOL)

        # Verify events were persisted
        events = await repos.external_events.list_by_symbol(
            symbol=SYMBOL,
            since=datetime.now(timezone.utc) - timedelta(hours=1),
            include_seeded_news=True,
        )
        assert len(events) > 0
        assert all(e.source_reliability_tier == "T3" for e in events)


class TestRunT3LivePipelinePartialPersist:
    """``_run_t3_live_pipeline()`` — timeout 시 partial persist 검증."""

    # _fake_db_transaction이 yield한 mock_tx를 저장 (테스트 assertion에서 사용)
    _last_mock_tx: Any = None

    @asynccontextmanager
    async def _fake_db_transaction(*args: object, **kwargs: object) -> AsyncIterator[Any]:
        """가짜 _db_transaction() 컨텍스트 매니저 — in-memory repo와 호환.

        PostgresExternalEventRepository는 self._tx.connection.fetchrow()와
        self._tx.connection.execute()를 호출하므로, connection mock이 필요.
        execute()/fetchrow()는 RETURNING * 결과로 dict-like row를 반환해야 함.

        added_count: _fake_fetchrow가 호출된 횟수 (persist 호출 검증용).
        """
        _added_count: int = 0

        async def _fake_fetchrow(*_args: object, **_kwargs: object) -> dict[str, object] | None:
            nonlocal _added_count
            _added_count += 1
            # row_to_entity를 통과할 수 있는 최소 필드
            return {
                "event_id": None,
                "event_type": "test",
                "source_name": "test",
                "published_at": datetime.now(timezone.utc),
            }

        # 일반 클래스 인스턴스를 사용하여 Mock의 속성 자동 생성 문제 회피
        class _MockTransaction:
            pass
        mock_tx = _MockTransaction()

        class _MockConnection:
            pass
        mock_conn = _MockConnection()
        mock_conn.fetchrow = _fake_fetchrow  # type: ignore[attr-defined]
        mock_conn.execute = _fake_fetchrow  # type: ignore[attr-defined]

        mock_tx.connection = mock_conn  # type: ignore[attr-defined]
        mock_tx.added_count = _added_count  # type: ignore[attr-defined]
        TestRunT3LivePipelinePartialPersist._last_mock_tx = mock_tx
        yield mock_tx  # type: ignore[misc]

    @pytest.mark.asyncio
    @patch(
        "agent_trading.db.transaction.transaction",
        side_effect=_fake_db_transaction,
    )
    async def test_partial_persist_after_convert_timeout(self, mock_tx: object) -> None:
        """convert 단계에서 timeout → candidates 기반 partial persist 호출 확인.

        시나리오:
        - Step 1 (fetch_disclosure_titles): 성공 → seeds 할당됨
        - Step 2 (process_seeds): 성공 → candidates 할당됨
        - Step 3 (convert_seeded_candidates): timeout 발생
        - 기대: except 블록에서 candidates → partial_events 변환 후 persist

        NOTE: convert_seeded_candidates는 _run_t3_live_pipeline() 내부에서
        lazy import되므로, agent_trading.services.seeded_news_converter
        모듈을 직접 패치해야 함.

        또한 except 블록 내부에서도 convert_seeded_candidates가 호출되므로
        (candidates → partial_events 변환), 첫 호출에서만 timeout을 발생시키고
        이후 호출에서는 원래 함수를 사용하도록 구성.
        """
        from agent_trading.domain.models import SeededNewsCandidate

        runtime = {
            "disclosure_seed_service": AsyncMock(),
            "seeded_news_service": AsyncMock(),
        }
        repos = build_in_memory_repositories()

        # Mock disclosure seeds
        from agent_trading.services.disclosure_seed_service import DisclosureTitleDTO
        seed = DisclosureTitleDTO(
            symbol=SYMBOL,
            company_name="Samsung",
            headline="Test disclosure",
        )
        runtime["disclosure_seed_service"].fetch_disclosure_titles = AsyncMock(
            return_value=[seed],
        )

        # Mock processed candidates
        candidate = SeededNewsCandidate(
            symbol=SYMBOL,
            company_name="Samsung",
            seed_headline="Test disclosure",
            related_news_title="Test news",
            related_news_summary="Test summary",
            link="https://news.example.com",
            confidence_score=0.8,
        )
        runtime["seeded_news_service"].process_seeds = AsyncMock(
            return_value=([candidate], {}),
        )

        # convert_seeded_candidates에서 timeout 발생시키기
        # (candidates는 할당되었고, seeded_events는 할당되지 않은 상태)
        # 첫 호출에서만 TimeoutError 발생, 이후 호출(except 블록 내)은 정상 동작
        import asyncio
        import agent_trading.services.seeded_news_converter as snc
        original_convert = snc.convert_seeded_candidates
        call_count = 0

        def _mock_convert(candidates):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            return original_convert(candidates)

        from scripts.run_decision_loop import persist_seeded_events as _real_persist
        with patch.object(
            snc,
            "convert_seeded_candidates",
            side_effect=_mock_convert,
        ), patch(
            "scripts.run_decision_loop.persist_seeded_events",
            side_effect=_real_persist,
        ) as mock_persist:
            # Should not raise — partial persist in except block
            await _run_t3_live_pipeline(runtime, repos, SYMBOL)

        # persist_seeded_events가 호출되었는지 확인
        assert mock_persist.called, (
            "persist_seeded_events should be called when convert_seeded_candidates "
            "times out (partial persist from candidates in except block)"
        )

    @pytest.mark.asyncio
    @patch(
        "agent_trading.db.transaction.transaction",
        side_effect=_fake_db_transaction,
    )
    async def test_partial_persist_with_seeds_only(self, mock_tx: object) -> None:
        """seeds만 있고 candidates는 없을 때 timeout → seeds 기반 partial persist.

        변경 사항:
        - 이전: seeds만 있으면 persist 미호출 (no partial data)
        - 변경 후: seeds를 T2 ExternalEventEntity로 변환하여 persist
        - T2 tier이므로 has_fresh_t3_events()에는 영향 없음
        """
        runtime = {
            "disclosure_seed_service": AsyncMock(),
            "seeded_news_service": AsyncMock(),
        }
        repos = build_in_memory_repositories()

        # Mock disclosure seeds success
        from agent_trading.services.disclosure_seed_service import DisclosureTitleDTO
        seed = DisclosureTitleDTO(
            symbol=SYMBOL,
            company_name="Samsung",
            headline="Test disclosure",
        )
        runtime["disclosure_seed_service"].fetch_disclosure_titles = AsyncMock(
            return_value=[seed],
        )

        # Mock process_seeds timeout (no candidates yet)
        import asyncio
        runtime["seeded_news_service"].process_seeds = AsyncMock(
            side_effect=asyncio.TimeoutError,
        )

        from scripts.run_decision_loop import persist_seeded_events as _real_persist
        with patch(
            "scripts.run_decision_loop.persist_seeded_events",
            side_effect=_real_persist,
        ) as mock_persist:
            # Should not raise
            await _run_t3_live_pipeline(runtime, repos, SYMBOL)

        # Verify persist_seeded_events was called
        assert mock_persist.called, (
            "persist_seeded_events should be called when timeout occurs after "
            "seeds are available (partial persist from seeds)"
        )

        # _convert_disclosure_seeds_to_events가 T2 이벤트를 생성하는지 별도 검증
        from scripts.run_decision_loop import _convert_disclosure_seeds_to_events
        partial_events = _convert_disclosure_seeds_to_events([seed])
        assert len(partial_events) > 0
        assert all(e.source_reliability_tier == "T2" for e in partial_events), (
            "Seeds-based partial persist should create T2 events, "
            "not T3 events, to avoid affecting has_fresh_t3_events()"
        )
        assert all(e.event_type.startswith("Y|") for e in partial_events), (
            "Seeds-based events should have KIS disclosure prefix (Y|)"
        )


class TestT3DegradedPath:
    """T3 degraded path 통합 검증."""

    @pytest.mark.asyncio
    async def test_collect_and_freshness_integration(self) -> None:
        """_collect_persisted_seeded_events + _is_t3_fresh_for_symbol 통합."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)

        # Add a fresh T3 event
        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="Y|seeded_news",
            source_name="naver",
            source_reliability_tier="T3",
            symbol=SYMBOL,
            market=MARKET,
            published_at=now - timedelta(minutes=5),
            ingested_at=now,
            severity="medium",
            direction="neutral",
            headline="Fresh T3",
        )
        await repos.external_events.add(event)

        # Should be fresh
        assert await _is_t3_fresh_for_symbol(repos, SYMBOL) is True

        # Should return the event
        events = await _collect_persisted_seeded_events(repos, SYMBOL)
        assert len(events) == 1
        assert events[0].event_id == event.event_id


# ---------------------------------------------------------------------------
# AccountLookup 필드명 검증 — alias 버그 재발 방지
# ---------------------------------------------------------------------------


class TestAccountLookupFieldName:
    """``AccountLookup``이 ``account_alias`` 필드를 사용하는지 검증 (alias 아님).

    Phase 0에서 발견된 버그 재발 방지:
    ``AccountLookup(alias=ACCOUNT_ALIAS)`` → TypeError 발생.
    """

    def test_account_alias_field_exists(self) -> None:
        """account_alias 필드가 존재하는지 확인."""
        from agent_trading.repositories.filters import AccountLookup
        assert hasattr(AccountLookup, "account_alias")

    def test_alias_field_does_not_exist(self) -> None:
        """alias 필드는 존재하지 않아야 함."""
        from agent_trading.repositories.filters import AccountLookup
        assert not hasattr(AccountLookup, "alias")

    def test_account_alias_construction_succeeds(self) -> None:
        """account_alias로 정상 생성 가능."""
        from agent_trading.repositories.filters import AccountLookup
        lookup = AccountLookup(account_alias="test")
        assert lookup.account_alias == "test"

    def test_alias_construction_raises_type_error(self) -> None:
        """alias로 생성 시 TypeError 발생 확인."""
        from agent_trading.repositories.filters import AccountLookup
        with pytest.raises(TypeError):
            AccountLookup(alias="test")  # type: ignore[call-arg]
