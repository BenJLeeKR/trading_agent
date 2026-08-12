"""Decision inspection endpoints: ``GET /trade-decisions``,
``GET /decision-contexts/{id}``.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_db, get_repos
from agent_trading.api.schemas import (
    CandidateAlignmentDiagnosticsResponse,
    CandidateAlignmentSampleItem,
    CandidateAlignmentStatusItem,
    CandidateIntentDistributionItem,
    DecisionContextDetail,
    LossCutShadowByInstrumentItem,
    LossCutShadowByInstrumentResponse,
    LossCutShadowCountItem,
    LossCutShadowDailyItem,
    LossCutShadowDailyResponse,
    LossCutShadowFirstEventLatencyResponse,
    LossCutShadowMissingCauseBreakdownItem,
    LossCutShadowMissingFirstEventCausesResponse,
    LossCutShadowMissingGroupBreakdownItem,
    LossCutShadowMissingSamplesResponse,
    LossCutShadowMissingSampleView,
    LossCutShadowQueueWritePathSuspectedByInstrumentItem,
    LossCutShadowQueueWritePathSuspectedGroupBreakdownItem,
    LossCutShadowQueueWritePathSuspectedLatencyBucketItem,
    LossCutShadowQueueWritePathSuspectedTimelineItem,
    LossCutShadowQueueWritePathSuspectedTimelinesResponse,
    LossCutShadowQueueWritePathSuspectedTimelineSummaryResponse,
    LossCutShadowRecomputeCrossCheckResponse,
    LossCutShadowRecomputeCrossCheckSampleView,
    LossCutShadowRecomputeMissingQueueCausesResponse,
    LossCutShadowRecomputeMissingQueueGroupBreakdownItem,
    LossCutShadowRecomputeMissingQueueSampleView,
    LossCutShadowSampleView,
    LossCutShadowSamplesResponse,
    LossCutShadowSummaryResponse,
    LossCutShadowTimelineRealizedEventView,
    LossCutShadowTimelineResponse,
    LossCutShadowTimelineSampleView,
    PaginatedTradeDecisionsResponse,
    TradeDecisionDetail,
    WatchDiagnosticsEvidenceStrengthItem,
    WatchDiagnosticsReasonCodeItem,
    WatchDiagnosticsResponse,
    WatchDiagnosticsSampleItem,
    WatchDiagnosticsSourceTypeItem,
)
from agent_trading.domain.entities import (
    AgentRunEntity,
    GuardrailEvaluationEntity,
    PositionCostBasisStateEntity,
)
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
    """Resolve decision_context-level signal feature anchors for trade decisions.

    Uses a single batch lookup (``get_many``) instead of one query per unique
    ``decision_context_id`` — Postgres repos share one tx-bound connection per
    request, so N per-row queries can't be parallelized away; the only way to
    avoid the per-row round trip is to cut the query count itself.
    """
    unique_context_ids = list({row.entity.decision_context_id for row in rows})
    contexts_by_id = await repos.decision_contexts.get_many(unique_context_ids)
    resolved: dict[str, str | None] = {}
    for ctx_id in unique_context_ids:
        decision_context = contexts_by_id.get(ctx_id)
        resolved[str(ctx_id)] = (
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
    """Unique context별 compliance inspection 조회 — batch lookup 2회로
    처리한다(위 함수와 동일한 이유: 쿼리 횟수 자체를 줄여야 한다)."""
    # decision_json은 row마다 다를 수 있으므로 context_id별 첫 row를 대표로 쓴다
    # (기존 순차 루프도 seen_context_ids로 첫 등장 row만 사용했으므로 동일한 동작).
    first_row_by_context: dict[UUID, TradeDecisionRow] = {}
    for row in rows:
        first_row_by_context.setdefault(row.entity.decision_context_id, row)

    context_ids = list(first_row_by_context.keys())
    # compliance inspection은 "ai_compliance" 타입 run만 쓰므로(아래
    # _select_latest_ai_compliance_run), SQL에서 그 타입만 필터링해 불필요한
    # agent_type(및 그 큰 structured_output_json)까지 끌어오지 않는다.
    agent_runs_by_context = await repos.agent_runs.list_by_decision_contexts(
        context_ids, agent_type="ai_compliance"
    )
    guardrail_evals_by_context = await repos.guardrail_evaluations.get_by_decision_contexts(
        context_ids
    )

    resolved: dict[str, dict[str, object] | None] = {}
    for context_id, row in first_row_by_context.items():
        agent_runs = agent_runs_by_context.get(context_id, [])
        guardrail_evaluations = guardrail_evals_by_context.get(context_id, [])
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


_LOSS_CUT_SHADOW_SAMPLES_DEFAULT_LIMIT = 50
_KST = timezone(timedelta(hours=9))


def _parse_query_uuid(value: str, *, field: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid {field} UUID: {value}"
        ) from exc


@router.get(
    "/trade-decisions/loss-cut-shadow/summary",
    response_model=LossCutShadowSummaryResponse,
)
async def get_loss_cut_shadow_summary(
    account_id: str = Query(..., description="Account UUID"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD, KST)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD, KST)"),
    source_type: str | None = Query(None, description="Optional source_type filter"),
    triggered: bool | None = Query(None, description="Optional triggered filter"),
    repos: RepositoryContainer = Depends(get_repos),
) -> LossCutShadowSummaryResponse:
    """계좌×기간 기준 loss-cut shadow 관측 현황 요약.

    ``trade_decisions.decision_json.loss_cut_shadow``에 이미 기록된
    값을 그대로 읽어 건수만 센다 — 손실률/트리거 여부를 다시 계산하지
    않는다(shadow 계산 자체는 ``decision_orchestrator.py``의
    ``_record_loss_cut_shadow_observation()``에서만 일어난다). shadow는
    실주문 결정에 개입하지 않으므로, 이 endpoint 자체도 어떤 결정/주문
    경로도 건드리지 않는 순수 read-only 집계다.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be on or before end_date"
        )
    aid = _parse_query_uuid(account_id, field="account_id")

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        triggered=triggered,
        limit=None,
    )

    total = len(rows)
    triggered_count = 0
    soft_count = 0
    hard_count = 0
    shadow_only_count = 0
    source_type_counter: dict[str, int] = {}
    decision_type_counter: dict[str, int] = {}

    for row in rows:
        shadow = row.loss_cut_shadow
        if shadow.get("triggered") is True:
            triggered_count += 1
        if shadow.get("tier") == "soft":
            soft_count += 1
        elif shadow.get("tier") == "hard":
            hard_count += 1
        if shadow.get("shadow_only") is True:
            shadow_only_count += 1
        source_type_counter[row.source_type] = source_type_counter.get(row.source_type, 0) + 1
        decision_type_counter[row.actual_decision_type] = (
            decision_type_counter.get(row.actual_decision_type, 0) + 1
        )

    return LossCutShadowSummaryResponse(
        account_id=aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        triggered=triggered,
        total_observation_count=total,
        triggered_count=triggered_count,
        soft_trigger_count=soft_count,
        hard_trigger_count=hard_count,
        shadow_only_count=shadow_only_count,
        trigger_rate=(triggered_count / total) if total > 0 else None,
        source_type_counts=[
            LossCutShadowCountItem(key=key, count=count)
            for key, count in sorted(source_type_counter.items())
        ],
        actual_decision_type_counts=[
            LossCutShadowCountItem(key=key, count=count)
            for key, count in sorted(decision_type_counter.items())
        ],
    )


