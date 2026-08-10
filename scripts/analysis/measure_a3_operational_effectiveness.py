#!/usr/bin/env python3
"""`core` soft demotion 규칙 A3의 실제 운영 발동 상태 계량 측정 — read-only.

``docs/20_system_analysis/universe_selection_structural_audit.md`` §15가
남긴 다음 과제 — "A5나 다른 규칙을 논하기 전에 A3 자체가 운영 데이터에서
의미 있게 작동하는지 계량 확인" — 를 수행한다. **정책 구현/코드 변경이
아니다.**

핵심 측정 원리
--------------
운영 코드(`UniverseSelectionService._evaluate_core_activity_demotion_
shadow`)가 실제로 계산한 A3 판정 결과는 DB에 저장되지 않는다(메모리
diagnostics에만 존재). 따라서 이 스크립트는 그 판정을 **동일한 규칙으로
재구성**한다 — ``simulate_core_demotion_rules.py``와 동일한 streak 계산
방식을 그대로 재사용한다.

"실제로 배제됐는가"는 아래 관찰로 판정한다: A3는 매 compose 시점에 **그
직전까지의** 차단 이력(연속 3거래일 이상)을 보고 그날 core 내부 정렬을
낮춘다. 따라서 "d일 진입 시점(=d-1일 종가 기준) streak>=3"인 종목이
**d일에 core로 평가된 decision이 단 한 건도 없다면**, 이는 그날 유니버스
freeze에서 실제로 빠졌다는 직접 증거다(decision은 그날 freeze에 포함된
종목에 대해서만 생성되기 때문 — `run_decision_loop.py`의 freeze-then-
evaluate 계약). 반대로 d일에도 core decision이 있다면, A3가 매칭됐어도
`core_cap`과 교차하지 않아(그날 core 후보 풀이 cap보다 작았거나, 순위가
cap 안에 들었거나) 실제 배제 효과는 없었다는 뜻이다.

**한계(반드시 읽을 것)**: d일 결측이 "정확히 core_cap 절단 때문"인지,
liquidity 예외(정지/관리종목 등, `_apply_exclusions`)나 다른 이유 때문인지
이 스크립트는 구분하지 못한다 — "배제 후보"로만 보고하고, 원인을 단정하지
않는다. "오탐률"은 정책 오류 판정이 아니라 **사후 회복 관찰 지표**일
뿐이다.

read-only 원칙, 외부 API/KIS 호출 없음, DB 쓰기 없음.
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
    """종목별 거래일 단위 상태(``blocked``/``passed``)를 복원한다.

    ``simulate_core_demotion_rules.py``의 동일 함수와 같은 day-level
    dedup 규칙을 쓴다 — 하루에 여러 decision이 있어도 그 날 한 번이라도
    ``eligibility_low_relative_activity``로 최종 차단되면 그 날은
    ``blocked``다.
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

    by_symbol_day: dict[str, dict[date, str]] = defaultdict(dict)
    for r in raw:
        reasons = r["reasons"]
        if isinstance(reasons, str):
            reasons = json.loads(reasons)
        reasons = reasons or []
        last_reason = reasons[-1] if reasons else None
        is_blocked = last_reason == "eligibility_low_relative_activity"
        symbol = r["symbol"]
        business_date = r["created_at"].astimezone(KST).date()
        current = by_symbol_day[symbol].get(business_date)
        if current == "blocked":
            continue
        by_symbol_day[symbol][business_date] = "blocked" if is_blocked else current or "passed"

    return dict(by_symbol_day)


def _business_day_calendar(by_symbol_day: dict[str, dict[date, str]]) -> list[date]:
    days: set[date] = set()
    for day_status in by_symbol_day.values():
        days.update(day_status.keys())
    return sorted(days)


def _consecutive_blocked_streak(
    day_status: dict[date, str], calendar: list[date], as_of_index: int
) -> int:
    """``as_of_index``에서 거슬러 올라가며 연속 ``blocked``인 일수를 센다."""
    streak = 0
    idx = as_of_index
    while idx >= 0:
        if day_status.get(calendar[idx]) != "blocked":
            break
        streak += 1
        idx -= 1
    return streak


def compute_a3_events(
    by_symbol_day: dict[str, dict[date, str]],
    calendar: list[date],
    eval_date_from: date,
    eval_date_to: date,
    lookahead_days: int,
) -> list[dict[str, Any]]:
    """평가 구간 각 거래일 진입 시점(=전날 종가 기준)에 A3가 매칭됐는지,
    그리고 그날 실제로 core decision이 있었는지(=배제 후보 여부)를
    이벤트 단위로 계산한다."""
    date_index = {d: i for i, d in enumerate(calendar)}
    events: list[dict[str, Any]] = []

    for symbol, day_status in by_symbol_day.items():
        for i, d in enumerate(calendar):
            if d < eval_date_from or d > eval_date_to:
                continue
            if i == 0:
                continue
            # d일 진입 시점 = d-1일까지의 이력으로 판정(그날 아침 compose
            # 시점에 아직 d일 decision은 없었으므로 d-1까지만 본다).
            entering_streak = _consecutive_blocked_streak(day_status, calendar, i - 1)
            if entering_streak < 3:
                continue

            appeared_on_d = day_status.get(d) is not None
            excluded_candidate = not appeared_on_d

            # 회복 관찰: d일 이후 lookahead_days 거래일 안에서 이 종목이
            # 다시 core로 등장한 첫 날의 상태(관찰 지표, 정책 판정 아님).
            recovery_status = None
            recovery_days_later = None
            for j in range(i, min(i + 1 + lookahead_days, len(calendar))):
                future_d = calendar[j]
                status = day_status.get(future_d)
                if status is not None:
                    recovery_status = status
                    recovery_days_later = j - i
                    break

            events.append(
                {
                    "symbol": symbol,
                    "business_date": d.isoformat(),
                    "entering_streak": entering_streak,
                    "appeared_on_day": appeared_on_d,
                    "excluded_candidate": excluded_candidate,
                    "recovery_status_within_lookahead": recovery_status,
                    "recovery_days_later": recovery_days_later,
                }
            )

    return events


