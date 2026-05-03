"""Tests for AI Agent wiring inside ``DecisionOrchestratorService``.

Verifies that:
* Agents are called during ``assemble()`` when injected.
* Custom agents can be injected and are called.
* Agent failure does not break ``assemble()`` (safe fallback).
* Recorder stores agent runs after ``assemble()``.
* Existing ``assemble()`` behaviour is preserved.
* Schema alignment: ``structured_output_json`` contains ``agent_name`` and
  ``decision_context_id`` consistent with the ``AgentRunEntity`` metadata.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    ConfigVersionEntity,
    DecisionContextEntity,
)
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.ai_agents.ai_risk import AIRiskAgent
from agent_trading.services.ai_agents.final_decision_composer import (
    FinalDecisionComposerAgent,
)
from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    AIProviderClient,
    ProviderAIAgent,
    RawProviderResponse,
)
from agent_trading.services.ai_agents.event_interpretation import (
    EventInterpretationAgent,
)
from agent_trading.services.ai_agents.recorder import AgentRunRecorder
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.decision_orchestrator import (
    AssembledContext,
    DecisionOrchestratorService,
    OrderIntent,
    ScoreResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_request() -> SubmitOrderRequest:
    return SubmitOrderRequest(
        client_order_id="client-1",
        correlation_id="",
        account_ref="test-account",
        symbol="005930",
        market="KRX",
        side="buy",
        order_type="limit",
        time_in_force="day",
        quantity=10,
        price=50000.0,
        decision_id="",
        strategy_id=None,
        idempotency_key="idem-1",
    )


@pytest.fixture
def repos() -> RepositoryContainer:
    """Return an empty in-memory repository container."""
    from agent_trading.repositories.memory import (
        InMemoryAccountRepository,
        InMemoryBrokerAccountRepository,
        InMemoryCashBalanceSnapshotRepository,
        InMemoryClientRepository,
        InMemoryConfigVersionRepository,
        InMemoryDecisionContextRepository,
        InMemoryExternalEventRepository,
        InMemoryFillEventRepository,
        InMemoryGuardrailEvaluationRepository,
        InMemoryInstrumentRepository,
        InMemoryOrderRepository,
        InMemoryOrderStateEventRepository,
        InMemoryPositionSnapshotRepository,
        InMemoryReconciliationRepository,
        InMemoryRiskLimitSnapshotRepository,
        InMemoryStrategyRepository,
        InMemoryTradeDecisionRepository,
        InMemoryUnitOfWork,
        InMemoryBrokerOrderRepository,
        InMemoryAuditLogRepository,
    )

    return RepositoryContainer(
        unit_of_work=InMemoryUnitOfWork(),
        clients=InMemoryClientRepository(),
        accounts=InMemoryAccountRepository(),
        strategies=InMemoryStrategyRepository(),
        config_versions=InMemoryConfigVersionRepository(),
        instruments=InMemoryInstrumentRepository(),
        decision_contexts=InMemoryDecisionContextRepository(),
        position_snapshots=InMemoryPositionSnapshotRepository(),
        cash_balance_snapshots=InMemoryCashBalanceSnapshotRepository(),
        trade_decisions=InMemoryTradeDecisionRepository(),
        orders=InMemoryOrderRepository(),
        broker_orders=InMemoryBrokerOrderRepository(),
        fill_events=InMemoryFillEventRepository(),
        reconciliations=InMemoryReconciliationRepository(),
        audit_logs=InMemoryAuditLogRepository(),
        broker_accounts=InMemoryBrokerAccountRepository(),
        order_state_events=InMemoryOrderStateEventRepository(),
        guardrail_evaluations=InMemoryGuardrailEvaluationRepository(),
        risk_limit_snapshots=InMemoryRiskLimitSnapshotRepository(),
        external_events=InMemoryExternalEventRepository(),
    )


@pytest.fixture
def service(repos: RepositoryContainer) -> DecisionOrchestratorService:
    return DecisionOrchestratorService(repos)


@pytest.fixture
def mock_ei_provider() -> AIProviderClient:
    """Return an ``AIProviderClient`` that returns a valid EI response."""
    import json
    from dataclasses import asdict

    from agent_trading.services.ai_agents.schemas import AggregateEventView, InterpretedEvent

    output = EventInterpretationOutput(
        symbol="AAPL",
        issuer_code="037730",
        events=(),
        aggregate_view=AggregateEventView(),
    )

    async def _generate(**kwargs: object) -> RawProviderResponse:
        return RawProviderResponse(
            raw_content=json.dumps(asdict(output)),
            parsed=output,
        )

    ei_mock = MagicMock(spec=AIProviderClient)
    ei_mock.generate_structured = AsyncMock(side_effect=_generate)
    return ei_mock


@pytest.fixture
def mock_ar_provider() -> AIProviderClient:
    """Return an ``AIProviderClient`` that returns a valid AR response."""
    import json
    from dataclasses import asdict

    output = AIRiskOutput(
        symbol="AAPL",
        agent_name="ai_risk",
        schema_version="v1",
        decision_context_id=None,
        risk_opinion="reduce",
        risk_score=0.65,
        confidence=0.8,
        size_adjustment_factor=0.5,
        max_holding_horizon="swing",
        risk_flags=("concentration",),
        reason_codes=("high_correlation",),
        opposing_evidence=(),
        summary="Reduce position due to concentration risk",
    )

    async def _generate(**kwargs: object) -> RawProviderResponse:
        return RawProviderResponse(
            raw_content=json.dumps(asdict(output)),
            parsed=output,
        )

    ar_mock = MagicMock(spec=AIProviderClient)
    ar_mock.generate_structured = AsyncMock(side_effect=_generate)
    return ar_mock


@pytest.fixture
def mock_fdc_provider() -> AIProviderClient:
    """Return an ``AIProviderClient`` that returns a valid FDC response."""
    import json
    from dataclasses import asdict

    output = FinalDecisionComposerOutput(
        schema_version="v1",
        agent_name="final_decision_composer",
        decision_context_id=None,
        symbol="AAPL",
        decision_type="BUY",
        confidence=0.75,
        summary="Strong momentum with manageable risk",
    )

    async def _generate(**kwargs: object) -> RawProviderResponse:
        return RawProviderResponse(
            raw_content=json.dumps(asdict(output)),
            parsed=output,
        )

    fdc_mock = MagicMock(spec=AIProviderClient)
    fdc_mock.generate_structured = AsyncMock(side_effect=_generate)
    return fdc_mock


# ---------------------------------------------------------------------------
# Agent injection and execution
# ---------------------------------------------------------------------------


class TestAgentInjection:
    """Custom agents are called during assemble()."""

    @pytest.mark.asyncio
    async def test_default_agents_used_when_none_injected(
        self, service: DecisionOrchestratorService, sample_request: SubmitOrderRequest
    ) -> None:
        """Default stub agents are used when no custom agents are injected."""
        intent = await service.assemble(sample_request)
        assert isinstance(intent, OrderIntent)

        # Recorder should have 3 runs (one per agent)
        runs = service._agent_recorder.list_all()
        assert len(runs) == 3
        agent_types = {r.agent_type for r in runs}
        assert agent_types == {
            "event_interpretation",
            "ai_risk",
            "final_decision_composer",
        }

    @pytest.mark.asyncio
    async def test_custom_agents_injected(
        self, repos: RepositoryContainer, sample_request: SubmitOrderRequest
    ) -> None:
        """Custom agents are called during assemble()."""
        # Create mock agents
        mock_ei = MagicMock(spec=ProviderAIAgent)
        mock_ei.agent_name = "event_interpretation"
        mock_ei.run = AsyncMock(return_value=EventInterpretationOutput())

        mock_ar = MagicMock(spec=ProviderAIAgent)
        mock_ar.agent_name = "ai_risk"
        mock_ar.run = AsyncMock(return_value=AIRiskOutput())

        mock_fdc = MagicMock(spec=ProviderAIAgent)
        mock_fdc.agent_name = "final_decision_composer"
        mock_fdc.run = AsyncMock(return_value=FinalDecisionComposerOutput())

        recorder = AgentRunRecorder()

        orchestrator = DecisionOrchestratorService(
            repos,
            event_interpretation_agent=mock_ei,
            ai_risk_agent=mock_ar,
            final_decision_agent=mock_fdc,
            agent_recorder=recorder,
        )

        intent = await orchestrator.assemble(sample_request)
        assert isinstance(intent, OrderIntent)

        # Each mock agent should have been called once
        assert mock_ei.run.call_count == 1
        assert mock_ar.run.call_count == 1
        assert mock_fdc.run.call_count == 1

        # Recorder should have 3 runs
        assert len(recorder.list_all()) == 3

    @pytest.mark.asyncio
    async def test_agents_called_in_correct_order(
        self, repos: RepositoryContainer, sample_request: SubmitOrderRequest
    ) -> None:
        """Agents are called in order: EI → AR → FDC."""
        call_order: list[str] = []

        class TrackingEI:
            agent_name = "event_interpretation"
            schema_version = "v1"
            async def run(self, request: AgentExecutionRequest) -> EventInterpretationOutput:
                call_order.append("event_interpretation")
                return EventInterpretationOutput()

        class TrackingAR:
            agent_name = "ai_risk"
            schema_version = "v1"
            async def run(self, request: AgentExecutionRequest) -> AIRiskOutput:
                call_order.append("ai_risk")
                return AIRiskOutput()

        class TrackingFDC:
            agent_name = "final_decision_composer"
            schema_version = "v1"
            async def run(self, request: AgentExecutionRequest) -> FinalDecisionComposerOutput:
                call_order.append("final_decision_composer")
                return FinalDecisionComposerOutput()

        orchestrator = DecisionOrchestratorService(
            repos,
            event_interpretation_agent=TrackingEI(),
            ai_risk_agent=TrackingAR(),
            final_decision_agent=TrackingFDC(),
        )

        await orchestrator.assemble(sample_request)
        assert call_order == [
            "event_interpretation",
            "ai_risk",
            "final_decision_composer",
        ]


# ---------------------------------------------------------------------------
# Safe fallback on agent failure
# ---------------------------------------------------------------------------


class TestAgentSafeFallback:
    """Agent failure does not break assemble()."""

    @pytest.mark.asyncio
    async def test_agent_failure_returns_default_output(
        self, repos: RepositoryContainer, sample_request: SubmitOrderRequest
    ) -> None:
        """When an agent raises, assemble() still succeeds with default output."""

        class FailingAgent:
            agent_name = "failing_agent"
            schema_version = "v1"
            async def run(self, request: AgentExecutionRequest) -> object:
                msg = "Simulated agent failure"
                raise RuntimeError(msg)

        orchestrator = DecisionOrchestratorService(
            repos,
            event_interpretation_agent=FailingAgent(),  # type: ignore[arg-type]
        )

        intent = await orchestrator.assemble(sample_request)
        assert isinstance(intent, OrderIntent)

        # Recorder should still have 3 runs (failing agent recorded with default output)
        runs = orchestrator._agent_recorder.list_all()
        assert len(runs) == 3

    @pytest.mark.asyncio
    async def test_all_agents_fail_assemble_still_succeeds(
        self, repos: RepositoryContainer, sample_request: SubmitOrderRequest
    ) -> None:
        """Even if all three agents fail, assemble() succeeds."""

        class FailingAgent:
            agent_name = "failing"
            schema_version = "v1"
            async def run(self, request: AgentExecutionRequest) -> object:
                msg = "Simulated failure"
                raise RuntimeError(msg)

        orchestrator = DecisionOrchestratorService(
            repos,
            event_interpretation_agent=FailingAgent(),  # type: ignore[arg-type]
            ai_risk_agent=FailingAgent(),  # type: ignore[arg-type]
            final_decision_agent=FailingAgent(),  # type: ignore[arg-type]
        )

        intent = await orchestrator.assemble(sample_request)
        assert isinstance(intent, OrderIntent)


# ---------------------------------------------------------------------------
# Schema alignment consistency
# ---------------------------------------------------------------------------


class TestSchemaAlignment:
    """structured_output_json is consistent with AgentRunEntity metadata."""

    @pytest.mark.asyncio
    async def test_structured_output_contains_agent_name(
        self, service: DecisionOrchestratorService, sample_request: SubmitOrderRequest
    ) -> None:
        """Each run's structured_output_json contains agent_name matching agent_type."""
        await service.assemble(sample_request)
        for run in service._agent_recorder.list_all():
            assert run.structured_output_json is not None
            stored_name = run.structured_output_json.get("agent_name")
            assert stored_name == run.agent_type, (
                f"agent_name mismatch: output={stored_name!r} != entity={run.agent_type!r}"
            )

    @pytest.mark.asyncio
    async def test_structured_output_decision_context_id_null_when_not_provided(
        self, service: DecisionOrchestratorService, sample_request: SubmitOrderRequest
    ) -> None:
        """When no decision_context_id is provided, payload is null (entity may have synthetic UUID)."""
        await service.assemble(sample_request)
        for run in service._agent_recorder.list_all():
            assert run.structured_output_json is not None
            stored_ctx = run.structured_output_json.get("decision_context_id")
            assert stored_ctx is None, (
                f"Expected null decision_context_id in payload when not provided, "
                f"got {stored_ctx!r} (entity has synthetic UUID={run.decision_context_id})"
            )

    @pytest.mark.asyncio
    async def test_structured_output_decision_context_id_matches_when_provided(
        self, service: DecisionOrchestratorService, sample_request: SubmitOrderRequest
    ) -> None:
        """When decision_context_id is provided, payload matches the explicit ID."""
        ctx_id = uuid4()
        await service.assemble(sample_request, decision_context_id=ctx_id)
        for run in service._agent_recorder.list_all():
            assert run.structured_output_json is not None
            stored_ctx = run.structured_output_json.get("decision_context_id")
            assert stored_ctx == str(ctx_id), (
                f"decision_context_id mismatch: output={stored_ctx!r} != expected={str(ctx_id)!r}"
            )
            # Entity should also use the same explicit ID (no synthetic fallback)
            assert run.decision_context_id == ctx_id, (
                f"Entity decision_context_id mismatch: "
                f"{run.decision_context_id} != {ctx_id}"
            )

    @pytest.mark.asyncio
    async def test_structured_output_schema_version_v1(
        self, service: DecisionOrchestratorService, sample_request: SubmitOrderRequest
    ) -> None:
        """Each run's structured_output_json has schema_version 'v1'."""
        await service.assemble(sample_request)
        for run in service._agent_recorder.list_all():
            assert run.structured_output_json is not None
            assert run.structured_output_json.get("schema_version") == "v1"


