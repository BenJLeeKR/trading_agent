"""Decision inspection endpoints: ``GET /trade-decisions``,
``GET /decision-contexts/{id}``.
"""

from __future__ import annotations

import json
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_db, get_repos
from agent_trading.api.schemas import (
    CandidateAlignmentDiagnosticsResponse,
    CandidateAlignmentSampleItem,
    CandidateAlignmentStatusItem,
    CandidateIntentDistributionItem,
    DecisionContextDetail,
    PaginatedTradeDecisionsResponse,
    TradeDecisionDetail,
    WatchDiagnosticsEvidenceStrengthItem,
    WatchDiagnosticsReasonCodeItem,
    WatchDiagnosticsResponse,
    WatchDiagnosticsSampleItem,
    WatchDiagnosticsSourceTypeItem,
)
from agent_trading.domain.entities import AgentRunEntity, GuardrailEvaluationEntity
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.contracts import TradeDecisionRow
from agent_trading.repositories.filters import OrderQuery

router = APIRouter(tags=["decisions"])


def _safe_enum_str(value: object) -> str:
    """Enum 또는 문자열 값을 API 응답용 문자열로 정규화."""
    if value is None:
        return ""
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_phase_trace(
    value: object,
) -> list[dict[str, object]] | None:
    """Normalize ``phase_trace`` into a JSON list for the API schema.

    Historical/driver-specific read paths may surface ``phase_trace`` as a
    JSON-encoded string like ``"[]"`` instead of a decoded Python list.
    """
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, list) else None
    return None


def _extract_ai_compliance_projection(
    decision_json: dict[str, object] | None,
) -> dict[str, object] | None:
    if not isinstance(decision_json, dict):
        return None
    payload = {
        "opinion": decision_json.get("compliance_opinion"),
        "score": decision_json.get("compliance_score"),
        "confidence": decision_json.get("compliance_confidence"),
        "reason_codes": decision_json.get("compliance_reason_codes"),
        "policy_flags": decision_json.get("compliance_policy_flags"),
        "check_passed": decision_json.get("compliance_check_passed"),
    }
    return payload if any(value is not None for value in payload.values()) else None


def _select_latest_ai_compliance_run(
    runs: list[AgentRunEntity],
) -> AgentRunEntity | None:
    candidates = [run for run in runs if (run.agent_type or "").strip().lower() == "ai_compliance"]
    if not candidates:
        return None
    return max(candidates, key=lambda run: run.started_at)


def _select_latest_compliance_guardrail(
    evaluations: list[GuardrailEvaluationEntity],
) -> GuardrailEvaluationEntity | None:
    candidates = [
        evaluation
        for evaluation in evaluations
        if (
            (evaluation.rule_set_version or "").strip().lower() == "compliance_validator_v1"
            or str(evaluation.rule_results.get("validator_bundle") or "").strip().lower()
            == "compliance_validator_v1"
        )
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda evaluation: evaluation.evaluated_at)


def _build_compliance_inspection(
    decision_json: dict[str, object] | None,
    ai_compliance_run: AgentRunEntity | None,
    compliance_evaluation: GuardrailEvaluationEntity | None,
) -> dict[str, object] | None:
    ai_projection = _extract_ai_compliance_projection(decision_json)
    ai_check_passed = None
    if ai_projection is not None:
        raw_ai_check_passed = ai_projection.get("check_passed")
        if isinstance(raw_ai_check_passed, bool):
            ai_check_passed = raw_ai_check_passed

    deterministic_check_passed = (
        compliance_evaluation.overall_passed if compliance_evaluation is not None else None
    )

    stored_alignment = None
    if compliance_evaluation is not None:
        candidate_alignment = compliance_evaluation.rule_results.get("ai_compliance_alignment")
        if isinstance(candidate_alignment, dict):
            stored_alignment = candidate_alignment

    agreement_status = "unavailable"
    if isinstance(stored_alignment, dict):
        agreement_status = str(stored_alignment.get("agreement_status") or "unavailable")
    elif ai_check_passed is not None and deterministic_check_passed is not None:
        agreement_status = "aligned" if ai_check_passed == deterministic_check_passed else "conflict"
    elif ai_check_passed is not None:
        agreement_status = "ai_only"
    elif deterministic_check_passed is not None:
        agreement_status = "deterministic_only"

    ai_agent_run_payload: dict[str, object] | None = None
    if ai_compliance_run is not None:
        ai_agent_run_payload = {
            "agent_run_id": str(ai_compliance_run.agent_run_id),
            "agent_type": ai_compliance_run.agent_type,
            "status": ai_compliance_run.status,
            "started_at": ai_compliance_run.started_at.isoformat(),
            "completed_at": (
                ai_compliance_run.completed_at.isoformat()
                if ai_compliance_run.completed_at is not None
                else None
            ),
            "structured_output_json": ai_compliance_run.structured_output_json,
        }

    deterministic_payload: dict[str, object] | None = None
    if compliance_evaluation is not None:
        deterministic_payload = {
            "guardrail_evaluation_id": str(compliance_evaluation.guardrail_evaluation_id),
            "rule_set_version": compliance_evaluation.rule_set_version,
            "validator_bundle": compliance_evaluation.rule_results.get("validator_bundle"),
            "overall_passed": compliance_evaluation.overall_passed,
            "evaluated_at": compliance_evaluation.evaluated_at.isoformat(),
            "blocking_rule_codes": compliance_evaluation.blocking_rule_codes,
            "warning_rule_codes": compliance_evaluation.warning_rule_codes,
            "ai_compliance_alignment": stored_alignment,
            "rule_results": compliance_evaluation.rule_results,
        }

    if ai_projection is None and ai_agent_run_payload is None and deterministic_payload is None:
        return None

    return {
        "agreement_status": agreement_status,
        "ai_projection": ai_projection,
        "ai_agent_run": ai_agent_run_payload,
        "deterministic_validator": deterministic_payload,
    }


