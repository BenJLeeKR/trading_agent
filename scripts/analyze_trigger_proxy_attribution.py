#!/usr/bin/env python3
"""deterministic trigger 후행 수익률 proxy attribution을 계산한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
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
                COALESCE((td.decision_json#>>'{deterministic_trigger,eligibility_passed}')::boolean, false) AS eligibility_passed,
                NULLIF(td.decision_json#>>'{deterministic_trigger,entry_score}', '')::double precision AS entry_score,
                NULLIF(td.decision_json#>>'{deterministic_trigger,watch_score}', '')::double precision AS watch_score,
                NULLIF(td.decision_json#>>'{deterministic_trigger,ranking_score}', '')::double precision AS ranking_score,
                COALESCE(
                    td.decision_json#>'{deterministic_trigger,metadata,core_risk_off_experiment}',
                    '{}'::jsonb
                ) AS core_risk_off_experiment_json,
                COALESCE(
                    td.decision_json#>'{deterministic_trigger,metadata,event_overlay_experiment}',
                    '{}'::jsonb
                ) AS event_overlay_experiment_json,
                COALESCE(td.decision_json#>'{deterministic_trigger,eligibility_reasons}', '[]'::jsonb) AS eligibility_reasons_json,
                ROW_NUMBER() OVER (
                    PARTITION BY td.symbol, (td.created_at AT TIME ZONE 'Asia/Seoul')::date
                    ORDER BY td.created_at ASC, td.trade_decision_id ASC
                ) AS rn
            FROM trading.trade_decisions td
            JOIN trading.decision_contexts dc
              ON dc.decision_context_id = td.decision_context_id
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
            eligibility_passed,
            entry_score,
            watch_score,
            ranking_score,
            core_risk_off_experiment_json,
            event_overlay_experiment_json,
            eligibility_reasons_json
        FROM ranked
        WHERE rn = 1
        ORDER BY trade_date ASC, symbol ASC
    """
    async with connection() as conn:
        rows = await conn.fetch(sql, account_id, start_date, end_date)
    decisions: list[dict[str, object]] = []
    for row in rows:
        reasons = _coerce_json_list(row["eligibility_reasons_json"])
        core_experiment = _coerce_json_mapping(row["core_risk_off_experiment_json"])
        event_experiment = _coerce_json_mapping(row["event_overlay_experiment_json"])
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
                "eligibility_passed": bool(row["eligibility_passed"]),
                "entry_score": float(row["entry_score"]) if row["entry_score"] is not None else None,
                "watch_score": float(row["watch_score"]) if row["watch_score"] is not None else None,
                "ranking_score": (
                    float(row["ranking_score"]) if row["ranking_score"] is not None else None
                ),
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
        core_risk_off_topk_rows = build_core_risk_off_topk_projection_rows(enriched_rows)
        event_overlay_shadow_rows = build_shadow_experiment_rows(
            enriched_rows,
            experiment_key="event_overlay_experiment",
            bucket_key="event_overlay_shadow_bucket",
        )
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
