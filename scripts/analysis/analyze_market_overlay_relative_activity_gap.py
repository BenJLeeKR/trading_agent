#!/usr/bin/env python3
"""``market_overlay`` × ``eligibility_low_relative_activity`` 원인 분해 — read-only.

``docs/40_action_plans/universe_activity_prefilter_measurement_plan.md`` 기준
34거래일 실측(``scripts/analysis/analyze_universe_activity_gap.py``)에서
``market_overlay``의 `pre-AI 활동성 부족` 차단율(42.27%)이 `core`/
`event_overlay`보다 눈에 띄게 높게 관측됐다. 이 스크립트는 유니버스
hard filter를 구현하기 전에 **왜** 그런지 구조적으로 분해한다. 정책
구현은 하지 않는다 — 순수 read-only 원인 분석 도구다.

**[핵심 구조 확인 결과]** ``analyze_universe_activity_gap.py``는
``relative_activity``를 ``trading.signal_feature_snapshots``에서 run당
1회 배치로 as-of 조인해 얻는다. 이 스크립트는 대신
``trade_decisions.decision_json.deterministic_trigger.metadata``에 이미
박혀 있는 ``volume_surge_ratio``/``turnover_surge_ratio``를 직접 읽는다 —
이것이 그 decision 순간에 ``deterministic_trigger_engine.py``가 실제로
eligibility 판정에 사용한 값이기 때문이다(표본 검증 결과 두 소스가 대체로
일치하지만, ``market_overlay`` 종목 중 일부는 signal feature 자체가
결측(all-null)인 경우가 있어 batched join으로는 값을 못 얻는 케이스가
있었다 — 이런 경우도 놓치지 않기 위해 원본 metadata를 직접 읽는다).

read-only 원칙, 외부 API/KIS 호출 없음, DB 쓰기 없음. universe 정책이나
BUY 정책 코드는 이 스크립트에서 전혀 다루지 않는다.
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
    if v is None:
        return None
    return float(v)


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
    """``trade_decisions``에서 BUY 경로 source_type 행을 직접 조회한다.

    [구조 확인 결과] 여기서는 run 클러스터링을 하지 않는다 — 이 분석은
    "실행 단위"가 아니라 "종목 × 사유 × 시점" 관점이 핵심이라, 개별
    decision 행 단위(중복 포함)로 집계한다. ``analyze_universe_activity_
    gap.py``와 달리 decision_context_id DISTINCT ON도 적용하지 않는다 —
    여기서는 오히려 같은 종목이 얼마나 자주 재평가/재차단되는지(반복
    빈도) 자체가 분석 대상이므로, 중복 제거하면 그 신호가 사라진다.
    """
    raw = await conn.fetch(
        """
        SELECT
            td.symbol,
            td.source_type,
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


