"""Performance summary inspection endpoint.

``GET /performance-summary`` — paper 운용 성과 요약.
``GET /performance-history`` — 기간 필터 기반 일별 성과 히스토리.
``GET /performance-metrics`` — 기간 기반 cumulative return / drawdown / win-rate.
``GET /performance-benchmark`` — 전략/계좌 성과를 기준 지수 대비 초과수익 비교.

계좌 수준 또는 전략 수준의 PnL/equity 요약,
일별 시계열 히스토리, 그리고 기간 기반 성과 지표를 반환합니다.
이 endpoint들은 **read-only**이며, 어떤 데이터도 변경하지 않습니다.
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_db, get_repos
from agent_trading.api.schemas import (
    AccountPerformanceSummaryView,
    BenchmarkComparisonView,
    BenchmarkHistoryResponse,
    DailyPerformancePointView,
    EdgeOutcomeAttributionItem,
    GateEvaluationView,
    GuardrailAttributionItem,
    HoldingProfileAttributionItem,
    HoldingProfilePerformanceAttributionResponse,
    PerformanceHistoryResponse,
    PerformanceMetricsView,
    RelativeBenchmarkPointView,
    StrategyPerformanceSummaryView,
    TriggerAttributionBucketItem,
    TriggerPerformanceAttributionResponse,
)
from agent_trading.config.settings import AppSettings
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.benchmark_comparison import (
    BENCHMARK_KOSPI,
    VALID_BENCHMARK_CODES,
    BenchmarkComparisonService,
    InMemoryBenchmarkPriceRepository,
    _DEFAULT_BENCHMARK_PRICES,
)
from agent_trading.services.gate_evaluation import GateEvaluationService
from agent_trading.services.performance_summary import PerformanceSummaryService

router = APIRouter(tags=["performance"])


def _build_trigger_bucket_items(rows: list[object]) -> list[TriggerAttributionBucketItem]:
    items: list[TriggerAttributionBucketItem] = []
    for row in rows:
        decision_count = int(row["decision_count"] or 0)
        actionable_decision_count = int(row["actionable_decision_count"] or 0)
        order_count = int(row["order_count"] or 0)
        filled_order_count = int(row["filled_order_count"] or 0)
        items.append(
            TriggerAttributionBucketItem(
                bucket=str(row["bucket"]),
                decision_count=decision_count,
                actionable_decision_count=actionable_decision_count,
                order_count=order_count,
                filled_order_count=filled_order_count,
                order_conversion_rate=(
                    float(order_count) / float(actionable_decision_count)
                    if actionable_decision_count
                    else 0.0
                ),
                fill_conversion_rate=(
                    float(filled_order_count) / float(actionable_decision_count)
                    if actionable_decision_count
                    else 0.0
                ),
            )
        )
    return items


def _float_or_none(value: object) -> float | None:
    return float(value) if value is not None else None


@router.get(
    "/performance-summary",
    response_model=AccountPerformanceSummaryView,
)
async def get_performance_summary(
    account_id: str = Query(..., description="Account UUID"),
    strategy_id: str | None = Query(
        None, description="Optional strategy UUID for strategy-level summary"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> AccountPerformanceSummaryView | StrategyPerformanceSummaryView:
    """Get paper performance summary for an account.

    Returns account-level PnL/equity summary by default.
    When ``strategy_id`` is provided, returns strategy-level summary
    (subset of metrics scoped to that strategy).

    Parameters
    ----------
    account_id:
        Target account UUID (required).
    strategy_id:
        Optional strategy UUID. When provided, the response includes
        strategy-scoped metrics.

    Returns
    -------
    AccountPerformanceSummaryView
        Account-level performance summary (default).
    StrategyPerformanceSummaryView
        Strategy-level performance summary (when ``strategy_id`` is given).
    """
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    service = PerformanceSummaryService(repos)

    if strategy_id is not None:
        try:
            sid = UUID(strategy_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid strategy_id UUID")

        summary = await service.get_strategy_summary(aid, sid)
        return StrategyPerformanceSummaryView.model_validate(summary)

    summary = await service.get_account_summary(aid)
    return AccountPerformanceSummaryView.model_validate(summary)


@router.get(
    "/performance-trigger-attribution",
    response_model=TriggerPerformanceAttributionResponse,
)
async def get_performance_trigger_attribution(
    account_id: str = Query(..., description="Account UUID"),
    lookback_days: int = Query(14, ge=1, le=90),
    db=Depends(get_db),
) -> TriggerPerformanceAttributionResponse:
    """계좌 기준 deterministic trigger/override의 주문·체결 전환을 집계한다."""
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    since_sql = "NOW() - ($2::int * INTERVAL '1 day')"
    candidate_expr = "jsonb_typeof(td.decision_json->'candidate_vs_final') = 'object'"
    actionable_expr = (
        "COALESCE(td.decision_json#>>'{candidate_vs_final,candidate_intent}', 'no_action') "
        "IN ('buy', 'sell', 'watch')"
    )
    filled_expr = (
        "LOWER(CAST(COALESCE(o.status, 'unknown') AS text)) "
        "IN ('filled', 'partially_filled')"
    )

    summary_row = await db.fetchrow(
        f"""
        SELECT
            COUNT(*)::int AS total_decision_count,
            COUNT(*) FILTER (
                WHERE {candidate_expr}
            )::int AS tracked_decision_count,
            COUNT(*) FILTER (
                WHERE {candidate_expr}
                  AND {actionable_expr}
            )::int AS actionable_decision_count,
            COUNT(*) FILTER (
                WHERE {candidate_expr}
                  AND o.order_request_id IS NOT NULL
            )::int AS ordered_decision_count,
            COUNT(*) FILTER (
                WHERE {candidate_expr}
                  AND o.order_request_id IS NOT NULL
                  AND {filled_expr}
            )::int AS filled_decision_count
        FROM trading.trade_decisions td
        JOIN trading.decision_contexts dc
          ON dc.decision_context_id = td.decision_context_id
        LEFT JOIN trading.order_requests o
          ON o.trade_decision_id = td.trade_decision_id
        WHERE dc.account_id = $1
          AND td.created_at >= {since_sql}
        """,
        aid,
        lookback_days,
    )

    alignment_rows = await db.fetch(
        f"""
        SELECT
            COALESCE(td.decision_json#>>'{{candidate_vs_final,alignment_status}}', 'unknown') AS bucket,
            COUNT(*)::int AS decision_count,
            COUNT(*) FILTER (
                WHERE {actionable_expr}
            )::int AS actionable_decision_count,
            COUNT(*) FILTER (
                WHERE o.order_request_id IS NOT NULL
            )::int AS order_count,
            COUNT(*) FILTER (
                WHERE o.order_request_id IS NOT NULL
                  AND {filled_expr}
            )::int AS filled_order_count
        FROM trading.trade_decisions td
        JOIN trading.decision_contexts dc
          ON dc.decision_context_id = td.decision_context_id
        LEFT JOIN trading.order_requests o
          ON o.trade_decision_id = td.trade_decision_id
        WHERE dc.account_id = $1
          AND td.created_at >= {since_sql}
          AND {candidate_expr}
        GROUP BY COALESCE(td.decision_json#>>'{{candidate_vs_final,alignment_status}}', 'unknown')
        ORDER BY decision_count DESC, bucket ASC
        """,
        aid,
        lookback_days,
    )

    candidate_rows = await db.fetch(
        f"""
        SELECT
            COALESCE(td.decision_json#>>'{{candidate_vs_final,candidate_intent}}', 'unknown') AS bucket,
            COUNT(*)::int AS decision_count,
            COUNT(*) FILTER (
                WHERE {actionable_expr}
            )::int AS actionable_decision_count,
            COUNT(*) FILTER (
                WHERE o.order_request_id IS NOT NULL
            )::int AS order_count,
            COUNT(*) FILTER (
                WHERE o.order_request_id IS NOT NULL
                  AND {filled_expr}
            )::int AS filled_order_count
        FROM trading.trade_decisions td
        JOIN trading.decision_contexts dc
          ON dc.decision_context_id = td.decision_context_id
        LEFT JOIN trading.order_requests o
          ON o.trade_decision_id = td.trade_decision_id
        WHERE dc.account_id = $1
          AND td.created_at >= {since_sql}
          AND {candidate_expr}
        GROUP BY COALESCE(td.decision_json#>>'{{candidate_vs_final,candidate_intent}}', 'unknown')
        ORDER BY decision_count DESC, bucket ASC
        """,
        aid,
        lookback_days,
    )

    total_decision_count = int((summary_row or {}).get("total_decision_count") or 0)
    tracked_decision_count = int((summary_row or {}).get("tracked_decision_count") or 0)
    actionable_decision_count = int((summary_row or {}).get("actionable_decision_count") or 0)
    ordered_decision_count = int((summary_row or {}).get("ordered_decision_count") or 0)
    filled_decision_count = int((summary_row or {}).get("filled_decision_count") or 0)

    return TriggerPerformanceAttributionResponse(
        account_id=account_id,
        lookback_days=lookback_days,
        total_decision_count=total_decision_count,
        tracked_decision_count=tracked_decision_count,
        actionable_decision_count=actionable_decision_count,
        ordered_decision_count=ordered_decision_count,
        filled_decision_count=filled_decision_count,
        decision_to_order_rate=(
            float(ordered_decision_count) / float(actionable_decision_count)
            if actionable_decision_count
            else 0.0
        ),
        decision_to_fill_rate=(
            float(filled_decision_count) / float(actionable_decision_count)
            if actionable_decision_count
            else 0.0
        ),
        alignment_items=_build_trigger_bucket_items(alignment_rows),
        candidate_intent_items=_build_trigger_bucket_items(candidate_rows),
    )


@router.get(
    "/performance-holding-profile-attribution",
    response_model=HoldingProfilePerformanceAttributionResponse,
)
async def get_performance_holding_profile_attribution(
    account_id: str = Query(..., description="Account UUID"),
    lookback_days: int = Query(14, ge=1, le=90),
    churn_window_hours: int = Query(24, ge=1, le=168),
    db=Depends(get_db),
) -> HoldingProfilePerformanceAttributionResponse:
    """holding_profile / reverse-trade / probe churn 관점의 deterministic attribution 리포트."""
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    since_sql = "NOW() - ($2::int * INTERVAL '1 day')"
    edge_expr = (
        "NULLIF(td.decision_json#>>'{expected_value_gate,edge_after_cost_bps}', '')::numeric"
    )
    actionable_expr = (
        "LOWER(COALESCE(td.decision_type::text, '')) IN ('approve', 'buy', 'sell', 'exit', 'reduce')"
    )
    filled_expr = (
        "LOWER(CAST(COALESCE(o.status, 'unknown') AS text)) IN ('filled', 'partially_filled')"
    )
    latest_attempt_join = """
        LEFT JOIN LATERAL (
            SELECT
                ea.stop_reason,
                ea.stop_phase
            FROM trading.execution_attempts ea
            WHERE ea.trade_decision_id = td.trade_decision_id
            ORDER BY COALESCE(ea.completed_at, ea.started_at, ea.created_at) DESC,
                     ea.execution_attempt_id DESC
            LIMIT 1
        ) latest_attempt ON TRUE
    """
    reverse_guard_filter = """
        LOWER(COALESCE(latest_attempt.stop_reason, '')) IN (
            'reverse_trade_same_signal_feature_snapshot',
            'reverse_trade_single_share_blocked',
            'same_symbol_reentry_cooldown',
            'held_position_recent_buy_sell_cooldown',
            'held_position_recent_risk_sell_cooldown'
        )
    """
    probe_guard_filter = """
        LOWER(COALESCE(latest_attempt.stop_reason, '')) IN (
            'probe_churn_single_share_blocked',
            'overlay_single_share_buy_blocked'
        )
    """
    holding_guard_filter = """
        LOWER(COALESCE(latest_attempt.stop_reason, '')) IN (
            'holding_profile_earliest_reduce_guard',
            'holding_profile_earliest_reentry_guard'
        )
    """

    summary_row = await db.fetchrow(
        f"""
        SELECT
            COUNT(*)::int AS total_decision_count,
            COUNT(*) FILTER (WHERE {reverse_guard_filter})::int AS reverse_trade_blocked_count,
            COUNT(*) FILTER (WHERE {probe_guard_filter})::int AS probe_churn_blocked_count,
            COUNT(*) FILTER (WHERE {holding_guard_filter})::int AS holding_profile_guard_blocked_count
        FROM trading.trade_decisions td
        JOIN trading.decision_contexts dc
          ON dc.decision_context_id = td.decision_context_id
        LEFT JOIN trading.order_requests o
          ON o.trade_decision_id = td.trade_decision_id
        {latest_attempt_join}
        WHERE dc.account_id = $1
          AND td.created_at >= {since_sql}
        """,
        aid,
        lookback_days,
    )

    holding_profile_rows = await db.fetch(
        f"""
        WITH decision_rows AS (
            SELECT
                COALESCE(
                    NULLIF(td.decision_json#>>'{{holding_profile_policy,holding_profile}}', ''),
                    'unknown'
                ) AS holding_profile,
                td.trade_decision_id,
                td.decision_type,
                {edge_expr} AS edge_after_cost_bps,
                o.order_request_id,
                o.status
            FROM trading.trade_decisions td
            JOIN trading.decision_contexts dc
              ON dc.decision_context_id = td.decision_context_id
            LEFT JOIN trading.order_requests o
              ON o.trade_decision_id = td.trade_decision_id
            WHERE dc.account_id = $1
              AND td.created_at >= {since_sql}
        ),
        closed_trade_rows AS (
            WITH filled_entries AS (
                SELECT
                    COALESCE(
                        NULLIF(td.decision_json#>>'{{holding_profile_policy,holding_profile}}', ''),
                        'unknown'
                    ) AS holding_profile,
                    {edge_expr} AS edge_after_cost_bps,
                    td.symbol,
                    COALESCE(o.avg_fill_price, o.requested_price) AS entry_price,
                    COALESCE(o.updated_at, o.created_at) AS entry_filled_at
                FROM trading.order_requests o
                JOIN trading.trade_decisions td
                  ON td.trade_decision_id = o.trade_decision_id
                JOIN trading.decision_contexts dc
                  ON dc.decision_context_id = td.decision_context_id
                WHERE dc.account_id = $1
                  AND td.created_at >= {since_sql}
                  AND LOWER(CAST(COALESCE(o.side, 'unknown') AS text)) = 'buy'
                  AND {filled_expr}
                  AND COALESCE(o.avg_fill_price, o.requested_price) IS NOT NULL
            )
            SELECT
                entry.holding_profile,
                COUNT(*)::int AS closed_trade_count,
                AVG(EXTRACT(EPOCH FROM (exit_trade.exit_filled_at - entry.entry_filled_at)) / 60.0)::float
                    AS avg_holding_minutes,
                AVG(
                    ((exit_trade.exit_price - entry.entry_price) / NULLIF(entry.entry_price, 0)) * 100.0
                )::float AS avg_realized_return_pct
            FROM filled_entries entry
            JOIN LATERAL (
                SELECT
                    COALESCE(o2.avg_fill_price, o2.requested_price) AS exit_price,
                    COALESCE(o2.updated_at, o2.created_at) AS exit_filled_at
                FROM trading.order_requests o2
                JOIN trading.trade_decisions td2
                  ON td2.trade_decision_id = o2.trade_decision_id
                JOIN trading.decision_contexts dc2
                  ON dc2.decision_context_id = td2.decision_context_id
                WHERE dc2.account_id = $1
                  AND td2.symbol = entry.symbol
                  AND LOWER(CAST(COALESCE(o2.side, 'unknown') AS text)) = 'sell'
                  AND {filled_expr.replace("o.", "o2.")}
                  AND COALESCE(o2.avg_fill_price, o2.requested_price) IS NOT NULL
                  AND COALESCE(o2.updated_at, o2.created_at) > entry.entry_filled_at
                ORDER BY COALESCE(o2.updated_at, o2.created_at) ASC, o2.order_request_id ASC
                LIMIT 1
            ) exit_trade ON TRUE
            GROUP BY entry.holding_profile
        )
        SELECT
            dr.holding_profile,
            COUNT(*)::int AS decision_count,
            COUNT(*) FILTER (
                WHERE LOWER(COALESCE(dr.decision_type::text, '')) IN ('approve', 'buy', 'sell', 'exit', 'reduce')
            )::int AS actionable_decision_count,
            COUNT(*) FILTER (
                WHERE dr.order_request_id IS NOT NULL
            )::int AS ordered_decision_count,
            COUNT(*) FILTER (
                WHERE LOWER(CAST(COALESCE(dr.status, 'unknown') AS text)) IN ('filled', 'partially_filled')
            )::int AS filled_decision_count,
            AVG(dr.edge_after_cost_bps)::float AS avg_edge_after_cost_bps,
            COALESCE(ct.closed_trade_count, 0)::int AS closed_trade_count,
            ct.avg_holding_minutes,
            ct.avg_realized_return_pct
        FROM decision_rows dr
        LEFT JOIN closed_trade_rows ct
          ON ct.holding_profile = dr.holding_profile
        GROUP BY
            dr.holding_profile,
            ct.closed_trade_count,
            ct.avg_holding_minutes,
            ct.avg_realized_return_pct
        ORDER BY decision_count DESC, dr.holding_profile ASC
        """,
        aid,
        lookback_days,
    )

    guardrail_rows = await db.fetch(
        f"""
        SELECT
            CASE
                WHEN {reverse_guard_filter} THEN 'reverse_trade'
                WHEN {probe_guard_filter} THEN 'probe_churn'
                WHEN {holding_guard_filter} THEN 'holding_profile_guard'
                ELSE 'other'
            END AS guardrail_family,
            LOWER(COALESCE(latest_attempt.stop_reason, 'unknown')) AS reason_code,
            COUNT(*)::int AS decision_count
        FROM trading.trade_decisions td
        JOIN trading.decision_contexts dc
          ON dc.decision_context_id = td.decision_context_id
        {latest_attempt_join}
        WHERE dc.account_id = $1
          AND td.created_at >= {since_sql}
          AND (
            {reverse_guard_filter}
            OR {probe_guard_filter}
            OR {holding_guard_filter}
          )
        GROUP BY guardrail_family, LOWER(COALESCE(latest_attempt.stop_reason, 'unknown'))
        ORDER BY decision_count DESC, guardrail_family ASC, reason_code ASC
        """,
        aid,
        lookback_days,
    )

    churn_row = await db.fetchrow(
        f"""
        WITH filled_orders AS (
            SELECT
                td.symbol,
                LOWER(CAST(COALESCE(o.side, 'unknown') AS text)) AS side,
                COALESCE(o.updated_at, o.created_at) AS filled_at
            FROM trading.order_requests o
            JOIN trading.trade_decisions td
              ON td.trade_decision_id = o.trade_decision_id
            JOIN trading.decision_contexts dc
              ON dc.decision_context_id = td.decision_context_id
            WHERE dc.account_id = $1
              AND td.created_at >= {since_sql}
              AND {filled_expr}
        ),
        sequenced AS (
            SELECT
                symbol,
                side,
                filled_at,
                LEAD(side) OVER (PARTITION BY symbol ORDER BY filled_at ASC) AS next_side,
                LEAD(filled_at) OVER (PARTITION BY symbol ORDER BY filled_at ASC) AS next_filled_at
            FROM filled_orders
        )
        SELECT
            COUNT(*) FILTER (
                WHERE next_side IS NOT NULL
                  AND next_side <> side
                  AND next_filled_at <= filled_at + ($3::int * INTERVAL '1 hour')
            )::int AS realized_opposite_fill_churn_count,
            COUNT(*) FILTER (
                WHERE next_side IS NOT NULL
                  AND next_side <> side
                  AND next_filled_at > filled_at + ($3::int * INTERVAL '1 hour')
            )::int AS realized_opposite_fill_non_churn_count
        FROM sequenced
        """,
        aid,
        lookback_days,
        churn_window_hours,
    )

    edge_rows = await db.fetch(
        f"""
        WITH filled_entries AS (
            SELECT
                CASE
                    WHEN {edge_expr} IS NULL THEN 'unknown'
                    WHEN {edge_expr} < 0 THEN 'lt_0'
                    WHEN {edge_expr} < 10 THEN '0_10'
                    WHEN {edge_expr} < 20 THEN '10_20'
                    WHEN {edge_expr} < 35 THEN '20_35'
                    ELSE 'ge_35'
                END AS edge_bucket,
                td.symbol,
                {edge_expr} AS edge_after_cost_bps,
                COALESCE(o.avg_fill_price, o.requested_price) AS entry_price,
                COALESCE(o.updated_at, o.created_at) AS entry_filled_at
            FROM trading.order_requests o
            JOIN trading.trade_decisions td
              ON td.trade_decision_id = o.trade_decision_id
            JOIN trading.decision_contexts dc
              ON dc.decision_context_id = td.decision_context_id
            WHERE dc.account_id = $1
              AND td.created_at >= {since_sql}
              AND LOWER(CAST(COALESCE(o.side, 'unknown') AS text)) = 'buy'
              AND {filled_expr}
              AND COALESCE(o.avg_fill_price, o.requested_price) IS NOT NULL
        )
        SELECT
            entry.edge_bucket,
            COUNT(*)::int AS closed_trade_count,
            AVG(EXTRACT(EPOCH FROM (exit_trade.exit_filled_at - entry.entry_filled_at)) / 60.0)::float
                AS avg_holding_minutes,
            AVG(
                ((exit_trade.exit_price - entry.entry_price) / NULLIF(entry.entry_price, 0)) * 100.0
            )::float AS avg_realized_return_pct
        FROM filled_entries entry
        JOIN LATERAL (
            SELECT
                COALESCE(o2.avg_fill_price, o2.requested_price) AS exit_price,
                COALESCE(o2.updated_at, o2.created_at) AS exit_filled_at
            FROM trading.order_requests o2
            JOIN trading.trade_decisions td2
              ON td2.trade_decision_id = o2.trade_decision_id
            JOIN trading.decision_contexts dc2
              ON dc2.decision_context_id = td2.decision_context_id
            WHERE dc2.account_id = $1
              AND td2.symbol = entry.symbol
              AND LOWER(CAST(COALESCE(o2.side, 'unknown') AS text)) = 'sell'
              AND {filled_expr.replace("o.", "o2.")}
              AND COALESCE(o2.avg_fill_price, o2.requested_price) IS NOT NULL
              AND COALESCE(o2.updated_at, o2.created_at) > entry.entry_filled_at
            ORDER BY COALESCE(o2.updated_at, o2.created_at) ASC, o2.order_request_id ASC
            LIMIT 1
        ) exit_trade ON TRUE
        GROUP BY entry.edge_bucket
        ORDER BY
            CASE entry.edge_bucket
                WHEN 'unknown' THEN 0
                WHEN 'lt_0' THEN 1
                WHEN '0_10' THEN 2
                WHEN '10_20' THEN 3
                WHEN '20_35' THEN 4
                ELSE 5
            END
        """,
        aid,
        lookback_days,
    )

    return HoldingProfilePerformanceAttributionResponse(
        account_id=account_id,
        lookback_days=lookback_days,
        churn_window_hours=churn_window_hours,
        total_decision_count=int((summary_row or {}).get("total_decision_count") or 0),
        reverse_trade_blocked_count=int((summary_row or {}).get("reverse_trade_blocked_count") or 0),
        probe_churn_blocked_count=int((summary_row or {}).get("probe_churn_blocked_count") or 0),
        holding_profile_guard_blocked_count=int((summary_row or {}).get("holding_profile_guard_blocked_count") or 0),
        realized_opposite_fill_churn_count=int((churn_row or {}).get("realized_opposite_fill_churn_count") or 0),
        realized_opposite_fill_non_churn_count=int((churn_row or {}).get("realized_opposite_fill_non_churn_count") or 0),
        holding_profile_items=[
            HoldingProfileAttributionItem(
                holding_profile=str(row["holding_profile"]),
                decision_count=int(row["decision_count"] or 0),
                actionable_decision_count=int(row["actionable_decision_count"] or 0),
                ordered_decision_count=int(row["ordered_decision_count"] or 0),
                filled_decision_count=int(row["filled_decision_count"] or 0),
                avg_edge_after_cost_bps=_float_or_none(row["avg_edge_after_cost_bps"]),
                closed_trade_count=int(row["closed_trade_count"] or 0),
                avg_holding_minutes=_float_or_none(row["avg_holding_minutes"]),
                avg_realized_return_pct=_float_or_none(row["avg_realized_return_pct"]),
            )
            for row in holding_profile_rows
        ],
        guardrail_items=[
            GuardrailAttributionItem(
                guardrail_family=str(row["guardrail_family"]),
                reason_code=str(row["reason_code"]),
                decision_count=int(row["decision_count"] or 0),
            )
            for row in guardrail_rows
        ],
        edge_outcome_items=[
            EdgeOutcomeAttributionItem(
                edge_bucket=str(row["edge_bucket"]),
                closed_trade_count=int(row["closed_trade_count"] or 0),
                avg_holding_minutes=_float_or_none(row["avg_holding_minutes"]),
                avg_realized_return_pct=_float_or_none(row["avg_realized_return_pct"]),
            )
            for row in edge_rows
        ],
    )


@router.get(
    "/performance-history",
    response_model=PerformanceHistoryResponse,
)
async def get_performance_history(
    account_id: str = Query(..., description="Account UUID"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    strategy_id: str | None = Query(
        None, description="Optional strategy UUID for strategy-filtered history"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> PerformanceHistoryResponse:
    """Get daily performance history for an account.

    Returns a time-series of daily performance points from ``start_date``
    to ``end_date`` (inclusive). Each point includes realized PnL,
    cumulative realized PnL, cash balance, position market value,
    unrealized PnL, and total equity.

    Parameters
    ----------
    account_id:
        Target account UUID (required).
    start_date:
        Start date in ``YYYY-MM-DD`` format (inclusive, required).
    end_date:
        End date in ``YYYY-MM-DD`` format (inclusive, required).
    strategy_id:
        Optional strategy UUID. When provided, only orders belonging
        to that strategy are included in realized PnL aggregation.

    Returns
    -------
    PerformanceHistoryResponse
        Time-series of daily performance points.
    """
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    try:
        sd = date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid start_date (use YYYY-MM-DD)")

    try:
        ed = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid end_date (use YYYY-MM-DD)")

    if sd > ed:
        raise HTTPException(
            status_code=400,
            detail="start_date must be on or before end_date",
        )

    sid: UUID | None = None
    if strategy_id is not None:
        try:
            sid = UUID(strategy_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid strategy_id UUID")

    service = PerformanceSummaryService(repos)
    points = await service.get_daily_history(aid, sd, ed, strategy_id=sid)

    return PerformanceHistoryResponse(
        account_id=account_id,
        start_date=sd,
        end_date=ed,
        strategy_id=strategy_id,
        points=[DailyPerformancePointView.model_validate(p) for p in points],
    )


@router.get(
    "/performance-metrics",
    response_model=PerformanceMetricsView,
)
async def get_performance_metrics(
    account_id: str = Query(..., description="Account UUID"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    strategy_id: str | None = Query(
        None, description="Optional strategy UUID for strategy-filtered metrics"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> PerformanceMetricsView:
    """Get performance metrics for an account over a date range.

    Computes cumulative return, drawdown, win-rate, avg win/loss,
    and profit factor from the equity history and per-order PnL
    between ``start_date`` and ``end_date`` (inclusive).

    Parameters
    ----------
    account_id:
        Target account UUID (required).
    start_date:
        Start date in ``YYYY-MM-DD`` format (inclusive, required).
    end_date:
        End date in ``YYYY-MM-DD`` format (inclusive, required).
    strategy_id:
        Optional strategy UUID. When provided, only orders belonging
        to that strategy are included.

    Returns
    -------
    PerformanceMetricsView
        Period-based performance metrics (19 fields).
    """
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    try:
        sd = date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid start_date (use YYYY-MM-DD)"
        )

    try:
        ed = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid end_date (use YYYY-MM-DD)"
        )

    if sd > ed:
        raise HTTPException(
            status_code=400,
            detail="start_date must be on or before end_date",
        )

    sid: UUID | None = None
    if strategy_id is not None:
        try:
            sid = UUID(strategy_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid strategy_id UUID")

    service = PerformanceSummaryService(repos)
    metrics = await service.get_performance_metrics(aid, sd, ed, strategy_id=sid)

    return PerformanceMetricsView.model_validate(metrics)


@router.get(
    "/performance-benchmark",
    response_model=BenchmarkComparisonView,
)
async def get_performance_benchmark(
    account_id: str = Query(..., description="Account UUID"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    benchmark_code: str = Query(
        ..., description=f"Benchmark code ({sorted(VALID_BENCHMARK_CODES)})"
    ),
    strategy_id: str | None = Query(
        None, description="Optional strategy UUID for strategy-scoped comparison"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> BenchmarkComparisonView:
    """Get portfolio vs benchmark comparison.

    Portfolio metrics (cumulative return, max drawdown) are reused from the
    existing :func:`get_performance_metrics` pipeline.  Benchmark return and
    drawdown are derived from daily close-price series via
    ``_calc_benchmark_metrics()``.

    Benchmark price data is currently served from in-memory fixtures
    (``_DEFAULT_BENCHMARK_PRICES``).  A persistent price source will be
    connected in a follow-up.

    Parameters
    ----------
    account_id:
        Target account UUID (required).
    start_date:
        Start date in ``YYYY-MM-DD`` format (inclusive, required).
    end_date:
        End date in ``YYYY-MM-DD`` format (inclusive, required).
    benchmark_code:
        Target benchmark code (required). One of ``KOSPI`` or ``KOSDAQ``.
    strategy_id:
        Optional strategy UUID. When provided, portfolio metrics are scoped
        to that strategy's orders.

    Returns
    -------
    BenchmarkComparisonView
        Portfolio-vs-benchmark comparison (13 fields).
    """
    # -- Validate account_id --
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    # -- Validate dates --
    try:
        sd = date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid start_date (use YYYY-MM-DD)"
        )

    try:
        ed = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid end_date (use YYYY-MM-DD)"
        )

    if sd > ed:
        raise HTTPException(
            status_code=400,
            detail="start_date must be on or before end_date",
        )

    # -- Validate benchmark_code --
    if benchmark_code not in VALID_BENCHMARK_CODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid benchmark_code={benchmark_code!r}. "
            f"Valid codes: {sorted(VALID_BENCHMARK_CODES)}",
        )

    # -- Validate optional strategy_id --
    sid: UUID | None = None
    if strategy_id is not None:
        try:
            sid = UUID(strategy_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid strategy_id UUID")

    # -- Build service with in-memory benchmark price repo --
    benchmark_price_repo = InMemoryBenchmarkPriceRepository(
        prices=_DEFAULT_BENCHMARK_PRICES,
    )
    service = BenchmarkComparisonService(
        repos=repos,
        benchmark_price_repo=benchmark_price_repo,
    )
    comparison = await service.get_benchmark_comparison(
        account_id=aid,
        start_date=sd,
        end_date=ed,
        benchmark_code=benchmark_code,
        strategy_id=sid,
    )

    return BenchmarkComparisonView.model_validate(comparison)


@router.get(
    "/performance-benchmark-history",
    response_model=BenchmarkHistoryResponse,
)
async def get_performance_benchmark_history(
    account_id: str = Query(..., description="Account UUID"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    benchmark_code: str = Query(
        default=BENCHMARK_KOSPI,
        description=f"Benchmark code ({sorted(VALID_BENCHMARK_CODES)}). Default: {BENCHMARK_KOSPI}",
    ),
    strategy_id: str | None = Query(
        None, description="Optional strategy UUID for strategy-scoped history"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> BenchmarkHistoryResponse:
    """Get daily portfolio vs benchmark relative performance history.

    Returns a time-series of daily relative performance points from
    ``start_date`` to ``end_date`` (inclusive).  Each point includes
    portfolio/benchmark cumulative return, drawdown, excess return, and
    outperformance streak.

    Parameters
    ----------
    account_id:
        Target account UUID (required).
    start_date:
        Start date in ``YYYY-MM-DD`` format (inclusive, required).
    end_date:
        End date in ``YYYY-MM-DD`` format (inclusive, required).
    benchmark_code:
        Target benchmark code.  Defaults to ``KOSPI``.
    strategy_id:
        Optional strategy UUID.  When provided, portfolio metrics are
        scoped to that strategy's orders.

    Returns
    -------
    BenchmarkHistoryResponse
        Time-series of daily relative performance points.
    """
    # -- Validate account_id --
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    # -- Validate dates --
    try:
        sd = date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid start_date (use YYYY-MM-DD)"
        )

    try:
        ed = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid end_date (use YYYY-MM-DD)"
        )

    if sd > ed:
        raise HTTPException(
            status_code=400,
            detail="start_date must be on or before end_date",
        )

    # -- Validate benchmark_code --
    if benchmark_code not in VALID_BENCHMARK_CODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid benchmark_code={benchmark_code!r}. "
            f"Valid codes: {sorted(VALID_BENCHMARK_CODES)}",
        )

    # -- Validate optional strategy_id --
    sid: UUID | None = None
    if strategy_id is not None:
        try:
            sid = UUID(strategy_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid strategy_id UUID")

    # -- Build service with in-memory benchmark price repo --
    benchmark_price_repo = InMemoryBenchmarkPriceRepository(
        prices=_DEFAULT_BENCHMARK_PRICES,
    )
    service = BenchmarkComparisonService(
        repos=repos,
        benchmark_price_repo=benchmark_price_repo,
    )
    points = await service.get_benchmark_daily_history(
        account_id=aid,
        start_date=sd,
        end_date=ed,
        benchmark_code=benchmark_code,
        strategy_id=sid,
    )

    return BenchmarkHistoryResponse(
        account_id=account_id,
        start_date=sd,
        end_date=ed,
        strategy_id=strategy_id,
        benchmark_code=benchmark_code,
        total_days=len(points),
        points=[RelativeBenchmarkPointView.model_validate(p) for p in points],
    )


@router.get(
    "/paper-go-no-go",
    response_model=GateEvaluationView,
)
async def get_paper_go_no_go(
    account_id: str = Query(..., description="Account UUID"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    strategy_id: str | None = Query(
        None, description="Optional strategy UUID for strategy-scoped evaluation"
    ),
    benchmark_code: str | None = Query(
        None, description=f"Optional benchmark code ({sorted(VALID_BENCHMARK_CODES)})"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> GateEvaluationView:
    """Get Paper Go/No-Go Gate evaluation for an account.

    Aggregates performance, stability and operational-health checks into a
    single ``GO`` / ``HOLD`` / ``NO_GO`` overall status.

    Parameters
    ----------
    account_id:
        Target account UUID (required).
    start_date:
        Start date in ``YYYY-MM-DD`` format (inclusive, required).
    end_date:
        End date in ``YYYY-MM-DD`` format (inclusive, required).
    strategy_id:
        Optional strategy UUID for strategy-scoped evaluation.
    benchmark_code:
        Optional benchmark code (e.g. ``KOSPI``).  When provided, the
        ``MIN_EXCESS_RETURN`` check is included.

    Returns
    -------
    GateEvaluationView
        Complete gate evaluation with overall status and individual checks.
    """
    # -- Validate account_id --
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    # -- Validate dates --
    try:
        sd = date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid start_date (use YYYY-MM-DD)"
        )
    try:
        ed = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid end_date (use YYYY-MM-DD)"
        )
    if sd > ed:
        raise HTTPException(
            status_code=400,
            detail="start_date must be on or before end_date",
        )

    # -- Validate optional strategy_id --
    sid: UUID | None = None
    if strategy_id is not None:
        try:
            sid = UUID(strategy_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid strategy_id UUID")

    # -- Build service --
    settings = AppSettings()
    benchmark_price_repo: InMemoryBenchmarkPriceRepository | None = None
    if benchmark_code is not None:
        benchmark_price_repo = InMemoryBenchmarkPriceRepository(
            prices=_DEFAULT_BENCHMARK_PRICES,
        )
    service = GateEvaluationService(
        repos=repos,
        settings=settings,
        benchmark_price_repo=benchmark_price_repo,
    )
    evaluation = await service.evaluate(
        account_id=aid,
        start_date=sd,
        end_date=ed,
        strategy_id=sid,
        benchmark_code=benchmark_code,
    )
    return GateEvaluationView.model_validate(evaluation)
