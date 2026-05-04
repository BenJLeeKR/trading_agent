from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    ExternalEventEntity,
    InstrumentEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
)
from agent_trading.domain.enums import (
    Environment,
    OrderSide,
    OrderType,
    TimeInForce,
)
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.decision_orchestrator import (
    AIDecisionInputs,
    AssembledContext,
    DecisionOrchestratorService,
    ScoreResult,
    StubScoreCalculator,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service() -> DecisionOrchestratorService:
    repos = build_in_memory_repositories()
    return DecisionOrchestratorService(repos=repos)


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

    return DecisionOrchestratorService(repos=repos)


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
    # Generated fields
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

        ctx = AssembledContext(
            decision_context=decision_context,
            config_version=config_version,
            recent_events=(event,),
            score=score,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
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
            repos=repos, score_calculator=CustomCalculator()
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

        service = DecisionOrchestratorService(repos=repos)
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

        service = DecisionOrchestratorService(repos=repos)
        intent = await service.assemble(sample_request, decision_context_id=ctx_id)

        # The matching snapshot (same instrument_id as the resolved instrument)
        # should be picked via the fallback path.
        assert intent.context.position_snapshot is not None
        assert intent.context.position_snapshot.position_snapshot_id == matching_snapshot.position_snapshot_id
        assert intent.context.position_snapshot.instrument_id == instrument.instrument_id
        assert intent.context.position_snapshot.quantity == Decimal("100")
