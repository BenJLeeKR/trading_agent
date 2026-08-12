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
    if not instrument_id_raw:
        # skipped_reason이 있는 관측(가격 미확보 등)은 instrument_id가
        # 없을 수 있다 — realized event와 연결할 키가 없으므로 빈
        # 타임라인으로 응답한다(에러 아님, 정상적으로 발생 가능한 상태).
        realized_events: list = []
    else:
        instrument_id = UUID(instrument_id_raw)
        events = await repos.realized_pnl_events.list_by_account_and_instrument_since(
            aid,
            instrument_id,
            since=decision.created_at,
            limit=event_limit,
        )
        realized_events = [
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
                seconds_after_shadow=(
                    event.fill_timestamp - decision.created_at
                ).total_seconds(),
            )
            for event in events
        ]

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
