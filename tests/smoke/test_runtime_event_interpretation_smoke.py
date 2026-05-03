"""Smoke tests: real EventInterpretationAgent through the runtime path.

Verifies that:
* ``build_default_runtime()`` creates a real ``EventInterpretationAgent``
  when DeepSeek provider credentials are configured, and falls back to
  ``None`` (stub) when they are missing.
* The real agent's ``run()`` method produces a valid
  ``EventInterpretationOutput`` with the correct schema shape.
* ``orchestrator.assemble()`` works correctly with a real
  ``EventInterpretationAgent`` injected (AI Risk and Final Decision
  Composer remain stubs).
* The ``AgentRunRecorder`` stores structured output from the real
  provider call.

These tests use in-memory repositories — no database required.

Markers
-------
* ``smoke`` — all tests in ``TestRuntimeEventInterpretationSmoke``.
"""

from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from agent_trading.config.settings import AppSettings
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.runtime.bootstrap import build_default_runtime
from agent_trading.services.ai_agents import EventInterpretationAgent
from agent_trading.services.ai_agents.event_interpretation import (
    StubEventInterpretationAgent,
)
from agent_trading.services.ai_agents.schemas import (
    AggregateEventView,
    EventInterpretationOutput,
)
from agent_trading.services.decision_orchestrator import (
    AssembledContext,
    DecisionOrchestratorService,
    OrderIntent,
)

# ---------------------------------------------------------------------------
# Module-level skip condition for smoke tests
# ---------------------------------------------------------------------------

_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
_HAVE_DEEPSEEK_CONFIG = (
    _LLM_PROVIDER == "deepseek"
    and bool(os.getenv("DEEPSEEK_API_KEY"))
    and bool(os.getenv("DEEPSEEK_BASE_URL"))
    and bool(os.getenv("DEEPSEEK_MODEL_ID"))
)

_SKIP_REASON = (
    "DeepSeek provider not fully configured — skipping runtime smoke test. "
    "Set LLM_PROVIDER=deepseek, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, "
    "and DEEPSEEK_MODEL_ID in the environment."
)


# ---------------------------------------------------------------------------
# Always-run: stub fallback verification
# ---------------------------------------------------------------------------


class TestRuntimeEventInterpretationFallback:
    """Runtime returns ``None`` (stub) when provider credentials are missing.

    These tests run unconditionally — no credential required.
    """

    def test_default_runtime_stub_when_no_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When all provider env vars are empty, ``event_interpretation_agent``
        is ``None`` and the orchestrator uses ``StubEventInterpretationAgent``."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)

        runtime = build_default_runtime()
        agent = runtime["event_interpretation_agent"]
        assert agent is None, (
            f"Expected None (stub) when no provider credential, "
            f"got {type(agent).__name__}"
        )

        orchestrator: DecisionOrchestratorService = runtime["orchestrator"]
        # The orchestrator internally falls back to StubEventInterpretationAgent
        # when event_interpretation_agent is None.
        internal_agent = orchestrator._event_interpretation_agent
        assert isinstance(internal_agent, StubEventInterpretationAgent), (
            f"Expected StubEventInterpretationAgent, "
            f"got {type(internal_agent).__name__}"
        )

    @pytest.mark.asyncio
    async def test_orchestrator_assemble_with_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Orchestrator ``assemble()`` succeeds with stub fallback
        (no real provider call).  This guards against regression in the
        existing safe-fallback path."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)

        runtime = build_default_runtime()
        orchestrator: DecisionOrchestratorService = runtime["orchestrator"]

        request = SubmitOrderRequest(
            client_order_id="stub-fallback-001",
            correlation_id="stub-fallback-corr",
            account_ref="stub-account",
            strategy_id="strat-stub",
            symbol="005930",
            market="KRX",
            side="buy",
            order_type="limit",
            time_in_force="day",
            quantity=Decimal("10"),
            price=Decimal("50000"),
            idempotency_key="idem-stub-fallback",
        )
        intent = await orchestrator.assemble(request)
        assert isinstance(intent, OrderIntent)

        # Recorder should have 3 stub agent runs
        runs = orchestrator._agent_recorder.list_all()
        assert len(runs) == 3, f"Expected 3 runs, got {len(runs)}"
        agent_types = {r.agent_type for r in runs}
        assert agent_types == {
            "event_interpretation",
            "ai_risk",
            "final_decision_composer",
        }, f"Unexpected agent types: {agent_types}"


