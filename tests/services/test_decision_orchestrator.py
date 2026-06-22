from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agent_trading.domain.entities import (
    AccountEntity,
    AuditLogEntity,
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    ExternalEventEntity,
    InstrumentEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
    SignalFeatureSnapshotEntity,
    TradeDecisionEntity,
)
from agent_trading.domain.enums import (
    DecisionType,
    EntryStyle,
    Environment,
    OrderSide,
    OrderStatus,
    OrderType,
    PipelineStopReason,
    TimeInForce,
)
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.services.order_manager import OrderManager
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.common_types import AgentExecutionBundle
from agent_trading.services.decision_orchestrator import (
    AIDecisionInputs,
    AssembledContext,
    DeterministicDerivationBundle,
    DecisionOrchestratorService,
    OrderIntent,
    ScoreResult,
    StubScoreCalculator,
)
from agent_trading.services.execution_service import ExecutionService
from agent_trading.services.held_position_policy import is_held_position_sell_path
from agent_trading.services.market_regime import MarketRegimeAssessment
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)
from agent_trading.services.portfolio_allocation import PortfolioAllocationAssessment
from agent_trading.services.sizing_engine import (
    SizingResult,
    SizingInputs,
    calculate_sizing,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service() -> DecisionOrchestratorService:
    repos = build_in_memory_repositories()
    return DecisionOrchestratorService(repos=repos, use_subprocess_isolation=False)


@pytest.fixture
def sample_request() -> SubmitOrderRequest:
    return SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="test-001",
        correlation_id="corr-001",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
    )


@pytest.fixture
def seeded_service() -> DecisionOrchestratorService:
    """Service with a seeded decision context and config version."""
    repos = build_in_memory_repositories()

    # Seed a config version
    config_version = ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=uuid4(),
        environment=Environment.PAPER,
        version_tag="v1.0",
        config_json={"max_order_size": 100},
        checksum="abc123",
        activated_at=datetime.now(timezone.utc),
    )
    repos.config_versions._items[config_version.config_version_id] = config_version

    # Seed a decision context referencing the config version
    context = DecisionContextEntity(
        decision_context_id=uuid4(),
        account_id=uuid4(),
        strategy_id=uuid4(),
        config_version_id=config_version.config_version_id,
        market_timestamp=datetime.now(timezone.utc),
        correlation_id="corr-seeded",
    )
    repos.decision_contexts._items[context.decision_context_id] = context

    return DecisionOrchestratorService(repos=repos, use_subprocess_isolation=False)


@pytest.fixture
def seeded_service_with_account() -> DecisionOrchestratorService:
    """Service with a seeded account and config version for context creation.

    ``sample_request.account_ref="test_account"``에 매칭되는 account와
    활성 config version이 존재하므로, orchestrator가 ``_ensure_or_create_decision_context()``
    에서 새 ``DecisionContextEntity``를 생성할 수 있다.

    Note: ``sample_request.strategy_id``는 UUID 문자열이어야 하므로
    ``str(uuid4())``로 설정한다.
    """
    repos = build_in_memory_repositories()
    now = datetime.now(timezone.utc)

    # Seed an account matching sample_request.account_ref="test_account"
    account = AccountEntity(
        account_id=uuid4(),
        client_id=uuid4(),
        broker_account_id=uuid4(),
        environment=Environment.PAPER,
        account_alias="test_account",
        account_masked="test-****",
        status="active",
    )
    repos.accounts._items[account.account_id] = account

    # Seed a config version referencing the account's client_id
    config_version = ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=account.client_id,
        environment=Environment.PAPER,
        version_tag="v1.0",
        config_json={},
        checksum="abc123",
        activated_at=now,
    )
    repos.config_versions._items[config_version.config_version_id] = config_version

    return DecisionOrchestratorService(repos=repos, use_subprocess_isolation=False)


def test_agent_runner_receives_provider_runtime_from_orchestrator() -> None:
    repos = build_in_memory_repositories()
    service = DecisionOrchestratorService(
        repos=repos,
        use_subprocess_isolation=False,
        llm_provider="gemini",
        provider_api_key="gemini-key",
        provider_base_url="https://example.test/v1beta/openai/",
        provider_model_id="gemini-3.5-flash",
        provider_timeout_seconds=88,
    )

    assert service._agent_runner._provider_runtime == {
        "llm_provider": "gemini",
        "provider_api_key": "gemini-key",
        "provider_base_url": "https://example.test/v1beta/openai/",
        "provider_model_id": "gemini-3.5-flash",
        "provider_timeout_seconds": 88,
    }


# ---------------------------------------------------------------------------
# Existing tests (must remain green)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_returns_order_intent(service, sample_request):
    """assemble() returns an OrderIntent with the given fields."""
    decision_context_id = uuid4()
    order_intent_id = uuid4()

    intent = await service.assemble(
        sample_request,
        decision_context_id=decision_context_id,
        order_intent_id=order_intent_id,
    )

    assert intent.decision_context_id == decision_context_id
    assert intent.order_intent_id == order_intent_id
    # assemble() generates decision_id, decision_context_id, order_intent_id
    # so the assembled request differs from the original sample_request.
    # Verify that the original fields are preserved.
    assert intent.request.client_order_id == sample_request.client_order_id
    assert intent.request.correlation_id == sample_request.correlation_id
    assert intent.request.account_ref == sample_request.account_ref
    assert intent.request.symbol == sample_request.symbol
    assert intent.request.market == sample_request.market
    assert intent.request.side == sample_request.side
    assert intent.request.order_type == sample_request.order_type
    assert intent.request.quantity == sample_request.quantity
    assert intent.request.price == sample_request.price
    assert intent.request.strategy_id == sample_request.strategy_id
    # Generated fields should be populated
    assert intent.request.decision_id is not None
    assert intent.request.decision_context_id == str(decision_context_id)
    assert intent.request.order_intent_id == str(order_intent_id)


@pytest.mark.asyncio
async def test_assemble_without_optional_fields(service, sample_request):
    """assemble() works with None for optional fields and generates IDs."""
    intent = await service.assemble(sample_request)

    # When no decision_context_id is provided, it resolves to None (no contexts exist)
    assert intent.decision_context_id is None
    # order_intent_id is generated when not provided
    assert intent.order_intent_id is not None
    # Generated fields — no context created (empty repo → fail-open)
    assert intent.request.decision_id is not None
    assert intent.request.decision_context_id is None
    assert intent.request.order_intent_id == str(intent.order_intent_id)
    # Original fields preserved
    assert intent.request.client_order_id == sample_request.client_order_id
    assert intent.request.symbol == sample_request.symbol


@pytest.mark.asyncio
async def test_assemble_preserves_request_fields(service, sample_request):
    """assemble() preserves the original request fields."""
    intent = await service.assemble(sample_request)

    assert intent.request.client_order_id == "test-001"
    assert intent.request.symbol == "005930"
    assert intent.request.quantity == Decimal("10")
    assert intent.request.side == OrderSide.BUY
    assert intent.request.order_type == OrderType.LIMIT
    assert intent.request.time_in_force == TimeInForce.DAY


@pytest.mark.asyncio
async def test_assemble_prefers_latest_success_cash_snapshot_over_latest_stale(
    seeded_service_with_account: DecisionOrchestratorService,
) -> None:
    repos = seeded_service_with_account._repos
    account = next(iter(repos.accounts._items.values()))
    config_version = next(iter(repos.config_versions._items.values()))
    now = datetime.now(timezone.utc)

    stale_cash = CashBalanceSnapshotEntity(
        cash_balance_snapshot_id=uuid4(),
        account_id=account.account_id,
        currency="KRW",
        available_cash=Decimal("7000000"),
        settled_cash=Decimal("7000000"),
        unsettled_cash=Decimal("0"),
        source_of_truth="broker",
        snapshot_at=now,
        orderable_amount=Decimal("0"),
        fetch_status="stale",
    )
    fresh_cash = CashBalanceSnapshotEntity(
        cash_balance_snapshot_id=uuid4(),
        account_id=account.account_id,
        currency="KRW",
        available_cash=Decimal("7000000"),
        settled_cash=Decimal("7000000"),
        unsettled_cash=Decimal("0"),
        source_of_truth="broker",
        snapshot_at=now - timedelta(minutes=5),
        orderable_amount=Decimal("16000000"),
        fetch_status="success",
    )
    repos.cash_balance_snapshots._items[stale_cash.cash_balance_snapshot_id] = stale_cash
    repos.cash_balance_snapshots._items[fresh_cash.cash_balance_snapshot_id] = fresh_cash

    request = SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="cash-select-001",
        correlation_id="corr-cash-select-001",
        strategy_id=str(config_version.config_version_id),
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
    )

    intent = await seeded_service_with_account.assemble(request)

    assert intent.context.cash_balance_snapshot is not None
    assert intent.context.cash_balance_snapshot.cash_balance_snapshot_id == fresh_cash.cash_balance_snapshot_id
    assert intent.context.cash_balance_snapshot.fetch_status == "success"


@pytest.mark.asyncio
async def test_assemble_replaces_anchored_stale_cash_snapshot_with_latest_success(
    service: DecisionOrchestratorService,
) -> None:
    repos = service._repos
    now = datetime.now(timezone.utc)

    account = AccountEntity(
        account_id=uuid4(),
        client_id=uuid4(),
        broker_account_id=uuid4(),
        environment=Environment.PAPER,
        account_alias="stale_context_account",
        account_masked="stale-****",
        status="active",
    )
    repos.accounts._items[account.account_id] = account

    config_version = ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=account.client_id,
        environment=Environment.PAPER,
        version_tag="v1.0",
        config_json={},
        checksum="abc123",
        activated_at=now,
    )
    repos.config_versions._items[config_version.config_version_id] = config_version

    stale_cash = CashBalanceSnapshotEntity(
        cash_balance_snapshot_id=uuid4(),
        account_id=account.account_id,
        currency="KRW",
        available_cash=Decimal("7000000"),
        settled_cash=Decimal("7000000"),
        unsettled_cash=Decimal("0"),
        source_of_truth="broker",
        snapshot_at=now - timedelta(minutes=10),
        orderable_amount=Decimal("0"),
        fetch_status="stale",
    )
    fresh_cash = CashBalanceSnapshotEntity(
        cash_balance_snapshot_id=uuid4(),
        account_id=account.account_id,
        currency="KRW",
        available_cash=Decimal("7000000"),
        settled_cash=Decimal("7000000"),
        unsettled_cash=Decimal("0"),
        source_of_truth="broker",
        snapshot_at=now - timedelta(minutes=1),
        orderable_amount=Decimal("16500000"),
        fetch_status="success",
    )
    repos.cash_balance_snapshots._items[stale_cash.cash_balance_snapshot_id] = stale_cash
    repos.cash_balance_snapshots._items[fresh_cash.cash_balance_snapshot_id] = fresh_cash

    context = DecisionContextEntity(
        decision_context_id=uuid4(),
        account_id=account.account_id,
        strategy_id=uuid4(),
        config_version_id=config_version.config_version_id,
        market_timestamp=now,
        correlation_id="corr-stale-context",
        cash_balance_snapshot_id=stale_cash.cash_balance_snapshot_id,
    )
    repos.decision_contexts._items[context.decision_context_id] = context

    request = SubmitOrderRequest(
        account_ref="stale_context_account",
        client_order_id="cash-replace-001",
        correlation_id="corr-cash-replace-001",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
    )

    intent = await service.assemble(
        request,
        decision_context_id=context.decision_context_id,
    )
    updated_context = repos.decision_contexts._items[context.decision_context_id]

    assert intent.context.cash_balance_snapshot is not None
    assert intent.context.cash_balance_snapshot.cash_balance_snapshot_id == fresh_cash.cash_balance_snapshot_id
    assert updated_context.cash_balance_snapshot_id == fresh_cash.cash_balance_snapshot_id


