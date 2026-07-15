#!/usr/bin/env python3
"""SPPV-2.20 후속 — A/B regime 판정이 갈린 표본만 분리해 direct 비교
(read-only).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §10.5(다음
단계 1, 2) 참고.

§10(SPPV-2.20)은 "변형 A(종목별)/변형 B(시장 공통) 각각의 eligibility
통과군"을 **독립적으로** baseline과 비교했다 — 그러나 이 방식은 A와 B가
공통으로 통과시키는 표본(둘 다 동의하는 부분)이 두 평균에 섞여 들어가,
"A와 B가 서로 다르게 판단한 표본에서 어느 쪽이 옳았는가"를 직접 보여주지
못한다. 이 스크립트는 새 방법론을 만들지 않고, 기존 §10 스크립트의 표본
수집 함수(`_collect_symbol_rows`)를 그대로 재사용해 다음을 추가한다.

1. 같은 종목-거래일 표본을 **4개 배타적 집합**으로 분해한다:
   `A_only`(A만 통과)/`B_only`(B만 통과)/`both`(둘 다 통과)/
   `neither`(둘 다 탈락). `A_only`와 `B_only`가 바로 "두 정의가 서로
   다르게 판단한" 표본이다 — 공격형 관점에서 중요한 질문은 "B가
   A보다 더 많이 걸러낸 종목(`A_only`, 즉 A는 사도 된다고 했지만 B는
   안 된다고 한 종목)이 실제로 forward return이 나빴는가"다.
2. `A_only`와 `B_only`의 forward return을 각각 요약하고, **일자별
   짝비교(day-matched paired difference)**를 계산한다 — 그날
   `A_only`/`B_only` 둘 다 표본이 있는 날만 골라
   `일별 diff = mean(B_only 그날 수익률) - mean(A_only 그날 수익률)`
   시리즈를 만들고, 기존 quintile spread와 **동일한 방법**(일별 평균
   → Newey-West 보정 t-검정)으로 유의성을 검정한다 — 새 통계 기법을
   도입하지 않고 SPPV 트랙 전체가 써온 방법을 그대로 재사용한다.
3. 1차(최근 12개월)/2차(3년) 이원 기준(§16)을 그대로 적용해 동일
   비교를 두 창에서 반복한다.

DB write / 주문 경로 / 실시간 구독 없음. 3년 캐시를 재사용하며, 실제
KIS 호출 여부는 가정하지 않고 로그의 `HTTP Request:` 카운트로 그대로
보고한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_entry_score_regime_definition_ab_diff")

_KST = timezone(timedelta(hours=9))

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v2 import _mean, _newey_west_se_of_mean, _stdev  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)
from validate_entry_score_regime_definition_comparison import _collect_symbol_rows  # noqa: E402

RECENT_WINDOW_CALENDAR_DAYS = 365


def _summarize_series(xs: list[float], horizon: int, *, is_pct: bool = True) -> dict:
    n = len(xs)
    if n < 5:
        return {"n": n, "note": "표본부족(<5)"}
    m = _mean(xs)
    std = _stdev(xs)
    from math import sqrt

    t_naive = (m / (std / sqrt(n))) if std else None
    nw_se = _newey_west_se_of_mean(xs, lag=max(horizon - 1, 1))
    t_nw = (m / nw_se) if nw_se else None
    return {
        "n": n,
        "mean_pct": round(m * 100, 4) if is_pct else round(m, 4),
        "t_naive": round(t_naive, 2) if t_naive else None,
        "t_newey_west": round(t_nw, 2) if t_nw else None,
        "pct_positive": round(sum(1 for x in xs if x > 0) / n, 4),
    }


def _day_matched_paired_diff(a_only_rows: list[dict], b_only_rows: list[dict], key: str) -> list[float]:
    """그날 A_only/B_only 둘 다 존재하는 날만 골라 (B평균 - A평균) 일별 시리즈를 만든다."""
    a_by_date: dict[str, list[float]] = defaultdict(list)
    b_by_date: dict[str, list[float]] = defaultdict(list)
    for r in a_only_rows:
        a_by_date[r["trade_date"]].append(r[key])
    for r in b_only_rows:
        b_by_date[r["trade_date"]].append(r[key])

    diffs: list[float] = []
    for d in sorted(set(a_by_date) & set(b_by_date)):
        a_mean = _mean(a_by_date[d])
        b_mean = _mean(b_by_date[d])
        if a_mean is not None and b_mean is not None:
            diffs.append(b_mean - a_mean)
    return diffs


def _classify_and_report(rows: list[dict], window_label: str) -> dict:
    # 시장 공통 라벨(B 판정)이 존재하는 표본만 4개 집합 분해 대상으로 삼는다
    # (없으면 B 판정 자체가 미정이라 A_only/B_only/both/neither 어디에도
    # 넣을 수 없다).
    evaluable = [r for r in rows if r["market_common_regime_label"] is not None]
    a_only = [r for r in evaluable if r["eligible_a_per_symbol"] and not r["eligible_b_market_common"]]
    b_only = [r for r in evaluable if r["eligible_b_market_common"] and not r["eligible_a_per_symbol"]]
    both = [r for r in evaluable if r["eligible_a_per_symbol"] and r["eligible_b_market_common"]]
    neither = [r for r in evaluable if not r["eligible_a_per_symbol"] and not r["eligible_b_market_common"]]

    print(f"\n--- {window_label} ---")
    print(f"전체 표본(시장 공통 라벨 존재): {len(evaluable)}건")
    print(f"A_only={len(a_only)}, B_only={len(b_only)}, both={len(both)}, neither={len(neither)}")

    window_report: dict = {
        "window": window_label,
        "counts": {"A_only": len(a_only), "B_only": len(b_only), "both": len(both), "neither": len(neither)},
        "by_horizon": {},
    }

    for h in FORWARD_HORIZONS_FOCUS:
        key = f"fwd_{h}"
        print(f"\n  [T+{h}]")
        entry: dict = {}
        for label, group in [("A_only", a_only), ("B_only", b_only), ("both", both), ("neither", neither)]:
            summary = _summarize_series([r[key] for r in group], h)
            entry[label] = summary
            print(f"    {label}: {summary}")

        diffs = _day_matched_paired_diff(a_only, b_only, key)
        diff_summary = _summarize_series(diffs, h)
        entry["day_matched_paired_diff_B_minus_A"] = diff_summary
        print(f"    일별 짝비교(B_only평균-A_only평균) 시리즈: n_days={diff_summary.get('n')}, "
              f"{diff_summary}")

        window_report["by_horizon"][f"T+{h}"] = entry

    return window_report


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")

    bench_bars = await _fetch_extended_bars(client, BENCHMARK_SYMBOL)
    market_common_regime_by_date, _ = _build_benchmark_daily_series(bench_bars)
    if not market_common_regime_by_date:
        raise SystemExit("시장 공통 국면 계산 실패")

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})
    all_rows: list[dict] = []
    fetch_failures: list[str] = []
    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        if len(bars) < 61 + max(FORWARD_HORIZONS_FOCUS) + 5:
            fetch_failures.append(symbol)
            continue
        rows = _collect_symbol_rows(symbol, bars, market_common_regime_by_date)
        all_rows.extend(rows)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_rows))

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_rows), len(fetch_failures))

    last_date = max(datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in all_rows)
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    recent_rows = [r for r in all_rows if r["trade_date"] >= cutoff]

    print("\n=== A/B regime 판정 불일치 표본(A_only/B_only) 직접 비교 ===")
    print(f"전체 3년 표본: {len(all_rows)}건, 최근 12개월(cutoff={cutoff}) 표본: {len(recent_rows)}건")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_rows),
        "total_rolling_samples_recent_12m": len(recent_rows),
        "recent_window_cutoff": cutoff,
        "windows": {},
    }

    report["windows"]["supplementary_3y"] = _classify_and_report(all_rows, "2차(3년, 전체 표본)")
    report["windows"]["primary_recent_12m"] = _classify_and_report(recent_rows, "1차(최근 12개월)")

    out_path = "logs/signal_ic_entry_score_regime_ab_diff_2026-07-15.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
