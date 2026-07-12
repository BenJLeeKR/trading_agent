#!/usr/bin/env python3
"""deterministic trigger 후행 수익률 proxy attribution을 계산한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.koreainvestment.token_cache import CachePurpose
from agent_trading.config.settings import AppSettings, KIS_DEFAULT_REST_URLS
from agent_trading.db.connection import close_pool, connection, create_pool
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.signal_backbone import (
    KST,
    TechnicalFeatureSnapshot,
    build_shadow_v5_payload_from_feature_snapshot,
)
from agent_trading.services.deterministic_trigger_engine import (
    _build_relative_activity_score_from_raw,
    _clamp,
    _normalize_signed_score,
)
from agent_trading.services.trigger_proxy_attribution import (
    build_core_risk_off_floor_diagnostic_rows,
    build_core_risk_off_floor_diagnostics_report,
    build_core_risk_off_floor_bucket_rows,
    build_core_risk_off_floor_report,
    build_core_risk_off_floor_v2_bucket_rows,
    build_core_risk_off_floor_v2_diagnostic_rows,
    build_core_risk_off_floor_v2_diagnostics_report,
    build_core_risk_off_floor_v2_report,
    build_core_risk_off_floor_v3_bucket_rows,
    build_core_risk_off_floor_v3_diagnostic_rows,
    build_core_risk_off_floor_v3_diagnostics_report,
    build_core_risk_off_floor_v3_report,
    build_core_risk_off_floor_v5_bucket_rows,
    build_core_risk_off_floor_v5_diagnostic_rows,
    build_core_risk_off_floor_v5_diagnostics_report,
    build_core_risk_off_floor_v5_report,
    DailyPriceBar,
    build_core_risk_off_topk_projection_rows,
    build_shadow_experiment_rows,
    build_trigger_proxy_aggregate_items,
    build_watch_projection_shadow_rows,
    calculate_trigger_proxy_metrics,
    explode_eligibility_reason_rows,
)

logger = logging.getLogger("trigger-proxy-attribution")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="trigger proxy attribution 계산",
    )
    parser.add_argument("--account-id", help="account UUID. 미지정 시 최신 active account")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--output",
        choices=("json", "text"),
        default="text",
        help="출력 형식",
    )
    parser.add_argument(
        "--write-json",
        help="결과 JSON 저장 경로",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=50,
        help="출력 sample 최대 개수",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.2,
        help="symbol별 KIS 일봉 조회 간 sleep",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _coerce_json_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return dict(parsed)
    return {}


def _coerce_json_list(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return list(parsed)
    return []


def _coerce_snapshot_component_scores(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return dict(parsed)
    return {}


def _hydrate_core_risk_off_experiment_from_snapshot(
    *,
    source_type: str,
    core_experiment: dict[str, object],
    snapshot_component_scores: dict[str, object],
) -> dict[str, object]:
    if source_type != "core":
        return core_experiment
    if not snapshot_component_scores:
        return core_experiment

    hydrated = dict(core_experiment or {})
    fallback_keys = (
        "shadow_overall_score_v5",
        "shadow_slow_score_v5",
        "shadow_fast_score_v5",
        "shadow_component_scores_v5",
        "shadow_reason_codes_v5",
        "shadow_diagnostics_v5",
    )
    for key in fallback_keys:
        if hydrated.get(key) is None and snapshot_component_scores.get(key) is not None:
            hydrated[key] = snapshot_component_scores.get(key)
    return hydrated


def _coerce_iso_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _build_snapshot_feature_payload(snapshot_row: dict[str, object]) -> dict[str, object]:
    required_keys = (
        "snapshot_at",
        "bar_count",
        "price_vs_sma_20_pct",
        "price_vs_sma_60_pct",
        "return_3m_pct",
        "volatility_20d_pct",
        "atr_14_pct",
        "rsi_14",
        "volume_surge_ratio",
        "turnover_surge_ratio",
    )
    if all(snapshot_row.get(key) is None for key in required_keys):
        return {}
    snapshot_at = _coerce_iso_datetime(snapshot_row.get("snapshot_at"))
    bar_count = snapshot_row.get("bar_count")
    if snapshot_at is None or bar_count is None:
        return {}
    features = TechnicalFeatureSnapshot(
        symbol=str(snapshot_row.get("symbol") or ""),
        as_of=snapshot_at.astimezone(KST),
        bar_count=int(bar_count),
        sma_5=None,
        sma_20=None,
        sma_60=None,
        price_vs_sma_20_pct=_coerce_float(snapshot_row.get("price_vs_sma_20_pct")),
        price_vs_sma_60_pct=_coerce_float(snapshot_row.get("price_vs_sma_60_pct")),
        return_1m_pct=None,
        return_3m_pct=_coerce_float(snapshot_row.get("return_3m_pct")),
        volatility_20d_pct=_coerce_float(snapshot_row.get("volatility_20d_pct")),
        atr_14_pct=_coerce_float(snapshot_row.get("atr_14_pct")),
        rsi_14=_coerce_float(snapshot_row.get("rsi_14")),
        average_volume_20d=None,
        average_turnover_20d=None,
        volume_surge_ratio=_coerce_float(snapshot_row.get("volume_surge_ratio")),
        turnover_surge_ratio=_coerce_float(snapshot_row.get("turnover_surge_ratio")),
    )
    return build_shadow_v5_payload_from_feature_snapshot(features)


def _enrich_snapshot_component_scores(
    raw_component_scores: object,
    *,
    snapshot_row: dict[str, object],
) -> dict[str, object]:
    component_scores = _coerce_snapshot_component_scores(raw_component_scores)
    has_v5 = any(
        component_scores.get(key) is not None
        for key in (
            "shadow_overall_score_v5",
            "shadow_slow_score_v5",
            "shadow_fast_score_v5",
            "shadow_component_scores_v5",
            "shadow_reason_codes_v5",
            "shadow_diagnostics_v5",
        )
    )
    if has_v5:
        return component_scores
    rebuilt = _build_snapshot_feature_payload(snapshot_row)
    if not rebuilt:
        return component_scores
    enriched = dict(component_scores)
    for key, value in rebuilt.items():
        enriched.setdefault(key, value)
    return enriched


async def _resolve_target_account(
    account_id: str | None,
) -> tuple[UUID | None, str | None]:
    if account_id:
        try:
            parsed = UUID(str(account_id))
        except ValueError as exc:
            raise SystemExit(f"Invalid --account-id UUID: {account_id}") from exc
        async with connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT account_id,
                       COALESCE(account_alias, account_code, broker_account_id::text) AS account_label
                FROM trading.accounts
                WHERE account_id = $1
                LIMIT 1
                """,
                parsed,
            )
        if row is None:
            return None, None
        return parsed, str(row["account_label"]) if row["account_label"] is not None else None

    async with connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT account_id,
                   COALESCE(account_alias, account_code, broker_account_id::text) AS account_label
            FROM trading.accounts
            WHERE LOWER(COALESCE(status, '')) = 'active'
            ORDER BY updated_at DESC NULLS LAST, created_at DESC, account_id ASC
            LIMIT 1
            """
        )
    if row is None:
        return None, None
    return row["account_id"], str(row["account_label"]) if row["account_label"] is not None else None


async def _load_first_symbol_day_decisions(
    account_id: UUID,
    *,
    start_date: date,
    end_date: date,
) -> list[dict[str, object]]:
    sql = """
        WITH ranked AS (
            SELECT
                td.trade_decision_id,
                td.created_at,
                (td.created_at AT TIME ZONE 'Asia/Seoul')::date AS trade_date,
                td.symbol,
                td.market,
                COALESCE(td.source_type, 'unknown') AS source_type,
                LOWER(COALESCE(td.decision_type::text, 'unknown')) AS final_decision_type,
                COALESCE(td.decision_json#>>'{candidate_vs_final,candidate_intent}', 'unknown') AS candidate_intent,
                COALESCE(td.decision_json#>>'{candidate_vs_final,alignment_status}', 'unknown') AS alignment_status,
                COALESCE(td.decision_json#>>'{deterministic_trigger,primary_candidate}', 'unknown') AS primary_candidate,
                COALESCE((td.decision_json#>>'{deterministic_trigger,watch_candidate}')::boolean, false) AS watch_candidate,
                COALESCE((td.decision_json#>>'{deterministic_trigger,buy_candidate}')::boolean, false) AS buy_candidate,
                COALESCE((td.decision_json#>>'{deterministic_trigger,eligibility_passed}')::boolean, false) AS eligibility_passed,
                NULLIF(td.decision_json#>>'{deterministic_trigger,entry_score}', '')::double precision AS entry_score,
                NULLIF(td.decision_json#>>'{deterministic_trigger,watch_score}', '')::double precision AS watch_score,
                NULLIF(td.decision_json#>>'{deterministic_trigger,ranking_score}', '')::double precision AS ranking_score,
                COALESCE(td.decision_json#>'{deterministic_trigger,reason_codes}', '[]'::jsonb) AS trigger_reason_codes_json,
                COALESCE(
                    td.decision_json#>'{deterministic_trigger,metadata,core_risk_off_experiment}',
                    '{}'::jsonb
                ) AS core_risk_off_experiment_json,
                COALESCE(
                    td.decision_json#>'{deterministic_trigger,metadata,event_overlay_experiment}',
                    '{}'::jsonb
                ) AS event_overlay_experiment_json,
                COALESCE(
                    td.decision_json#>>'{deterministic_trigger,metadata,regime_label}',
                    ''
                ) AS trigger_regime_label,
                COALESCE(
                    td.decision_json#>>'{deterministic_trigger,metadata,risk_tone}',
                    ''
                ) AS trigger_risk_tone,
                COALESCE(
                    td.decision_json#>>'{deterministic_trigger,metadata,preferred_strategy}',
                    ''
                ) AS trigger_preferred_strategy,
                COALESCE(
                    (td.decision_json#>>'{deterministic_trigger,metadata,allocation_budget_ok}')::boolean,
                    false
                ) AS trigger_allocation_budget_ok,
                NULLIF(
                    td.decision_json#>>'{portfolio_allocation,max_new_capital_pct}',
                    ''
                )::double precision AS portfolio_max_new_capital_pct,
                NULLIF(
                    td.decision_json#>>'{portfolio_allocation,recommended_max_order_value}',
                    ''
                )::double precision AS portfolio_recommended_max_order_value,
                COALESCE(sfs.component_scores_json, '{}'::jsonb) AS signal_component_scores_json,
                sfs.fast_score AS snapshot_fast_score,
                sfs.slow_score AS snapshot_slow_score,
                sfs.overall_score AS snapshot_overall_score,
                sfs.snapshot_at AS snapshot_at,
                sfs.bar_count AS snapshot_bar_count,
                sfs.price_vs_sma_20_pct AS snapshot_price_vs_sma_20_pct,
                sfs.price_vs_sma_60_pct AS snapshot_price_vs_sma_60_pct,
                sfs.return_3m_pct AS snapshot_return_3m_pct,
                sfs.volatility_20d_pct AS snapshot_volatility_20d_pct,
                sfs.atr_14_pct AS snapshot_atr_14_pct,
                sfs.rsi_14 AS snapshot_rsi_14,
                sfs.average_volume_20d AS snapshot_average_volume_20d,
                sfs.average_turnover_20d AS snapshot_average_turnover_20d,
                sfs.volume_surge_ratio AS snapshot_volume_surge_ratio,
                sfs.turnover_surge_ratio AS snapshot_turnover_surge_ratio,
                COALESCE(td.decision_json#>'{deterministic_trigger,eligibility_reasons}', '[]'::jsonb) AS eligibility_reasons_json,
                latest_order.order_request_id AS order_request_id,
                LOWER(COALESCE(latest_order.status::text, 'unknown')) AS order_status,
                LOWER(COALESCE(latest_attempt.status, 'unknown')) AS execution_status,
                LOWER(COALESCE(latest_attempt.stop_reason, '')) AS execution_stop_reason,
                COALESCE(latest_submit.accepted, false) AS submission_accepted,
                LOWER(COALESCE(latest_submit.error_type, '')) AS submission_error_type,
                ROW_NUMBER() OVER (
                    PARTITION BY td.symbol, (td.created_at AT TIME ZONE 'Asia/Seoul')::date
                    ORDER BY td.created_at ASC, td.trade_decision_id ASC
                ) AS rn
            FROM trading.trade_decisions td
            JOIN trading.decision_contexts dc
              ON dc.decision_context_id = td.decision_context_id
            LEFT JOIN trading.signal_feature_snapshots sfs
              ON sfs.signal_feature_snapshot_id = dc.signal_feature_snapshot_id
            LEFT JOIN LATERAL (
                SELECT
                    o.order_request_id,
                    o.status
                FROM trading.order_requests o
                WHERE o.trade_decision_id = td.trade_decision_id
                ORDER BY o.created_at DESC, o.order_request_id DESC
                LIMIT 1
            ) latest_order ON TRUE
            LEFT JOIN LATERAL (
                SELECT
                    ea.status,
                    ea.stop_reason
                FROM trading.execution_attempts ea
                WHERE ea.trade_decision_id = td.trade_decision_id
                ORDER BY COALESCE(ea.completed_at, ea.started_at, ea.created_at) DESC,
                         ea.execution_attempt_id DESC
                LIMIT 1
            ) latest_attempt ON TRUE
            LEFT JOIN LATERAL (
                SELECT
                    osa.accepted,
                    osa.error_type
                FROM trading.order_submission_attempts osa
                JOIN trading.order_requests o2
                  ON o2.order_request_id = osa.order_request_id
                WHERE o2.trade_decision_id = td.trade_decision_id
                ORDER BY osa.submitted_at DESC, osa.attempt_id DESC
                LIMIT 1
            ) latest_submit ON TRUE
            WHERE dc.account_id = $1
              AND (td.created_at AT TIME ZONE 'Asia/Seoul')::date BETWEEN $2::date AND $3::date
        )
        SELECT
            trade_decision_id,
            created_at,
            trade_date,
            symbol,
            market,
            source_type,
            final_decision_type,
            candidate_intent,
            alignment_status,
            primary_candidate,
            watch_candidate,
            buy_candidate,
            eligibility_passed,
            entry_score,
            watch_score,
            ranking_score,
            trigger_reason_codes_json,
            core_risk_off_experiment_json,
            event_overlay_experiment_json,
            trigger_regime_label,
            trigger_risk_tone,
            trigger_preferred_strategy,
            trigger_allocation_budget_ok,
            portfolio_max_new_capital_pct,
            signal_component_scores_json,
            portfolio_recommended_max_order_value,
            snapshot_fast_score,
            snapshot_slow_score,
            snapshot_overall_score,
            snapshot_at,
            snapshot_bar_count,
            snapshot_price_vs_sma_20_pct,
            snapshot_price_vs_sma_60_pct,
            snapshot_return_3m_pct,
            snapshot_volatility_20d_pct,
            snapshot_atr_14_pct,
            snapshot_rsi_14,
            snapshot_average_volume_20d,
            snapshot_average_turnover_20d,
            snapshot_volume_surge_ratio,
            snapshot_turnover_surge_ratio,
            eligibility_reasons_json,
            order_request_id,
            order_status,
            execution_status,
            execution_stop_reason,
            submission_accepted,
            submission_error_type
        FROM ranked
        WHERE rn = 1
        ORDER BY trade_date ASC, symbol ASC
    """
    async with connection() as conn:
        rows = await conn.fetch(sql, account_id, start_date, end_date)
    decisions: list[dict[str, object]] = []
    for row in rows:
        reasons = _coerce_json_list(row["eligibility_reasons_json"])
        trigger_reason_codes = _coerce_json_list(row["trigger_reason_codes_json"])
        core_experiment = _coerce_json_mapping(row["core_risk_off_experiment_json"])
        event_experiment = _coerce_json_mapping(row["event_overlay_experiment_json"])
        snapshot_component_scores = _enrich_snapshot_component_scores(
            row["signal_component_scores_json"],
            snapshot_row={
                "symbol": row["symbol"],
                "snapshot_at": row["snapshot_at"],
                "bar_count": row["snapshot_bar_count"],
                "price_vs_sma_20_pct": row["snapshot_price_vs_sma_20_pct"],
                "price_vs_sma_60_pct": row["snapshot_price_vs_sma_60_pct"],
                "return_3m_pct": row["snapshot_return_3m_pct"],
                "volatility_20d_pct": row["snapshot_volatility_20d_pct"],
                "atr_14_pct": row["snapshot_atr_14_pct"],
                "rsi_14": row["snapshot_rsi_14"],
                "average_volume_20d": row["snapshot_average_volume_20d"],
                "average_turnover_20d": row["snapshot_average_turnover_20d"],
                "volume_surge_ratio": row["snapshot_volume_surge_ratio"],
                "turnover_surge_ratio": row["snapshot_turnover_surge_ratio"],
            },
        )
        core_experiment = _hydrate_core_risk_off_experiment_from_snapshot(
            source_type=str(row["source_type"]),
            core_experiment=core_experiment,
            snapshot_component_scores=snapshot_component_scores,
        )
        decisions.append(
            {
                "trade_decision_id": str(row["trade_decision_id"]),
                "created_at": row["created_at"].isoformat(),
                "trade_date": row["trade_date"].isoformat(),
                "symbol": str(row["symbol"]),
                "market": str(row["market"]),
                "source_type": str(row["source_type"]),
                "final_decision_type": str(row["final_decision_type"]),
                "candidate_intent": str(row["candidate_intent"]),
                "alignment_status": str(row["alignment_status"]),
                "primary_candidate": str(row["primary_candidate"]),
                "watch_candidate": bool(row["watch_candidate"]),
                "buy_candidate": bool(row["buy_candidate"]),
                "eligibility_passed": bool(row["eligibility_passed"]),
                "entry_score": float(row["entry_score"]) if row["entry_score"] is not None else None,
                "watch_score": float(row["watch_score"]) if row["watch_score"] is not None else None,
                "ranking_score": (
                    float(row["ranking_score"]) if row["ranking_score"] is not None else None
                ),
                "trigger_regime_label": str(row["trigger_regime_label"] or ""),
                "trigger_risk_tone": str(row["trigger_risk_tone"] or ""),
                "trigger_preferred_strategy": str(row["trigger_preferred_strategy"] or ""),
                "trigger_allocation_budget_ok": bool(row["trigger_allocation_budget_ok"]),
                "portfolio_max_new_capital_pct": (
                    float(row["portfolio_max_new_capital_pct"])
                    if row["portfolio_max_new_capital_pct"] is not None
                    else None
                ),
                "trigger_reason_codes": [str(reason) for reason in trigger_reason_codes],
                "snapshot_fast_score": (
                    float(row["snapshot_fast_score"])
                    if row["snapshot_fast_score"] is not None
                    else None
                ),
                "snapshot_slow_score": (
                    float(row["snapshot_slow_score"])
                    if row["snapshot_slow_score"] is not None
                    else None
                ),
                "snapshot_overall_score": (
                    float(row["snapshot_overall_score"])
                    if row["snapshot_overall_score"] is not None
                    else None
                ),
                "snapshot_component_scores": snapshot_component_scores,
                "price_vs_sma_60_pct": (
                    float(row["snapshot_price_vs_sma_60_pct"])
                    if row["snapshot_price_vs_sma_60_pct"] is not None
                    else None
                ),
                "return_3m_pct": (
                    float(row["snapshot_return_3m_pct"])
                    if row["snapshot_return_3m_pct"] is not None
                    else None
                ),
                "average_volume_20d": (
                    float(row["snapshot_average_volume_20d"])
                    if row["snapshot_average_volume_20d"] is not None
                    else None
                ),
                "average_turnover_20d": (
                    float(row["snapshot_average_turnover_20d"])
                    if row["snapshot_average_turnover_20d"] is not None
                    else None
                ),
                "volume_surge_ratio": (
                    float(row["snapshot_volume_surge_ratio"])
                    if row["snapshot_volume_surge_ratio"] is not None
                    else None
                ),
                "turnover_surge_ratio": (
                    float(row["snapshot_turnover_surge_ratio"])
                    if row["snapshot_turnover_surge_ratio"] is not None
                    else None
                ),
                "recommended_max_order_value": (
                    float(row["portfolio_recommended_max_order_value"])
                    if row["portfolio_recommended_max_order_value"] is not None
                    else None
                ),
                "order_request_id": (
                    str(row["order_request_id"]) if row["order_request_id"] is not None else None
                ),
                "order_status": str(row["order_status"]),
                "execution_status": str(row["execution_status"]),
                "execution_stop_reason": str(row["execution_stop_reason"]),
                "submission_accepted": bool(row["submission_accepted"]),
                "submission_error_type": str(row["submission_error_type"]),
                "core_risk_off_experiment": core_experiment,
                "event_overlay_experiment": event_experiment,
                "eligibility_reasons": [str(reason) for reason in reasons],
            }
        )
    return decisions


def _build_market_data_client(settings: AppSettings) -> KISRestClient:
    use_live = bool(settings.kis_live_app_key and settings.kis_live_app_secret)
    if use_live:
        return KISRestClient(
            env="live",
            api_key=str(settings.kis_live_app_key or ""),
            api_secret=str(settings.kis_live_app_secret or ""),
            account_number="",
            account_product_code="",
            base_url=settings.kis_live_info_base_url or KIS_DEFAULT_REST_URLS["live"],
            dev_token_cache_enabled=settings.kis_disclosure_token_cache_enabled,
            dev_token_cache_path=settings.kis_disclosure_token_cache_path,
            cache_purpose=CachePurpose.LIVE_DISCLOSURE_ACCESS_TOKEN,
            approval_cache_enabled=settings.kis_approval_key_cache_enabled,
            approval_cache_path=settings.kis_approval_key_cache_path,
        )
    return KISRestClient(
        env=settings.kis_env,
        api_key=settings.kis_api_key,
        api_secret=settings.kis_api_secret,
        account_number=settings.kis_account_number,
        account_product_code=settings.kis_account_product_code,
        base_url=settings.kis_base_url,
        dev_token_cache_enabled=settings.kis_dev_token_cache_enabled,
        dev_token_cache_path=settings.kis_dev_token_cache_path,
        approval_cache_enabled=settings.kis_approval_key_cache_enabled,
        approval_cache_path=settings.kis_approval_key_cache_path,
    )


async def _fetch_symbol_bars(
    client: KISRestClient,
    *,
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[DailyPriceBar]:
    raw_rows = await client.inquire_daily_itemchartprice(
        symbol=symbol,
        market_code="J",
        start_date=start_date.strftime("%Y%m%d"),
        end_date=end_date.strftime("%Y%m%d"),
        period_div_code="D",
        adjusted_price=True,
    )
    bars: list[DailyPriceBar] = []
    for raw in sorted(raw_rows, key=lambda item: str(item.get("stck_bsop_date", ""))):
        trade_date = str(raw.get("stck_bsop_date", "")).strip()
        close_price = _coerce_float(raw.get("stck_clpr"))
        high_price = _coerce_float(raw.get("stck_hgpr"))
        low_price = _coerce_float(raw.get("stck_lwpr"))
        if not trade_date or close_price is None or high_price is None or low_price is None:
            continue
        bars.append(
            DailyPriceBar(
                trade_date=trade_date,
                close_price=close_price,
                high_price=high_price,
                low_price=low_price,
            )
        )
    return bars


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _select_forward_window(
    bars: Sequence[DailyPriceBar],
    *,
    trade_date: str,
) -> list[DailyPriceBar]:
    for idx, bar in enumerate(bars):
        if bar.trade_date >= trade_date.replace("-", ""):
            return list(bars[idx:])
    return []


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / float(len(values)), 4)


def _build_entry_score_term_breakdown(row: dict[str, object]) -> dict[str, float]:
    overall = _coerce_float(row.get("snapshot_overall_score"))
    fast = _coerce_float(row.get("snapshot_fast_score"))
    slow = _coerce_float(row.get("snapshot_slow_score"))
    regime_label = str(row.get("trigger_regime_label") or "")
    risk_tone = str(row.get("trigger_risk_tone") or "")
    preferred_strategy = str(row.get("trigger_preferred_strategy") or "")
    source_type = str(row.get("source_type") or "")
    max_new_capital_pct = _coerce_float(row.get("portfolio_max_new_capital_pct"))
    volume_surge_ratio = _coerce_float(row.get("volume_surge_ratio"))
    turnover_surge_ratio = _coerce_float(row.get("turnover_surge_ratio"))

    overall_term = 0.45 * _normalize_signed_score(overall)
    fast_term = 0.20 * _normalize_signed_score(fast)
    slow_term = 0.15 * _normalize_signed_score(slow)
    bullish_term = 0.10 if regime_label == "bullish_trend" else 0.0
    risk_on_term = 0.05 if risk_tone == "risk_on" else 0.0
    risk_off_term = -0.15 if risk_tone == "risk_off" else 0.0
    if max_new_capital_pct is None:
        allocation_term = 0.0
    elif max_new_capital_pct > 0:
        allocation_term = min(0.10, max_new_capital_pct / 100.0)
    else:
        allocation_term = -0.20
    strategy_term = (
        0.05
        if preferred_strategy in {"swing_momentum", "event_continuation"}
        else 0.0
    )
    source_term = 0.05 if source_type == "market_overlay" else 0.0
    if source_type == "held_position":
        source_term = -0.35
    relative_activity_bonus = _build_relative_activity_score_from_raw(
        volume_surge_ratio=volume_surge_ratio,
        turnover_surge_ratio=turnover_surge_ratio,
    )
    relative_activity_term = (
        min(0.10, relative_activity_bonus * 0.10)
        if relative_activity_bonus > 0
        else 0.0
    )
    reconstructed_entry_score = _clamp(
        overall_term
        + fast_term
        + slow_term
        + bullish_term
        + risk_on_term
        + risk_off_term
        + allocation_term
        + strategy_term
        + source_term
        + relative_activity_term
    )
    return {
        "overall_term": round(overall_term, 4),
        "fast_term": round(fast_term, 4),
        "slow_term": round(slow_term, 4),
        "bullish_term": round(bullish_term, 4),
        "risk_on_term": round(risk_on_term, 4),
        "risk_off_term": round(risk_off_term, 4),
        "allocation_term": round(allocation_term, 4),
        "strategy_term": round(strategy_term, 4),
        "source_term": round(source_term, 4),
        "relative_activity_term": round(relative_activity_term, 4),
        "reconstructed_entry_score": round(reconstructed_entry_score, 4),
    }


def _summarize_entry_score_cohort(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    scored_rows = [
        row
        for row in rows
        if isinstance(row.get("entry_score"), (int, float))
    ]
    if not scored_rows:
        return {
            "count": 0,
            "entry_score_min": None,
            "entry_score_avg": None,
            "entry_score_max": None,
            "avg_terms": {},
            "top_reason_codes": [],
        }
    entry_scores = [float(row["entry_score"]) for row in scored_rows]
    term_keys = tuple(_build_entry_score_term_breakdown(scored_rows[0]).keys())
    term_means: dict[str, float | None] = {}
    for key in term_keys:
        values = [
            _build_entry_score_term_breakdown(row)[key]
            for row in scored_rows
        ]
        term_means[key] = _mean(values)
    reason_counter: Counter[str] = Counter()
    for row in scored_rows:
        reason_counter.update(str(reason) for reason in row.get("trigger_reason_codes", []))
    return {
        "count": len(scored_rows),
        "entry_score_min": round(min(entry_scores), 4),
        "entry_score_avg": _mean(entry_scores),
        "entry_score_max": round(max(entry_scores), 4),
        "avg_terms": term_means,
        "top_reason_codes": [
            [reason, count]
            for reason, count in reason_counter.most_common(10)
        ],
    }


def _build_entry_score_counterfactual_report(
    rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    scored_rows = [
        row
        for row in rows
        if isinstance(row.get("entry_score"), (int, float))
    ]
    if not scored_rows:
        return {
            "count": 0,
            "cross_if_remove_risk_off_penalty": 0,
            "cross_if_add_strategy_bonus": 0,
            "cross_if_add_full_relative_activity_bonus": 0,
            "cross_if_remove_risk_off_and_add_strategy": 0,
            "cross_if_remove_risk_off_and_add_relative_activity": 0,
        }
    result = {
        "count": len(scored_rows),
        "cross_if_remove_risk_off_penalty": 0,
        "cross_if_add_strategy_bonus": 0,
        "cross_if_add_full_relative_activity_bonus": 0,
        "cross_if_remove_risk_off_and_add_strategy": 0,
        "cross_if_remove_risk_off_and_add_relative_activity": 0,
    }
    for row in scored_rows:
        entry_score = float(row["entry_score"])
        reason_codes = {str(reason) for reason in row.get("trigger_reason_codes", [])}
        remove_risk_off = 0.15 if "trigger_risk_off_penalty" in reason_codes else 0.0
        add_strategy = 0.05 if "trigger_strategy_alignment" not in reason_codes else 0.0
        add_relative_activity = (
            0.10 if "trigger_relative_activity_bonus" not in reason_codes else 0.0
        )
        if entry_score + remove_risk_off >= 0.65:
            result["cross_if_remove_risk_off_penalty"] += 1
        if entry_score + add_strategy >= 0.65:
            result["cross_if_add_strategy_bonus"] += 1
        if entry_score + add_relative_activity >= 0.65:
            result["cross_if_add_full_relative_activity_bonus"] += 1
        if entry_score + remove_risk_off + add_strategy >= 0.65:
            result["cross_if_remove_risk_off_and_add_strategy"] += 1
        if entry_score + remove_risk_off + add_relative_activity >= 0.65:
            result["cross_if_remove_risk_off_and_add_relative_activity"] += 1
    return result


def _build_entry_score_bias_report(
    rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    scored_rows = [
        row
        for row in rows
        if isinstance(row.get("entry_score"), (int, float))
    ]
    core_rows = [row for row in scored_rows if str(row.get("source_type") or "") == "core"]
    watch_candidate_all_rows = [
        row
        for row in scored_rows
        if bool(row.get("watch_candidate"))
    ]
    watch_from_entry_setup_or_ge_052_rows = [
        row
        for row in scored_rows
        if (
            "trigger_watch_from_entry_setup"
            in {str(reason) for reason in row.get("trigger_reason_codes", [])}
        )
        or float(row["entry_score"]) >= 0.52
    ]
    near_buy_floor_rows = [
        row for row in scored_rows if 0.52 <= float(row["entry_score"]) < 0.65
    ]
    top_core_samples = sorted(
        core_rows,
        key=lambda row: float(row.get("entry_score") or 0.0),
        reverse=True,
    )[:10]
    sample_fields = (
        "trade_date",
        "symbol",
        "source_type",
        "entry_score",
        "ranking_score",
        "watch_candidate",
        "eligibility_passed",
        "trigger_regime_label",
        "trigger_risk_tone",
        "trigger_preferred_strategy",
        "trigger_reason_codes",
    )
    return {
        "all": _summarize_entry_score_cohort(scored_rows),
        "core": _summarize_entry_score_cohort(core_rows),
        "watch_candidate_all": _summarize_entry_score_cohort(watch_candidate_all_rows),
        "watch_from_entry_setup_or_ge_052": _summarize_entry_score_cohort(
            watch_from_entry_setup_or_ge_052_rows
        ),
        "near_buy_floor": _summarize_entry_score_cohort(near_buy_floor_rows),
        "near_buy_floor_counterfactual": _build_entry_score_counterfactual_report(
            near_buy_floor_rows
        ),
        "top_core_samples": [
            {field: row.get(field) for field in sample_fields}
            for row in top_core_samples
        ],
    }


async def _run(args: argparse.Namespace) -> int:
    await create_pool()
    try:
        account_id, account_label = await _resolve_target_account(args.account_id)
        start_date = date.fromisoformat(str(args.start_date))
        end_date = date.fromisoformat(str(args.end_date))

        if account_id is None:
            payload = {
                "skipped": True,
                "skipped_reason": "no_active_account",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }
            if args.write_json:
                path = Path(str(args.write_json))
                path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if args.output == "json":
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("skipped_reason=no_active_account")
            return 0

        async with postgres_runtime(run_migrations=False) as runtime:
            settings: AppSettings = runtime["settings"]
            decisions = await _load_first_symbol_day_decisions(
                account_id,
                start_date=start_date,
                end_date=end_date,
            )
            client = _build_market_data_client(settings)
            try:
                symbols = sorted({str(row["symbol"]) for row in decisions})
                series_by_symbol: dict[str, list[DailyPriceBar]] = {}
                fetch_end_date = end_date + timedelta(days=14)
                for idx, symbol in enumerate(symbols):
                    if idx > 0 and args.sleep_seconds > 0:
                        await asyncio.sleep(float(args.sleep_seconds))
                    series_by_symbol[symbol] = await _fetch_symbol_bars(
                        client,
                        symbol=symbol,
                        start_date=start_date,
                        end_date=fetch_end_date,
                    )

                enriched_rows: list[dict[str, object]] = []
                for row in decisions:
                    bars = _select_forward_window(
                        series_by_symbol.get(str(row["symbol"]), []),
                        trade_date=str(row["trade_date"]),
                    )
                    metrics = calculate_trigger_proxy_metrics(bars)
                    enriched_rows.append(
                        {
                            **row,
                            "t1_return_pct": metrics.forward_return_pct_by_horizon.get(1),
                            "t3_return_pct": metrics.forward_return_pct_by_horizon.get(3),
                            "t5_return_pct": metrics.forward_return_pct_by_horizon.get(5),
                            "t3_mfe_pct": metrics.mfe_pct_by_horizon.get(3),
                            "t3_mae_pct": metrics.mae_pct_by_horizon.get(3),
                            "t5_mfe_pct": metrics.mfe_pct_by_horizon.get(5),
                            "t5_mae_pct": metrics.mae_pct_by_horizon.get(5),
                        }
                    )
            finally:
                await client.close()

        eligibility_rows = explode_eligibility_reason_rows(enriched_rows)
        watch_projection_rows = build_watch_projection_shadow_rows(enriched_rows)
        core_risk_off_shadow_rows = build_shadow_experiment_rows(
            enriched_rows,
            experiment_key="core_risk_off_experiment",
            bucket_key="core_risk_off_shadow_bucket",
        )
        core_risk_off_floor_rows = build_core_risk_off_floor_bucket_rows(enriched_rows)
        core_risk_off_floor_diagnostic_rows = build_core_risk_off_floor_diagnostic_rows(
            enriched_rows
        )
        core_risk_off_floor_v2_rows = build_core_risk_off_floor_v2_bucket_rows(enriched_rows)
        core_risk_off_floor_v2_diagnostic_rows = (
            build_core_risk_off_floor_v2_diagnostic_rows(enriched_rows)
        )
        core_risk_off_floor_v3_rows = build_core_risk_off_floor_v3_bucket_rows(enriched_rows)
        core_risk_off_floor_v3_diagnostic_rows = (
            build_core_risk_off_floor_v3_diagnostic_rows(enriched_rows)
        )
        core_risk_off_floor_v5_rows = build_core_risk_off_floor_v5_bucket_rows(enriched_rows)
        core_risk_off_floor_v5_diagnostic_rows = (
            build_core_risk_off_floor_v5_diagnostic_rows(enriched_rows)
        )
        core_risk_off_topk_rows = build_core_risk_off_topk_projection_rows(enriched_rows)
        event_overlay_shadow_rows = build_shadow_experiment_rows(
            enriched_rows,
            experiment_key="event_overlay_experiment",
            bucket_key="event_overlay_shadow_bucket",
        )
        entry_score_bias_report = _build_entry_score_bias_report(enriched_rows)
        payload = {
            "account_id": str(account_id),
            "account_label": account_label,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "sample_count": len(enriched_rows),
            "candidate_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    enriched_rows,
                    bucket_key="primary_candidate",
                )
            ],
            "source_type_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    enriched_rows,
                    bucket_key="source_type",
                )
            ],
            "eligibility_reason_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    eligibility_rows,
                    bucket_key="eligibility_reason",
                )
            ],
            "watch_projection_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    watch_projection_rows,
                    bucket_key="watch_projection_bucket",
                )
            ],
            "core_risk_off_shadow_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    core_risk_off_shadow_rows,
                    bucket_key="core_risk_off_shadow_bucket",
                )
            ],
            "core_risk_off_floor_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    core_risk_off_floor_rows,
                    bucket_key="core_risk_off_floor_bucket",
                )
            ],
            "core_risk_off_floor_report": build_core_risk_off_floor_report(
                enriched_rows
            ),
            "core_risk_off_floor_diagnostics": build_core_risk_off_floor_diagnostics_report(
                enriched_rows,
                sample_limit=max(0, int(args.sample_limit)),
            ),
            "core_risk_off_floor_diagnostic_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    core_risk_off_floor_diagnostic_rows,
                    bucket_key="blocking_reason",
                )
            ],
            "core_risk_off_floor_v2_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    core_risk_off_floor_v2_rows,
                    bucket_key="core_risk_off_floor_v2_bucket",
                )
            ],
            "core_risk_off_floor_v2_report": build_core_risk_off_floor_v2_report(
                enriched_rows
            ),
            "core_risk_off_floor_v2_diagnostics": (
                build_core_risk_off_floor_v2_diagnostics_report(
                    enriched_rows,
                    sample_limit=max(0, int(args.sample_limit)),
                )
            ),
            "core_risk_off_floor_v2_diagnostic_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    core_risk_off_floor_v2_diagnostic_rows,
                    bucket_key="blocking_reason",
                )
            ],
            "core_risk_off_floor_v3_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    core_risk_off_floor_v3_rows,
                    bucket_key="core_risk_off_floor_v3_bucket",
                )
            ],
            "core_risk_off_floor_v3_report": build_core_risk_off_floor_v3_report(
                enriched_rows
            ),
            "core_risk_off_floor_v3_diagnostics": (
                build_core_risk_off_floor_v3_diagnostics_report(
                    enriched_rows,
                    sample_limit=max(0, int(args.sample_limit)),
                )
            ),
            "core_risk_off_floor_v3_diagnostic_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    core_risk_off_floor_v3_diagnostic_rows,
                    bucket_key="blocking_reason",
                )
            ],
            "core_risk_off_floor_v5_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    core_risk_off_floor_v5_rows,
                    bucket_key="core_risk_off_floor_v5_bucket",
                )
            ],
            "core_risk_off_floor_v5_report": build_core_risk_off_floor_v5_report(
                enriched_rows
            ),
            "core_risk_off_floor_v5_diagnostics": (
                build_core_risk_off_floor_v5_diagnostics_report(
                    enriched_rows,
                    sample_limit=max(0, int(args.sample_limit)),
                )
            ),
            "core_risk_off_floor_v5_diagnostic_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    core_risk_off_floor_v5_diagnostic_rows,
                    bucket_key="blocking_reason",
                )
            ],
            "core_risk_off_topk_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    core_risk_off_topk_rows,
                    bucket_key="core_risk_off_topk_bucket",
                )
            ],
            "event_overlay_shadow_items": [
                asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    event_overlay_shadow_rows,
                    bucket_key="event_overlay_shadow_bucket",
                )
            ],
            "entry_score_bias_report": entry_score_bias_report,
            "samples": enriched_rows[: max(0, int(args.sample_limit))],
        }

        if args.write_json:
            path = Path(str(args.write_json))
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if args.output == "json":
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(
                f"sample_count={payload['sample_count']} "
                f"candidate_buckets={len(payload['candidate_items'])} "
                f"source_types={len(payload['source_type_items'])} "
                f"eligibility_buckets={len(payload['eligibility_reason_items'])} "
                f"watch_projection_buckets={len(payload['watch_projection_items'])} "
                f"core_risk_off_shadow_buckets={len(payload['core_risk_off_shadow_items'])} "
                f"core_risk_off_floor_buckets={len(payload['core_risk_off_floor_items'])} "
                f"core_risk_off_topk_buckets={len(payload['core_risk_off_topk_items'])} "
                f"event_overlay_shadow_buckets={len(payload['event_overlay_shadow_items'])}"
            )
            for item in payload["candidate_items"][:10]:
                print(
                    "candidate="
                    f"{item['bucket']} count={item['sample_count']} "
                    f"t3_avg={item['t3_return_pct_avg']} "
                    f"hit_rate={item['positive_t3_hit_rate']}"
                )
            for item in payload["watch_projection_items"][:10]:
                print(
                    "watch_projection="
                    f"{item['bucket']} count={item['sample_count']} "
                    f"t3_avg={item['t3_return_pct_avg']} "
                    f"hit_rate={item['positive_t3_hit_rate']}"
                )
        return 0
    finally:
        await close_pool()


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