@pytest.mark.asyncio
async def test_assemble_loads_latest_signal_feature_snapshot(
    seeded_service_with_account: DecisionOrchestratorService,
    sample_request: SubmitOrderRequest,
) -> None:
    repos = seeded_service_with_account._repos
    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol=sample_request.symbol,
        market_code=sample_request.market,
        asset_class="KR_STOCK",
        currency="KRW",
        name="삼성전자",
    )
    repos.instruments._items[instrument.instrument_id] = instrument
    snapshot = SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=uuid4(),
        instrument_id=instrument.instrument_id,
        timeframe="1d",
        snapshot_at=datetime.now(timezone.utc),
        feature_set_version="signal_backbone_v1",
        bar_count=80,
        fast_score=Decimal("0.31"),
        slow_score=Decimal("0.42"),
        overall_score=Decimal("0.37"),
        return_3m_pct=Decimal("7.00"),
        price_vs_sma_60_pct=Decimal("4.00"),
        component_scores_json={"slow_momentum": 0.4},
    )
    await repos.signal_feature_snapshots.add(snapshot)

    account = next(iter(repos.accounts._items.values()))
    config = next(iter(repos.config_versions._items.values()))
    repos.accounts.find_one = AsyncMock(return_value=account)  # type: ignore[method-assign]
    repos.config_versions.get_active = AsyncMock(  # type: ignore[method-assign]
        return_value=config
    )
    sample_request = dataclasses.replace(
        sample_request,
        strategy_id=str(uuid4()),
    )

    intent = await seeded_service_with_account.assemble(sample_request)

    assert intent.context.signal_feature_snapshot is not None
    assert (
        intent.context.signal_feature_snapshot.signal_feature_snapshot_id
        == snapshot.signal_feature_snapshot_id
    )
    assert intent.context.market_regime is not None
    assert intent.context.market_regime.regime_label == "bullish_trend"
    assert intent.context.strategy_selection is not None
    assert intent.context.strategy_selection.preferred_strategy == "swing_momentum"
    assert intent.context.portfolio_allocation is not None
    assert intent.context.portfolio_allocation.target_weight_pct == 8.0
    assert intent.context.deterministic_trigger is not None
    assert intent.context.deterministic_trigger.primary_candidate in {
        "BUY_CANDIDATE",
        "WATCH",
    }
    assert intent.context.decision_context is not None
    assert (
        intent.context.decision_context.signal_feature_snapshot_id
        == snapshot.signal_feature_snapshot_id
    )


@pytest.mark.asyncio
async def test_derive_deterministic_context_components_returns_expected_bundle(
    seeded_service_with_account: DecisionOrchestratorService,
    sample_request: SubmitOrderRequest,
) -> None:
    repos = seeded_service_with_account._repos
    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol=sample_request.symbol,
        market_code=sample_request.market,
        asset_class="KR_STOCK",
        currency="KRW",
        name="삼성전자",
    )
    repos.instruments._items[instrument.instrument_id] = instrument
    snapshot = SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=uuid4(),
        instrument_id=instrument.instrument_id,
        timeframe="1d",
        snapshot_at=datetime.now(timezone.utc),
        feature_set_version="signal_backbone_v1",
        bar_count=80,
        fast_score=Decimal("0.35"),
        slow_score=Decimal("0.40"),
        overall_score=Decimal("0.55"),
        return_3m_pct=Decimal("8.00"),
        price_vs_sma_60_pct=Decimal("5.00"),
        component_scores_json={},
    )
    await repos.signal_feature_snapshots.add(snapshot)

    bundle = await seeded_service_with_account._derive_deterministic_context_components(
        request=dataclasses.replace(
            sample_request,
            strategy_id=str(uuid4()),
            metadata={"source_type": "core"},
        ),
        config_version=next(iter(repos.config_versions._items.values())),
        instrument=instrument,
        position_snapshot=None,
        cash_balance_snapshot=None,
        risk_limit_snapshot=None,
    )

    assert bundle.source_type == "core"
    assert bundle.signal_feature_snapshot is not None
    assert bundle.signal_feature_snapshot.signal_feature_snapshot_id == snapshot.signal_feature_snapshot_id
    assert bundle.market_regime is not None
    assert bundle.strategy_selection is not None
    assert bundle.portfolio_allocation is not None
    assert bundle.deterministic_trigger is not None


def test_build_ai_policy_context_view_projects_deterministic_fields(
    service: DecisionOrchestratorService,
) -> None:
    now = datetime.now(timezone.utc)
    decision_context = DecisionContextEntity(
        decision_context_id=uuid4(),
        account_id=uuid4(),
        strategy_id=uuid4(),
        config_version_id=uuid4(),
        market_timestamp=now,
        correlation_id="corr-policy-view",
    )
    event = ExternalEventEntity(
        event_id=uuid4(),
        event_type="filing",
        source_name="dart",
        published_at=now,
        symbol="005930",
        market="KRX",
    )
    score = ScoreResult(score=0.61, threshold=0.5, reason_codes=("momentum",))
    market_regime = MarketRegimeAssessment(
        regime_label="bullish_trend",
        volatility_regime="normal_volatility",
        risk_tone="risk_on",
        confidence=0.7,
        half_life_hours=24,
        strategy_weights={"swing_momentum": 0.5},
        reason_codes=("trend_up",),
    )
    portfolio_allocation = PortfolioAllocationAssessment(
        target_weight_pct=8.0,
        current_weight_pct=2.0,
        max_single_position_pct=10.0,
        remaining_concentration_pct=8.0,
        remaining_gross_budget_pct=60.0,
        max_new_capital_pct=6.0,
        orderable_cash=Decimal("1000000"),
        available_allocation_cash=Decimal("900000"),
        recommended_max_order_value=Decimal("700000"),
        allocation_bias="accumulate",
        confidence=0.7,
        reason_codes=("portfolio_bullish_target",),
        metadata={"source_type": "core"},
    )
    deterministic_trigger = DeterministicTriggerAssessment(
        trigger_version="deterministic_trigger_v1",
        primary_candidate="WATCH",
        candidate_set=("WATCH", "BUY_CANDIDATE"),
        watch_candidate=True,
        buy_candidate=True,
        sell_candidate=False,
        reduce_candidate=False,
        candidate_confidence=0.58,
        entry_score=0.58,
        exit_score=0.20,
        watch_score=0.61,
        reason_codes=("trigger_core_watch_path",),
        thresholds={"watch_candidate_threshold": 0.45},
        metadata={"source_type": "core"},
    )
    assembled_context = AssembledContext(
        decision_context=decision_context,
        config_version=ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=uuid4(),
            environment=Environment.PAPER,
            version_tag="v1",
            config_json={"internal_only": True},
            checksum="checksum",
        ),
        recent_events=(event,),
        score=score,
        market_regime=market_regime,
        portfolio_allocation=portfolio_allocation,
        deterministic_trigger=deterministic_trigger,
        source_type="core",
    )

    policy_view = service._build_ai_policy_context_view(assembled_context)

    assert policy_view.decision_context is decision_context
    assert policy_view.recent_events == (event,)
    assert policy_view.score == score
    assert policy_view.market_regime is market_regime
    assert policy_view.portfolio_allocation is portfolio_allocation
    assert policy_view.deterministic_trigger is deterministic_trigger
    assert policy_view.source_type == "core"
    assert not hasattr(policy_view, "config_version")


# ---------------------------------------------------------------------------
# Priority 3: AssembledContext
# ---------------------------------------------------------------------------