@router.get(
    "/trade-decisions/loss-cut-shadow/daily",
    response_model=LossCutShadowDailyResponse,
)
async def get_loss_cut_shadow_daily(
    account_id: str = Query(..., description="Account UUID"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD, KST)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD, KST)"),
    source_type: str | None = Query(None, description="Optional source_type filter"),
    triggered: bool | None = Query(None, description="Optional triggered filter"),
    repos: RepositoryContainer = Depends(get_repos),
) -> LossCutShadowDailyResponse:
    """계좌×기간 기준 loss-cut shadow 관측을 **날짜별로** 나눠 집계한다.

    ``summary``가 기간 전체를 하나의 숫자로 합산하는 것과 달리, 이
    endpoint는 같은 원시 관측을 ``created_at``의 KST 날짜로 묶어
    날짜별 추이(어느 날 trigger가 몰렸는지, soft/hard 비율이 날짜별로
    어떻게 바뀌는지)를 보여준다. ``summary``와 마찬가지로
    ``list_loss_cut_shadow_observations()``가 반환한 원시 행을 그대로
    집계할 뿐 — 계산은 하지 않는다. 관측이 있었던 날짜만
    ``days``에 포함되고(활동 없는 날짜는 생략), ``source_type``별/
    ``actual_decision_type``별 세부 분포는 응답 크기를 억제하기 위해
    이 endpoint에서는 제공하지 않는다 — 특정 날짜의 세부 분포가
    필요하면 ``summary``를 그 하루로 좁혀 호출하면 된다.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be on or before end_date"
        )
    aid = _parse_query_uuid(account_id, field="account_id")

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        triggered=triggered,
        limit=None,
    )

    grouped: dict[date, list] = {}
    for row in rows:
        trade_date = row.created_at.astimezone(_KST).date()
        grouped.setdefault(trade_date, []).append(row)

    days: list[LossCutShadowDailyItem] = []
    for trade_date in sorted(grouped):
        day_rows = grouped[trade_date]
        total = len(day_rows)
        triggered_count = 0
        soft_count = 0
        hard_count = 0
        shadow_only_count = 0
        for row in day_rows:
            shadow = row.loss_cut_shadow
            if shadow.get("triggered") is True:
                triggered_count += 1
            if shadow.get("tier") == "soft":
                soft_count += 1
            elif shadow.get("tier") == "hard":
                hard_count += 1
            if shadow.get("shadow_only") is True:
                shadow_only_count += 1
        days.append(
            LossCutShadowDailyItem(
                trade_date=trade_date,
                total_observation_count=total,
                triggered_count=triggered_count,
                soft_trigger_count=soft_count,
                hard_trigger_count=hard_count,
                shadow_only_count=shadow_only_count,
                trigger_rate=(triggered_count / total) if total > 0 else None,
            )
        )

    return LossCutShadowDailyResponse(
        account_id=aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        triggered=triggered,
        days=days,
    )


@router.get(
    "/trade-decisions/loss-cut-shadow/by-instrument",
    response_model=LossCutShadowByInstrumentResponse,
)
async def get_loss_cut_shadow_by_instrument(
    account_id: str = Query(..., description="Account UUID"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD, KST)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD, KST)"),
    source_type: str | None = Query(None, description="Optional source_type filter"),
    repos: RepositoryContainer = Depends(get_repos),
) -> LossCutShadowByInstrumentResponse:
    """종목별로 loss-cut shadow 발동 이력과 realized PnL을 나란히 보여준다.

    **교차 조회이지 정답 계산기가 아니다.** shadow 쪽
    (``shadow_triggered_count``/``soft_trigger_count``/
    ``hard_trigger_count``/``latest_shadow_at``)은 이 endpoint가
    지정한 기간 내 ``triggered=true`` 관측만 세고, realized PnL 쪽
    (``realized_pnl_net_sum``/``realized_sell_event_count``)은 기존
    ``realized_pnl_daily_aggregates``에 이미 저장된 **전체 기간
    누계**를 그대로 읽는다(기간 필터링 없음 — shadow가 발동한 시점
    이후에 발생한 실현손익까지 보여주는 것이 이 endpoint의 목적이므로
    의도적으로 기간을 묶지 않는다). 두 값 다 이미 저장된 값을 세거나
    합산할 뿐, 새로운 손익/판정 계산은 전혀 하지 않는다. 두 값을
    인과관계로 연결하는 판단(예: "이 손절이 손실을 막았다")은 이
    endpoint가 내리지 않는다 — 사람이 두 값을 나란히 보고 판단하는
    참고 자료다.

    ``triggered=true``인 관측이 1건도 없는 종목은 ``items``에
    나타나지 않는다.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be on or before end_date"
        )
    aid = _parse_query_uuid(account_id, field="account_id")

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        triggered=True,
        limit=None,
    )

    grouped: dict[UUID, list] = {}
    symbols_by_instrument: dict[UUID, str] = {}
    for row in rows:
        instrument_id_raw = row.loss_cut_shadow.get("instrument_id")
        if not instrument_id_raw:
            # triggered=true는 average_price/market_price가 모두 있어야만
            # 나오므로 이 경로는 사실상 발생하지 않는다 — 방어적으로만 skip.
            continue
        iid = UUID(instrument_id_raw)
        grouped.setdefault(iid, []).append(row)
        symbols_by_instrument[iid] = row.symbol

    items: list[LossCutShadowByInstrumentItem] = []
    for iid in sorted(grouped, key=str):
        instrument_rows = grouped[iid]
        soft_count = sum(1 for r in instrument_rows if r.loss_cut_shadow.get("tier") == "soft")
        hard_count = sum(1 for r in instrument_rows if r.loss_cut_shadow.get("tier") == "hard")
        latest_shadow_at = max(r.created_at for r in instrument_rows)

        daily_rows = await repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
            aid, iid
        )
        realized_net_sum = sum(
            (r.realized_pnl_net_sum for r in daily_rows), Decimal("0")
        )
        realized_sell_count = sum(r.sell_event_count for r in daily_rows)

        cost_basis_state = await repos.position_cost_basis_states.get(aid, iid)
        recompute_required = (
            cost_basis_state.recompute_required if cost_basis_state is not None else None
        )

        items.append(
            LossCutShadowByInstrumentItem(
                instrument_id=iid,
                symbol=symbols_by_instrument[iid],
                shadow_triggered_count=len(instrument_rows),
                soft_trigger_count=soft_count,
                hard_trigger_count=hard_count,
                latest_shadow_at=latest_shadow_at,
                realized_pnl_net_sum=realized_net_sum,
                realized_sell_event_count=realized_sell_count,
                recompute_required=recompute_required,
            )
        )

    return LossCutShadowByInstrumentResponse(
        account_id=aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        items=items,
    )


