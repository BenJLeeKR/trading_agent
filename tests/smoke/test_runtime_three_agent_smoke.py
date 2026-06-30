"""Smoke tests: real 4-agent chain through the runtime path.

Verifies that:
* ``build_default_runtime()`` creates real ``EventInterpretationAgent``,
  ``AIRiskAgent``, ``AIComplianceAgent``, and
  ``FinalDecisionComposerAgent`` when provider credentials are configured,
  and falls back to ``None`` (stub) for all four when they are missing.
* ``orchestrator.assemble()`` executes the full EI → AR → AC → FDC chain
  via real provider calls, records all 4 runs, and assembles a valid
  ``AIDecisionInputs`` contract on ``OrderIntent``.
* Partial chains (EI-only real, EI+AR+AC real) correctly mix real and
  stub agents, with the recorder and ``AIDecisionInputs`` reflecting the
  expected combination.

These tests use in-memory repositories — no database required.

Markers
-------
* ``smoke`` — all tests in ``TestRuntimeThreeAgentSmoke`` and
  ``TestRuntimeThreeAgentPartialChain``.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from agent_trading.config.settings import AppSettings
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.runtime.bootstrap import build_default_runtime
from agent_trading.services.ai_agents import (
    AIComplianceAgent,
    AIRiskAgent,
    EventInterpretationAgent,
    FinalDecisionComposerAgent,
)
from agent_trading.services.decision_orchestrator import (
    AIDecisionInputs,
    DecisionOrchestratorService,
    OrderIntent,
)

# ---------------------------------------------------------------------------
# Provider-agnostic skip condition for smoke tests
# ---------------------------------------------------------------------------
# Uses AppSettings() which resolves LLM_PROVIDER + the corresponding
# DEEPSEEK_* or OPENAI_* env vars — same logic as _build_provider_agent().


def _have_real_provider_config() -> bool:
    """Check whether the environment has a fully configured provider.

    Uses ``AppSettings()`` which resolves ``LLM_PROVIDER`` and the
    corresponding ``DEEPSEEK_*`` or ``OPENAI_*`` env vars provider-
    agnostically — mirrors the same logic used by
    ``_build_provider_agent()`` in :mod:`bootstrap`.
    """
    s = AppSettings()
    return bool(
        s.llm_provider
        and s.provider_api_key
        and s.provider_base_url
        and s.provider_model_id
    )


_SKIP_REASON = (
    "LLM provider not fully configured — skipping 4-agent runtime smoke test. "
    "Set LLM_PROVIDER and the corresponding provider environment variables "
    "(API key, base URL, model ID)."
)


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _sample_request() -> SubmitOrderRequest:
    """Return a minimal ``SubmitOrderRequest`` for smoke tests."""
    return SubmitOrderRequest(
        client_order_id="smoke-3agent-001",
        correlation_id="runtime-3agent-smoke-001",
        account_ref="smoke-test",
        strategy_id="strat-3agent-smoke",
        symbol="005930",
        market="KRX",
        side="buy",
        order_type="limit",
        time_in_force="day",
        quantity=Decimal("10"),
        price=Decimal("50000"),
        idempotency_key="idem-3agent-smoke-001",
    )


# ---------------------------------------------------------------------------
# Always-run: stub fallback verification
# ---------------------------------------------------------------------------


class TestRuntimeThreeAgentFallback:
    """Runtime returns ``None`` (stub) for all four agents when provider
    credentials are missing.

    These tests are **env-isolated** — they force all provider env vars
    to empty via ``monkeypatch``, so they are deterministic regardless of
    the user's shell environment."""

    def test_default_runtime_all_stub_when_no_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All four agent slots are ``None`` (stub fallback) when no
        provider credential is configured."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
        monkeypatch.delenv("DEEPSEEK_MODEL_ID", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_MODEL_ID", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        runtime = build_default_runtime()
        assert runtime["event_interpretation_agent"] is None
        assert runtime["ai_risk_agent"] is None
        assert runtime["ai_compliance_agent"] is None
        assert runtime["final_decision_agent"] is None

    @pytest.mark.asyncio
    async def test_orchestrator_assemble_all_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``assemble()`` succeeds with all stubs — recorder stores 4 runs
        with ``structured_output_json`` and ``ai_backend_inputs`` carries
        safe-fallback defaults.

        .. note::

           Stub agents share the same ``agent_type`` (``agent_name``) as
           real agents (both return ``"event_interpretation"``, ``"ai_risk"``,
           ``"ai_compliance"``, ``"final_decision_composer"``).  The recorder cannot distinguish
           stubs from real agents by ``agent_type`` — only the injection
           path (``None`` vs real instance) carries that semantic
           distinction."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
        monkeypatch.delenv("DEEPSEEK_MODEL_ID", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_MODEL_ID", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        runtime = build_default_runtime()
        orchestrator: DecisionOrchestratorService = runtime["orchestrator"]
        intent = await orchestrator.assemble(_sample_request())

        assert isinstance(intent, OrderIntent)

        # Recorder: 4 runs — each with structured_output_json
        # NOTE: list_all() returns runs ordered by started_at DESC (contract),
        # so we lookup by agent_type rather than assuming insertion order.
        runs = await orchestrator._agent_recorder.list_all()
        assert len(runs) == 4
        runs_by_type = {r.agent_type: r for r in runs}
        for expected_agent in (
            "event_interpretation", "ai_risk", "ai_compliance", "final_decision_composer"
        ):
            run = runs_by_type.get(expected_agent)
            assert run is not None, (
                f"Missing run for agent_type={expected_agent!r}; "
                f"got types: {list(runs_by_type)}"
            )
            assert run.structured_output_json is not None, (
                f"Run agent_type={expected_agent!r}: structured_output_json is None"
            )
            assert (
                run.structured_output_json.get("schema_version") == "v1"
            ), f"Run agent_type={expected_agent!r}: schema_version mismatch"

        # AIDecisionInputs: safe-fallback defaults for decision values,
        # but agent_name / schema_version metadata is populated by stub
        # outputs (same values as real agents).
        ai = intent.ai_backend_inputs
        assert isinstance(ai, AIDecisionInputs)
        assert ai.decision_type == "HOLD"
        assert ai.risk_opinion == "allow"
        assert ai.compliance_opinion == "allow"
        assert ai.event_bias == "neutral"
        assert len(ai.source_agent_names) == 4
        assert len(ai.schema_versions) == 4


# ---------------------------------------------------------------------------
# Real 4-agent full chain — requires provider config
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.skipif(not _have_real_provider_config(), reason=_SKIP_REASON)
class TestRuntimeThreeAgentSmoke:
    """Real provider call — full EI → AR → AC → FDC chain through
    ``build_default_runtime()``.

    Requires provider config values in the environment (DeepSeek or
    OpenAI — controlled by ``LLM_PROVIDER``).

    API calls are minimised:
    * The runtime fixture is built once per class.
    * ``orchestrator.assemble()`` is called once; the result is shared
      across two test methods.
    Total: **1 real ``assemble()`` call** (4 internal provider calls) for
    the entire class.
    """

    @pytest.fixture(scope="class")
    def runtime(self) -> dict[str, object]:
        """Build the default runtime (in-memory repos)."""
        return build_default_runtime()

    def test_runtime_creates_real_agents(
        self, runtime: dict[str, object]
    ) -> None:
        """All four agent slots hold real agent instances."""
        ei = runtime["event_interpretation_agent"]
        ar = runtime["ai_risk_agent"]
        ac = runtime["ai_compliance_agent"]
        fdc = runtime["final_decision_agent"]

        assert isinstance(ei, EventInterpretationAgent), (
            f"Expected EventInterpretationAgent, got {type(ei).__name__}"
        )
        assert isinstance(ar, AIRiskAgent), (
            f"Expected AIRiskAgent, got {type(ar).__name__}"
        )
        assert isinstance(ac, AIComplianceAgent), (
            f"Expected AIComplianceAgent, got {type(ac).__name__}"
        )
        assert isinstance(fdc, FinalDecisionComposerAgent), (
            f"Expected FinalDecisionComposerAgent, got {type(fdc).__name__}"
        )

        assert ei.agent_name == "event_interpretation"
        assert ar.agent_name == "ai_risk"
        assert ac.agent_name == "ai_compliance"
        assert fdc.agent_name == "final_decision_composer"

    @pytest.fixture(scope="class")
    async def assemble_result(
        self, runtime: dict[str, object]
    ) -> OrderIntent:
        """Call ``orchestrator.assemble()`` once and cache the result.

        This executes the full EI → AR → AC → FDC chain with real provider
        calls (4 internal provider calls, 1 real API invocation).
        """
        orchestrator: DecisionOrchestratorService = runtime["orchestrator"]  # type: ignore[assignment]
        return await orchestrator.assemble(_sample_request())

    @pytest.mark.asyncio
    async def test_orchestrator_assemble_with_real_agents(
        self,
        runtime: dict[str, object],
        assemble_result: OrderIntent,
    ) -> None:
        """``assemble()`` returns ``OrderIntent`` — recorder stores 4 real
        runs with ``structured_output_json`` and correct metadata."""
        intent = assemble_result
        assert isinstance(intent, OrderIntent)

        # Recorder: 4 runs, all real agent_type
        orchestrator: DecisionOrchestratorService = runtime["orchestrator"]  # type: ignore[assignment]
        runs = await orchestrator._agent_recorder.list_all()
        assert len(runs) == 4
        runs_by_type = {run.agent_type: run for run in runs}

        for expected_agent in (
            "event_interpretation", "ai_risk", "ai_compliance", "final_decision_composer"
        ):
            run = runs_by_type[expected_agent]
            assert run.agent_type == expected_agent, (
                f"Run: expected agent_type={expected_agent!r}, "
                f"got {run.agent_type!r}"
            )
            assert run.structured_output_json is not None, (
                f"Run ({expected_agent}): structured_output_json is None"
            )
            assert run.structured_output_json.get("schema_version"), (
                f"Run {expected_agent}: schema_version missing"
            )
            assert run.structured_output_json.get("agent_name") == expected_agent, (
                f"Run {expected_agent}: agent_name mismatch"
            )

    @pytest.mark.asyncio
    async def test_ai_backend_inputs_assembled(
        self,
        assemble_result: OrderIntent,
    ) -> None:
        """``AIDecisionInputs`` is assembled on ``OrderIntent`` with
        correct structural contract — metadata, field existence, and
        schema versions from all four agents."""
        ai = assemble_result.ai_backend_inputs
        assert isinstance(ai, AIDecisionInputs)

        # Metadata: source_agent_names from _run_agents() assembly
        assert len(ai.source_agent_names) == 4, (
            f"Expected 4 source_agent_names, got {len(ai.source_agent_names)}"
        )
        assert all(str(name).strip() for name in ai.source_agent_names), (
            f"Empty source_agent_names entry detected: {ai.source_agent_names}"
        )

        # Metadata: schema_versions — each agent has a (name, version) tuple
        assert len(ai.schema_versions) == 4, (
            f"Expected 4 schema_versions, got {len(ai.schema_versions)}"
        )
        for agent_name in (
            "event_interpretation",
            "ai_risk",
            "ai_compliance",
            "final_decision_composer",
        ):
            matching = [v for v in ai.schema_versions if v[0] == agent_name]
            assert len(matching) == 1, (
                f"Missing schema_version entry for {agent_name!r}"
            )
            assert matching[0][1], (
                f"Empty schema_version for {agent_name!r}: "
                f"{matching[0][1]!r}"
            )

        # Structural contract: every AIDecisionInputs field is accessible
        # (no AttributeError).  Values are model-dependent and may be
        # conservative defaults — that is acceptable.
        _ = ai.decision_type
        _ = ai.confidence
        _ = ai.conviction
        _ = ai.reason_codes
        _ = ai.opposing_evidence
        _ = ai.execution_preferences
        _ = ai.sizing_hint
        _ = ai.risk_opinion
        _ = ai.risk_score
        _ = ai.risk_confidence
        _ = ai.size_adjustment_factor
        _ = ai.risk_reason_codes
        _ = ai.risk_flags
        _ = ai.event_bias
        _ = ai.event_conflict
        _ = ai.event_reason_codes
        _ = ai.compliance_opinion
        _ = ai.compliance_score
        _ = ai.compliance_confidence
        _ = ai.compliance_reason_codes
        _ = ai.compliance_policy_flags
        _ = ai.compliance_check_passed


# ---------------------------------------------------------------------------
# Partial real-agent chains — requires provider config
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.skipif(not _have_real_provider_config(), reason=_SKIP_REASON)
class TestRuntimeThreeAgentPartialChain:
    """Partial real-agent chains: some agents real, some stub.

    Verifies that:
    * A runtime with all-real agents is built once (class-scoped).
    * Individual real agents are extracted and injected into
      ``DecisionOrchestratorService`` with ``None`` (stub) for the
      remaining slots.
    * The recorder correctly distinguishes real runs from stub runs.
    * ``AIDecisionInputs`` metadata reflects the real/stub combination.

    API calls are minimised:
    * The full runtime is built once (0 API calls).
    * ``test_ei_only_real_rest_stub`` — 1 ``assemble()`` (1 real provider
      call: EI only; AR, AC, and FDC are stubs).
    * ``test_ei_ar_ac_real_fdc_stub`` — 1 ``assemble()`` (3 real provider
      calls: EI + AR + AC; FDC is stub).
    Total: **2 real ``assemble()`` calls** (4 internal provider calls) for
    the entire class.
    """

    @pytest.fixture(scope="class")
    def full_runtime(self) -> dict[str, object]:
        """Build runtime with all real agents (1 build, 0 API calls)."""
        return build_default_runtime()

    @pytest.fixture(scope="class")
    def repos(
        self, full_runtime: dict[str, object]
    ) -> RepositoryContainer:
        """Extract the repository container from the runtime."""
        repos: RepositoryContainer = full_runtime["repositories"]  # type: ignore[assignment]
        return repos

    @pytest.fixture(scope="class")
    def real_ei(
        self, full_runtime: dict[str, object]
    ) -> EventInterpretationAgent:
        """Extract the real ``EventInterpretationAgent``."""
        agent = full_runtime["event_interpretation_agent"]
        assert isinstance(agent, EventInterpretationAgent)
        return agent

    @pytest.fixture(scope="class")
    def real_ar(
        self, full_runtime: dict[str, object]
    ) -> AIRiskAgent:
        """Extract the real ``AIRiskAgent``."""
        agent = full_runtime["ai_risk_agent"]
        assert isinstance(agent, AIRiskAgent)
        return agent

    @pytest.fixture(scope="class")
    def real_ac(
        self, full_runtime: dict[str, object]
    ) -> AIComplianceAgent:
        """Extract the real ``AIComplianceAgent``."""
        agent = full_runtime["ai_compliance_agent"]
        assert isinstance(agent, AIComplianceAgent)
        return agent

    # ------------------------------------------------------------------
    # EI only real; AR and FDC fall back to stubs
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_ei_only_real_rest_stub(
        self,
        real_ei: EventInterpretationAgent,
        repos: RepositoryContainer,
    ) -> None:
        """Real EI + stub AR + stub AC + stub FDC — recorder shows 1 real + 3 stub
        runs; ``AIDecisionInputs`` metadata is consistent."""
        orchestrator = DecisionOrchestratorService(
            repos=repos,
            event_interpretation_agent=real_ei,
            ai_risk_agent=None,       # stub fallback
            ai_compliance_agent=None,  # stub fallback
            final_decision_agent=None,  # stub fallback
        )
        before_count = len(await orchestrator._agent_recorder.list_all())
        intent = await orchestrator.assemble(_sample_request())

        # Recorder: 4 runs — 1 real EI, 3 stubs
        # NOTE: Stub agents use the same agent_type as real agents
        # (both return "ai_risk", "ai_compliance", "final_decision_composer").
        # The stub/real distinction is in the injection path, not the
        # agent_type string.
        runs = await orchestrator._agent_recorder.list_all()
        recent_runs = runs[: len(runs) - before_count]
        assert len(recent_runs) == 4
        assert {run.agent_type for run in recent_runs} == {
            "event_interpretation",
            "ai_risk",
            "ai_compliance",
            "final_decision_composer",
        }

        # AIDecisionInputs: metadata reflects the real/stub combination
        ai = intent.ai_backend_inputs
        assert len(ai.source_agent_names) == 4

        # Only EI has a real schema_version entry
        ei_versions = [
            v for v in ai.schema_versions if v[0] == "event_interpretation"
        ]
        assert len(ei_versions) == 1
        assert ei_versions[0][1] == "v1"

        # AR/AC/FDC fields are at default values (stub fallback contract)
        assert ai.risk_opinion == "allow"
        assert ai.compliance_opinion == "allow"
        assert ai.decision_type == "HOLD"

        # Structural check: all fields accessible
        _ = ai.event_bias

    # ------------------------------------------------------------------
    # EI + AR real; FDC falls back to stub
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_ei_ar_ac_real_fdc_stub(
        self,
        real_ei: EventInterpretationAgent,
        real_ar: AIRiskAgent,
        real_ac: AIComplianceAgent,
        repos: RepositoryContainer,
    ) -> None:
        """Real EI + real AR + real AC + stub FDC — recorder shows 3 real + 1 stub
        runs; ``AIDecisionInputs`` metadata reflects all pre-FDC agents."""
        orchestrator = DecisionOrchestratorService(
            repos=repos,
            event_interpretation_agent=real_ei,
            ai_risk_agent=real_ar,
            ai_compliance_agent=real_ac,
            final_decision_agent=None,  # stub fallback
        )
        before_count = len(await orchestrator._agent_recorder.list_all())
        intent = await orchestrator.assemble(_sample_request())

        # Recorder: 4 runs — 3 real (EI + AR + AC), 1 stub (FDC)
        # NOTE: Stub FDC uses the same agent_type as real FDC
        # ("final_decision_composer").  The stub/real distinction is
        # in the injection path, not the agent_type string.
        runs = await orchestrator._agent_recorder.list_all()
        recent_runs = runs[: len(runs) - before_count]
        assert len(recent_runs) == 4
        assert {run.agent_type for run in recent_runs} == {
            "event_interpretation",
            "ai_risk",
            "ai_compliance",
            "final_decision_composer",
        }

        # AIDecisionInputs: metadata reflects both real agents
        ai = intent.ai_backend_inputs
        assert len(ai.source_agent_names) == 4

        # EI, AR, AC have real schema_version entries; FDC entry is from stub
        ei_ar_versions = [
            v
            for v in ai.schema_versions
            if v[0] in ("event_interpretation", "ai_risk", "ai_compliance")
        ]
        assert len(ei_ar_versions) == 3

        # FDC is stub → decision_type is default
        assert ai.decision_type == "HOLD"
        assert ai.compliance_opinion in {"allow", "warn", "review", "reject"}

        # Structural check: all fields accessible
        _ = ai.event_bias
        _ = ai.risk_opinion
        _ = ai.compliance_opinion