class TestAssembledContext:
    """AssembledContext dataclass field requirements."""

    def test_default_construction(self) -> None:
        """AssembledContext can be constructed with defaults."""
        ctx = AssembledContext()
        assert ctx.decision_context is None
        assert ctx.config_version is None
        assert ctx.recent_events == ()
        assert ctx.score.score == 0.0
        assert ctx.score.threshold == 0.0
        assert ctx.score.reason_codes == ()
        # New fields default to None
        assert ctx.position_snapshot is None
        assert ctx.cash_balance_snapshot is None
        assert ctx.risk_limit_snapshot is None
        assert ctx.signal_feature_snapshot is None
        assert ctx.market_regime is None
        assert ctx.portfolio_allocation is None
        assert ctx.deterministic_trigger is None

    def test_full_construction(self) -> None:
        """AssembledContext can be constructed with all fields."""
        now = datetime.now(timezone.utc)
        decision_context = DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=uuid4(),
            strategy_id=uuid4(),
            config_version_id=uuid4(),
            market_timestamp=now,
            correlation_id="corr-001",
        )
        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=uuid4(),
            environment=Environment.PAPER,
            version_tag="v1",
            config_json={},
            checksum="abc",
        )
        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="test",
            source_name="test",
            published_at=now,
        )
        score = ScoreResult(score=0.75, threshold=0.5, reason_codes=("momentum",))

        # New snapshot entities
        position_snapshot = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            quantity=Decimal("100"),
            average_price=Decimal("50.00"),
            market_price=Decimal("52.00"),
            unrealized_pnl=Decimal("200.00"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        cash_balance_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=uuid4(),
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("500000"),
            unsettled_cash=Decimal("500000"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        risk_limit_snapshot = RiskLimitSnapshotEntity(
            risk_limit_snapshot_id=uuid4(),
            account_id=uuid4(),
            snapshot_at=now,
            nav=Decimal("10000000"),
            kill_switch_active=False,
            blocked_reason_codes=None,
        )
        signal_feature_snapshot = SignalFeatureSnapshotEntity(
            signal_feature_snapshot_id=uuid4(),
            instrument_id=uuid4(),
            timeframe="1d",
            snapshot_at=now,
            feature_set_version="signal_backbone_v1",
            bar_count=80,
            overall_score=Decimal("0.51"),
            component_scores_json={"slow_momentum": 0.6},
        )
        market_regime = MarketRegimeAssessment(
            regime_label="bullish_trend",
            volatility_regime="normal_volatility",
            risk_tone="risk_on",
            confidence=0.8,
            half_life_hours=24,
            strategy_weights={"swing_momentum": 0.45},
            reason_codes=("trend_up",),
        )
        from agent_trading.services.strategy_selection import StrategySelectionAssessment
        strategy_selection = StrategySelectionAssessment(
            preferred_strategy="swing_momentum",
            allowed_strategies=("swing_momentum", "event_continuation"),
            preferred_entry_style="LIMIT",
            preferred_time_horizon="swing",
            confidence=0.8,
            reason_codes=("bullish_trend_momentum",),
            metadata={"source_type": "core"},
        )
        portfolio_allocation = PortfolioAllocationAssessment(
            target_weight_pct=8.0,
            current_weight_pct=1.2,
            max_single_position_pct=10.0,
            remaining_concentration_pct=8.8,
            remaining_gross_budget_pct=60.0,
            max_new_capital_pct=6.8,
            orderable_cash=Decimal("1000000"),
            available_allocation_cash=Decimal("1000000"),
            recommended_max_order_value=Decimal("1000000"),
            allocation_bias="accumulate",
            confidence=0.8,
            reason_codes=("portfolio_bullish_target",),
            metadata={"source_type": "core"},
        )
        deterministic_trigger = DeterministicTriggerAssessment(
            trigger_version="deterministic_trigger_v1",
            primary_candidate="WATCH",
            candidate_set=("WATCH",),
            watch_candidate=True,
            buy_candidate=False,
            sell_candidate=False,
            reduce_candidate=False,
            candidate_confidence=0.52,
            entry_score=0.52,
            exit_score=0.18,
            watch_score=0.52,
            reason_codes=("trigger_core_watch_path",),
            thresholds={"watch_candidate_threshold": 0.45},
            metadata={"source_type": "core"},
        )

        ctx = AssembledContext(
            decision_context=decision_context,
            config_version=config_version,
            recent_events=(event,),
            score=score,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
            signal_feature_snapshot=signal_feature_snapshot,
            market_regime=market_regime,
            strategy_selection=strategy_selection,
            portfolio_allocation=portfolio_allocation,
            deterministic_trigger=deterministic_trigger,
        )

        assert ctx.decision_context is decision_context
        assert ctx.config_version is config_version
        assert len(ctx.recent_events) == 1
        assert ctx.recent_events[0] is event
        assert ctx.score.score == 0.75
        assert ctx.score.reason_codes == ("momentum",)
        # New fields
        assert ctx.position_snapshot is position_snapshot
        assert ctx.cash_balance_snapshot is cash_balance_snapshot
        assert ctx.risk_limit_snapshot is risk_limit_snapshot
        assert ctx.signal_feature_snapshot is signal_feature_snapshot
        assert ctx.market_regime is market_regime
        assert ctx.strategy_selection is strategy_selection
        assert ctx.portfolio_allocation is portfolio_allocation
        assert ctx.deterministic_trigger is deterministic_trigger

    def test_frozen(self) -> None:
        """AssembledContext is frozen."""
        ctx = AssembledContext()
        with pytest.raises(AttributeError):
            ctx.score = ScoreResult()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Priority 3: ScoreResult and StubScoreCalculator
# ---------------------------------------------------------------------------


class TestScoreResult:
    """ScoreResult dataclass."""

    def test_defaults(self) -> None:
        """ScoreResult has sensible defaults."""
        sr = ScoreResult()
        assert sr.score == 0.0
        assert sr.threshold == 0.0
        assert sr.reason_codes == ()

    def test_custom_values(self) -> None:
        """ScoreResult accepts custom values."""
        sr = ScoreResult(score=0.8, threshold=0.6, reason_codes=("a", "b"))
        assert sr.score == 0.8
        assert sr.threshold == 0.6
        assert sr.reason_codes == ("a", "b")


class TestStubScoreCalculator:
    """StubScoreCalculator returns zero-score result."""

    @pytest.mark.asyncio
    async def test_calculate_returns_zero_score(self) -> None:
        """StubScoreCalculator.calculate() returns ScoreResult with defaults."""
        calc = StubScoreCalculator()
        ctx = AssembledContext()
        result = await calc.calculate(ctx)
        assert isinstance(result, ScoreResult)
        assert result.score == 0.0
        assert result.threshold == 0.0
        assert result.reason_codes == ()


# ---------------------------------------------------------------------------
# Priority 3: OrderIntent extensions
# ---------------------------------------------------------------------------


class TestOrderIntentExtensions:
    """OrderIntent new fields (context, config_version_id, reason_codes)."""

    @pytest.mark.asyncio
    async def test_intent_contains_context(self, service, sample_request):
        """OrderIntent has context field populated."""
        intent = await service.assemble(sample_request)
        assert hasattr(intent, "context")
        assert isinstance(intent.context, AssembledContext)

    @pytest.mark.asyncio
    async def test_intent_contains_config_version_id(self, service, sample_request):
        """OrderIntent has config_version_id field."""
        intent = await service.assemble(sample_request)
        assert hasattr(intent, "config_version_id")

    @pytest.mark.asyncio
    async def test_intent_contains_reason_codes(self, service, sample_request):
        """OrderIntent has reason_codes field."""
        intent = await service.assemble(sample_request)
        assert hasattr(intent, "reason_codes")
        assert intent.reason_codes == ()

    @pytest.mark.asyncio
    async def test_intent_context_default_when_no_context(
        self, service, sample_request
    ):
        """OrderIntent.context has defaults when no decision context exists."""
        intent = await service.assemble(sample_request)
        assert intent.context.decision_context is None
        assert intent.context.config_version is None
        assert intent.context.recent_events == ()
        assert intent.context.score.score == 0.0

    @pytest.mark.asyncio
    async def test_intent_contains_ai_backend_inputs(
        self, service, sample_request
    ):
        """OrderIntent has ai_backend_inputs field populated (default stub)."""
        intent = await service.assemble(sample_request)
        assert hasattr(intent, "ai_backend_inputs")
        assert isinstance(intent.ai_backend_inputs, AIDecisionInputs)

    @pytest.mark.asyncio
    async def test_ai_backend_inputs_defaults_on_stub(
        self, service, sample_request
    ):
        """Stub agents produce deterministic safe-fallback defaults."""
        intent = await service.assemble(sample_request)
        inputs = intent.ai_backend_inputs
        # FDC defaults
        assert inputs.decision_type == "HOLD"
        assert inputs.confidence == 0.0
        assert inputs.conviction == 0.0
        assert inputs.reason_codes == ()
        assert inputs.opposing_evidence == ()
        # AR defaults (size_adjustment_factor=0.0 from stub AIRiskOutput)
        assert inputs.risk_opinion == "allow"
        assert inputs.risk_score == 0.0
        assert inputs.risk_confidence == 0.0
        assert inputs.size_adjustment_factor == 0.0
        assert inputs.risk_reason_codes == ()
        assert inputs.risk_flags == ()
        # EI defaults
        assert inputs.event_bias == "neutral"
        assert inputs.event_conflict is False
        assert inputs.event_reason_codes == ()
        # schema_versions is a tuple (not a dict)
        assert isinstance(inputs.schema_versions, tuple)
        assert not isinstance(inputs.schema_versions, dict)

    @pytest.mark.asyncio
    async def test_ai_backend_inputs_different_from_reason_codes(
        self, service, sample_request
    ):
        """AIDecisionInputs.reason_codes is distinct from OrderIntent.reason_codes."""
        intent = await service.assemble(sample_request)
        # OrderIntent.reason_codes comes from ScoreResult (deterministic)
        assert intent.reason_codes == ()
        # AIDecisionInputs.reason_codes comes from FDC agent output
        assert intent.ai_backend_inputs.reason_codes == ()
        # They are different objects (different sources)
        assert intent.reason_codes is not intent.ai_backend_inputs.reason_codes or (
            intent.reason_codes == () and intent.ai_backend_inputs.reason_codes == ()
        )

    @pytest.mark.asyncio
    async def test_ai_backend_inputs_direct_defaults(
        self
    ):
        """AIDecisionInputs() direct construction has correct defaults."""
        inputs = AIDecisionInputs()
        # size_adjustment_factor defaults to 0.0 (matches AIRiskOutput default)
        assert inputs.size_adjustment_factor == 0.0
        # schema_versions defaults to empty tuple
        assert inputs.schema_versions == ()
        assert isinstance(inputs.schema_versions, tuple)

    @pytest.mark.asyncio
    async def test_ai_backend_inputs_schema_versions_immutable(
        self
    ):
        """schema_versions is a deeply immutable tuple structure."""
        inputs = AIDecisionInputs(
            schema_versions=(
                ("event_interpretation", "v1"),
                ("ai_risk", "v2"),
            )
        )
        assert isinstance(inputs.schema_versions, tuple)
        assert not isinstance(inputs.schema_versions, dict)
        assert len(inputs.schema_versions) == 2
        sv = dict(inputs.schema_versions)
        assert sv["event_interpretation"] == "v1"
        assert sv["ai_risk"] == "v2"

        # Frozen dataclass prevents mutation at the top level
        with pytest.raises(AttributeError):
            # slot frozen — cannot assign
            inputs.schema_versions = ()  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_ai_backend_inputs_does_not_affect_submit_request(
        self, service, sample_request
    ):
        """ai_backend_inputs populated but SubmitOrderRequest preserves original fields.

        This verifies the AI-to-execution safety boundary: even when
        ``ai_backend_inputs`` carries the full AI decision payload, the
        ``SubmitOrderRequest`` (which is what the broker receives) is
        assembled exclusively from the original ``request`` fields, not
        from any AI-derived data.
        """
        intent = await service.assemble(sample_request)

        # ai_backend_inputs is populated (stub agents produce defaults)
        assert intent.ai_backend_inputs is not None
        assert intent.ai_backend_inputs.decision_type == "HOLD"

        # SubmitOrderRequest preserves ALL original fields — ai_backend_inputs
        # is NOT injected into the request payload.
        assert intent.request.client_order_id == sample_request.client_order_id
        assert intent.request.correlation_id == sample_request.correlation_id
        assert intent.request.account_ref == sample_request.account_ref
        assert intent.request.symbol == sample_request.symbol
        assert intent.request.market == sample_request.market
        assert intent.request.side == sample_request.side
        assert intent.request.order_type == sample_request.order_type
        assert intent.request.quantity == sample_request.quantity
        assert intent.request.price == sample_request.price
        assert intent.request.strategy_id == sample_request.strategy_id
        assert intent.request.time_in_force == sample_request.time_in_force

        # Verify ai_backend_inputs is NOT a field of SubmitOrderRequest
        assert not hasattr(intent.request, "ai_backend_inputs")

# ---------------------------------------------------------------------------
# Priority 3: Config version connection
# ---------------------------------------------------------------------------


class TestConfigVersionConnection:
    """Config version lookup via decision_context.config_version_id."""

    @pytest.mark.asyncio
    async def test_config_version_resolved_when_context_exists(
        self, seeded_service, sample_request
    ):
        """Config version is resolved from seeded decision context."""
        # Retrieve the seeded context ID from the fixture's repos
        repos = seeded_service._repos
        context_id = next(iter(repos.decision_contexts._items))
        intent = await seeded_service.assemble(
            sample_request,
            decision_context_id=context_id,
        )
        assert intent.config_version_id is not None
        assert intent.context.config_version is not None
        assert intent.context.config_version.version_tag == "v1.0"

    @pytest.mark.asyncio
    async def test_config_version_none_when_no_context(
        self, service, sample_request
    ):
        """Config version is None when no decision context exists."""
        intent = await service.assemble(sample_request)
        assert intent.config_version_id is None
        assert intent.context.config_version is None


# ---------------------------------------------------------------------------
# Priority 3: External event stub
# ---------------------------------------------------------------------------


class TestExternalEventStub:
    """External event query stub does not break assemble()."""

    @pytest.mark.asyncio
    async def test_external_events_empty_when_no_events(
        self, service, sample_request
    ):
        """recent_events is empty when no external events exist."""
        intent = await service.assemble(sample_request)
        assert intent.context.recent_events == ()

    @pytest.mark.asyncio
    async def test_external_events_stub_does_not_raise(
        self, service, sample_request
    ):
        """External event query stub does not raise during assemble()."""
        # Even with no events, assemble() should complete without error
        intent = await service.assemble(sample_request)
        assert isinstance(intent, object)


# ---------------------------------------------------------------------------
# Priority 3: ScoreCalculator stub
# ---------------------------------------------------------------------------


class TestScoreCalculatorStub:
    """ScoreCalculator stub does not break existing flow."""

    @pytest.mark.asyncio
    async def test_default_stub_used_when_no_calculator(
        self, service, sample_request
    ):
        """Default StubScoreCalculator is used when no calculator injected."""
        intent = await service.assemble(sample_request)
        assert intent.reason_codes == ()
        assert intent.context.score.score == 0.0

    @pytest.mark.asyncio
    async def test_custom_calculator_injected(self, sample_request):
        """Custom ScoreCalculator is called during assemble()."""

        class CustomCalculator:
            async def calculate(self, context: AssembledContext) -> ScoreResult:
                return ScoreResult(
                    score=0.9, threshold=0.5, reason_codes=("custom",)
                )

        repos = build_in_memory_repositories()
        service = DecisionOrchestratorService(
            repos=repos, score_calculator=CustomCalculator(), use_subprocess_isolation=False
        )
        intent = await service.assemble(sample_request)

        assert intent.context.score.score == 0.9
        assert intent.context.score.threshold == 0.5
        assert intent.reason_codes == ("custom",)

    @pytest.mark.asyncio
    async def test_calculator_stub_keeps_flow_intact(
        self, service, sample_request
    ):
        """ScoreCalculator stub does not alter existing assemble() flow."""
        intent = await service.assemble(sample_request)
        # Core fields still populated
        assert intent.order_intent_id is not None
        assert intent.request.client_order_id == sample_request.client_order_id
        assert intent.request.symbol == sample_request.symbol


# ---------------------------------------------------------------------------
# Priority: position_snapshot_id source-of-truth
# ---------------------------------------------------------------------------


class TestPositionSnapshotSourceOfTruth:
    """position_snapshot_id is the strongest source of truth for replay.

    ``decision_context.position_snapshot_id`` -> ``get(id)`` must be accepted
    unconditionally, even when the instrument catalog lookup returns ``None``.
    The latest-fallback path (``list_latest_by_account``) still uses instrument
    symbol filtering as before.
    """

    @pytest.mark.asyncio
    async def test_explicit_snapshot_survives_instrument_failure(
        self, sample_request
    ):
        """Explicit position_snapshot_id is accepted even when instrument
        lookup yields None (no instrument seeded)."""
        repos = build_in_memory_repositories()

        # Seed a decision context with an explicit position_snapshot_id
        ctx_id = uuid4()
        snap_id = uuid4()
        account_id = uuid4()
        strategy_id = uuid4()
        config_id = uuid4()
        now = datetime.now(timezone.utc)

        context = DecisionContextEntity(
            decision_context_id=ctx_id,
            account_id=account_id,
            strategy_id=strategy_id,
            config_version_id=config_id,
            market_timestamp=now,
            correlation_id="corr-snapshot-test",
            position_snapshot_id=snap_id,
        )
        repos.decision_contexts._items[ctx_id] = context

        # Seed the referenced PositionSnapshotEntity
        snapshot = PositionSnapshotEntity(
            position_snapshot_id=snap_id,
            account_id=account_id,
            instrument_id=uuid4(),  # any instrument_id works
            quantity=Decimal("100"),
            average_price=Decimal("50000"),
            market_price=Decimal("50500"),
            unrealized_pnl=Decimal("50000"),
            source_of_truth="reconciliation",
            snapshot_at=now,
        )
        repos.position_snapshots._items[snap_id] = snapshot

        # Do NOT seed any InstrumentEntity → get_by_symbol() returns None

        service = DecisionOrchestratorService(repos=repos, use_subprocess_isolation=False)
        intent = await service.assemble(sample_request, decision_context_id=ctx_id)

        # The explicit snapshot must survive even though instrument is None
        assert intent.context.position_snapshot is not None
        assert intent.context.position_snapshot.position_snapshot_id == snap_id

    @pytest.mark.asyncio
    async def test_latest_fallback_with_symbol_filtering(
        self, sample_request
    ):
        """Without explicit position_snapshot_id, the latest snapshot matching
        the request symbol is picked via instrument filtering."""
        repos = build_in_memory_repositories()

        account_id = uuid4()
        strategy_id = uuid4()
        config_id = uuid4()
        now = datetime.now(timezone.utc)

        # Seed an instrument matching the sample request symbol/market
        instrument = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="005930",
            market_code="KRX",
            asset_class="stock",
            currency="KRW",
            name="Samsung Electronics",
        )
        repos.instruments._items[instrument.instrument_id] = instrument

        # Seed multiple PositionSnapshotEntity entries for the same account;
        # only one matches the seeded instrument_id.
        wrong_instrument_id = uuid4()

        old_snapshot = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account_id,
            instrument_id=wrong_instrument_id,
            quantity=Decimal("50"),
            average_price=Decimal("60000"),
            market_price=Decimal("61000"),
            unrealized_pnl=Decimal("50000"),
            source_of_truth="broker",
            snapshot_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        repos.position_snapshots._items[old_snapshot.position_snapshot_id] = old_snapshot

        matching_snapshot = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument.instrument_id,
            quantity=Decimal("100"),
            average_price=Decimal("50000"),
            market_price=Decimal("50500"),
            unrealized_pnl=Decimal("50000"),
            source_of_truth="reconciliation",
            snapshot_at=now,
        )
        repos.position_snapshots._items[matching_snapshot.position_snapshot_id] = matching_snapshot

        # Seed a decision context WITHOUT position_snapshot_id
        ctx_id = uuid4()
        context = DecisionContextEntity(
            decision_context_id=ctx_id,
            account_id=account_id,
            strategy_id=strategy_id,
            config_version_id=config_id,
            market_timestamp=now,
            correlation_id="corr-fallback-test",
            position_snapshot_id=None,
        )
        repos.decision_contexts._items[ctx_id] = context

        service = DecisionOrchestratorService(repos=repos, use_subprocess_isolation=False)
        intent = await service.assemble(sample_request, decision_context_id=ctx_id)

        # The matching snapshot (same instrument_id as the resolved instrument)
        # should be picked via the fallback path.
        assert intent.context.position_snapshot is not None
        assert intent.context.position_snapshot.position_snapshot_id == matching_snapshot.position_snapshot_id
        assert intent.context.position_snapshot.instrument_id == instrument.instrument_id
        assert intent.context.position_snapshot.quantity == Decimal("100")