@router.get(
    "/trade-decisions/loss-cut-shadow/samples",
    response_model=LossCutShadowSamplesResponse,
)
async def list_loss_cut_shadow_samples(
    account_id: str = Query(..., description="Account UUID"),
    source_type: str | None = Query(None, description="Optional source_type filter"),
    triggered: bool | None = Query(None, description="Optional triggered filter"),
    tier: str | None = Query(None, description="Optional tier filter (soft|hard)"),
    symbol: str | None = Query(None, description="Optional symbol filter"),
    before: datetime | None = Query(
        None, description="Optional — only observations created before this instant"
    ),
    limit: int = Query(
        _LOSS_CUT_SHADOW_SAMPLES_DEFAULT_LIMIT,
        ge=1,
        le=500,
        description="Maximum observations to return",
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> LossCutShadowSamplesResponse:
    """loss-cut shadow 관측 원시 표본을 ``created_at`` 내림차순으로 나열한다.

    summary만으로는 확인할 수 없는 개별 관측 행(기준 가격, 손실률,
    당시 실제 decision_type 등)을 보기 위한 endpoint다. 이 endpoint도
    ``decision_json.loss_cut_shadow``를 그대로 읽기만 한다.
    """
    aid = _parse_query_uuid(account_id, field="account_id")

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        aid,
        source_type=source_type,
        triggered=triggered,
        tier=tier,
        symbol=symbol,
        before=before,
        limit=limit,
    )

    items: list[LossCutShadowSampleView] = []
    for row in rows:
        shadow = row.loss_cut_shadow
        instrument_id_raw = shadow.get("instrument_id")
        items.append(
            LossCutShadowSampleView(
                trade_decision_id=row.trade_decision_id,
                decision_context_id=row.decision_context_id,
                account_id=row.account_id,
                created_at=row.created_at,
                symbol=row.symbol,
                instrument_id=UUID(instrument_id_raw) if instrument_id_raw else None,
                source_type=row.source_type,
                actual_decision_type=row.actual_decision_type,
                average_price=shadow.get("average_price"),
                market_price=shadow.get("market_price"),
                loss_pct=shadow.get("loss_pct"),
                triggered=shadow.get("triggered"),
                tier=shadow.get("tier"),
                skipped_reason=shadow.get("skipped_reason"),
                shadow_only=shadow.get("shadow_only"),
            )
        )

    return LossCutShadowSamplesResponse(
        account_id=aid,
        limit=limit,
        before=before,
        items=items,
    )


_LOSS_CUT_SHADOW_TIMELINE_DEFAULT_EVENT_LIMIT = 5
_LOSS_CUT_SHADOW_TIMELINE_MAX_EVENT_LIMIT = 50


async def _fetch_realized_events_after_shadow(
    repos: RepositoryContainer,
    *,
    account_id: UUID,
    instrument_id_raw: str | None,
    since: datetime,
    event_limit: int,
) -> list[LossCutShadowTimelineRealizedEventView]:
    """shadow sample 1건 이후 같은 계좌×종목의 realized PnL event를

    시간순으로 가져온다 — 단일 ``.../timeline`` endpoint와 batch
    endpoint(``queue-write-path-suspected-timelines``)가 **반드시
    같은 event 선정 규칙**을 쓰도록 이 함수 하나만 공유한다. 연결
    기준은 ``account_id + instrument_id + fill_timestamp >= since``
    (오름차순, ``event_limit``건까지) — 두 endpoint 사이에 판정
    불일치가 생기지 않게 한다.
    """
    if not instrument_id_raw:
        # skipped_reason이 있는 관측(가격 미확보 등)은 instrument_id가
        # 없을 수 있다 — realized event와 연결할 키가 없으므로 빈
        # 타임라인으로 응답한다(에러 아님, 정상적으로 발생 가능한 상태).
        return []
    instrument_id = UUID(instrument_id_raw)
    events = await repos.realized_pnl_events.list_by_account_and_instrument_since(
        account_id,
        instrument_id,
        since=since,
        limit=event_limit,
    )
    return [
        LossCutShadowTimelineRealizedEventView(
            realized_pnl_event_id=event.realized_pnl_event_id,
            fill_event_id=event.fill_event_id,
            fill_timestamp=event.fill_timestamp,
            sell_quantity=event.sell_quantity,
            sell_price=event.sell_price,
            avg_cost_basis_before=event.avg_cost_basis_before,
            realized_pnl_net=event.realized_pnl_net,
            position_quantity_after=event.position_quantity_after,
            broker_order_id=event.broker_order_id,
            computation_run_id=event.computation_run_id,
            seconds_after_shadow=(event.fill_timestamp - since).total_seconds(),
        )
        for event in events
    ]


@router.get(
    "/trade-decisions/loss-cut-shadow/samples/{trade_decision_id}/timeline",
    response_model=LossCutShadowTimelineResponse,
)
async def get_loss_cut_shadow_sample_timeline(
    trade_decision_id: str,
    account_id: str = Query(..., description="Account UUID (ownership check)"),
    event_limit: int = Query(
        _LOSS_CUT_SHADOW_TIMELINE_DEFAULT_EVENT_LIMIT,
        ge=1,
        le=_LOSS_CUT_SHADOW_TIMELINE_MAX_EVENT_LIMIT,
        description="Maximum realized PnL events to return after the shadow sample",
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> LossCutShadowTimelineResponse:
    """shadow sample 1건과 그 이후 같은 계좌×종목의 realized PnL event를

    시간순으로 나란히 보여준다. **후속 참고 타임라인이지 인과 매칭이
    아니다** — ``realized_events``에 나온 이벤트가 이 shadow sample
    "때문에" 발생했다는 뜻이 아니다. 새 손익 계산이나 새 trigger
    판정은 하지 않는다 — ``trade_decisions.decision_json.loss_cut_
    shadow``와 ``realized_pnl_events``를 그대로 읽어 시간순으로만
    나열한다.

    연결 기준: ``account_id + instrument_id + fill_timestamp >=
    sample.created_at``(오름차순, ``event_limit``건까지). ``account_id``
    쿼리 파라미터는 이 sample이 호출자가 알고 있는 계좌 소유인지
    확인하는 용도다 — 일치하지 않으면 404(다른 계좌의 존재 여부를
    노출하지 않기 위해 403이 아니라 404).
    """
    td_id = _parse_query_uuid(trade_decision_id, field="trade_decision_id")
    aid = _parse_query_uuid(account_id, field="account_id")

    decision = await repos.trade_decisions.get(td_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="trade_decision not found")

    shadow = (decision.decision_json or {}).get("loss_cut_shadow")
    if shadow is None:
        raise HTTPException(
            status_code=404,
            detail="no loss_cut_shadow observation recorded for this trade_decision_id",
        )

    context = await repos.decision_contexts.get(decision.decision_context_id)
    if context is None or context.account_id != aid:
        raise HTTPException(status_code=404, detail="trade_decision not found")

    instrument_id_raw = shadow.get("instrument_id")
    realized_events = await _fetch_realized_events_after_shadow(
        repos,
        account_id=aid,
        instrument_id_raw=instrument_id_raw,
        since=decision.created_at,
        event_limit=event_limit,
    )

    sample = LossCutShadowTimelineSampleView(
        trade_decision_id=decision.trade_decision_id,
        account_id=aid,
        decision_context_id=decision.decision_context_id,
        symbol=decision.symbol,
        instrument_id=UUID(instrument_id_raw) if instrument_id_raw else None,
        created_at=decision.created_at,
        source_type=decision.source_type or "unknown",
        actual_decision_type=_safe_enum_str(decision.decision_type),
        triggered=shadow.get("triggered"),
        tier=shadow.get("tier"),
        loss_pct=shadow.get("loss_pct"),
        average_price=shadow.get("average_price"),
        market_price=shadow.get("market_price"),
        shadow_only=shadow.get("shadow_only"),
    )

    return LossCutShadowTimelineResponse(
        sample=sample,
        realized_events=realized_events,
        realized_event_limit=event_limit,
    )


@router.get(
    "/trade-decisions/loss-cut-shadow/first-realized-event-latency",
    response_model=LossCutShadowFirstEventLatencyResponse,
)
async def get_loss_cut_shadow_first_realized_event_latency(
    account_id: str = Query(..., description="Account UUID"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD, KST)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD, KST)"),
    source_type: str | None = Query(None, description="Optional source_type filter"),
    tier: str | None = Query(None, description="Optional tier filter (soft|hard)"),
    repos: RepositoryContainer = Depends(get_repos),
) -> LossCutShadowFirstEventLatencyResponse:
    """``triggered=true`` shadow sample 이후 첫 realized event까지의

    지연(초) 분포를 낸다. **후속 사건 지연 분포이지 정책 효과
    판정기가 아니다** — 지연이 짧다/길다는 사실 자체가 shadow의
    적중 여부를 뜻하지 않는다. 모집단은 항상 ``triggered=true``인
    sample로 고정한다(``triggered=false`` sample에는 "이후 첫
    event"를 물을 이유가 없다). 각 sample마다
    ``realized_pnl_events.list_by_account_and_instrument_since(
    since=sample.created_at, limit=1)``로 가장 먼저 발생한 event
    1건만 가져온다 — ``timeline`` endpoint와 동일한 조회를 표본
    전체에 반복해 분포만 집계할 뿐, 새 계산/판정은 없다.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be on or before end_date"
        )
    aid = _parse_query_uuid(account_id, field="account_id")

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        triggered=True,
        limit=None,
    )

    sample_count = len(rows)
    latencies_seconds: list[float] = []
    first_event_pnl_nets: list[Decimal] = []
    missing_count = 0

    for row in rows:
        instrument_id_raw = row.loss_cut_shadow.get("instrument_id")
        if not instrument_id_raw:
            missing_count += 1
            continue
        events = await repos.realized_pnl_events.list_by_account_and_instrument_since(
            aid,
            UUID(instrument_id_raw),
            since=row.created_at,
            limit=1,
        )
        if not events:
            missing_count += 1
            continue
        first_event = events[0]
        latencies_seconds.append(
            (first_event.fill_timestamp - row.created_at).total_seconds()
        )
        first_event_pnl_nets.append(first_event.realized_pnl_net)

    matched_count = len(latencies_seconds)

    def _median(values: list[float]) -> float | None:
        return statistics.median(values) if values else None

    def _p90(values: list[float]) -> float | None:
        if not values:
            return None
        if len(values) == 1:
            return values[0]
        return statistics.quantiles(values, n=10, method="inclusive")[8]

    def _decimal_avg(values: list[Decimal]) -> Decimal | None:
        return (sum(values, Decimal("0")) / len(values)) if values else None

    def _decimal_median(values: list[Decimal]) -> Decimal | None:
        if not values:
            return None
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2 == 1:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2

    return LossCutShadowFirstEventLatencyResponse(
        account_id=aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        sample_count=sample_count,
        matched_first_event_count=matched_count,
        missing_first_event_count=missing_count,
        missing_first_event_rate=(
            missing_count / sample_count if sample_count > 0 else None
        ),
        latency_seconds_min=min(latencies_seconds) if latencies_seconds else None,
        latency_seconds_max=max(latencies_seconds) if latencies_seconds else None,
        latency_seconds_avg=(
            statistics.fmean(latencies_seconds) if latencies_seconds else None
        ),
        latency_seconds_median=_median(latencies_seconds),
        latency_seconds_p90=_p90(latencies_seconds),
        first_realized_event_pnl_net_avg=_decimal_avg(first_event_pnl_nets),
        first_realized_event_pnl_net_median=_decimal_median(first_event_pnl_nets),
    )


# --- missing-first-event-causes bucket 상수 ---
# precedence: 위에서 아래 순서로 먼저 만족하는 bucket에 배정한다.
_MISSING_CAUSE_INSTRUMENT_LINKAGE = "missing_instrument_linkage"
_MISSING_CAUSE_RECOMPUTE_REQUIRED = "recompute_required"
_MISSING_CAUSE_MISSING_POSITION_STATE = "missing_position_state"
_MISSING_CAUSE_STILL_HOLDING = "still_holding_position"
_MISSING_CAUSE_POSITION_CLOSED_NO_EVENT = "position_closed_but_no_realized_event"
_MISSING_CAUSE_OTHER_UNCLASSIFIED = "other_unclassified"

_MISSING_CAUSE_PRECEDENCE = (
    _MISSING_CAUSE_INSTRUMENT_LINKAGE,
    _MISSING_CAUSE_RECOMPUTE_REQUIRED,
    _MISSING_CAUSE_MISSING_POSITION_STATE,
    _MISSING_CAUSE_STILL_HOLDING,
    _MISSING_CAUSE_POSITION_CLOSED_NO_EVENT,
    _MISSING_CAUSE_OTHER_UNCLASSIFIED,
)


@dataclass(frozen=True, slots=True)
class _MissingCauseClassification:
    """``_classify_missing_first_event_cause()``의 판정 결과.

    ``cost_basis_state``를 함께 담아, 호출자(예: ``missing-first-
    event-samples``)가 ``recompute_required``/``quantity``를 보려고
    같은 조회를 다시 하지 않아도 되게 한다."""

    cause: str
    cost_basis_state: PositionCostBasisStateEntity | None


async def _classify_missing_first_event_cause(
    repos: RepositoryContainer,
    *,
    account_id: UUID,
    instrument_id_raw: str | None,
) -> _MissingCauseClassification:
    """missing 표본 1건의 원인 bucket을 판정한다(읽기 전용, 판단 없음).

    ``missing-first-event-causes``와 ``missing-first-event-samples``
    endpoint가 **반드시 같은 판정 규칙**을 쓰도록 이 함수 하나만
    공유한다 — 두 endpoint가 각자 판정 로직을 중복 구현하면 미묘하게
    달라질 위험이 있어, 이 함수를 유일한 판정 지점으로 둔다.

    precedence(위에서부터 먼저 만족하는 것으로 확정):

    1. ``missing_instrument_linkage`` — shadow payload에 ``instrument_id``
       가 없어(구형 관측 등) 이후 어떤 조회도 할 근거가 없음.
    2. ``recompute_required`` — ``position_cost_basis_state.recompute_
       required is True``. ledger 자체가 신뢰 불가 상태이므로, quantity
       기준 보유 여부 판단(3/4)보다 **먼저** 이 상태를 알려야 한다는
       판단 — recompute_required가 True인 상태에서 quantity를 보고
       "청산됐다/보유 중이다"라고 단정하면 잘못된 결론으로 이어질 수
       있다.
    3. ``missing_position_state`` — 계좌×종목 ``position_cost_basis_
       state``가 아예 없음(한 번도 ledger에 반영된 적 없음) — 보유
       여부를 이 값으로는 판단할 수 없다.
    4. ``still_holding_position`` — ``quantity > 0``(ledger 기준 아직
       보유 중) — 아직 청산이 안 됐으니 realized event가 없는 것이
       자연스럽다.
    5. ``position_closed_but_no_realized_event`` — ``quantity <= 0``
       (ledger 기준 이미 청산됨)인데 realized event가 안 보임 — ledger/
       recompute 누락 가능성, 데이터 정합성 의심 신호.
    6. ``other_unclassified`` — 위 어느 것도 명확히 해당하지 않음(코드
       경로상 도달 가능성은 낮지만, 애매한 값을 억지로 분류하지 않기
       위한 안전망).
    """
    if not instrument_id_raw:
        return _MissingCauseClassification(
            cause=_MISSING_CAUSE_INSTRUMENT_LINKAGE, cost_basis_state=None
        )

    instrument_id = UUID(instrument_id_raw)
    cost_basis_state = await repos.position_cost_basis_states.get(
        account_id, instrument_id
    )
    if cost_basis_state is None:
        return _MissingCauseClassification(
            cause=_MISSING_CAUSE_MISSING_POSITION_STATE, cost_basis_state=None
        )
    if cost_basis_state.recompute_required:
        cause = _MISSING_CAUSE_RECOMPUTE_REQUIRED
    elif cost_basis_state.quantity > 0:
        cause = _MISSING_CAUSE_STILL_HOLDING
    elif cost_basis_state.quantity <= 0:
        cause = _MISSING_CAUSE_POSITION_CLOSED_NO_EVENT
    else:
        cause = _MISSING_CAUSE_OTHER_UNCLASSIFIED
    return _MissingCauseClassification(cause=cause, cost_basis_state=cost_basis_state)


def _build_group_breakdown(
    sample_counter: dict[str, int], missing_counter: dict[str, int]
) -> list[LossCutShadowMissingGroupBreakdownItem]:
    items: list[LossCutShadowMissingGroupBreakdownItem] = []
    for key in sorted(sample_counter):
        total = sample_counter[key]
        missing = missing_counter.get(key, 0)
        items.append(
            LossCutShadowMissingGroupBreakdownItem(
                group_value=key,
                sample_count=total,
                missing_first_event_count=missing,
                missing_first_event_rate=(missing / total) if total > 0 else None,
            )
        )
    return items


@router.get(
    "/trade-decisions/loss-cut-shadow/missing-first-event-causes",
    response_model=LossCutShadowMissingFirstEventCausesResponse,
)
async def get_loss_cut_shadow_missing_first_event_causes(
    account_id: str = Query(..., description="Account UUID"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD, KST)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD, KST)"),
    source_type: str | None = Query(None, description="Optional source_type filter"),
    tier: str | None = Query(None, description="Optional tier filter (soft|hard)"),
    repos: RepositoryContainer = Depends(get_repos),
) -> LossCutShadowMissingFirstEventCausesResponse:
    """first realized event가 안 잡힌 shadow sample들을 원인 bucket으로

    분류한다. **원인 분류 inspection이지 인과 확정 도구가 아니다** —
    각 bucket은 이미 저장된 값(shadow payload/``position_cost_basis_
    state``/realized event 존재 여부)만으로 코드상 재현 가능한 규칙
    으로 분류한 것이고, 새로운 매매 판단이나 causality 해석은 하지
    않는다. ``first-realized-event-latency``와 동일하게 모집단은
    ``triggered=true`` sample로 고정한다(``triggered=false``에는
    "이후 첫 event"를 물을 이유가 없다). bucket precedence는
    ``_classify_missing_first_event_cause()`` docstring 참고.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be on or before end_date"
        )
    aid = _parse_query_uuid(account_id, field="account_id")

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        triggered=True,
        limit=None,
    )

    sample_count = len(rows)
    cause_counts: dict[str, int] = {cause: 0 for cause in _MISSING_CAUSE_PRECEDENCE}

    source_type_sample_counts: dict[str, int] = {}
    source_type_missing_counts: dict[str, int] = {}
    tier_sample_counts: dict[str, int] = {}
    tier_missing_counts: dict[str, int] = {}
    decision_type_sample_counts: dict[str, int] = {}
    decision_type_missing_counts: dict[str, int] = {}

    missing_count = 0

    for row in rows:
        group_source_type = row.source_type
        group_tier = row.loss_cut_shadow.get("tier") or "none"
        group_decision_type = row.actual_decision_type

        source_type_sample_counts[group_source_type] = (
            source_type_sample_counts.get(group_source_type, 0) + 1
        )
        tier_sample_counts[group_tier] = tier_sample_counts.get(group_tier, 0) + 1
        decision_type_sample_counts[group_decision_type] = (
            decision_type_sample_counts.get(group_decision_type, 0) + 1
        )

        instrument_id_raw = row.loss_cut_shadow.get("instrument_id")
        is_missing = True
        if instrument_id_raw:
            events = await repos.realized_pnl_events.list_by_account_and_instrument_since(
                aid,
                UUID(instrument_id_raw),
                since=row.created_at,
                limit=1,
            )
            is_missing = not events

        if not is_missing:
            continue

        missing_count += 1
        source_type_missing_counts[group_source_type] = (
            source_type_missing_counts.get(group_source_type, 0) + 1
        )
        tier_missing_counts[group_tier] = tier_missing_counts.get(group_tier, 0) + 1
        decision_type_missing_counts[group_decision_type] = (
            decision_type_missing_counts.get(group_decision_type, 0) + 1
        )

        classification = await _classify_missing_first_event_cause(
            repos, account_id=aid, instrument_id_raw=instrument_id_raw
        )
        cause_counts[classification.cause] += 1

    cause_breakdown = [
        LossCutShadowMissingCauseBreakdownItem(
            cause=cause,
            count=cause_counts[cause],
            rate=(cause_counts[cause] / missing_count) if missing_count > 0 else 0.0,
        )
        for cause in _MISSING_CAUSE_PRECEDENCE
    ]

    return LossCutShadowMissingFirstEventCausesResponse(
        account_id=aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        sample_count=sample_count,
        missing_first_event_count=missing_count,
        missing_first_event_rate=(
            missing_count / sample_count if sample_count > 0 else None
        ),
        cause_breakdown=cause_breakdown,
        by_source_type=_build_group_breakdown(
            source_type_sample_counts, source_type_missing_counts
        ),
        by_tier=_build_group_breakdown(tier_sample_counts, tier_missing_counts),
        by_decision_type=_build_group_breakdown(
            decision_type_sample_counts, decision_type_missing_counts
        ),
    )


