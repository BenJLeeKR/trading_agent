#!/usr/bin/env python3
"""`core` 동적 강등(demotion) 규칙 후보 — shadow-only read-only 시뮬레이션.

``docs/40_action_plans/universe_activity_prefilter_measurement_plan.md``의
"`core` 동적 강등 레이어 설계 검토" 절에서 1차안으로 제시된 "최근
``eligibility_low_relative_activity`` 반복 차단 이력 기반 demotion"을,
실제로 어떤 종목이 강등 후보가 되는지 최근 실측 데이터에 **shadow-only로
재생**해본다. **정책 구현이 아니다** — universe 선정/BUY 게이트 코드는
전혀 건드리지 않는다. 이 스크립트가 계산하는 "강등 후보"는 순수 관측치일
뿐, 어떤 운영 동작도 바꾸지 않는다.

핵심 설계 원칙(측정 계획 문서와 동일):
- 정적 core seed(``APPROVED_CORE_UNIVERSE_SYMBOLS`` 등)는 그대로 둔다.
- ``relative_activity`` 원값(volume_surge_ratio/turnover_surge_ratio)을
  직접 규칙 입력으로 쓰지 않는다 — 뒤단 게이트가 이미 내린 실제 차단
  판정(``eligibility_low_relative_activity`` 최종 사유)만 이력으로 재사용
  한다.
- 반복 평가로 인한 "행 개수 부풀림"을 피하기 위해, 판정은 반드시
  **거래일(business_date) 단위로 dedup**한다(하루에 여러 decision이
  있어도 "그날 차단됐는가"는 1건으로 취급한다) — 이전 turn에서 확인한
  분자/분모 granularity 교훈을 그대로 적용한다.

read-only 원칙, 외부 API/KIS 호출 없음, DB 쓰기 없음, `core` 이외
source_type은 다루지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
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


async def resolve_account_id(conn: Any, account_alias: str) -> Any:
    row = await conn.fetchrow(
        "SELECT account_id FROM trading.accounts WHERE account_alias = $1", account_alias
    )
    if row is None:
        raise SystemExit(f"account_alias='{account_alias}'를 찾지 못했습니다.")
    return row["account_id"]


async def fetch_core_daily_status(
    conn: Any, account_id: Any, date_from: date, date_to: date
) -> dict[str, dict[date, str]]:
    """``core`` 종목별 거래일 단위 상태(``blocked``/``passed``)를 복원한다.

    하루 안에 같은 종목이 여러 decision 행으로 반복 평가돼도, 그 날
    **한 번이라도** ``eligibility_low_relative_activity``로 최종 차단된
    적이 있으면 그 날은 ``blocked``로 취급한다(day-level dedup).
    """
    raw = await conn.fetch(
        """
        SELECT
            td.symbol,
            td.created_at,
            td.decision_json->'deterministic_trigger'->'eligibility_reasons' AS reasons
        FROM trading.trade_decisions td
        JOIN trading.decision_contexts dc ON dc.decision_context_id = td.decision_context_id
        WHERE dc.account_id = $1
          AND td.source_type = 'core'
          AND (td.created_at AT TIME ZONE 'Asia/Seoul')::date >= $2
          AND (td.created_at AT TIME ZONE 'Asia/Seoul')::date <= $3
        ORDER BY td.created_at ASC
        """,
        account_id,
        date_from,
        date_to,
    )

    # symbol -> business_date -> "blocked" | "passed"
    by_symbol_day: dict[str, dict[date, str]] = defaultdict(dict)
    for r in raw:
        reasons = r["reasons"]
        if isinstance(reasons, str):
            reasons = json.loads(reasons)
        reasons = reasons or []
        last_reason = reasons[-1] if reasons else None
        is_low_relative_activity_block = last_reason == "eligibility_low_relative_activity"
        symbol = r["symbol"]
        business_date = r["created_at"].astimezone(KST).date()

        current = by_symbol_day[symbol].get(business_date)
        if current == "blocked":
            continue  # 이미 그날 최소 1건 차단 확인됨 — 유지
        by_symbol_day[symbol][business_date] = (
            "blocked" if is_low_relative_activity_block else current or "passed"
        )

    return by_symbol_day


def _business_day_calendar(by_symbol_day: dict[str, dict[date, str]]) -> list[date]:
    days: set[date] = set()
    for day_status in by_symbol_day.values():
        days.update(day_status.keys())
    return sorted(days)


def _trailing_window(calendar: list[date], as_of_index: int, window_size: int) -> list[date]:
    start = max(0, as_of_index - window_size + 1)
    return calendar[start : as_of_index + 1]


def _consecutive_blocked_streak(
    day_status: dict[date, str], calendar: list[date], as_of_index: int
) -> int:
    """``as_of_index``에서 거슬러 올라가며 연속 ``blocked``인 일수를 센다.

    ``absent``(그날 core로 등장 안 함)나 ``passed``를 만나면 즉시 멈춘다.
    """
    streak = 0
    idx = as_of_index
    while idx >= 0:
        d = calendar[idx]
        status = day_status.get(d)
        if status != "blocked":
            break
        streak += 1
        idx -= 1
    return streak


RULE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "A1_ratio5d_ge_80pct": {
        "window": 5,
        "kind": "ratio",
        "threshold": 0.80,
        "desc": "최근 5영업일 중 core 등장일 대비 차단 비율 >= 80%",
    },
    "A2_ratio5d_ge_60pct": {
        "window": 5,
        "kind": "ratio",
        "threshold": 0.60,
        "desc": "최근 5영업일 중 core 등장일 대비 차단 비율 >= 60%",
    },
    "A3_streak_ge_3": {
        "window": None,
        "kind": "streak",
        "threshold": 3,
        "desc": "연속 차단일수(streak) >= 3",
    },
    "A4_streak_ge_2": {
        "window": None,
        "kind": "streak",
        "threshold": 2,
        "desc": "연속 차단일수(streak) >= 2",
    },
    "A5_count5d_ge_3": {
        "window": 5,
        "kind": "count",
        "threshold": 3,
        "desc": "최근 5영업일 중 차단일수 >= 3일(등장 여부와 무관하게 5일 창)",
    },
    "A6_count5d_ge_4_conservative": {
        "window": 5,
        "kind": "count",
        "threshold": 4,
        "desc": "최근 5영업일 중 차단일수 >= 4일(더 보수적인 대조군)",
    },
}


def evaluate_rules(
    by_symbol_day: dict[str, dict[date, str]],
    calendar: list[date],
    eval_date_from: date,
) -> dict[str, list[dict[str, Any]]]:
    """평가 대상 날짜(``eval_date_from`` 이후, 이 스크립트의 "주 구간") 각각에
    대해, 그날 core로 등장한 종목마다 각 규칙을 적용한다.

    ``eval_date_from`` 이전 날짜는 룩백 창 계산에는 쓰이지만, 강등 후보
    "발생"으로는 세지 않는다 — 즉 룩백 재료로는 보조 구간
    (``2026-06-29``~)을 포함해도, 실제 강등 이벤트 집계는 주 구간
    (``2026-07-24``~)에서만 한다.
    """
    date_index = {d: i for i, d in enumerate(calendar)}
    events: dict[str, list[dict[str, Any]]] = {name: [] for name in RULE_DEFINITIONS}

    for symbol, day_status in by_symbol_day.items():
        for d in sorted(day_status.keys()):
            if d < eval_date_from:
                continue
            if day_status[d] == "absent":
                continue
            idx = date_index[d]

            streak = _consecutive_blocked_streak(day_status, calendar, idx)

            for rule_name, rule in RULE_DEFINITIONS.items():
                triggered = False
                appeared_in_window = 0
                blocked_in_window = 0
                if rule["kind"] == "streak":
                    triggered = streak >= rule["threshold"]
                else:
                    window_days = _trailing_window(calendar, idx, rule["window"])
                    for wd in window_days:
                        status = day_status.get(wd)
                        if status is None:
                            continue
                        appeared_in_window += 1
                        if status == "blocked":
                            blocked_in_window += 1
                    if rule["kind"] == "ratio":
                        ratio = (
                            blocked_in_window / appeared_in_window
                            if appeared_in_window
                            else 0.0
                        )
                        triggered = appeared_in_window > 0 and ratio >= rule["threshold"]
                    elif rule["kind"] == "count":
                        triggered = blocked_in_window >= rule["threshold"]

                if triggered:
                    # 오탐 점검용: 강등이 걸린 다음 core 등장일에 실제로
                    # 통과(passed)했는지 확인한다(그렇다면 그 시점에 강등
                    # 했다면 "아까운 종목"을 하루 놓쳤을 수 있다는 신호).
                    next_status = None
                    for future_d in calendar[idx + 1 :]:
                        s = day_status.get(future_d)
                        if s is not None:
                            next_status = (future_d.isoformat(), s)
                            break
                    events[rule_name].append(
                        {
                            "symbol": symbol,
                            "flagged_date": d.isoformat(),
                            "streak_at_flag": streak,
                            "appeared_in_window": appeared_in_window,
                            "blocked_in_window": blocked_in_window,
                            "next_appearance_status": next_status,
                        }
                    )

    return events


def summarize_rule(events: list[dict[str, Any]]) -> dict[str, Any]:
    distinct_symbols = {e["symbol"] for e in events}
    distinct_dates = {e["flagged_date"] for e in events}
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        by_symbol[e["symbol"]].append(e)

    per_symbol_summary = []
    recovered_next_day_count = 0
    for symbol, occ in by_symbol.items():
        occ_sorted = sorted(occ, key=lambda x: x["flagged_date"])
        recoveries = sum(
            1
            for o in occ_sorted
            if o["next_appearance_status"] is not None
            and o["next_appearance_status"][1] == "passed"
        )
        recovered_next_day_count += recoveries
        per_symbol_summary.append(
            {
                "symbol": symbol,
                "flagged_day_count": len(occ_sorted),
                "first_flagged_date": occ_sorted[0]["flagged_date"],
                "last_flagged_date": occ_sorted[-1]["flagged_date"],
                "max_streak_observed": max(o["streak_at_flag"] for o in occ_sorted),
                "recoveries_to_passed_next_appearance": recoveries,
            }
        )
    per_symbol_summary.sort(key=lambda d: d["flagged_day_count"], reverse=True)

    return {
        "flagged_event_count": len(events),
        "distinct_flagged_symbols": len(distinct_symbols),
        "distinct_flagged_dates": len(distinct_dates),
        "recoveries_to_passed_next_appearance_total": recovered_next_day_count,
        "recovery_rate_among_flagged_events": (
            round(recovered_next_day_count / len(events), 4) if events else None
        ),
        "per_symbol_summary": per_symbol_summary,
    }


async def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="core 동적 강등 규칙 후보 shadow-only 시뮬레이션(read-only)"
    )
    parser.add_argument(
        "--lookback-date-from",
        required=True,
        help="룩백 창 계산에 쓸 데이터 시작일(YYYY-MM-DD, 보조 구간 포함 가능)",
    )
    parser.add_argument(
        "--eval-date-from",
        required=True,
        help="강등 이벤트 집계를 시작할 날짜(YYYY-MM-DD, 주 구간 시작일)",
    )
    parser.add_argument("--date-to", required=True, help="YYYY-MM-DD")
    parser.add_argument("--account-alias", required=True, help="trading.accounts.account_alias")
    parser.add_argument("--output-json", default=None, help="결과 JSON 저장 경로")
    args = parser.parse_args(argv)

    lookback_date_from = datetime.strptime(args.lookback_date_from, "%Y-%m-%d").date()
    eval_date_from = datetime.strptime(args.eval_date_from, "%Y-%m-%d").date()
    date_to = datetime.strptime(args.date_to, "%Y-%m-%d").date()

    await create_pool()
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            account_id = await resolve_account_id(conn, args.account_alias)
            by_symbol_day = await fetch_core_daily_status(
                conn, account_id, lookback_date_from, date_to
            )
        calendar = _business_day_calendar(by_symbol_day)
        print(
            f"[수집] core 종목 {len(by_symbol_day)}개, "
            f"거래일 캘린더 {len(calendar)}일"
            f"({calendar[0] if calendar else None}~{calendar[-1] if calendar else None})"
        )

        events = evaluate_rules(by_symbol_day, calendar, eval_date_from)
        summaries = {name: summarize_rule(evs) for name, evs in events.items()}

        result: dict[str, Any] = {
            "lookback_date_from": lookback_date_from.isoformat(),
            "eval_date_from": eval_date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "account_alias": args.account_alias,
            "rule_definitions": RULE_DEFINITIONS,
            "rule_summaries": summaries,
        }

        print("\n=== 규칙별 요약 ===")
        for name, summary in summaries.items():
            print(f"\n--- {name} ({RULE_DEFINITIONS[name]['desc']}) ---")
            print(
                json.dumps(
                    {k: v for k, v in summary.items() if k != "per_symbol_summary"},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print("종목별 요약:")
            print(json.dumps(summary["per_symbol_summary"], ensure_ascii=False, indent=2))

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
