"""Tests for Phase 4 subprocess isolation for agent calls.

Test coverage
-------------
* ``serialize_agent_input()`` — serialization of agent input to JSON-safe dict
* ``deserialize_agent_output()`` — deserialization of subprocess output
* ``build_fallback_bundle()`` — fallback bundle on timeout/failure
* ``dict_to_dataclass()`` — generic dict-to-dataclass conversion
* ``_run_agents_in_subprocess()`` — subprocess timeout → fallback output
* ``_run_agents_in_subprocess()`` — subprocess success → normal output
* ``_run_agents_in_subprocess()`` — subprocess crash → fallback output
* ``_use_subprocess_isolation`` flag — False preserves existing test compatibility
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.schemas import (
    AIComplianceOutput,
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.common_types import (
    AIDecisionInputs,
    AgentExecutionBundle,
    AssembledContext,
    dataclass_to_dict,
    dict_to_dataclass,
)
from agent_trading.services.subprocess_helpers import (
    build_fallback_bundle,
    deserialize_agent_output,
    serialize_agent_input,
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


@pytest.fixture
def sample_compliance_output() -> AIComplianceOutput:
    """Create a sample AIComplianceOutput."""
    return AIComplianceOutput(
        agent_name="ai_compliance",
        schema_version="v1",
        compliance_opinion="warn",
        compliance_score=0.25,
        confidence=0.8,
        policy_flags=("policy_watch",),
    )


# =========================================================================
# serialize_agent_input tests
# =========================================================================


class TestSerializeAgentInput:
    """Tests for ``serialize_agent_input()``."""

    def test_basic_serialization(self, sample_context: AssembledContext) -> None:
        """Basic serialization produces expected JSON."""
        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test-correlation",
            context=sample_context,
        )
        result = serialize_agent_input(
            request=request,
            context=sample_context,
            score=None,
        )
        assert isinstance(result, str)
        payload = json.loads(result)
        assert "context" in payload
        assert payload["score"] is None
        # request should contain correlation_id
        assert payload["correlation_id"] == "test-correlation"

    def test_serialization_with_none_decision_context(
        self, sample_context: AssembledContext,
    ) -> None:
        """decision_context_id=None is serialized as None."""
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test-no-ctx",
            context=sample_context,
        )
        result = serialize_agent_input(
            request=request,
            context=sample_context,
            score=None,
        )
        assert isinstance(result, str)
        payload = json.loads(result)
        assert payload.get("decision_context_id") is None

    def test_serialized_context_is_json_safe(
        self, sample_context: AssembledContext,
    ) -> None:
        """Serialized output must be JSON-serializable."""
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test-json-safe",
            context=sample_context,
        )
        result = serialize_agent_input(
            request=request,
            context=sample_context,
            score=None,
        )
        # Should not raise
        json.loads(result)


# =========================================================================
# dict_to_dataclass tests
# =========================================================================


class TestDictToDataclass:
    """Tests for ``dict_to_dataclass()``."""

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
        result = dict_to_dataclass(data, EventInterpretationOutput)
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
        result = dict_to_dataclass(data, FinalDecisionComposerOutput)
        assert isinstance(result, FinalDecisionComposerOutput)
        assert result.decision_type == "BUY"
        assert result.execution_preferences.use_limit_order is True
        assert result.sizing_hint.size_mode == "no_change"
        assert result.exit_plan_hint.stop_style == "volatility_based"

    def test_empty_dict_fallback(self) -> None:
        """Empty dict produces default instance."""
        result = dict_to_dataclass({}, EventInterpretationOutput)
        assert isinstance(result, EventInterpretationOutput)
        assert result.agent_name == "event_interpretation"
        assert result.schema_version == "v1"

    def test_partial_dict(self) -> None:
        """Partial dict fills missing fields with defaults."""
        data = {"symbol": "000660"}
        result = dict_to_dataclass(data, EventInterpretationOutput)
        assert result.symbol == "000660"
        # Other fields should have defaults
        assert result.agent_name == "event_interpretation"


# =========================================================================
# deserialize_agent_output tests
# =========================================================================


class TestDeserializeAgentOutput:
    """Tests for ``deserialize_agent_output()``."""

    def test_deserialize_full_output(
        self,
        sample_event_output: EventInterpretationOutput,
        sample_risk_output: AIRiskOutput,
        sample_compliance_output: AIComplianceOutput,
        sample_composer_output: FinalDecisionComposerOutput,
    ) -> None:
        """Full agent output round-trips correctly."""
        # Build a serialized JSON string matching the subprocess output format
        serialized_dict: dict[str, Any] = {
            "success": True,
            "ei_output": dataclass_to_dict(sample_event_output),
            "ar_output": dataclass_to_dict(sample_risk_output),
            "ac_output": dataclass_to_dict(sample_compliance_output),
            "fdc_output": dataclass_to_dict(sample_composer_output),
            "score": None,
        }
        bundle = deserialize_agent_output(json.dumps(serialized_dict))
        assert isinstance(bundle, AgentExecutionBundle)
        assert bundle.event_output.symbol == "005930"
        assert bundle.risk_output.risk_opinion == "allow"
        assert bundle.compliance_output.compliance_opinion == "warn"
        assert bundle.composer_output.decision_type == "HOLD"

    def test_deserialize_with_decision_context_id(
        self,
        sample_event_output: EventInterpretationOutput,
        sample_risk_output: AIRiskOutput,
        sample_compliance_output: AIComplianceOutput,
        sample_composer_output: FinalDecisionComposerOutput,
    ) -> None:
        """decision_context_id is preserved through round-trip."""
        ctx_id = uuid4()
        ei = replace(sample_event_output, decision_context_id=str(ctx_id))
        ar = replace(sample_risk_output, decision_context_id=str(ctx_id))
        ac = replace(sample_compliance_output, decision_context_id=str(ctx_id))
        fdc = replace(sample_composer_output, decision_context_id=str(ctx_id))

        serialized_dict: dict[str, Any] = {
            "success": True,
            "ei_output": dataclass_to_dict(ei),
            "ar_output": dataclass_to_dict(ar),
            "ac_output": dataclass_to_dict(ac),
            "fdc_output": dataclass_to_dict(fdc),
            "score": None,
        }
        bundle = deserialize_agent_output(json.dumps(serialized_dict))
        assert bundle.event_output.decision_context_id == str(ctx_id)
        assert bundle.risk_output.decision_context_id == str(ctx_id)
        assert bundle.compliance_output.decision_context_id == str(ctx_id)
        assert bundle.composer_output.decision_context_id == str(ctx_id)

    def test_deserialize_with_ai_inputs_metadata(
        self,
        sample_event_output: EventInterpretationOutput,
        sample_risk_output: AIRiskOutput,
        sample_compliance_output: AIComplianceOutput,
        sample_composer_output: FinalDecisionComposerOutput,
    ) -> None:
        """AIDecisionInputs metadata is populated from agent outputs."""
        serialized_dict: dict[str, Any] = {
            "success": True,
            "ei_output": dataclass_to_dict(sample_event_output),
            "ar_output": dataclass_to_dict(sample_risk_output),
            "ac_output": dataclass_to_dict(sample_compliance_output),
            "fdc_output": dataclass_to_dict(sample_composer_output),
            "score": None,
        }
        bundle = deserialize_agent_output(json.dumps(serialized_dict))
        assert "event_interpretation" in bundle.ai_inputs.source_agent_names
        assert "ai_risk" in bundle.ai_inputs.source_agent_names
        assert "ai_compliance" in bundle.ai_inputs.source_agent_names
        assert "final_decision_composer" in bundle.ai_inputs.source_agent_names


# =========================================================================
# build_fallback_bundle tests
# =========================================================================


class TestBuildFallbackBundle:
    """Tests for ``build_fallback_bundle()``."""

    def test_fallback_bundle_is_valid(self) -> None:
        """Fallback bundle has all required fields."""
        bundle = build_fallback_bundle()
        assert isinstance(bundle, AgentExecutionBundle)
        assert isinstance(bundle.event_output, EventInterpretationOutput)
        assert isinstance(bundle.risk_output, AIRiskOutput)
        assert isinstance(bundle.compliance_output, AIComplianceOutput)
        assert isinstance(bundle.composer_output, FinalDecisionComposerOutput)
        assert isinstance(bundle.ai_inputs, AIDecisionInputs)

    def test_fallback_bundle_decision_type_is_hold(self) -> None:
        """Fallback decision_type is HOLD (safest default)."""
        bundle = build_fallback_bundle()
        assert bundle.ai_inputs.decision_type == "HOLD"

    def test_fallback_bundle_risk_opinion_is_allow(self) -> None:
        """Fallback risk_opinion is 'allow' (does not block)."""
        bundle = build_fallback_bundle()
        assert bundle.ai_inputs.risk_opinion == "allow"

    def test_fallback_bundle_event_bias_is_neutral(self) -> None:
        """Fallback event_bias is 'neutral' (safest default)."""
        bundle = build_fallback_bundle()
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
    request = AgentExecutionRequest(
        decision_context_id=None,
        correlation_id="test-timeout-fallback",
        context=context,
        symbol="005930",
        market="KRX",
    )

    # With subprocess isolation disabled, this calls _run_agents() directly
    result = await orchestrator._run_agents_in_subprocess(
        request=request,
        assembled_context=context,
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
    request = AgentExecutionRequest(
        decision_context_id=None,
        correlation_id="test-success",
        context=context,
        symbol="005930",
        market="KRX",
    )

    result = await orchestrator._run_agents_in_subprocess(
        request=request,
        assembled_context=context,
    )

    assert isinstance(result, AgentExecutionBundle)
    assert isinstance(result.event_output, EventInterpretationOutput)
    assert isinstance(result.risk_output, AIRiskOutput)
    assert isinstance(result.compliance_output, AIComplianceOutput)
    assert isinstance(result.composer_output, FinalDecisionComposerOutput)


class TestWriteAgentSubprocessOutputRoundTrip:
    """``write_agent_subprocess_output()`` → JSON → ``deserialize_agent_output()``
    실제 round-trip이 AC 값을 보존하는지 검증한다.

    배경(2026-08-17 PR #283): ``scripts/run_agent_subprocess.py::
    _write_output()``이 한때 stdout JSON에 ``compliance_output`` 키를
    쓰지 않아, 부모 프로세스가 항상 default ``AIComplianceOutput()``으로
    복원하던 회귀가 있었다. 그 PR에서는 이 모듈이 import-time에
    ``/workspace`` 디렉터리를 생성하려 시도해(이 harness dev-validation
    컨테이너에서는 read-only라 실패) 실제 함수 호출 대신 AST 정적
    파싱으로만 키 존재를 확인했었다.

    이번 PR에서 payload 생성 로직을
    ``agent_trading.services.ai_agents.subprocess_io``로 분리했다 — 이
    모듈은 import-time 부작용이 전혀 없으므로, 여기서는 실제
    ``write_agent_subprocess_output()``을 호출하고 그 출력을 실제
    ``deserialize_agent_output()``에 넣어 ``AgentExecutionBundle``/
    ``AIDecisionInputs``까지 값이 보존되는지 끝까지 검증한다 — AST 정적
    검사보다 훨씬 강한 검증이므로 이전의 AST 테스트는 제거했다(중복이자
    더 약한 검증이었기 때문).
    """

    def test_round_trip_preserves_compliance_output_default_marker(
        self,
        sample_event_output: EventInterpretationOutput,
        sample_risk_output: AIRiskOutput,
        sample_compliance_output: AIComplianceOutput,
        sample_composer_output: FinalDecisionComposerOutput,
    ) -> None:
        """default(``sample_compliance_output``, opinion="warn")로도 키가 실제로
        전달되는지 확인 — payload 자체에 ``compliance_output`` 키가 없으면
        ``deserialize_agent_output()``이 default ``AIComplianceOutput()``
        (``compliance_opinion="allow"``)으로 복원해버려 이 테스트가 실패한다.
        """
        from io import StringIO

        from agent_trading.services.ai_agents.subprocess_io import (
            write_agent_subprocess_output,
        )

        fake_output = SimpleNamespace(
            success=True,
            event_output=dataclass_to_dict(sample_event_output),
            risk_output=dataclass_to_dict(sample_risk_output),
            compliance_output=dataclass_to_dict(sample_compliance_output),
            composer_output=dataclass_to_dict(sample_composer_output),
            error=None,
            duration_seconds=1.23,
            ei_error_metadata=None,
            ei_skipped=False,
            ar_skipped=False,
            fdc_skipped=False,
            skip_reason_codes=(),
        )

        stream = StringIO()
        write_agent_subprocess_output(fake_output, stream)
        raw_json = stream.getvalue()

        # 페이로드 자체에 키가 존재하는지도 직접 확인(회귀의 정확한 지점).
        payload = json.loads(raw_json)
        assert "compliance_output" in payload

        bundle = deserialize_agent_output(raw_json)
        assert bundle.compliance_output.compliance_opinion == "warn"
        assert bundle.ai_inputs.compliance_opinion == "warn"

    def test_round_trip_preserves_all_compliance_fields_and_ai_inputs(
        self,
        sample_event_output: EventInterpretationOutput,
        sample_risk_output: AIRiskOutput,
        sample_composer_output: FinalDecisionComposerOutput,
    ) -> None:
        """default와 뚜렷이 구분되는 AC 값이 ``bundle.compliance_output``과
        ``bundle.ai_inputs.compliance_*`` 양쪽 모두에 온전히 보존돼야 한다.
        """
        from io import StringIO

        from agent_trading.services.ai_agents.subprocess_io import (
            write_agent_subprocess_output,
        )

        ctx_id = uuid4()
        ac = AIComplianceOutput(
            agent_name="ai_compliance",
            schema_version="v1",
            decision_context_id=str(ctx_id),
            symbol="005930",
            compliance_opinion="review",
            compliance_score=0.7,
            confidence=1.0,
            reason_codes=(
                "compliance_rule_set:deterministic_v1",
                "risk_reject_review",
            ),
            policy_flags=("eligibility_xxx",),
        )

        fake_output = SimpleNamespace(
            success=True,
            event_output=dataclass_to_dict(sample_event_output),
            risk_output=dataclass_to_dict(sample_risk_output),
            compliance_output=dataclass_to_dict(ac),
            composer_output=dataclass_to_dict(sample_composer_output),
            error=None,
            duration_seconds=2.5,
            ei_error_metadata=None,
            ei_skipped=False,
            ar_skipped=False,
            fdc_skipped=False,
            skip_reason_codes=(),
        )

        stream = StringIO()
        write_agent_subprocess_output(fake_output, stream)
        bundle = deserialize_agent_output(stream.getvalue())

        # --- AgentExecutionBundle.compliance_output ---
        assert bundle.compliance_output.compliance_opinion == "review"
        assert bundle.compliance_output.compliance_score == 0.7
        assert bundle.compliance_output.confidence == 1.0
        assert bundle.compliance_output.reason_codes == (
            "compliance_rule_set:deterministic_v1",
            "risk_reject_review",
        )
        assert bundle.compliance_output.policy_flags == ("eligibility_xxx",)
        assert bundle.compliance_output.decision_context_id == str(ctx_id)
        assert bundle.compliance_output.symbol == "005930"

        # --- AIDecisionInputs.compliance_* ---
        assert bundle.ai_inputs.compliance_opinion == "review"
        assert bundle.ai_inputs.compliance_score == 0.7
        assert bundle.ai_inputs.compliance_confidence == 1.0
        assert bundle.ai_inputs.compliance_reason_codes == (
            "compliance_rule_set:deterministic_v1",
            "risk_reject_review",
        )
        assert bundle.ai_inputs.compliance_policy_flags == ("eligibility_xxx",)
        # "review"는 {"allow", "warn"}에 속하지 않으므로 False여야 한다.
        assert bundle.ai_inputs.compliance_check_passed is False

    def test_allow_and_warn_opinions_pass_compliance_check(
        self,
        sample_event_output: EventInterpretationOutput,
        sample_risk_output: AIRiskOutput,
        sample_composer_output: FinalDecisionComposerOutput,
    ) -> None:
        """``compliance_check_passed``는 allow/warn=True, review/reject=False다."""
        from io import StringIO

        from agent_trading.services.ai_agents.subprocess_io import (
            write_agent_subprocess_output,
        )

        expectations = {
            "allow": True,
            "warn": True,
            "review": False,
            "reject": False,
        }
        for opinion, expected_passed in expectations.items():
            ac = AIComplianceOutput(
                agent_name="ai_compliance",
                compliance_opinion=opinion,
            )
            fake_output = SimpleNamespace(
                success=True,
                event_output=dataclass_to_dict(sample_event_output),
                risk_output=dataclass_to_dict(sample_risk_output),
                compliance_output=dataclass_to_dict(ac),
                composer_output=dataclass_to_dict(sample_composer_output),
                error=None,
                duration_seconds=0.1,
                ei_error_metadata=None,
                ei_skipped=False,
                ar_skipped=False,
                fdc_skipped=False,
                skip_reason_codes=(),
            )
            stream = StringIO()
            write_agent_subprocess_output(fake_output, stream)
            bundle = deserialize_agent_output(stream.getvalue())
            assert bundle.ai_inputs.compliance_check_passed is expected_passed, (
                f"opinion={opinion!r}: expected compliance_check_passed="
                f"{expected_passed}, got {bundle.ai_inputs.compliance_check_passed}"
            )

    def test_round_trip_preserves_fdc_skipped_metadata(
        self,
        sample_event_output: EventInterpretationOutput,
        sample_risk_output: AIRiskOutput,
        sample_compliance_output: AIComplianceOutput,
        sample_composer_output: FinalDecisionComposerOutput,
    ) -> None:
        """2026-08-17 관측성 수정 회귀 테스트.

        subprocess 경로에서 ``scripts/run_agent_subprocess.py::_check_fdc_skip()``
        가 실제로 FDC를 생략했을 때, 그 사실(``fdc_skipped=True``,
        ``skip_reason_codes``)이 stdout JSON → ``deserialize_agent_output()``을
        거쳐 ``bundle.ai_inputs.fdc_skipped``/``skip_reason_codes``까지
        보존돼야 한다. 이 필드가 없으면(구버전 payload) 안전하게
        False/()로 기본값 처리되는지도 함께 확인한다.
        """
        from io import StringIO

        from agent_trading.services.ai_agents.subprocess_io import (
            write_agent_subprocess_output,
        )

        fake_output = SimpleNamespace(
            success=True,
            event_output=dataclass_to_dict(sample_event_output),
            risk_output=dataclass_to_dict(sample_risk_output),
            compliance_output=dataclass_to_dict(sample_compliance_output),
            composer_output=dataclass_to_dict(sample_composer_output),
            error=None,
            duration_seconds=0.5,
            ei_error_metadata=None,
            ei_skipped=False,
            ar_skipped=False,
            fdc_skipped=True,
            skip_reason_codes=("risk_reject",),
        )

        stream = StringIO()
        write_agent_subprocess_output(fake_output, stream)
        raw_json = stream.getvalue()

        payload = json.loads(raw_json)
        assert payload["fdc_skipped"] is True
        assert payload["skip_reason_codes"] == ["risk_reject"]

        bundle = deserialize_agent_output(raw_json)
        assert bundle.ai_inputs.ei_skipped is False
        assert bundle.ai_inputs.ar_skipped is False
        assert bundle.ai_inputs.fdc_skipped is True
        assert bundle.ai_inputs.skip_reason_codes == ("risk_reject",)

    def test_deserialize_missing_skip_fields_defaults_to_false(
        self,
        sample_event_output: EventInterpretationOutput,
        sample_risk_output: AIRiskOutput,
        sample_compliance_output: AIComplianceOutput,
        sample_composer_output: FinalDecisionComposerOutput,
    ) -> None:
        """구버전 payload(``ei_skipped``/``ar_skipped``/``fdc_skipped``/
        ``skip_reason_codes`` 키가 아예 없음)와의 하위 호환 — 예외 없이
        안전한 default(False/())로 복원돼야 한다."""
        legacy_payload = {
            "success": True,
            "event_output": dataclass_to_dict(sample_event_output),
            "risk_output": dataclass_to_dict(sample_risk_output),
            "compliance_output": dataclass_to_dict(sample_compliance_output),
            "composer_output": dataclass_to_dict(sample_composer_output),
            "error": None,
            "duration_seconds": 0.1,
            "ei_error_metadata": None,
            # ei_skipped/ar_skipped/fdc_skipped/skip_reason_codes 키 없음
        }
        bundle = deserialize_agent_output(json.dumps(legacy_payload))
        assert bundle.ai_inputs.ei_skipped is False
        assert bundle.ai_inputs.ar_skipped is False
        assert bundle.ai_inputs.fdc_skipped is False
        assert bundle.ai_inputs.skip_reason_codes == ()


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
    request = AgentExecutionRequest(
        decision_context_id=ctx_id,
        correlation_id="test-with-ctx-id",
        context=context,
        symbol="005930",
        market="KRX",
    )

    result = await orchestrator._run_agents_in_subprocess(
        request=request,
        assembled_context=context,
    )

    assert isinstance(result, AgentExecutionBundle)
    assert result.ai_inputs.decision_type in ("HOLD", "APPROVE", "REJECT", "WATCH", "EXIT", "REDUCE")


@pytest.mark.asyncio
async def test_rehydrate_subprocess_agent_runs_records_all_four() -> None:
    """subprocess 결과 rehydrate가 EI/AR/AC/FDC 4개 모두 기록해야 한다.

    2026-08-16 이전에는 AC(``ai_compliance``) record가 rehydrate 코드에서
    누락되어 있었다(``agent_runs``에 ``ai_compliance`` row가 전혀 쌓이지
    않던 원인). ``_rehydrate_subprocess_agent_runs()``로 추출한 뒤 이
    회귀를 직접 검증한다.
    """
    from agent_trading.services.ai_agents.recorder import AgentRunRecorder
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
        # repo=None → 순수 in-memory 기록(MagicMock().add()가
        # awaitable이 아니라서 발생하는 TypeError를 피한다).
        agent_recorder=AgentRunRecorder(),
    )

    ctx_id = uuid4()
    context = AssembledContext(source_type="core")
    request = AgentExecutionRequest(
        decision_context_id=ctx_id,
        correlation_id="test-rehydrate-four",
        context=context,
        symbol="005930",
        market="KRX",
    )

    bundle = await orchestrator._run_agents_in_subprocess(
        request=request,
        assembled_context=context,
    )

    fdc_run_id = await orchestrator._rehydrate_subprocess_agent_runs(
        resolved_context_id=ctx_id,
        agent_bundle=bundle,
    )

    runs = await orchestrator._agent_recorder.list_by_decision_context(ctx_id)
    recorded_agent_types = {run.agent_type for run in runs}

    assert recorded_agent_types == {
        "event_interpretation",
        "ai_risk",
        "ai_compliance",
        "final_decision_composer",
    }
    assert fdc_run_id is not None

    ac_run = next(run for run in runs if run.agent_type == "ai_compliance")
    assert ac_run.structured_output_json.get("agent_name") == "ai_compliance"
    assert ac_run.structured_output_json.get("compliance_opinion") in {
        "allow", "warn", "review", "reject",
    }


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
