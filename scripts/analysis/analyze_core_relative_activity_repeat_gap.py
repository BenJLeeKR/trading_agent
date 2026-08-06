#!/usr/bin/env python3
"""``core`` × ``eligibility_low_relative_activity`` 반복 차단 원인 분해 — read-only.

최근 10영업일(``2026-07-24``~``2026-08-06``) 실측에서 `활동성 부족` 차단이
다시 높게 나타났고, 이번에는 `market_overlay`가 아니라 `core` 경로가 중심
으로 관측됐다. 이 스크립트는
``analyze_market_overlay_relative_activity_gap.py``와 같은 구조(반복 종목
집중도, 잔류 지속성, entry_score/relative_activity 분리, 급등일 vs 평시
비교)를 ``core`` 경로 기준으로 재현한다. 정책 구현은 하지 않는다 — 순수
read-only 원인 분석 도구다.

**[구조 확인 결과]** ``relative_activity``는
``trade_decisions.decision_json.deterministic_trigger.metadata``에 박힌
``volume_surge_ratio``/``turnover_surge_ratio``를 직접 읽는다(as-of
signal_feature_snapshots 배치 조인 대신) — production이 그 decision 순간에
실제로 사용한 값이기 때문이다(``analyze_market_overlay_relative_activity_
gap.py`` 도입 근거와 동일).

**[용어 주의]** 여기서 "등장 decision_context 수"는
``analyze_universe_activity_gap.py``의 클러스터링된 "run"과 다르다 — 이
스크립트는 run 클러스터링을 하지 않고 ``decision_context_id`` 고유값
개수를 그대로 "평가 사이클 횟수"의 근사치로 쓴다(더 세밀한 단위이며,
클러스터링된 run 수보다 크거나 같다).

read-only 원칙, 외부 API/KIS 호출 없음, DB 쓰기 없음.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(str(_REPO_ROOT / ".env"))

from agent_trading.db.connection import close_pool, create_pool, get_pool  # noqa: E402

KST = timezone(timedelta(hours=9))

ACTIVITY_BLOCK_REASONS = frozenset(
    {
        "eligibility_low_average_volume",
        "eligibility_low_turnover",
        "eligibility_low_relative_activity",
    }
)
BUY_PATH_SOURCE_TYPES = ("core", "event_overlay", "market_overlay")


def classify_time_bucket(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=KST)
    else:
        ts = ts.astimezone(KST)
    hm = ts.hour * 60 + ts.minute
    if hm < 9 * 60:
        return "pre_open"
    if hm < 9 * 60 + 30:
        return "open_30m"
    if hm < 15 * 60 + 20:
        return "intraday"
    return "after_close"


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(p * (len(ordered) - 1)))))
    return ordered[idx]


def _percentiles(values: list[float]) -> dict[str, float | None]:
    return {
        "p10": _percentile(values, 0.10),
        "p25": _percentile(values, 0.25),
        "p50": _percentile(values, 0.50),
        "p75": _percentile(values, 0.75),
        "n": len(values),
    }


async def resolve_account_id(conn: Any, account_alias: str) -> Any:
    row = await conn.fetchrow(
        "SELECT account_id FROM trading.accounts WHERE account_alias = $1", account_alias
    )
    if row is None:
        raise SystemExit(f"account_alias='{account_alias}'를 찾지 못했습니다.")
    return row["account_id"]


async def fetch_rows(
    conn: Any, account_id: Any, date_from: date, date_to: date
) -> list[dict[str, Any]]:
    """BUY 경로 source_type 행을 decision 단위(중복 포함)로 직접 조회한다."""
    raw = await conn.fetch(
        """
        SELECT
            td.symbol,
            td.source_type,
            td.decision_context_id,
            td.created_at,
            td.decision_json->'deterministic_trigger'->>'entry_score' AS entry_score,
            td.decision_json->'deterministic_trigger'->>'buy_candidate' AS buy_candidate,
            td.decision_json->'deterministic_trigger'->'eligibility_reasons' AS reasons,
            td.decision_json->'deterministic_trigger'->'metadata'->>'volume_surge_ratio'
                AS volume_surge_ratio,
            td.decision_json->'deterministic_trigger'->'metadata'->>'turnover_surge_ratio'
                AS turnover_surge_ratio,
            td.decision_json->'deterministic_trigger'->'metadata'->>'average_volume_20d'
                AS average_volume_20d,
            td.decision_json->'deterministic_trigger'->'metadata'->>'regime_label'
                AS regime_label,
            td.decision_json->'deterministic_trigger'->'metadata'->>'risk_tone'
                AS risk_tone
        FROM trading.trade_decisions td
        JOIN trading.decision_contexts dc ON dc.decision_context_id = td.decision_context_id
        WHERE dc.account_id = $1
          AND (td.created_at AT TIME ZONE 'Asia/Seoul')::date >= $2
          AND (td.created_at AT TIME ZONE 'Asia/Seoul')::date <= $3
          AND td.source_type = ANY($4::text[])
        ORDER BY td.created_at ASC
        """,
        account_id,
        date_from,
        date_to,
        list(BUY_PATH_SOURCE_TYPES),
    )

    out: list[dict[str, Any]] = []
    for r in raw:
        reasons = r["reasons"]
        if isinstance(reasons, str):
            reasons = json.loads(reasons)
        reasons = reasons or []
        last_reason = reasons[-1] if reasons else None
        vsr = _f(r["volume_surge_ratio"])
        tsr = _f(r["turnover_surge_ratio"])
        relative_activity = None
        if vsr is not None or tsr is not None:
            relative_activity = max(vsr or 0.0, tsr or 0.0)
        created_at: datetime = r["created_at"]
        out.append(
            {
                "symbol": r["symbol"],
                "source_type": r["source_type"],
                "decision_context_id": r["decision_context_id"],
                "created_at": created_at,
                "business_date": created_at.astimezone(KST).date(),
                "time_bucket": classify_time_bucket(created_at),
                "entry_score": _f(r["entry_score"]),
                "buy_candidate": (
                    None if r["buy_candidate"] is None else r["buy_candidate"] == "true"
                ),
                "reasons": reasons,
                "block_reason": last_reason if last_reason in ACTIVITY_BLOCK_REASONS else None,
                "volume_surge_ratio": vsr,
                "turnover_surge_ratio": tsr,
                "relative_activity": relative_activity,
                "average_volume_20d": _f(r["average_volume_20d"]),
                "regime_label": r["regime_label"],
                "risk_tone": r["risk_tone"],
                "has_signal_data": vsr is not None or tsr is not None,
            }
        )
    return out


def _is_low_relative_activity_block(row: dict[str, Any]) -> bool:
    return row["block_reason"] == "eligibility_low_relative_activity"


def build_symbol_persistence(
    rows: Sequence[dict[str, Any]], source_type: str, top_n: int = 20
) -> list[dict[str, Any]]:
    """반복 차단 종목의 등장/차단 지속성을 종목별로 재구성한다.

    "같은 종목이 계속 재선정되는가"(질문 1, 2)에 직접 답하기 위한 표.
    """
    scoped = [r for r in rows if r["source_type"] == source_type]
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in scoped:
        by_symbol[r["symbol"]].append(r)

    result: list[dict[str, Any]] = []
    for symbol, instances in by_symbol.items():
        blocked = [i for i in instances if _is_low_relative_activity_block(i)]
        if not blocked:
            continue
        appearance_dates = sorted({i["business_date"] for i in instances})
        blocked_dates = sorted({i["business_date"] for i in blocked})
        appearance_contexts = {i["decision_context_id"] for i in instances}
        blocked_contexts = {i["decision_context_id"] for i in blocked}
        entry_scores = [i["entry_score"] for i in instances if i["entry_score"] is not None]
        relative_activities = [
            i["relative_activity"] for i in instances if i["relative_activity"] is not None
        ]
        result.append(
            {
                "symbol": symbol,
                "first_appearance_date": appearance_dates[0].isoformat(),
                "last_appearance_date": appearance_dates[-1].isoformat(),
                "distinct_appearance_dates": len(appearance_dates),
                "distinct_appearance_decision_contexts": len(appearance_contexts),
                "distinct_blocked_dates": len(blocked_dates),
                "distinct_blocked_decision_contexts": len(blocked_contexts),
                "total_rows": len(instances),
                "blocked_rows": len(blocked),
                "block_rate_within_symbol": round(len(blocked) / len(instances), 4),
                "entry_score_p50": _percentile(entry_scores, 0.50),
                "relative_activity_p50": _percentile(relative_activities, 0.50),
            }
        )

    result.sort(key=lambda d: d["blocked_rows"], reverse=True)
    return result[:top_n]


def build_period_summary(rows: Sequence[dict[str, Any]], source_type: str) -> dict[str, Any]:
    scoped = [r for r in rows if r["source_type"] == source_type]
    blocked = [r for r in scoped if _is_low_relative_activity_block(r)]
    distinct_all = {r["symbol"] for r in scoped}
    distinct_blocked = {r["symbol"] for r in blocked}

    entry_score_blocked = [r["entry_score"] for r in blocked if r["entry_score"] is not None]
    entry_score_unblocked = [
        r["entry_score"]
        for r in scoped
        if r["entry_score"] is not None and not _is_low_relative_activity_block(r)
    ]
    relative_activity_blocked = [
        r["relative_activity"] for r in blocked if r["relative_activity"] is not None
    ]
    relative_activity_all = [
        r["relative_activity"] for r in scoped if r["relative_activity"] is not None
    ]
    time_bucket_dist = Counter(r["time_bucket"] for r in blocked)
    co_occurring = Counter(
        reason for r in blocked for reason in r["reasons"] if reason != r["block_reason"]
    )
    regime_labels = Counter(r["regime_label"] for r in blocked if r["regime_label"])

    return {
        "total_rows": len(scoped),
        "distinct_symbols": len(distinct_all),
        "blocked_rows": len(blocked),
        "block_rate": round(len(blocked) / len(scoped), 4) if scoped else None,
        "distinct_blocked_symbols": len(distinct_blocked),
        "rows_per_distinct_blocked_symbol": (
            round(len(blocked) / len(distinct_blocked), 2) if distinct_blocked else None
        ),
        "entry_score_percentiles_blocked": _percentiles(entry_score_blocked),
        "entry_score_percentiles_unblocked": _percentiles(entry_score_unblocked),
        "relative_activity_percentiles_blocked": _percentiles(relative_activity_blocked),
        "relative_activity_percentiles_all": _percentiles(relative_activity_all),
        "time_bucket_distribution_of_blocked": dict(time_bucket_dist),
        "regime_label_distribution_of_blocked": dict(regime_labels.most_common(10)),
        "co_occurring_reason_counts_among_blocked": dict(co_occurring.most_common(10)),
    }


def build_daily_core_summary(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """일별 `core` universe 크기/차단/반복집중도를 비교표로 만든다(질문 4)."""
    scoped = [r for r in rows if r["source_type"] == "core"]
    by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for r in scoped:
        by_date[r["business_date"]].append(r)

    out: list[dict[str, Any]] = []
    for business_date in sorted(by_date):
        day_rows = by_date[business_date]
        blocked = [r for r in day_rows if _is_low_relative_activity_block(r)]
        distinct_all = {r["symbol"] for r in day_rows}
        distinct_blocked = {r["symbol"] for r in blocked}
        time_bucket_dist = Counter(r["time_bucket"] for r in blocked)
        regime_labels = Counter(r["regime_label"] for r in blocked if r["regime_label"])
        out.append(
            {
                "business_date": business_date.isoformat(),
                "total_rows": len(day_rows),
                "distinct_symbols": len(distinct_all),
                "blocked_rows": len(blocked),
                "block_rate": round(len(blocked) / len(day_rows), 4) if day_rows else None,
                "distinct_blocked_symbols": len(distinct_blocked),
                "rows_per_distinct_blocked_symbol": (
                    round(len(blocked) / len(distinct_blocked), 2) if distinct_blocked else None
                ),
                "time_bucket_distribution_of_blocked": dict(time_bucket_dist),
                "regime_label_distribution_of_blocked": dict(regime_labels.most_common(5)),
            }
        )
    return out


def build_surge_vs_normal_comparison(
    rows: Sequence[dict[str, Any]], surge_dates: list[date], normal_dates: list[date]
) -> dict[str, Any]:
    """급등일 vs 평시 비교(질문 4) — core 한정."""

    def _subset_summary(dates: list[date]) -> dict[str, Any]:
        scoped = [
            r for r in rows if r["source_type"] == "core" and r["business_date"] in dates
        ]
        blocked = [r for r in scoped if _is_low_relative_activity_block(r)]
        distinct_blocked = {r["symbol"] for r in blocked}
        source_type_all_scope = [
            r for r in rows if r["business_date"] in dates and _is_low_relative_activity_block(r)
        ]
        source_dist = Counter(r["source_type"] for r in source_type_all_scope)
        time_bucket_dist = Counter(r["time_bucket"] for r in blocked)
        relative_activity_blocked = [
            r["relative_activity"] for r in blocked if r["relative_activity"] is not None
        ]
        regime_labels = Counter(r["regime_label"] for r in blocked if r["regime_label"])
        return {
            "dates": [d.isoformat() for d in sorted(dates)],
            "total_rows": len(scoped),
            "distinct_symbols_universe": len({r["symbol"] for r in scoped}),
            "blocked_rows": len(blocked),
            "block_rate": round(len(blocked) / len(scoped), 4) if scoped else None,
            "distinct_blocked_symbols": len(distinct_blocked),
            "rows_per_distinct_blocked_symbol": (
                round(len(blocked) / len(distinct_blocked), 2) if distinct_blocked else None
            ),
            "blocked_source_type_distribution(all source types, not core-only)": dict(
                source_dist
            ),
            "time_bucket_distribution_of_blocked": dict(time_bucket_dist),
            "relative_activity_percentiles_blocked": _percentiles(relative_activity_blocked),
            "regime_label_distribution_of_blocked": dict(regime_labels.most_common(5)),
        }

    return {
        "surge_days": _subset_summary(surge_dates),
        "normal_days": _subset_summary(normal_dates),
    }


async def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="core x eligibility_low_relative_activity 반복 차단 원인 분해(read-only)"
    )
    parser.add_argument("--date-from", required=True, help="YYYY-MM-DD (KST 기준)")
    parser.add_argument("--date-to", required=True, help="YYYY-MM-DD (KST 기준)")
    parser.add_argument("--account-alias", required=True, help="trading.accounts.account_alias")
    parser.add_argument(
        "--surge-dates",
        default="",
        help="급등일 목록(쉼표구분 YYYY-MM-DD) — 지정 시 평시와 비교",
    )
    parser.add_argument(
        "--normal-dates",
        default="",
        help="평시 날짜 목록(쉼표구분 YYYY-MM-DD) — 지정 시 급등일과 비교",
    )
    parser.add_argument("--output-json", default=None, help="결과 JSON 저장 경로")
    args = parser.parse_args(argv)

    date_from = datetime.strptime(args.date_from, "%Y-%m-%d").date()
    date_to = datetime.strptime(args.date_to, "%Y-%m-%d").date()

    await create_pool()
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            account_id = await resolve_account_id(conn, args.account_alias)
            rows = await fetch_rows(conn, account_id, date_from, date_to)
        print(f"[수집] BUY 경로 decision 행 {len(rows)}건 (core/event_overlay/market_overlay)")

        period_summary = {
            source_type: build_period_summary(rows, source_type)
            for source_type in BUY_PATH_SOURCE_TYPES
        }
        core_symbol_persistence = build_symbol_persistence(rows, "core", top_n=20)
        daily_core = build_daily_core_summary(rows)

        result: dict[str, Any] = {
            "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "account_alias": args.account_alias,
            "period_summary_by_source_type": period_summary,
            "core_repeated_blocked_symbol_persistence_top20": core_symbol_persistence,
            "daily_core_summary": daily_core,
        }

        if args.surge_dates and args.normal_dates:
            surge_dates = [
                datetime.strptime(d.strip(), "%Y-%m-%d").date()
                for d in args.surge_dates.split(",")
                if d.strip()
            ]
            normal_dates = [
                datetime.strptime(d.strip(), "%Y-%m-%d").date()
                for d in args.normal_dates.split(",")
                if d.strip()
            ]
            result["surge_vs_normal"] = build_surge_vs_normal_comparison(
                rows, surge_dates, normal_dates
            )

        print("\n=== source_type별 기간 요약 ===")
        print(json.dumps(period_summary, ensure_ascii=False, indent=2, default=str))
        print("\n=== core 반복 차단 종목 지속성 top20 ===")
        print(json.dumps(core_symbol_persistence, ensure_ascii=False, indent=2, default=str))
        print("\n=== 일별 core 요약 ===")
        print(json.dumps(daily_core, ensure_ascii=False, indent=2, default=str))
        if "surge_vs_normal" in result:
            print("\n=== 급등일 vs 평시 ===")
            print(json.dumps(result["surge_vs_normal"], ensure_ascii=False, indent=2, default=str))

        if args.output_json:
            os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
            with open(args.output_json, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
            print(f"\n[출력] 결과 JSON 저장: {args.output_json}")
    finally:
        await close_pool()

    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