_REVERSE_TRADE_STOP_REASONS = {
    "reverse_trade_same_signal_feature_snapshot",
    "reverse_trade_single_share_blocked",
    "same_symbol_reentry_cooldown",
    "held_position_recent_buy_sell_cooldown",
    "held_position_recent_risk_sell_cooldown",
}

_PROBE_CHURN_STOP_REASONS = {
    "probe_churn_single_share_blocked",
    "overlay_single_share_buy_blocked",
}

_HOLDING_PROFILE_STOP_REASONS = {
    "holding_profile_earliest_reduce_guard",
    "holding_profile_earliest_reentry_guard",
}


def _build_decision_inspection(
    decision_json: dict[str, object] | None,
    *,
    latest_stop_reason: str | None,
    latest_stop_phase: str | None,
    execution_status: str | None,
) -> dict[str, object] | None:
    if not isinstance(decision_json, dict):
        decision_json = {}

    holding_profile_policy = (
        dict(decision_json.get("holding_profile_policy"))
        if isinstance(decision_json.get("holding_profile_policy"), dict)
        else None
    )
    expected_value_anchor = (
        dict(decision_json.get("expected_value_anchor"))
        if isinstance(decision_json.get("expected_value_anchor"), dict)
        else None
    )

    normalized_stop_reason = str(latest_stop_reason or "").strip().lower() or None
    normalized_stop_phase = str(latest_stop_phase or "").strip() or None

    holding_profile_payload: dict[str, object] | None = None
    if holding_profile_policy is not None:
        metadata = (
            dict(holding_profile_policy.get("metadata"))
            if isinstance(holding_profile_policy.get("metadata"), dict)
            else {}
        )
        holding_profile_payload = {
            "holding_profile": holding_profile_policy.get("holding_profile"),
            "minimum_hold_until": holding_profile_policy.get("minimum_hold_until"),
            "earliest_reduce_at": holding_profile_policy.get("earliest_reduce_at"),
            "earliest_reentry_at": holding_profile_policy.get("earliest_reentry_at"),
            "sell_cooldown_until": holding_profile_policy.get("sell_cooldown_until"),
            "reentry_cooldown_until": holding_profile_policy.get("reentry_cooldown_until"),
            "blocked": normalized_stop_reason in _HOLDING_PROFILE_STOP_REASONS,
            "blocking_reason_code": (
                normalized_stop_reason
                if normalized_stop_reason in _HOLDING_PROFILE_STOP_REASONS
                else None
            ),
            "source_type": metadata.get("source_type"),
            "time_horizon": metadata.get("time_horizon"),
        }

    reverse_trade_payload = {
        "blocked": normalized_stop_reason in _REVERSE_TRADE_STOP_REASONS,
        "blocking_reason_code": (
            normalized_stop_reason
            if normalized_stop_reason in _REVERSE_TRADE_STOP_REASONS
            else None
        ),
        "stop_phase": normalized_stop_phase,
        "same_signal_feature_snapshot": (
            normalized_stop_reason == "reverse_trade_same_signal_feature_snapshot"
        ),
        "reentry_edge_improved_vs_last_exit": (
            expected_value_anchor.get("reentry_edge_improved_vs_last_exit")
            if expected_value_anchor is not None
            else None
        ),
        "edge_vs_last_exit_delta_bps": (
            expected_value_anchor.get("edge_vs_last_exit_delta_bps")
            if expected_value_anchor is not None
            else None
        ),
    }

    probe_churn_payload = {
        "blocked": normalized_stop_reason in _PROBE_CHURN_STOP_REASONS,
        "blocking_reason_code": (
            normalized_stop_reason
            if normalized_stop_reason in _PROBE_CHURN_STOP_REASONS
            else None
        ),
        "stop_phase": normalized_stop_phase,
        "single_share_probe": (
            normalized_stop_reason in _PROBE_CHURN_STOP_REASONS
            or normalized_stop_reason == "reverse_trade_single_share_blocked"
        ),
    }

    guardrail_attribution = {
        "execution_status": execution_status,
        "latest_stop_reason": normalized_stop_reason,
        "latest_stop_phase": normalized_stop_phase,
    }

    if (
        holding_profile_payload is None
        and expected_value_anchor is None
        and guardrail_attribution["latest_stop_reason"] is None
    ):
        return None

    return {
        "holding_profile": holding_profile_payload,
        "expected_value_anchor": expected_value_anchor,
        "reverse_trade": reverse_trade_payload,
        "probe_churn": probe_churn_payload,
        "guardrail_attribution": guardrail_attribution,
    }


