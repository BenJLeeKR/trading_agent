"""Tests for the three stub AI agents and the real EventInterpretationAgent.

Each agent is tested for:
* Protocol conformance (``ProviderAIAgent``).
* Default output values match the aligned schema (``08_ai_decision_policy.md``
  §4.2).
* ``run()`` succeeds with a valid ``AgentExecutionRequest``.
* Safe fallback on exception (the stub agents themselves don't raise,
  but the fallback path is verified).

The real ``EventInterpretationAgent`` is tested with a mock provider to
verify successful parsing and safe fallback behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.services.ai_agents.ai_risk import (
    AIRiskAgent,
    StubAIRiskAgent,
    _ALLOWED_RISK_OPINIONS,
)
from agent_trading.services.ai_agents.base import (
    AIProviderClient,
    AgentExecutionRequest,
    ProviderAIAgent,
    RawProviderResponse,
)
from agent_trading.services.ai_agents.event_interpretation import (
    EventInterpretationAgent,
    StubEventInterpretationAgent,
)
from agent_trading.services.ai_agents.final_decision_composer import (
    FinalDecisionComposerAgent,
    StubFinalDecisionComposerAgent,
)
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.decision_orchestrator import (
    AssembledContext,
    ScoreResult,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        decision_context_id=uuid4(),
        correlation_id="test-corr-1",
        context=AssembledContext(),
    )


@pytest.fixture
def mock_provider() -> AIProviderClient:
    """Return an ``AIProviderClient`` that returns a valid response."""
    client = AsyncMock(spec=AIProviderClient)

    async def _generate(**kwargs: object) -> RawProviderResponse:
        return RawProviderResponse(
            parsed=EventInterpretationOutput(
                symbol="AAPL",
                issuer_code="037730",
                events=(),
                aggregate_view=EventInterpretationOutput.__dataclass_fields__[
                    "aggregate_view"
                ].default_factory(),
            ),
            raw_content='{"symbol": "AAPL", "issuer_code": "037730"}',
        )

    client.generate_structured = _generate  # type: ignore[method-assign]
    return client


# ---------------------------------------------------------------------------
# StubEventInterpretationAgent
# ---------------------------------------------------------------------------


class TestStubEventInterpretationAgent:
    """StubEventInterpretationAgent protocol conformance and output."""

    def test_protocol_conformance(self) -> None:
        """Agent satisfies the ProviderAIAgent protocol."""
        agent = StubEventInterpretationAgent()
        assert isinstance(agent, ProviderAIAgent)

    def test_agent_name(self) -> None:
        """agent_name is 'event_interpretation'."""
        agent = StubEventInterpretationAgent()
        assert agent.agent_name == "event_interpretation"

    def test_schema_version_default(self) -> None:
        """schema_version defaults to 'v1'."""
        agent = StubEventInterpretationAgent()
        assert agent.schema_version == "v1"

    def test_schema_version_custom(self) -> None:
        """schema_version can be set via constructor."""
        agent = StubEventInterpretationAgent(schema_version="v2")
        assert agent.schema_version == "v2"

    @pytest.mark.asyncio
    async def test_run_returns_event_interpretation_output(
        self, sample_request: AgentExecutionRequest
    ) -> None:
        """run() returns an EventInterpretationOutput."""
        agent = StubEventInterpretationAgent()
        result = await agent.run(sample_request)
        assert isinstance(result, EventInterpretationOutput)

    @pytest.mark.asyncio
    async def test_default_output_values(
        self, sample_request: AgentExecutionRequest
    ) -> None:
        """Default output matches the aligned schema (empty events, neutral)."""
        agent = StubEventInterpretationAgent()
        result = await agent.run(sample_request)
        # Schema metadata
        assert result.schema_version == "v1"
        assert result.agent_name == "event_interpretation"
        assert result.decision_context_id is None
        # Symbol / issuer
        assert result.symbol == ""
        assert result.issuer_code == ""
        # Events
        assert result.events == ()
        # Aggregate view
        assert result.aggregate_view.overall_bias == "neutral"
        assert result.aggregate_view.event_conflict is False
        assert result.aggregate_view.top_reason_codes == ()
        assert result.aggregate_view.opposing_evidence == ()

    @pytest.mark.asyncio
    async def test_run_succeeds_with_none_context_id(
        self,
    ) -> None:
        """run() succeeds when decision_context_id is None."""
        agent = StubEventInterpretationAgent()
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test-corr-2",
            context=AssembledContext(),
        )
        result = await agent.run(request)
        assert isinstance(result, EventInterpretationOutput)
        assert result.decision_context_id is None


# ---------------------------------------------------------------------------
# StubAIRiskAgent
# ---------------------------------------------------------------------------


class TestStubAIRiskAgent:
    """StubAIRiskAgent protocol conformance and output."""

    def test_protocol_conformance(self) -> None:
        """Agent satisfies the ProviderAIAgent protocol."""
        agent = StubAIRiskAgent()
        assert isinstance(agent, ProviderAIAgent)

    def test_agent_name(self) -> None:
        """agent_name is 'ai_risk'."""
        agent = StubAIRiskAgent()
        assert agent.agent_name == "ai_risk"

    def test_schema_version_default(self) -> None:
        """schema_version defaults to 'v1'."""
        agent = StubAIRiskAgent()
        assert agent.schema_version == "v1"

    @pytest.mark.asyncio
    async def test_run_returns_ai_risk_output(
        self, sample_request: AgentExecutionRequest
    ) -> None:
        """run() returns an AIRiskOutput."""
        agent = StubAIRiskAgent()
        result = await agent.run(sample_request)
        assert isinstance(result, AIRiskOutput)

    @pytest.mark.asyncio
    async def test_default_output_values(
        self, sample_request: AgentExecutionRequest
    ) -> None:
        """Default output matches the aligned schema (allow, zero risk)."""
        agent = StubAIRiskAgent()
        result = await agent.run(sample_request)
        # Schema metadata
        assert result.schema_version == "v1"
        assert result.agent_name == "ai_risk"
        assert result.decision_context_id is None
        # Symbol / side
        assert result.symbol == ""
        assert result.proposed_side == ""
        # Risk opinion
        assert result.risk_opinion == "allow"
        assert result.risk_score == 0.0
        assert result.confidence == 0.0
        assert result.size_adjustment_factor == 0.0
        assert result.max_holding_horizon == "swing"
        # Lists
        assert result.risk_flags == ()
        assert result.reason_codes == ()
        assert result.opposing_evidence == ()
        # Summary
        assert result.summary == ""

    @pytest.mark.asyncio
    async def test_run_succeeds_with_none_context_id(self) -> None:
        """run() succeeds when decision_context_id is None."""
        agent = StubAIRiskAgent()
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test-corr-3",
            context=AssembledContext(),
        )
        result = await agent.run(request)
        assert isinstance(result, AIRiskOutput)
        assert result.decision_context_id is None


# ---------------------------------------------------------------------------
# AIRiskAgent (real) — with mock provider
# ---------------------------------------------------------------------------


class TestAIRiskAgent:
    """Real AIRiskAgent with mock provider."""

    def test_protocol_conformance(self, mock_provider: AIProviderClient) -> None:
        """Agent satisfies the ProviderAIAgent protocol."""
        agent = AIRiskAgent(provider_client=mock_provider)
        assert isinstance(agent, ProviderAIAgent)

    def test_agent_name(self, mock_provider: AIProviderClient) -> None:
        """agent_name is 'ai_risk'."""
        agent = AIRiskAgent(provider_client=mock_provider)
        assert agent.agent_name == "ai_risk"

    def test_schema_version_default(self, mock_provider: AIProviderClient) -> None:
        """schema_version defaults to 'v1'."""
        agent = AIRiskAgent(provider_client=mock_provider)
        assert agent.schema_version == "v1"

    def test_schema_version_custom(self, mock_provider: AIProviderClient) -> None:
        """schema_version can be set via constructor."""
        agent = AIRiskAgent(
            provider_client=mock_provider,
            schema_version="v2",
        )
        assert agent.schema_version == "v2"

    @pytest.mark.asyncio
    async def test_run_returns_ai_risk_output(
        self,
        mock_provider: AIProviderClient,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Real agent with successful provider call returns valid output."""
        agent = AIRiskAgent(provider_client=mock_provider)
        result = await agent.run(sample_request)
        assert isinstance(result, AIRiskOutput)
        # The mock returns EventInterpretationOutput as parsed, but AIRiskAgent
        # expects AIRiskOutput shape — verify safe fallback kicks in
        # when provider returns wrong type
        assert result.risk_opinion == "allow"  # default fallback value

    @pytest.mark.asyncio
    async def test_run_with_ai_risk_mock_response(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Provider returns valid AIRiskOutput shape."""
        risk_provider = AsyncMock(spec=AIProviderClient)

        async def _generate(**kwargs: object) -> RawProviderResponse:
            return RawProviderResponse(
                parsed=AIRiskOutput(
                    symbol="005930",
                    proposed_side="buy",
                    risk_opinion="reduce",
                    risk_score=0.65,
                    confidence=0.7,
                    size_adjustment_factor=0.3,
                    max_holding_horizon="short",
                    risk_flags=("high_volatility",),
                    reason_codes=("R001", "R002"),
                    opposing_evidence=("Recent price gap",),
                    summary="Moderate risk due to high volatility.",
                ),
                raw_content='{"symbol": "005930", "risk_opinion": "reduce"}',
            )

        risk_provider.generate_structured = _generate  # type: ignore[method-assign]

        agent = AIRiskAgent(provider_client=risk_provider)
        result = await agent.run(sample_request)
        assert isinstance(result, AIRiskOutput)
        # Provider response fields should be preserved
        assert result.symbol == "005930"
        assert result.proposed_side == "buy"
        assert result.risk_opinion == "reduce"
        assert result.risk_score == 0.65
        assert result.confidence == 0.7
        assert result.size_adjustment_factor == 0.3
        assert result.max_holding_horizon == "short"
        assert result.risk_flags == ("high_volatility",)
        assert result.reason_codes == ("R001", "R002")
        assert result.opposing_evidence == ("Recent price gap",)
        assert result.summary == "Moderate risk due to high volatility."
        # Metadata fields overridden by agent
        assert result.agent_name == "ai_risk"
        assert result.schema_version == "v1"

    @pytest.mark.asyncio
    async def test_run_fallback_on_provider_error(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Provider error → default AIRiskOutput."""
        failing_provider = AsyncMock(spec=AIProviderClient)

        async def _raise(**kwargs: object) -> object:
            raise RuntimeError("Provider unavailable")

        failing_provider.generate_structured = _raise  # type: ignore[method-assign]

        agent = AIRiskAgent(provider_client=failing_provider)
        result = await agent.run(sample_request)
        assert isinstance(result, AIRiskOutput)
        # Default values
        assert result.risk_opinion == "allow"
        assert result.risk_score == 0.0

    @pytest.mark.asyncio
    async def test_run_fallback_on_parse_error(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Invalid response from provider → default output."""
        bad_provider = AsyncMock(spec=AIProviderClient)

        async def _bad_generate(**kwargs: object) -> RawProviderResponse:
            raise ValueError("Invalid JSON")

        bad_provider.generate_structured = _bad_generate  # type: ignore[method-assign]

        agent = AIRiskAgent(provider_client=bad_provider)
        result = await agent.run(sample_request)
        assert isinstance(result, AIRiskOutput)
        assert result.risk_opinion == "allow"

    @pytest.mark.asyncio
    async def test_decision_context_id_set_when_provided(
        self,
        mock_provider: AIProviderClient,
    ) -> None:
        """decision_context_id is set from the request when provided."""
        ctx_id = uuid4()
        request = AgentExecutionRequest(
            decision_context_id=ctx_id,
            correlation_id="test-ctx-ar",
            context=AssembledContext(),
        )
        agent = AIRiskAgent(provider_client=mock_provider)
        result = await agent.run(request)
        # Mock returns EventInterpretationOutput which has decision_context_id=None,
        # but AIRiskAgent overrides it from request
        assert result.decision_context_id == str(ctx_id)

    @pytest.mark.asyncio
    async def test_decision_context_id_none_when_not_provided(
        self,
        mock_provider: AIProviderClient,
    ) -> None:
        """decision_context_id is None when request has no context."""
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test-noctx-ar",
            context=AssembledContext(),
        )
        agent = AIRiskAgent(provider_client=mock_provider)
        result = await agent.run(request)
        assert result.decision_context_id is None


    @pytest.mark.asyncio
    async def test_run_with_ei_output_in_prompt(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """EI output in request adds EI context to the user prompt."""
        from unittest.mock import AsyncMock

        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            InterpretedEvent,
        )

        provider = AsyncMock(spec=AIProviderClient)
        captured_kwargs: dict[str, object] = {}

        async def _generate(**kwargs: object) -> RawProviderResponse:
            captured_kwargs.update(kwargs)
            return RawProviderResponse(
                parsed=AIRiskOutput(
                    symbol="TEST",
                    proposed_side="buy",
                    risk_opinion="allow",
                ),
                raw_content='{"symbol": "TEST"}',
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        # Create a request with EI output
        ei_output = EventInterpretationOutput(
            symbol="AAPL",
            aggregate_view=AggregateEventView(
                overall_bias="positive",
                event_conflict=True,
                top_reason_codes=("R01", "R02"),
            ),
            events=(
                InterpretedEvent(
                    event_type="earnings",
                    summary="Strong earnings beat",
                    impact_direction="positive",
                    confidence=0.9,
                ),
            ),
        )

        request = AgentExecutionRequest(
            decision_context_id=sample_request.decision_context_id,
            correlation_id=sample_request.correlation_id,
            context=sample_request.context,
            event_interpretation_output=ei_output,
        )

        agent = AIRiskAgent(provider_client=provider)
        await agent.run(request)

        user_prompt = str(captured_kwargs.get("user_prompt", ""))
        # Verify EI content is included in the prompt
        assert "Event Interpretation" in user_prompt
        assert "positive" in user_prompt  # overall_bias
        assert "Strong earnings beat" in user_prompt  # event summary
        assert "R01" in user_prompt  # top_reason_codes

    @pytest.mark.asyncio
    async def test_run_without_ei_output(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Without EI output, the prompt does not contain EI sections."""
        from unittest.mock import AsyncMock

        provider = AsyncMock(spec=AIProviderClient)
        captured_kwargs: dict[str, object] = {}

        async def _generate(**kwargs: object) -> RawProviderResponse:
            captured_kwargs.update(kwargs)
            return RawProviderResponse(
                parsed=AIRiskOutput(
                    symbol="TEST",
                    proposed_side="buy",
                    risk_opinion="allow",
                ),
                raw_content='{"symbol": "TEST"}',
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        # Use the sample request as-is (no EI output)
        agent = AIRiskAgent(provider_client=provider)
        await agent.run(sample_request)

        user_prompt = str(captured_kwargs.get("user_prompt", ""))
        # Verify EI content is NOT in the prompt
        assert "Event Interpretation" not in user_prompt

    @pytest.mark.asyncio
    async def test_run_with_position_cash_risk_in_prompt(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Position, cash, and risk limit snapshots in context add sections to the prompt."""
        from datetime import datetime, timezone
        from decimal import Decimal
        from unittest.mock import AsyncMock
        from uuid import uuid4

        from agent_trading.domain.entities import (
            CashBalanceSnapshotEntity,
            PositionSnapshotEntity,
            RiskLimitSnapshotEntity,
        )
        from agent_trading.services.decision_orchestrator import AssembledContext

        provider = AsyncMock(spec=AIProviderClient)
        captured_kwargs: dict[str, object] = {}

        async def _generate(**kwargs: object) -> RawProviderResponse:
            captured_kwargs.update(kwargs)
            return RawProviderResponse(
                parsed=AIRiskOutput(
                    symbol="TEST",
                    proposed_side="buy",
                    risk_opinion="allow",
                ),
                raw_content='{"symbol": "TEST"}',
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        now = datetime.now(timezone.utc)
        pos = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            quantity=Decimal("50"),
            average_price=Decimal("100.00"),
            market_price=Decimal("105.00"),
            unrealized_pnl=Decimal("250.00"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        cash = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=uuid4(),
            currency="KRW",
            available_cash=Decimal("5000000"),
            settled_cash=Decimal("3000000"),
            unsettled_cash=Decimal("2000000"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        rl = RiskLimitSnapshotEntity(
            risk_limit_snapshot_id=uuid4(),
            account_id=uuid4(),
            snapshot_at=now,
            kill_switch_active=False,
            drawdown_state="normal",
            daily_loss_used_pct=Decimal("15.0"),
            max_daily_loss_limit_pct=Decimal("20.0"),
            gross_exposure_pct=Decimal("45.0"),
        )

        context = AssembledContext(
            position_snapshot=pos,
            cash_balance_snapshot=cash,
            risk_limit_snapshot=rl,
        )
        request = AgentExecutionRequest(
            decision_context_id=sample_request.decision_context_id,
            correlation_id=sample_request.correlation_id,
            context=context,
        )

        agent = AIRiskAgent(provider_client=provider)
        await agent.run(request)

        user_prompt = str(captured_kwargs.get("user_prompt", ""))
        # Verify position section
        assert "Current Position" in user_prompt
        assert "Quantity: 50" in user_prompt
        assert "Average price: 100.00" in user_prompt
        assert "Market price: 105.00" in user_prompt
        assert "Unrealised P&L: 250.00" in user_prompt
        # Verify cash section
        assert "Cash Balance" in user_prompt
        assert "Available cash: 5000000" in user_prompt
        assert "Settled cash: 3000000" in user_prompt
        # Verify risk limit section
        assert "Risk Limit State" in user_prompt
        assert "Kill switch active: False" in user_prompt
        assert "Drawdown state: normal" in user_prompt
        assert "Daily loss: 15.0% / 20.0% limit" in user_prompt
        assert "Gross exposure: 45.0%" in user_prompt

    @pytest.mark.asyncio
    async def test_run_without_position_cash_risk(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Without position/cash/risk_limit snapshots, prompt does not contain those sections."""
        from unittest.mock import AsyncMock

        provider = AsyncMock(spec=AIProviderClient)
        captured_kwargs: dict[str, object] = {}

        async def _generate(**kwargs: object) -> RawProviderResponse:
            captured_kwargs.update(kwargs)
            return RawProviderResponse(
                parsed=AIRiskOutput(
                    symbol="TEST",
                    proposed_side="buy",
                    risk_opinion="allow",
                ),
                raw_content='{"symbol": "TEST"}',
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        # Use sample request with empty AssembledContext (no snapshots)
        agent = AIRiskAgent(provider_client=provider)
        await agent.run(sample_request)

        user_prompt = str(captured_kwargs.get("user_prompt", ""))
        # Verify new snapshot sections are NOT present
        assert "Current Position" not in user_prompt
        assert "Cash Balance" not in user_prompt
        assert "Risk Limit State" not in user_prompt

    # ------------------------------------------------------------------
    # risk_opinion canonical validation tests (B안 post-parse normalization)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_risk_opinion_drift_detected(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Korean prose risk_opinion → 'allow' fallback + warning log."""
        from unittest.mock import AsyncMock

        provider = AsyncMock(spec=AIProviderClient)
        captured_kwargs: dict[str, object] = {}

        async def _generate(**kwargs: object) -> RawProviderResponse:
            captured_kwargs.update(kwargs)
            return RawProviderResponse(
                parsed=AIRiskOutput(
                    symbol="TEST",
                    proposed_side="buy",
                    risk_opinion="기술적 돌파 신호가 있으나 신뢰도가 낮음",
                ),
                raw_content='{"symbol": "TEST"}',
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        agent = AIRiskAgent(provider_client=provider)
        result = await agent.run(sample_request)

        assert result.risk_opinion == "allow", (
            f"Expected 'allow' fallback, got {result.risk_opinion!r}"
        )

    @pytest.mark.asyncio
    async def test_risk_opinion_canonical_allow(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """risk_opinion='allow' → pass-through (no fallback)."""
        from unittest.mock import AsyncMock

        provider = AsyncMock(spec=AIProviderClient)

        async def _generate(**kwargs: object) -> RawProviderResponse:
            return RawProviderResponse(
                parsed=AIRiskOutput(
                    symbol="TEST",
                    proposed_side="buy",
                    risk_opinion="allow",
                ),
                raw_content='{"symbol": "TEST"}',
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        agent = AIRiskAgent(provider_client=provider)
        result = await agent.run(sample_request)

        assert result.risk_opinion == "allow"

    @pytest.mark.asyncio
    async def test_risk_opinion_canonical_reduce(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """risk_opinion='reduce' → pass-through (no fallback)."""
        from unittest.mock import AsyncMock

        provider = AsyncMock(spec=AIProviderClient)

        async def _generate(**kwargs: object) -> RawProviderResponse:
            return RawProviderResponse(
                parsed=AIRiskOutput(
                    symbol="TEST",
                    proposed_side="buy",
                    risk_opinion="reduce",
                ),
                raw_content='{"symbol": "TEST"}',
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        agent = AIRiskAgent(provider_client=provider)
        result = await agent.run(sample_request)

        assert result.risk_opinion == "reduce"

    @pytest.mark.asyncio
    async def test_risk_opinion_canonical_reject(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """risk_opinion='reject' → pass-through (no fallback)."""
        from unittest.mock import AsyncMock

        provider = AsyncMock(spec=AIProviderClient)

        async def _generate(**kwargs: object) -> RawProviderResponse:
            return RawProviderResponse(
                parsed=AIRiskOutput(
                    symbol="TEST",
                    proposed_side="buy",
                    risk_opinion="reject",
                ),
                raw_content='{"symbol": "TEST"}',
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        agent = AIRiskAgent(provider_client=provider)
        result = await agent.run(sample_request)

        assert result.risk_opinion == "reject"

    @pytest.mark.asyncio
    async def test_risk_opinion_canonical_review(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """risk_opinion='review' → pass-through (no fallback)."""
        from unittest.mock import AsyncMock

        provider = AsyncMock(spec=AIProviderClient)

        async def _generate(**kwargs: object) -> RawProviderResponse:
            return RawProviderResponse(
                parsed=AIRiskOutput(
                    symbol="TEST",
                    proposed_side="buy",
                    risk_opinion="review",
                ),
                raw_content='{"symbol": "TEST"}',
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        agent = AIRiskAgent(provider_client=provider)
        result = await agent.run(sample_request)

        assert result.risk_opinion == "review"

    @pytest.mark.asyncio
    async def test_risk_opinion_uppercase_passthrough(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """'ALLOW' → strip().lower()='allow' (in canonical set) → pass-through (no fallback)."""
        from unittest.mock import AsyncMock

        provider = AsyncMock(spec=AIProviderClient)

        async def _generate(**kwargs: object) -> RawProviderResponse:
            return RawProviderResponse(
                parsed=AIRiskOutput(
                    symbol="TEST",
                    proposed_side="buy",
                    risk_opinion="ALLOW",
                ),
                raw_content='{"symbol": "TEST"}',
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        agent = AIRiskAgent(provider_client=provider)
        result = await agent.run(sample_request)

        # strip().lower() 후 canonical set에 포함되므로 pass-through, 원본 유지
        assert result.risk_opinion == "ALLOW"

    @pytest.mark.asyncio
    async def test_risk_opinion_empty_fallback(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Empty risk_opinion → 'allow' fallback."""
        from unittest.mock import AsyncMock

        provider = AsyncMock(spec=AIProviderClient)

        async def _generate(**kwargs: object) -> RawProviderResponse:
            return RawProviderResponse(
                parsed=AIRiskOutput(
                    symbol="TEST",
                    proposed_side="buy",
                    risk_opinion="",
                ),
                raw_content='{"symbol": "TEST"}',
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        agent = AIRiskAgent(provider_client=provider)
        result = await agent.run(sample_request)

        assert result.risk_opinion == "allow"

    def test_risk_opinion_system_prompt_contains_allowed_values(
        self,
        mock_provider: AIProviderClient,
    ) -> None:
        """System prompt lists all 4 canonical risk_opinion values."""
        agent = AIRiskAgent(provider_client=mock_provider)
        # Access the private method for test verification
        prompt = agent._build_system_prompt()  # type: ignore[no-untyped-call]

        for value in ("allow", "reduce", "reject", "review"):
            assert value in prompt, (
                f"Canonical value {value!r} not found in system prompt"
            )

    def test_allowed_risk_opinions_constant(self) -> None:
        """_ALLOWED_RISK_OPINIONS contains exactly 4 canonical values."""
        assert _ALLOWED_RISK_OPINIONS == frozenset(
            {"allow", "reduce", "reject", "review"}
        ), f"Unexpected values: {_ALLOWED_RISK_OPINIONS}"


# ---------------------------------------------------------------------------
# StubFinalDecisionComposerAgent
# ---------------------------------------------------------------------------


class TestStubFinalDecisionComposerAgent:
    """StubFinalDecisionComposerAgent protocol conformance and output."""

    def test_protocol_conformance(self) -> None:
        """Agent satisfies the ProviderAIAgent protocol."""
        agent = StubFinalDecisionComposerAgent()
        assert isinstance(agent, ProviderAIAgent)

    def test_agent_name(self) -> None:
        """agent_name is 'final_decision_composer'."""
        agent = StubFinalDecisionComposerAgent()
        assert agent.agent_name == "final_decision_composer"

    def test_schema_version_default(self) -> None:
        """schema_version defaults to 'v1'."""
        agent = StubFinalDecisionComposerAgent()
        assert agent.schema_version == "v1"

    @pytest.mark.asyncio
    async def test_run_returns_final_decision_composer_output(
        self, sample_request: AgentExecutionRequest
    ) -> None:
        """run() returns a FinalDecisionComposerOutput."""
        agent = StubFinalDecisionComposerAgent()
        result = await agent.run(sample_request)
        assert isinstance(result, FinalDecisionComposerOutput)

    @pytest.mark.asyncio
    async def test_default_output_values(
        self, sample_request: AgentExecutionRequest
    ) -> None:
        """Default output matches the aligned schema (HOLD, empty)."""
        agent = StubFinalDecisionComposerAgent()
        result = await agent.run(sample_request)
        # Schema metadata
        assert result.schema_version == "v1"
        assert result.agent_name == "final_decision_composer"
        assert result.decision_context_id is None
        # Symbol
        assert result.symbol == ""
        # Decision
        assert result.decision_type == "HOLD"
        assert result.side == ""
        assert result.entry_style == ""
        assert result.time_horizon == "swing"
        assert result.confidence == 0.0
        assert result.conviction == 0.0
        # Lists
        assert result.reason_codes == ()
        assert result.opposing_evidence == ()
        # Nested: execution_preferences
        assert result.execution_preferences.use_limit_order is True
        assert result.execution_preferences.price_band_hint.reference_type == "last_price"
        assert result.execution_preferences.price_band_hint.max_slippage_bps == 15
        assert result.execution_preferences.allow_partial_fill is True
        # Nested: sizing_hint
        assert result.sizing_hint.size_mode == "no_change"
        assert result.sizing_hint.size_adjustment_factor == 0.0
        # Nested: exit_plan_hint
        assert result.exit_plan_hint.stop_style == "volatility_based"
        assert result.exit_plan_hint.take_profit_style == "partial_scale_out"
        assert result.exit_plan_hint.max_holding_days == 20
        # Summary
        assert result.summary == ""

    @pytest.mark.asyncio
    async def test_run_succeeds_with_none_context_id(self) -> None:
        """run() succeeds when decision_context_id is None."""
        agent = StubFinalDecisionComposerAgent()
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test-corr-4",
            context=AssembledContext(),
        )
        result = await agent.run(request)
        assert isinstance(result, FinalDecisionComposerOutput)
        assert result.decision_context_id is None


# ---------------------------------------------------------------------------
# FinalDecisionComposerAgent (real) — with mock provider
# ---------------------------------------------------------------------------


class TestFinalDecisionComposerAgent:
    """Real FinalDecisionComposerAgent with mock provider."""

    def test_protocol_conformance(self, mock_provider: AIProviderClient) -> None:
        """Agent satisfies the ProviderAIAgent protocol."""
        agent = FinalDecisionComposerAgent(provider_client=mock_provider)
        assert isinstance(agent, ProviderAIAgent)

    def test_agent_name(self, mock_provider: AIProviderClient) -> None:
        """agent_name is 'final_decision_composer'."""
        agent = FinalDecisionComposerAgent(provider_client=mock_provider)
        assert agent.agent_name == "final_decision_composer"

    def test_schema_version_default(self, mock_provider: AIProviderClient) -> None:
        """schema_version defaults to 'v1'."""
        agent = FinalDecisionComposerAgent(provider_client=mock_provider)
        assert agent.schema_version == "v1"

    def test_schema_version_custom(self, mock_provider: AIProviderClient) -> None:
        """schema_version can be set via constructor."""
        agent = FinalDecisionComposerAgent(
            provider_client=mock_provider,
            schema_version="v2",
        )
        assert agent.schema_version == "v2"

    @pytest.mark.asyncio
    async def test_run_returns_final_decision_composer_output(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Real agent with successful provider call returns valid output."""
        from unittest.mock import AsyncMock

        provider = AsyncMock(spec=AIProviderClient)

        async def _generate(**kwargs: object) -> RawProviderResponse:
            parsed = FinalDecisionComposerOutput(
                symbol="AAPL",
                decision_type="APPROVE",
                agent_name="final_decision_composer",
                schema_version="v1",
                decision_context_id=str(sample_request.decision_context_id) if sample_request.decision_context_id else None,
            )
            return RawProviderResponse(parsed=parsed, raw_content="{}")

        provider.generate_structured = _generate  # type: ignore[method-assign]

        agent = FinalDecisionComposerAgent(provider_client=provider)  # type: ignore[arg-type]
        result = await agent.run(sample_request)
        assert isinstance(result, FinalDecisionComposerOutput)
        # Provider response fields should be preserved
        assert result.symbol == "AAPL"
        assert result.decision_type == "APPROVE"

    @pytest.mark.asyncio
    async def test_run_with_mock_response(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Provider returns valid FinalDecisionComposerOutput shape."""
        provider = AsyncMock(spec=AIProviderClient)

        async def _generate(**kwargs: object) -> RawProviderResponse:
            from agent_trading.services.ai_agents.schemas import (
                ExecutionPreferences,
                ExitPlanHint,
                SizingHint,
            )

            parsed = FinalDecisionComposerOutput(
                schema_version="v1",
                agent_name="final_decision_composer",
                decision_context_id=str(sample_request.decision_context_id) if sample_request.decision_context_id else None,
                symbol="AAPL",
                decision_type="APPROVE",
                side="BUY",
                entry_style="LIMIT",
                time_horizon="swing",
                confidence=0.85,
                conviction=0.75,
                reason_codes=("strong_momentum", "high_volume"),
                opposing_evidence=("overbought_rsi",),
                execution_preferences=ExecutionPreferences(),
                sizing_hint=SizingHint(),
                exit_plan_hint=ExitPlanHint(),
                summary="Strong buy signal across all indicators.",
            )
            return RawProviderResponse(parsed=parsed, raw_content="{}")

        provider.generate_structured = _generate  # type: ignore[method-assign]

        agent = FinalDecisionComposerAgent(provider_client=provider)
        result = await agent.run(sample_request)

        assert isinstance(result, FinalDecisionComposerOutput)
        assert result.symbol == "AAPL"
        assert result.decision_type == "APPROVE"
        assert result.side == "BUY"
        assert result.entry_style == "LIMIT"
        assert result.confidence == 0.85
        assert result.conviction == 0.75
        assert "strong_momentum" in result.reason_codes
        assert "overbought_rsi" in result.opposing_evidence
        assert "Strong buy" in result.summary

    @pytest.mark.asyncio
    async def test_run_fallback_on_provider_error(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Provider error → default FinalDecisionComposerOutput (HOLD)."""
        failing_provider = AsyncMock(spec=AIProviderClient)

        async def _raise(**kwargs: object) -> object:
            raise RuntimeError("Provider unavailable")

        failing_provider.generate_structured = _raise  # type: ignore[method-assign]

        agent = FinalDecisionComposerAgent(provider_client=failing_provider)
        result = await agent.run(sample_request)
        assert isinstance(result, FinalDecisionComposerOutput)
        # Default values — most conservative (HOLD)
        assert result.decision_type == "HOLD"
        assert result.symbol == ""
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_run_fallback_on_parse_error(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Invalid response from provider → default output."""
        bad_provider = AsyncMock(spec=AIProviderClient)

        async def _bad_generate(**kwargs: object) -> RawProviderResponse:
            raise ValueError("Invalid JSON")

        bad_provider.generate_structured = _bad_generate  # type: ignore[method-assign]

        agent = FinalDecisionComposerAgent(provider_client=bad_provider)
        result = await agent.run(sample_request)
        assert isinstance(result, FinalDecisionComposerOutput)
        assert result.decision_type == "HOLD"
        assert result.symbol == ""

    @pytest.mark.asyncio
    async def test_decision_context_id_set_when_provided(
        self,
        mock_provider: AIProviderClient,
    ) -> None:
        """decision_context_id is set from the request when provided."""
        ctx_id = uuid4()
        request = AgentExecutionRequest(
            decision_context_id=ctx_id,
            correlation_id="test-ctx",
            context=AssembledContext(),
        )
        agent = FinalDecisionComposerAgent(provider_client=mock_provider)
        result = await agent.run(request)
        assert result.decision_context_id == str(ctx_id)

    @pytest.mark.asyncio
    async def test_decision_context_id_none_when_not_provided(
        self,
        mock_provider: AIProviderClient,
    ) -> None:
        """decision_context_id is None when request has no context."""
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test-noctx",
            context=AssembledContext(),
        )
        agent = FinalDecisionComposerAgent(provider_client=mock_provider)
        result = await agent.run(request)
        assert result.decision_context_id is None

    @pytest.mark.asyncio
    async def test_run_with_ei_and_ar_output_in_prompt(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """EI and AR outputs in request add EI/AR context to the user prompt."""
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            InterpretedEvent,
        )

        provider = AsyncMock(spec=AIProviderClient)

        # Track the user_prompt passed to generate_structured
        captured: dict[str, object] = {}

        async def _generate(**kwargs: object) -> RawProviderResponse:
            captured["user_prompt"] = kwargs.get("user_prompt", "")
            parsed = FinalDecisionComposerOutput()
            return RawProviderResponse(parsed=parsed, raw_content="{}")

        provider.generate_structured = _generate  # type: ignore[method-assign]

        # Build a request with both EI and AR output
        ei_output = EventInterpretationOutput(
            symbol="AAPL",
            issuer_code="037730",
            aggregate_view=AggregateEventView(
                overall_bias="bullish",
                event_conflict="low",
                top_reason_codes=("earnings_beat", "positive_guidance"),
            ),
            events=(
                InterpretedEvent(
                    event_type="earnings",
                    summary="Q2 earnings beat estimates — Strong revenue growth",
                    impact_direction="positive",
                    confidence=0.85,
                ),
            ),
        )
        ar_output = AIRiskOutput(
            symbol="AAPL",
            risk_opinion="cautious",
            risk_score=0.35,
            confidence=0.75,
            size_adjustment_factor=0.8,
            reason_codes=("moderate_volatility",),
            opposing_evidence=("sector_headwinds",),
        )
        request_with_ei_and_ar = AgentExecutionRequest(
            decision_context_id=sample_request.decision_context_id,
            correlation_id=sample_request.correlation_id,
            context=sample_request.context,
            event_interpretation_output=ei_output,
            ai_risk_output=ar_output,
        )

        agent = FinalDecisionComposerAgent(provider_client=provider)
        await agent.run(request_with_ei_and_ar)

        prompt = captured.get("user_prompt", "")
        assert isinstance(prompt, str)
        # EI output sections should be present
        assert "=== Event Interpretation Output ===" in prompt
        assert "bullish" in prompt
        assert "earnings_beat" in prompt
        assert "Q2 earnings" in prompt
        # AR output sections should be present
        assert "=== AI Risk Output ===" in prompt
        assert "cautious" in prompt
        assert "0.35" in prompt
        assert "0.8" in prompt
        assert "moderate_volatility" in prompt
        assert "sector_headwinds" in prompt

    @pytest.mark.asyncio
    async def test_run_without_ei_and_ar_output(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Without EI and AR outputs, the prompt does not contain EI/AR sections."""
        provider = AsyncMock(spec=AIProviderClient)

        captured: dict[str, object] = {}

        async def _generate(**kwargs: object) -> RawProviderResponse:
            captured["user_prompt"] = kwargs.get("user_prompt", "")
            parsed = FinalDecisionComposerOutput()
            return RawProviderResponse(parsed=parsed, raw_content="{}")

        provider.generate_structured = _generate  # type: ignore[method-assign]

        # No EI/AR output in the request
        agent = FinalDecisionComposerAgent(provider_client=provider)
        await agent.run(sample_request)

        prompt = captured.get("user_prompt", "")
        assert isinstance(prompt, str)
        # EI/AR sections should NOT be present
        assert "=== Event Interpretation Output ===" not in prompt
        assert "=== AI Risk Output ===" not in prompt


# ---------------------------------------------------------------------------
# EventInterpretationAgent (real) — with mock provider
# ---------------------------------------------------------------------------


class TestEventInterpretationAgent:
    """Real EventInterpretationAgent with mock provider."""

    def test_protocol_conformance(self, mock_provider: AIProviderClient) -> None:
        """Agent satisfies the ProviderAIAgent protocol."""
        agent = EventInterpretationAgent(provider_client=mock_provider)
        assert isinstance(agent, ProviderAIAgent)

    def test_agent_name(self, mock_provider: AIProviderClient) -> None:
        """agent_name is 'event_interpretation'."""
        agent = EventInterpretationAgent(provider_client=mock_provider)
        assert agent.agent_name == "event_interpretation"

    def test_schema_version_default(self, mock_provider: AIProviderClient) -> None:
        """schema_version defaults to 'v1'."""
        agent = EventInterpretationAgent(provider_client=mock_provider)
        assert agent.schema_version == "v1"

    def test_schema_version_custom(self, mock_provider: AIProviderClient) -> None:
        """schema_version can be set via constructor."""
        agent = EventInterpretationAgent(
            provider_client=mock_provider,
            schema_version="v2",
        )
        assert agent.schema_version == "v2"

    @pytest.mark.asyncio
    async def test_run_returns_event_interpretation_output(
        self,
        mock_provider: AIProviderClient,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Real agent with successful provider call returns valid output."""
        agent = EventInterpretationAgent(provider_client=mock_provider)
        result = await agent.run(sample_request)
        assert isinstance(result, EventInterpretationOutput)
        # Provider response fields should be preserved
        assert result.symbol == "AAPL"
        assert result.issuer_code == "037730"

    @pytest.mark.asyncio
    async def test_run_fallback_on_provider_error(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Provider error → default EventInterpretationOutput."""
        failing_provider = AsyncMock(spec=AIProviderClient)

        async def _raise(**kwargs: object) -> object:
            raise RuntimeError("Provider unavailable")

        failing_provider.generate_structured = _raise  # type: ignore[method-assign]

        agent = EventInterpretationAgent(provider_client=failing_provider)
        result = await agent.run(sample_request)
        assert isinstance(result, EventInterpretationOutput)
        # Default values
        assert result.symbol == ""
        assert result.issuer_code == ""

    @pytest.mark.asyncio
    async def test_run_fallback_on_parse_error(
        self,
        sample_request: AgentExecutionRequest,
    ) -> None:
        """Invalid response from provider → default output."""
        bad_provider = AsyncMock(spec=AIProviderClient)

        async def _bad_generate(**kwargs: object) -> RawProviderResponse:
            # Return a response that will fail dataclass construction
            raise ValueError("Invalid JSON")

        bad_provider.generate_structured = _bad_generate  # type: ignore[method-assign]

        agent = EventInterpretationAgent(provider_client=bad_provider)
        result = await agent.run(sample_request)
        assert isinstance(result, EventInterpretationOutput)
        assert result.symbol == ""

    @pytest.mark.asyncio
    async def test_decision_context_id_set_when_provided(
        self,
        mock_provider: AIProviderClient,
    ) -> None:
        """decision_context_id is set from the request when provided."""
        ctx_id = uuid4()
        request = AgentExecutionRequest(
            decision_context_id=ctx_id,
            correlation_id="test-ctx",
            context=AssembledContext(),
        )
        agent = EventInterpretationAgent(provider_client=mock_provider)
        result = await agent.run(request)
        assert result.decision_context_id == str(ctx_id)

    @pytest.mark.asyncio
    async def test_decision_context_id_none_when_not_provided(
        self,
        mock_provider: AIProviderClient,
    ) -> None:
        """decision_context_id is None when request has no context."""
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test-noctx",
            context=AssembledContext(),
        )
        agent = EventInterpretationAgent(provider_client=mock_provider)
        result = await agent.run(request)
        assert result.decision_context_id is None


# ---------------------------------------------------------------------------
# P1-A: Provenance prompt format tests
# ---------------------------------------------------------------------------


class TestEventInterpretationAgentPrompt:
    """Tests for ``_build_user_prompt()`` provenance format.

    These tests verify that provenance tags, stale flags, and
    non-default-only rules are correctly applied.
    """

    @staticmethod
    def _make_event(
        *,
        source_name: str = "opendart",
        source_reliability_tier: str = "T1",
        event_type: str = "disclosure",
        published_at: datetime | None = None,
        issuer_code: str | None = "005930",
        severity: str = "medium",
        direction: str = "neutral",
        ingested_at: datetime | None = None,
        headline: str = "test headline",
        body_summary: str | None = None,
    ) -> ExternalEventEntity:
        """Helper to build an ``ExternalEventEntity`` with defaults."""
        now = datetime.now(timezone.utc)
        return ExternalEventEntity(
            event_id=uuid4(),
            event_type=event_type,
            source_name=source_name,
            published_at=published_at or now,
            source_reliability_tier=source_reliability_tier,
            issuer_code=issuer_code,
            symbol=None,
            ingested_at=ingested_at or now,
            severity=severity,
            direction=direction,
            headline=headline,
            body_summary=body_summary,
        )

    def _build_prompt(
        self,
        events: list[ExternalEventEntity],
        score: ScoreResult | None = None,
    ) -> str:
        """Call ``_build_user_prompt()`` and return the result string."""
        agent = EventInterpretationAgent(provider_client=AsyncMock())
        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test-provenance",
            context=AssembledContext(
                recent_events=tuple(events),
                score=score or ScoreResult(),
            ),
        )
        return agent._build_user_prompt(request)

    # ------------------------------------------------------------------
    # Test 1: All tags present when all fields exist
    # ------------------------------------------------------------------

    def test_all_tags_present(self) -> None:
        """All provenance tags appear when every field is populated."""
        now = datetime.now(timezone.utc)
        event = self._make_event(
            source_name="opendart",
            source_reliability_tier="T1",
            event_type="disclosure",
            published_at=now,
            issuer_code="005930",
            severity="high",          # non-default → tag appears
            direction="positive",     # non-default → tag appears
            ingested_at=now,          # fresh → no stale mark
        )
        prompt = self._build_prompt([event])

        assert "[src:opendart]" in prompt
        assert "[tier:T1]" in prompt
        assert "[disclosure]" in prompt
        # published_at date in YYYY-MM-DD format
        date_str = now.strftime("%Y-%m-%d")
        assert f"[{date_str}]" in prompt
        assert "[issuer:005930]" in prompt
        assert "[severity:high]" in prompt
        assert "[positive]" in prompt
        # ⚠️STALE must NOT appear (fresh event)
        assert "⚠️STALE" not in prompt

    # ------------------------------------------------------------------
    # Test 2: severity=medium → [severity:...] NOT present
    # ------------------------------------------------------------------

    def test_severity_medium_omitted(self) -> None:
        """Default severity ``medium`` does NOT produce a ``[severity:...]`` tag."""
        event = self._make_event(severity="medium")
        prompt = self._build_prompt([event])
        assert "[severity:medium]" not in prompt
        assert "[severity:" not in prompt

    # ------------------------------------------------------------------
    # Test 3: direction=neutral → [positive]/[negative] NOT present
    # ------------------------------------------------------------------

    def test_direction_neutral_omitted(self) -> None:
        """Default direction ``neutral`` does NOT produce ``[positive]`` or ``[negative]``."""
        event = self._make_event(direction="neutral")
        prompt = self._build_prompt([event])
        assert "[positive]" not in prompt
        assert "[negative]" not in prompt

    # ------------------------------------------------------------------
    # Test 4: ingested_at < 24h → ⚠️STALE NOT present
    # ------------------------------------------------------------------

    def test_fresh_event_no_stale(self) -> None:
        """Event ingested less than 24h ago does NOT get the stale mark."""
        now = datetime.now(timezone.utc)
        event = self._make_event(ingested_at=now)
        prompt = self._build_prompt([event])
        assert "⚠️STALE" not in prompt

    # ------------------------------------------------------------------
    # Test 5: issuer_code=None → [issuer:...] NOT present
    # ------------------------------------------------------------------

    def test_no_issuer_code_omitted(self) -> None:
        """When ``issuer_code`` is ``None``, the ``[issuer:...]`` tag is absent."""
        event = self._make_event(issuer_code=None)
        prompt = self._build_prompt([event])
        assert "[issuer:" not in prompt

    # ------------------------------------------------------------------
    # Test 6: ingested_at > 24h → ⚠️STALE IS present
    # ------------------------------------------------------------------

    def test_stale_event_shows_stale_mark(self) -> None:
        """Event ingested more than 24h ago DOES get the stale mark."""
        now = datetime.now(timezone.utc)
        stale_time = now - timedelta(hours=25)
        event = self._make_event(ingested_at=stale_time)
        prompt = self._build_prompt([event])
        assert "⚠️STALE" in prompt


# ---------------------------------------------------------------------------
# TestAIRiskAgentPrompt — AR _build_user_prompt() provenance format
# ---------------------------------------------------------------------------


class TestAIRiskAgentPrompt:
    """Tests for ``AIRiskAgent._build_user_prompt()`` provenance format.

    These tests verify that provenance tags, stale flags, and
    non-default-only rules are correctly applied in the AR events section,
    and that the Symbol line does not leak ``DecisionContextEntity.__repr__()``.
    """

    @staticmethod
    def _make_event(
        *,
        source_name: str = "opendart",
        source_reliability_tier: str = "T1",
        event_type: str = "disclosure",
        published_at: datetime | None = None,
        issuer_code: str | None = "005930",
        severity: str = "medium",
        direction: str = "neutral",
        ingested_at: datetime | None = None,
        headline: str = "test headline",
        body_summary: str | None = None,
        symbol: str | None = "030200",
    ) -> ExternalEventEntity:
        """Helper to build an ``ExternalEventEntity`` with defaults."""
        now = datetime.now(timezone.utc)
        return ExternalEventEntity(
            event_id=uuid4(),
            event_type=event_type,
            source_name=source_name,
            published_at=published_at or now,
            source_reliability_tier=source_reliability_tier,
            issuer_code=issuer_code,
            symbol=symbol,
            ingested_at=ingested_at or now,
            severity=severity,
            direction=direction,
            headline=headline,
            body_summary=body_summary,
        )

    def _build_prompt(
        self,
        events: list[ExternalEventEntity],
        score: ScoreResult | None = None,
    ) -> str:
        """Call ``AIRiskAgent._build_user_prompt()`` and return the result string."""
        agent = AIRiskAgent(provider_client=AsyncMock())
        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test-ar-provenance",
            context=AssembledContext(
                recent_events=tuple(events),
                score=score or ScoreResult(),
            ),
        )
        return agent._build_user_prompt(request)

    # ------------------------------------------------------------------
    # Test 1: All provenance tags present
    # ------------------------------------------------------------------

    def test_ar_events_all_tags_present(self) -> None:
        """All provenance tags appear when every field is populated."""
        now = datetime.now(timezone.utc)
        event = self._make_event(
            source_name="opendart",
            source_reliability_tier="T1",
            event_type="disclosure",
            published_at=now,
            issuer_code="005930",
            severity="high",
            direction="positive",
            ingested_at=now,
        )
        prompt = self._build_prompt([event])
        assert "[src:opendart]" in prompt
        assert "[tier:T1]" in prompt
        assert "[disclosure]" in prompt
        date_str = now.strftime("%Y-%m-%d")
        assert f"[{date_str}]" in prompt
        assert "[issuer:005930]" in prompt
        assert "[severity:high]" in prompt
        assert "[positive]" in prompt
        assert "⚠️STALE" not in prompt

    # ------------------------------------------------------------------
    # Test 2: severity=medium → [severity:...] NOT present
    # ------------------------------------------------------------------

    def test_ar_events_severity_medium_omitted(self) -> None:
        """Default severity ``medium`` does NOT produce a ``[severity:...]`` tag."""
        event = self._make_event(severity="medium")
        prompt = self._build_prompt([event])
        assert "[severity:medium]" not in prompt
        assert "[severity:" not in prompt

    # ------------------------------------------------------------------
    # Test 3: direction=neutral → [positive]/[negative] NOT present
    # ------------------------------------------------------------------

    def test_ar_events_direction_neutral_omitted(self) -> None:
        """Default direction ``neutral`` does NOT produce ``[positive]`` or ``[negative]``."""
        event = self._make_event(direction="neutral")
        prompt = self._build_prompt([event])
        assert "[positive]" not in prompt
        assert "[negative]" not in prompt

    # ------------------------------------------------------------------
    # Test 4: ingested_at < 24h → ⚠️STALE NOT present
    # ------------------------------------------------------------------

    def test_ar_events_fresh_no_stale(self) -> None:
        """Freshly ingested event does NOT get the stale mark."""
        now = datetime.now(timezone.utc)
        event = self._make_event(ingested_at=now)
        prompt = self._build_prompt([event])
        assert "⚠️STALE" not in prompt

    # ------------------------------------------------------------------
    # Test 5: issuer_code=None → [issuer:...] NOT present
    # ------------------------------------------------------------------

    def test_ar_events_no_issuer_tag_when_none(self) -> None:
        """When ``issuer_code`` is ``None``, no ``[issuer:...]`` tag appears."""
        event = self._make_event(issuer_code=None)
        prompt = self._build_prompt([event])
        assert "[issuer:" not in prompt

    # ------------------------------------------------------------------
    # Test 6: ingested_at > 24h → ⚠️STALE IS present
    # ------------------------------------------------------------------

    def test_ar_events_stale_mark_when_old(self) -> None:
        """Event ingested more than 24h ago DOES get the stale mark."""
        now = datetime.now(timezone.utc)
        stale_time = now - timedelta(hours=25)
        event = self._make_event(ingested_at=stale_time)
        prompt = self._build_prompt([event])
        assert "⚠️STALE" in prompt

    # ------------------------------------------------------------------
    # Test 7: Symbol line — no DecisionContextEntity.__repr__() leak
    # ------------------------------------------------------------------

    def test_ar_symbol_line_no_repr_leak(self) -> None:
        """Symbol line shows the event symbol, not a ``DecisionContextEntity`` repr."""
        event = self._make_event(symbol="030200")
        prompt = self._build_prompt([event])
        # Must contain the actual symbol
        assert "Symbol: 030200" in prompt
        # Must NOT contain DecisionContextEntity repr patterns
        assert "DecisionContextEntity" not in prompt
        assert "decision_context" not in prompt

    # ------------------------------------------------------------------
    # Test 8: Symbol line — fallback when events list is empty
    # ------------------------------------------------------------------

    def test_ar_symbol_line_fallback_when_no_events(self) -> None:
        """When no events are provided, Symbol falls back to ``(not available)``."""
        prompt = self._build_prompt([])
        assert "Symbol: (not available)" in prompt

    # ------------------------------------------------------------------
    # Test 9: Symbol line — fallback when all event symbols are None
    # ------------------------------------------------------------------

    def test_ar_symbol_line_fallback_when_symbol_none(self) -> None:
        """When all events have ``symbol=None``, Symbol falls back to ``(not available)``."""
        event = self._make_event(symbol=None)
        prompt = self._build_prompt([event])
        assert "Symbol: (not available)" in prompt

    # ------------------------------------------------------------------
    # Test 10: Combined — provenance tags + Symbol line in same prompt
    # ------------------------------------------------------------------

    def test_ar_combined_provenance_and_symbol(self) -> None:
        """Provenance tags and Symbol line coexist correctly in the same prompt."""
        now = datetime.now(timezone.utc)
        event = self._make_event(
            source_name="opendart",
            source_reliability_tier="T1",
            event_type="disclosure",
            published_at=now,
            issuer_code="005930",
            severity="high",
            direction="positive",
            ingested_at=now,
            symbol="030200",
        )
        prompt = self._build_prompt([event])
        # Provenance tags present
        assert "[src:opendart]" in prompt
        assert "[tier:T1]" in prompt
        assert "[issuer:005930]" in prompt
        assert "[severity:high]" in prompt
        assert "[positive]" in prompt
        # Symbol line correct
        assert "Symbol: 030200" in prompt
        # No stale mark
        assert "⚠️STALE" not in prompt


# ---------------------------------------------------------------------------
# TestFinalDecisionComposerAgentPrompt — FDC _build_user_prompt() provenance
# ---------------------------------------------------------------------------


class TestFinalDecisionComposerAgentPrompt:
    """Tests for ``FinalDecisionComposerAgent._build_user_prompt()`` provenance format.

    These tests verify that provenance tags, stale flags, and
    non-default-only rules are correctly applied in the FDC events section.
    """

    @staticmethod
    def _make_event(
        *,
        source_name: str = "opendart",
        source_reliability_tier: str = "T1",
        event_type: str = "disclosure",
        published_at: datetime | None = None,
        issuer_code: str | None = "005930",
        severity: str = "medium",
        direction: str = "neutral",
        ingested_at: datetime | None = None,
        headline: str = "test headline",
        body_summary: str | None = None,
        symbol: str | None = "030200",
    ) -> ExternalEventEntity:
        """Helper to build an ``ExternalEventEntity`` with defaults."""
        now = datetime.now(timezone.utc)
        return ExternalEventEntity(
            event_id=uuid4(),
            event_type=event_type,
            source_name=source_name,
            published_at=published_at or now,
            source_reliability_tier=source_reliability_tier,
            issuer_code=issuer_code,
            symbol=symbol,
            ingested_at=ingested_at or now,
            severity=severity,
            direction=direction,
            headline=headline,
            body_summary=body_summary,
        )

    def _build_prompt(
        self,
        events: list[ExternalEventEntity],
        score: ScoreResult | None = None,
    ) -> str:
        """Call ``FinalDecisionComposerAgent._build_user_prompt()`` and return the result string."""
        agent = FinalDecisionComposerAgent(provider_client=AsyncMock())
        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test-fdc-provenance",
            context=AssembledContext(
                recent_events=tuple(events),
                score=score or ScoreResult(),
            ),
        )
        return agent._build_user_prompt(request)

    # ------------------------------------------------------------------
    # Test 1: All provenance tags present
    # ------------------------------------------------------------------

    def test_fdc_events_all_tags_present(self) -> None:
        """All provenance tags appear when every field is populated."""
        now = datetime.now(timezone.utc)
        event = self._make_event(
            source_name="opendart",
            source_reliability_tier="T1",
            event_type="disclosure",
            published_at=now,
            issuer_code="005930",
            severity="high",
            direction="positive",
            ingested_at=now,
        )
        prompt = self._build_prompt([event])
        assert "[src:opendart]" in prompt
        assert "[tier:T1]" in prompt
        assert "[disclosure]" in prompt
        date_str = now.strftime("%Y-%m-%d")
        assert f"[{date_str}]" in prompt
        assert "[issuer:005930]" in prompt
        assert "[severity:high]" in prompt
        assert "[positive]" in prompt
        assert "⚠️STALE" not in prompt

    # ------------------------------------------------------------------
    # Test 2: severity=medium → [severity:...] NOT present
    # ------------------------------------------------------------------

    def test_fdc_events_severity_medium_omitted(self) -> None:
        """Default severity ``medium`` does NOT produce a ``[severity:...]`` tag."""
        event = self._make_event(severity="medium")
        prompt = self._build_prompt([event])
        assert "[severity:medium]" not in prompt
        assert "[severity:" not in prompt

    # ------------------------------------------------------------------
    # Test 3: direction=neutral → [positive]/[negative] NOT present
    # ------------------------------------------------------------------

    def test_fdc_events_direction_neutral_omitted(self) -> None:
        """Default direction ``neutral`` does NOT produce ``[positive]`` or ``[negative]``."""
        event = self._make_event(direction="neutral")
        prompt = self._build_prompt([event])
        assert "[positive]" not in prompt
        assert "[negative]" not in prompt

    # ------------------------------------------------------------------
    # Test 4: ingested_at < 24h → ⚠️STALE NOT present
    # ------------------------------------------------------------------

    def test_fdc_events_fresh_no_stale(self) -> None:
        """Freshly ingested event does NOT get the stale mark."""
        now = datetime.now(timezone.utc)
        event = self._make_event(ingested_at=now)
        prompt = self._build_prompt([event])
        assert "⚠️STALE" not in prompt

    # ------------------------------------------------------------------
    # Test 5: issuer_code=None → [issuer:...] NOT present
    # ------------------------------------------------------------------

    def test_fdc_events_no_issuer_tag_when_none(self) -> None:
        """When ``issuer_code`` is ``None``, no ``[issuer:...]`` tag appears."""
        event = self._make_event(issuer_code=None)
        prompt = self._build_prompt([event])
        assert "[issuer:" not in prompt

    # ------------------------------------------------------------------
    # Test 6: ingested_at > 24h → ⚠️STALE IS present
    # ------------------------------------------------------------------

    def test_fdc_events_stale_mark_when_old(self) -> None:
        """Event ingested more than 24h ago DOES get the stale mark."""
        now = datetime.now(timezone.utc)
        stale_time = now - timedelta(hours=25)
        event = self._make_event(ingested_at=stale_time)
        prompt = self._build_prompt([event])
        assert "⚠️STALE" in prompt

    # ------------------------------------------------------------------
    # Test 7: events have symbol → "Symbol: 030200" in prompt
    # ------------------------------------------------------------------

    def test_fdc_symbol_line_from_events(self) -> None:
        """When events carry a symbol, the prompt includes ``Symbol: 030200``."""
        event = self._make_event(symbol="030200")
        prompt = self._build_prompt([event])
        assert "Symbol: 030200" in prompt

    # ------------------------------------------------------------------
    # Test 8: no events / no symbol → "Symbol: (not available)"
    # ------------------------------------------------------------------

    def test_fdc_symbol_line_fallback_when_no_symbol(self) -> None:
        """When no events have a symbol, the prompt shows ``Symbol: (not available)``."""
        event = self._make_event(symbol=None)
        prompt = self._build_prompt([event])
        assert "Symbol: (not available)" in prompt

    def test_fdc_symbol_line_fallback_when_no_events(self) -> None:
        """When there are no events at all, the prompt shows ``Symbol: (not available)``."""
        prompt = self._build_prompt([])
        assert "Symbol: (not available)" in prompt
