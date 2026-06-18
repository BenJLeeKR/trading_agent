"""Subprocess isolation helpers for the decision pipeline.

Extracted from DecisionOrchestratorService to separate subprocess
serialization/deserialization from decision orchestration logic.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent_trading.config.settings import resolve_provider_runtime_config
from agent_trading.domain.entities import (
    AgentRunEntity,
    CashBalanceSnapshotEntity,
    ExternalEventEntity,
    PositionSnapshotEntity,
)
from agent_trading.repositories.contracts import AccountLookup
from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.event_interpretation import _finalize_ei_output
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.common_types import (
    AIPolicyContextView,
    AssembledContext,
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
) -> str:
    """Serialize agent input for subprocess execution.

    Produces a JSON payload that matches ``AgentSubprocessInput``
    dataclass in ``scripts/run_agent_subprocess.py``.

    Extracted from DecisionOrchestratorService._serialize_agent_input().
    """
    provider_runtime = resolve_provider_runtime_config()
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
        "llm_provider": provider_runtime["llm_provider"],
        "provider_api_key": provider_runtime["provider_api_key"],
        "provider_base_url": provider_runtime["provider_base_url"],
        "provider_model_id": provider_runtime["provider_model_id"],
        "provider_timeout_seconds": provider_runtime["provider_timeout_seconds"],

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
        Expected keys: ``ei_output``, ``ar_output``, ``fdc_output``,
        ``score``, ``ei_run_id``, ``ar_run_id``, ``fdc_run_id``,
        ``ei_error_metadata``.

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
    fdc_output = dict_to_dataclass(
        data.get("composer_output") or data.get("fdc_output", {}),
        FinalDecisionComposerOutput,
    )  # type: ignore[arg-type]

    # Score
    score_data = data.get("score")
    score = ScoreResult(**score_data) if score_data else ScoreResult()

    # Run IDs from subprocess
    ei_run_id: str | None = data.get("ei_run_id")  # type: ignore[assignment]
    ar_run_id: str | None = data.get("ar_run_id")  # type: ignore[assignment]
    fdc_run_id: str | None = data.get("fdc_run_id")  # type: ignore[assignment]
    ei_error_metadata: dict[str, object] | None = data.get("ei_error_metadata")  # type: ignore[assignment]

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
            fdc_output.agent_name,
        ),
        schema_versions=(
            ("event_interpretation", ei_output.schema_version),
            ("ai_risk", ar_output.schema_version),
            ("final_decision_composer", fdc_output.schema_version),
        ),
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
        composer_output=fdc_output,
        ei_error_metadata=ei_error_metadata,
    )


# ---------------------------------------------------------------------------
# build_fallback_bundle
# ---------------------------------------------------------------------------


def build_fallback_bundle(
    ei_output: EventInterpretationOutput | None = None,
    ar_output: AIRiskOutput | None = None,
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
            resolved_fdc.agent_name,
        ),
        schema_versions=(
            ("event_interpretation", resolved_ei.schema_version),
            ("ai_risk", resolved_ar.schema_version),
            ("final_decision_composer", resolved_fdc.schema_version),
        ),
    )

    return AgentExecutionBundle(
        ai_inputs=ai_inputs,
        event_output=resolved_ei,
        risk_output=resolved_ar,
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