_LOSS_CUT_SHADOW_MISSING_SAMPLES_DEFAULT_LIMIT = 50


@router.get(
    "/trade-decisions/loss-cut-shadow/missing-first-event-samples",
    response_model=LossCutShadowMissingSamplesResponse,
)
async def list_loss_cut_shadow_missing_first_event_samples(
    account_id: str = Query(..., description="Account UUID"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD, KST)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD, KST)"),
    source_type: str | None = Query(None, description="Optional source_type filter"),
    tier: str | None = Query(None, description="Optional tier filter (soft|hard)"),
    cause: str | None = Query(
        None,
        description=(
            "Optional cause bucket filter — one of: "
            + ", ".join(_MISSING_CAUSE_PRECEDENCE)
        ),
    ),
    before: datetime | None = Query(
        None, description="Optional — only samples created before this instant"
    ),
    limit: int = Query(
        _LOSS_CUT_SHADOW_MISSING_SAMPLES_DEFAULT_LIMIT,
        ge=1,
        le=500,
        description="Maximum samples to return",
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> LossCutShadowMissingSamplesResponse:
    """first realized event가 안 잡힌 shadow sample들을 개별 행으로

    나열한다(``missing-first-event-causes``의 drilldown). **개별
    사례 inspection이지 인과 확정 도구가 아니다.**

    ``cause``는 ``missing-first-event-causes``와 **완전히 동일한**
    판정 함수(``_classify_missing_first_event_cause()``)를 그대로
    재사용해 계산한다 — 판정 규칙이 두 endpoint 사이에서 중복
    구현으로 미묘하게 어긋날 여지를 없앤다. ``cause`` 필터를 주면
    그 bucket에 속한 표본만 남긴다.

    정렬/페이지네이션은 기존 ``samples`` endpoint와 동일하게
    ``created_at`` 내림차순(최신순) + ``before``/``limit`` cursor
    방식을 쓴다 — ``before``는 ``list_loss_cut_shadow_observations()``
    자체의 커서 파라미터를 그대로 전달한다(추가 필터링 없이 repository
    레벨에서 이미 적용됨). missing/cause 판정은 fetch된 행에 대해서만
    수행하므로, ``limit``은 "missing/cause 조건을 만족하는 행" 개수
    기준으로 적용된다 — repository가 반환하는 원시 행 수 기준이
    아니다(missing이 아닌 행은 세지 않는다).
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be on or before end_date"
        )
    if cause is not None and cause not in _MISSING_CAUSE_PRECEDENCE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid cause: {cause}. "
                f"Must be one of: {', '.join(_MISSING_CAUSE_PRECEDENCE)}"
            ),
        )
    aid = _parse_query_uuid(account_id, field="account_id")

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        triggered=True,
        before=before,
        limit=None,
    )

    items: list[LossCutShadowMissingSampleView] = []
    for row in rows:
        if len(items) >= limit:
            break

        shadow = row.loss_cut_shadow
        instrument_id_raw = shadow.get("instrument_id")

        is_missing = True
        if instrument_id_raw:
            events = await repos.realized_pnl_events.list_by_account_and_instrument_since(
                aid,
                UUID(instrument_id_raw),
                since=row.created_at,
                limit=1,
            )
            is_missing = not events
        if not is_missing:
            continue

        classification = await _classify_missing_first_event_cause(
            repos, account_id=aid, instrument_id_raw=instrument_id_raw
        )
        if cause is not None and classification.cause != cause:
            continue

        cost_basis_state = classification.cost_basis_state
        items.append(
            LossCutShadowMissingSampleView(
                trade_decision_id=row.trade_decision_id,
                created_at=row.created_at,
                symbol=row.symbol,
                instrument_id=UUID(instrument_id_raw) if instrument_id_raw else None,
                source_type=row.source_type,
                actual_decision_type=row.actual_decision_type,
                tier=shadow.get("tier"),
                triggered=shadow.get("triggered"),
                loss_pct=shadow.get("loss_pct"),
                shadow_only=shadow.get("shadow_only"),
                cause=classification.cause,
                recompute_required=(
                    cost_basis_state.recompute_required
                    if cost_basis_state is not None
                    else None
                ),
                position_quantity=(
                    cost_basis_state.quantity if cost_basis_state is not None else None
                ),
                has_first_realized_event=False,
            )
        )

    return LossCutShadowMissingSamplesResponse(
        account_id=aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        cause=cause,
        limit=limit,
        before=before,
        items=items,
    )


# 큐 전체를 스캔하는 기본 깊이 — `/performance/realized-pnl/recompute-queue`
# (realized_pnl.py)의 `_DEFAULT_RECOMPUTE_QUEUE_LIMIT`과 동일한 값·동일한
# 한계(계좌 필터가 없는 `list_pending()`을 애플리케이션 레벨에서 필터링)를
# 그대로 따른다.
_LOSS_CUT_SHADOW_RECOMPUTE_QUEUE_SCAN_LIMIT = 100
_LOSS_CUT_SHADOW_RECOMPUTE_CROSS_CHECK_DEFAULT_LIMIT = 50


@router.get(
    "/trade-decisions/loss-cut-shadow/missing-first-event-recompute-cross-check",
    response_model=LossCutShadowRecomputeCrossCheckResponse,
)
async def get_loss_cut_shadow_missing_first_event_recompute_cross_check(
    account_id: str = Query(..., description="Account UUID"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD, KST)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD, KST)"),
    source_type: str | None = Query(None, description="Optional source_type filter"),
    tier: str | None = Query(None, description="Optional tier filter (soft|hard)"),
    before: datetime | None = Query(
        None, description="Optional — only samples created before this instant"
    ),
    limit: int = Query(
        _LOSS_CUT_SHADOW_RECOMPUTE_CROSS_CHECK_DEFAULT_LIMIT,
        ge=1,
        le=500,
        description="Maximum samples to return",
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> LossCutShadowRecomputeCrossCheckResponse:
    """missing-first-event sample들과 realized PnL recompute queue를

    ``account_id + instrument_id`` 기준으로 나란히 대사(reconciliation)
    한다. **운영 대사 inspection이지 인과 확정 도구가 아니다** —
    ``trade_decision_id``와 특정 queue 항목을 1:1로 인과 매칭하지
    않는다. ``recompute_required``(``position_cost_basis_state``,
    sample 관점)와 ``queue_pending``(``realized_pnl_recompute_
    queue``, 큐 관점)는 서로 다른 축이라 항상 같이 움직이지 않을 수
    있다 — 이 둘이 어긋나는 케이스(``queue_pending_missing_count``/
    ``queue_pending_extra_count``)를 드러내는 것이 이 endpoint의
    핵심 목적이다.

    모집단은 ``missing-first-event-samples``와 동일하다(``triggered=
    true``이고 first realized event가 없는 sample 전체, cause로
    필터링하지 않음 — recompute_required가 아닌 cause에서도 queue
    pending이 걸려 있는지 보려면 cause를 좁히면 안 되기 때문이다).
    cause 판정은 ``_classify_missing_first_event_cause()``를 그대로
    재사용한다. 정렬/페이지네이션은 ``missing-first-event-samples``
    와 동일하게 ``created_at`` 내림차순 + ``before``/``limit``.

    queue 쪽은 ``realized_pnl_recompute_queue.list_pending()``이
    계좌 필터를 지원하지 않으므로(``/performance/realized-pnl/
    recompute-queue``와 동일한 한계), 최근
    ``_LOSS_CUT_SHADOW_RECOMPUTE_QUEUE_SCAN_LIMIT``건을 스캔한 뒤
    애플리케이션 레벨에서 ``account_id + instrument_id``로 필터링한다
    — 큐 전체 미해결 건수가 이 스캔 깊이를 넘으면 오래된 pending
    항목을 놓칠 수 있다(기존 recompute-queue endpoint와 동일한
    한계, 새로 만든 제약이 아니다).
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be on or before end_date"
        )
    aid = _parse_query_uuid(account_id, field="account_id")

    queue_items = await repos.realized_pnl_recompute_queue.list_pending(
        limit=_LOSS_CUT_SHADOW_RECOMPUTE_QUEUE_SCAN_LIMIT
    )
    queue_by_instrument: dict[UUID, list] = {}
    for queue_item in queue_items:
        if queue_item.account_id != aid:
            continue
        queue_by_instrument.setdefault(queue_item.instrument_id, []).append(queue_item)

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        triggered=True,
        before=before,
        limit=None,
    )

    sample_count = 0
    queue_pending_match_count = 0
    queue_pending_missing_count = 0
    queue_pending_extra_count = 0
    items: list[LossCutShadowRecomputeCrossCheckSampleView] = []

    for row in rows:
        shadow = row.loss_cut_shadow
        instrument_id_raw = shadow.get("instrument_id")

        is_missing = True
        if instrument_id_raw:
            events = await repos.realized_pnl_events.list_by_account_and_instrument_since(
                aid,
                UUID(instrument_id_raw),
                since=row.created_at,
                limit=1,
            )
            is_missing = not events
        if not is_missing:
            continue

        sample_count += 1

        classification = await _classify_missing_first_event_cause(
            repos, account_id=aid, instrument_id_raw=instrument_id_raw
        )
        cost_basis_state = classification.cost_basis_state
        recompute_required = (
            cost_basis_state.recompute_required if cost_basis_state is not None else None
        )

        instrument_id = UUID(instrument_id_raw) if instrument_id_raw else None
        matching_queue_items = (
            queue_by_instrument.get(instrument_id, []) if instrument_id is not None else []
        )
        queue_pending = len(matching_queue_items) > 0

        if recompute_required is True and queue_pending:
            queue_pending_match_count += 1
        elif recompute_required is True and not queue_pending:
            queue_pending_missing_count += 1
        elif recompute_required is not True and queue_pending:
            queue_pending_extra_count += 1

        if len(items) < limit:
            oldest_requested_at = (
                min(
                    (q.requested_at for q in matching_queue_items if q.requested_at is not None),
                    default=None,
                )
                if matching_queue_items
                else None
            )
            reason_codes = sorted({q.reason_code for q in matching_queue_items})
            items.append(
                LossCutShadowRecomputeCrossCheckSampleView(
                    trade_decision_id=row.trade_decision_id,
                    created_at=row.created_at,
                    symbol=row.symbol,
                    instrument_id=instrument_id,
                    source_type=row.source_type,
                    actual_decision_type=row.actual_decision_type,
                    tier=shadow.get("tier"),
                    cause=classification.cause,
                    recompute_required=recompute_required,
                    position_quantity=(
                        cost_basis_state.quantity if cost_basis_state is not None else None
                    ),
                    queue_pending=queue_pending,
                    queue_pending_count=len(matching_queue_items),
                    queue_oldest_requested_at=oldest_requested_at,
                    queue_reason_codes=reason_codes,
                    has_first_realized_event=False,
                )
            )

    match_denominator = queue_pending_match_count + queue_pending_missing_count
    return LossCutShadowRecomputeCrossCheckResponse(
        account_id=aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        sample_count=sample_count,
        queue_pending_match_count=queue_pending_match_count,
        queue_pending_missing_count=queue_pending_missing_count,
        queue_pending_extra_count=queue_pending_extra_count,
        recompute_required_queue_match_rate=(
            queue_pending_match_count / match_denominator if match_denominator > 0 else None
        ),
        limit=limit,
        before=before,
        items=items,
    )


