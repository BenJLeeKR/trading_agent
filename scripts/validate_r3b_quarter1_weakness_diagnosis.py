#!/usr/bin/env python3
"""SPPV-2.43 — R3b `Conditional Go`의 가장 약한 고리(분기1 t_NW
약화) 정밀 점검 (read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §32.6(다음
단계 2 — 분기1 t_NW 약화(0.96) 우선 재확인) 참고.

**이번 턴이 검증하는 정확한 질문**: §32(SPPV-2.42)가 strategy_
selection을 실제 반영한 뒤 분기1 T+20의 t_NW가 1.31→0.96으로
더 약해졌다 — 이 약화가 (a) R3b의 방향성 우위 자체가 무너진
것인지(mean이 음수로 반전되거나 표본이 극단적으로 줄었는지), 아니면
(b) 표본 수/분산 문제로 통계적 신뢰도만 낮아진 것인지, 그리고 (c)
분기1이 다른 분기와 구조적으로 다른 국면 구성을 가지고 있어서
`regime_conditional_signal`(risk_adj_momentum_3m vs reversal_1m)의
정의 자체가 자주 바뀌는 구간인지를 확인한다.

방법론: §32의 point-in-time 파이프라인(strategy_selection 반영,
`validate_r3b_point_in_time_pipeline_shadow.py`)을 재실행하지 않고
그 row-collection 함수만 재사용해 분기1을 거래일 단위로 분해한다
(§24~§26의 day-group 분해 방법론을 재사용, 분기1에 처음 적용).
분기2·분기3과 비교해 분기1만의 구조적 차이(국면 분포, 표본 수,
스왑 발생 패턴)가 있는지도 함께 확인한다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음. 실제 KIS
호출 여부는 가정하지 않고 로그의 `HTTP Request:` 카운트로 그대로
보고한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys as _sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_r3b_quarter1_weakness_diagnosis")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_alpha_layer_r3_reproducibility import _split_into_quarters  # noqa: E402
from validate_r3b_point_in_time_pipeline_shadow import (  # noqa: E402
    _attach_candidate_only_percentile,
    _collect_symbol_rows_with_strategy,
    _score_a,
    _score_b_r0,
    _score_b_r3b,
)
from validate_alpha_layer_score_rescaling_comparison import _attach_day_level_rescaled_scores  # noqa: E402
from validate_r3b_day_concentration_and_effect_decomposition import (  # noqa: E402
    TOP_DECILE_FRACTION,
    _build_day_groups,
    _day_swap_count,
    _pooled_summary_from_days,
)
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK, _mean  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

QUARTER_LABELS = {1: "분기1", 2: "분기2", 3: "분기3"}


def _paired_effect_for_day(dg: dict, h: int) -> float | None:
    if not dg["added_rows"] or not dg["dropped_rows"]:
        return None
    added_mean = _mean([r[f"fwd_{h}"] for r in dg["added_rows"]])
    dropped_mean = _mean([r[f"fwd_{h}"] for r in dg["dropped_rows"]])
    return round((added_mean - dropped_mean) * 100, 4)


def _regime_distribution(rows: list[dict]) -> dict:
    return dict(Counter(r["market_common_regime"] for r in rows))


def _would_buy_summary(rows: list[dict], score_fn) -> dict:
    """§20의 funnel 정의(candidate quintile은 여기선 이미 quintile
    컷된 row가 아니므로 재현하지 않고, would_buy만 재구성)."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["regime_conditional_signal"] is not None:
            by_date[r["trade_date"]].append(r)

    would_buy_rows: list[dict] = []
    for day_rows in by_date.values():
        if len(day_rows) < 5:
            continue
        ordered = sorted(day_rows, key=lambda r: r["regime_conditional_signal"], reverse=True)
        q = max(1, int(len(ordered) * 0.20))
        day_candidates = ordered[:q]
        ranked = []
        for r in day_candidates:
            if not r["eligible"]:
                continue
            score = score_fn(r)
            if score is not None and score >= 0.65:
                ranked.append((r, score))
        ranked.sort(key=lambda pair: pair[1], reverse=True)
        would_buy_rows.extend(r for r, _ in ranked[:3])

    summary: dict = {"would_buy_n": len(would_buy_rows), "by_horizon": {}}
    for h in FORWARD_HORIZONS_FOCUS:
        xs = [r[f"fwd_{h}"] for r in would_buy_rows]
        if len(xs) < 5:
            summary["by_horizon"][f"T+{h}"] = {"n": len(xs), "note": "표본부족"}
            continue
        from validate_signal_predictive_power_v2 import _newey_west_se_of_mean, _stdev
        m = _mean(xs)
        std = _stdev(xs)
        from math import sqrt
        nw_se = _newey_west_se_of_mean(xs, lag=max(h - 1, 1))
        t_nw = (m / nw_se) if nw_se else None
        mfe = _mean([r[f"mfe_{h}"] for r in would_buy_rows])
        mae = _mean([r[f"mae_{h}"] for r in would_buy_rows])
        summary["by_horizon"][f"T+{h}"] = {
            "n": len(xs),
            "mean_pct": round(m * 100, 4),
            "t_newey_west": round(t_nw, 2) if t_nw else None,
            "pct_positive": round(sum(1 for x in xs if x > 0) / len(xs), 4),
            "mfe_mean_pct": round(mfe * 100, 4),
            "mae_mean_pct": round(mae * 100, 4),
        }
    return summary, would_buy_rows


