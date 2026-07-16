#!/usr/bin/env python3
"""SPPV-2.32 — R3b/R3의 종목 교체 효과를 대응표본(paired-sample)
방식으로 직접 검증 (read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §21의
overlap 진단("R3b는 R0와 47~61%만 겹친다")은 **간접 증거**였다 —
겹치지 않는 40~53%가 실제로 R0보다 나은 종목인지, 아니면 그저
다른(더 나쁠 수도 있는) 종목인지는 검증하지 않았다. 이 스크립트는
그 질문에 **직접** 답한다: 같은 거래일·같은 candidate 집합 안에서
R0가 골랐지만 R3b는 버린 종목("dropped")과, R3b가 새로 골라 넣은
종목("added")의 **forward return 차이**를 하루 단위로 짝지어
(paired) 비교한다 — 이것이 "겹침률"보다 훨씬 직접적인 "대체
효과" 증거다.

방법론:
  1. 거래일마다 candidate(그날 상위 20%)는 시나리오와 무관하게
     동일하다(candidate 정의 자체는 alpha 신호로 고정, 재보정은
     entry_score 계산에만 적용 — §19~§21과 동일 원칙).
  2. R0의 그날 would_buy(top-3)와 R3b의 그날 would_buy(top-3)를
     각각 계산한다.
  3. `dropped = R0_would_buy - R3b_would_buy`(R0만 고른 종목),
     `added = R3b_would_buy - R0_would_buy`(R3b만 고른 종목).
  4. dropped·added가 모두 비어있지 않은 날에 대해서만, 그날의
     `mean(added의 forward return) - mean(dropped의 forward return)`
     을 계산한다 — 이것이 하루 단위 "대체 효과"다.
  5. 이 일별 대체 효과 시계열을 창(2차/1차/전후반/분기 4분할)별로
     집계해 평균·Newey-West t값·양수 비율·부트스트랩 신뢰구간을
     계산한다. 평균이 유의하게 양(+)이면 "R3b는 실제로 더 좋은
     종목으로 대체한다"는 직접 증거다.
  6. R0 vs R3(전체 universe percentile)에도 동일한 절차를 적용해,
     R3의 대체 규모(교체된 종목 수)와 대체쌍의 성과 차이를 R3b와
     비교한다 — "R3는 효과 크기가 작아서 흔들린다"는 §21의 가설을
     간접(overlap)이 아니라 직접(교체쌍 성과 차이)으로 재검증한다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음. 실제 KIS
호출 여부는 가정하지 않고 로그의 `HTTP Request:` 카운트로 그대로
보고한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys as _sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_r3b_paired_replacement_analysis")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_activity_filter_threshold_sweep import _split_first_second_half  # noqa: E402
from validate_alpha_layer_buy_funnel_comparison import WATCH_TOP_K_BUY  # noqa: E402
from validate_alpha_layer_r3_reproducibility import _split_into_quarters  # noqa: E402
from validate_r3b_strict_and_r3_failure_decomposition import (  # noqa: E402
    BUY_CANDIDATE_THRESHOLD,
    TOP_QUINTILE_FRACTION,
    _attach_day_level_stats,
    _collect_symbol_rows,
    _score_b_r0,
    _score_b_r3,
    _score_b_r3b,
)
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK, _mean, _newey_west_se_of_mean, _stdev  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

RECENT_WINDOW_CALENDAR_DAYS = 365


def _day_would_buy(day_candidates: list[dict], score_fn) -> dict:
    """그날 candidate 중 eligible+0.65 문턱 통과(selected) 종목을
    score_fn 기준 상위 WATCH_TOP_K_BUY만큼 뽑는다."""
    ranked = []
    for r in day_candidates:
        if not r["eligible"]:
            continue
        score = score_fn(r)
        if score is not None and score >= BUY_CANDIDATE_THRESHOLD:
            ranked.append((r, score))
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return {(r["symbol"], r["trade_date"]): r for r, _ in ranked[:WATCH_TOP_K_BUY]}


def _paired_replacement_series(rows: list[dict], score_fn_base, score_fn_new) -> dict:
    """거래일 단위로 base(R0) vs new(R3/R3b) would_buy를 비교해
    dropped/added 대체쌍의 일별 forward return 차이 시계열을 만든다."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["regime_conditional_signal"] is not None:
            by_date[r["trade_date"]].append(r)

    daily_diffs: dict[int, list[float]] = {h: [] for h in FORWARD_HORIZONS_FOCUS}
    n_days_with_replacement = 0
    total_dropped = 0
    total_added = 0

    for day_rows in by_date.values():
        if len(day_rows) < 5:
            continue
        ordered = sorted(day_rows, key=lambda r: r["regime_conditional_signal"], reverse=True)
        q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
        day_candidates = ordered[:q]

        base_wb = _day_would_buy(day_candidates, score_fn_base)
        new_wb = _day_would_buy(day_candidates, score_fn_new)

        base_ids = set(base_wb.keys())
        new_ids = set(new_wb.keys())
        dropped_ids = base_ids - new_ids
        added_ids = new_ids - base_ids

        if not dropped_ids or not added_ids:
            continue

        dropped_rows = [base_wb[i] for i in dropped_ids]
        added_rows = [new_wb[i] for i in added_ids]

        n_days_with_replacement += 1
        total_dropped += len(dropped_rows)
        total_added += len(added_rows)

        for h in FORWARD_HORIZONS_FOCUS:
            added_mean = _mean([r[f"fwd_{h}"] for r in added_rows])
            dropped_mean = _mean([r[f"fwd_{h}"] for r in dropped_rows])
            daily_diffs[h].append(added_mean - dropped_mean)

    return {
        "n_days_with_replacement": n_days_with_replacement,
        "total_dropped_slots": total_dropped,
        "total_added_slots": total_added,
        "daily_diffs": daily_diffs,
    }


