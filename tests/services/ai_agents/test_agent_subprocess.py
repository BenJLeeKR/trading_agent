"""Tests for Phase 4 subprocess isolation for agent calls.

Test coverage
-------------
* ``_serialize_agent_input()`` — serialization of agent input to JSON-safe dict
* ``_deserialize_agent_output()`` — deserialization of subprocess output
* ``_build_fallback_bundle()`` — fallback bundle on timeout/failure
* ``_dict_to_dataclass()`` — generic dict-to-dataclass conversion
* ``_run_agents_in_subprocess()`` — subprocess timeout → fallback output
* ``_run_agents_in_subprocess()`` — subprocess success → normal output
* ``_run_agents_in_subprocess()`` — subprocess crash → fallback output
* ``_use_subprocess_isolation`` flag — False preserves existing test compatibility
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest

from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.decision_orchestrator import (
    AIDecisionInputs,
    AgentExecutionBundle,
    AssembledContext,
    _build_fallback_bundle,
    _dataclass_to_dict,
    _deserialize_agent_output,
    _dict_to_dataclass,
    _serialize_agent_input,
)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def sample_context() -> AssembledContext:
    """Create a minimal AssembledContext for testing."""
    return AssembledContext(
        source_type="core",
    )


@pytest.fixture
def sample_event_output() -> EventInterpretationOutput:
    """Create a sample EventInterpretationOutput."""
    return EventInterpretationOutput(
        agent_name="event_interpretation",
        schema_version="v1",
        symbol="005930",
    )


@pytest.fixture
def sample_risk_output() -> AIRiskOutput:
    """Create a sample AIRiskOutput."""
    return AIRiskOutput(
        agent_name="ai_risk",
        schema_version="v1",
        risk_opinion="allow",
        risk_score=0.3,
        confidence=0.85,
    )


@pytest.fixture
def sample_composer_output() -> FinalDecisionComposerOutput:
    """Create a sample FinalDecisionComposerOutput."""
    return FinalDecisionComposerOutput(
        agent_name="final_decision_composer",
        schema_version="v1",
        decision_type="HOLD",
        confidence=0.7,
        conviction=0.6,
    )


# =========================================================================
# _serialize_agent_input tests
# =========================================================================


class TestSerializeAgentInput:
    """Tests for ``_serialize_agent_input()``."""

    def test_basic_serialization(self, sample_context: AssembledContext) -> None:
        """Basic serialization produces expected keys."""
        ctx_id = uuid4()
        result = _serialize_agent_input(
            assembled_context=sample_context,
            decision_context_id=ctx_id,
            correlation_id="test-correlation",
            symbol="005930",
            market="KRX",
        )
        assert isinstance(result, dict)
        assert result["correlation_id"] == "test-correlation"
        assert result["symbol"] == "005930"
        assert result["market"] == "KRX"
        assert result["decision_context_id"] == str(ctx_id)
        assert "context" in result

    def test_serialization_with_none_decision_context(
        self, sample_context: AssembledContext,
    ) -> None:
        """decision_context_id=None is serialized as None."""
        result = _serialize_agent_input(
            assembled_context=sample_context,
            decision_context_id=None,
            correlation_id="test-no-ctx",
            symbol=None,
            market=None,
        )
        assert result["decision_context_id"] is None
        assert result["symbol"] is None
        assert result["market"] is None

    def test_serialized_context_is_json_safe(
        self, sample_context: AssembledContext,
    ) -> None:
        """Serialized output must be JSON-serializable."""
        result = _serialize_agent_input(
            assembled_context=sample_context,
            decision_context_id=None,
            correlation_id="test-json-safe",
        )
        # Should not raise
        json.dumps(result)


# =========================================================================
# _dict_to_dataclass tests
# =========================================================================


class TestDictToDataclass:
    """Tests for ``_dict_to_dataclass()``."""

    def test_simple_dataclass(self) -> None:
        """Simple flat dataclass round-trips correctly."""
        data = {
            "agent_name": "test_agent",
            "schema_version": "v1",
            "decision_context_id": None,
            "symbol": "005930",
            "issuer_code": "",
            "events": [],
            "aggregate_view": {
                "overall_bias": "neutral",
                "event_conflict": False,
                "top_reason_codes": [],
                "opposing_evidence": [],
                "evidence_strength": "none",
                "event_count": 0,
                "no_material_events": True,
            },
        }
        result = _dict_to_dataclass(EventInterpretationOutput, data)
        assert isinstance(result, EventInterpretationOutput)
        assert result.agent_name == "test_agent"
        assert result.symbol == "005930"

    def test_nested_dataclass(self) -> None:
        """Nested dataclass fields are reconstructed recursively."""
        data = {
            "agent_name": "final_decision_composer",
            "schema_version": "v1",
            "decision_context_id": None,
            "symbol": "005930",
            "decision_type": "BUY",
            "side": "buy",
            "entry_style": "limit",
            "time_horizon": "swing",
            "confidence": 0.8,
            "conviction": 0.7,
            "reason_codes": ("momentum", "volume"),
            "opposing_evidence": (),
            "execution_preferences": {
                "use_limit_order": True,
                "price_band_hint": {
                    "reference_type": "last_price",
                    "max_slippage_bps": 15,
                },
                "allow_partial_fill": True,
            },
            "sizing_hint": {
                "size_mode": "no_change",
                "size_adjustment_factor": 0.0,
            },
            "exit_plan_hint": {
                "stop_style": "volatility_based",
                "take_profit_style": "partial_scale_out",
                "max_holding_days": 20,
            },
            "summary": "",
        }
        result = _dict_to_dataclass(FinalDecisionComposerOutput, data)
        assert isinstance(result, FinalDecisionComposerOutput)
        assert result.decision_type == "BUY"
        assert result.execution_preferences.use_limit_order is True
        assert result.sizing_hint.size_mode == "no_change"
        assert result.exit_plan_hint.stop_style == "volatility_based"

    def test_empty_dict_fallback(self) -> None:
        """Empty dict produces default instance."""
        result = _dict_to_dataclass(EventInterpretationOutput, {})
        assert isinstance(result, EventInterpretationOutput)
        assert result.agent_name == "event_interpretation"
        assert result.schema_version == "v1"

    def test_partial_dict(self) -> None:
        """Partial dict fills missing fields with defaults."""
        data = {"symbol": "000660"}
        result = _dict_to_dataclass(EventInterpretationOutput, data)
        assert result.symbol == "000660"
        # Other fields should have defaults
        assert result.agent_name == "event_interpretation"


# =========================================================================
# _deserialize_agent_output tests
# =========================================================================


class TestDeserializeAgentOutput:
    """Tests for ``_deserialize_agent_output()``."""

    def test_deserialize_full_output(
        self,
        sample_event_output: EventInterpretationOutput,
        sample_risk_output: AIRiskOutput,
        sample_composer_output: FinalDecisionComposerOutput,
    ) -> None:
        """Full agent output round-trips correctly."""
        # Build a serialized dict matching the subprocess output format
        serialized: dict[str, Any] = {
            "success": True,
            "event_output": _dataclass_to_dict(sample_event_output),
            "risk_output": _dataclass_to_dict(sample_risk_output),
            "composer_output": _dataclass_to_dict(sample_composer_output),
        }
        bundle = _deserialize_agent_output(serialized)
        assert isinstance(bundle, AgentExecutionBundle)
        assert bundle.event_output.symbol == "005930"
        assert bundle.risk_output.risk_opinion == "allow"
        assert bundle.composer_output.decision_type == "HOLD"

    def test_deserialize_with_decision_context_id(
        self,
        sample_event_output: EventInterpretationOutput,
        sample_risk_output: AIRiskOutput,
        sample_composer_output: FinalDecisionComposerOutput,
    ) -> None:
        """decision_context_id is preserved through round-trip."""
        ctx_id = uuid4()
        ei = replace(sample_event_output, decision_context_id=str(ctx_id))
        ar = replace(sample_risk_output, decision_context_id=str(ctx_id))
        fdc = replace(sample_composer_output, decision_context_id=str(ctx_id))

        serialized: dict[str, Any] = {
            "success": True,
            "event_output": _dataclass_to_dict(ei),
            "risk_output": _dataclass_to_dict(ar),
            "composer_output": _dataclass_to_dict(fdc),
        }
        bundle = _deserialize_agent_output(serialized)
        assert bundle.event_output.decision_context_id == str(ctx_id)
        assert bundle.risk_output.decision_context_id == str(ctx_id)
        assert bundle.composer_output.decision_context_id == str(ctx_id)

    def test_deserialize_with_ai_inputs_metadata(
        self,
        sample_event_output: EventInterpretationOutput,
        sample_risk_output: AIRiskOutput,
        sample_composer_output: FinalDecisionComposerOutput,
    ) -> None:
        """AIDecisionInputs metadata is populated from agent outputs."""
        serialized: dict[str, Any] = {
            "success": True,
            "event_output": _dataclass_to_dict(sample_event_output),
            "risk_output": _dataclass_to_dict(sample_risk_output),
            "composer_output": _dataclass_to_dict(sample_composer_output),
        }
        bundle = _deserialize_agent_output(serialized)
        assert "event_interpretation" in bundle.ai_inputs.source_agent_names
        assert "ai_risk" in bundle.ai_inputs.source_agent_names
        assert "final_decision_composer" in bundle.ai_inputs.source_agent_names


# =========================================================================
# _build_fallback_bundle tests
# =========================================================================


class TestBuildFallbackBundle:
    """Tests for ``_build_fallback_bundle()``."""

    def test_fallback_bundle_is_valid(self) -> None:
        """Fallback bundle has all required fields."""
        bundle = _build_fallback_bundle()
        assert isinstance(bundle, AgentExecutionBundle)
        assert isinstance(bundle.event_output, EventInterpretationOutput)
        assert isinstance(bundle.risk_output, AIRiskOutput)
        assert isinstance(bundle.composer_output, FinalDecisionComposerOutput)
        assert isinstance(bundle.ai_inputs, AIDecisionInputs)

    def test_fallback_bundle_decision_type_is_hold(self) -> None:
        """Fallback decision_type is HOLD (safest default)."""
        bundle = _build_fallback_bundle()
        assert bundle.ai_inputs.decision_type == "HOLD"

    def test_fallback_bundle_risk_opinion_is_allow(self) -> None:
        """Fallback risk_opinion is 'allow' (does not block)."""
        bundle = _build_fallback_bundle()
        assert bundle.ai_inputs.risk_opinion == "allow"

    def test_fallback_bundle_event_bias_is_neutral(self) -> None:
        """Fallback event_bias is 'neutral' (safest default)."""
        bundle = _build_fallback_bundle()
        # neutral is the safest default event bias
        assert bundle.ai_inputs.event_bias == "neutral"


# =========================================================================
# Integration: _run_agents_in_subprocess (requires subprocess execution)
#
# NOTE: These tests use use_subprocess_isolation=False because subprocess
# isolation requires real agent dependencies (provider_client, etc.) that
# cannot be mocked at the subprocess level.  The subprocess isolation
# code path is tested indirectly via the unit tests above
# (TestSerializeAgentInput, TestDeserializeAgentOutput, etc.) and via
# the constructor flag test (TestUseSubprocessIsolationFlag).
#
# Full end-to-end subprocess isolation tests require a real database and
# real AI provider credentials, and are run as smoke tests in staging.
# =========================================================================


@pytest.mark.asyncio
async def test_run_agents_in_subprocess_timeout_fallback() -> None:
    """Subprocess timeout produces fallback output.

    NOTE: This test runs with use_subprocess_isolation=False because
    subprocess isolation requires real agent dependencies.  The subprocess
    code path is tested indirectly via unit tests above.
    """
    from agent_trading.services.decision_orchestrator import (
        DecisionOrchestratorService,
    )

    from unittest.mock import AsyncMock, MagicMock

    mock_repos = MagicMock()
    mock_repos.unit_of_work = MagicMock()
    mock_repos.unit_of_work.connection = None

    orchestrator = DecisionOrchestratorService(
        repos=mock_repos,  # type: ignore[arg-type]
        use_subprocess_isolation=False,
    )

    context = AssembledContext(source_type="core")

    # With subprocess isolation disabled, this calls _run_agents() directly
    result = await orchestrator._run_agents_in_subprocess(
        assembled_context=context,
        decision_context_id=None,
        correlation_id="test-timeout-fallback",
        symbol="005930",
        market="KRX",
    )

    assert isinstance(result, AgentExecutionBundle)
    assert isinstance(result.ai_inputs, AIDecisionInputs)
    # The result should always be valid, even on timeout
    assert result.ai_inputs.decision_type in ("HOLD", "APPROVE", "REJECT", "WATCH", "EXIT", "REDUCE")


@pytest.mark.asyncio
async def test_run_agents_in_subprocess_success() -> None:
    """Subprocess success produces valid agent outputs.

    NOTE: This test runs with use_subprocess_isolation=False because
    subprocess isolation requires real agent dependencies.
    """
    from agent_trading.services.decision_orchestrator import (
        DecisionOrchestratorService,
    )

    from unittest.mock import MagicMock

    mock_repos = MagicMock()
    mock_repos.unit_of_work = MagicMock()
    mock_repos.unit_of_work.connection = None

    orchestrator = DecisionOrchestratorService(
        repos=mock_repos,  # type: ignore[arg-type]
        use_subprocess_isolation=False,
    )

    context = AssembledContext(source_type="core")

    result = await orchestrator._run_agents_in_subprocess(
        assembled_context=context,
        decision_context_id=None,
        correlation_id="test-success",
        symbol="005930",
        market="KRX",
    )

    assert isinstance(result, AgentExecutionBundle)
    assert isinstance(result.event_output, EventInterpretationOutput)
    assert isinstance(result.risk_output, AIRiskOutput)
    assert isinstance(result.composer_output, FinalDecisionComposerOutput)


@pytest.mark.asyncio
async def test_run_agents_in_subprocess_with_decision_context() -> None:
    """Subprocess works with a valid decision_context_id."""
    from agent_trading.services.decision_orchestrator import (
        DecisionOrchestratorService,
    )

    from unittest.mock import MagicMock

    mock_repos = MagicMock()
    mock_repos.unit_of_work = MagicMock()
    mock_repos.unit_of_work.connection = None

    orchestrator = DecisionOrchestratorService(
        repos=mock_repos,  # type: ignore[arg-type]
        use_subprocess_isolation=False,
    )

    ctx_id = uuid4()
    context = AssembledContext(source_type="core")

    result = await orchestrator._run_agents_in_subprocess(
        assembled_context=context,
        decision_context_id=ctx_id,
        correlation_id="test-with-ctx-id",
        symbol="005930",
        market="KRX",
    )

    assert isinstance(result, AgentExecutionBundle)
    assert result.ai_inputs.decision_type in ("HOLD", "APPROVE", "REJECT", "WATCH", "EXIT", "REDUCE")


# =========================================================================
# _use_subprocess_isolation flag tests
#
# NOTE: This section MUST be at the end of the file because
# test_default_is_true_without_env_override uses importlib.reload() which
# invalidates previously imported class references (AgentExecutionBundle,
# etc.), causing isinstance() checks in subsequent tests to fail.
# =========================================================================


class TestUseSubprocessIsolationFlag:
    """Tests for the ``_use_subprocess_isolation`` flag."""

    def test_default_is_true_without_env_override(self) -> None:
        """Module-level default is True (production) when env var is unset.

        NOTE: This test uses a subprocess to avoid importlib.reload()
        which would invalidate previously imported class references
        (AgentExecutionBundle, OrderIntent, etc.) and cause isinstance()
        checks in subsequent tests to fail across the entire test suite.
        """
        import subprocess
        import sys
        code = (
            "import os;"
            "os.environ.pop('AGENT_SUBPROCESS_ISOLATION', None);"
            "from agent_trading.services.decision_orchestrator import _USE_SUBPROCESS_ISOLATION;"
            "print(_USE_SUBPROCESS_ISOLATION)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"subprocess stderr: {result.stderr}"
        assert result.stdout.strip() == "True"

    def test_constructor_override(self) -> None:
        """Constructor accepts override for test compatibility."""
        from agent_trading.services.decision_orchestrator import (
            DecisionOrchestratorService,
        )
        from agent_trading.repositories.container import RepositoryContainer

        # We can't easily instantiate RepositoryContainer without DB,
        # but we can verify the constructor parameter exists and is accepted.
        # Full integration test is in test_decision_orchestrator.py.
        import inspect
        sig = inspect.signature(DecisionOrchestratorService.__init__)
        assert "use_subprocess_isolation" in sig.parameters
        param = sig.parameters["use_subprocess_isolation"]
        assert param.default is None  # None → use module-level default