# ---------------------------------------------------------------------------
# TradeDecision persistence
# ---------------------------------------------------------------------------


class TestTradeDecisionPersistence:
    @pytest.mark.asyncio
    async def test_assemble_persists_trade_decision_for_context(
        self, sample_request: SubmitOrderRequest
    ) -> None:
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        strategy_id = uuid4()

        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=uuid4(),
            environment=Environment.PAPER,
            version_tag="v1",
            config_json={},
            checksum="sum",
            activated_at=now,
        )
        await repos.config_versions.add(config_version)

        context = DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=uuid4(),
            strategy_id=strategy_id,
            config_version_id=config_version.config_version_id,
            market_timestamp=now,
            correlation_id="corr-persist",
            created_at=now,
        )
        await repos.decision_contexts.add(context)

        service = DecisionOrchestratorService(repos=repos, use_subprocess_isolation=False)
        intent = await service.assemble(
            sample_request,
            decision_context_id=context.decision_context_id,
        )

        assert intent.request.decision_id is not None
        persisted = await repos.trade_decisions.get_by_context(
            context.decision_context_id
        )
        assert persisted is not None
        assert str(persisted.trade_decision_id) == intent.request.decision_id
        assert persisted.decision_type == DecisionType.HOLD
        assert persisted.side == OrderSide.BUY
        assert persisted.strategy_id == strategy_id
        assert persisted.entry_style == EntryStyle.LIMIT
        assert persisted.quantity == Decimal("10")
        assert persisted.entry_price == Decimal("50000")
        assert persisted.max_order_value == Decimal("500000")
        assert persisted.risk_check_passed is True
        assert persisted.agent_version_json == {
            "event_interpretation": "v1",
            "ai_risk": "v1",
            "final_decision_composer": "v1",
        }

    @pytest.mark.asyncio
    async def test_assemble_reuses_existing_trade_decision_for_context(
        self, sample_request: SubmitOrderRequest
    ) -> None:
        """INSERT-only 정책: 동일 context 2회 assemble 시 TD가 2건 생성됨."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        context = DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=uuid4(),
            strategy_id=uuid4(),
            config_version_id=uuid4(),
            market_timestamp=now,
            correlation_id="corr-reuse",
            created_at=now,
        )
        await repos.decision_contexts.add(context)

        service = DecisionOrchestratorService(repos=repos, use_subprocess_isolation=False)
        first = await service.assemble(
            sample_request,
            decision_context_id=context.decision_context_id,
        )
        second = await service.assemble(
            sample_request,
            decision_context_id=context.decision_context_id,
        )

        decisions = await repos.trade_decisions.list_all()
        assert len(decisions) == 2
        assert first.request.decision_id != second.request.decision_id


class TestWatchCandidateUpgradeGuard:
    @pytest.mark.asyncio
    async def test_core_watch_candidate_blocks_fdc_approve_upgrade(
        self, sample_request: SubmitOrderRequest
    ) -> None:
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        strategy_id = uuid4()

        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=uuid4(),
            environment=Environment.PAPER,
            version_tag="v1",
            config_json={},
            checksum="sum",
            activated_at=now,
        )
        await repos.config_versions.add(config_version)

        context = DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=uuid4(),
            strategy_id=strategy_id,
            config_version_id=config_version.config_version_id,
            market_timestamp=now,
            correlation_id="corr-watch-guard",
            created_at=now,
        )
        await repos.decision_contexts.add(context)

        service = DecisionOrchestratorService(
            repos=repos,
            use_subprocess_isolation=False,
        )
        deterministic_trigger = DeterministicTriggerAssessment(
            trigger_version="deterministic_trigger_v1",
            primary_candidate="WATCH",
            candidate_set=("WATCH",),
            watch_candidate=True,
            buy_candidate=False,
            sell_candidate=False,
            reduce_candidate=False,
            candidate_confidence=0.58,
            entry_score=0.58,
            exit_score=0.22,
            watch_score=0.58,
            reason_codes=("trigger_watch_candidate",),
            thresholds={
                "buy_candidate_threshold": 0.65,
                "watch_candidate_threshold": 0.45,
            },
            metadata={"source_type": "core"},
        )
        service._derive_deterministic_context_components = AsyncMock(  # type: ignore[method-assign]
            return_value=DeterministicDerivationBundle(
                source_type="core",
                deterministic_trigger=deterministic_trigger,
            )
        )
        service._run_agents = AsyncMock(  # type: ignore[method-assign]
            return_value=AgentExecutionBundle(
                ai_inputs=AIDecisionInputs(
                    decision_type="APPROVE",
                    side="BUY",
                    confidence=0.81,
                    conviction=0.77,
                    reason_codes=("fdc_entry",),
                ),
                composer_output=FinalDecisionComposerOutput(
                    decision_type="APPROVE",
                    side="BUY",
                    confidence=0.81,
                    conviction=0.77,
                    reason_codes=("fdc_entry",),
                    summary="한국어 요약",
                ),
            )
        )

        intent = await service.assemble(
            sample_request,
            decision_context_id=context.decision_context_id,
        )

        assert intent.ai_backend_inputs.decision_type == "WATCH"
        assert intent.ai_backend_inputs.side == ""
        assert "watch_candidate_guard" in intent.ai_backend_inputs.reason_codes

        persisted = await repos.trade_decisions.get_by_context(
            context.decision_context_id
        )
        assert persisted is not None
        assert persisted.decision_type == DecisionType.WATCH
        assert persisted.side == OrderSide.BUY
        assert (
            persisted.decision_json["candidate_vs_final"]["alignment_status"]
            == "matched"
        )
        assert (
            persisted.decision_json["candidate_vs_final"]["final_decision_type"]
            == "WATCH"
        )

    @pytest.mark.asyncio
    async def test_market_overlay_watch_candidate_allows_fdc_approve_upgrade(
        self, sample_request: SubmitOrderRequest
    ) -> None:
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)

        context = DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=uuid4(),
            strategy_id=uuid4(),
            config_version_id=uuid4(),
            market_timestamp=now,
            correlation_id="corr-market-overlay",
            created_at=now,
        )
        await repos.decision_contexts.add(context)

        service = DecisionOrchestratorService(
            repos=repos,
            use_subprocess_isolation=False,
        )
        deterministic_trigger = DeterministicTriggerAssessment(
            trigger_version="deterministic_trigger_v1",
            primary_candidate="WATCH",
            candidate_set=("WATCH",),
            watch_candidate=True,
            buy_candidate=False,
            sell_candidate=False,
            reduce_candidate=False,
            candidate_confidence=0.57,
            entry_score=0.57,
            exit_score=0.19,
            watch_score=0.57,
            reason_codes=("trigger_watch_candidate",),
            thresholds={
                "buy_candidate_threshold": 0.65,
                "watch_candidate_threshold": 0.45,
            },
            metadata={"source_type": "market_overlay"},
        )
        service._derive_deterministic_context_components = AsyncMock(  # type: ignore[method-assign]
            return_value=DeterministicDerivationBundle(
                source_type="market_overlay",
                deterministic_trigger=deterministic_trigger,
            )
        )
        service._run_agents = AsyncMock(  # type: ignore[method-assign]
            return_value=AgentExecutionBundle(
                ai_inputs=AIDecisionInputs(
                    decision_type="APPROVE",
                    side="BUY",
                    confidence=0.74,
                    conviction=0.70,
                    reason_codes=("fdc_overlay_entry",),
                ),
                composer_output=FinalDecisionComposerOutput(
                    decision_type="APPROVE",
                    side="BUY",
                    confidence=0.74,
                    conviction=0.70,
                    reason_codes=("fdc_overlay_entry",),
                    summary="한국어 요약",
                ),
            )
        )

        intent = await service.assemble(
            sample_request,
            decision_context_id=context.decision_context_id,
        )

        assert intent.ai_backend_inputs.decision_type == "APPROVE"
        assert intent.ai_backend_inputs.side == "BUY"
        assert "watch_candidate_guard" not in intent.ai_backend_inputs.reason_codes

    @pytest.mark.asyncio
    async def test_core_buy_eligibility_guard_blocks_no_action_to_approve_upgrade(
        self, sample_request: SubmitOrderRequest
    ) -> None:
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        strategy_id = uuid4()

        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=uuid4(),
            environment=Environment.PAPER,
            version_tag="v1",
            config_json={},
            checksum="sum",
            activated_at=now,
        )
        await repos.config_versions.add(config_version)

        context = DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=uuid4(),
            strategy_id=strategy_id,
            config_version_id=config_version.config_version_id,
            market_timestamp=now,
            correlation_id="corr-buy-eligibility-guard",
            created_at=now,
        )
        await repos.decision_contexts.add(context)

        service = DecisionOrchestratorService(
            repos=repos,
            use_subprocess_isolation=False,
        )
        deterministic_trigger = DeterministicTriggerAssessment(
            trigger_version="deterministic_trigger_v1",
            primary_candidate="NO_ACTION",
            candidate_set=("NO_ACTION",),
            watch_candidate=False,
            buy_candidate=False,
            sell_candidate=False,
            reduce_candidate=False,
            candidate_confidence=0.52,
            entry_score=0.62,
            exit_score=0.18,
            watch_score=0.20,
            eligibility_passed=False,
            eligibility_reasons=("eligibility_low_turnover",),
            reason_codes=("trigger_no_action",),
            thresholds={
                "buy_candidate_threshold": 0.65,
                "watch_candidate_threshold": 0.45,
            },
            metadata={"source_type": "core"},
        )
        service._derive_deterministic_context_components = AsyncMock(  # type: ignore[method-assign]
            return_value=DeterministicDerivationBundle(
                source_type="core",
                deterministic_trigger=deterministic_trigger,
            )
        )
        service._run_agents = AsyncMock(  # type: ignore[method-assign]
            return_value=AgentExecutionBundle(
                ai_inputs=AIDecisionInputs(
                    decision_type="APPROVE",
                    side="BUY",
                    confidence=0.83,
                    conviction=0.78,
                    reason_codes=("fdc_entry",),
                ),
                composer_output=FinalDecisionComposerOutput(
                    decision_type="APPROVE",
                    side="BUY",
                    confidence=0.83,
                    conviction=0.78,
                    reason_codes=("fdc_entry",),
                    summary="한국어 요약",
                ),
            )
        )

        intent = await service.assemble(
            sample_request,
            decision_context_id=context.decision_context_id,
        )

        assert intent.ai_backend_inputs.decision_type == "HOLD"
        assert intent.ai_backend_inputs.side == ""
        assert "pre_ai_short_circuit" in intent.ai_backend_inputs.reason_codes
        assert "eligibility_low_turnover" in intent.ai_backend_inputs.reason_codes

    @pytest.mark.asyncio
    async def test_core_pre_agent_short_circuit_on_execution_ineligible_buy(
        self, sample_request: SubmitOrderRequest
    ) -> None:
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        strategy_id = uuid4()

        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=uuid4(),
            environment=Environment.PAPER,
            version_tag="v1",
            config_json={},
            checksum="sum",
            activated_at=now,
        )
        await repos.config_versions.add(config_version)

        context = DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=uuid4(),
            strategy_id=strategy_id,
            config_version_id=config_version.config_version_id,
            market_timestamp=now,
            correlation_id="corr-pre-agent-eligibility",
            created_at=now,
        )
        await repos.decision_contexts.add(context)

        service = DecisionOrchestratorService(
            repos=repos,
            use_subprocess_isolation=False,
        )
        deterministic_trigger = DeterministicTriggerAssessment(
            trigger_version="deterministic_trigger_v1",
            primary_candidate="NO_ACTION",
            candidate_set=("NO_ACTION",),
            watch_candidate=False,
            buy_candidate=False,
            sell_candidate=False,
            reduce_candidate=False,
            candidate_confidence=0.31,
            entry_score=0.31,
            exit_score=0.12,
            watch_score=0.20,
            eligibility_passed=False,
            eligibility_reasons=("eligibility_low_turnover",),
            reason_codes=("trigger_no_action",),
            thresholds={
                "buy_candidate_threshold": 0.65,
                "watch_candidate_threshold": 0.45,
            },
            metadata={"source_type": "core"},
        )
        service._derive_deterministic_context_components = AsyncMock(  # type: ignore[method-assign]
            return_value=DeterministicDerivationBundle(
                source_type="core",
                deterministic_trigger=deterministic_trigger,
            )
        )
        service._run_agents = AsyncMock(  # type: ignore[method-assign]
            side_effect=AssertionError("AI agents must not run"),
        )

        intent = await service.assemble(
            sample_request,
            decision_context_id=context.decision_context_id,
        )

        assert intent.ai_backend_inputs.decision_type == "HOLD"
        assert intent.ai_backend_inputs.side == ""
        assert "pre_ai_short_circuit" in intent.ai_backend_inputs.reason_codes
        assert "eligibility_low_turnover" in intent.ai_backend_inputs.reason_codes
        assert intent.ai_backend_inputs.ei_skipped is True
        assert intent.ai_backend_inputs.fdc_skipped is True
        service._run_agents.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_core_pre_agent_short_circuit_on_no_action_without_events(
        self, sample_request: SubmitOrderRequest
    ) -> None:
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        strategy_id = uuid4()

        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=uuid4(),
            environment=Environment.PAPER,
            version_tag="v1",
            config_json={},
            checksum="sum",
            activated_at=now,
        )
        await repos.config_versions.add(config_version)

        context = DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=uuid4(),
            strategy_id=strategy_id,
            config_version_id=config_version.config_version_id,
            market_timestamp=now,
            correlation_id="corr-pre-agent-no-event",
            created_at=now,
        )
        await repos.decision_contexts.add(context)

        service = DecisionOrchestratorService(
            repos=repos,
            use_subprocess_isolation=False,
        )
        deterministic_trigger = DeterministicTriggerAssessment(
            trigger_version="deterministic_trigger_v1",
            primary_candidate="NO_ACTION",
            candidate_set=("NO_ACTION",),
            watch_candidate=False,
            buy_candidate=False,
            sell_candidate=False,
            reduce_candidate=False,
            candidate_confidence=0.29,
            entry_score=0.29,
            exit_score=0.11,
            watch_score=0.18,
            eligibility_passed=True,
            eligibility_reasons=("eligibility_feature_coverage_ok",),
            reason_codes=("trigger_no_action",),
            thresholds={
                "buy_candidate_threshold": 0.65,
                "watch_candidate_threshold": 0.45,
            },
            metadata={"source_type": "core"},
        )
        service._derive_deterministic_context_components = AsyncMock(  # type: ignore[method-assign]
            return_value=DeterministicDerivationBundle(
                source_type="core",
                deterministic_trigger=deterministic_trigger,
            )
        )
        service._run_agents = AsyncMock(  # type: ignore[method-assign]
            side_effect=AssertionError("AI agents must not run"),
        )

        intent = await service.assemble(
            sample_request,
            decision_context_id=context.decision_context_id,
        )

        assert intent.ai_backend_inputs.decision_type == "HOLD"
        assert intent.ai_backend_inputs.side == ""
        assert "pre_ai_short_circuit" in intent.ai_backend_inputs.reason_codes
        assert "pre_ai_no_action_no_event" in intent.ai_backend_inputs.reason_codes
        assert intent.ai_backend_inputs.ei_skipped is True
        assert intent.ai_backend_inputs.fdc_skipped is True
        service._run_agents.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_core_no_recent_events_skips_ei_but_runs_ar_fdc(
        self, sample_request: SubmitOrderRequest
    ) -> None:
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        strategy_id = uuid4()

        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=uuid4(),
            environment=Environment.PAPER,
            version_tag="v1",
            config_json={},
            checksum="sum",
            activated_at=now,
        )
        await repos.config_versions.add(config_version)

        context = DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=uuid4(),
            strategy_id=strategy_id,
            config_version_id=config_version.config_version_id,
            market_timestamp=now,
            correlation_id="corr-skip-ei-only",
            created_at=now,
        )
        await repos.decision_contexts.add(context)

        service = DecisionOrchestratorService(
            repos=repos,
            use_subprocess_isolation=False,
        )
        deterministic_trigger = DeterministicTriggerAssessment(
            trigger_version="deterministic_trigger_v1",
            primary_candidate="WATCH",
            candidate_set=("WATCH",),
            watch_candidate=True,
            buy_candidate=False,
            sell_candidate=False,
            reduce_candidate=False,
            candidate_confidence=0.57,
            entry_score=0.57,
            exit_score=0.12,
            watch_score=0.57,
            eligibility_passed=True,
            eligibility_reasons=("eligibility_feature_coverage_ok",),
            reason_codes=("trigger_watch_candidate",),
            thresholds={
                "buy_candidate_threshold": 0.65,
                "watch_candidate_threshold": 0.45,
            },
            metadata={"source_type": "core"},
        )
        service._derive_deterministic_context_components = AsyncMock(  # type: ignore[method-assign]
            return_value=DeterministicDerivationBundle(
                source_type="core",
                deterministic_trigger=deterministic_trigger,
            )
        )

        mock_ei = AsyncMock(side_effect=AssertionError("EI must be skipped"))
        mock_ar = AsyncMock(return_value=AIRiskOutput())
        mock_fdc = AsyncMock(
            return_value=FinalDecisionComposerOutput(
                decision_type="HOLD",
                side="",
                summary="한국어 요약",
            )
        )
        service._event_interpretation_agent.run = mock_ei  # type: ignore[method-assign]
        service._ai_risk_agent.run = mock_ar  # type: ignore[method-assign]
        service._final_decision_agent.run = mock_fdc  # type: ignore[method-assign]

        intent = await service.assemble(
            sample_request,
            decision_context_id=context.decision_context_id,
        )

        assert intent.ai_backend_inputs.decision_type == "HOLD"
        assert intent.ai_backend_inputs.detected_event_count == 0
        assert intent.ai_backend_inputs.no_material_events is True
        assert intent.ai_backend_inputs.ei_skipped is True
        assert "skip_ei_no_recent_events" in intent.ai_backend_inputs.skip_reason_codes
        mock_ei.assert_not_awaited()
        mock_ar.assert_awaited_once()
        mock_fdc.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_core_high_risk_ar_skips_fdc(
        self, sample_request: SubmitOrderRequest
    ) -> None:
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        strategy_id = uuid4()

        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=uuid4(),
            environment=Environment.PAPER,
            version_tag="v1",
            config_json={},
            checksum="sum",
            activated_at=now,
        )
        await repos.config_versions.add(config_version)

        context = DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=uuid4(),
            strategy_id=strategy_id,
            config_version_id=config_version.config_version_id,
            market_timestamp=now,
            correlation_id="corr-skip-fdc-risk",
            created_at=now,
        )
        await repos.decision_contexts.add(context)

        service = DecisionOrchestratorService(
            repos=repos,
            use_subprocess_isolation=False,
        )
        deterministic_trigger = DeterministicTriggerAssessment(
            trigger_version="deterministic_trigger_v1",
            primary_candidate="WATCH",
            candidate_set=("WATCH",),
            watch_candidate=True,
            buy_candidate=False,
            sell_candidate=False,
            reduce_candidate=False,
            candidate_confidence=0.56,
            entry_score=0.56,
            exit_score=0.12,
            watch_score=0.56,
            eligibility_passed=True,
            eligibility_reasons=("eligibility_feature_coverage_ok",),
            reason_codes=("trigger_watch_candidate",),
            thresholds={
                "buy_candidate_threshold": 0.65,
                "watch_candidate_threshold": 0.45,
            },
            metadata={"source_type": "core"},
        )
        service._derive_deterministic_context_components = AsyncMock(  # type: ignore[method-assign]
            return_value=DeterministicDerivationBundle(
                source_type="core",
                deterministic_trigger=deterministic_trigger,
            )
        )

        mock_ar = AsyncMock(
            return_value=AIRiskOutput(
                risk_opinion="reject",
                risk_score=0.91,
                confidence=0.88,
                reason_codes=("risk_block",),
            )
        )
        mock_fdc = AsyncMock(side_effect=AssertionError("FDC must be skipped"))
        service._ai_risk_agent.run = mock_ar  # type: ignore[method-assign]
        service._final_decision_agent.run = mock_fdc  # type: ignore[method-assign]

        intent = await service.assemble(
            sample_request,
            decision_context_id=context.decision_context_id,
        )

        assert intent.ai_backend_inputs.decision_type == "WATCH"
        assert "pre_ai_risk_short_circuit" in intent.ai_backend_inputs.reason_codes
        assert intent.ai_backend_inputs.fdc_skipped is True
        assert "skip_fdc_high_risk" in intent.ai_backend_inputs.skip_reason_codes
        mock_ar.assert_awaited_once()
        mock_fdc.assert_not_awaited()

# ---------------------------------------------------------------------------
# Plan 32: AI-Broker Pre-Submit Safety Boundary — Test D
# ---------------------------------------------------------------------------


class TestAssembleAndCreateOrderFullFlow:
    """assemble() + create_order() full flow: AI recorder + order audit path.

    This test verifies that:
    1. After ``assemble()``, the in-memory recorder contains exactly 3
       ``AgentRunEntity`` entries (EI, AR, FDC).
    2. ``OrderManager.create_order(intent.request)`` succeeds and creates an
       order in ``DRAFT`` status.
    3. The audit log contains an ``order.create`` entry.
    4. The AI recorder and the order audit path coexist without interference.
    """

    @pytest.mark.asyncio
    async def test_assemble_and_create_order_full_flow(
        self, sample_request
    ):
        """Full flow: assemble → recorder 3 runs → create_order → audit log."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)

        # ── Seed account (needed by OrderManager.create_order) ──
        account = AccountEntity(
            account_id=uuid4(),
            client_id=uuid4(),
            broker_account_id=uuid4(),
            environment=Environment.PAPER,
            account_alias="test_account",  # matches sample_request.account_ref
            account_masked="test-****",
            status="active",
        )
        repos.accounts._items[account.account_id] = account

        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=account.client_id,
            environment=Environment.PAPER,
            version_tag="v1",
            config_json={},
            checksum="cfg-1",
            activated_at=now,
        )
        repos.config_versions._items[config_version.config_version_id] = config_version

        decision_context = DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=account.account_id,
            strategy_id=uuid4(),
            config_version_id=config_version.config_version_id,
            market_timestamp=now,
            correlation_id="corr-full-flow",
            created_at=now,
        )
        repos.decision_contexts._items[decision_context.decision_context_id] = (
            decision_context
        )

        # ── Seed instrument (needed by OrderManager.create_order) ──
        instrument = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="005930",  # matches sample_request.symbol
            market_code="KRX",  # matches sample_request.market
            asset_class="stock",
            currency="KRW",
            name="Samsung Electronics",
        )
        repos.instruments._items[instrument.instrument_id] = instrument

        # ── Create services sharing the same repos ──
        service = DecisionOrchestratorService(repos=repos, use_subprocess_isolation=False)
        manager = OrderManager(repos=repos, reconciliation_service=None)

        # ── Step 1: assemble() → recorder should have 3 agent runs ──
        intent = await service.assemble(
            sample_request,
            decision_context_id=decision_context.decision_context_id,
        )

        assert intent.ai_backend_inputs is not None
        runs = await service._agent_recorder.list_all()
        assert len(runs) == 3, (
            f"Expected 3 agent runs (EI, AR, FDC), got {len(runs)}"
        )
        agent_types = {r.agent_type for r in runs}
        assert agent_types == {
            "event_interpretation",
            "ai_risk",
            "final_decision_composer",
        }, f"Unexpected agent types: {agent_types}"

        # ── Step 2: create_order(intent.request) → DRAFT ──
        created = await manager.create_order(intent.request)

        assert created.status == OrderStatus.DRAFT, (
            f"Expected DRAFT, got {created.status}"
        )
        assert created.account_id == account.account_id
        assert created.instrument_id == instrument.instrument_id
        assert created.client_order_id == intent.request.client_order_id
        assert created.trade_decision_id is not None
        persisted = await repos.trade_decisions.get_by_context(
            decision_context.decision_context_id
        )
        assert persisted is not None
        assert created.trade_decision_id == persisted.trade_decision_id

        # ── Step 3: Audit log contains order.create ──
        audit_logs = await repos.audit_logs.list_by_correlation_id(
            intent.request.correlation_id
        )
        create_entries = [
            e for e in audit_logs if e.action == "order.create"
        ]
        assert len(create_entries) == 1, (
            f"Expected 1 order.create audit entry, got {len(create_entries)}"
        )
        assert create_entries[0].target_entity_type == "order_request"
        assert create_entries[0].target_entity_id == str(created.order_request_id)

        # ── Step 4: AI recorder + order audit path coexist (both populated) ──
        assert len(await service._agent_recorder.list_all()) == 3  # unchanged
        assert len(audit_logs) >= 1  # at least order.create
        # The recorder and audit log are independent storage backends
        assert await service._agent_recorder.list_all() is not audit_logs


