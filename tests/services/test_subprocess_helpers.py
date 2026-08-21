from __future__ import annotations

import json
from uuid import uuid4

from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.schemas import (
    AIComplianceOutput,
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.common_types import (
    AIPolicyContextView,
    ScoreResult,
    dataclass_to_dict,
)
from agent_trading.services.subprocess_helpers import (
    deserialize_agent_output,
    serialize_agent_input,
)


def test_serialize_agent_input_prefers_injected_provider_runtime() -> None:
    request = AgentExecutionRequest(
        decision_context_id=uuid4(),
        correlation_id="corr-1",
        context=AIPolicyContextView(),
        symbol="005930",
        market="KRX",
    )
    provider_runtime = {
        "llm_provider": "gemini",
        "provider_api_key": "gemini-key",
        "provider_base_url": "https://example.test/v1beta/openai/",
        "provider_model_id": "gemini-3.5-flash",
        "provider_timeout_seconds": 77,
    }

    payload = json.loads(
        serialize_agent_input(
            request=request,
            context=AIPolicyContextView(),
            score=ScoreResult(),
            provider_runtime=provider_runtime,
        )
    )

    assert payload["llm_provider"] == "gemini"
    assert payload["provider_api_key"] == "gemini-key"
    assert payload["provider_base_url"] == "https://example.test/v1beta/openai/"
    assert payload["provider_model_id"] == "gemini-3.5-flash"
    assert payload["provider_timeout_seconds"] == 77


def test_serialize_agent_input_includes_primary_index_membership() -> None:
    request = AgentExecutionRequest(
        decision_context_id=uuid4(),
        correlation_id="corr-2",
        context=AIPolicyContextView(
            instrument_market_segment="KOSPI",
            instrument_index_memberships=("KOSPI100", "KOSPI200"),
            primary_index_membership="KOSPI100",
        ),
        symbol="005930",
        market="KRX",
    )

    payload = json.loads(
        serialize_agent_input(
            request=request,
            context=request.context,
            score=ScoreResult(),
        )
    )

    assert payload["context"]["primary_index_membership"] == "KOSPI100"


class TestDeserializeAgentOutputProviderObservability:
    """2026-08-21 strict FDC rate limiter 관측성 필드의 subprocess
    stdout-JSON → deserialize round trip 무손실 검증.

    ``scripts/run_agent_subprocess.py``가 실제로 stdout에 쓰는 것과
    동일한 top-level 키 구조(``AgentSubprocessOutput``의 필드명)를
    직접 재현해, 파일 시스템을 거치지 않고도 이 boundary만 좁게
    검증한다.
    """

    def _build_stdout_payload(self, **overrides: object) -> str:
        base: dict[str, object] = {
            "success": True,
            "event_output": dataclass_to_dict(EventInterpretationOutput()),
            "risk_output": dataclass_to_dict(AIRiskOutput()),
            "compliance_output": dataclass_to_dict(AIComplianceOutput()),
            "composer_output": dataclass_to_dict(
                FinalDecisionComposerOutput(
                    symbol="005930",
                    decision_type="HOLD",
                    reason_codes=("provider_queue_timeout",),
                    summary="[규칙 기반 fallback] 005930 — rate limiter queue_timeout",
                )
            ),
            "duration_seconds": 12.3,
            "ei_error_metadata": None,
            "ei_skipped": False,
            "ar_skipped": False,
            "fdc_skipped": False,
            "skip_reason_codes": [],
            "rate_limiter_waited_seconds": 18.0,
            "rate_limiter_slot_acquired": False,
            "rate_limiter_queue_timeout": True,
            "rate_limiter_state_file_error": False,
            "provider_http_attempt_count": 0,
            "provider_http_429_count": 0,
            "provider_execution_seconds": 18.4,
            "provider_final_status": "provider_queue_timeout",
        }
        base.update(overrides)
        return json.dumps(base)

    def test_queue_timeout_fields_survive_round_trip(self) -> None:
        raw_json = self._build_stdout_payload()

        bundle = deserialize_agent_output(raw_json)

        assert bundle.provider_observability is not None
        obs = bundle.provider_observability
        assert obs["rate_limiter_waited_seconds"] == 18.0
        assert obs["rate_limiter_slot_acquired"] is False
        assert obs["rate_limiter_queue_timeout"] is True
        assert obs["rate_limiter_state_file_error"] is False
        assert obs["provider_http_attempt_count"] == 0
        assert obs["provider_http_429_count"] == 0
        assert obs["provider_execution_seconds"] == 18.4
        assert obs["provider_final_status"] == "provider_queue_timeout"

        # fallback 정책: decision_type=HOLD 유지, reason_codes 비어있지 않음,
        # symbol 보존 — no Gemini HTTP request was implied by attempt_count=0.
        assert bundle.composer_output.decision_type == "HOLD"
        assert bundle.composer_output.reason_codes == ("provider_queue_timeout",)
        assert bundle.composer_output.symbol == "005930"
        assert bundle.composer_output.summary

    def test_limiter_unavailable_fields_survive_round_trip(self) -> None:
        raw_json = self._build_stdout_payload(
            composer_output=dataclass_to_dict(
                FinalDecisionComposerOutput(
                    symbol="196170",
                    decision_type="HOLD",
                    reason_codes=("provider_limiter_unavailable",),
                    summary="provider fallback: provider_limiter_unavailable",
                )
            ),
            rate_limiter_waited_seconds=0.4,
            rate_limiter_slot_acquired=False,
            rate_limiter_queue_timeout=False,
            rate_limiter_state_file_error=True,
            provider_final_status="provider_limiter_unavailable",
        )

        bundle = deserialize_agent_output(raw_json)

        obs = bundle.provider_observability
        assert obs["rate_limiter_state_file_error"] is True
        assert obs["rate_limiter_queue_timeout"] is False
        assert obs["provider_final_status"] == "provider_limiter_unavailable"
        assert bundle.composer_output.reason_codes == ("provider_limiter_unavailable",)
        assert bundle.composer_output.decision_type == "HOLD"
        assert bundle.composer_output.symbol == "196170"

    def test_successful_call_reports_actual_http_attempt_and_429_counts(self) -> None:
        """429 재시도 후 성공한 경우 — Gemini HTTP 요청이 실제로 몇 번
        발생했는지가 손실 없이 전달돼야 한다."""
        raw_json = self._build_stdout_payload(
            composer_output=dataclass_to_dict(
                FinalDecisionComposerOutput(
                    symbol="005930", decision_type="APPROVE", confidence=0.7,
                )
            ),
            rate_limiter_waited_seconds=2.0,
            rate_limiter_slot_acquired=True,
            rate_limiter_queue_timeout=False,
            rate_limiter_state_file_error=False,
            provider_http_attempt_count=2,
            provider_http_429_count=1,
            provider_execution_seconds=4.5,
            provider_final_status="success",
        )

        bundle = deserialize_agent_output(raw_json)

        obs = bundle.provider_observability
        assert obs["provider_http_attempt_count"] == 2
        assert obs["provider_http_429_count"] == 1
        assert obs["provider_final_status"] == "success"
        assert obs["rate_limiter_slot_acquired"] is True

    def test_missing_observability_keys_default_to_no_call_state(self) -> None:
        """구버전 subprocess payload(관측성 필드가 아예 없음)와의 하위
        호환 — 키 부재 시 '호출 없음'을 뜻하는 안전한 기본값으로
        채워져야 하며 예외가 발생하면 안 된다."""
        base: dict[str, object] = {
            "success": True,
            "event_output": dataclass_to_dict(EventInterpretationOutput()),
            "risk_output": dataclass_to_dict(AIRiskOutput()),
            "compliance_output": dataclass_to_dict(AIComplianceOutput()),
            "composer_output": dataclass_to_dict(FinalDecisionComposerOutput()),
        }
        raw_json = json.dumps(base)

        bundle = deserialize_agent_output(raw_json)

        obs = bundle.provider_observability
        assert obs["rate_limiter_waited_seconds"] == 0.0
        assert obs["rate_limiter_slot_acquired"] is True
        assert obs["rate_limiter_queue_timeout"] is False
        assert obs["rate_limiter_state_file_error"] is False
        assert obs["provider_http_attempt_count"] == 0
        assert obs["provider_http_429_count"] == 0
        assert obs["provider_final_status"] == ""