def _diagnose_quarter(rows: list[dict], label: str) -> dict:
    print(f"\n=== {label} 구조 진단 (표본 {len(rows)}건) ===")
    regime_dist = _regime_distribution(rows)
    print(f"  국면 분포: {regime_dist}")

    r0_summary, r0_wb = _would_buy_summary(rows, _score_b_r0)
    r3b_summary, r3b_wb = _would_buy_summary(rows, _score_b_r3b)
    print(f"  R0 would_buy={r0_summary['would_buy_n']}, R3b would_buy={r3b_summary['would_buy_n']}")
    for h in FORWARD_HORIZONS_FOCUS:
        print(f"    T+{h} R0: {r0_summary['by_horizon'].get(f'T+{h}')}")
        print(f"    T+{h} R3b: {r3b_summary['by_horizon'].get(f'T+{h}')}")

    day_groups = _build_day_groups(rows, _score_b_r0, _score_b_r3b)
    swap_days = [dg for dg in day_groups if dg["dropped_rows"] and dg["added_rows"]]
    ranked_swap_days = sorted(swap_days, key=_day_swap_count, reverse=True)
    n_swap_days = len(swap_days)
    print(f"  스왑 발생일: {n_swap_days}건")

    result: dict = {
        "label": label,
        "n_rows": len(rows),
        "regime_distribution": regime_dist,
        "r0_would_buy": r0_summary,
        "r3b_would_buy": r3b_summary,
        "n_swap_days": n_swap_days,
        "by_horizon_day_level": {},
    }

    for h in FORWARD_HORIZONS_FOCUS:
        full_summary = _pooled_summary_from_days(day_groups, h)
        paired_effects = [v for v in (_paired_effect_for_day(dg, h) for dg in swap_days) if v is not None]
        paired_mean = round(_mean(paired_effects), 4) if paired_effects else None

        top_n = max(1, int(n_swap_days * TOP_DECILE_FRACTION))
        top_days = ranked_swap_days[:top_n]
        top_dates = {dg["trade_date"] for dg in top_days}
        rest_days = [d for d in day_groups if d["trade_date"] not in top_dates]
        rest_summary = _pooled_summary_from_days(rest_days, h)
        remaining_pct = None
        if full_summary.get("aggregate_diff_pct"):
            remaining_pct = round(rest_summary.get("aggregate_diff_pct", 0) / full_summary["aggregate_diff_pct"] * 100, 1)

        # 스왑일 중 양(+)/음(-) 분포
        pos_days = sum(1 for v in paired_effects if v > 0)
        neg_days = sum(1 for v in paired_effects if v < 0)

        print(f"  [T+{h}] pooled aggregate_diff={full_summary.get('aggregate_diff_pct')}%p, "
              f"paired 평균={paired_mean}%p, 스왑일 중 양(+)={pos_days}건/음(-)={neg_days}건, "
              f"상위10%일 제거후 잔존={remaining_pct}%")

        result["by_horizon_day_level"][f"T+{h}"] = {
            "aggregate_diff_pct": full_summary.get("aggregate_diff_pct"),
            "replacement_effect_pct": full_summary.get("replacement_effect_pct"),
            "composition_effect_pct": full_summary.get("composition_effect_pct"),
            "paired_mean_pct": paired_mean,
            "n_swap_days_positive": pos_days,
            "n_swap_days_negative": neg_days,
            "top_decile_day_remaining_pct": remaining_pct,
        }

    # 상위 10개 스왑일 상세(분기1 진단 핵심)
    top_detail = []
    for rank, dg in enumerate(ranked_swap_days[:10], start=1):
        entry = {"rank": rank, "trade_date": dg["trade_date"], "swap_count": _day_swap_count(dg)}
        for h in FORWARD_HORIZONS_FOCUS:
            entry[f"paired_effect_T+{h}_pct"] = _paired_effect_for_day(dg, h)
        top_detail.append(entry)
    result["top_swap_days_detail"] = top_detail
    print(f"  상위 스왑일 상세: {top_detail}")

    return result


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
        rows = _collect_symbol_rows_with_strategy(symbol, bars, market_common_regime_by_date)
        all_rows.extend(rows)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_rows))

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_rows), len(fetch_failures))

    _attach_day_level_rescaled_scores(all_rows)
    _attach_candidate_only_percentile(all_rows)

    quarters = _split_into_quarters(all_rows)

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "quarters": {},
    }
    for qi, label in QUARTER_LABELS.items():
        report["quarters"][label] = _diagnose_quarter(quarters[qi - 1], label)

    out_path = "logs/signal_ic_r3b_quarter1_weakness_diagnosis_2026-07-17.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