# ---------------------------------------------------------------------------
# Decision context auto-creation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_creates_decision_context_when_not_provided(
    seeded_service_with_account, sample_request
):
    """Orchestrator creates a decision context when none is provided.

    조건: account + strategy_id(UUID) + config_version 모두 유효 → 생성 성공
    검증:
    - decision_context_id가 None이 아님
    - context가 repos에 persisted 됨
    - 3개 agent run이 recorder에 기록됨
    """
    service = seeded_service_with_account

    # sample_request.strategy_id="strat-001"은 UUID가 아니므로
    # 유효한 UUID 문자열로 교체
    import dataclasses
    request = dataclasses.replace(
        sample_request,
        strategy_id=str(uuid4()),
    )

    intent = await service.assemble(request)

    # Context should have been created
    assert intent.decision_context_id is not None, (
        "Expected orchestrator to create a decision context"
    )
    assert intent.request.decision_context_id == str(intent.decision_context_id)

    # Verify context was persisted in repos
    context = await service._repos.decision_contexts.get(
        intent.decision_context_id
    )
    assert context is not None
    assert context.account_id is not None
    assert context.config_version_id is not None
    assert context.strategy_id is not None
    assert context.market_timestamp is not None
    assert context.correlation_id is not None

    # Verify 3 agent runs recorded (recorder has no repo guard → all persisted)
    runs = await service._agent_recorder.list_all()
    assert len(runs) == 3, (
        f"Expected 3 agent runs (EI, AR, FDC), got {len(runs)}"
    )
    agent_types = {r.agent_type for r in runs}
    assert agent_types == {
        "event_interpretation",
        "ai_risk",
        "final_decision_composer",
    }