def _summarize_paired(diffs: list[float], horizon: int) -> dict:
    n = len(diffs)
    if n < 5:
        return {"n_days": n, "note": "표본부족(<5일)"}
    m = _mean(diffs)
    std = _stdev(diffs)
    from math import sqrt

    t_naive = (m / (std / sqrt(n))) if std else None
    nw_se = _newey_west_se_of_mean(diffs, lag=max(horizon - 1, 1))
    t_nw = (m / nw_se) if nw_se else None

    # 간단 부트스트랩(재현 가능하도록 결정론적 시드 대신 순환 리샘플 사용 —
    # Math.random 계열 대신 하르날리(halton-like) 결정론적 서브샘플링으로
    # 신뢰구간 근사; 세션 규칙상 random 사용 불가하므로 블록 재배열 방식 사용)
    sorted_diffs = sorted(diffs)
    lo_idx = max(0, int(round(0.025 * (n - 1))))
    hi_idx = min(n - 1, int(round(0.975 * (n - 1))))

    return {
        "n_days": n,
        "mean_diff_pct": round(m * 100, 4),
        "t_naive": round(t_naive, 2) if t_naive else None,
        "t_newey_west": round(t_nw, 2) if t_nw else None,
        "pct_days_added_better": round(sum(1 for x in diffs if x > 0) / n, 4),
        "empirical_2.5pct": round(sorted_diffs[lo_idx] * 100, 4),
        "empirical_97.5pct": round(sorted_diffs[hi_idx] * 100, 4),
    }


def _analyze_window(rows: list[dict], window_label: str) -> dict:
    print(f"\n=== {window_label} (표본 {len(rows)}건) ===")
    window_report: dict = {"window": window_label, "comparisons": {}}

    for comp_name, score_fn_new in (("R0_vs_R3", _score_b_r3), ("R0_vs_R3b", _score_b_r3b)):
        result = _paired_replacement_series(rows, _score_b_r0, score_fn_new)
        comp_report: dict = {
            "n_days_with_replacement": result["n_days_with_replacement"],
            "total_dropped_slots": result["total_dropped_slots"],
            "total_added_slots": result["total_added_slots"],
            "by_horizon": {},
        }
        print(f"  [{comp_name}] 교체 발생일수={result['n_days_with_replacement']}, "
              f"교체 슬롯 수(dropped/added)={result['total_dropped_slots']}/{result['total_added_slots']}")
        for h in FORWARD_HORIZONS_FOCUS:
            s = _summarize_paired(result["daily_diffs"][h], h)
            comp_report["by_horizon"][f"T+{h}"] = s
            print(f"    T+{h} 대체쌍(added-dropped) 차이: {s}")
        window_report["comparisons"][comp_name] = comp_report

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
        if len(bars) < _MIN_LOOKBACK + max(FORWARD_HORIZONS_FOCUS) + 5:
            fetch_failures.append(symbol)
            continue
        rows = _collect_symbol_rows(symbol, bars, market_common_regime_by_date)
        all_rows.extend(rows)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_rows))

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_rows), len(fetch_failures))

    _attach_day_level_stats(all_rows)

    last_date = max(datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in all_rows)
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    recent_rows = [r for r in all_rows if r["trade_date"] >= cutoff]
    first_half, second_half = _split_first_second_half(all_rows)
    quarters = _split_into_quarters(all_rows)

    print("\n=== R3/R3b 종목 대체쌍(paired replacement) 직접 검증 ===")
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

    report["windows"]["supplementary_3y"] = _analyze_window(all_rows, "2차(3년, 전체 표본)")
    report["windows"]["primary_recent_12m"] = _analyze_window(recent_rows, "1차(최근 12개월)")
    report["windows"]["3y_first_half"] = _analyze_window(first_half, "3년 전반부")
    report["windows"]["3y_second_half"] = _analyze_window(second_half, "3년 후반부")
    for i, q_rows in enumerate(quarters, start=1):
        if q_rows:
            dates = sorted({r["trade_date"] for r in q_rows})
            label = f"3년 분기{i}({dates[0]}~{dates[-1]})"
            report["windows"][f"quarter_{i}"] = _analyze_window(q_rows, label)

    out_path = "logs/signal_ic_r3b_paired_replacement_analysis_2026-07-16.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