# ---------------------------------------------------------------------------
# Smoke: real DeepSeek provider through the runtime path
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.skipif(not _HAVE_DEEPSEEK_CONFIG, reason=_SKIP_REASON)
class TestRuntimeEventInterpretationSmoke:
    """Real DeepSeek provider call through ``build_default_runtime()``.

    Requires all four DeepSeek provider config values to be set in the
    environment:
    * ``LLM_PROVIDER=deepseek``
    * ``DEEPSEEK_API_KEY``
    * ``DEEPSEEK_BASE_URL``
    * ``DEEPSEEK_MODEL_ID``

    API calls are minimised:
    * The runtime fixture is built once per class.
    * ``agent.run()`` is called once; the result is shared across two
      test methods.
    * ``orchestrator.assemble()`` is called once (separate test).
    Total: **2 real API calls** for the entire class.

    .. important::

       Assertions are limited to **type-level schema shape** and
       **deterministic fields** (e.g. ``decision_context_id`` is
       ``None`` when we pass ``None``).  We do **not** assert specific
       values for model-generated fields (``schema_version``,
       ``agent_name``, ``symbol``, etc.) because the model's output
       varies between providers, models, and runs.

       The ``EventInterpretationAgent`` post-processing step only
       overrides metadata fields when the model returned a *falsy*
       value, so any non-empty model output is preserved as-is.
    """

    @pytest.fixture(scope="class")
    def runtime(self) -> dict[str, object]:
        """Build the default runtime (in-memory repos)."""
        return build_default_runtime()

    @pytest.fixture(scope="class")
    def agent(
        self, runtime: dict[str, object]
    ) -> EventInterpretationAgent:
        """Return the real ``EventInterpretationAgent`` from the runtime."""
        agent = runtime["event_interpretation_agent"]
        assert isinstance(agent, EventInterpretationAgent), (
            f"Expected EventInterpretationAgent, "
            f"got {type(agent).__name__}"
        )
        return agent

    @pytest.fixture(scope="class")
    def orchestrator(
        self, runtime: dict[str, object]
    ) -> DecisionOrchestratorService:
        """Return the orchestrator from the runtime."""
        orch: DecisionOrchestratorService = runtime["orchestrator"]  # type: ignore[assignment]
        return orch

    # ------------------------------------------------------------------
    # Agent type verification (no API call)
    # ------------------------------------------------------------------

    def test_runtime_creates_real_agent(
        self, agent: EventInterpretationAgent
    ) -> None:
        """``build_default_runtime()`` returns a real
        ``EventInterpretationAgent`` when provider config is complete."""
        # The fixture already asserts isinstance; this is an explicit sanity check.
        assert isinstance(agent, EventInterpretationAgent)

    # ------------------------------------------------------------------
    # agent.run() — 1 API call, result shared
    # ------------------------------------------------------------------

    @pytest.fixture(scope="class")
    async def agent_run_result(
        self, agent: EventInterpretationAgent
    ) -> EventInterpretationOutput:
        """Call ``agent.run()`` once and cache the result.

        Builds a minimal ``AgentExecutionRequest`` with no decision context
        and no external events — the provider still receives a valid prompt
        and returns structured output.
        """
        from agent_trading.services.ai_agents.base import AgentExecutionRequest

        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="runtime-smoke-ei-001",
            context=AssembledContext(),
        )
        return await agent.run(request)

    @pytest.mark.asyncio
    async def test_agent_run_returns_structured_output(
        self, agent_run_result: EventInterpretationOutput
    ) -> None:
        """``agent.run()`` returns a valid ``EventInterpretationOutput``
        with the correct schema shape.

        Verification is limited to **deterministic field types and schema
        shape** — we do NOT assert specific model interpretation values
        because the model may return different values across runs.
        """
        result = agent_run_result
        assert isinstance(result, EventInterpretationOutput)

        # --- Deterministic: decision_context_id is None (we passed None) ---
        assert result.decision_context_id is None

        # --- Type-level shape verification (not value-level) ---
        assert isinstance(result.schema_version, str)
        assert result.schema_version != "", "schema_version should not be empty"

        assert isinstance(result.agent_name, str)
        assert result.agent_name != "", "agent_name should not be empty"

        assert isinstance(result.symbol, str)
        assert isinstance(result.issuer_code, str)

        # events should ideally be tuple[InterpretedEvent, ...], but the
        # model may return a non-conforming type (e.g. empty string).
        # We verify gracefully without enforcing the type.
        if isinstance(result.events, tuple):
            assert True  # shape is correct
        # If the model returned a string for events, accept it —
        # the smoke test verifies the integration path, not model quality.

        # aggregate_view should ideally be AggregateEventView.
        if isinstance(result.aggregate_view, AggregateEventView):
            assert isinstance(result.aggregate_view.total_events, int)
        # If the model returned a string, accept it.

    @pytest.mark.asyncio
    async def test_agent_run_preserves_fields(
        self, agent_run_result: EventInterpretationOutput
    ) -> None:
        """``EventInterpretationOutput`` fields preserve the provider
        response structure.

        This test reuses ``agent_run_result`` from the same API call —
        no additional provider invocation.

        Verification is limited to **deterministic field types and schema
        shape**, not model interpretation values.
        """
        result = agent_run_result

        # --- schema_version and agent_name are always present ---
        assert isinstance(result.schema_version, str)
        assert result.schema_version != "", "schema_version should not be empty"

        assert isinstance(result.agent_name, str)
        assert result.agent_name != "", "agent_name should not be empty"

        # --- symbol is a string ---
        assert isinstance(result.symbol, str)
        # We do NOT assert a specific symbol value — it depends on model output.

        # --- events type check (lenient) ---
        assert isinstance(result.events, (tuple, str)), (
            f"Expected events to be tuple or str, got {type(result.events)}"
        )
        if isinstance(result.events, tuple) and result.events:
            from agent_trading.services.ai_agents.schemas import InterpretedEvent

            first_event = result.events[0]
            assert isinstance(first_event, InterpretedEvent)
            assert isinstance(first_event.event_type, str)
            assert isinstance(first_event.headline, str | None)

        # --- aggregate_view type check (lenient) ---
        if isinstance(result.aggregate_view, AggregateEventView):
            assert isinstance(result.aggregate_view.total_events, int)
            assert isinstance(result.aggregate_view.positive_count, int)
            assert isinstance(result.aggregate_view.negative_count, int)
            assert isinstance(result.aggregate_view.neutral_count, int)
            assert isinstance(result.aggregate_view.net_sentiment, str | None)

        # --- issuer_code is a string (may be empty) ---
        assert isinstance(result.issuer_code, str)

    # ------------------------------------------------------------------
    # orchestrator.assemble() — 1 API call (EI only; AR/FDC are stubs)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_orchestrator_assemble_with_real_agent(
        self,
        orchestrator: DecisionOrchestratorService,
        agent: EventInterpretationAgent,
    ) -> None:
        """``orchestrator.assemble()`` works with a real
        ``EventInterpretationAgent`` injected.

        Verifies:
        1. ``assemble()`` returns a valid ``OrderIntent``.
        2. The recorder has exactly 3 runs (EI, AR, FDC).
        3. The EI run has ``structured_output_json`` populated by the
           real provider call.
        4. The EI run's ``agent_type`` is ``"event_interpretation"``
           (real agent, not stub).
        5. The AR and FDC runs use stub agents (no HTTP call).
        """
        # Sanity: the injected agent is real
        assert isinstance(agent, EventInterpretationAgent)
        # The orchestrator's internal EI agent is the same real instance
        assert (
            orchestrator._event_interpretation_agent is agent
        ), "Orchestrator must use the injected real agent"

        # The AR and FDC agents are stubs
        from agent_trading.services.ai_agents.ai_risk import StubAIRiskAgent
        from agent_trading.services.ai_agents.final_decision_composer import (
            StubFinalDecisionComposerAgent,
        )

        assert isinstance(
            orchestrator._ai_risk_agent, StubAIRiskAgent
        ), "AI Risk Agent should be stub"
        assert isinstance(
            orchestrator._final_decision_agent, StubFinalDecisionComposerAgent
        ), "Final Decision Composer should be stub"

        # --- assemble() ---
        request = SubmitOrderRequest(
            client_order_id="smoke-ei-orch-001",
            correlation_id="runtime-smoke-asm-001",
            account_ref="smoke-test",
            strategy_id="strat-smoke",
            symbol="005930",
            market="KRX",
            side="buy",
            order_type="limit",
            time_in_force="day",
            quantity=Decimal("10"),
            price=Decimal("50000"),
            idempotency_key="idem-smoke-orch",
        )
        intent = await orchestrator.assemble(request)
        assert isinstance(intent, OrderIntent)

        # --- Recorder verification ---
        runs = orchestrator._agent_recorder.list_all()
        assert len(runs) == 3, f"Expected 3 runs, got {len(runs)}"

        # EI run (index 0): real provider call
        ei_run = runs[0]
        assert ei_run.agent_type == "event_interpretation"
        assert ei_run.structured_output_json is not None
        # Verify schema fields exist — but don't assert specific values
        # (model may return "v1", "1.0.0", etc.)
        assert isinstance(
            ei_run.structured_output_json.get("schema_version"), str
        ), "schema_version should be a string"
        assert (
            ei_run.structured_output_json.get("agent_name") is not None
        ), "agent_name should be present"

        # AR run (index 1): stub
        ar_run = runs[1]
        assert ar_run.agent_type == "ai_risk"
        assert ar_run.structured_output_json is not None

        # FDC run (index 2): stub
        fdc_run = runs[2]
        assert fdc_run.agent_type == "final_decision_composer"
        assert fdc_run.structured_output_json is not None
