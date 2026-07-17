#!/usr/bin/env python3
"""SPPV-2.36 — 분기3 반례의 대형/소규모 스왑 구조 정밀 확정 (read-only,
broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §25.7(다음
단계 2 — "대형 스왑일=양(+)/소규모 스왑일=음(-)" 패턴을 정량 확정)
참고.

§25(SPPV-2.35)는 분기3 상위 15개 거래일만 개별 나열해 "대형
스왑일(상위 10%)은 순기여 양(+), 나머지 다수 소규모 스왑일은 완만한
음(-) 누적"이라는 잠정 구조를 제시했으나, 이는 (a) 83개 스왑일
전체를 구간화(quintile)하지 않았고 (b) "전적으로 의존" 같은 표현이
실제 기여 비율로 뒷받침됐는지 확인하지 않았다. 이 스크립트는:

1. 분기3 83개 스왑 발생일 전부를 스왑 개수 기준 5분위(quintile)로
   구간화하고, 각 구간의 거래일 수/paired 평균/구간 자체의 pooled
   교체효과(구간 내 added 합계-dropped 합계 기반)를 계측한다.
2. 상위 10%(top-decile, §24/§25와 동일 정의)를 별도로도 분리해
   보고한다(quintile 1과의 관계 확인용).
3. leave-top-k-days-out(k=1,3,5,8) 민감도를 aggregate_diff(pooled)와
   paired 평균 양쪽에 대해 계측한다.
4. 전체 83일의 paired 효과를 부호로 나눠 "총 양(+) 합"과 "총 음(-)
   합"을 계산하고, 그중 상위 10%(대형 스왑일)가 차지하는 비중을
   정량화한다 — "전적으로 의존"이 맞는 표현인지 판단하는 근거.
5. 2025-02-12/02-13을 묶어서 동시 제거했을 때 aggregate/paired가
   어떻게 바뀌는지 별도 계측한다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음. 실제 KIS
호출 여부는 가정하지 않고 로그의 `HTTP Request:` 카운트로 그대로
보고한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys as _sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_r3b_q3_swap_size_bucket_decomposition")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_alpha_layer_r3_reproducibility import _split_into_quarters  # noqa: E402
from validate_r3b_day_concentration_and_effect_decomposition import (  # noqa: E402
    TOP_DECILE_FRACTION,
    _build_day_groups,
    _day_swap_count,
    _pooled_summary_from_days,
)
from validate_r3b_strict_and_r3_failure_decomposition import (  # noqa: E402
    _attach_day_level_stats,
    _collect_symbol_rows,
    _score_b_r0,
    _score_b_r3b,
)
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK, _mean  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

N_QUINTILES = 5
LEAVE_TOP_K = (1, 3, 5, 8)
EARLY_CLUSTER_DATES = ("2025-02-12", "2025-02-13")


def _paired_effect_for_day(dg: dict, h: int) -> float | None:
    if not dg["added_rows"] or not dg["dropped_rows"]:
        return None
    added_mean = _mean([r[f"fwd_{h}"] for r in dg["added_rows"]])
    dropped_mean = _mean([r[f"fwd_{h}"] for r in dg["dropped_rows"]])
    return round((added_mean - dropped_mean) * 100, 4)


def _bucket_pooled_effect(days: list[dict], h: int) -> dict:
    """구간 자체의 added/dropped 행만 풀링한 교체효과(가중 평균)."""
    added_vals: list[float] = []
    dropped_vals: list[float] = []
    for dg in days:
        added_vals.extend(r[f"fwd_{h}"] for r in dg["added_rows"])
        dropped_vals.extend(r[f"fwd_{h}"] for r in dg["dropped_rows"])
    if not added_vals or not dropped_vals:
        return {"n_added": len(added_vals), "n_dropped": len(dropped_vals), "pooled_effect_pct": None}
    pooled_effect = (_mean(added_vals) - _mean(dropped_vals)) * 100
    return {
        "n_added": len(added_vals),
        "n_dropped": len(dropped_vals),
        "mean_added_pct": round(_mean(added_vals) * 100, 4),
        "mean_dropped_pct": round(_mean(dropped_vals) * 100, 4),
        "pooled_effect_pct": round(pooled_effect, 4),
    }


def _paired_mean_of(days: list[dict], h: int) -> float | None:
    vals = [v for v in (_paired_effect_for_day(dg, h) for dg in days) if v is not None]
    return round(_mean(vals), 4) if vals else None


def _analyze(q3_rows: list[dict]) -> dict:
    day_groups = _build_day_groups(q3_rows, _score_b_r0, _score_b_r3b)
    swap_days = [dg for dg in day_groups if dg["dropped_rows"] and dg["added_rows"]]
    ranked = sorted(swap_days, key=_day_swap_count, reverse=True)
    n_swap_days = len(ranked)

    report: dict = {"n_swap_days": n_swap_days, "by_horizon": {}}

    print(f"\n=== 분기3 스왑 발생일 {n_swap_days}건 — 대형/소규모 구조 정밀 확정 ===")

    # --- quintile 구간화 ---
    q_size = n_swap_days / N_QUINTILES
    quintile_days: list[list[dict]] = [[] for _ in range(N_QUINTILES)]
    for idx, dg in enumerate(ranked):
        bucket_idx = min(int(idx / q_size), N_QUINTILES - 1)
        quintile_days[bucket_idx].append(dg)

    top_decile_n = max(1, int(n_swap_days * TOP_DECILE_FRACTION))
    top_decile_days = ranked[:top_decile_n]
    rest_after_decile_days = ranked[top_decile_n:]

    for h in FORWARD_HORIZONS_FOCUS:
        horizon_key = f"T+{h}"
        full_summary = _pooled_summary_from_days(day_groups, h)
        full_paired_mean = _paired_mean_of(swap_days, h)

        print(f"\n[{horizon_key}] 분기3 전체: aggregate_diff(pooled)={full_summary.get('aggregate_diff_pct')}%p, "
              f"paired 평균={full_paired_mean}%p")

        # quintile 테이블
        quintile_rows = []
        print(f"  -- {horizon_key} quintile(스왑개수 내림차순 5분위) --")
        for qi, days in enumerate(quintile_days, start=1):
            n_days = len(days)
            swap_counts = [_day_swap_count(d) for d in days]
            paired_mean = _paired_mean_of(days, h)
            pooled_info = _bucket_pooled_effect(days, h)

            rest_days = [d for d in swap_days if d not in days]
            rest_summary = _pooled_summary_from_days(
                [d for d in day_groups if d not in days], h
            )
            rest_paired_mean = _paired_mean_of(rest_days, h)

            row = {
                "quintile": qi,
                "n_days": n_days,
                "swap_count_range": f"{min(swap_counts)}~{max(swap_counts)}" if swap_counts else None,
                "swap_count_sum": sum(swap_counts),
                "paired_mean_pct": paired_mean,
                "bucket_pooled_effect_pct": pooled_info.get("pooled_effect_pct"),
                "aggregate_diff_after_removal_pct": rest_summary.get("aggregate_diff_pct"),
                "paired_mean_after_removal_pct": rest_paired_mean,
            }
            quintile_rows.append(row)
            print(f"    Q{qi}: n_days={n_days}, 스왑개수범위={row['swap_count_range']}, "
                  f"paired평균={paired_mean}%p, 구간자체 pooled효과={pooled_info.get('pooled_effect_pct')}%p | "
                  f"이 구간 제거 후 aggregate={rest_summary.get('aggregate_diff_pct')}%p, "
                  f"paired평균={rest_paired_mean}%p")

        # top-decile vs 나머지
        decile_paired_mean = _paired_mean_of(top_decile_days, h)
        decile_pooled = _bucket_pooled_effect(top_decile_days, h)
        rest_decile_paired_mean = _paired_mean_of(rest_after_decile_days, h)
        rest_decile_summary = _pooled_summary_from_days(
            [d for d in day_groups if d not in top_decile_days], h
        )
        print(f"  -- {horizon_key} 상위 10%(대형, n={top_decile_n}) vs 나머지 90%(n={n_swap_days - top_decile_n}) --")
        print(f"    대형: paired평균={decile_paired_mean}%p, 구간자체 pooled효과={decile_pooled.get('pooled_effect_pct')}%p")
        print(f"    나머지 제거 후(=대형만 남김 아님, 대형 제거 후) aggregate={rest_decile_summary.get('aggregate_diff_pct')}%p, "
              f"paired평균={rest_decile_paired_mean}%p")

        # leave-top-k-out
        leave_top_k_rows = []
        for k in LEAVE_TOP_K:
            k = min(k, n_swap_days)
            top_k_days = ranked[:k]
            rest_k_days = [d for d in day_groups if d not in top_k_days]
            rest_k_swap_days = [d for d in swap_days if d not in top_k_days]
            rest_k_summary = _pooled_summary_from_days(rest_k_days, h)
            rest_k_paired_mean = _paired_mean_of(rest_k_swap_days, h)
            remaining_agg_pct = None
            if full_summary.get("aggregate_diff_pct"):
                remaining_agg_pct = round(
                    rest_k_summary.get("aggregate_diff_pct", 0) / full_summary["aggregate_diff_pct"] * 100, 1
                )
            leave_top_k_rows.append({
                "k": k,
                "aggregate_diff_after_pct": rest_k_summary.get("aggregate_diff_pct"),
                "remaining_pct_of_original_aggregate": remaining_agg_pct,
                "paired_mean_after_pct": rest_k_paired_mean,
            })
        print(f"  -- {horizon_key} leave-top-k-days-out --")
        for row in leave_top_k_rows:
            print(f"    k={row['k']}: 제거 후 aggregate={row['aggregate_diff_after_pct']}%p"
                  f"(원본 대비 {row['remaining_pct_of_original_aggregate']}%), "
                  f"제거 후 paired평균={row['paired_mean_after_pct']}%p")

        # 부호별 총합 분해 + 대형 비중
        all_effects = [(dg, _paired_effect_for_day(dg, h)) for dg in swap_days]
        all_effects = [(dg, v) for dg, v in all_effects if v is not None]
        pos_sum = sum(v for _, v in all_effects if v > 0)
        neg_sum = sum(v for _, v in all_effects if v < 0)
        decile_dates = {dg["trade_date"] for dg in top_decile_days}
        pos_sum_decile = sum(v for dg, v in all_effects if v > 0 and dg["trade_date"] in decile_dates)
        neg_sum_decile = sum(v for dg, v in all_effects if v < 0 and dg["trade_date"] in decile_dates)
        pos_share_decile_pct = round(pos_sum_decile / pos_sum * 100, 1) if pos_sum else None
        neg_share_decile_pct = round(neg_sum_decile / neg_sum * 100, 1) if neg_sum else None

        print(f"  -- {horizon_key} 부호별 총합 분해 --")
        print(f"    전체 양(+) 합계={round(pos_sum,4)}%p (대형 10% 비중={pos_share_decile_pct}%), "
              f"전체 음(-) 합계={round(neg_sum,4)}%p (대형 10% 비중={neg_share_decile_pct}%)")

        # 2025-02-12/13 묶음 제거
        cluster_days = [dg for dg in swap_days if dg["trade_date"] in EARLY_CLUSTER_DATES]
        rest_cluster_days = [d for d in day_groups if d["trade_date"] not in EARLY_CLUSTER_DATES]
        rest_cluster_swap_days = [d for d in swap_days if d["trade_date"] not in EARLY_CLUSTER_DATES]
        cluster_summary_before = full_summary
        cluster_summary_after = _pooled_summary_from_days(rest_cluster_days, h)
        cluster_paired_after = _paired_mean_of(rest_cluster_swap_days, h)
        print(f"  -- {horizon_key} 2025-02-12/13 묶음 제거 --")
        print(f"    제거 전 aggregate={cluster_summary_before.get('aggregate_diff_pct')}%p, paired={full_paired_mean}%p")
        print(f"    제거 후 aggregate={cluster_summary_after.get('aggregate_diff_pct')}%p, paired={cluster_paired_after}%p")

        report["by_horizon"][horizon_key] = {
            "aggregate_diff_full_pct": full_summary.get("aggregate_diff_pct"),
            "paired_mean_full_pct": full_paired_mean,
            "quintiles": quintile_rows,
            "top_decile": {
                "n_days": top_decile_n,
                "paired_mean_pct": decile_paired_mean,
                "bucket_pooled_effect_pct": decile_pooled.get("pooled_effect_pct"),
                "aggregate_diff_after_removal_pct": rest_decile_summary.get("aggregate_diff_pct"),
                "paired_mean_after_removal_pct": rest_decile_paired_mean,
            },
            "leave_top_k_out": leave_top_k_rows,
            "sign_decomposition": {
                "positive_sum_pct": round(pos_sum, 4),
                "negative_sum_pct": round(neg_sum, 4),
                "positive_share_from_top_decile_pct": pos_share_decile_pct,
                "negative_share_from_top_decile_pct": neg_share_decile_pct,
            },
            "early_cluster_feb12_13": {
                "aggregate_diff_before_pct": cluster_summary_before.get("aggregate_diff_pct"),
                "aggregate_diff_after_removal_pct": cluster_summary_after.get("aggregate_diff_pct"),
                "paired_mean_before_pct": full_paired_mean,
                "paired_mean_after_removal_pct": cluster_paired_after,
            },
        }

    return report


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

    quarters = _split_into_quarters(all_rows)
    if len(quarters) < 3:
        raise SystemExit("분기 분할 실패 — quarters 개수 부족")
    q3_rows = quarters[2]
    q3_dates = sorted({r["trade_date"] for r in q3_rows})
    print(f"\n=== 분기3 대형/소규모 스왑 구조 정밀 진단 시작: {q3_dates[0]}~{q3_dates[-1]}, 표본 {len(q3_rows)}건 ===")

    report = _analyze(q3_rows)
    report["as_of"] = datetime.now(_KST).isoformat()
    report["quarter3_date_range"] = f"{q3_dates[0]}~{q3_dates[-1]}"
    report["symbol_count_used"] = len(symbols) - len(fetch_failures)
    report["fetch_failures"] = fetch_failures

    out_path = "logs/signal_ic_r3b_q3_swap_size_bucket_decomposition_2026-07-17.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