# --- recompute-missing-queue-causes bucket 상수 ---
# precedence: 위에서 아래 순서로 먼저 만족하는 bucket에 배정한다.
_RECOMPUTE_MISSING_QUEUE_CAUSE_INSTRUMENT_LINKAGE = "missing_instrument_linkage"
_RECOMPUTE_MISSING_QUEUE_CAUSE_SCAN_LIMIT_SUSPECTED = "queue_scan_limit_suspected"
_RECOMPUTE_MISSING_QUEUE_CAUSE_RECENT_PENDING_GAP = "recent_pending_gap"
_RECOMPUTE_MISSING_QUEUE_CAUSE_WRITE_PATH_SUSPECTED = "queue_write_path_suspected"
_RECOMPUTE_MISSING_QUEUE_CAUSE_OTHER_UNCLASSIFIED = "other_unclassified"

_RECOMPUTE_MISSING_QUEUE_CAUSE_PRECEDENCE = (
    _RECOMPUTE_MISSING_QUEUE_CAUSE_INSTRUMENT_LINKAGE,
    _RECOMPUTE_MISSING_QUEUE_CAUSE_SCAN_LIMIT_SUSPECTED,
    _RECOMPUTE_MISSING_QUEUE_CAUSE_RECENT_PENDING_GAP,
    _RECOMPUTE_MISSING_QUEUE_CAUSE_WRITE_PATH_SUSPECTED,
    _RECOMPUTE_MISSING_QUEUE_CAUSE_OTHER_UNCLASSIFIED,
)

_RECOMPUTE_MISSING_QUEUE_RECENT_THRESHOLD = timedelta(hours=1)
_LOSS_CUT_SHADOW_RECOMPUTE_MISSING_QUEUE_DEFAULT_LIMIT = 50


