"""Subprocess isolation helpers for the decision pipeline.

Extracted from DecisionOrchestratorService to separate subprocess
serialization/deserialization from decision orchestration logic.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent_trading.config.settings import resolve_provider_runtime_config
from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.event_interpretation import _finalize_ei_output
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
    dict_to_dataclass,
)
from agent_trading.services.common_types import AgentExecutionBundle
from agent_trading.services.common_types import AIDecisionInputs

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# serialize_agent_input
# ---------------------------------------------------------------------------


def serialize_agent_input(
    request: AgentExecutionRequest,
    context: AIPolicyContextView,
    score: ScoreResult | None,
    positional_args: tuple[Any, ...] = (),
    provider_runtime: dict[str, Any] | None = None,
    mode: str = "full",
    event_interpretation_output: dict[str, Any] | None = None,
    ai_risk_output: dict[str, Any] | None = None,
    ai_compliance_output: dict[str, Any] | None = None,
) -> str:
    """Serialize agent input for subprocess execution.

    Produces a JSON payload that matches ``AgentSubprocessInput``
    dataclass in ``scripts/run_agent_subprocess.py``.

    Extracted from DecisionOrchestratorService._serialize_agent_input().

    ``mode``(2026-08-27, held_position 실제 dispatcher 신설 — PR #359
    리뷰 보정): ``"full"``(기본값, 기존 동작 그대로 EI/AR/AC/FDC를 한
    subprocess에서 순차 실행) | ``"pre_fdc"``(EI/AR/AC + FDC skip 판정만,
    FDC-ready면 FDC를 호출하지 않고 즉시 반환) | ``"fdc_only"``(이미
    확보한 reservation grant로 FDC one-shot만 실행 — EI/AR/AC는 호출하지
    않는다). 어느 lane/flag를 대상으로 이 모드를 선택할지는 호출자
    (``DecisionAgentRunner``)가 결정한다 — 이 함수는 그 결정을 그대로
    전달할 뿐이다.

    ``event_interpretation_output``/``ai_risk_output``/
    ``ai_compliance_output``: ``mode="fdc_only"``일 때 pre_fdc 단계의
    결과를 전달해 FDC 프롬프트를 재구성하는 데 쓴다(기존
    ``AgentSubprocessInput``의 동명 필드를 그대로 재사용 — 새 carryover
    포맷을 만들지 않는다).
    """
    resolved_provider_runtime = provider_runtime or resolve_provider_runtime_config()
    payload = {
        # AgentSubprocessInput top-level fields (from request)
        "decision_context_id": str(request.decision_context_id) if request.decision_context_id else None,
        "correlation_id": request.correlation_id,
        "symbol": request.symbol,
        "market": request.market,
        "source_type": request.source_type,

        # AssembledContext (JSON-safe)
        "context": dataclass_to_dict(context),

        # Provider configuration (settings.py와 동일한 해석 규칙 사용)
        "llm_provider": resolved_provider_runtime["llm_provider"],
        "provider_api_key": resolved_provider_runtime["provider_api_key"],
        "provider_base_url": resolved_provider_runtime["provider_base_url"],
        "provider_model_id": resolved_provider_runtime["provider_model_id"],
        "provider_timeout_seconds": resolved_provider_runtime["provider_timeout_seconds"],

        # subprocess 실행 모드(2026-08-27 신설)
        "mode": mode,
        "event_interpretation_output": event_interpretation_output,
        "ai_risk_output": ai_risk_output,
        "ai_compliance_output": ai_compliance_output,

        # Legacy top-level keys (consumed by _reconstruct_context)
        "score": dataclass_to_dict(score) if score is not None else None,
        "positional_args": positional_args,
    }
    return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# deserialize_agent_output
# ---------------------------------------------------------------------------


def deserialize_agent_output(
    raw_json: str,
) -> AgentExecutionBundle:
    """Deserialize agent output from subprocess execution.

    Extracted from DecisionOrchestratorService._deserialize_agent_output().

    Parameters
    ----------
    raw_json
        Raw JSON string from subprocess stdout.
        Expected keys: ``ei_output``, ``ar_output``, ``ac_output``, ``fdc_output``,
        ``ei_error_metadata``, ``ei_skipped``, ``ar_skipped``, ``fdc_skipped``,
        ``skip_reason_codes``(2026-08-17 추가 — 없으면 False/()로 안전하게
        기본값 처리해 구버전 payload와도 호환된다).

    Returns
    -------
    AgentExecutionBundle
        Fully reconstructed bundle with ``AIDecisionInputs`` assembled
        from the three agent outputs.
    """
    data = json.loads(raw_json)

    # Reconstruct dataclass instances from dicts
    # NOTE: The subprocess writes keys "event_output", "risk_output", "composer_output"
    # (matching AgentSubprocessOutput field names).  Support both old-style
    # ("ei_output", "ar_output", "fdc_output") and new-style for resilience.
    ei_output = dict_to_dataclass(
        data.get("event_output") or data.get("ei_output", {}),
        EventInterpretationOutput,
    )  # type: ignore[arg-type]
    ar_output = dict_to_dataclass(
        data.get("risk_output") or data.get("ar_output", {}),
        AIRiskOutput,
    )  # type: ignore[arg-type]
    ac_output = dict_to_dataclass(
        data.get("compliance_output") or data.get("ac_output", {}),
        AIComplianceOutput,
    )  # type: ignore[arg-type]
    fdc_output = dict_to_dataclass(
        data.get("composer_output") or data.get("fdc_output", {}),
        FinalDecisionComposerOutput,
    )  # type: ignore[arg-type]

    ei_error_metadata: dict[str, object] | None = data.get("ei_error_metadata")  # type: ignore[assignment]

    # 2026-08-17 관측성 수정: ei_skipped/ar_skipped/fdc_skipped/
    # skip_reason_codes가 stdout payload에 없는 구버전 subprocess 출력과의
    # 호환을 위해 키 부재 시 안전한 default(False/())를 쓴다.
    ei_skipped = bool(data.get("ei_skipped", False))
    ar_skipped = bool(data.get("ar_skipped", False))
    fdc_skipped = bool(data.get("fdc_skipped", False))
    skip_reason_codes_raw = data.get("skip_reason_codes")
    if isinstance(skip_reason_codes_raw, (list, tuple)):
        skip_reason_codes: tuple[str, ...] = tuple(
            str(code) for code in skip_reason_codes_raw
        )
    elif isinstance(skip_reason_codes_raw, str) and skip_reason_codes_raw:
        # 단일 문자열로 잘못 전달된 경우도 방어적으로 1-tuple로 감싼다.
        skip_reason_codes = (skip_reason_codes_raw,)
    else:
        skip_reason_codes = ()

    # FDC cycle-scoped batch queue lifecycle shadow(Phase 1) 전용 —
    # 구버전 payload(키 없음)와 호환되도록 기본값 ""를 쓴다.
    fdc_ready_at = str(data.get("fdc_ready_at", "") or "")

    # 2026-08-21 신설: strict FDC rate limiter + retry-inclusive permit
    # 관측성 필드. 구버전 subprocess payload(이 필드들이 없는 경우)와도
    # 호환되도록 키 부재 시 안전한 기본값을 쓴다 — FDC가 아예 생략되거나
    # provider 미설정(Stub)이면 자연스럽게 "호출 없음" 기본값과 같다.
    provider_observability: dict[str, object] = {
        "rate_limiter_waited_seconds": float(data.get("rate_limiter_waited_seconds", 0.0)),
        "rate_limiter_slot_acquired": bool(data.get("rate_limiter_slot_acquired", True)),
        "rate_limiter_queue_timeout": bool(data.get("rate_limiter_queue_timeout", False)),
        "rate_limiter_state_file_error": bool(data.get("rate_limiter_state_file_error", False)),
        "provider_http_attempt_count": int(data.get("provider_http_attempt_count", 0)),
        "provider_http_429_count": int(data.get("provider_http_429_count", 0)),
        "provider_execution_seconds": float(data.get("provider_execution_seconds", 0.0)),
        "provider_final_status": str(data.get("provider_final_status", "")),
        # 2026-08-21(2차) 신설: in-cycle FIFO 재대기열 관측성 필드.
        # 구버전 payload(키 없음)와의 호환을 위해 "대기 없음/재대기 없음"을
        # 뜻하는 안전한 기본값을 쓴다.
        "rate_limiter_queue_ticket": str(data.get("rate_limiter_queue_ticket", "")),
        "rate_limiter_queue_position_at_first_wait": int(
            data.get("rate_limiter_queue_position_at_first_wait", -1)
        ),
        "rate_limiter_requeue_count": int(data.get("rate_limiter_requeue_count", 0)),
        "rate_limiter_final_waited_seconds": float(
            data.get("rate_limiter_final_waited_seconds", 0.0)
        ),
        "rate_limiter_queue_deadline_exceeded": bool(
            data.get("rate_limiter_queue_deadline_exceeded", False)
        ),
    }

    # --- Assemble AIDecisionInputs (same logic as _run_agents()) ---
    ai_inputs = AIDecisionInputs(
        # FDC-derived
        decision_type=fdc_output.decision_type,
        confidence=fdc_output.confidence,
        conviction=fdc_output.conviction,
        reason_codes=fdc_output.reason_codes,
        opposing_evidence=fdc_output.opposing_evidence,
        execution_preferences=fdc_output.execution_preferences,
        sizing_hint=fdc_output.sizing_hint,
        side=fdc_output.side if hasattr(fdc_output, "side") else "",
        # AR-derived
        risk_opinion=ar_output.risk_opinion,
        risk_score=ar_output.risk_score,
        risk_confidence=ar_output.confidence,
        size_adjustment_factor=ar_output.size_adjustment_factor,
        risk_reason_codes=ar_output.reason_codes,
        risk_flags=ar_output.risk_flags,
        compliance_opinion=ac_output.compliance_opinion,
        compliance_score=ac_output.compliance_score,
        compliance_confidence=ac_output.confidence,
        compliance_reason_codes=ac_output.reason_codes,
        compliance_policy_flags=ac_output.policy_flags,
        compliance_check_passed=ac_output.compliance_opinion in {"allow", "warn"},
        # EI-derived
        event_bias=ei_output.aggregate_view.overall_bias,
        event_conflict=ei_output.aggregate_view.event_conflict,
        event_reason_codes=ei_output.aggregate_view.top_reason_codes,
        evidence_strength=ei_output.aggregate_view.evidence_strength,
        no_material_events=ei_output.aggregate_view.no_material_events,
        detected_event_count=ei_output.detected_event_count,
        interpreted_event_count=ei_output.interpreted_event_count,
        # Metadata
        source_agent_names=(
            ei_output.agent_name,
            ar_output.agent_name,
            ac_output.agent_name,
            fdc_output.agent_name,
        ),
        schema_versions=(
            ("event_interpretation", ei_output.schema_version),
            ("ai_risk", ar_output.schema_version),
            ("ai_compliance", ac_output.schema_version),
            ("final_decision_composer", fdc_output.schema_version),
        ),
        # 2026-08-17 관측성 수정: subprocess가 실제로 EI/FDC를 생략했는지를
        # in-process 경로(decision_agent_runner.py)와 동일하게 반영한다.
        ei_skipped=ei_skipped,
        ar_skipped=ar_skipped,
        fdc_skipped=fdc_skipped,
        skip_reason_codes=skip_reason_codes,
        fdc_ready_at=fdc_ready_at,
    )

    logger.info(
        "deserialize_agent_output: "
        "ei_output.events=%d ei_output.aggregate_view.no_material_events=%s "
        "ei_output.detected_event_count=%s",
        len(ei_output.events),
        ei_output.aggregate_view.no_material_events,
        ei_output.detected_event_count,
    )

    return AgentExecutionBundle(
        ai_inputs=ai_inputs,
        event_output=ei_output,
        risk_output=ar_output,
        compliance_output=ac_output,
        composer_output=fdc_output,
        ei_error_metadata=ei_error_metadata,
        provider_observability=provider_observability,
    )


# ---------------------------------------------------------------------------
# build_fallback_bundle
# ---------------------------------------------------------------------------


def build_fallback_bundle(
    ei_output: EventInterpretationOutput | None = None,
    ar_output: AIRiskOutput | None = None,
    ac_output: AIComplianceOutput | None = None,
    fdc_output: FinalDecisionComposerOutput | None = None,
    score: ScoreResult | None = None,
    ei_run_id: str | None = None,
    ar_run_id: str | None = None,
    fdc_run_id: str | None = None,
    ei_error_metadata: dict[str, object] | None = None,
) -> AgentExecutionBundle:
    """Build a fallback ``AgentExecutionBundle`` when subprocess execution fails.

    Extracted from DecisionOrchestratorService._build_fallback_bundle().

    When all inputs are ``None`` (the default), the bundle is built from
    default (empty/safe) agent outputs — matching the safe-fallback policy
    in ``_run_agents()``.

    Parameters
    ----------
    ei_output
        Pre-existing EI output to use instead of a default instance.
    ar_output
        Pre-existing AR output to use instead of a default instance.
    fdc_output
        Pre-existing FDC output to use instead of a default instance.
    score
        Pre-existing score result (reserved for future use).
    ei_run_id
        Pre-existing EI run ID (reserved for future use).
    ar_run_id
        Pre-existing AR run ID (reserved for future use).
    fdc_run_id
        Pre-existing FDC run ID (reserved for future use).
    ei_error_metadata
        Error metadata from subprocess execution failure.

    .. warning::

        Fallback bundles produce empty ``summary=""``, ``symbol=""``,
        ``confidence=0``, ``decision_type="HOLD"`` in ``agent_runs``.
        This is a known limitation — the subprocess must receive a valid
        ``provider_client`` to produce meaningful output.
    """
    logger.warning(
        "Building fallback AgentExecutionBundle — all agent outputs will be "
        "default (empty/safe) instances. This typically means the subprocess "
        "failed or timed out, or provider configuration was missing."
    )

    # Use provided outputs or fall back to defaults
    resolved_ei = ei_output if ei_output is not None else EventInterpretationOutput()
    resolved_ar = ar_output if ar_output is not None else AIRiskOutput()
    resolved_ac = ac_output if ac_output is not None else AIComplianceOutput()
    resolved_fdc = fdc_output if fdc_output is not None else FinalDecisionComposerOutput()

    # ★ fallback bundle: _finalize_ei_output()로 interpreted_event_count,
    #   summary_basis, summary 설정 (default 인스턴스에 대해서만 실행)
    if ei_output is None:
        resolved_ei = _finalize_ei_output(resolved_ei)

    ai_inputs = AIDecisionInputs(
        # FDC-derived
        decision_type=resolved_fdc.decision_type,
        confidence=resolved_fdc.confidence,
        conviction=resolved_fdc.conviction,
        reason_codes=resolved_fdc.reason_codes,
        opposing_evidence=resolved_fdc.opposing_evidence,
        execution_preferences=resolved_fdc.execution_preferences,
        sizing_hint=resolved_fdc.sizing_hint,
        side="",
        # AR-derived
        risk_opinion=resolved_ar.risk_opinion,
        risk_score=resolved_ar.risk_score,
        risk_confidence=resolved_ar.confidence,
        size_adjustment_factor=resolved_ar.size_adjustment_factor,
        risk_reason_codes=resolved_ar.reason_codes,
        risk_flags=resolved_ar.risk_flags,
        compliance_opinion=resolved_ac.compliance_opinion,
        compliance_score=resolved_ac.compliance_score,
        compliance_confidence=resolved_ac.confidence,
        compliance_reason_codes=resolved_ac.reason_codes,
        compliance_policy_flags=resolved_ac.policy_flags,
        compliance_check_passed=resolved_ac.compliance_opinion in {"allow", "warn"},
        # EI-derived
        event_bias=resolved_ei.aggregate_view.overall_bias,
        event_conflict=resolved_ei.aggregate_view.event_conflict,
        event_reason_codes=resolved_ei.aggregate_view.top_reason_codes,
        evidence_strength=resolved_ei.aggregate_view.evidence_strength,
        no_material_events=resolved_ei.aggregate_view.no_material_events,
        detected_event_count=resolved_ei.detected_event_count,
        interpreted_event_count=resolved_ei.interpreted_event_count,
        # Metadata
        source_agent_names=(
            resolved_ei.agent_name,
            resolved_ar.agent_name,
            resolved_ac.agent_name,
            resolved_fdc.agent_name,
        ),
        schema_versions=(
            ("event_interpretation", resolved_ei.schema_version),
            ("ai_risk", resolved_ar.schema_version),
            ("ai_compliance", resolved_ac.schema_version),
            ("final_decision_composer", resolved_fdc.schema_version),
        ),
    )

    return AgentExecutionBundle(
        ai_inputs=ai_inputs,
        event_output=resolved_ei,
        risk_output=resolved_ar,
        compliance_output=resolved_ac,
        composer_output=resolved_fdc,
        ei_error_metadata=ei_error_metadata,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "serialize_agent_input",
    "deserialize_agent_output",
    "build_fallback_bundle",
]