@pytest.mark.asyncio
async def test_assemble_fail_open_when_account_missing(service, sample_request):
    """Orchestrator fails open when account lookup fails.

    조건: account 없음 → context 생성 실패 → fail-open
    검증:
    - decision_context_id가 None
    - agent run은 계속 실행됨 (3개 기록)
    """
    intent = await service.assemble(sample_request)

    # No context created (empty repo → fail-open)
    assert intent.decision_context_id is None
    assert intent.request.decision_context_id is None

    # Agent runs still proceed (recorded in-memory)
    runs = await service._agent_recorder.list_all()
    assert len(runs) == 3, (
        f"Expected 3 agent runs even on fail-open, got {len(runs)}"
    )


# ===========================================================================
# Correlation duplicate → transaction 유지
# ===========================================================================


@pytest.mark.asyncio
async def test_ensure_or_create_decision_context_reuses_existing(
    seeded_service_with_account, sample_request
):
    """동일 correlation_id로 2회 호출 시 context 재사용 (transaction 유지).

    검증 목표
    --------
    - ``_ensure_or_create_decision_context()``가 ``existing_context_id``를 제공받으면
      바로 반환 (추가 insert 없음) → transaction abort 위험 없음
    - savepoint fallback (in-memory에서 connection 없을 때) 정상 동작

    Note
    ----
    실제 UniqueViolationError → savepoint rollback → transaction 유지 검증은
    postgres integration test 필요. 여기서는 구조적 안전성을 확인.
    """
    from dataclasses import replace

    # sample_request의 strategy_id를 UUID 문자열로 변경
    strategy_id = uuid4()
    req = replace(sample_request, strategy_id=str(strategy_id))

    # 1차: context 생성
    ctx_id_1 = await seeded_service_with_account._ensure_or_create_decision_context(
        req, None
    )
    assert ctx_id_1 is not None, "First call should create a context"

    # 2차: 동일 existing_context_id 전달 → 바로 반환 (추가 insert 없음)
    ctx_id_2 = await seeded_service_with_account._ensure_or_create_decision_context(
        req, ctx_id_1
    )
    assert ctx_id_2 == ctx_id_1, "Should return the same existing context ID"

    # Transaction 유지 확인: 후속 agent_run 기록 가능
    from agent_trading.domain.entities import AgentRunEntity
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    run = AgentRunEntity(
        agent_run_id=uuid4(),
        decision_context_id=ctx_id_1,
        agent_type="event_interpretation",
        started_at=now,
        completed_at=now,
    )
    # InFailedSQLTransactionError 없이 정상 저장되어야 함
    saved = await seeded_service_with_account._repos.agent_runs.add(run)
    assert saved is not None
    assert saved.agent_run_id == run.agent_run_id