def _classify_recompute_missing_queue_cause(
    *,
    instrument_id_raw: str | None,
    queue_scan_limit_reached: bool,
    reference_time: datetime,
    now: datetime,
) -> str:
    """``recompute_required=true``인데 queue pending이 없는 이유를

    운영 관점에서 분류한다(읽기 전용, 판단 없음 — 버그/인과 확정
    아님). precedence(위에서부터 먼저 만족하는 것으로 확정):

    1. ``missing_instrument_linkage`` — shadow payload에 ``instrument_
       id``가 없음. 이 endpoint의 모집단은 이미 ``recompute_required
       =true``(= ``position_cost_basis_state`` 존재 = ``instrument_id``
       존재)를 전제하므로 **실제로는 도달 불가능**하다 — 상위
       ``_classify_missing_first_event_cause()``와 정의를 대칭적으로
       유지하기 위한 방어적 bucket이다(항상 count 0으로 기대).
    2. ``queue_scan_limit_suspected`` — 이번 조회에서 ``list_pending(
       limit=queue_scan_limit)``이 스캔 한계에 정확히 도달함(전역
       신호, 모든 row에 동일 적용) — 실제 미해결 큐가 스캔 창보다
       깊어 이 row의 pending이 스캔에서 빠졌을 가능성이 있다. 이
       가능성이 있으면 그 아래 판정(3/4)은 신뢰할 수 없으므로 항상
       먼저 이 bucket으로 분류한다.
    3. ``recent_pending_gap`` — ``reference_time``(``position_cost_
       basis_state.updated_at``, 없으면 sample ``created_at``)이
       ``_RECOMPUTE_MISSING_QUEUE_RECENT_THRESHOLD``(1시간) 이내로
       최근이면, 아직 queue에 반영되기 전일 가능성을 배제할 수 없다
       — "누락"이 아니라 "아직"일 수 있다는 뜻으로만 쓴다.
    4. ``queue_write_path_suspected`` — 스캔 한계에 걸리지 않았고
       (2), 충분히 시간이 지났는데도(3) queue pending이 안 보이는
       경우 — queue write 경로에 문제가 있을 **가능성**을 의심할
       근거는 있지만, 이 함수는 "의심"까지만 표현하고 확정하지
       않는다(``queue_write_path_bug_confirmed`` 같은 이름을 쓰지
       않는 이유).
    5. ``other_unclassified`` — 위 어느 것도 명확히 해당하지 않음
       (1~4가 모든 경우를 이미 다루므로 코드 경로상 도달 불가능하지만,
       애매한 값을 억지로 분류하지 않기 위한 안전망으로 유지한다).
    """
    if not instrument_id_raw:
        return _RECOMPUTE_MISSING_QUEUE_CAUSE_INSTRUMENT_LINKAGE
    if queue_scan_limit_reached:
        return _RECOMPUTE_MISSING_QUEUE_CAUSE_SCAN_LIMIT_SUSPECTED
    if now - reference_time <= _RECOMPUTE_MISSING_QUEUE_RECENT_THRESHOLD:
        return _RECOMPUTE_MISSING_QUEUE_CAUSE_RECENT_PENDING_GAP
    return _RECOMPUTE_MISSING_QUEUE_CAUSE_WRITE_PATH_SUSPECTED


