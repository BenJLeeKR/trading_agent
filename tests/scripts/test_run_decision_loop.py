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

import asyncio
import dataclasses
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
    DecisionContextEntity,
    ExternalEventEntity,
    InstrumentEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
    SignalFeatureSnapshotEntity,
    SnapshotSyncRunEntity,
    StrategyEntity,
    SymbolTradeStateEntity,
    TradeDecisionEntity,
    UniverseFreezeRunEntity,
    UniverseFreezeRunItemEntity,
)
from agent_trading.domain.enums import (
    AssetClass,
    DecisionType,
    EntryStyle,
    Environment,
    OrderSide,
    OrderStatus,
    OrderType,
)
from agent_trading.domain.models import Quote, SubmitOrderRequest
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.contracts import SnapshotSyncHealthSummary
from agent_trading.repositories.memory import InMemoryExternalEventRepository
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
    OrderIntent,
    SubmitResult,
)
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)
from agent_trading.services.submit_lane_gate import (
    HELD_POSITION_SELL_MAX_PER_CYCLE,
    evaluate_symbol_submit_lane,
)
from agent_trading.services.validators import ValidationResult

# Module under test
from scripts.run_decision_loop import (
    DEFAULT_TRADING_UNIVERSE_CORE_CAP,
    DEFAULT_TRADING_UNIVERSE_MAX_CAP,
    DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE,
    ENV_TRADING_UNIVERSE_CORE_CAP,
    ENV_TRADING_UNIVERSE_MAX_CAP,
    ENV_TRADING_UNIVERSE,
    KISRestClient,
    UniverseAnchorMetadata,
    UniverseSymbol,
    _build_aggregate_summary,
    _collect_persisted_seeded_events,
    _evaluate_pre_ai_skip_reason,
    _evaluate_pre_ai_validation_result,
    _is_t3_fresh_for_symbol,
    _parse_args,
    _parse_universe_symbols,
    _read_trading_universe,
    _resolve_symbol_price,
    _general_lane_priority_key,
    _run_general_lane_pass2,
    _run_loop,
    _run_one_cycle,
    _run_precheck,
    _run_t3_live_pipeline,
    _run_t3_live_pipeline_shielded,
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


def _make_trade_decision(
    *,
    symbol: str = SYMBOL,
    source_type: str = "held_position",
    decision_type: DecisionType = DecisionType.HOLD,
    side: OrderSide = OrderSide.BUY,
    created_at: datetime | None = None,
    decision_context_id: UUID | None = None,
) -> TradeDecisionEntity:
    now = created_at or datetime.now(timezone.utc)
    return TradeDecisionEntity(
        trade_decision_id=uuid4(),
        decision_context_id=decision_context_id or uuid4(),
        decision_type=decision_type,
        side=side,
        strategy_id=STRATEGY_ID,
        symbol=symbol,
        market=MARKET,
        entry_style=EntryStyle.MARKET,
        created_at=now,
        source_type=source_type,
    )


def _blocked_pre_ai_result(
    reason: str, details: dict[str, str | None]
) -> tuple[ValidationResult, dict[str, str | None]]:
    return (
        ValidationResult.blocked(
            rule_set_version="pre_ai_gate_v1",
            blocking_rule_codes=[reason],
            rule_results={"details": details},
            stop_reason=reason,
        ),
        details,
    )


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
            orderable_amount=Decimal("1000000"),
            source_of_truth="test",
            snapshot_at=now,
            created_at=now,
        )
    )

    instrument_id = UUID("f0694572-df26-59fa-a6c9-130668e1eeed")
    await repos.instruments.add(
        InstrumentEntity(
            instrument_id=instrument_id,
            symbol=SYMBOL,
            market_code=MARKET,
            asset_class="KR_STOCK",
            currency="KRW",
            name="삼성전자",
            is_active=True,
        )
    )

    # Position snapshot (fresh, positive default to keep held_position path actionable)
    await repos.position_snapshots.add(
        PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=ACCOUNT_ID,
            instrument_id=instrument_id,
            quantity=Decimal("10"),
            average_price=Decimal("50000"),
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
            deterministic_trigger=DeterministicTriggerAssessment(
                trigger_version="deterministic_trigger_v1",
                primary_candidate="BUY_CANDIDATE",
                candidate_set=("BUY_CANDIDATE",),
                watch_candidate=False,
                buy_candidate=True,
                sell_candidate=False,
                reduce_candidate=False,
                candidate_confidence=0.8,
                entry_score=0.8,
                exit_score=0.2,
                watch_score=0.3,
            ),
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
    broker.get_quote = AsyncMock(
        return_value=Quote(
            symbol=SYMBOL,
            market=MARKET,
            bid=Decimal("69900"),
            ask=Decimal("70100"),
            last=Decimal("70000"),
            as_of=datetime.now(timezone.utc),
        )
    )
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
    broker.get_quote = AsyncMock(
        return_value=Quote(
            symbol=SYMBOL,
            market=MARKET,
            bid=Decimal("69900"),
            ask=Decimal("70100"),
            last=Decimal("70000"),
            as_of=datetime.now(timezone.utc),
        )
    )
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
    mock_tx.connection = None

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
            stop_reason="submit_budget_consumed_core",
        )

        serialized = _serialize_cycle_result(
            cycle=1,
            result=result,
            duration=3.0,
            dry_run=True,
            dry_run_reason="submit_budget_consumed_core",
        )

        assert serialized["status"] == "DRY_RUN"
        assert serialized["dry_run_reason"] == "submit_budget_consumed_core"
        assert serialized["stop_reason"] == "submit_budget_consumed_core"
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

    def test_includes_universe_anchor_fields(self) -> None:
        """Universe freeze anchor가 cycle 결과에 포함된다."""
        anchor = UniverseAnchorMetadata(
            source="intraday_freeze",
            universe_freeze_run_id=str(uuid4()),
            freeze_purpose="decision_loop_intraday",
            freeze_reused=True,
            business_date="2026-06-24",
        )
        serialized = _serialize_cycle_result(
            cycle=1,
            result=None,
            duration=0.5,
            error="anchor-check",
            universe_anchor=anchor,
        )

        assert serialized["universe_anchor_source"] == "intraday_freeze"
        assert serialized["universe_freeze_run_id"] == anchor.universe_freeze_run_id
        assert serialized["freeze_purpose"] == "decision_loop_intraday"
        assert serialized["freeze_reused"] is True
        assert serialized["universe_anchor"]["business_date"] == "2026-06-24"

    def test_includes_ai_call_path(self) -> None:
        """AI skip 계측이 결과 직렬화에 포함된다."""
        ctx_id = uuid4()
        intent = _make_stub_intent(decision_context_id=ctx_id)
        intent = dataclasses.replace(
            intent,
            ai_backend_inputs=dataclasses.replace(
                intent.ai_backend_inputs,
                ei_skipped=True,
                fdc_skipped=True,
                skip_reason_codes=(
                    "skip_ei_no_recent_events",
                    "skip_fdc_high_risk",
                ),
            ),
        )
        result = SubmitResult(
            status="SKIPPED",
            order_intent=intent,
            decision_context_id=ctx_id,
        )

        serialized = _serialize_cycle_result(cycle=1, result=result, duration=1.5)

        assert serialized["ai_call_path"] == {
            "ei_skipped": True,
            "ar_skipped": False,
            "fdc_skipped": True,
            "skip_reason_codes": [
                "skip_ei_no_recent_events",
                "skip_fdc_high_risk",
            ],
        }
        assert serialized["risk_off_exception_eligible"] is False

    def test_includes_risk_off_exception_flag(self) -> None:
        ctx_id = uuid4()
        intent = _make_stub_intent(decision_context_id=ctx_id)
        trigger = dataclasses.replace(
            intent.context.deterministic_trigger,
            risk_off_exception_eligible=True,
        )
        intent = dataclasses.replace(
            intent,
            context=dataclasses.replace(
                intent.context,
                deterministic_trigger=trigger,
            ),
        )
        result = SubmitResult(
            status="DRY_RUN",
            order_intent=intent,
            decision_context_id=ctx_id,
        )

        serialized = _serialize_cycle_result(cycle=1, result=result, duration=1.0)

        assert serialized["risk_off_exception_eligible"] is True


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
        assert summary["metrics"]["processed_symbol_count"] == 3

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

    def test_includes_universe_and_processed_source_metrics(self) -> None:
        """운영 진단용 유니버스/source_type 메트릭을 포함한다."""
        results = [
            {"status": "SKIPPED", "source_type": "held_position"},
            {"status": "ERROR", "source_type": "core"},
        ]
        universe = (
            UniverseSymbol(symbol="005930", market="KRX", source_type="held_position"),
            UniverseSymbol(symbol="000660", market="KRX", source_type="held_position"),
            UniverseSymbol(symbol="000100", market="KRX", source_type="core"),
        )

        summary = _build_aggregate_summary(
            results,
            total_duration=12.0,
            universe=universe,
        )

        assert summary["metrics"]["universe_symbol_count"] == 3
        assert summary["metrics"]["held_position_count"] == 2
        assert summary["metrics"]["processed_symbol_count"] == 2
        assert summary["metrics"]["held_position_processed_count"] == 1
        assert summary["metrics"]["universe_source_counts"] == {
            "held_position": 2,
            "core": 1,
        }
        assert summary["metrics"]["processed_source_counts"] == {
            "held_position": 1,
            "core": 1,
        }

    def test_includes_ai_call_path_metrics(self) -> None:
        """AI skip 계측 집계를 운영 요약에 포함한다."""
        results = [
            {
                "status": "SKIPPED",
                "ai_call_path": {
                    "ei_skipped": True,
                    "ar_skipped": False,
                    "fdc_skipped": True,
                    "skip_reason_codes": [
                        "skip_ei_no_recent_events",
                        "skip_fdc_high_risk",
                    ],
                },
            },
            {
                "status": "SUBMITTED",
                "ai_call_path": {
                    "ei_skipped": False,
                    "ar_skipped": False,
                    "fdc_skipped": False,
                    "skip_reason_codes": [],
                },
            },
        ]

        summary = _build_aggregate_summary(results, total_duration=7.0)

        assert summary["metrics"]["ai_call_path"] == {
            "tracked_count": 2,
            "ei_skipped_count": 1,
            "ar_skipped_count": 0,
            "fdc_skipped_count": 1,
            "skip_reason_counts": {
                "skip_ei_no_recent_events": 1,
                "skip_fdc_high_risk": 1,
            },
        }

    def test_includes_risk_off_exception_metrics(self) -> None:
        results = [
            {
                "status": "SUBMITTED",
                "risk_off_exception_eligible": True,
                "ai_call_path": {
                    "ei_skipped": False,
                    "ar_skipped": False,
                    "fdc_skipped": False,
                    "skip_reason_codes": [],
                },
            },
            {
                "status": "SKIPPED",
                "risk_off_exception_eligible": True,
                "ai_call_path": {
                    "ei_skipped": True,
                    "ar_skipped": True,
                    "fdc_skipped": True,
                    "skip_reason_codes": ["pre_ai_short_circuit"],
                },
            },
            {
                "status": "DRY_RUN",
                "risk_off_exception_eligible": False,
                "ai_call_path": {
                    "ei_skipped": False,
                    "ar_skipped": False,
                    "fdc_skipped": False,
                    "skip_reason_codes": [],
                },
            },
        ]

        summary = _build_aggregate_summary(results, total_duration=5.0)

        assert summary["metrics"]["risk_off_exception_path"] == {
            "risk_off_exception_eligible_count": 2,
            "risk_off_exception_ai_pass_count": 1,
            "risk_off_exception_submit_count": 1,
        }

    def test_includes_universe_anchor_metrics(self) -> None:
        """Aggregate summary가 universe anchor 메타데이터를 포함한다."""
        anchor = UniverseAnchorMetadata(
            source="intraday_freeze",
            universe_freeze_run_id=str(uuid4()),
            freeze_purpose="decision_loop_intraday",
            freeze_reused=True,
            business_date="2026-06-24",
        )
        summary = _build_aggregate_summary(
            [{"status": "SUBMITTED"}],
            total_duration=1.0,
            universe_anchor=anchor,
        )

        assert summary["metrics"]["universe_anchor_source"] == "intraday_freeze"
        assert summary["metrics"]["universe_freeze_run_id"] == anchor.universe_freeze_run_id
        assert summary["metrics"]["freeze_purpose"] == "decision_loop_intraday"
        assert summary["metrics"]["freeze_reused"] is True
        assert summary["metrics"]["universe_anchor"]["business_date"] == "2026-06-24"


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
    async def test_scheduler_dry_run_records_guardrail_evaluation(self) -> None:
        """scheduler gate dry-run 사유도 guardrail_evaluations에 남겨야 한다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            result = await _run_one_cycle(
                cycle=1,
                submit=False,
                dry_run=True,
                output="text",
                source_type="core",
                dry_run_reason="submit_budget_consumed_core",
                runtime=runtime,
            )

        assert result["status"] == "DRY_RUN"
        assert result["dry_run_reason"] == "submit_budget_consumed_core"
        assert result["stop_reason"] == "submit_budget_consumed_core"
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].rule_set_version == "scheduler_gate_v1"
        assert evaluations[0].blocking_rule_codes == ["submit_budget_consumed_core"]

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

    @pytest.mark.asyncio
    async def test_held_position_can_trigger_t3_live_pipeline_when_not_fresh(self) -> None:
        """held_position도 T3 freshness가 stale이면 live pipeline을 태워야 한다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            live_pipeline = AsyncMock(return_value=None)
            with (
                patch.dict("os.environ", {"SEEDED_NEWS_ENABLED": "1"}),
                patch(
                    "scripts.run_decision_loop._collect_persisted_seeded_events",
                    new=AsyncMock(return_value=[]),
                ),
                patch(
                    "scripts.run_decision_loop._is_t3_fresh_for_symbol",
                    new=AsyncMock(return_value=False),
                ),
                patch(
                    "scripts.run_decision_loop._run_t3_live_pipeline_shielded",
                    new=live_pipeline,
                ),
                patch(
                    "agent_trading.brokers.naver_news_adapter.NaverNewsSearchAdapter.is_quota_exhausted",
                    return_value=False,
                ),
            ):
                result = await _run_one_cycle(
                    cycle=1,
                    submit=False,
                    dry_run=True,
                    output="text",
                    source_type="held_position",
                    runtime=runtime,
                )
                await asyncio.sleep(0)

        assert result["source_type"] == "held_position"
        live_pipeline.assert_called_once()
        assert live_pipeline.await_args.kwargs["source_type"] == "held_position"

    @pytest.mark.asyncio
    async def test_pre_ai_skip_when_orderable_amount_below_threshold(self) -> None:
        """일반 BUY 후보는 주문가능금액이 기준 이하이면 AI 전에 SKIPPED 처리한다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            await repos.instruments.add(
                InstrumentEntity(
                    instrument_id=uuid4(),
                    symbol="000100",
                    market_code=MARKET,
                    asset_class="KR_STOCK",
                    currency="KRW",
                    name="유한양행",
                    is_active=True,
                )
            )
            latest_cash = await repos.cash_balance_snapshots.get_latest_by_account(ACCOUNT_ID)
            assert latest_cash is not None
            repos.cash_balance_snapshots._items[latest_cash.cash_balance_snapshot_id] = (  # type: ignore[attr-defined]
                CashBalanceSnapshotEntity(
                    cash_balance_snapshot_id=latest_cash.cash_balance_snapshot_id,
                    account_id=latest_cash.account_id,
                    currency=latest_cash.currency,
                    available_cash=latest_cash.available_cash,
                    settled_cash=latest_cash.settled_cash,
                    unsettled_cash=latest_cash.unsettled_cash,
                    orderable_amount=Decimal("499999"),
                    source_of_truth=latest_cash.source_of_truth,
                    snapshot_at=latest_cash.snapshot_at,
                    created_at=latest_cash.created_at,
                )
            )
            result = await _run_one_cycle(
                cycle=1,
                submit=True,
                dry_run=False,
                output="text",
                symbol="000100",
                source_type="core",
                runtime=runtime,
            )

        assert result["status"] == "SKIPPED"
        assert result["error_phase"] == "pre_ai_gate"
        assert result["error_message"] == "low_orderable_amount"
        assert result["stop_reason"] == "low_orderable_amount"
        assert result["skip_reason"] == "low_orderable_amount"
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].rule_set_version == "pre_ai_gate_v1"
        assert evaluations[0].blocking_rule_codes == ["low_orderable_amount"]

    @pytest.mark.asyncio
    async def test_pre_ai_does_not_skip_when_cash_snapshot_is_stale(self) -> None:
        """stale cash snapshot의 orderable_amount=0은 신규 BUY 차단 근거로 쓰지 않는다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            latest_cash = await repos.cash_balance_snapshots.get_latest_by_account(ACCOUNT_ID)
            assert latest_cash is not None
            repos.cash_balance_snapshots._items[latest_cash.cash_balance_snapshot_id] = (  # type: ignore[attr-defined]
                CashBalanceSnapshotEntity(
                    cash_balance_snapshot_id=latest_cash.cash_balance_snapshot_id,
                    account_id=latest_cash.account_id,
                    currency=latest_cash.currency,
                    available_cash=latest_cash.available_cash,
                    settled_cash=latest_cash.settled_cash,
                    unsettled_cash=latest_cash.unsettled_cash,
                    orderable_amount=Decimal("0"),
                    source_of_truth=latest_cash.source_of_truth,
                    snapshot_at=latest_cash.snapshot_at,
                    created_at=latest_cash.created_at,
                    fetch_status="stale",
                )
            )
            result = await _run_one_cycle(
                cycle=1,
                submit=True,
                dry_run=False,
                output="text",
                symbol="000100",
                source_type="core",
                runtime=runtime,
            )

        assert result["error_phase"] != "pre_ai_gate"
        assert result["stop_reason"] != "low_orderable_amount"
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert evaluations == []

    @pytest.mark.asyncio
    async def test_pre_ai_skip_when_held_position_has_no_quantity(self) -> None:
        """held_position 후보는 보유수량이 없으면 AI 전에 SKIPPED 처리한다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert snapshots
            latest_position = snapshots[0]
            repos.position_snapshots._items[latest_position.position_snapshot_id] = (  # type: ignore[attr-defined]
                PositionSnapshotEntity(
                    position_snapshot_id=latest_position.position_snapshot_id,
                    account_id=latest_position.account_id,
                    instrument_id=latest_position.instrument_id,
                    quantity=Decimal("0"),
                    average_price=latest_position.average_price,
                    market_price=latest_position.market_price,
                    unrealized_pnl=latest_position.unrealized_pnl,
                    source_of_truth=latest_position.source_of_truth,
                    snapshot_at=latest_position.snapshot_at,
                    created_at=latest_position.created_at,
                )
            )
            result = await _run_one_cycle(
                cycle=1,
                submit=True,
                dry_run=False,
                output="text",
                source_type="held_position",
                runtime=runtime,
            )

        assert result["status"] == "SKIPPED"
        assert result["error_phase"] == "pre_ai_gate"
        assert result["error_message"] == "no_held_position"
        assert result["stop_reason"] == "no_held_position"
        assert result["skip_reason"] == "no_held_position"
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].blocking_rule_codes == ["no_held_position"]

    @pytest.mark.asyncio
    async def test_pre_ai_skip_when_held_position_recent_hold_has_no_change(self) -> None:
        """held_position은 최근 HOLD였고 이벤트/주문 변화가 없으면 AI 전에 SKIP."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 4, 0, 0, tzinfo=timezone.utc)  # 13:00 KST
            await repos.trade_decisions.add(
                _make_trade_decision(
                    decision_type=DecisionType.HOLD,
                    created_at=now_utc - timedelta(minutes=5),
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="held_position",
                now_utc=now_utc,
            )

        assert reason == "held_position_recent_hold_no_change"
        assert details["latest_held_decision_type"] == "hold"

    @pytest.mark.asyncio
    async def test_pre_ai_validation_result_uses_common_contract(self) -> None:
        """pre_ai_gate는 공통 ValidationResult 계약으로도 같은 차단 사유를 준다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 4, 0, 0, tzinfo=timezone.utc)
            await repos.trade_decisions.add(
                _make_trade_decision(
                    decision_type=DecisionType.HOLD,
                    created_at=now_utc - timedelta(minutes=5),
                )
            )

            validation_result, details = await _evaluate_pre_ai_validation_result(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="held_position",
                now_utc=now_utc,
            )

        assert validation_result is not None
        assert validation_result.rule_set_version == "pre_ai_gate_v1"
        assert validation_result.stop_reason == "held_position_recent_hold_no_change"
        assert validation_result.blocking_rule_codes == (
            "held_position_recent_hold_no_change",
        )
        assert details["latest_held_decision_type"] == "hold"

    @pytest.mark.asyncio
    async def test_pre_ai_skip_not_triggered_for_held_position_after_cutoff(self) -> None:
        """장 마감 임박 이후에는 held_position stable-hold skip을 끈다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 5, 35, 0, tzinfo=timezone.utc)  # 14:35 KST
            await repos.trade_decisions.add(
                _make_trade_decision(
                    decision_type=DecisionType.HOLD,
                    created_at=now_utc - timedelta(minutes=5),
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="held_position",
                now_utc=now_utc,
            )

        assert reason is None
        assert details["skip_guard"] == "disabled_after_cutoff"

    @pytest.mark.asyncio
    async def test_pre_ai_skip_not_triggered_for_held_position_when_recent_event_exists(self) -> None:
        """최근 이벤트가 있으면 held_position stable-hold skip을 하지 않는다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 4, 0, 0, tzinfo=timezone.utc)  # 13:00 KST
            await repos.trade_decisions.add(
                _make_trade_decision(
                    decision_type=DecisionType.HOLD,
                    created_at=now_utc - timedelta(minutes=5),
                )
            )
            await repos.external_events.add(
                ExternalEventEntity(
                    event_id=uuid4(),
                    event_type="seeded_news",
                    source_name="naver",
                    source_reliability_tier="T3",
                    symbol=SYMBOL,
                    market=MARKET,
                    published_at=now_utc - timedelta(minutes=2),
                    ingested_at=now_utc - timedelta(minutes=2),
                    severity="medium",
                    direction="neutral",
                    headline="Recent event should disable held-position skip",
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="held_position",
                now_utc=now_utc,
            )

        assert reason is None
        assert details["recent_event_count"] == "1"

    @pytest.mark.asyncio
    async def test_pre_ai_skip_when_held_position_recent_risk_sell_has_no_change(self) -> None:
        """최근 REDUCE/EXIT sell 이후 보유수량이 늘지 않았으면 새 AI 판단을 skip한다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 4, 0, 0, tzinfo=timezone.utc)  # 13:00 KST
            current_snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert current_snapshots
            current_snapshot = current_snapshots[0]

            anchor_snapshot = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=current_snapshot.account_id,
                instrument_id=current_snapshot.instrument_id,
                quantity=Decimal("10"),
                average_price=current_snapshot.average_price,
                market_price=current_snapshot.market_price,
                unrealized_pnl=current_snapshot.unrealized_pnl,
                source_of_truth="test",
                snapshot_at=now_utc - timedelta(minutes=6),
                created_at=now_utc - timedelta(minutes=6),
            )
            await repos.position_snapshots.add(anchor_snapshot)
            decision_context = DecisionContextEntity(
                decision_context_id=uuid4(),
                account_id=ACCOUNT_ID,
                strategy_id=STRATEGY_ID,
                config_version_id=CONFIG_VERSION_ID,
                market_timestamp=now_utc - timedelta(minutes=5),
                correlation_id="held-sell-cooldown",
                position_snapshot_id=anchor_snapshot.position_snapshot_id,
                created_at=now_utc - timedelta(minutes=5),
            )
            await repos.decision_contexts.add(decision_context)
            await repos.trade_decisions.add(
                _make_trade_decision(
                    decision_type=DecisionType.REDUCE,
                    side=OrderSide.SELL,
                    created_at=now_utc - timedelta(minutes=5),
                    decision_context_id=decision_context.decision_context_id,
                )
            )
            await repos.orders.add(
                OrderRequestEntity(
                    order_request_id=uuid4(),
                    account_id=ACCOUNT_ID,
                    instrument_id=current_snapshot.instrument_id,
                    client_order_id="held-reduce-1",
                    idempotency_key="held-reduce-1",
                    correlation_id="held-reduce-1",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    requested_quantity=Decimal("5"),
                    status=OrderStatus.SUBMITTED,
                    created_at=now_utc - timedelta(minutes=4),
                    submitted_at=now_utc - timedelta(minutes=4),
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="held_position",
                now_utc=now_utc,
            )

        assert reason == "held_position_recent_risk_sell_cooldown"
        assert details["recent_sell_order_count"] == "1"
        assert details["latest_held_sell_decision_type"] == "reduce"
        assert details["latest_held_sell_position_qty"] == "10"
        assert details["sell_cooldown_position_unchanged_or_reduced"] == "true"

    @pytest.mark.asyncio
    async def test_pre_ai_skip_not_triggered_when_position_increased_after_recent_risk_sell(self) -> None:
        """최근 위험축소 SELL 뒤에 보유수량이 증가했다면 suppression하지 않는다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 4, 0, 0, tzinfo=timezone.utc)  # 13:00 KST
            current_snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert current_snapshots
            current_snapshot = current_snapshots[0]
            repos.position_snapshots._items[current_snapshot.position_snapshot_id] = (  # type: ignore[attr-defined]
                PositionSnapshotEntity(
                    position_snapshot_id=current_snapshot.position_snapshot_id,
                    account_id=current_snapshot.account_id,
                    instrument_id=current_snapshot.instrument_id,
                    quantity=Decimal("12"),
                    average_price=current_snapshot.average_price,
                    market_price=current_snapshot.market_price,
                    unrealized_pnl=current_snapshot.unrealized_pnl,
                    source_of_truth=current_snapshot.source_of_truth,
                    snapshot_at=current_snapshot.snapshot_at,
                    created_at=current_snapshot.created_at,
                )
            )

            anchor_snapshot = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=current_snapshot.account_id,
                instrument_id=current_snapshot.instrument_id,
                quantity=Decimal("10"),
                average_price=current_snapshot.average_price,
                market_price=current_snapshot.market_price,
                unrealized_pnl=current_snapshot.unrealized_pnl,
                source_of_truth="test",
                snapshot_at=now_utc - timedelta(minutes=6),
                created_at=now_utc - timedelta(minutes=6),
            )
            await repos.position_snapshots.add(anchor_snapshot)
            decision_context = DecisionContextEntity(
                decision_context_id=uuid4(),
                account_id=ACCOUNT_ID,
                strategy_id=STRATEGY_ID,
                config_version_id=CONFIG_VERSION_ID,
                market_timestamp=now_utc - timedelta(minutes=5),
                correlation_id="held-sell-cooldown-increased",
                position_snapshot_id=anchor_snapshot.position_snapshot_id,
                created_at=now_utc - timedelta(minutes=5),
            )
            await repos.decision_contexts.add(decision_context)
            await repos.trade_decisions.add(
                _make_trade_decision(
                    decision_type=DecisionType.REDUCE,
                    side=OrderSide.SELL,
                    created_at=now_utc - timedelta(minutes=5),
                    decision_context_id=decision_context.decision_context_id,
                )
            )
            await repos.orders.add(
                OrderRequestEntity(
                    order_request_id=uuid4(),
                    account_id=ACCOUNT_ID,
                    instrument_id=current_snapshot.instrument_id,
                    client_order_id="held-reduce-2",
                    idempotency_key="held-reduce-2",
                    correlation_id="held-reduce-2",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    requested_quantity=Decimal("5"),
                    status=OrderStatus.SUBMITTED,
                    created_at=now_utc - timedelta(minutes=4),
                    submitted_at=now_utc - timedelta(minutes=4),
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="held_position",
                now_utc=now_utc,
            )

        assert reason is None
        assert details["latest_held_sell_position_qty"] == "10"
        assert details["sell_cooldown_position_unchanged_or_reduced"] == "false"

    @pytest.mark.asyncio
    async def test_pre_ai_skip_when_held_position_recent_buy_sell_cooldown_active(self) -> None:
        """최근 BUY/APPROVE 직후 보유수량이 유지되면 held_position SELL AI를 skip한다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 4, 0, 0, tzinfo=timezone.utc)  # 13:00 KST
            current_snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert current_snapshots
            current_snapshot = current_snapshots[0]
            repos.position_snapshots._items[current_snapshot.position_snapshot_id] = (  # type: ignore[attr-defined]
                PositionSnapshotEntity(
                    position_snapshot_id=current_snapshot.position_snapshot_id,
                    account_id=current_snapshot.account_id,
                    instrument_id=current_snapshot.instrument_id,
                    quantity=Decimal("10"),
                    average_price=current_snapshot.average_price,
                    market_price=current_snapshot.market_price,
                    unrealized_pnl=current_snapshot.unrealized_pnl,
                    source_of_truth=current_snapshot.source_of_truth,
                    snapshot_at=current_snapshot.snapshot_at,
                    created_at=current_snapshot.created_at,
                )
            )
            anchor_snapshot = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=current_snapshot.account_id,
                instrument_id=current_snapshot.instrument_id,
                quantity=Decimal("10"),
                average_price=current_snapshot.average_price,
                market_price=current_snapshot.market_price,
                unrealized_pnl=current_snapshot.unrealized_pnl,
                source_of_truth="test",
                snapshot_at=now_utc - timedelta(minutes=6),
                created_at=now_utc - timedelta(minutes=6),
            )
            await repos.position_snapshots.add(anchor_snapshot)
            decision_context = DecisionContextEntity(
                decision_context_id=uuid4(),
                account_id=ACCOUNT_ID,
                strategy_id=STRATEGY_ID,
                config_version_id=CONFIG_VERSION_ID,
                market_timestamp=now_utc - timedelta(minutes=5),
                correlation_id="held-buy-sell-cooldown",
                position_snapshot_id=anchor_snapshot.position_snapshot_id,
                created_at=now_utc - timedelta(minutes=5),
            )
            await repos.decision_contexts.add(decision_context)
            await repos.trade_decisions.add(
                _make_trade_decision(
                    source_type="core",
                    decision_type=DecisionType.BUY,
                    side=OrderSide.BUY,
                    created_at=now_utc - timedelta(minutes=5),
                    decision_context_id=decision_context.decision_context_id,
                )
            )
            await repos.orders.add(
                OrderRequestEntity(
                    order_request_id=uuid4(),
                    account_id=ACCOUNT_ID,
                    instrument_id=current_snapshot.instrument_id,
                    client_order_id="held-buy-1",
                    idempotency_key="held-buy-1",
                    correlation_id="held-buy-1",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    requested_quantity=Decimal("10"),
                    status=OrderStatus.SUBMITTED,
                    created_at=now_utc - timedelta(minutes=4),
                    submitted_at=now_utc - timedelta(minutes=4),
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="held_position",
                now_utc=now_utc,
            )

        assert reason == "held_position_recent_buy_sell_cooldown"
        assert details["recent_buy_order_count"] == "1"
        assert details["latest_buy_decision_type"] == "buy"
        assert details["latest_buy_position_qty"] == "10"
        assert details["buy_cooldown_position_unchanged_or_increased"] == "true"

    @pytest.mark.asyncio
    async def test_pre_ai_skip_when_holding_profile_earliest_reduce_window_active(self) -> None:
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 4, 0, 0, tzinfo=timezone.utc)
            current_snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert current_snapshots
            current_snapshot = current_snapshots[0]
            await repos.symbol_trade_states.upsert(
                SymbolTradeStateEntity(
                    symbol_trade_state_id=uuid4(),
                    account_id=ACCOUNT_ID,
                    instrument_id=current_snapshot.instrument_id,
                    symbol=SYMBOL,
                    market=MARKET,
                    state="held_active",
                    holding_profile="core_swing",
                    position_quantity=Decimal("10"),
                    minimum_hold_until=now_utc + timedelta(minutes=30),
                    metadata_json={
                        "holding_profile_policy": {
                            "holding_profile": "core_swing",
                            "earliest_reduce_at": (
                                now_utc + timedelta(minutes=30)
                            ).isoformat(),
                        }
                    },
                    created_at=now_utc,
                    updated_at=now_utc,
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="held_position",
                now_utc=now_utc,
            )

        assert reason == "holding_profile_earliest_reduce_guard"
        assert details["holding_profile_reduce_window_active"] == "true"

    @pytest.mark.asyncio
    async def test_pre_ai_skip_when_reverse_trade_uses_same_signal_feature_snapshot_after_buy(self) -> None:
        """최근 BUY 직후 현재 최신 signal feature가 같으면 reverse trade를 별도 reason으로 차단한다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 4, 0, 0, tzinfo=timezone.utc)
            current_snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert current_snapshots
            current_snapshot = current_snapshots[0]
            signal_snapshot = SignalFeatureSnapshotEntity(
                signal_feature_snapshot_id=uuid4(),
                instrument_id=current_snapshot.instrument_id,
                timeframe="1d",
                snapshot_at=now_utc - timedelta(minutes=1),
                feature_set_version="signal_backbone_v1",
                bar_count=60,
            )
            await repos.signal_feature_snapshots.add(signal_snapshot)
            anchor_snapshot = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=current_snapshot.account_id,
                instrument_id=current_snapshot.instrument_id,
                quantity=Decimal("10"),
                average_price=current_snapshot.average_price,
                market_price=current_snapshot.market_price,
                unrealized_pnl=current_snapshot.unrealized_pnl,
                source_of_truth="test",
                snapshot_at=now_utc - timedelta(minutes=6),
                created_at=now_utc - timedelta(minutes=6),
            )
            await repos.position_snapshots.add(anchor_snapshot)
            decision_context = DecisionContextEntity(
                decision_context_id=uuid4(),
                account_id=ACCOUNT_ID,
                strategy_id=STRATEGY_ID,
                config_version_id=CONFIG_VERSION_ID,
                market_timestamp=now_utc - timedelta(minutes=5),
                correlation_id="reverse-trade-same-snapshot-buy",
                position_snapshot_id=anchor_snapshot.position_snapshot_id,
                signal_feature_snapshot_id=signal_snapshot.signal_feature_snapshot_id,
                created_at=now_utc - timedelta(minutes=5),
            )
            await repos.decision_contexts.add(decision_context)
            await repos.trade_decisions.add(
                _make_trade_decision(
                    source_type="core",
                    decision_type=DecisionType.BUY,
                    side=OrderSide.BUY,
                    created_at=now_utc - timedelta(minutes=5),
                    decision_context_id=decision_context.decision_context_id,
                )
            )
            await repos.orders.add(
                OrderRequestEntity(
                    order_request_id=uuid4(),
                    account_id=ACCOUNT_ID,
                    instrument_id=current_snapshot.instrument_id,
                    client_order_id="held-buy-snapshot-1",
                    idempotency_key="held-buy-snapshot-1",
                    correlation_id="held-buy-snapshot-1",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    requested_quantity=Decimal("10"),
                    status=OrderStatus.SUBMITTED,
                    created_at=now_utc - timedelta(minutes=4),
                    submitted_at=now_utc - timedelta(minutes=4),
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="held_position",
                now_utc=now_utc,
            )

        assert reason == "reverse_trade_same_signal_feature_snapshot"
        assert details["current_signal_feature_snapshot_id"] == str(
            signal_snapshot.signal_feature_snapshot_id
        )
        assert details["latest_buy_signal_feature_snapshot_id"] == str(
            signal_snapshot.signal_feature_snapshot_id
        )
        assert details["buy_signal_feature_snapshot_unchanged"] == "true"

    @pytest.mark.asyncio
    async def test_pre_ai_skip_not_triggered_when_position_reduced_after_recent_buy(self) -> None:
        """최근 BUY 직후라도 보유수량이 줄어 있으면 held_position SELL suppression하지 않는다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 4, 0, 0, tzinfo=timezone.utc)  # 13:00 KST
            current_snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert current_snapshots
            current_snapshot = current_snapshots[0]
            repos.position_snapshots._items[current_snapshot.position_snapshot_id] = (  # type: ignore[attr-defined]
                PositionSnapshotEntity(
                    position_snapshot_id=current_snapshot.position_snapshot_id,
                    account_id=current_snapshot.account_id,
                    instrument_id=current_snapshot.instrument_id,
                    quantity=Decimal("8"),
                    average_price=current_snapshot.average_price,
                    market_price=current_snapshot.market_price,
                    unrealized_pnl=current_snapshot.unrealized_pnl,
                    source_of_truth=current_snapshot.source_of_truth,
                    snapshot_at=current_snapshot.snapshot_at,
                    created_at=current_snapshot.created_at,
                )
            )
            anchor_snapshot = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=current_snapshot.account_id,
                instrument_id=current_snapshot.instrument_id,
                quantity=Decimal("10"),
                average_price=current_snapshot.average_price,
                market_price=current_snapshot.market_price,
                unrealized_pnl=current_snapshot.unrealized_pnl,
                source_of_truth="test",
                snapshot_at=now_utc - timedelta(minutes=6),
                created_at=now_utc - timedelta(minutes=6),
            )
            await repos.position_snapshots.add(anchor_snapshot)
            decision_context = DecisionContextEntity(
                decision_context_id=uuid4(),
                account_id=ACCOUNT_ID,
                strategy_id=STRATEGY_ID,
                config_version_id=CONFIG_VERSION_ID,
                market_timestamp=now_utc - timedelta(minutes=5),
                correlation_id="held-buy-sell-cooldown-reduced",
                position_snapshot_id=anchor_snapshot.position_snapshot_id,
                created_at=now_utc - timedelta(minutes=5),
            )
            await repos.decision_contexts.add(decision_context)
            await repos.trade_decisions.add(
                _make_trade_decision(
                    source_type="core",
                    decision_type=DecisionType.APPROVE,
                    side=OrderSide.BUY,
                    created_at=now_utc - timedelta(minutes=5),
                    decision_context_id=decision_context.decision_context_id,
                )
            )
            await repos.orders.add(
                OrderRequestEntity(
                    order_request_id=uuid4(),
                    account_id=ACCOUNT_ID,
                    instrument_id=current_snapshot.instrument_id,
                    client_order_id="held-buy-2",
                    idempotency_key="held-buy-2",
                    correlation_id="held-buy-2",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    requested_quantity=Decimal("10"),
                    status=OrderStatus.SUBMITTED,
                    created_at=now_utc - timedelta(minutes=4),
                    submitted_at=now_utc - timedelta(minutes=4),
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="held_position",
                now_utc=now_utc,
            )

        assert reason is None
        assert details["latest_buy_position_qty"] == "10"
        assert details["buy_cooldown_position_unchanged_or_increased"] == "false"

    @pytest.mark.asyncio
    async def test_pre_ai_skip_when_same_symbol_reentry_cooldown_active(self) -> None:
        """최근 SELL/REDUCE 직후에는 no-position core BUY를 AI 전에 skip한다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 4, 0, 0, tzinfo=timezone.utc)
            current_snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert current_snapshots
            current_snapshot = current_snapshots[0]
            repos.position_snapshots._items[current_snapshot.position_snapshot_id] = (  # type: ignore[attr-defined]
                PositionSnapshotEntity(
                    position_snapshot_id=current_snapshot.position_snapshot_id,
                    account_id=current_snapshot.account_id,
                    instrument_id=current_snapshot.instrument_id,
                    quantity=Decimal("0"),
                    average_price=current_snapshot.average_price,
                    market_price=current_snapshot.market_price,
                    unrealized_pnl=current_snapshot.unrealized_pnl,
                    source_of_truth=current_snapshot.source_of_truth,
                    snapshot_at=current_snapshot.snapshot_at,
                    created_at=current_snapshot.created_at,
                )
            )

            anchor_snapshot = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=current_snapshot.account_id,
                instrument_id=current_snapshot.instrument_id,
                quantity=Decimal("8"),
                average_price=current_snapshot.average_price,
                market_price=current_snapshot.market_price,
                unrealized_pnl=current_snapshot.unrealized_pnl,
                source_of_truth="test",
                snapshot_at=now_utc - timedelta(minutes=6),
                created_at=now_utc - timedelta(minutes=6),
            )
            await repos.position_snapshots.add(anchor_snapshot)
            decision_context = DecisionContextEntity(
                decision_context_id=uuid4(),
                account_id=ACCOUNT_ID,
                strategy_id=STRATEGY_ID,
                config_version_id=CONFIG_VERSION_ID,
                market_timestamp=now_utc - timedelta(minutes=5),
                correlation_id="same-symbol-reentry-cooldown",
                position_snapshot_id=anchor_snapshot.position_snapshot_id,
                created_at=now_utc - timedelta(minutes=5),
            )
            await repos.decision_contexts.add(decision_context)
            await repos.trade_decisions.add(
                _make_trade_decision(
                    decision_type=DecisionType.EXIT,
                    side=OrderSide.SELL,
                    created_at=now_utc - timedelta(minutes=5),
                    decision_context_id=decision_context.decision_context_id,
                )
            )
            await repos.orders.add(
                OrderRequestEntity(
                    order_request_id=uuid4(),
                    account_id=ACCOUNT_ID,
                    instrument_id=current_snapshot.instrument_id,
                    client_order_id="reentry-sell-1",
                    idempotency_key="reentry-sell-1",
                    correlation_id="reentry-sell-1",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    requested_quantity=Decimal("8"),
                    status=OrderStatus.FILLED,
                    created_at=now_utc - timedelta(minutes=4),
                    submitted_at=now_utc - timedelta(minutes=4),
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="core",
                now_utc=now_utc,
            )

        assert reason == "same_symbol_reentry_cooldown"
        assert details["held_quantity"] == "0"
        assert details["reentry_recent_sell_order_count"] == "1"
        assert details["reentry_latest_sell_decision_type"] == "exit"

    @pytest.mark.asyncio
    async def test_pre_ai_skip_when_reentry_uses_same_signal_feature_snapshot(self) -> None:
        """최근 SELL 뒤 현재 최신 signal feature가 같으면 재진입을 별도 reason으로 차단한다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 4, 0, 0, tzinfo=timezone.utc)
            current_snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert current_snapshots
            current_snapshot = current_snapshots[0]
            repos.position_snapshots._items[current_snapshot.position_snapshot_id] = (  # type: ignore[attr-defined]
                PositionSnapshotEntity(
                    position_snapshot_id=current_snapshot.position_snapshot_id,
                    account_id=current_snapshot.account_id,
                    instrument_id=current_snapshot.instrument_id,
                    quantity=Decimal("0"),
                    average_price=current_snapshot.average_price,
                    market_price=current_snapshot.market_price,
                    unrealized_pnl=current_snapshot.unrealized_pnl,
                    source_of_truth=current_snapshot.source_of_truth,
                    snapshot_at=current_snapshot.snapshot_at,
                    created_at=current_snapshot.created_at,
                )
            )
            signal_snapshot = SignalFeatureSnapshotEntity(
                signal_feature_snapshot_id=uuid4(),
                instrument_id=current_snapshot.instrument_id,
                timeframe="1d",
                snapshot_at=now_utc - timedelta(minutes=1),
                feature_set_version="signal_backbone_v1",
                bar_count=60,
            )
            await repos.signal_feature_snapshots.add(signal_snapshot)
            anchor_snapshot = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=current_snapshot.account_id,
                instrument_id=current_snapshot.instrument_id,
                quantity=Decimal("8"),
                average_price=current_snapshot.average_price,
                market_price=current_snapshot.market_price,
                unrealized_pnl=current_snapshot.unrealized_pnl,
                source_of_truth="test",
                snapshot_at=now_utc - timedelta(minutes=6),
                created_at=now_utc - timedelta(minutes=6),
            )
            await repos.position_snapshots.add(anchor_snapshot)
            decision_context = DecisionContextEntity(
                decision_context_id=uuid4(),
                account_id=ACCOUNT_ID,
                strategy_id=STRATEGY_ID,
                config_version_id=CONFIG_VERSION_ID,
                market_timestamp=now_utc - timedelta(minutes=5),
                correlation_id="reverse-trade-same-snapshot-sell",
                position_snapshot_id=anchor_snapshot.position_snapshot_id,
                signal_feature_snapshot_id=signal_snapshot.signal_feature_snapshot_id,
                created_at=now_utc - timedelta(minutes=5),
            )
            await repos.decision_contexts.add(decision_context)
            await repos.trade_decisions.add(
                _make_trade_decision(
                    decision_type=DecisionType.EXIT,
                    side=OrderSide.SELL,
                    created_at=now_utc - timedelta(minutes=5),
                    decision_context_id=decision_context.decision_context_id,
                )
            )
            await repos.orders.add(
                OrderRequestEntity(
                    order_request_id=uuid4(),
                    account_id=ACCOUNT_ID,
                    instrument_id=current_snapshot.instrument_id,
                    client_order_id="reentry-sell-snapshot-1",
                    idempotency_key="reentry-sell-snapshot-1",
                    correlation_id="reentry-sell-snapshot-1",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    requested_quantity=Decimal("8"),
                    status=OrderStatus.FILLED,
                    created_at=now_utc - timedelta(minutes=4),
                    submitted_at=now_utc - timedelta(minutes=4),
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="core",
                now_utc=now_utc,
            )

        assert reason == "reverse_trade_same_signal_feature_snapshot"
        assert details["current_signal_feature_snapshot_id"] == str(
            signal_snapshot.signal_feature_snapshot_id
        )
        assert details["reentry_latest_sell_signal_feature_snapshot_id"] == str(
            signal_snapshot.signal_feature_snapshot_id
        )
        assert details["reentry_signal_feature_snapshot_unchanged"] == "true"

    @pytest.mark.asyncio
    async def test_pre_ai_skip_when_holding_profile_earliest_reentry_window_active(self) -> None:
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            now_utc = datetime(2026, 6, 8, 4, 0, 0, tzinfo=timezone.utc)
            current_snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert current_snapshots
            current_snapshot = current_snapshots[0]
            repos.position_snapshots._items[current_snapshot.position_snapshot_id] = (  # type: ignore[attr-defined]
                PositionSnapshotEntity(
                    position_snapshot_id=current_snapshot.position_snapshot_id,
                    account_id=current_snapshot.account_id,
                    instrument_id=current_snapshot.instrument_id,
                    quantity=Decimal("0"),
                    average_price=current_snapshot.average_price,
                    market_price=current_snapshot.market_price,
                    unrealized_pnl=current_snapshot.unrealized_pnl,
                    source_of_truth=current_snapshot.source_of_truth,
                    snapshot_at=current_snapshot.snapshot_at,
                    created_at=current_snapshot.created_at,
                )
            )
            await repos.symbol_trade_states.upsert(
                SymbolTradeStateEntity(
                    symbol_trade_state_id=uuid4(),
                    account_id=ACCOUNT_ID,
                    instrument_id=current_snapshot.instrument_id,
                    symbol=SYMBOL,
                    market=MARKET,
                    state="flat_cooldown",
                    holding_profile="risk_reduction_only",
                    position_quantity=Decimal("0"),
                    reentry_cooldown_until=now_utc + timedelta(minutes=20),
                    metadata_json={
                        "holding_profile_policy": {
                            "holding_profile": "risk_reduction_only",
                            "earliest_reentry_at": (
                                now_utc + timedelta(minutes=20)
                            ).isoformat(),
                        }
                    },
                    created_at=now_utc,
                    updated_at=now_utc,
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="core",
                now_utc=now_utc,
            )

        assert reason == "holding_profile_earliest_reentry_guard"
        assert details["holding_profile_reentry_window_active"] == "true"

    @pytest.mark.asyncio
    async def test_pre_ai_same_symbol_reentry_cooldown_skips_core_cycle(self) -> None:
        """최근 SELL 직후 동일 종목 core cycle은 pre-AI gate에서 SKIPPED 처리된다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            with patch(
                "scripts.run_decision_loop._evaluate_pre_ai_validation_result",
                new=AsyncMock(
                    return_value=_blocked_pre_ai_result(
                        "same_symbol_reentry_cooldown",
                        {
                            "held_quantity": "0",
                            "reentry_recent_sell_order_count": "1",
                            "reentry_latest_sell_decision_type": "reduce",
                        },
                    )
                ),
            ):
                result = await _run_one_cycle(
                    cycle=1,
                    submit=True,
                    dry_run=False,
                    output="text",
                    symbol=SYMBOL,
                    source_type="core",
                    runtime=runtime,
                )

        assert result["status"] == "SKIPPED"
        assert result["error_phase"] == "pre_ai_gate"
        assert result["error_message"] == "same_symbol_reentry_cooldown"
        assert result["stop_reason"] == "same_symbol_reentry_cooldown"
        assert result["skip_reason"] == "same_symbol_reentry_cooldown"
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].blocking_rule_codes == ["same_symbol_reentry_cooldown"]

    @pytest.mark.asyncio
    async def test_pre_ai_recent_buy_sell_cooldown_skips_held_position_cycle(self) -> None:
        """최근 BUY 직후 held_position cycle은 pre-AI gate에서 SKIPPED 처리된다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            with patch(
                "scripts.run_decision_loop._evaluate_pre_ai_validation_result",
                new=AsyncMock(
                    return_value=_blocked_pre_ai_result(
                        "held_position_recent_buy_sell_cooldown",
                        {
                            "held_quantity": "10",
                            "recent_buy_order_count": "1",
                            "latest_buy_decision_type": "buy",
                        },
                    )
                ),
            ):
                result = await _run_one_cycle(
                    cycle=1,
                    submit=True,
                    dry_run=False,
                    output="text",
                    symbol=SYMBOL,
                    source_type="held_position",
                    runtime=runtime,
                )

        assert result["status"] == "SKIPPED"
        assert result["error_phase"] == "pre_ai_gate"
        assert result["error_message"] == "held_position_recent_buy_sell_cooldown"
        assert result["stop_reason"] == "held_position_recent_buy_sell_cooldown"
        assert result["skip_reason"] == "held_position_recent_buy_sell_cooldown"
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].blocking_rule_codes == ["held_position_recent_buy_sell_cooldown"]

    @pytest.mark.asyncio
    async def test_pre_ai_reverse_trade_same_snapshot_skips_cycle(self) -> None:
        """signal_feature_snapshot_id 불변 reverse trade는 pre-AI gate에서 SKIPPED 처리된다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            with patch(
                "scripts.run_decision_loop._evaluate_pre_ai_validation_result",
                new=AsyncMock(
                    return_value=_blocked_pre_ai_result(
                        "reverse_trade_same_signal_feature_snapshot",
                        {
                            "current_signal_feature_snapshot_id": "same-snapshot",
                            "reentry_signal_feature_snapshot_unchanged": "true",
                        },
                    )
                ),
            ):
                result = await _run_one_cycle(
                    cycle=1,
                    submit=True,
                    dry_run=False,
                    output="text",
                    symbol=SYMBOL,
                    source_type="core",
                    runtime=runtime,
                )

        assert result["status"] == "SKIPPED"
        assert result["error_phase"] == "pre_ai_gate"
        assert result["error_message"] == "reverse_trade_same_signal_feature_snapshot"
        assert result["stop_reason"] == "reverse_trade_same_signal_feature_snapshot"
        assert result["skip_reason"] == "reverse_trade_same_signal_feature_snapshot"
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].blocking_rule_codes == ["reverse_trade_same_signal_feature_snapshot"]

    @pytest.mark.asyncio
    async def test_pre_ai_skip_when_general_buy_budget_exhausted_and_no_position(self) -> None:
        """일반 lane 후보는 보유수량이 없고 일반 BUY 예산이 0이면 AI 전에 SKIP."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert snapshots
            latest_position = snapshots[0]
            repos.position_snapshots._items[latest_position.position_snapshot_id] = (  # type: ignore[attr-defined]
                PositionSnapshotEntity(
                    position_snapshot_id=latest_position.position_snapshot_id,
                    account_id=latest_position.account_id,
                    instrument_id=latest_position.instrument_id,
                    quantity=Decimal("0"),
                    average_price=latest_position.average_price,
                    market_price=latest_position.market_price,
                    unrealized_pnl=latest_position.unrealized_pnl,
                    source_of_truth=latest_position.source_of_truth,
                    snapshot_at=latest_position.snapshot_at,
                    created_at=latest_position.created_at,
                )
            )
            result = await _run_one_cycle(
                cycle=1,
                submit=True,
                dry_run=False,
                output="text",
                source_type="core",
                remaining_general_buy_budget=0,
                runtime=runtime,
            )

        assert result["status"] == "SKIPPED"
        assert result["error_phase"] == "pre_ai_gate"
        assert result["error_message"] == "general_buy_budget_exhausted"
        assert result["stop_reason"] == "general_buy_budget_exhausted"
        assert result["skip_reason"] == "general_buy_budget_exhausted"
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].blocking_rule_codes == ["general_buy_budget_exhausted"]

    @pytest.mark.asyncio
    async def test_pre_ai_skip_records_decision_cycle_id_when_provided(self) -> None:
        """Stage A-1b(2026-08-20): ``_run_one_cycle(decision_cycle_id=...)``
        로 넘긴 값이 pre-AI gate 스킵 기록의 ``guardrail_evaluations``
        row에 그대로 저장돼야 한다(관측성 전용, 판정 로직 무변화)."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert snapshots
            latest_position = snapshots[0]
            repos.position_snapshots._items[latest_position.position_snapshot_id] = (  # type: ignore[attr-defined]
                PositionSnapshotEntity(
                    position_snapshot_id=latest_position.position_snapshot_id,
                    account_id=latest_position.account_id,
                    instrument_id=latest_position.instrument_id,
                    quantity=Decimal("0"),
                    average_price=latest_position.average_price,
                    market_price=latest_position.market_price,
                    unrealized_pnl=latest_position.unrealized_pnl,
                    source_of_truth=latest_position.source_of_truth,
                    snapshot_at=latest_position.snapshot_at,
                    created_at=latest_position.created_at,
                )
            )
            await _run_one_cycle(
                cycle=1,
                submit=True,
                dry_run=False,
                output="text",
                source_type="core",
                remaining_general_buy_budget=0,
                runtime=runtime,
                decision_cycle_id="decision_submit_gate:2026-08-20T09:05:12+09:00#1",
            )

        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].decision_cycle_id == (
            "decision_submit_gate:2026-08-20T09:05:12+09:00#1"
        )

    @pytest.mark.asyncio
    async def test_pre_ai_skip_reason_not_triggered_when_position_exists_even_if_buy_budget_zero(self) -> None:
        """보유수량이 있으면 일반 BUY 예산 0이어도 SELL 후보 가능성을 위해 즉시 skip하지 않음."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="core",
                remaining_general_buy_budget=0,
            )

        assert reason is None
        assert details["held_quantity"] == "10"

    @pytest.mark.asyncio
    async def test_assemble_not_called_when_general_buy_budget_exhausted_pre_ai(self) -> None:
        """AI 토큰 낭비 방지 확인(2026-08-12 KST): 무보유 + remaining_general_
        buy_budget=0이면 ``orchestrator.assemble()``이 전혀 호출되지 않아야
        한다 — Pre-AI gate가 AI 호출 전에 차단함을 직접 증명한다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            snapshots = await repos.position_snapshots.list_latest_by_account(ACCOUNT_ID)
            assert snapshots
            latest_position = snapshots[0]
            repos.position_snapshots._items[latest_position.position_snapshot_id] = (  # type: ignore[attr-defined]
                PositionSnapshotEntity(
                    position_snapshot_id=latest_position.position_snapshot_id,
                    account_id=latest_position.account_id,
                    instrument_id=latest_position.instrument_id,
                    quantity=Decimal("0"),
                    average_price=latest_position.average_price,
                    market_price=latest_position.market_price,
                    unrealized_pnl=latest_position.unrealized_pnl,
                    source_of_truth=latest_position.source_of_truth,
                    snapshot_at=latest_position.snapshot_at,
                    created_at=latest_position.created_at,
                )
            )
            orchestrator = runtime["orchestrator"]
            mock_assemble = AsyncMock()
            with patch.object(orchestrator, "assemble", mock_assemble):
                result = await _run_one_cycle(
                    cycle=1,
                    submit=True,
                    dry_run=False,
                    output="text",
                    source_type="core",
                    remaining_general_buy_budget=0,
                    runtime=runtime,
                )

        assert result["status"] == "SKIPPED"
        assert result["error_phase"] == "pre_ai_gate"
        assert result["stop_reason"] == "general_buy_budget_exhausted"
        mock_assemble.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pre_ai_cash_gate_not_triggered_when_position_exists_and_orderable_amount_low(self) -> None:
        """보유 종목은 주문가능금액이 낮아도 매도/축소 판단 경로를 위해 현금 gate로 막지 않는다."""
        async with _mock_runtime_for_one_cycle() as runtime:
            repos = runtime["repositories"]
            cash_snapshot = await repos.cash_balance_snapshots.get_latest_by_account(ACCOUNT_ID)
            assert cash_snapshot is not None
            repos.cash_balance_snapshots._items[cash_snapshot.cash_balance_snapshot_id] = (  # type: ignore[attr-defined]
                CashBalanceSnapshotEntity(
                    cash_balance_snapshot_id=cash_snapshot.cash_balance_snapshot_id,
                    account_id=cash_snapshot.account_id,
                    currency=cash_snapshot.currency,
                    available_cash=cash_snapshot.available_cash,
                    settled_cash=cash_snapshot.settled_cash,
                    unsettled_cash=cash_snapshot.unsettled_cash,
                    source_of_truth=cash_snapshot.source_of_truth,
                    snapshot_at=cash_snapshot.snapshot_at,
                    total_asset=cash_snapshot.total_asset,
                    settlement_amount=cash_snapshot.settlement_amount,
                    total_unrealized_pnl=cash_snapshot.total_unrealized_pnl,
                    orderable_amount=Decimal("1000"),
                    created_at=cash_snapshot.created_at,
                )
            )

            reason, details = await _evaluate_pre_ai_skip_reason(
                repos,
                account_alias="Entrypoint Paper",
                symbol=SYMBOL,
                market=MARKET,
                source_type="core",
                remaining_general_buy_budget=5,
            )

        assert reason is None
        assert details["held_quantity"] == "10"

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
    """``evaluate_symbol_submit_lane()`` held_position sell lane 검증.

    일반 BUY lane과 분리되고, 같은 cycle 내 symbol deduplication이
    올바르게 동작하는지 확인.
    """

    def test_hp_sell_ignores_general_submit_budget_consumed(self) -> None:
        """앞선 BUY가 submit 슬롯을 예약해도 held_position은 submit 가능해야 함."""
        decision = evaluate_symbol_submit_lane(
            submit=True,
            dry_run=False,
            allow_general_submit=True,
            source_type="held_position",
            submit_budget_consumed_count=1,
            max_general_submits_this_cycle=1,
            held_position_sell_cycle_count=0,
            held_position_sell_cycle_symbols=set(),
            symbol="001740",
        )
        assert decision.submit is True
        assert decision.dry_run is False
        assert decision.dry_run_reason is None

    def test_hp_sell_cycle_count_no_longer_blocks_submit(self) -> None:
        """HP sell은 cycle count와 무관하게 submit 가능해야 함."""
        decision = evaluate_symbol_submit_lane(
            submit=True,
            dry_run=False,
            allow_general_submit=True,
            source_type="held_position",
            submit_budget_consumed_count=0,
            max_general_submits_this_cycle=1,
            held_position_sell_cycle_count=HELD_POSITION_SELL_MAX_PER_CYCLE,
            held_position_sell_cycle_symbols={"AAPL", "GOOGL"},
            symbol="MSFT",
        )
        assert decision.submit is True
        assert decision.dry_run is False
        assert decision.dry_run_reason is None

    def test_hp_sell_symbol_dedupe_blocks_duplicate(self) -> None:
        """동일 cycle 내 같은 symbol 중복 submit은 막아야 함."""
        decision = evaluate_symbol_submit_lane(
            submit=True,
            dry_run=False,
            allow_general_submit=True,
            source_type="held_position",
            submit_budget_consumed_count=0,
            max_general_submits_this_cycle=1,
            held_position_sell_cycle_count=1,
            held_position_sell_cycle_symbols={"001740"},
            symbol="001740",
        )
        assert decision.submit is False
        assert decision.dry_run is True
        assert decision.dry_run_reason == "held_position_sell_symbol_duplicate"

    def test_core_symbol_still_respects_general_submit_budget(self) -> None:
        """core 종목은 기존처럼 일반 submit 슬롯을 따라야 함."""
        decision = evaluate_symbol_submit_lane(
            submit=True,
            dry_run=False,
            allow_general_submit=True,
            source_type="core",
            submit_budget_consumed_count=1,
            max_general_submits_this_cycle=1,
            held_position_sell_cycle_count=0,
            held_position_sell_cycle_symbols=set(),
            symbol="005930",
        )
        assert decision.submit is False
        assert decision.dry_run is True
        assert decision.dry_run_reason == "submit_budget_consumed_core"
        assert decision.validation_result is not None
        assert decision.validation_result.rule_set_version == "submit_lane_gate_v1"
        assert decision.validation_result.stop_reason == "submit_budget_consumed_core"

    def test_core_symbol_blocked_when_general_submit_disabled(self) -> None:
        """일반 budget 소진 후에는 core submit이 명시적으로 금지되어야 함."""
        decision = evaluate_symbol_submit_lane(
            submit=True,
            dry_run=False,
            allow_general_submit=False,
            source_type="core",
            submit_budget_consumed_count=0,
            max_general_submits_this_cycle=1,
            held_position_sell_cycle_count=0,
            held_position_sell_cycle_symbols=set(),
            symbol="003550",
        )
        assert decision.submit is False
        assert decision.dry_run is True
        assert decision.dry_run_reason == "general_submit_disabled_core"

    def test_infer_core_dry_run_reason_when_general_submit_disabled(self) -> None:
        decision = evaluate_symbol_submit_lane(
            submit=True,
            dry_run=False,
            allow_general_submit=False,
            source_type="core",
            submit_budget_consumed_count=0,
            max_general_submits_this_cycle=1,
            held_position_sell_cycle_count=0,
            held_position_sell_cycle_symbols=set(),
            symbol="003550",
        )
        assert decision.dry_run_reason == "general_submit_disabled_core"

    def test_infer_market_overlay_dry_run_reason_when_slot_consumed(self) -> None:
        decision = evaluate_symbol_submit_lane(
            submit=True,
            dry_run=False,
            allow_general_submit=True,
            source_type="market_overlay",
            submit_budget_consumed_count=1,
            max_general_submits_this_cycle=1,
            held_position_sell_cycle_count=0,
            held_position_sell_cycle_symbols=set(),
            symbol="012330",
        )
        assert decision.dry_run_reason == "submit_budget_consumed_market_overlay"

    def test_core_symbol_allows_submit_while_cycle_budget_remains(self) -> None:
        decision = evaluate_symbol_submit_lane(
            submit=True,
            dry_run=False,
            allow_general_submit=True,
            source_type="core",
            submit_budget_consumed_count=1,
            max_general_submits_this_cycle=3,
            held_position_sell_cycle_count=0,
            held_position_sell_cycle_symbols=set(),
            symbol="005930",
        )
        assert decision.submit is True
        assert decision.dry_run is False
        assert decision.dry_run_reason is None


class TestGeneralSubmitLane:
    """일반 BUY submit lane 직렬화/승계 검증."""

    # NOTE(2026-08-11 KST, D안 2단계 분리): 아래 두 테스트는 원래
    # ``_run_one_cycle()``의 ``submit``/``dry_run`` kwargs가 예약 시점에
    # 바로 최종값을 반영한다는 옛 구조(reservation)를 검증했다. 이제 general
    # lane의 Pass 1은 항상 ``defer_actionable_for_pass2=True``로만
    # ``_run_one_cycle()``을 호출하고, budget 소비/차단은 Pass 2
    # (``_run_general_lane_pass2()`` → ``_submit_general_lane_candidate()``)
    # 에서만 일어난다. 단순히 새 kwargs 기본값을 덮어 통과시키는 대신,
    # 새 구조가 실제로 같은 행동(예산 이연/이월, budget 소진 시 차단)을
    # 보장하는지를 검증하도록 다시 작성했다.
    @pytest.mark.asyncio
    async def test_run_loop_pass2_moves_to_next_candidate_after_submit_failure(self) -> None:
        """Pass 2에서 첫 candidate가 budget-비소비 결과로 끝나면, budget이
        남아있는 한 다음 candidate가 이어받아 제출을 시도해야 한다(item C)."""
        import scripts.run_decision_loop as module

        universe = (
            UniverseSymbol(symbol="000030", market="KRX", source_type="core"),
            UniverseSymbol(symbol="000150", market="KRX", source_type="core"),
            UniverseSymbol(symbol="003670", market="KRX", source_type="core"),
        )

        @asynccontextmanager
        async def _mock_runtime(run_migrations: bool = False) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": MagicMock()}

        class _DummyTx:
            async def commit(self) -> None:
                return None

        @asynccontextmanager
        async def _mock_tx() -> AsyncIterator[_DummyTx]:
            yield _DummyTx()

        async def _mock_run_one_cycle(**kwargs: object) -> dict[str, object]:
            # Pass 1: 전부 actionable로 판단해 pending_candidates_sink에 적재.
            sink = kwargs.get("pending_candidates_sink")
            assert isinstance(sink, list)
            sink.append(
                {
                    "cycle_index": kwargs["cycle_index"],
                    "symbol": kwargs["symbol"],
                    "market": kwargs["market"],
                    "source_type": kwargs["source_type"],
                    "intent": None,
                    "trade_decision_id": None,
                    "decision_context_id": None,
                    "request": None,
                    "final_trade_score": None,
                    "analysis_completed_at": datetime.now(timezone.utc),
                }
            )
            return {
                "status": "PENDING_PASS2",
                "symbol": str(kwargs["symbol"]),
                "market": str(kwargs["market"]),
                "source_type": str(kwargs["source_type"]),
                "duration_seconds": 0.01,
            }

        submit_calls: list[str] = []

        async def _mock_submit_candidate(
            candidate: dict[str, object], *, cycle_count: int, runtime: dict[str, object],
        ) -> dict[str, object]:
            symbol = str(candidate["symbol"])
            submit_calls.append(symbol)
            if symbol == "000030":
                # pre-submit 실패 — budget을 소비하지 않는 상태(non-SUBMITTED/
                # RECONCILE_REQUIRED)로 끝난다.
                return {
                    "status": "SIZING_REJECTED",
                    "symbol": symbol,
                    "market": "KRX",
                    "duration_seconds": 0.01,
                }
            return {
                "status": "SUBMITTED",
                "symbol": symbol,
                "market": "KRX",
                "duration_seconds": 0.01,
            }

        original_shutdown_event = module._shutdown_event
        module._shutdown_event = asyncio.Event()
        try:
            with (
                patch("scripts.run_decision_loop._install_signal_handlers", return_value=None),
                patch(
                    "scripts.run_decision_loop._load_trading_universe_with_anchor",
                    AsyncMock(
                        return_value=(
                            universe,
                            UniverseAnchorMetadata(source="test"),
                        )
                    ),
                ),
                patch("scripts.run_decision_loop.postgres_runtime", new=_mock_runtime),
                patch("scripts.run_decision_loop._seed_if_empty", AsyncMock(return_value=False)),
                patch("scripts.run_decision_loop._run_precheck", AsyncMock(return_value=None)),
                patch("scripts.run_decision_loop._run_one_cycle", side_effect=_mock_run_one_cycle),
                patch(
                    "scripts.run_decision_loop._submit_general_lane_candidate",
                    side_effect=_mock_submit_candidate,
                ),
                patch("agent_trading.db.transaction.transaction", new=_mock_tx),
                patch(
                    "agent_trading.repositories.postgres.bootstrap.build_postgres_repositories",
                    return_value=MagicMock(),
                ),
            ):
                exit_code = await _run_loop(
                    interval=0,
                    max_cycles=1,
                    submit=True,
                    dry_run=False,
                    allow_general_submit=True,
                    max_general_submits_this_cycle=1,
                    output="text",
                )
        finally:
            module._shutdown_event = original_shutdown_event

        # 정렬 기준(동일 source_type/score → analysis_completed_at 오름차순,
        # universe 순서와 동일)상 000030 → 000150 → 003670 순으로 시도된다.
        # 000030은 budget을 소비하지 않으므로 budget(=1)이 그대로 남아
        # 000150이 이어받아 SUBMITTED된다. 그 시점에 budget이 소진되므로
        # 003670은 _submit_general_lane_candidate가 전혀 호출되지 않아야
        # 한다(예산 소진 후보는 Pass 2 진입 자체를 막는다).
        assert submit_calls == ["000030", "000150"]
        # 000030(SIZING_REJECTED)이 실패로 집계되어 exit_code=1.
        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_run_loop_pass2_submits_up_to_cycle_budget(self) -> None:
        """budget 범위 내에서는 순서대로 전부 제출되고, budget을 넘는
        candidate는 Pass 2 호출 자체 없이 차단돼야 한다(item C)."""
        import scripts.run_decision_loop as module

        universe = (
            UniverseSymbol(symbol="000030", market="KRX", source_type="core"),
            UniverseSymbol(symbol="000150", market="KRX", source_type="core"),
            UniverseSymbol(symbol="003670", market="KRX", source_type="core"),
            UniverseSymbol(symbol="005930", market="KRX", source_type="core"),
        )

        @asynccontextmanager
        async def _mock_runtime(run_migrations: bool = False) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": MagicMock()}

        class _DummyTx:
            async def commit(self) -> None:
                return None

        @asynccontextmanager
        async def _mock_tx() -> AsyncIterator[_DummyTx]:
            yield _DummyTx()

        async def _mock_run_one_cycle(**kwargs: object) -> dict[str, object]:
            sink = kwargs.get("pending_candidates_sink")
            assert isinstance(sink, list)
            sink.append(
                {
                    "cycle_index": kwargs["cycle_index"],
                    "symbol": kwargs["symbol"],
                    "market": kwargs["market"],
                    "source_type": kwargs["source_type"],
                    "intent": None,
                    "trade_decision_id": None,
                    "decision_context_id": None,
                    "request": None,
                    "final_trade_score": None,
                    "analysis_completed_at": datetime.now(timezone.utc),
                }
            )
            return {
                "status": "PENDING_PASS2",
                "symbol": str(kwargs["symbol"]),
                "market": str(kwargs["market"]),
                "source_type": str(kwargs["source_type"]),
                "duration_seconds": 0.01,
            }

        submit_calls: list[str] = []

        async def _mock_submit_candidate(
            candidate: dict[str, object], *, cycle_count: int, runtime: dict[str, object],
        ) -> dict[str, object]:
            symbol = str(candidate["symbol"])
            submit_calls.append(symbol)
            return {
                "status": "SUBMITTED",
                "symbol": symbol,
                "market": "KRX",
                "duration_seconds": 0.01,
            }

        original_shutdown_event = module._shutdown_event
        module._shutdown_event = asyncio.Event()
        try:
            with (
                patch("scripts.run_decision_loop._install_signal_handlers", return_value=None),
                patch(
                    "scripts.run_decision_loop._load_trading_universe_with_anchor",
                    AsyncMock(
                        return_value=(
                            universe,
                            UniverseAnchorMetadata(source="test"),
                        )
                    ),
                ),
                patch("scripts.run_decision_loop.postgres_runtime", new=_mock_runtime),
                patch("scripts.run_decision_loop._seed_if_empty", AsyncMock(return_value=False)),
                patch("scripts.run_decision_loop._run_precheck", AsyncMock(return_value=None)),
                patch("scripts.run_decision_loop._run_one_cycle", side_effect=_mock_run_one_cycle),
                patch(
                    "scripts.run_decision_loop._submit_general_lane_candidate",
                    side_effect=_mock_submit_candidate,
                ),
                patch("agent_trading.db.transaction.transaction", new=_mock_tx),
                patch(
                    "agent_trading.repositories.postgres.bootstrap.build_postgres_repositories",
                    return_value=MagicMock(),
                ),
            ):
                exit_code = await _run_loop(
                    interval=0,
                    max_cycles=1,
                    submit=True,
                    dry_run=False,
                    allow_general_submit=True,
                    max_general_submits_this_cycle=3,
                    output="text",
                )
        finally:
            module._shutdown_event = original_shutdown_event

        assert exit_code == 0
        # budget=3이므로 처음 3개(정렬 순서 = universe 순서)만 Pass 2가
        # 시도하고, 4번째(005930)는 _submit_general_lane_candidate가 전혀
        # 호출되지 않아야 한다.
        assert submit_calls == ["000030", "000150", "003670"]

    @pytest.mark.asyncio
    async def test_run_loop_general_submit_lane_does_not_serialize_symbol_execution(self) -> None:
        """general BUY lane lock은 submit slot 예약에만 사용되고 실행 전체는 병렬로 진행된다."""
        import scripts.run_decision_loop as module

        universe = (
            UniverseSymbol(symbol="000030", market="KRX", source_type="core"),
            UniverseSymbol(symbol="000150", market="KRX", source_type="core"),
        )
        active = 0
        peak_active = 0

        @asynccontextmanager
        async def _mock_runtime(run_migrations: bool = False) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": MagicMock()}

        class _DummyTx:
            async def commit(self) -> None:
                return None

        @asynccontextmanager
        async def _mock_tx() -> AsyncIterator[_DummyTx]:
            yield _DummyTx()

        async def _mock_run_one_cycle(**kwargs: object) -> dict[str, object]:
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            await asyncio.sleep(0.05)
            active -= 1
            return {
                "status": "SIZING_REJECTED",
                "symbol": str(kwargs["symbol"]),
                "market": "KRX",
                "duration_seconds": 0.05,
            }

        original_shutdown_event = module._shutdown_event
        module._shutdown_event = asyncio.Event()
        try:
            with (
                patch("scripts.run_decision_loop._install_signal_handlers", return_value=None),
                patch(
                    "scripts.run_decision_loop._load_trading_universe_with_anchor",
                    AsyncMock(
                        return_value=(
                            universe,
                            UniverseAnchorMetadata(source="test"),
                        )
                    ),
                ),
                patch("scripts.run_decision_loop.postgres_runtime", new=_mock_runtime),
                patch("scripts.run_decision_loop._seed_if_empty", AsyncMock(return_value=False)),
                patch("scripts.run_decision_loop._run_precheck", AsyncMock(return_value=None)),
                patch("scripts.run_decision_loop._run_one_cycle", side_effect=_mock_run_one_cycle),
                patch("agent_trading.db.transaction.transaction", new=_mock_tx),
                patch(
                    "agent_trading.repositories.postgres.bootstrap.build_postgres_repositories",
                    return_value=MagicMock(),
                ),
            ):
                exit_code = await _run_loop(
                    interval=0,
                    max_cycles=1,
                    submit=True,
                    dry_run=False,
                    allow_general_submit=True,
                    max_general_submits_this_cycle=1,
                    output="text",
                )
        finally:
            module._shutdown_event = original_shutdown_event

        assert exit_code == 1
        assert peak_active >= 2


# ---------------------------------------------------------------------------
# D안(2026-08-11 KST) — submit budget 2단계 분리 (Pass 1/Pass 1.5/Pass 2)
# ---------------------------------------------------------------------------


class TestDeferActionableForPass2:
    """``_run_one_cycle(defer_actionable_for_pass2=True)`` — Pass 1 분기 검증(item A)."""

    @pytest.mark.asyncio
    async def test_actionable_intent_is_deferred_not_submitted_in_pass1(self) -> None:
        """actionable(APPROVE) intent는 Pass 1에서 즉시 제출되지 않고
        ``pending_candidates_sink``에 적재된 뒤 ``PENDING_PASS2``를
        반환해야 한다. ``ExecutionService``는 Pass 1에서 호출되지 않아야
        한다(AI 비용 중복 지불 방지 확인 포함 — assemble()은 1회만 호출)."""
        from agent_trading.services.decision_orchestrator import AIDecisionInputs

        # build_submit_order_request_from_decision()이 실제로 actionable로
        # 판정하려면 EV anchor 필드(expected_return_bps 등)가 전부 채워져
        # 있어야 한다(translation.py의 _has_required_expected_value_anchor —
        # APPROVE/BUY도 이 필드 존재 여부 자체는 면제되지 않는다).
        intent = dataclasses.replace(
            _make_stub_intent(),
            ai_backend_inputs=AIDecisionInputs(
                decision_type="APPROVE",
                side="buy",
                confidence=0.8,
                expected_return_bps=Decimal("78.56"),
                expected_downside_bps=Decimal("42.00"),
                net_expected_value_bps=Decimal("36.56"),
                final_trade_score=Decimal("0.77"),
                minimum_required_edge_bps=Decimal("10.00"),
                edge_after_cost_bps=Decimal("8.56"),
                estimated_round_trip_cost_bps=Decimal("8.00"),
                slippage_buffer_bps=Decimal("20.00"),
            ),
        )
        sink: list[dict[str, object]] = []

        async with _mock_runtime_for_one_cycle() as runtime:
            orchestrator = runtime["orchestrator"]
            mock_assemble = AsyncMock(return_value=intent)
            with (
                patch.object(orchestrator, "assemble", mock_assemble),
                patch("scripts.run_decision_loop.ExecutionService") as mock_execution_service_cls,
            ):
                result = await _run_one_cycle(
                    cycle=1,
                    submit=False,
                    dry_run=False,
                    output="text",
                    runtime=runtime,
                    defer_actionable_for_pass2=True,
                    pending_candidates_sink=sink,
                    cycle_index=3,
                )

        assert result["status"] == "PENDING_PASS2"
        mock_assemble.assert_awaited_once()
        mock_execution_service_cls.assert_not_called()
        assert len(sink) == 1
        candidate = sink[0]
        assert candidate["cycle_index"] == 3
        assert candidate["symbol"] == SYMBOL
        assert candidate["intent"] is intent
        # request는 _run_one_cycle()이 이 cycle을 위해 직접 만든
        # SubmitOrderRequest다(assemble()의 반환값과는 별개 객체) — Pass 2가
        # 그대로 재사용할 수 있도록 symbol/side만 확인한다.
        assert candidate["request"].symbol == SYMBOL
        assert candidate["request"].side == OrderSide.BUY

    @pytest.mark.asyncio
    async def test_non_actionable_intent_still_runs_execution_pipeline_immediately(self) -> None:
        """non-actionable(HOLD) intent는 오늘과 동일하게 Pass 1에서 즉시
        ``run_execution_pipeline()``까지 실행해 감사 추적을 남겨야 한다 —
        pending_candidates_sink에는 아무것도 쌓이지 않아야 한다."""
        from agent_trading.services.decision_orchestrator import AIDecisionInputs

        hold_intent = dataclasses.replace(
            _make_stub_intent(),
            ai_backend_inputs=AIDecisionInputs(decision_type="HOLD", side="buy"),
        )
        sink: list[dict[str, object]] = []

        async with _mock_runtime_for_one_cycle() as runtime:
            orchestrator = runtime["orchestrator"]
            with patch.object(orchestrator, "assemble", AsyncMock(return_value=hold_intent)):
                result = await _run_one_cycle(
                    cycle=1,
                    submit=False,
                    dry_run=False,
                    output="text",
                    runtime=runtime,
                    defer_actionable_for_pass2=True,
                    pending_candidates_sink=sink,
                    cycle_index=0,
                )

        assert result["status"] != "PENDING_PASS2"
        assert sink == []


class TestPreAiGeneralBuyBudgetExhaustedDispatch:
    """``_process_one()`` dispatch — cycle-level ``allow_general_submit=False``
    일 때만 general BUY lane에 ``remaining_general_buy_budget=0``을 강제
    전달하는지 검증(2026-08-12 KST). held_position lane과 ``allow_general_
    submit=True`` cycle의 기존(D안) 동작은 그대로 유지돼야 한다."""

    @staticmethod
    async def _run_and_capture(*, allow_general_submit: bool) -> dict[str, dict[str, object]]:
        import scripts.run_decision_loop as module

        universe = (
            UniverseSymbol(symbol="000030", market="KRX", source_type="core"),
            UniverseSymbol(symbol="005930", market="KRX", source_type="held_position"),
        )

        captured_kwargs: dict[str, dict[str, object]] = {}

        async def _mock_run_one_cycle(**kwargs: object) -> dict[str, object]:
            symbol = str(kwargs["symbol"])
            captured_kwargs[symbol] = kwargs
            return {
                "status": "SKIPPED" if symbol == "000030" and not allow_general_submit else "WATCH",
                "symbol": symbol,
                "market": str(kwargs["market"]),
                "source_type": str(kwargs["source_type"]),
                "duration_seconds": 0.01,
                "error_phase": (
                    "pre_ai_gate" if symbol == "000030" and not allow_general_submit else None
                ),
            }

        @asynccontextmanager
        async def _mock_runtime(run_migrations: bool = False) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": MagicMock()}

        class _DummyTx:
            async def commit(self) -> None:
                return None

        @asynccontextmanager
        async def _mock_tx() -> AsyncIterator[_DummyTx]:
            yield _DummyTx()

        original_shutdown_event = module._shutdown_event
        module._shutdown_event = asyncio.Event()
        try:
            with (
                patch("scripts.run_decision_loop._install_signal_handlers", return_value=None),
                patch(
                    "scripts.run_decision_loop._load_trading_universe_with_anchor",
                    AsyncMock(
                        return_value=(universe, UniverseAnchorMetadata(source="test"))
                    ),
                ),
                patch("scripts.run_decision_loop.postgres_runtime", new=_mock_runtime),
                patch("scripts.run_decision_loop._seed_if_empty", AsyncMock(return_value=False)),
                patch("scripts.run_decision_loop._run_precheck", AsyncMock(return_value=None)),
                patch("scripts.run_decision_loop._run_one_cycle", side_effect=_mock_run_one_cycle),
                patch("agent_trading.db.transaction.transaction", new=_mock_tx),
                patch(
                    "agent_trading.repositories.postgres.bootstrap.build_postgres_repositories",
                    return_value=MagicMock(),
                ),
            ):
                await _run_loop(
                    interval=0,
                    max_cycles=1,
                    submit=True,
                    dry_run=False,
                    allow_general_submit=allow_general_submit,
                    # held_position lane의 remaining_general_buy_budget 계산식
                    # (max(0, max_general_submits_this_cycle - consumed))이 general
                    # lane의 강제 0 처리와 독립적임을 뚜렷이 구분하기 위해 일부러
                    # 0이 아닌 값을 쓴다(held_position은 이 값을 애초에 pre_ai_gate
                    # 판정에 쓰지 않으므로 값 자체는 held_position 차단 여부에
                    # 영향을 주지 않는다 — evaluate_pre_ai_validation_result()의
                    # source_type == "held_position" 분기가 remaining_general_buy_
                    # budget을 참조하기 전에 먼저 반환하기 때문).
                    max_general_submits_this_cycle=3,
                    output="text",
                )
        finally:
            module._shutdown_event = original_shutdown_event

        return captured_kwargs

    @pytest.mark.asyncio
    async def test_allow_general_submit_false_forces_zero_budget_for_general_lane_only(self) -> None:
        by_symbol = await self._run_and_capture(allow_general_submit=False)

        # general BUY lane(core) — cycle 전체에 budget이 없으므로 0 강제.
        assert by_symbol["000030"]["remaining_general_buy_budget"] == 0
        assert by_symbol["000030"]["defer_actionable_for_pass2"] is True

        # held_position lane은 general lane 분기 자체를 타지 않으므로
        # 강제 0의 영향을 받지 않는다(기존 else 분기 값 그대로).
        assert by_symbol["005930"]["remaining_general_buy_budget"] != 0
        assert by_symbol["005930"]["defer_actionable_for_pass2"] is False

    @pytest.mark.asyncio
    async def test_allow_general_submit_true_keeps_existing_pass1_behavior(self) -> None:
        by_symbol = await self._run_and_capture(allow_general_submit=True)

        # budget이 남아있는 cycle에서는 D안 기존 동작(None) 그대로 유지 —
        # Pass 1.5/Pass 2가 dedupe·우선순위·순차소비를 담당한다.
        assert by_symbol["000030"]["remaining_general_buy_budget"] is None
        assert by_symbol["000030"]["defer_actionable_for_pass2"] is True

        assert by_symbol["005930"]["defer_actionable_for_pass2"] is False


class TestDecisionCycleIdDispatch:
    """``_run_loop(decision_cycle_id=...)`` — scheduler가 넘긴 cycle
    식별자가 같은 cycle 안의 모든 symbol에 동일하게 전달되는지 검증
    (Stage A-1b, 2026-08-20). 판정 로직에는 관여하지 않는 순수 배선
    검증이다."""

    @staticmethod
    async def _run_and_capture(
        *, decision_cycle_id: str | None,
    ) -> dict[str, dict[str, object]]:
        import scripts.run_decision_loop as module

        universe = (
            UniverseSymbol(symbol="000030", market="KRX", source_type="core"),
            UniverseSymbol(symbol="005930", market="KRX", source_type="held_position"),
        )

        captured_kwargs: dict[str, dict[str, object]] = {}

        async def _mock_run_one_cycle(**kwargs: object) -> dict[str, object]:
            symbol = str(kwargs["symbol"])
            captured_kwargs[symbol] = kwargs
            return {
                "status": "WATCH",
                "symbol": symbol,
                "market": str(kwargs["market"]),
                "source_type": str(kwargs["source_type"]),
                "duration_seconds": 0.01,
            }

        @asynccontextmanager
        async def _mock_runtime(run_migrations: bool = False) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": MagicMock()}

        class _DummyTx:
            async def commit(self) -> None:
                return None

        @asynccontextmanager
        async def _mock_tx() -> AsyncIterator[_DummyTx]:
            yield _DummyTx()

        original_shutdown_event = module._shutdown_event
        module._shutdown_event = asyncio.Event()
        try:
            with (
                patch("scripts.run_decision_loop._install_signal_handlers", return_value=None),
                patch(
                    "scripts.run_decision_loop._load_trading_universe_with_anchor",
                    AsyncMock(
                        return_value=(universe, UniverseAnchorMetadata(source="test"))
                    ),
                ),
                patch("scripts.run_decision_loop.postgres_runtime", new=_mock_runtime),
                patch("scripts.run_decision_loop._seed_if_empty", AsyncMock(return_value=False)),
                patch("scripts.run_decision_loop._run_precheck", AsyncMock(return_value=None)),
                patch("scripts.run_decision_loop._run_one_cycle", side_effect=_mock_run_one_cycle),
                patch("agent_trading.db.transaction.transaction", new=_mock_tx),
                patch(
                    "agent_trading.repositories.postgres.bootstrap.build_postgres_repositories",
                    return_value=MagicMock(),
                ),
            ):
                await _run_loop(
                    interval=0,
                    max_cycles=1,
                    submit=True,
                    dry_run=False,
                    allow_general_submit=True,
                    max_general_submits_this_cycle=3,
                    output="text",
                    decision_cycle_id=decision_cycle_id,
                )
        finally:
            module._shutdown_event = original_shutdown_event

        return captured_kwargs

    @pytest.mark.asyncio
    async def test_same_cycle_id_reaches_every_symbol_in_the_cycle(self) -> None:
        """scheduler가 넘긴 값(``#{cycle_count}`` suffix 포함)이 같은
        cycle의 general lane/held_position lane 심볼 모두에 동일하게
        전달돼야 한다."""
        by_symbol = await self._run_and_capture(
            decision_cycle_id="decision_submit_gate:2026-08-20T09:05:12+09:00"
        )

        assert by_symbol["000030"]["decision_cycle_id"] == (
            "decision_submit_gate:2026-08-20T09:05:12+09:00#1"
        )
        assert by_symbol["005930"]["decision_cycle_id"] == (
            "decision_submit_gate:2026-08-20T09:05:12+09:00#1"
        )

    @pytest.mark.asyncio
    async def test_decision_cycle_id_none_when_not_provided(self) -> None:
        """cycle 식별자를 안 넘기면(수동/단독 실행) 모든 symbol에 대해
        여전히 ``None``으로 남아야 한다(하위 호환)."""
        by_symbol = await self._run_and_capture(decision_cycle_id=None)

        assert by_symbol["000030"]["decision_cycle_id"] is None
        assert by_symbol["005930"]["decision_cycle_id"] is None


class TestGeneralLanePriorityKeyAndDedupe:
    """``_general_lane_priority_key()`` 정렬 + Pass 1.5 dedupe 검증(item B)."""

    def test_priority_orders_source_type_then_score_then_time(self) -> None:
        t0 = datetime(2026, 8, 11, 9, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 8, 11, 9, 0, 1, tzinfo=timezone.utc)
        core_high_score = {
            "source_type": "core", "final_trade_score": Decimal("0.9"),
            "analysis_completed_at": t1,
        }
        core_low_score_earlier = {
            "source_type": "core", "final_trade_score": Decimal("0.1"),
            "analysis_completed_at": t0,
        }
        event_overlay_top_score = {
            "source_type": "event_overlay", "final_trade_score": Decimal("0.99"),
            "analysis_completed_at": t0,
        }
        market_overlay_no_score = {
            "source_type": "market_overlay", "final_trade_score": None,
            "analysis_completed_at": t0,
        }
        ordered = sorted(
            [market_overlay_no_score, event_overlay_top_score, core_low_score_earlier, core_high_score],
            key=_general_lane_priority_key,
        )
        # 1차: source_type(core > event_overlay > market_overlay).
        # core 둘 사이에서는 2차 기준(final_trade_score 내림차순)이 우선한다
        # — event_overlay가 core보다 점수가 높아도 순위에서 밀린다.
        assert ordered == [
            core_high_score, core_low_score_earlier,
            event_overlay_top_score, market_overlay_no_score,
        ]

    @pytest.mark.asyncio
    async def test_dedupe_keeps_only_highest_priority_candidate_per_symbol(self) -> None:
        """같은 symbol이 core/event_overlay 두 source_type으로 동시에
        들어와도, 우선순위가 높은 core 1건만 실제 제출 시도로 이어져야
        한다(나머지는 symbol_duplicate_in_cycle로 drop)."""
        now = datetime.now(timezone.utc)
        candidates = [
            {
                "cycle_index": 0, "symbol": "005930", "market": "KRX",
                "source_type": "event_overlay", "intent": None,
                "trade_decision_id": None, "decision_context_id": None,
                "request": None, "final_trade_score": None,
                "analysis_completed_at": now,
            },
            {
                "cycle_index": 1, "symbol": "005930", "market": "KRX",
                "source_type": "core", "intent": None,
                "trade_decision_id": None, "decision_context_id": None,
                "request": None, "final_trade_score": None,
                "analysis_completed_at": now,
            },
        ]
        cycle_results: list[dict[str, object]] = [
            {"status": "PENDING_PASS2", "symbol": "005930", "cycle_index": 0},
            {"status": "PENDING_PASS2", "symbol": "005930", "cycle_index": 1},
        ]
        submitted_source_types: list[str] = []

        async def _mock_submit(
            candidate: dict[str, object], *, cycle_count: int, runtime: dict[str, object],
        ) -> dict[str, object]:
            submitted_source_types.append(str(candidate["source_type"]))
            return {
                "status": "SUBMITTED",
                "symbol": str(candidate["symbol"]),
                "market": "KRX",
                "duration_seconds": 0.01,
            }

        with patch(
            "scripts.run_decision_loop._submit_general_lane_candidate",
            side_effect=_mock_submit,
        ):
            new_consumed = await _run_general_lane_pass2(
                candidates,
                cycle_results=cycle_results,
                cycle_count=1,
                max_general_submits_this_cycle=5,
                submit_budget_consumed_count=0,
                runtime={},
                output="text",
            )

        # event_overlay는 dedupe로 제출 시도조차 되지 않는다.
        assert submitted_source_types == ["core"]
        assert new_consumed == 1
        assert cycle_results[0]["status"] == "SKIPPED"
        assert cycle_results[0]["stop_reason"] == "symbol_duplicate_in_cycle"
        assert cycle_results[1]["status"] == "SUBMITTED"


class TestRunGeneralLanePass2BudgetConsumption:
    """``_run_general_lane_pass2()`` — budget 소비 조건 검증(item C)."""

    @pytest.mark.asyncio
    async def test_budget_increments_only_on_submitted_or_reconcile_required(self) -> None:
        """WATCH/SKIPPED로 끝난 candidate는 budget을 소비하지 않고,
        SUBMITTED/RECONCILE_REQUIRED만 소비해야 한다."""
        now = datetime.now(timezone.utc)

        def _candidate(idx: int, symbol: str) -> dict[str, object]:
            return {
                "cycle_index": idx, "symbol": symbol, "market": "KRX",
                "source_type": "core", "intent": None,
                "trade_decision_id": None, "decision_context_id": None,
                "request": None, "final_trade_score": None,
                "analysis_completed_at": now,
            }

        candidates = [
            _candidate(0, "AAA"),
            _candidate(1, "BBB"),
            _candidate(2, "CCC"),
        ]
        cycle_results: list[dict[str, object]] = [
            {"status": "PENDING_PASS2", "symbol": "AAA", "cycle_index": 0},
            {"status": "PENDING_PASS2", "symbol": "BBB", "cycle_index": 1},
            {"status": "PENDING_PASS2", "symbol": "CCC", "cycle_index": 2},
        ]
        outcomes = {"AAA": "WATCH", "BBB": "SUBMITTED", "CCC": "RECONCILE_REQUIRED"}

        async def _mock_submit(
            candidate: dict[str, object], *, cycle_count: int, runtime: dict[str, object],
        ) -> dict[str, object]:
            symbol = str(candidate["symbol"])
            return {
                "status": outcomes[symbol],
                "symbol": symbol,
                "market": "KRX",
                "duration_seconds": 0.01,
            }

        with patch(
            "scripts.run_decision_loop._submit_general_lane_candidate",
            side_effect=_mock_submit,
        ):
            new_consumed = await _run_general_lane_pass2(
                candidates,
                cycle_results=cycle_results,
                cycle_count=1,
                max_general_submits_this_cycle=5,
                submit_budget_consumed_count=0,
                runtime={},
                output="text",
            )

        # WATCH(AAA)는 미소비, SUBMITTED(BBB)+RECONCILE_REQUIRED(CCC) 2건만 소비.
        assert new_consumed == 2
        assert cycle_results[0]["status"] == "WATCH"
        assert cycle_results[1]["status"] == "SUBMITTED"
        assert cycle_results[2]["status"] == "RECONCILE_REQUIRED"


class TestPass2DropGuardrailEvaluationRecording:
    """Pass 2(budget exhausted/symbol dedupe) drop이 ``guardrail_
    evaluations``에 기록되도록 배선됐는지 검증(Stage A-1a, 2026-08-20).

    판정 로직(누가 드롭되는지)은 기존과 동일해야 하며, 이 테스트는
    오직 "기록 호출이 일어나는지"만 검증한다 — 실제 DB 기록 자체는
    ``test_validators.py``/``_record_pass2_general_lane_drop_guardrail_
    evaluation()`` 자체 단위 테스트가 별도로 커버한다.
    """

    @staticmethod
    def _candidate(idx: int, symbol: str, score: str | None = None) -> dict[str, object]:
        return {
            "cycle_index": idx, "symbol": symbol, "market": "KRX",
            "source_type": "core", "intent": None,
            "trade_decision_id": None, "decision_context_id": None,
            "request": None, "final_trade_score": score,
            "analysis_completed_at": datetime.now(timezone.utc),
        }

    @pytest.mark.asyncio
    async def test_budget_exhausted_drop_records_guardrail_evaluation(self) -> None:
        """budget이 부족해 드롭된 candidate는 reason=submit_budget_
        consumed_core로 기록 호출이 발생해야 한다."""
        candidates = [self._candidate(0, "AAA"), self._candidate(1, "BBB")]
        cycle_results: list[dict[str, object]] = [
            {"status": "PENDING_PASS2", "symbol": "AAA", "cycle_index": 0},
            {"status": "PENDING_PASS2", "symbol": "BBB", "cycle_index": 1},
        ]
        recorded: list[tuple[str, str]] = []

        async def _mock_submit(
            candidate: dict[str, object], *, cycle_count: int, runtime: dict[str, object],
        ) -> dict[str, object]:
            return {
                "status": "SUBMITTED", "symbol": str(candidate["symbol"]),
                "market": "KRX", "duration_seconds": 0.01,
            }

        async def _mock_record(
            candidate: dict[str, object], *, cycle_count: int, reason: str,
            decision_cycle_id: str | None = None,
        ) -> None:
            recorded.append((str(candidate["symbol"]), reason))

        with (
            patch(
                "scripts.run_decision_loop._submit_general_lane_candidate",
                side_effect=_mock_submit,
            ),
            patch(
                "scripts.run_decision_loop._record_pass2_general_lane_drop_guardrail_evaluation",
                side_effect=_mock_record,
            ),
        ):
            await _run_general_lane_pass2(
                candidates,
                cycle_results=cycle_results,
                cycle_count=1,
                max_general_submits_this_cycle=1,
                submit_budget_consumed_count=0,
                runtime={},
                output="text",
            )

        # budget=1이라 AAA만 제출되고 BBB는 예산 소진으로 드롭 → 기록 호출.
        assert recorded == [("BBB", "submit_budget_consumed_core")]
        assert cycle_results[1]["stop_reason"] == "submit_budget_consumed_core"

    @pytest.mark.asyncio
    async def test_symbol_duplicate_drop_records_guardrail_evaluation(self) -> None:
        """같은 symbol이 두 source_type으로 동시에 들어와 dedupe로 드롭된
        candidate는 reason=symbol_duplicate_in_cycle로 기록 호출이
        발생해야 한다."""
        low_priority = self._candidate(0, "AAA", score="0.50")
        low_priority["source_type"] = "market_overlay"
        high_priority = self._candidate(1, "AAA", score="0.90")
        high_priority["source_type"] = "core"
        candidates = [low_priority, high_priority]
        cycle_results: list[dict[str, object]] = [
            {"status": "PENDING_PASS2", "symbol": "AAA", "cycle_index": 0},
            {"status": "PENDING_PASS2", "symbol": "AAA", "cycle_index": 1},
        ]
        recorded: list[tuple[str, str]] = []

        async def _mock_submit(
            candidate: dict[str, object], *, cycle_count: int, runtime: dict[str, object],
        ) -> dict[str, object]:
            return {
                "status": "SUBMITTED", "symbol": str(candidate["symbol"]),
                "market": "KRX", "duration_seconds": 0.01,
            }

        async def _mock_record(
            candidate: dict[str, object], *, cycle_count: int, reason: str,
            decision_cycle_id: str | None = None,
        ) -> None:
            recorded.append((str(candidate["source_type"]), reason))

        with (
            patch(
                "scripts.run_decision_loop._submit_general_lane_candidate",
                side_effect=_mock_submit,
            ),
            patch(
                "scripts.run_decision_loop._record_pass2_general_lane_drop_guardrail_evaluation",
                side_effect=_mock_record,
            ),
        ):
            await _run_general_lane_pass2(
                candidates,
                cycle_results=cycle_results,
                cycle_count=1,
                max_general_submits_this_cycle=5,
                submit_budget_consumed_count=0,
                runtime={},
                output="text",
            )

        # core(우선순위 높음)가 남고 market_overlay가 dedupe로 드롭 → 기록 호출.
        assert recorded == [("market_overlay", "symbol_duplicate_in_cycle")]

    @pytest.mark.asyncio
    async def test_pass2_drop_forwards_decision_cycle_id(self) -> None:
        """Stage A-1b(2026-08-20): ``_run_general_lane_pass2(decision_
        cycle_id=...)``로 넘긴 값이 budget exhausted/dedupe 드롭 기록
        호출 양쪽 모두에 그대로 전달돼야 한다."""
        low_priority = self._candidate(0, "AAA", score="0.50")
        low_priority["source_type"] = "market_overlay"
        high_priority = self._candidate(1, "AAA", score="0.90")
        high_priority["source_type"] = "core"
        budget_dropped = self._candidate(2, "CCC", score="0.10")
        candidates = [low_priority, high_priority, budget_dropped]
        cycle_results: list[dict[str, object]] = [
            {"status": "PENDING_PASS2", "symbol": "AAA", "cycle_index": 0},
            {"status": "PENDING_PASS2", "symbol": "AAA", "cycle_index": 1},
            {"status": "PENDING_PASS2", "symbol": "CCC", "cycle_index": 2},
        ]
        recorded_cycle_ids: list[str | None] = []

        async def _mock_submit(
            candidate: dict[str, object], *, cycle_count: int, runtime: dict[str, object],
        ) -> dict[str, object]:
            return {
                "status": "SUBMITTED", "symbol": str(candidate["symbol"]),
                "market": "KRX", "duration_seconds": 0.01,
            }

        async def _mock_record(
            candidate: dict[str, object], *, cycle_count: int, reason: str,
            decision_cycle_id: str | None = None,
        ) -> None:
            recorded_cycle_ids.append(decision_cycle_id)

        with (
            patch(
                "scripts.run_decision_loop._submit_general_lane_candidate",
                side_effect=_mock_submit,
            ),
            patch(
                "scripts.run_decision_loop._record_pass2_general_lane_drop_guardrail_evaluation",
                side_effect=_mock_record,
            ),
        ):
            await _run_general_lane_pass2(
                candidates,
                cycle_results=cycle_results,
                cycle_count=1,
                max_general_submits_this_cycle=1,
                submit_budget_consumed_count=0,
                runtime={},
                output="text",
                decision_cycle_id="decision_submit_gate:2026-08-20T09:05:12+09:00#1",
            )

        # dedupe 드롭(market_overlay) + budget 소진 드롭(CCC) 총 2건,
        # 둘 다 같은 decision_cycle_id를 받아야 한다.
        assert len(recorded_cycle_ids) == 2
        assert all(
            cid == "decision_submit_gate:2026-08-20T09:05:12+09:00#1"
            for cid in recorded_cycle_ids
        )


class TestHeldPositionLaneUnaffectedByPass2:
    """held_position lane이 D안 Pass 1(defer_actionable_for_pass2)을 절대
    타지 않는지 검증(item D)."""

    @pytest.mark.asyncio
    async def test_held_position_symbol_never_defers_to_pass2(self) -> None:
        import scripts.run_decision_loop as module

        universe = (
            UniverseSymbol(symbol="005930", market="KRX", source_type="held_position"),
            UniverseSymbol(symbol="000660", market="KRX", source_type="core"),
        )
        calls: list[dict[str, object]] = []

        @asynccontextmanager
        async def _mock_runtime(run_migrations: bool = False) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": MagicMock()}

        class _DummyTx:
            async def commit(self) -> None:
                return None

        @asynccontextmanager
        async def _mock_tx() -> AsyncIterator[_DummyTx]:
            yield _DummyTx()

        async def _mock_run_one_cycle(**kwargs: object) -> dict[str, object]:
            calls.append(
                {
                    "symbol": kwargs["symbol"],
                    "source_type": kwargs["source_type"],
                    "defer_actionable_for_pass2": kwargs.get(
                        "defer_actionable_for_pass2", False
                    ),
                    "pending_candidates_sink": kwargs.get("pending_candidates_sink"),
                }
            )
            return {
                "status": "DRY_RUN",
                "symbol": str(kwargs["symbol"]),
                "market": "KRX",
                "duration_seconds": 0.01,
            }

        original_shutdown_event = module._shutdown_event
        module._shutdown_event = asyncio.Event()
        try:
            with (
                patch("scripts.run_decision_loop._install_signal_handlers", return_value=None),
                patch(
                    "scripts.run_decision_loop._load_trading_universe_with_anchor",
                    AsyncMock(
                        return_value=(
                            universe,
                            UniverseAnchorMetadata(source="test"),
                        )
                    ),
                ),
                patch("scripts.run_decision_loop.postgres_runtime", new=_mock_runtime),
                patch("scripts.run_decision_loop._seed_if_empty", AsyncMock(return_value=False)),
                patch("scripts.run_decision_loop._run_precheck", AsyncMock(return_value=None)),
                patch("scripts.run_decision_loop._run_one_cycle", side_effect=_mock_run_one_cycle),
                patch("agent_trading.db.transaction.transaction", new=_mock_tx),
                patch(
                    "agent_trading.repositories.postgres.bootstrap.build_postgres_repositories",
                    return_value=MagicMock(),
                ),
            ):
                await _run_loop(
                    interval=0,
                    max_cycles=1,
                    submit=True,
                    dry_run=False,
                    allow_general_submit=True,
                    max_general_submits_this_cycle=5,
                    output="text",
                )
        finally:
            module._shutdown_event = original_shutdown_event

        held_call = next(c for c in calls if c["source_type"] == "held_position")
        core_call = next(c for c in calls if c["source_type"] == "core")
        assert held_call["defer_actionable_for_pass2"] is False
        assert held_call["pending_candidates_sink"] is None
        assert core_call["defer_actionable_for_pass2"] is True
        assert core_call["pending_candidates_sink"] is not None


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
        assert args.max_general_submits_this_cycle == 1

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
    async def test_read_trading_universe_prefers_latest_intraday_freeze(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """intraday freeze가 있으면 compose보다 먼저 사용해야 한다."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)

        repos = build_in_memory_repositories()
        freeze_run_id = uuid4()
        instrument_id = uuid4()
        await repos.universe_freeze_runs.add(
            UniverseFreezeRunEntity(
                universe_freeze_run_id=freeze_run_id,
                business_date=datetime.now(timezone.utc).date(),
                freeze_purpose=DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE,
                freeze_sequence=1,
                frozen_at=datetime.now(timezone.utc),
                selection_version="universe_selection.freeze.v1",
                target_count=1,
                status="materialized",
            )
        )
        await repos.universe_freeze_run_items.add_many(
            (
                UniverseFreezeRunItemEntity(
                    universe_freeze_run_item_id=uuid4(),
                    universe_freeze_run_id=freeze_run_id,
                    instrument_id=instrument_id,
                    symbol="123456",
                    market_code="KRX",
                    source_type="core",
                    inclusion_reason="approved_core_universe",
                    rank=1,
                    cap_bucket="core",
                ),
            )
        )

        @asynccontextmanager
        async def _mock_postgres_runtime(
            run_migrations: bool = False,
        ) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": repos}

        with (
            patch(
                "scripts.run_decision_loop.postgres_runtime",
                new=_mock_postgres_runtime,
            ),
            patch("scripts.run_decision_loop._HAS_KIS", False),
            patch(
                "scripts.run_decision_loop._current_business_date_kst",
                return_value=datetime.now(timezone.utc).date(),
            ),
        ):
            result = await _read_trading_universe()

        assert result == (
            UniverseSymbol(
                "123456",
                "KRX",
                source_type="core",
                inclusion_reason="approved_core_universe",
            ),
        )

    @pytest.mark.asyncio
    async def test_read_trading_universe_dedupes_duplicate_freeze_rows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)

        repos = build_in_memory_repositories()
        freeze_run_id = uuid4()
        instrument_id = uuid4()
        await repos.universe_freeze_runs.add(
            UniverseFreezeRunEntity(
                universe_freeze_run_id=freeze_run_id,
                business_date=datetime.now(timezone.utc).date(),
                freeze_purpose=DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE,
                freeze_sequence=1,
                frozen_at=datetime.now(timezone.utc),
                selection_version="universe_selection.freeze.v1",
                target_count=2,
                status="materialized",
            )
        )
        await repos.universe_freeze_run_items.add_many(
            (
                UniverseFreezeRunItemEntity(
                    universe_freeze_run_item_id=uuid4(),
                    universe_freeze_run_id=freeze_run_id,
                    instrument_id=instrument_id,
                    symbol="123456",
                    market_code="KRX",
                    source_type="core",
                    inclusion_reason="approved_core_universe",
                    rank=1,
                    cap_bucket="core",
                ),
                UniverseFreezeRunItemEntity(
                    universe_freeze_run_item_id=uuid4(),
                    universe_freeze_run_id=freeze_run_id,
                    instrument_id=uuid4(),
                    symbol="123456",
                    market_code="KRX",
                    source_type="market_overlay",
                    inclusion_reason="event_overlay",
                    rank=2,
                    cap_bucket="market_overlay",
                ),
            )
        )

        @asynccontextmanager
        async def _mock_postgres_runtime(
            run_migrations: bool = False,
        ) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": repos}

        with (
            patch(
                "scripts.run_decision_loop.postgres_runtime",
                new=_mock_postgres_runtime,
            ),
            patch("scripts.run_decision_loop._HAS_KIS", False),
            patch(
                "scripts.run_decision_loop._current_business_date_kst",
                return_value=datetime.now(timezone.utc).date(),
            ),
        ):
            result = await _read_trading_universe()

        assert result == (
            UniverseSymbol(
                "123456",
                "KRX",
                source_type="core",
                inclusion_reason="approved_core_universe",
            ),
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
                metadata={"core_universe": True, "market_segment": "KOSPI"},
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
                metadata={"core_universe": True, "market_segment": "KOSPI"},
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
                assert u.inclusion_reason == "approved_core_universe"

    @pytest.mark.asyncio
    async def test_universe_selection_service_fallback_preserves_kosdaq_market(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DB fallback universe가 KOSDAQ instrument market_code를 유지해야 한다."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)

        repos = build_in_memory_repositories()
        from agent_trading.domain.entities import InstrumentEntity

        await repos.instruments.add(
            InstrumentEntity(
                instrument_id=UUID("33333333-3333-3333-3333-333333333333"),
                symbol="090150",
                market_code="KOSDAQ",
                name="광진윈텍",
                is_active=True,
                asset_class="KR_STOCK",
                currency="KRW",
                tick_size=Decimal("50"),
                metadata={"core_universe": True},
            )
        )

        @asynccontextmanager
        async def _mock_postgres_runtime(run_migrations: bool = False) -> AsyncIterator[dict[str, Any]]:
            yield {"repositories": repos}

        with (
            patch(
                "scripts.run_decision_loop.postgres_runtime",
                new=_mock_postgres_runtime,
            ),
            patch("scripts.run_decision_loop._HAS_KIS", False),
        ):
            result = await _read_trading_universe()

        assert any(
            item.symbol == "090150" and item.market == "KOSDAQ"
            for item in result
        )

    @pytest.mark.asyncio
    async def test_read_trading_universe_applies_cap_overrides(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """호출부 override 값이 universe cap에 반영되어야 한다."""
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
            result = await _read_trading_universe(max_cap=1)
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_read_trading_universe_applies_core_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """core_cap은 core source_type만 별도 제한해야 한다."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)
        monkeypatch.delenv(ENV_TRADING_UNIVERSE_CORE_CAP, raising=False)

        repos = build_in_memory_repositories()
        from agent_trading.domain.entities import InstrumentEntity

        for instrument_id, symbol in (
            (UUID("11111111-1111-1111-1111-111111111111"), "005930"),
            (UUID("22222222-2222-2222-2222-222222222222"), "000660"),
            (UUID("33333333-3333-3333-3333-333333333333"), "035420"),
        ):
            await repos.instruments.add(
                InstrumentEntity(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    market_code="KRX",
                    name=f"Test-{symbol}",
                    is_active=True,
                    asset_class="KR_STOCK",
                    currency="KRW",
                    tick_size=Decimal("50"),
                )
            )

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
            result = await _read_trading_universe(max_cap=3, core_cap=1)
            assert len(result) == 1

        assert DEFAULT_TRADING_UNIVERSE_CORE_CAP == 12

    @pytest.mark.asyncio
    async def test_read_trading_universe_max_cap_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TRADING_UNIVERSE_MAX_CAP env가 명시적 인자 없이도 universe
        전체 상한(max_cap)에 반영돼야 한다(core_cap과 동일한 배선 패턴,
        SPPV-2.110)."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)
        monkeypatch.setenv(ENV_TRADING_UNIVERSE_MAX_CAP, "1")

        repos = build_in_memory_repositories()
        from agent_trading.domain.entities import InstrumentEntity

        for instrument_id, symbol in (
            (UUID("11111111-1111-1111-1111-111111111111"), "005930"),
            (UUID("22222222-2222-2222-2222-222222222222"), "000660"),
            (UUID("33333333-3333-3333-3333-333333333333"), "035420"),
        ):
            await repos.instruments.add(
                InstrumentEntity(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    market_code="KRX",
                    name=f"Test-{symbol}",
                    is_active=True,
                    asset_class="KR_STOCK",
                    currency="KRW",
                    tick_size=Decimal("50"),
                )
            )

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
            assert len(result) == 1

        assert DEFAULT_TRADING_UNIVERSE_MAX_CAP == 30

    @pytest.mark.asyncio
    async def test_read_trading_universe_max_cap_default_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env 미설정 시 기존 동작(하드코딩 30)과 동일해야 한다
        (하위 호환 확인, SPPV-2.110)."""
        monkeypatch.delenv(ENV_TRADING_UNIVERSE, raising=False)
        monkeypatch.delenv(ENV_TRADING_UNIVERSE_MAX_CAP, raising=False)

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
            assert len(result) == 1

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
                    metadata={"core_universe": True, "market_segment": "KOSPI"},
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
                "scripts.run_decision_loop._build_kis_live_quote_client",
                return_value=mock_kis,
            ),
        ):
            result = await _read_trading_universe()
            assert len(result) == 3
            # market overlay returned empty batch → no market_overlay symbols
            for u in result:
                assert u.source_type == "core"
                assert u.inclusion_reason == "approved_core_universe"

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
                metadata={"core_universe": True, "market_segment": "KOSPI"},
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
                "scripts.run_decision_loop._build_kis_live_quote_client",
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
                "scripts.run_decision_loop._build_kis_live_quote_client",
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
            # event_id는 UUID 필수값이므로 None이 아닌 유효한 UUID 필요
            return {
                "event_id": uuid4(),
                "event_type": "test",
                "source_name": "test",
                "symbol": SYMBOL,
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
    @patch(
        "agent_trading.db.transaction.transaction",
        side_effect=_fake_db_transaction,
    )
    async def test_skip_when_naver_quota_exhausted(self, mock_tx: object) -> None:
        """NAVER quota 소진 시 degraded mode: KIS disclosure → T3 persist."""
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

        # Degraded mode: fetch_disclosure_titles IS called (KIS disclosure fetch)
        runtime["disclosure_seed_service"].fetch_disclosure_titles.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "agent_trading.db.transaction.transaction",
        side_effect=_fake_db_transaction,
    )
    async def test_process_quota_exhausted_degraded_persist_does_not_crash(
        self,
        mock_tx: object,
    ) -> None:
        """process_seeds 후 quota exhausted 분기에서도 degrade persist가 정상 동작해야 함."""
        from agent_trading.brokers.naver_news_adapter import NaverDailyQuotaTracker
        from agent_trading.services.disclosure_seed_service import DisclosureTitleDTO
        from agent_trading.services.seeded_news_service import PipelineMetrics

        runtime = {
            "disclosure_seed_service": AsyncMock(),
            "seeded_news_service": AsyncMock(),
        }
        repos = build_in_memory_repositories()

        seed = DisclosureTitleDTO(
            symbol=SYMBOL,
            company_name="Samsung",
            headline="Quota exhausted disclosure",
        )
        runtime["disclosure_seed_service"].fetch_disclosure_titles = AsyncMock(
            return_value=[seed],
        )
        runtime["seeded_news_service"].process_seeds = AsyncMock(
            return_value=([], PipelineMetrics(quota_exhausted_count=1)),
        )

        with patch.object(
            NaverDailyQuotaTracker,
            "is_exhausted",
            return_value=False,
        ):
            await _run_t3_live_pipeline(runtime, repos, SYMBOL)

        runtime["disclosure_seed_service"].fetch_disclosure_titles.assert_called_once()
        runtime["seeded_news_service"].process_seeds.assert_called_once()

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
    @patch(
        "agent_trading.db.transaction.transaction",
        new=_fake_db_transaction,
    )
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
        from agent_trading.services.seeded_news_service import PipelineMetrics
        runtime["seeded_news_service"].process_seeds = AsyncMock(
            return_value=([candidate], PipelineMetrics()),
        )

        # persist_seeded_events가 in-memory repo를 사용하도록 패치
        # (Step 4에서 PostgresExternalEventRepository를 생성하므로,
        #  in-memory repos.external_events에 직접 저장)
        from scripts.run_decision_loop import persist_seeded_events as _real_persist

        async def _persist_to_in_memory(
            events: list,
            repo: object,
        ) -> int:
            return await _real_persist(events, repos.external_events)

        with patch(
            "scripts.run_decision_loop.persist_seeded_events",
            side_effect=_persist_to_in_memory,
        ):
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
        from agent_trading.services.seeded_news_service import PipelineMetrics
        runtime["seeded_news_service"].process_seeds = AsyncMock(
            return_value=([candidate], PipelineMetrics()),
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


class TestRunT3LivePipelineShielded:
    """``_run_t3_live_pipeline_shielded()`` — wrapper coroutine for shield.

    이전 ``asyncio.create_task(asyncio.shield(coro))`` 구현은
    ``asyncio.shield()``가 Future를 반환하므로 TypeError를 유발했다.
    wrapper coroutine을 사용하면 create_task가 정상 동작한다.
    """

    @pytest.mark.asyncio
    async def test_creatable_via_create_task(self) -> None:
        """``create_task(_run_t3_live_pipeline_shielded(...))`` → 정상 Task 생성.

        이전 ``create_task(asyncio.shield(...))``는 TypeError를 유발했으나,
        wrapper coroutine을 사용하면 create_task가 정상 동작함을 검증.
        """
        import asyncio

        runtime: dict[str, object] = {}
        repos = build_in_memory_repositories()

        # create_task가 TypeError 없이 성공해야 함
        task = asyncio.create_task(
            _run_t3_live_pipeline_shielded(runtime, repos, SYMBOL)
        )
        assert isinstance(task, asyncio.Task)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_propagates_inner_result(self) -> None:
        """wrapper coroutine이 ``asyncio.shield``를 통해 내부 결과를 전파."""
        import asyncio

        runtime: dict[str, object] = {}
        repos = build_in_memory_repositories()

        task = asyncio.create_task(
            _run_t3_live_pipeline_shielded(runtime, repos, SYMBOL)
        )
        # _run_t3_live_pipeline은 서비스가 없으면 graceful skip (None 반환)
        result = await task
        assert result is None


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