# ---------------------------------------------------------------------------
# Real EI + Real AR + Stub FDC integration
# ---------------------------------------------------------------------------


class TestRealAgentsIntegration:
    """Real EventInterpretationAgent + real AIRiskAgent + stub composer."""

    @pytest.mark.asyncio
    async def test_real_ei_and_real_ar_with_stub_fdc(
        self,
        repos: RepositoryContainer,
        sample_request: SubmitOrderRequest,
        mock_ei_provider: AIProviderClient,
        mock_ar_provider: AIProviderClient,
    ) -> None:
        """Real EI + real AR + stub FDC: assemble() succeeds, recorder has 3 runs."""
        ei_agent = EventInterpretationAgent(provider_client=mock_ei_provider)
        ar_agent = AIRiskAgent(provider_client=mock_ar_provider)
        recorder = AgentRunRecorder()

        orchestrator = DecisionOrchestratorService(
            repos,
            event_interpretation_agent=ei_agent,
            ai_risk_agent=ar_agent,
            agent_recorder=recorder,
        )

        intent = await orchestrator.assemble(sample_request)
        assert isinstance(intent, OrderIntent)

        # Recorder should have 3 runs
        runs = recorder.list_all()
        assert len(runs) == 3

        # Agent types should include real EI and real AR
        agent_types = {r.agent_type for r in runs}
        assert agent_types == {
            "event_interpretation",
            "ai_risk",
            "final_decision_composer",
        }

        # EI run should have structured_output_json with symbol from mock
        ei_run = next(r for r in runs if r.agent_type == "event_interpretation")
        assert ei_run.structured_output_json is not None
        assert ei_run.structured_output_json.get("symbol") == "AAPL"
        assert ei_run.structured_output_json.get("agent_name") == "event_interpretation"

        # AR run should have structured_output_json with risk_opinion from mock
        ar_run = next(r for r in runs if r.agent_type == "ai_risk")
        assert ar_run.structured_output_json is not None
        assert ar_run.structured_output_json.get("risk_opinion") == "reduce"
        assert ar_run.structured_output_json.get("risk_score") == 0.65
        assert ar_run.structured_output_json.get("agent_name") == "ai_risk"

        # FDC run should be stub (default values)
        fdc_run = next(r for r in runs if r.agent_type == "final_decision_composer")
        assert fdc_run.structured_output_json is not None
        assert fdc_run.structured_output_json.get("decision_type") == "HOLD"

    @pytest.mark.asyncio
    async def test_real_ei_real_ar_records_decision_context_id(
        self,
        repos: RepositoryContainer,
        sample_request: SubmitOrderRequest,
        mock_ei_provider: AIProviderClient,
        mock_ar_provider: AIProviderClient,
    ) -> None:
        """Decision context ID is recorded in both real agent runs."""
        ctx_id = uuid4()
        ei_agent = EventInterpretationAgent(provider_client=mock_ei_provider)
        ar_agent = AIRiskAgent(provider_client=mock_ar_provider)
        recorder = AgentRunRecorder()

        orchestrator = DecisionOrchestratorService(
            repos,
            event_interpretation_agent=ei_agent,
            ai_risk_agent=ar_agent,
            agent_recorder=recorder,
        )

        await orchestrator.assemble(sample_request, decision_context_id=ctx_id)

        runs = recorder.list_all()
        # Both real agent runs should have decision_context_id
        for run in runs:
            assert run.decision_context_id == ctx_id
            assert run.structured_output_json is not None
            stored_ctx = run.structured_output_json.get("decision_context_id")
            assert stored_ctx == str(ctx_id)


    @pytest.mark.asyncio
    async def test_ei_output_passed_to_ar(
        self,
        repos: RepositoryContainer,
        sample_request: SubmitOrderRequest,
        mock_ei_provider: AIProviderClient,
        mock_ar_provider: AIProviderClient,
    ) -> None:
        """EI output is passed through to the AR agent via request_with_ei."""
        from agent_trading.services.ai_agents.schemas import EventInterpretationOutput

        ei_agent = EventInterpretationAgent(provider_client=mock_ei_provider)

        # Tracking AR agent that captures the request
        class TrackingARAgent:
            last_request: AgentExecutionRequest | None = None

            @property
            def agent_name(self) -> str:
                return "ai_risk"

            @property
            def schema_version(self) -> str:
                return "v1"

            async def run(self, request: AgentExecutionRequest) -> AIRiskOutput:
                self.last_request = request
                return AIRiskOutput()

        ar_agent = TrackingARAgent()
        recorder = AgentRunRecorder()

        orchestrator = DecisionOrchestratorService(
            repos,
            event_interpretation_agent=ei_agent,
            ai_risk_agent=ar_agent,  # type: ignore[arg-type]
            agent_recorder=recorder,
        )

        await orchestrator.assemble(sample_request)

        # The AR agent should have received a request with event_interpretation_output
        assert ar_agent.last_request is not None
        ei_output = ar_agent.last_request.event_interpretation_output
        assert ei_output is not None
        assert isinstance(ei_output, EventInterpretationOutput)
        # The EI output should contain data from the mock provider
        assert ei_output.symbol == "AAPL"
        assert ei_output.issuer_code == "037730"

    @pytest.mark.asyncio
    async def test_real_ei_real_ar_real_fdc(
        self,
        repos: RepositoryContainer,
        sample_request: SubmitOrderRequest,
        mock_ei_provider: AIProviderClient,
        mock_ar_provider: AIProviderClient,
        mock_fdc_provider: AIProviderClient,
    ) -> None:
        """Real EI + real AR + real FDC: assemble() succeeds, recorder has 3 runs, FDC output verified."""
        ei_agent = EventInterpretationAgent(provider_client=mock_ei_provider)
        ar_agent = AIRiskAgent(provider_client=mock_ar_provider)
        fdc_agent = FinalDecisionComposerAgent(provider_client=mock_fdc_provider)
        recorder = AgentRunRecorder()

        orchestrator = DecisionOrchestratorService(
            repos,
            event_interpretation_agent=ei_agent,
            ai_risk_agent=ar_agent,
            final_decision_agent=fdc_agent,
            agent_recorder=recorder,
        )

        intent = await orchestrator.assemble(sample_request)
        assert isinstance(intent, OrderIntent)

        # Recorder should have 3 runs
        runs = recorder.list_all()
        assert len(runs) == 3

        # Agent types should include all three real agents
        agent_types = {r.agent_type for r in runs}
        assert agent_types == {
            "event_interpretation",
            "ai_risk",
            "final_decision_composer",
        }

        # EI run should have structured_output_json from mock provider
        ei_run = next(r for r in runs if r.agent_type == "event_interpretation")
        assert ei_run.structured_output_json is not None
        assert ei_run.structured_output_json.get("symbol") == "AAPL"
        assert ei_run.structured_output_json.get("agent_name") == "event_interpretation"

        # AR run should have structured_output_json from mock provider
        ar_run = next(r for r in runs if r.agent_type == "ai_risk")
        assert ar_run.structured_output_json is not None
        assert ar_run.structured_output_json.get("risk_opinion") == "reduce"
        assert ar_run.structured_output_json.get("risk_score") == 0.65
        assert ar_run.structured_output_json.get("agent_name") == "ai_risk"

        # FDC run should have structured_output_json from mock provider
        fdc_run = next(r for r in runs if r.agent_type == "final_decision_composer")
        assert fdc_run.structured_output_json is not None
        assert fdc_run.structured_output_json.get("decision_type") == "BUY"
        assert fdc_run.structured_output_json.get("confidence") == 0.75
        assert fdc_run.structured_output_json.get("agent_name") == "final_decision_composer"
        assert fdc_run.structured_output_json.get("schema_version") == "v1"

    @pytest.mark.asyncio
    async def test_ei_and_ar_output_passed_to_fdc(
        self,
        repos: RepositoryContainer,
        sample_request: SubmitOrderRequest,
        mock_ei_provider: AIProviderClient,
        mock_ar_provider: AIProviderClient,
    ) -> None:
        """Both EI and AR outputs are passed through to the FDC agent via request_with_ei_and_ar."""
        ei_agent = EventInterpretationAgent(provider_client=mock_ei_provider)
        ar_agent = AIRiskAgent(provider_client=mock_ar_provider)

        # Tracking FDC agent that captures the request
        class TrackingFDCAgent:
            last_request: AgentExecutionRequest | None = None

            @property
            def agent_name(self) -> str:
                return "final_decision_composer"

            @property
            def schema_version(self) -> str:
                return "v1"

            async def run(self, request: AgentExecutionRequest) -> FinalDecisionComposerOutput:
                self.last_request = request
                return FinalDecisionComposerOutput()

        fdc_agent = TrackingFDCAgent()
        recorder = AgentRunRecorder()

        orchestrator = DecisionOrchestratorService(
            repos,
            event_interpretation_agent=ei_agent,
            ai_risk_agent=ar_agent,
            final_decision_agent=fdc_agent,  # type: ignore[arg-type]
            agent_recorder=recorder,
        )

        await orchestrator.assemble(sample_request)

        # The FDC agent should have received a request with both EI and AR outputs
        assert fdc_agent.last_request is not None

        # EI output should be present and valid
        ei_output = fdc_agent.last_request.event_interpretation_output
        assert ei_output is not None
        assert isinstance(ei_output, EventInterpretationOutput)
        assert ei_output.symbol == "AAPL"
        assert ei_output.issuer_code == "037730"

        # AR output should be present and valid
        ar_output = fdc_agent.last_request.ai_risk_output
        assert ar_output is not None
        assert isinstance(ar_output, AIRiskOutput)
        assert ar_output.risk_opinion == "reduce"
        assert ar_output.risk_score == 0.65

        # Both outputs received in a single request (the 3-stage request chain)
        assert fdc_agent.last_request.event_interpretation_output is not None
        assert fdc_agent.last_request.ai_risk_output is not None