def _to_detail(
    row: TradeDecisionRow,
    instrument_name: str | None = None,
    compliance_inspection: dict[str, object] | None = None,
) -> TradeDecisionDetail:
    """Convert ``TradeDecisionRow`` to API schema.

    ``TradeDecisionRow`` contains the domain entity plus optional
    ``order_request_id`` and ``order_status`` from a LEFT JOIN.

    ``instrument_name``은 SQL LEFT JOIN으로 미리 resolve된 값을 받아
    N+1 문제를 방지한다.
    """
    d = row.entity
    detail = TradeDecisionDetail(
        trade_decision_id=str(d.trade_decision_id),
        decision_context_id=str(d.decision_context_id),
        decision_type=_safe_enum_str(d.decision_type),
        side=_safe_enum_str(d.side),
        strategy_id=str(d.strategy_id),
        symbol=d.symbol,
        market=d.market,
        entry_style=_safe_enum_str(d.entry_style),
        created_at=d.created_at,
        entry_price=float(d.entry_price) if d.entry_price is not None else None,
        quantity=float(d.quantity) if d.quantity is not None else None,
        max_order_value=float(d.max_order_value) if d.max_order_value is not None else None,
        confidence=float(d.confidence) if d.confidence is not None else None,
        rationale_summary=d.rationale_summary,
        source_type=d.source_type,
        signal_feature_snapshot_id=row.signal_feature_snapshot_id,
        decision_json=d.decision_json,
        instrument_name=instrument_name,
        # 신규 pipeline_stop / order 노출 필드
        order_request_id=str(row.order_request_id) if row.order_request_id else None,
        order_status=row.order_status,
        execution_attempt_status=row.execution_attempt_status,
        phase_trace=_coerce_phase_trace(row.phase_trace),
        # Phase 5: Latest execution attempt summary fields
        latest_execution_attempt_id=row.latest_execution_attempt_id,
        latest_stop_phase=row.latest_stop_phase,
        latest_stop_reason=row.latest_stop_reason,
        latest_completed_at=row.latest_completed_at,
        latest_phase_count=row.latest_phase_count,
    )
    detail.decision_inspection = _build_decision_inspection(
        d.decision_json,
        latest_stop_reason=detail.latest_stop_reason,
        latest_stop_phase=detail.latest_stop_phase,
        execution_status=detail.execution_status,
    )
    detail.compliance_inspection = compliance_inspection
    return detail


async def _resolve_signal_feature_snapshot_ids(
    repos: RepositoryContainer,
    rows: list[TradeDecisionRow],
) -> dict[str, str | None]:
    """Resolve decision_context-level signal feature anchors for trade decisions."""
    resolved: dict[str, str | None] = {}
    seen_context_ids: set[str] = set()
    for row in rows:
        ctx_id = str(row.entity.decision_context_id)
        if ctx_id in seen_context_ids:
            continue
        seen_context_ids.add(ctx_id)
        try:
            decision_context = await repos.decision_contexts.get(row.entity.decision_context_id)
        except Exception:
            decision_context = None
        resolved[ctx_id] = (
            str(decision_context.signal_feature_snapshot_id)
            if decision_context is not None
            and decision_context.signal_feature_snapshot_id is not None
            else None
        )
    return resolved