@router.get(
    "/trade-decisions/loss-cut-shadow/recompute-missing-queue-causes",
    response_model=LossCutShadowRecomputeMissingQueueCausesResponse,
)
async def get_loss_cut_shadow_recompute_missing_queue_causes(
    account_id: str = Query(..., description="Account UUID"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD, KST)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD, KST)"),
    source_type: str | None = Query(None, description="Optional source_type filter"),
    tier: str | None = Query(None, description="Optional tier filter (soft|hard)"),
    before: datetime | None = Query(
        None, description="Optional — only samples created before this instant"
    ),
    limit: int = Query(
        _LOSS_CUT_SHADOW_RECOMPUTE_MISSING_QUEUE_DEFAULT_LIMIT,
        ge=1,
        le=500,
        description="Maximum samples to return",
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> LossCutShadowRecomputeMissingQueueCausesResponse:
    """``missing-first-event-recompute-cross-check``의 케이스 2

    (``recompute_required=true``인데 queue pending이 없는 sample)만
    모아 **왜 queue pending이 안 보이는지**를 운영 관점에서 분류한다.
    cross-check가 "불일치 탐지"라면, 이 endpoint는 "그 중 queue
    missing 케이스 분류"다 — **원인 분류 inspection이지 진단
    완료·인과 확정 도구가 아니다.**

    모집단: ``triggered=true`` + first realized event 없음 +
    ``recompute_required=true`` + 같은 계좌×종목에 queue pending
    없음. cause 판정은 ``_classify_missing_first_event_cause()``를
    재사용해 ``recompute_required`` 여부를 확인하고, queue missing
    "이유"는 이 endpoint 전용의 ``_classify_recompute_missing_queue_
    cause()``로 별도 분류한다(bucket precedence는 그 함수 docstring
    참고).

    **queue 스캔 한계를 숨기지 않는다**: ``queue_scan_limit``/
    ``queue_scan_limit_reached``를 top-level summary에 그대로
    노출한다 — 스캔이 한계에 도달했으면 이 응답의 모든 "queue
    missing" 판정 자체를 스캔 한계 관점에서 다시 봐야 한다.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be on or before end_date"
        )
    aid = _parse_query_uuid(account_id, field="account_id")

    queue_items = await repos.realized_pnl_recompute_queue.list_pending(
        limit=_LOSS_CUT_SHADOW_RECOMPUTE_QUEUE_SCAN_LIMIT
    )
    queue_scan_limit_reached = len(queue_items) >= _LOSS_CUT_SHADOW_RECOMPUTE_QUEUE_SCAN_LIMIT
    queue_by_instrument: dict[UUID, list] = {}
    for queue_item in queue_items:
        if queue_item.account_id != aid:
            continue
        queue_by_instrument.setdefault(queue_item.instrument_id, []).append(queue_item)

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        triggered=True,
        before=before,
        limit=None,
    )

    now = datetime.now(timezone.utc)
    sample_count = 0
    cause_counts: dict[str, int] = {
        cause: 0 for cause in _RECOMPUTE_MISSING_QUEUE_CAUSE_PRECEDENCE
    }
    source_type_sample_counts: dict[str, int] = {}
    tier_sample_counts: dict[str, int] = {}
    items: list[LossCutShadowRecomputeMissingQueueSampleView] = []

    for row in rows:
        shadow = row.loss_cut_shadow
        instrument_id_raw = shadow.get("instrument_id")

        is_missing = True
        if instrument_id_raw:
            events = await repos.realized_pnl_events.list_by_account_and_instrument_since(
                aid,
                UUID(instrument_id_raw),
                since=row.created_at,
                limit=1,
            )
            is_missing = not events
        if not is_missing:
            continue

        classification = await _classify_missing_first_event_cause(
            repos, account_id=aid, instrument_id_raw=instrument_id_raw
        )
        cost_basis_state = classification.cost_basis_state
        recompute_required = (
            cost_basis_state.recompute_required if cost_basis_state is not None else None
        )
        if recompute_required is not True:
            continue

        instrument_id = UUID(instrument_id_raw) if instrument_id_raw else None
        matching_queue_items = (
            queue_by_instrument.get(instrument_id, []) if instrument_id is not None else []
        )
        if matching_queue_items:
            continue  # queue pending이 있으면 이 endpoint의 모집단이 아니다.

        sample_count += 1
        group_source_type = row.source_type
        group_tier = shadow.get("tier") or "none"
        source_type_sample_counts[group_source_type] = (
            source_type_sample_counts.get(group_source_type, 0) + 1
        )
        tier_sample_counts[group_tier] = tier_sample_counts.get(group_tier, 0) + 1

        reference_time = (
            cost_basis_state.updated_at
            if cost_basis_state is not None and cost_basis_state.updated_at is not None
            else row.created_at
        )
        recompute_missing_cause = _classify_recompute_missing_queue_cause(
            instrument_id_raw=instrument_id_raw,
            queue_scan_limit_reached=queue_scan_limit_reached,
            reference_time=reference_time,
            now=now,
        )
        cause_counts[recompute_missing_cause] += 1

        if len(items) < limit:
            items.append(
                LossCutShadowRecomputeMissingQueueSampleView(
                    trade_decision_id=row.trade_decision_id,
                    created_at=row.created_at,
                    symbol=row.symbol,
                    instrument_id=instrument_id,
                    source_type=row.source_type,
                    actual_decision_type=row.actual_decision_type,
                    tier=shadow.get("tier"),
                    cause=recompute_missing_cause,
                    recompute_required=True,
                    position_quantity=(
                        cost_basis_state.quantity if cost_basis_state is not None else None
                    ),
                    queue_pending=False,
                    has_first_realized_event=False,
                    queue_scan_limit_reached=queue_scan_limit_reached,
                    recompute_required_since=(
                        cost_basis_state.updated_at if cost_basis_state is not None else None
                    ),
                )
            )

    cause_breakdown = [
        LossCutShadowMissingCauseBreakdownItem(
            cause=cause,
            count=cause_counts[cause],
            rate=(cause_counts[cause] / sample_count) if sample_count > 0 else 0.0,
        )
        for cause in _RECOMPUTE_MISSING_QUEUE_CAUSE_PRECEDENCE
    ]

    def _build_recompute_missing_queue_group_breakdown(
        counter: dict[str, int],
    ) -> list[LossCutShadowRecomputeMissingQueueGroupBreakdownItem]:
        return [
            LossCutShadowRecomputeMissingQueueGroupBreakdownItem(
                group_value=key,
                count=counter[key],
                rate=(counter[key] / sample_count) if sample_count > 0 else 0.0,
            )
            for key in sorted(counter)
        ]

    return LossCutShadowRecomputeMissingQueueCausesResponse(
        account_id=aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        sample_count=sample_count,
        queue_scan_limit=_LOSS_CUT_SHADOW_RECOMPUTE_QUEUE_SCAN_LIMIT,
        queue_scan_limit_reached=queue_scan_limit_reached,
        cause_breakdown=cause_breakdown,
        by_source_type=_build_recompute_missing_queue_group_breakdown(
            source_type_sample_counts
        ),
        by_tier=_build_recompute_missing_queue_group_breakdown(tier_sample_counts),
        limit=limit,
        before=before,
        items=items,
    )


_LOSS_CUT_SHADOW_QUEUE_WRITE_PATH_TIMELINES_DEFAULT_LIMIT = 50


@dataclass(frozen=True, slots=True)
class _QueueWritePathSuspectedSample:
    """``queue_write_path_suspected`` population 1건 — raw batch

    timeline endpoint와 summary endpoint가 완전히 동일한 계산
    결과를 공유하도록 이 dataclass 하나로 묶는다."""

    row: object
    instrument_id: UUID | None
    events: list[LossCutShadowTimelineRealizedEventView]
    first_event_found: bool
    first_event_latency_seconds: float | None


async def _collect_queue_write_path_suspected_samples(
    repos: RepositoryContainer,
    *,
    account_id: UUID,
    start_date: date,
    end_date: date,
    source_type: str | None,
    tier: str | None,
    before: datetime | None,
    event_limit: int,
) -> list[_QueueWritePathSuspectedSample]:
    """``queue_write_path_suspected`` 모집단 전체를 계산한다(페이지네이션

    없음 — ``limit``은 이 함수를 호출하는 쪽에서 표시 건수만 줄일 때
    쓴다). raw batch timeline endpoint와 summary endpoint가 이 함수
    하나만 공유해, 두 endpoint의 모집단·event 선정 규칙·latency
    계산이 항상 일치하게 한다(중복 구현 없음).
    """
    queue_items = await repos.realized_pnl_recompute_queue.list_pending(
        limit=_LOSS_CUT_SHADOW_RECOMPUTE_QUEUE_SCAN_LIMIT
    )
    queue_scan_limit_reached = len(queue_items) >= _LOSS_CUT_SHADOW_RECOMPUTE_QUEUE_SCAN_LIMIT
    queue_by_instrument: dict[UUID, list] = {}
    for queue_item in queue_items:
        if queue_item.account_id != account_id:
            continue
        queue_by_instrument.setdefault(queue_item.instrument_id, []).append(queue_item)

    rows = await repos.trade_decisions.list_loss_cut_shadow_observations(
        account_id,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        triggered=True,
        before=before,
        limit=None,
    )

    now = datetime.now(timezone.utc)
    samples: list[_QueueWritePathSuspectedSample] = []

    for row in rows:
        shadow = row.loss_cut_shadow
        instrument_id_raw = shadow.get("instrument_id")

        classification = await _classify_missing_first_event_cause(
            repos, account_id=account_id, instrument_id_raw=instrument_id_raw
        )
        cost_basis_state = classification.cost_basis_state
        recompute_required = (
            cost_basis_state.recompute_required if cost_basis_state is not None else None
        )
        if recompute_required is not True:
            continue

        instrument_id = UUID(instrument_id_raw) if instrument_id_raw else None
        matching_queue_items = (
            queue_by_instrument.get(instrument_id, []) if instrument_id is not None else []
        )
        if matching_queue_items:
            continue

        reference_time = (
            cost_basis_state.updated_at
            if cost_basis_state is not None and cost_basis_state.updated_at is not None
            else row.created_at
        )
        recompute_missing_cause = _classify_recompute_missing_queue_cause(
            instrument_id_raw=instrument_id_raw,
            queue_scan_limit_reached=queue_scan_limit_reached,
            reference_time=reference_time,
            now=now,
        )
        if recompute_missing_cause != _RECOMPUTE_MISSING_QUEUE_CAUSE_WRITE_PATH_SUSPECTED:
            continue

        events = await _fetch_realized_events_after_shadow(
            repos,
            account_id=account_id,
            instrument_id_raw=instrument_id_raw,
            since=row.created_at,
            event_limit=event_limit,
        )
        first_event_found = len(events) > 0
        first_event_latency_seconds = events[0].seconds_after_shadow if events else None

        samples.append(
            _QueueWritePathSuspectedSample(
                row=row,
                instrument_id=instrument_id,
                events=events,
                first_event_found=first_event_found,
                first_event_latency_seconds=first_event_latency_seconds,
            )
        )

    return samples


@router.get(
    "/trade-decisions/loss-cut-shadow/queue-write-path-suspected-timelines",
    response_model=LossCutShadowQueueWritePathSuspectedTimelinesResponse,
)
async def list_loss_cut_shadow_queue_write_path_suspected_timelines(
    account_id: str = Query(..., description="Account UUID"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD, KST)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD, KST)"),
    source_type: str | None = Query(None, description="Optional source_type filter"),
    tier: str | None = Query(None, description="Optional tier filter (soft|hard)"),
    before: datetime | None = Query(
        None, description="Optional — only samples created before this instant"
    ),
    limit: int = Query(
        _LOSS_CUT_SHADOW_QUEUE_WRITE_PATH_TIMELINES_DEFAULT_LIMIT,
        ge=1,
        le=200,
        description="Maximum samples to return",
    ),
    event_limit: int = Query(
        _LOSS_CUT_SHADOW_TIMELINE_DEFAULT_EVENT_LIMIT,
        ge=1,
        le=_LOSS_CUT_SHADOW_TIMELINE_MAX_EVENT_LIMIT,
        description="Maximum realized PnL events to return per sample",
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> LossCutShadowQueueWritePathSuspectedTimelinesResponse:
    """``recompute-missing-queue-causes``가 ``queue_write_path_

    suspected``로 분류한 sample들만 모아, 각 sample 이후 realized
    event 타임라인을 batch로 보여준다. **이 batch endpoint는 단일
    ``.../timeline`` endpoint를 건건이 눌러보는 수작업을 줄이기
    위한 것이지, 인과 확정 도구가 아니다** — "queue write path가
    실제로 고장났다"/"이 event가 바로 그 shadow의 결과다" 같은
    결론을 내리지 않는다. 의심 표본과 그 이후 관측된 realized
    event들, 시간차를 나란히 보여줄 뿐이다.

    모집단: ``triggered=true`` + ``recompute_required=true`` +
    queue pending 없음 + cause 판정이 ``queue_write_path_suspected``
    인 sample. cause 판정은 ``_classify_missing_first_event_cause()``/
    ``_classify_recompute_missing_queue_cause()``를 그대로 재사용한다
    (중복 구현 없음).

    **``recompute-missing-queue-causes``와 유일하게 다른 점**: 이
    endpoint는 "first realized event 없음"을 population 게이트로
    쓰지 않는다 — 이 endpoint의 목적이 "이전에 queue_write_path_
    suspected로 분류됐을 sample들 중 이후 실제로 event가 붙었는지"
    를 보는 것이므로, event 유무로 population을 걸러내면 그 목적
    자체가 성립하지 않는다(그러면 모든 표본이 항상 "event 없음"
    으로만 남는다). 그래서 두 endpoint를 정확히 같은 순간에 호출
    하면 population이 일치하지만, 시간이 지나 일부 표본에 event가
    생기면 이 endpoint의 population이 causes endpoint보다(이미
    해소된 표본을 포함해) 더 넓을 수 있다 — 이 차이 자체가 이
    endpoint가 답하려는 질문이다.

    **realized event 선정 규칙은 단일 ``.../timeline`` endpoint와
    완전히 동일하다** — ``_fetch_realized_events_after_shadow()``
    공통 helper를 그대로 재사용한다: ``account_id + instrument_id +
    fill_timestamp >= sample.created_at``(오름차순), sample당
    ``event_limit``건까지.

    **응답 크기 제어**: sample 개수는 ``limit``(기본 50, 최대
    200 — 단일 sample당 최대 ``event_limit``건의 event를 함께
    담으므로 samples 계열의 500보다 낮게 잡았다)으로, sample당
    event 개수는 ``event_limit``(단일 timeline endpoint와 동일한
    기본 5/최대 50)으로 각각 통제한다. **top-level 집계(``sample_
    count``/``timeline_with_events_count`` 등)는 항상 전체
    모집단 기준이다** — ``limit``은 ``items`` 표시 건수만 줄인다
    (그래야 이 endpoint와 ``queue-write-path-suspected-timeline-
    summary``의 top-level 수치가 항상 일치한다).
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be on or before end_date"
        )
    aid = _parse_query_uuid(account_id, field="account_id")

    samples = await _collect_queue_write_path_suspected_samples(
        repos,
        account_id=aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        before=before,
        event_limit=event_limit,
    )

    sample_count = len(samples)
    timeline_with_events_count = sum(1 for s in samples if s.first_event_found)
    timeline_without_events_count = sample_count - timeline_with_events_count
    found_latencies = [
        s.first_event_latency_seconds for s in samples if s.first_event_found
    ]

    items = [
        LossCutShadowQueueWritePathSuspectedTimelineItem(
            trade_decision_id=s.row.trade_decision_id,
            created_at=s.row.created_at,
            symbol=s.row.symbol,
            instrument_id=s.instrument_id,
            source_type=s.row.source_type,
            actual_decision_type=s.row.actual_decision_type,
            tier=s.row.loss_cut_shadow.get("tier"),
            timeline_event_count=len(s.events),
            first_event_found=s.first_event_found,
            first_event_latency_seconds=s.first_event_latency_seconds,
            events=s.events,
        )
        for s in samples[:limit]
    ]

    return LossCutShadowQueueWritePathSuspectedTimelinesResponse(
        account_id=aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        sample_count=sample_count,
        event_limit=event_limit,
        timeline_with_events_count=timeline_with_events_count,
        timeline_without_events_count=timeline_without_events_count,
        first_event_found_rate=(
            timeline_with_events_count / sample_count if sample_count > 0 else None
        ),
        max_observed_latency_seconds=(max(found_latencies) if found_latencies else None),
        avg_first_event_latency_seconds=(
            statistics.fmean(found_latencies) if found_latencies else None
        ),
        limit=limit,
        before=before,
        items=items,
    )