# ---------------------------------------------------------------------------
# Existing assemble() behaviour preserved
# ---------------------------------------------------------------------------


class TestExistingBehaviourPreserved:
    """Existing assemble() behaviour is unchanged by agent wiring."""

    @pytest.mark.asyncio
    async def test_assemble_returns_order_intent(
        self, service: DecisionOrchestratorService, sample_request: SubmitOrderRequest
    ) -> None:
        """assemble() still returns an OrderIntent."""
        intent = await service.assemble(sample_request)
        assert isinstance(intent, OrderIntent)

    @pytest.mark.asyncio
    async def test_assemble_preserves_request_fields(
        self, service: DecisionOrchestratorService, sample_request: SubmitOrderRequest
    ) -> None:
        """Request fields are preserved in the assembled OrderIntent."""
        intent = await service.assemble(sample_request)
        assert intent.request.symbol == sample_request.symbol
        assert intent.request.side == sample_request.side
        assert intent.request.quantity == sample_request.quantity
        assert intent.request.price == sample_request.price

    @pytest.mark.asyncio
    async def test_assemble_with_decision_context_id(
        self,
        repos: RepositoryContainer,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """When a decision_context_id is provided, it is used."""
        # Seed a decision context
        ctx_id = uuid4()
        ctx = DecisionContextEntity(
            decision_context_id=ctx_id,
            account_id=uuid4(),
            strategy_id=uuid4(),
            config_version_id=uuid4(),
            market_timestamp=None,
            correlation_id="corr-seed",
        )
        await repos.decision_contexts.add(ctx)

        service = DecisionOrchestratorService(repos)
        intent = await service.assemble(
            sample_request,
            decision_context_id=ctx_id,
        )
        assert intent.decision_context_id == ctx_id
        # Recorder should have 3 runs
        assert len(service._agent_recorder.list_all()) == 3

    @pytest.mark.asyncio
    async def test_recorder_accessible_after_assemble(
        self, service: DecisionOrchestratorService, sample_request: SubmitOrderRequest
    ) -> None:
        """Recorder is accessible and contains runs after assemble()."""
        await service.assemble(sample_request)
        runs = service._agent_recorder.list_all()
        assert len(runs) == 3
        # Each run should have structured_output_json
        for run in runs:
            assert run.structured_output_json is not None