async def _resolve_compliance_inspection_views(
    repos: RepositoryContainer,
    rows: list[TradeDecisionRow],
) -> dict[str, dict[str, object] | None]:
    resolved: dict[str, dict[str, object] | None] = {}
    seen_context_ids: set[UUID] = set()
    for row in rows:
        context_id = row.entity.decision_context_id
        if context_id in seen_context_ids:
            continue
        seen_context_ids.add(context_id)
        agent_runs = list(await repos.agent_runs.list_by_decision_context(context_id))
        guardrail_evaluations = list(
            await repos.guardrail_evaluations.get_by_decision_context(context_id)
        )
        ai_compliance_run = _select_latest_ai_compliance_run(agent_runs)
        compliance_evaluation = _select_latest_compliance_guardrail(guardrail_evaluations)
        resolved[str(context_id)] = _build_compliance_inspection(
            row.entity.decision_json,
            ai_compliance_run,
            compliance_evaluation,
        )
    return resolved


@router.get("/trade-decisions/watch-diagnostics", response_model=WatchDiagnosticsResponse)
async def get_watch_diagnostics(
    lookback_days: int = Query(default=14, ge=1, le=90),
    sample_limit: int = Query(default=20, ge=1, le=100),
    db=Depends(get_db),
) -> WatchDiagnosticsResponse:
    """Summarize recent WATCH/HOLD distribution and EI metadata.

    This endpoint is intended for backlog items 11/12:
    WATCH absence diagnosis and core+no_event HOLD concentration analysis.
    """
    since_sql = "NOW() - ($1::int * INTERVAL '1 day')"

    summary_row = await db.fetchrow(
        f"""
        SELECT
            COUNT(*)::int AS total_decision_count,
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(td.decision_type::text, '')) = 'hold'
            )::int AS hold_count,
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(td.decision_type::text, '')) = 'watch'
            )::int AS watch_count,
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(td.decision_type::text, '')) = 'watch'
                  AND COALESCE((td.decision_json->>'no_material_events')::boolean, false) = true
            )::int AS no_material_events_watch_count,
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(td.decision_type::text, '')) = 'hold'
                  AND COALESCE((td.decision_json->>'no_material_events')::boolean, false) = true
            )::int AS no_material_events_hold_count
        FROM trading.trade_decisions td
        WHERE td.created_at >= {since_sql}
        """,
        lookback_days,
    )

    source_type_rows = await db.fetch(
        f"""
        SELECT
            COALESCE(td.source_type, 'unknown') AS source_type,
            COUNT(*)::int AS decision_count,
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(td.decision_type::text, '')) = 'watch'
            )::int AS watch_count,
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(td.decision_type::text, '')) = 'hold'
            )::int AS hold_count
        FROM trading.trade_decisions td
        WHERE td.created_at >= {since_sql}
        GROUP BY COALESCE(td.source_type, 'unknown')
        ORDER BY decision_count DESC, source_type ASC
        """,
        lookback_days,
    )

    evidence_strength_rows = await db.fetch(
        f"""
        SELECT
            COALESCE(NULLIF(td.decision_json->>'evidence_strength', ''), 'unknown') AS evidence_strength,
            COUNT(*)::int AS decision_count,
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(td.decision_type::text, '')) = 'watch'
            )::int AS watch_count,
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(td.decision_type::text, '')) = 'hold'
            )::int AS hold_count
        FROM trading.trade_decisions td
        WHERE td.created_at >= {since_sql}
        GROUP BY COALESCE(NULLIF(td.decision_json->>'evidence_strength', ''), 'unknown')
        ORDER BY decision_count DESC, evidence_strength ASC
        """,
        lookback_days,
    )

    reason_code_rows = await db.fetch(
        f"""
        SELECT
            reason_code,
            COUNT(*)::int AS decision_count
        FROM (
            SELECT
                jsonb_array_elements_text(
                    CASE
                        WHEN jsonb_typeof(td.decision_json->'event_reason_codes') = 'array'
                            THEN td.decision_json->'event_reason_codes'
                        ELSE '[]'::jsonb
                    END
                ) AS reason_code
            FROM trading.trade_decisions td
            WHERE td.created_at >= {since_sql}
              AND LOWER(COALESCE(td.decision_type::text, '')) = 'watch'
        ) codes
        GROUP BY reason_code
        ORDER BY decision_count DESC, reason_code ASC
        LIMIT 10
        """,
        lookback_days,
    )

    sample_rows = await db.fetch(
        f"""
        SELECT
            td.trade_decision_id,
            td.symbol,
            td.market,
            COALESCE(td.source_type, 'unknown') AS source_type,
            LOWER(COALESCE(td.decision_type::text, '')) AS decision_type,
            COALESCE(NULLIF(td.decision_json->>'evidence_strength', ''), 'unknown') AS evidence_strength,
            CASE
                WHEN td.decision_json ? 'no_material_events'
                    THEN (td.decision_json->>'no_material_events')::boolean
                ELSE NULL
            END AS no_material_events,
            CASE
                WHEN td.decision_json ? 'detected_event_count'
                    THEN (td.decision_json->>'detected_event_count')::int
                ELSE NULL
            END AS detected_event_count,
            CASE
                WHEN td.decision_json ? 'interpreted_event_count'
                    THEN (td.decision_json->>'interpreted_event_count')::int
                ELSE NULL
            END AS interpreted_event_count,
            NULLIF(td.decision_json->>'event_bias', '') AS event_bias,
            td.rationale_summary,
            td.created_at
        FROM trading.trade_decisions td
        WHERE td.created_at >= {since_sql}
          AND LOWER(COALESCE(td.decision_type::text, '')) IN ('watch', 'hold')
        ORDER BY
            CASE WHEN LOWER(COALESCE(td.decision_type::text, '')) = 'watch' THEN 0 ELSE 1 END,
            td.created_at DESC,
            td.trade_decision_id DESC
        LIMIT $2
        """,
        lookback_days,
        sample_limit,
    )

    total_decision_count = int((summary_row or {}).get("total_decision_count") or 0)
    hold_count = int((summary_row or {}).get("hold_count") or 0)
    watch_count = int((summary_row or {}).get("watch_count") or 0)
    no_material_events_watch_count = int((summary_row or {}).get("no_material_events_watch_count") or 0)
    no_material_events_hold_count = int((summary_row or {}).get("no_material_events_hold_count") or 0)

    return WatchDiagnosticsResponse(
        lookback_days=lookback_days,
        sample_limit=sample_limit,
        total_decision_count=total_decision_count,
        hold_count=hold_count,
        watch_count=watch_count,
        watch_rate=(float(watch_count) / float(total_decision_count) if total_decision_count else 0.0),
        no_material_events_watch_count=no_material_events_watch_count,
        no_material_events_hold_count=no_material_events_hold_count,
        source_type_items=[
            WatchDiagnosticsSourceTypeItem(
                source_type=str(row["source_type"]),
                decision_count=int(row["decision_count"] or 0),
                watch_count=int(row["watch_count"] or 0),
                hold_count=int(row["hold_count"] or 0),
                watch_rate=(
                    float(row["watch_count"] or 0) / float(row["decision_count"])
                    if row["decision_count"]
                    else 0.0
                ),
            )
            for row in source_type_rows
        ],
        evidence_strength_items=[
            WatchDiagnosticsEvidenceStrengthItem(
                evidence_strength=str(row["evidence_strength"]),
                decision_count=int(row["decision_count"] or 0),
                watch_count=int(row["watch_count"] or 0),
                hold_count=int(row["hold_count"] or 0),
                watch_rate=(
                    float(row["watch_count"] or 0) / float(row["decision_count"])
                    if row["decision_count"]
                    else 0.0
                ),
            )
            for row in evidence_strength_rows
        ],
        top_watch_event_reason_codes=[
            WatchDiagnosticsReasonCodeItem(
                reason_code=str(row["reason_code"]),
                decision_count=int(row["decision_count"] or 0),
            )
            for row in reason_code_rows
        ],
        recent_watch_items=[
            WatchDiagnosticsSampleItem(
                trade_decision_id=row["trade_decision_id"],
                symbol=row["symbol"],
                market=row["market"],
                source_type=row["source_type"],
                decision_type=row["decision_type"],
                evidence_strength=row["evidence_strength"],
                no_material_events=row["no_material_events"],
                detected_event_count=row["detected_event_count"],
                interpreted_event_count=row["interpreted_event_count"],
                event_bias=row["event_bias"],
                rationale_summary=row["rationale_summary"],
                created_at=row["created_at"],
            )
            for row in sample_rows
        ],
    )