_QUEUE_WRITE_PATH_LATENCY_BUCKET_NO_EVENT = "no_event_found"
_QUEUE_WRITE_PATH_LATENCY_BUCKET_UNDER_10M = "under_10m"
_QUEUE_WRITE_PATH_LATENCY_BUCKET_10M_TO_1H = "10m_to_1h"
_QUEUE_WRITE_PATH_LATENCY_BUCKET_1H_TO_1D = "1h_to_1d"
_QUEUE_WRITE_PATH_LATENCY_BUCKET_OVER_1D = "over_1d"

_QUEUE_WRITE_PATH_LATENCY_BUCKET_ORDER = (
    _QUEUE_WRITE_PATH_LATENCY_BUCKET_NO_EVENT,
    _QUEUE_WRITE_PATH_LATENCY_BUCKET_UNDER_10M,
    _QUEUE_WRITE_PATH_LATENCY_BUCKET_10M_TO_1H,
    _QUEUE_WRITE_PATH_LATENCY_BUCKET_1H_TO_1D,
    _QUEUE_WRITE_PATH_LATENCY_BUCKET_OVER_1D,
)


def _first_event_latency_bucket(first_event_latency_seconds: float | None) -> str:
    """지연 시간(초)을 고정된 5개 구간 중 하나로 분류한다(재현 가능,

    임의 문자열 아님):

    - ``no_event_found``: 이후 realized event를 아직 못 찾음
      (``first_event_latency_seconds is None``)
    - ``under_10m``: 600초(10분) 미만
    - ``10m_to_1h``: 600초 이상 ~ 3600초(1시간) 미만
    - ``1h_to_1d``: 3600초 이상 ~ 86400초(1일) 미만
    - ``over_1d``: 86400초 이상
    """
    if first_event_latency_seconds is None:
        return _QUEUE_WRITE_PATH_LATENCY_BUCKET_NO_EVENT
    if first_event_latency_seconds < 600:
        return _QUEUE_WRITE_PATH_LATENCY_BUCKET_UNDER_10M
    if first_event_latency_seconds < 3600:
        return _QUEUE_WRITE_PATH_LATENCY_BUCKET_10M_TO_1H
    if first_event_latency_seconds < 86400:
        return _QUEUE_WRITE_PATH_LATENCY_BUCKET_1H_TO_1D
    return _QUEUE_WRITE_PATH_LATENCY_BUCKET_OVER_1D


@router.get(
    "/trade-decisions/loss-cut-shadow/queue-write-path-suspected-timeline-summary",
    response_model=LossCutShadowQueueWritePathSuspectedTimelineSummaryResponse,
)
async def get_loss_cut_shadow_queue_write_path_suspected_timeline_summary(
    account_id: str = Query(..., description="Account UUID"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD, KST)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD, KST)"),
    source_type: str | None = Query(None, description="Optional source_type filter"),
    tier: str | None = Query(None, description="Optional tier filter (soft|hard)"),
    event_limit: int = Query(
        _LOSS_CUT_SHADOW_TIMELINE_DEFAULT_EVENT_LIMIT,
        ge=1,
        le=_LOSS_CUT_SHADOW_TIMELINE_MAX_EVENT_LIMIT,
        description="Maximum realized PnL events to inspect per sample",
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> LossCutShadowQueueWritePathSuspectedTimelineSummaryResponse:
    """``queue-write-path-suspected-timelines``(raw batch inspection)의

    결과를 종목별/지연구간별/해소 여부 기준으로 요약한다. **이
    endpoint 자체는 새 계산을 하지 않는다** — raw endpoint와
    ``_collect_queue_write_path_suspected_samples()`` 공통 helper를
    그대로 공유해 **완전히 동일한 모집단·event 선정 규칙**으로
    계산한다(중복 구현 없음). 같은 조회 조건으로 raw endpoint와 이
    endpoint를 호출하면 top-level 수치가 항상 일치한다 — raw
    endpoint의 ``limit``은 ``items`` 표시 건수만 줄이고 top-level
    집계는 이미 전체 모집단 기준이기 때문이다.

    모집단: ``triggered=true`` + ``recompute_required=true`` +
    queue pending 없음 + cause 판정이 ``queue_write_path_suspected``
    인 sample 전체(페이지네이션 없음 — ``limit``/``before`` 쿼리
    파라미터를 두지 않았다).

    지연구간 bucket 정의는 ``_first_event_latency_bucket()``
    docstring 참고. **운영 summary inspection이지 인과 확정 도구가
    아니다** — "queue write path가 고장났다" 같은 결론을 내리지
    않는다.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be on or before end_date"
        )
    aid = _parse_query_uuid(account_id, field="account_id")

    samples = await _collect_queue_write_path_suspected_samples(
        repos,
        account_id=aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        before=None,
        event_limit=event_limit,
    )

    sample_count = len(samples)
    timeline_with_events_count = sum(1 for s in samples if s.first_event_found)
    timeline_without_events_count = sample_count - timeline_with_events_count
    found_latencies = [
        s.first_event_latency_seconds for s in samples if s.first_event_found
    ]

    by_instrument_samples: dict[UUID, list[_QueueWritePathSuspectedSample]] = {}
    by_source_type_samples: dict[str, list[_QueueWritePathSuspectedSample]] = {}
    by_tier_samples: dict[str, list[_QueueWritePathSuspectedSample]] = {}
    bucket_counts: dict[str, int] = {
        bucket: 0 for bucket in _QUEUE_WRITE_PATH_LATENCY_BUCKET_ORDER
    }

    for s in samples:
        if s.instrument_id is not None:
            by_instrument_samples.setdefault(s.instrument_id, []).append(s)
        by_source_type_samples.setdefault(s.row.source_type, []).append(s)
        tier_key = s.row.loss_cut_shadow.get("tier") or "none"
        by_tier_samples.setdefault(tier_key, []).append(s)
        bucket_counts[_first_event_latency_bucket(s.first_event_latency_seconds)] += 1

    by_instrument: list[LossCutShadowQueueWritePathSuspectedByInstrumentItem] = []
    for instrument_id in sorted(by_instrument_samples, key=str):
        group = by_instrument_samples[instrument_id]
        group_with_events = [s for s in group if s.first_event_found]
        group_latencies = [s.first_event_latency_seconds for s in group_with_events]
        by_instrument.append(
            LossCutShadowQueueWritePathSuspectedByInstrumentItem(
                instrument_id=instrument_id,
                symbol=group[0].row.symbol,
                sample_count=len(group),
                timeline_with_events_count=len(group_with_events),
                timeline_without_events_count=len(group) - len(group_with_events),
                first_event_found_rate=(
                    len(group_with_events) / len(group) if group else None
                ),
                avg_first_event_latency_seconds=(
                    statistics.fmean(group_latencies) if group_latencies else None
                ),
                max_observed_latency_seconds=(
                    max(group_latencies) if group_latencies else None
                ),
                latest_sample_created_at=max(s.row.created_at for s in group),
            )
        )

    def _build_queue_write_path_group_breakdown(
        grouped: dict[str, list[_QueueWritePathSuspectedSample]],
    ) -> list[LossCutShadowQueueWritePathSuspectedGroupBreakdownItem]:
        result: list[LossCutShadowQueueWritePathSuspectedGroupBreakdownItem] = []
        for key in sorted(grouped):
            group = grouped[key]
            group_with_events = sum(1 for s in group if s.first_event_found)
            result.append(
                LossCutShadowQueueWritePathSuspectedGroupBreakdownItem(
                    group_value=key,
                    sample_count=len(group),
                    timeline_with_events_count=group_with_events,
                    timeline_without_events_count=len(group) - group_with_events,
                    first_event_found_rate=(
                        group_with_events / len(group) if group else None
                    ),
                )
            )
        return result

    by_latency_bucket = [
        LossCutShadowQueueWritePathSuspectedLatencyBucketItem(
            bucket=bucket,
            count=bucket_counts[bucket],
            rate=(bucket_counts[bucket] / sample_count) if sample_count > 0 else 0.0,
        )
        for bucket in _QUEUE_WRITE_PATH_LATENCY_BUCKET_ORDER
    ]

    return LossCutShadowQueueWritePathSuspectedTimelineSummaryResponse(
        account_id=aid,
        start_date=start_date,
        end_date=end_date,
        source_type=source_type,
        tier=tier,
        sample_count=sample_count,
        event_limit=event_limit,
        timeline_with_events_count=timeline_with_events_count,
        timeline_without_events_count=timeline_without_events_count,
        first_event_found_rate=(
            timeline_with_events_count / sample_count if sample_count > 0 else None
        ),
        max_observed_latency_seconds=(max(found_latencies) if found_latencies else None),
        avg_first_event_latency_seconds=(
            statistics.fmean(found_latencies) if found_latencies else None
        ),
        median_first_event_latency_seconds=(
            statistics.median(found_latencies) if found_latencies else None
        ),
        by_instrument=by_instrument,
        by_latency_bucket=by_latency_bucket,
        by_source_type=_build_queue_write_path_group_breakdown(by_source_type_samples),
        by_tier=_build_queue_write_path_group_breakdown(by_tier_samples),
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