@pytest.mark.asyncio
async def test_ensure_or_create_decision_context_none_no_connection_crash(
    service, sample_request
):
    """In-memory UoW (connection attr 없음)에서 savepoint 코드가 crash 나지 않음.

    ``service`` fixture는 in-memory repository를 사용하므로
    ``unit_of_work.connection``이 없다. savepoint fallback 경로 검증.
    """
    ctx_id = await service._ensure_or_create_decision_context(
        sample_request, None
    )
    # In-memory에서는 account lookup 실패 → fail-open → None
    # (crash만 안 나면 OK)
    _ = ctx_id


# ---------------------------------------------------------------------------
# Phase AF: _build_sizing_inputs — orderable_amount priority
# ---------------------------------------------------------------------------


class TestBuildSizingInputs:
    """``DecisionOrchestratorService._build_sizing_inputs()`` — orderable_amount."""

    def test_orderable_amount_passed_to_sizing_inputs(self, service: DecisionOrchestratorService) -> None:
        """_build_sizing_inputs passes orderable_amount to SizingInputs."""
        now = datetime.now(timezone.utc)
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=uuid4(),
            currency="KRW",
            available_cash=Decimal("5000000"),
            settled_cash=Decimal("3000000"),
            unsettled_cash=Decimal("2000000"),
            source_of_truth="broker",
            snapshot_at=now,
            orderable_amount=Decimal("-81419050"),
        )
        ctx = AssembledContext(
            cash_balance_snapshot=cash_snapshot,
        )
        intent = OrderIntent(
            decision_context_id=None,
            order_intent_id=None,
            request=SubmitOrderRequest(
                account_ref="test",
                client_order_id="test-001",
                correlation_id="corr-001",
                strategy_id="strat-001",
                symbol="005930",
                market="KRX",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                price=Decimal("50000"),
                time_in_force=TimeInForce.DAY,
            ),
            context=ctx,
            ai_backend_inputs=AIDecisionInputs(decision_type="BUY"),
        )
        sizing = ExecutionService._build_sizing_inputs(intent)
        assert isinstance(sizing, SizingInputs)
        assert sizing.orderable_amount == Decimal("-81419050")
        assert sizing.available_cash == Decimal("5000000")

    def test_orderable_amount_none_when_no_cash_snapshot(
        self, service: DecisionOrchestratorService
    ) -> None:
        """No cash_balance_snapshot → orderable_amount is None."""
        ctx = AssembledContext(cash_balance_snapshot=None)
        intent = OrderIntent(
            decision_context_id=None,
            order_intent_id=None,
            request=SubmitOrderRequest(
                account_ref="test",
                client_order_id="test-002",
                correlation_id="corr-002",
                strategy_id="strat-001",
                symbol="005930",
                market="KRX",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                price=Decimal("50000"),
                time_in_force=TimeInForce.DAY,
            ),
            context=ctx,
            ai_backend_inputs=AIDecisionInputs(decision_type="BUY"),
        )
        sizing = ExecutionService._build_sizing_inputs(intent)
        assert sizing.orderable_amount is None
        assert sizing.available_cash is None

    def test_legacy_max_position_size_ratio_is_normalized_to_percent(
        self, service: DecisionOrchestratorService
    ) -> None:
        """Legacy max_position_size=0.1 means 10%, not 0.1%.

        This mirrors the production 004990 MARKET BUY case:
        orderable_amount=9,014,583 and reference_price=25,400 should size near
        70 shares from the 20% cash allocation.  Before normalization, the
        concentration cap interpreted 0.1 as 0.1% of NAV and reduced this to
        one share.
        """
        now = datetime.now(timezone.utc)
        account_id = uuid4()
        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=uuid4(),
            environment=Environment.PAPER,
            version_tag="legacy-ratio",
            config_json={"max_position_size": "0.1"},
            checksum="legacy-ratio",
            activated_at=now,
        )
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account_id,
            currency="KRW",
            available_cash=Decimal("9014583"),
            settled_cash=Decimal("9014583"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
            orderable_amount=Decimal("9014583"),
            total_asset=Decimal("29880403"),
        )
        ctx = AssembledContext(
            config_version=config_version,
            cash_balance_snapshot=cash_snapshot,
        )
        intent = OrderIntent(
            decision_context_id=None,
            order_intent_id=None,
            request=SubmitOrderRequest(
                account_ref="test",
                client_order_id="test-legacy-ratio-001",
                correlation_id="corr-legacy-ratio-001",
                strategy_id="strat-001",
                symbol="004990",
                market="KRX",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1"),
                price=None,
                time_in_force=TimeInForce.DAY,
            ),
            context=ctx,
            ai_backend_inputs=AIDecisionInputs(decision_type="BUY"),
        )

        sizing_inputs = ExecutionService._build_sizing_inputs(
            intent,
            reference_price=Decimal("25400"),
        )
        sizing_result = calculate_sizing(sizing_inputs)

        assert sizing_inputs.max_single_position_pct == Decimal("10.0")
        assert sizing_result.quantity == Decimal("70")
        assert "position_concentration" not in sizing_result.applied_constraints

    def test_nested_max_single_position_pct_keeps_percent_semantics(
        self, service: DecisionOrchestratorService
    ) -> None:
        """Nested risk.max_single_position_pct remains an explicit percent."""
        now = datetime.now(timezone.utc)
        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=uuid4(),
            environment=Environment.PAPER,
            version_tag="nested-percent",
            config_json={
                "max_position_size": "0.1",
                "risk": {"max_single_position_pct": "5"},
            },
            checksum="nested-percent",
            activated_at=now,
        )
        ctx = AssembledContext(config_version=config_version)
        intent = OrderIntent(
            decision_context_id=None,
            order_intent_id=None,
            request=SubmitOrderRequest(
                account_ref="test",
                client_order_id="test-nested-percent-001",
                correlation_id="corr-nested-percent-001",
                strategy_id="strat-001",
                symbol="005930",
                market="KRX",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                price=Decimal("50000"),
                time_in_force=TimeInForce.DAY,
            ),
            context=ctx,
            ai_backend_inputs=AIDecisionInputs(decision_type="BUY"),
        )

        sizing_inputs = ExecutionService._build_sizing_inputs(intent)

        assert sizing_inputs.max_single_position_pct == Decimal("5")

    @pytest.mark.asyncio
    async def test_recent_active_buy_order_guard_detects_same_symbol(
        self,
    ) -> None:
        """Recent active BUY for the same symbol blocks re-entry."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        account_id = uuid4()
        instrument_id = uuid4()
        await repos.accounts.add(
            AccountEntity(
                account_id=account_id,
                client_id=uuid4(),
                broker_account_id=uuid4(),
                environment=Environment.PAPER,
                account_alias="test",
                account_masked="****",
                status="active",
            )
        )
        await repos.instruments.add(
            InstrumentEntity(
                instrument_id=instrument_id,
                symbol="004990",
                market_code="KRX",
                asset_class="equity",
                currency="KRW",
                name="롯데지주",
            )
        )
        existing_order_id = uuid4()
        await repos.orders.add(
            OrderRequestEntity(
                order_request_id=existing_order_id,
                account_id=account_id,
                instrument_id=instrument_id,
                client_order_id="existing-buy",
                idempotency_key="existing-buy",
                correlation_id="existing-buy",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                requested_quantity=Decimal("98"),
                status=OrderStatus.SUBMITTED,
                created_at=now,
            )
        )
        service = ExecutionService(repos)

        has_duplicate, duplicate_order_id = await service._has_recent_active_buy_order(
            account_id=account_id,
            symbol="004990",
            market="KRX",
            created_after=now - timedelta(minutes=15),
        )

        assert has_duplicate is True
        assert duplicate_order_id == str(existing_order_id)

    @pytest.mark.asyncio
    async def test_recent_active_buy_order_guard_ignores_old_order(
        self,
    ) -> None:
        """Old BUY orders outside the cooldown do not block new entries."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        account_id = uuid4()
        instrument_id = uuid4()
        await repos.instruments.add(
            InstrumentEntity(
                instrument_id=instrument_id,
                symbol="004990",
                market_code="KRX",
                asset_class="equity",
                currency="KRW",
                name="롯데지주",
            )
        )
        await repos.orders.add(
            OrderRequestEntity(
                order_request_id=uuid4(),
                account_id=account_id,
                instrument_id=instrument_id,
                client_order_id="old-buy",
                idempotency_key="old-buy",
                correlation_id="old-buy",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                requested_quantity=Decimal("98"),
                status=OrderStatus.SUBMITTED,
                created_at=now - timedelta(minutes=20),
            )
        )
        service = ExecutionService(repos)

        has_duplicate, duplicate_order_id = await service._has_recent_active_buy_order(
            account_id=account_id,
            symbol="004990",
            market="KRX",
            created_after=now - timedelta(minutes=15),
        )

        assert has_duplicate is False
        assert duplicate_order_id is None