@router.get(
    "/trade-decisions/candidate-alignment-diagnostics",
    response_model=CandidateAlignmentDiagnosticsResponse,
)
async def get_candidate_alignment_diagnostics(
    lookback_days: int = Query(default=14, ge=1, le=90),
    sample_limit: int = Query(default=20, ge=1, le=100),
    db=Depends(get_db),
) -> CandidateAlignmentDiagnosticsResponse:
    """Summarize deterministic candidate vs final decision alignment."""
    since_sql = "NOW() - ($1::int * INTERVAL '1 day')"
    candidate_expr = (
        "jsonb_typeof(td.decision_json->'candidate_vs_final') = 'object'"
    )

    summary_row = await db.fetchrow(
        f"""
        SELECT
            COUNT(*)::int AS total_decision_count,
            COUNT(*) FILTER (
                WHERE {candidate_expr}
            )::int AS candidate_tracked_count,
            COUNT(*) FILTER (
                WHERE {candidate_expr}
                  AND COALESCE((td.decision_json#>>'{{candidate_vs_final,override_applied}}')::boolean, false) = true
            )::int AS override_applied_count,
            COUNT(*) FILTER (
                WHERE {candidate_expr}
                  AND COALESCE(td.decision_json#>>'{{candidate_vs_final,alignment_status}}', 'unknown') = 'matched'
            )::int AS matched_count
        FROM trading.trade_decisions td
        WHERE td.created_at >= {since_sql}
        """,
        lookback_days,
    )

    alignment_rows = await db.fetch(
        f"""
        SELECT
            COALESCE(td.decision_json#>>'{{candidate_vs_final,alignment_status}}', 'unknown') AS alignment_status,
            COUNT(*)::int AS decision_count
        FROM trading.trade_decisions td
        WHERE td.created_at >= {since_sql}
          AND {candidate_expr}
        GROUP BY COALESCE(td.decision_json#>>'{{candidate_vs_final,alignment_status}}', 'unknown')
        ORDER BY decision_count DESC, alignment_status ASC
        """,
        lookback_days,
    )

    candidate_intent_rows = await db.fetch(
        f"""
        SELECT
            COALESCE(td.decision_json#>>'{{candidate_vs_final,candidate_intent}}', 'unknown') AS intent,
            COUNT(*)::int AS decision_count
        FROM trading.trade_decisions td
        WHERE td.created_at >= {since_sql}
          AND {candidate_expr}
        GROUP BY COALESCE(td.decision_json#>>'{{candidate_vs_final,candidate_intent}}', 'unknown')
        ORDER BY decision_count DESC, intent ASC
        """,
        lookback_days,
    )

    final_intent_rows = await db.fetch(
        f"""
        SELECT
            COALESCE(td.decision_json#>>'{{candidate_vs_final,final_intent}}', 'unknown') AS intent,
            COUNT(*)::int AS decision_count
        FROM trading.trade_decisions td
        WHERE td.created_at >= {since_sql}
          AND {candidate_expr}
        GROUP BY COALESCE(td.decision_json#>>'{{candidate_vs_final,final_intent}}', 'unknown')
        ORDER BY decision_count DESC, intent ASC
        """,
        lookback_days,
    )

    sample_rows = await db.fetch(
        f"""
        SELECT
            td.trade_decision_id,
            td.symbol,
            td.market,
            COALESCE(td.source_type, 'unknown') AS source_type,
            td.decision_json#>>'{{candidate_vs_final,primary_candidate}}' AS primary_candidate,
            td.decision_json#>>'{{candidate_vs_final,candidate_intent}}' AS candidate_intent,
            td.decision_json#>>'{{candidate_vs_final,final_decision_type}}' AS final_decision_type,
            td.decision_json#>>'{{candidate_vs_final,final_intent}}' AS final_intent,
            td.decision_json#>>'{{candidate_vs_final,alignment_status}}' AS alignment_status,
            CASE
                WHEN td.decision_json#>>'{{candidate_vs_final,override_applied}}' IS NOT NULL
                    THEN (td.decision_json#>>'{{candidate_vs_final,override_applied}}')::boolean
                ELSE NULL
            END AS override_applied,
            td.rationale_summary,
            td.created_at
        FROM trading.trade_decisions td
        WHERE td.created_at >= {since_sql}
          AND {candidate_expr}
          AND COALESCE(td.decision_json#>>'{{candidate_vs_final,alignment_status}}', 'unknown') <> 'matched'
        ORDER BY td.created_at DESC, td.trade_decision_id DESC
        LIMIT $2
        """,
        lookback_days,
        sample_limit,
    )

    total_decision_count = int((summary_row or {}).get("total_decision_count") or 0)
    candidate_tracked_count = int((summary_row or {}).get("candidate_tracked_count") or 0)
    override_applied_count = int((summary_row or {}).get("override_applied_count") or 0)
    matched_count = int((summary_row or {}).get("matched_count") or 0)

    return CandidateAlignmentDiagnosticsResponse(
        lookback_days=lookback_days,
        sample_limit=sample_limit,
        total_decision_count=total_decision_count,
        candidate_tracked_count=candidate_tracked_count,
        candidate_missing_count=max(0, total_decision_count - candidate_tracked_count),
        override_applied_count=override_applied_count,
        matched_count=matched_count,
        candidate_coverage_rate=(
            float(candidate_tracked_count) / float(total_decision_count)
            if total_decision_count
            else 0.0
        ),
        match_rate=(
            float(matched_count) / float(candidate_tracked_count)
            if candidate_tracked_count
            else 0.0
        ),
        alignment_status_items=[
            CandidateAlignmentStatusItem(
                alignment_status=str(row["alignment_status"]),
                decision_count=int(row["decision_count"] or 0),
            )
            for row in alignment_rows
        ],
        candidate_intent_items=[
            CandidateIntentDistributionItem(
                intent=str(row["intent"]),
                decision_count=int(row["decision_count"] or 0),
            )
            for row in candidate_intent_rows
        ],
        final_intent_items=[
            CandidateIntentDistributionItem(
                intent=str(row["intent"]),
                decision_count=int(row["decision_count"] or 0),
            )
            for row in final_intent_rows
        ],
        recent_misaligned_items=[
            CandidateAlignmentSampleItem(
                trade_decision_id=row["trade_decision_id"],
                symbol=row["symbol"],
                market=row["market"],
                source_type=row["source_type"],
                primary_candidate=row["primary_candidate"],
                candidate_intent=row["candidate_intent"],
                final_decision_type=row["final_decision_type"],
                final_intent=row["final_intent"],
                alignment_status=row["alignment_status"],
                override_applied=row["override_applied"],
                rationale_summary=row["rationale_summary"],
                created_at=row["created_at"],
            )
            for row in sample_rows
        ],
    )


