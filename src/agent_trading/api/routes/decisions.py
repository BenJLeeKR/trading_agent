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
    DecisionContextDetail,
    PaginatedTradeDecisionsResponse,
    TradeDecisionDetail,
    WatchDiagnosticsEvidenceStrengthItem,
    WatchDiagnosticsReasonCodeItem,
    WatchDiagnosticsResponse,
    WatchDiagnosticsSampleItem,
    WatchDiagnosticsSourceTypeItem,
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


def _to_detail(row: TradeDecisionRow, instrument_name: str | None = None) -> TradeDecisionDetail:
    """Convert ``TradeDecisionRow`` to API schema.

    ``TradeDecisionRow`` contains the domain entity plus optional
    ``order_request_id`` and ``order_status`` from a LEFT JOIN.

    ``instrument_name``은 SQL LEFT JOIN으로 미리 resolve된 값을 받아
    N+1 문제를 방지한다.
    """
    d = row.entity
    return TradeDecisionDetail(
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


@router.get("/trade-decisions", response_model=PaginatedTradeDecisionsResponse)
async def list_trade_decisions(
    decision_context_id: str | None = Query(None, description="Decision context ID (optional)"),
    created_date: date | None = Query(None, description="KST created_at date filter (YYYY-MM-DD)"),
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

    # SQL LEFT JOIN으로 instrument_name이 이미 TradeDecisionRow.instrument_name에
    # resolve되어 있음
    details = [_to_detail(row, instrument_name=row.instrument_name) for row in rows]

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
        created_at=ctx.created_at,
    )