def build_source_type_breakdown(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """source_type별 규모, 반복도, 활동성 부족 차단 집중도를 비교한다."""
    out: dict[str, Any] = {}
    for source_type in BUY_PATH_SOURCE_TYPES:
        scoped = [r for r in rows if r["source_type"] == source_type]
        blocked = [r for r in scoped if _is_low_relative_activity_block(r)]
        distinct_all = {r["symbol"] for r in scoped}
        distinct_blocked = {r["symbol"] for r in blocked}
        blocked_dates = sorted({r["business_date"] for r in blocked})

        relative_activity_all = [
            r["relative_activity"] for r in scoped if r["relative_activity"] is not None
        ]
        relative_activity_blocked = [
            r["relative_activity"] for r in blocked if r["relative_activity"] is not None
        ]
        entry_score_blocked = [r["entry_score"] for r in blocked if r["entry_score"] is not None]
        entry_score_unblocked = [
            r["entry_score"]
            for r in scoped
            if r["entry_score"] is not None and not _is_low_relative_activity_block(r)
        ]
        buy_candidate_true = sum(1 for r in blocked if r["buy_candidate"] is True)
        buy_candidate_known = sum(1 for r in blocked if r["buy_candidate"] is not None)

        time_bucket_dist = Counter(r["time_bucket"] for r in blocked)
        missing_signal_data = sum(1 for r in blocked if not r["has_signal_data"])

        # [오해 방지] "동반 사유" — 같은 reasons 리스트에 함께 나타난 다른 항목의
        # 빈도. low_relative_activity 자체와 통과 마커(source_type_allowed 등)는
        # 거의 모든 행에 있으므로, 이 분포를 보면 "레짐 관련 사유와 함께 실패하는
        # 경우"와 "순수 활동성만으로 실패하는 경우"를 구분할 수 있다.
        co_occurring_reason_counts = Counter(
            reason for r in blocked for reason in r["reasons"] if reason != r["block_reason"]
        )

        out[source_type] = {
            "total_rows": len(scoped),
            "distinct_symbols": len(distinct_all),
            "low_relative_activity_block_rows": len(blocked),
            "low_relative_activity_block_distinct_symbols": len(distinct_blocked),
            "rows_per_distinct_blocked_symbol": (
                round(len(blocked) / len(distinct_blocked), 2) if distinct_blocked else None
            ),
            "blocked_distinct_business_dates": len(blocked_dates),
            "blocked_business_date_range": (
                [blocked_dates[0].isoformat(), blocked_dates[-1].isoformat()]
                if blocked_dates
                else None
            ),
            "relative_activity_percentiles_all_rows": _percentiles(relative_activity_all),
            "relative_activity_percentiles_blocked_rows": _percentiles(relative_activity_blocked),
            "entry_score_percentiles_blocked": _percentiles(entry_score_blocked),
            "entry_score_percentiles_unblocked": _percentiles(entry_score_unblocked),
            "buy_candidate_true_ratio_among_blocked": (
                round(buy_candidate_true / buy_candidate_known, 4) if buy_candidate_known else None
            ),
            "time_bucket_distribution_of_blocked": dict(time_bucket_dist),
            "missing_signal_data_among_blocked": missing_signal_data,
            "co_occurring_reason_counts_among_blocked": dict(
                co_occurring_reason_counts.most_common(10)
            ),
        }
    return out


def build_top_repeated_blocked_symbols(
    rows: Sequence[dict[str, Any]], source_type: str, top_n: int = 10
) -> list[dict[str, Any]]:
    """특정 source_type에서 활동성 부족으로 가장 자주 반복 차단된 종목
    top-N과 그 표본 상세를 뽑는다(질적 관찰용)."""
    blocked = [
        r
        for r in rows
        if r["source_type"] == source_type and _is_low_relative_activity_block(r)
    ]
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in blocked:
        by_symbol[r["symbol"]].append(r)

    ranked = sorted(by_symbol.items(), key=lambda kv: len(kv[1]), reverse=True)[:top_n]
    out: list[dict[str, Any]] = []
    for symbol, instances in ranked:
        dates = sorted({i["business_date"] for i in instances})
        sample = instances[0]
        out.append(
            {
                "symbol": symbol,
                "block_row_count": len(instances),
                "distinct_business_dates": len(dates),
                "business_date_range": [dates[0].isoformat(), dates[-1].isoformat()],
                "sample_volume_surge_ratio": sample["volume_surge_ratio"],
                "sample_turnover_surge_ratio": sample["turnover_surge_ratio"],
                "sample_entry_score": sample["entry_score"],
                "sample_buy_candidate": sample["buy_candidate"],
                "sample_reasons": sample["reasons"],
            }
        )
    return out


def build_market_overlay_before_after(
    rows: Sequence[dict[str, Any]], split_date: date
) -> dict[str, Any]:
    """market_overlay 활동성 부족 차단이 특정 날짜 전/후로 어떻게
    달라지는지 비교한다(시간적 집중도 검증용)."""
    scoped = [r for r in rows if r["source_type"] == "market_overlay"]
    before = [r for r in scoped if r["business_date"] <= split_date]
    after = [r for r in scoped if r["business_date"] > split_date]

    def _summary(part: Sequence[dict[str, Any]]) -> dict[str, Any]:
        blocked = [r for r in part if _is_low_relative_activity_block(r)]
        return {
            "total_rows": len(part),
            "blocked_rows": len(blocked),
            "block_rate": round(len(blocked) / len(part), 4) if part else None,
            "distinct_blocked_symbols": len({r["symbol"] for r in blocked}),
        }

    return {
        "split_date": split_date.isoformat(),
        "before_or_on_split": _summary(before),
        "after_split": _summary(after),
    }


async def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "market_overlay x eligibility_low_relative_activity 원인 분해(read-only)"
        )
    )
    parser.add_argument("--date-from", required=True, help="YYYY-MM-DD (KST 기준)")
    parser.add_argument("--date-to", required=True, help="YYYY-MM-DD (KST 기준)")
    parser.add_argument("--account-alias", required=True, help="trading.accounts.account_alias")
    parser.add_argument(
        "--split-date",
        default=None,
        help="market_overlay 시간적 집중도 확인용 분할 날짜(YYYY-MM-DD), 미지정 시 건너뜀",
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

        breakdown = build_source_type_breakdown(rows)
        top_symbols = {
            source_type: build_top_repeated_blocked_symbols(rows, source_type)
            for source_type in BUY_PATH_SOURCE_TYPES
        }

        result: dict[str, Any] = {
            "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "account_alias": args.account_alias,
            "source_type_breakdown": breakdown,
            "top_repeated_low_relative_activity_symbols": top_symbols,
        }

        if args.split_date:
            split_date = datetime.strptime(args.split_date, "%Y-%m-%d").date()
            result["market_overlay_before_after"] = build_market_overlay_before_after(
                rows, split_date
            )

        print("\n=== source_type별 분해 ===")
        print(json.dumps(breakdown, ensure_ascii=False, indent=2, default=str))
        print("\n=== market_overlay 반복 차단 top symbols ===")
        print(json.dumps(top_symbols["market_overlay"], ensure_ascii=False, indent=2, default=str))
        if "market_overlay_before_after" in result:
            print("\n=== market_overlay 분할 전/후 ===")
            print(
                json.dumps(
                    result["market_overlay_before_after"], ensure_ascii=False, indent=2, default=str
                )
            )

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