@router.get("/trade-decisions", response_model=PaginatedTradeDecisionsResponse)
async def list_trade_decisions(
    decision_context_id: str | None = Query(None, description="Decision context ID (optional)"),
    created_date: date | None = Query(None, alias="date", description="KST created_at date filter (YYYY-MM-DD)"),
    side: str | None = Query(None, description="Filter by side"),
    source_type: str | None = Query(None, description="Filter by source_type"),
    decision_type: str | None = Query(None, description="Filter by decision_type"),
    execution_status: str | None = Query(None, description="Filter by derived execution_status"),
    latest_stop_reason: str | None = Query(None, description="Filter by latest stop_reason"),
    latest_stop_reason_prefix: str | None = Query(None, description="Filter by latest stop_reason prefix"),
    has_order: bool | None = Query(None, description="Filter by whether an order was created"),
    limit: int = Query(50, ge=1, le=500, description="페이지당 최대 항목 수"),
    offset: int = Query(0, ge=0, description="건너뛸 항목 수"),
    repos: RepositoryContainer = Depends(get_repos),
) -> PaginatedTradeDecisionsResponse:
    """List trade decisions with server-side pagination.

    ``decision_context_id``가 주어지면 해당 컨텍스트로 필터링.
    ``limit``: 페이지당 최대 항목 수 (기본 50, 최대 500).
    ``offset``: 건너뛸 항목 수 (기본 0).

    SQL LEFT JOIN으로 instrument_name을 한 번에 resolve하여
    N+1 문제를 방지한다.
    """
    ctx_id: UUID | None = None
    if decision_context_id is not None:
        try:
            ctx_id = UUID(decision_context_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid UUID: {decision_context_id}"
            ) from exc

    is_in_memory = type(repos.trade_decisions).__name__.startswith("InMemory")
    if is_in_memory:
        in_memory_order_decision_ids: set[UUID] = set()
        if has_order is not None:
            day_orders = await repos.orders.list(OrderQuery(limit=10000))
            in_memory_order_decision_ids = {
                order.trade_decision_id
                for order in day_orders
                if order.trade_decision_id is not None
            }
        rows, _ = await repos.trade_decisions.list_all_paginated(
            limit=5000,
            offset=0,
            decision_context_id=ctx_id,
            created_date_kst=created_date,
            side=side,
            source_type=source_type,
            decision_type=decision_type,
        )
        filtered_rows: list[TradeDecisionRow] = []
        for row in rows:
            resolved_stop_reason = str(row.latest_stop_reason or "").lower()
            resolved_execution_attempt_status = row.execution_attempt_status
            resolved_latest_execution_attempt_id = row.latest_execution_attempt_id
            resolved_latest_stop_phase = row.latest_stop_phase
            resolved_latest_completed_at = row.latest_completed_at
            resolved_latest_phase_count = row.latest_phase_count
            resolved_phase_trace = row.phase_trace
            if not resolved_stop_reason:
                attempts = await repos.execution_attempts.list_by_trade_decision(
                    row.entity.trade_decision_id
                )
                if attempts:
                    latest_attempt = max(attempts, key=lambda item: item.created_at or item.started_at)
                    resolved_stop_reason = str(latest_attempt.stop_reason or "").lower()
                    resolved_execution_attempt_status = latest_attempt.status
                    resolved_latest_execution_attempt_id = str(latest_attempt.execution_attempt_id)
                    resolved_latest_stop_phase = latest_attempt.stop_phase
                    resolved_latest_completed_at = latest_attempt.completed_at
                    resolved_latest_phase_count = len(latest_attempt.phase_trace or []) or None
                    resolved_phase_trace = latest_attempt.phase_trace
            has_order_resolved = row.order_request_id is not None or (
                row.entity.trade_decision_id in in_memory_order_decision_ids
            )

            if latest_stop_reason is not None and resolved_stop_reason != latest_stop_reason.lower():
                continue
            if latest_stop_reason_prefix is not None and not resolved_stop_reason.startswith(
                latest_stop_reason_prefix.lower()
            ):
                continue
            if has_order is True and not has_order_resolved:
                continue
            if has_order is False and has_order_resolved:
                continue

            filtered_row = TradeDecisionRow(
                entity=row.entity,
                order_request_id=row.order_request_id,
                order_status=row.order_status,
                instrument_name=row.instrument_name,
                phase_trace=resolved_phase_trace,
                execution_attempt_status=resolved_execution_attempt_status,
                latest_execution_attempt_id=resolved_latest_execution_attempt_id,
                latest_stop_phase=resolved_latest_stop_phase,
                latest_stop_reason=resolved_stop_reason or row.latest_stop_reason,
                latest_completed_at=resolved_latest_completed_at,
                latest_phase_count=resolved_latest_phase_count,
            )
            if execution_status is not None:
                derived = _to_detail(filtered_row, instrument_name=row.instrument_name).execution_status
                if (derived or "").lower() != execution_status.lower():
                    continue
            filtered_rows.append(filtered_row)
        total = len(filtered_rows)
        rows = filtered_rows[offset : offset + limit]
    else:
        rows, total = await repos.trade_decisions.list_all_paginated(
            limit=limit,
            offset=offset,
            decision_context_id=ctx_id,
            created_date_kst=created_date,
            side=side,
            source_type=source_type,
            decision_type=decision_type,
            execution_status=execution_status,
            latest_stop_reason=latest_stop_reason,
            latest_stop_reason_prefix=latest_stop_reason_prefix,
            has_order=has_order,
        )

    signal_feature_snapshot_ids = await _resolve_signal_feature_snapshot_ids(repos, rows)
    compliance_inspection_views = await _resolve_compliance_inspection_views(repos, rows)

    # SQL LEFT JOIN으로 instrument_name이 이미 TradeDecisionRow.instrument_name에
    # resolve되어 있음
    details = []
    for row in rows:
        details.append(
            _to_detail(
                TradeDecisionRow(
                    entity=row.entity,
                    order_request_id=row.order_request_id,
                    order_status=row.order_status,
                    instrument_name=row.instrument_name,
                    phase_trace=row.phase_trace,
                    execution_attempt_status=row.execution_attempt_status,
                    latest_execution_attempt_id=row.latest_execution_attempt_id,
                    latest_stop_phase=row.latest_stop_phase,
                    latest_stop_reason=row.latest_stop_reason,
                    latest_completed_at=row.latest_completed_at,
                    latest_phase_count=row.latest_phase_count,
                    signal_feature_snapshot_id=signal_feature_snapshot_ids.get(
                        str(row.entity.decision_context_id)
                    ),
                ),
                instrument_name=row.instrument_name,
                compliance_inspection=compliance_inspection_views.get(
                    str(row.entity.decision_context_id)
                ),
            )
        )

    return PaginatedTradeDecisionsResponse(
        items=details,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/decision-contexts/{decision_context_id}", response_model=DecisionContextDetail)
async def get_decision_context(
    decision_context_id: str,
    repos: RepositoryContainer = Depends(get_repos),
) -> DecisionContextDetail:
    """Get a single decision context by ID."""
    try:
        uid = UUID(decision_context_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {decision_context_id}") from exc

    ctx = await repos.decision_contexts.get(uid)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Decision context not found: {decision_context_id}")

    return DecisionContextDetail(
        decision_context_id=str(ctx.decision_context_id),
        account_id=str(ctx.account_id),
        strategy_id=str(ctx.strategy_id),
        config_version_id=str(ctx.config_version_id),
        market_timestamp=ctx.market_timestamp,
        correlation_id=ctx.correlation_id,
        trading_session_id=str(ctx.trading_session_id) if ctx.trading_session_id is not None else None,
        signal_feature_snapshot_id=(
            str(ctx.signal_feature_snapshot_id)
            if ctx.signal_feature_snapshot_id is not None
            else None
        ),
        created_at=ctx.created_at,
    )