# ---------------------------------------------------------------------------
# Sell path sizing fallback tests
# ---------------------------------------------------------------------------


class TestSellPathSizingFallback:
    """Phase 1.5 sizing fallback: when sizing returns 0 for SELL side,
    the request quantity should be used as fallback."""

    @pytest.fixture
    def sell_intent_no_position(self) -> OrderIntent:
        """OrderIntent with SELL side, no position snapshot (position_qty=None)."""
        ctx = AssembledContext(
            position_snapshot=None,
            cash_balance_snapshot=None,
            risk_limit_snapshot=None,
        )
        return OrderIntent(
            decision_context_id=None,
            order_intent_id=None,
            request=SubmitOrderRequest(
                account_ref="test",
                client_order_id="test-sell-fallback-001",
                correlation_id="corr-sell-fallback-001",
                strategy_id="strat-001",
                symbol="005930",
                market="KRX",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                price=Decimal("50000"),
                time_in_force=TimeInForce.DAY,
            ),
            context=ctx,
            ai_backend_inputs=AIDecisionInputs(
                decision_type="REDUCE",
                side="sell",
            ),
        )

    def test_sizing_fallback_behavior_for_sell_without_position(
        self,
        service: DecisionOrchestratorService,
        sell_intent_no_position: OrderIntent,
    ) -> None:
        """Sizing falls back to requested_quantity when position is unknown for SELL/REDUCE.

        _base_qty_reduce() returns requested_quantity when current_position_qty is None.
        This confirms the sizing engine itself does not block the sell path;
        the fallback in assemble_and_submit() is an additional safety net.
        """
        sizing_inputs = ExecutionService._build_sizing_inputs(sell_intent_no_position)
        sizing_result = calculate_sizing(sizing_inputs)

        # Without position data, _base_qty_reduce falls back to requested_quantity
        assert sizing_result.quantity == Decimal("10"), (
            f"Expected sizing to fallback to requested_quantity=10, "
            f"got {sizing_result.quantity}"
        )

    def test_sizing_fallback_uses_request_quantity_for_sell(
        self,
        service: DecisionOrchestratorService,
        sell_intent_no_position: OrderIntent,
    ) -> None:
        """The fallback logic should use intent.request.quantity when sizing returns 0."""
        sizing_inputs = ExecutionService._build_sizing_inputs(sell_intent_no_position)
        sizing_result = calculate_sizing(sizing_inputs)

        # Simulate the fallback logic from assemble_and_submit()
        effective_qty = sizing_result.quantity
        if effective_qty <= 0 and sell_intent_no_position.request.side == OrderSide.SELL:
            req_qty = sell_intent_no_position.request.quantity
            if req_qty > 0:
                effective_qty = req_qty

        assert effective_qty == Decimal("10"), (
            f"Expected fallback quantity=10, got {effective_qty}"
        )

    def test_held_position_reduce_zero_does_not_use_placeholder_fallback(
        self,
        service: DecisionOrchestratorService,
    ) -> None:
        """held_position REDUCE/EXIT는 0수량일 때 placeholder 1주 fallback을 타지 않아야 한다."""
        intent = OrderIntent(
            decision_context_id=None,
            order_intent_id=None,
            request=SubmitOrderRequest(
                account_ref="test",
                client_order_id="hp-sell-fallback-001",
                correlation_id="corr-hp-sell-fallback-001",
                strategy_id="strat-001",
                symbol="005930",
                market="KRX",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                price=Decimal("50000"),
                time_in_force=TimeInForce.DAY,
                metadata={"source_type": "held_position"},
            ),
            context=AssembledContext(source_type="held_position"),
            ai_backend_inputs=AIDecisionInputs(
                decision_type="REDUCE",
                side="sell",
            ),
        )
        sizing_result = SizingResult(
            quantity=Decimal("0"),
            skip_reason="sizing_rejected",
        )

        effective_qty = sizing_result.quantity
        is_hp_sell = is_held_position_sell_path(
            source_type=intent.context.source_type,
            decision_type=intent.ai_backend_inputs.decision_type,
            side=intent.request.side,
        )
        if effective_qty <= 0 and intent.request.side == OrderSide.SELL and not is_hp_sell:
            req_qty = intent.request.quantity
            if req_qty > 0:
                effective_qty = req_qty

        assert is_hp_sell is True
        assert effective_qty == Decimal("0")

    def test_sizing_fallback_for_exit_sell(
        self,
        service: DecisionOrchestratorService,
    ) -> None:
        """EXIT + SELL side: sizing returns 0 without position, fallback to request qty."""


class TestExecutionServiceSizingStopReason:
    def test_non_actionable_hold_maps_to_decision_hold(self) -> None:
        intent = OrderIntent(
            decision_context_id=uuid4(),
            order_intent_id=uuid4(),
            request=SubmitOrderRequest(
                account_ref="test",
                client_order_id="hold-001",
                correlation_id="corr-hold-001",
                strategy_id="strat-001",
                symbol="005930",
                market="KRX",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1"),
                price=None,
                time_in_force=TimeInForce.DAY,
            ),
            context=AssembledContext(),
            ai_backend_inputs=AIDecisionInputs(decision_type="HOLD"),
        )
        sizing_result = SizingResult(
            quantity=Decimal("0"),
            skip_reason="non_actionable_decision",
        )

        attempt_status, stop_reason, error_message = (
            ExecutionService._resolve_zero_quantity_outcome(intent, sizing_result)
        )

        assert attempt_status == "non_trade"
        assert stop_reason == PipelineStopReason.DECISION_HOLD.value
        assert error_message == PipelineStopReason.DECISION_HOLD.value

    def test_non_actionable_watch_maps_to_decision_watch(self) -> None:
        intent = OrderIntent(
            decision_context_id=uuid4(),
            order_intent_id=uuid4(),
            request=SubmitOrderRequest(
                account_ref="test",
                client_order_id="watch-001",
                correlation_id="corr-watch-001",
                strategy_id="strat-001",
                symbol="005930",
                market="KRX",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1"),
                price=None,
                time_in_force=TimeInForce.DAY,
            ),
            context=AssembledContext(),
            ai_backend_inputs=AIDecisionInputs(decision_type="WATCH"),
        )
        sizing_result = SizingResult(
            quantity=Decimal("0"),
            skip_reason="non_actionable_decision",
        )

        attempt_status, stop_reason, error_message = (
            ExecutionService._resolve_zero_quantity_outcome(intent, sizing_result)
        )

        assert attempt_status == "non_trade"
        assert stop_reason == PipelineStopReason.DECISION_WATCH.value
        assert error_message == PipelineStopReason.DECISION_WATCH.value

    def test_real_sizing_failure_keeps_sizing_rejected(self) -> None:
        intent = OrderIntent(
            decision_context_id=uuid4(),
            order_intent_id=uuid4(),
            request=SubmitOrderRequest(
                account_ref="test",
                client_order_id="buy-001",
                correlation_id="corr-buy-001",
                strategy_id="strat-001",
                symbol="005930",
                market="KRX",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1"),
                price=None,
                time_in_force=TimeInForce.DAY,
            ),
            context=AssembledContext(),
            ai_backend_inputs=AIDecisionInputs(decision_type="APPROVE"),
        )
        sizing_result = SizingResult(
            quantity=Decimal("0"),
            skip_reason="below_min_qty",
        )

        attempt_status, stop_reason, error_message = (
            ExecutionService._resolve_zero_quantity_outcome(intent, sizing_result)
        )

        assert attempt_status == "stopped"
        assert stop_reason == PipelineStopReason.SIZING_REJECTED.value
        assert error_message == "below_min_qty"
        ctx = AssembledContext(
            position_snapshot=None,
            cash_balance_snapshot=None,
            risk_limit_snapshot=None,
        )
        intent = OrderIntent(
            decision_context_id=None,
            order_intent_id=None,
            request=SubmitOrderRequest(
                account_ref="test",
                client_order_id="test-exit-sell-001",
                correlation_id="corr-exit-sell-001",
                strategy_id="strat-001",
                symbol="005930",
                market="KRX",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal("5"),
                price=Decimal("50000"),
                time_in_force=TimeInForce.DAY,
            ),
            context=ctx,
            ai_backend_inputs=AIDecisionInputs(
                decision_type="EXIT",
                side="sell",
            ),
        )

        sizing_inputs = ExecutionService._build_sizing_inputs(intent)
        sizing_result = calculate_sizing(sizing_inputs)

        # Simulate fallback
        effective_qty = sizing_result.quantity
        if effective_qty <= 0 and intent.request.side == OrderSide.SELL:
            req_qty = intent.request.quantity
            if req_qty > 0:
                effective_qty = req_qty

        assert effective_qty == Decimal("5"), (
            f"Expected fallback quantity=5 for EXIT+SELL, got {effective_qty}"
        )


class TestExecutionSizingSync:
    @pytest.mark.asyncio
    async def test_sync_trade_decision_execution_sizing_updates_analysis_fields(self) -> None:
        repos = build_in_memory_repositories()
        service = ExecutionService(repos)
        decision = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=uuid4(),
            decision_type=DecisionType.REDUCE,
            side=OrderSide.SELL,
            strategy_id=uuid4(),
            symbol="005930",
            market="KRX",
            entry_style=EntryStyle.LIMIT,
            created_at=datetime.now(timezone.utc),
            quantity=Decimal("1"),
            target_quantity=Decimal("1"),
            decision_json={"existing": True},
        )
        await repos.trade_decisions.add(decision)

        request = SubmitOrderRequest(
            account_ref="test",
            client_order_id="sizing-sync-001",
            correlation_id="corr-sizing-sync-001",
            strategy_id="strat-001",
            symbol="005930",
            market="KRX",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            price=Decimal("50000"),
            time_in_force=TimeInForce.DAY,
        )
        sizing_result = SizingResult(
            quantity=Decimal("37"),
            max_order_value=Decimal("1850000"),
            applied_constraints=("max_qty",),
        )

        await service._sync_trade_decision_execution_sizing(
            trade_decision_id=decision.trade_decision_id,
            request=request,
            original_request_quantity=Decimal("1"),
            effective_qty=Decimal("37"),
            sizing_result=sizing_result,
        )

        updated = await repos.trade_decisions.get(decision.trade_decision_id)
        assert updated is not None
        assert updated.quantity == Decimal("37")
        assert updated.target_quantity == Decimal("37")
        assert updated.max_order_value == Decimal("1850000")
        assert updated.target_notional == Decimal("1850000")
        assert updated.decision_json["existing"] is True
        assert updated.decision_json["execution_sizing"]["requested_quantity_before_sizing"] == "1"
        assert updated.decision_json["execution_sizing"]["resolved_quantity"] == "37"
        assert updated.decision_json["execution_sizing"]["applied_constraints"] == ["max_qty"]