def summarize(events: list[dict[str, Any]], lookahead_days: int) -> dict[str, Any]:
    total = len(events)
    distinct_symbols = {e["symbol"] for e in events}
    distinct_dates = {e["business_date"] for e in events}
    excluded_candidate_events = [e for e in events if e["excluded_candidate"]]
    not_excluded_events = [e for e in events if not e["excluded_candidate"]]

    recoverable = [
        e for e in events if e["recovery_status_within_lookahead"] is not None
    ]
    recovered = [
        e for e in recoverable if e["recovery_status_within_lookahead"] == "passed"
    ]

    by_date: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "excluded_candidate": 0})
    for e in events:
        by_date[e["business_date"]]["total"] += 1
        if e["excluded_candidate"]:
            by_date[e["business_date"]]["excluded_candidate"] += 1

    by_symbol: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "excluded_candidate": 0})
    for e in events:
        by_symbol[e["symbol"]]["total"] += 1
        if e["excluded_candidate"]:
            by_symbol[e["symbol"]]["excluded_candidate"] += 1

    return {
        "a3_matched_event_count": total,
        "a3_matched_distinct_symbols": len(distinct_symbols),
        "a3_matched_distinct_business_dates": len(distinct_dates),
        "excluded_candidate_event_count": len(excluded_candidate_events),
        "excluded_candidate_rate": (
            round(len(excluded_candidate_events) / total, 4) if total else None
        ),
        "not_excluded_event_count": len(not_excluded_events),
        "not_excluded_rate": (
            round(len(not_excluded_events) / total, 4) if total else None
        ),
        "recovery_observation": {
            "lookahead_business_days": lookahead_days,
            "recoverable_event_count": len(recoverable),
            "recovered_to_passed_count": len(recovered),
            "recovery_rate_among_recoverable": (
                round(len(recovered) / len(recoverable), 4) if recoverable else None
            ),
            "note": (
                "이 지표는 정책 오류 판정이 아니라 사후 회복 관찰 지표다 — "
                "회복률이 높다고 A3가 틀렸다는 뜻이 아니며, 낮다고 A3가 "
                "맞다는 뜻도 아니다."
            ),
        },
        "by_business_date": dict(sorted(by_date.items())),
        "top_symbols_by_event_count": sorted(
            ({"symbol": k, **v} for k, v in by_symbol.items()),
            key=lambda x: x["total"],
            reverse=True,
        )[:15],
    }


async def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="core soft demotion A3의 실제 운영 발동 상태 계량 측정(read-only)"
    )
    parser.add_argument(
        "--date-from", required=True, help="평가 구간 시작일(YYYY-MM-DD, KST)"
    )
    parser.add_argument("--date-to", required=True, help="평가 구간 종료일(YYYY-MM-DD, KST)")
    parser.add_argument(
        "--lookback-buffer-days",
        type=int,
        default=15,
        help="streak 계산용 룩백 여유(캘린더일, 기본 15 — 5거래일 이상 확보)",
    )
    parser.add_argument(
        "--lookahead-days",
        type=int,
        default=3,
        help="회복 관찰 창(거래일 기준, 기본 3)",
    )
    parser.add_argument("--account-alias", default="Entrypoint Paper")
    parser.add_argument("--output-json", default=None)
    args = parser.parse_args(argv)

    eval_date_from = datetime.strptime(args.date_from, "%Y-%m-%d").date()
    eval_date_to = datetime.strptime(args.date_to, "%Y-%m-%d").date()
    fetch_date_from = eval_date_from - timedelta(days=args.lookback_buffer_days)
    # 회복 관찰이 평가 구간 밖으로 넘어갈 수 있으므로 조회 범위를 넉넉히 확보.
    fetch_date_to = eval_date_to + timedelta(days=args.lookahead_days * 3)

    await create_pool()
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            account_id = await resolve_account_id(conn, args.account_alias)
            by_symbol_day = await fetch_core_daily_status(
                conn, account_id, fetch_date_from, fetch_date_to
            )
        calendar = _business_day_calendar(by_symbol_day)
        print(
            f"[수집] core 종목 {len(by_symbol_day)}개, "
            f"거래일 캘린더 {len(calendar)}일"
            f"({calendar[0] if calendar else None}~{calendar[-1] if calendar else None})"
        )

        events = compute_a3_events(
            by_symbol_day, calendar, eval_date_from, eval_date_to, args.lookahead_days
        )
        summary = summarize(events, args.lookahead_days)

        result = {
            "eval_date_range": {"from": eval_date_from.isoformat(), "to": eval_date_to.isoformat()},
            "account_alias": args.account_alias,
            "lookback_buffer_days": args.lookback_buffer_days,
            "lookahead_days": args.lookahead_days,
            "summary": summary,
            "events": events,
        }

        print("\n=== A3 운영 발동 요약 ===")
        print(
            json.dumps(
                {k: v for k, v in summary.items() if k not in ("by_business_date", "top_symbols_by_event_count")},
                ensure_ascii=False,
                indent=2,
            )
        )
        print("\n=== 일별 분포 ===")
        print(json.dumps(summary["by_business_date"], ensure_ascii=False, indent=2))
        print("\n=== 종목별 상위 ===")
        print(json.dumps(summary["top_symbols_by_event_count"], ensure_ascii=False, indent=2))

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
