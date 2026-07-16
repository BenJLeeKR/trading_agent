#!/usr/bin/env python3
"""SPPV-2.35 — 분기3 스왑 집중일 세부 진단 (read-only, broker submit
없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §24.6(다음
단계 1 — 분기3의 스왑 상위 10% 거래일을 구체적으로 나열해 특정
사유 존재 여부 확인) 참고.

§24(SPPV-2.34)는 분기3에서만 스왑 상위 10% 거래일을 제거하면
aggregate 우위 잔존비율이 T+5=29.7%/T+20=65.2%로 크게 줄어든다는
것을 "집계"로 확인했다 — 그러나 **어느 날짜가**, **어떤 스왑
조합으로**, **얼마나** aggregate 우위를 만들어내는지는 개별적으로
나열하지 않았다. 이 스크립트는 분기3의 R0 vs R3b 비교에서 스왑
상위 10% 거래일을 하나씩 나열하고, 각 날짜의 (a) 스왑 개수, (b)
그날의 pooled 교체효과(added_day_mean - dropped_day_mean, 그날
가중치 반영 없이 단순 그날의 두 그룹 평균 차이), (c) common_kept/
dropped_only/added_only 평균, (d) 그 날짜 하나를 제거했을 때
분기3 전체 aggregate_diff와 paired 평균이 어떻게 바뀌는지(leave-
one-day-out)를 계측한다.

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
logger = logging.getLogger("validate_r3b_q3_day_level_diagnostics")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_alpha_layer_r3_reproducibility import _split_into_quarters  # noqa: E402
from validate_r3b_day_concentration_and_effect_decomposition import (  # noqa: E402
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

TOP_N_DAYS_TO_LIST = 15  # 분기3 스왑 상위 10%(≈8일)보다 넉넉히 나열


def _day_group_means(dg: dict, h: int) -> dict:
    def _m(rows):
        return round(_mean([r[f"fwd_{h}"] for r in rows]) * 100, 4) if rows else None

    return {
        "n_common": len(dg["common_rows"]),
        "n_dropped": len(dg["dropped_rows"]),
        "n_added": len(dg["added_rows"]),
        "mean_common_pct": _m(dg["common_rows"]),
        "mean_dropped_pct": _m(dg["dropped_rows"]),
        "mean_added_pct": _m(dg["added_rows"]),
    }


def _paired_effect_for_day(dg: dict, h: int) -> float | None:
    if not dg["added_rows"] or not dg["dropped_rows"]:
        return None
    added_mean = _mean([r[f"fwd_{h}"] for r in dg["added_rows"]])
    dropped_mean = _mean([r[f"fwd_{h}"] for r in dg["dropped_rows"]])
    return round((added_mean - dropped_mean) * 100, 4)


def _diagnose_quarter3(q3_rows: list[dict]) -> dict:
    day_groups = _build_day_groups(q3_rows, _score_b_r0, _score_b_r3b)
    swap_days = [dg for dg in day_groups if dg["dropped_rows"] and dg["added_rows"]]
    ranked = sorted(swap_days, key=_day_swap_count, reverse=True)

    print(f"\n=== 3년 분기3 — R0 vs R3b 스왑 거래일 세부 진단(스왑 발생일 {len(swap_days)}건 중 상위 {TOP_N_DAYS_TO_LIST}건) ===")

    report: dict = {"n_swap_days": len(swap_days), "top_days": []}

    for h in FORWARD_HORIZONS_FOCUS:
        full_summary = _pooled_summary_from_days(day_groups, h)
        print(f"\n[T+{h}] 분기3 전체(모든 날 포함) aggregate_diff={full_summary.get('aggregate_diff_pct')}%p, "
              f"replacement_effect={full_summary.get('replacement_effect_pct')}%p, "
              f"composition_effect={full_summary.get('composition_effect_pct')}%p")

    for rank, dg in enumerate(ranked[:TOP_N_DAYS_TO_LIST], start=1):
        trade_date = dg["trade_date"]
        swap_n = _day_swap_count(dg)

        # leave-one-day-out: 이 날짜를 제외한 나머지로 재계산
        rest_days = [d for d in day_groups if d["trade_date"] != trade_date]
        rest_swap_days = [d for d in swap_days if d["trade_date"] != trade_date]

        day_entry: dict = {
            "rank": rank,
            "trade_date": trade_date,
            "swap_count": swap_n,
            "by_horizon": {},
        }

        print(f"\n  #{rank} {trade_date} (스왑 개수={swap_n})")
        for h in FORWARD_HORIZONS_FOCUS:
            groups = _day_group_means(dg, h)
            day_paired_effect = _paired_effect_for_day(dg, h)

            full_summary = _pooled_summary_from_days(day_groups, h)
            rest_summary = _pooled_summary_from_days(rest_days, h)

            # 이 날짜 제외 시 paired(일별 동일가중) 평균이 어떻게 바뀌는지
            full_paired_diffs = []
            rest_paired_diffs = []
            for d in swap_days:
                pe = _paired_effect_for_day(d, h)
                if pe is not None:
                    full_paired_diffs.append(pe)
            for d in rest_swap_days:
                pe = _paired_effect_for_day(d, h)
                if pe is not None:
                    rest_paired_diffs.append(pe)
            full_paired_mean = round(_mean(full_paired_diffs), 4) if full_paired_diffs else None
            rest_paired_mean = round(_mean(rest_paired_diffs), 4) if rest_paired_diffs else None

            day_entry["by_horizon"][f"T+{h}"] = {
                "groups": groups,
                "day_paired_effect_pct": day_paired_effect,
                "aggregate_diff_before_pct": full_summary.get("aggregate_diff_pct"),
                "aggregate_diff_after_removal_pct": rest_summary.get("aggregate_diff_pct"),
                "paired_mean_before_pct": full_paired_mean,
                "paired_mean_after_removal_pct": rest_paired_mean,
            }

            print(f"    T+{h}: common={groups['mean_common_pct']}%(n={groups['n_common']}), "
                  f"dropped={groups['mean_dropped_pct']}%(n={groups['n_dropped']}), "
                  f"added={groups['mean_added_pct']}%(n={groups['n_added']}) | "
                  f"이날 paired효과={day_paired_effect}%p | "
                  f"제거 전 aggregate={full_summary.get('aggregate_diff_pct')}%p → "
                  f"제거 후={rest_summary.get('aggregate_diff_pct')}%p | "
                  f"제거 전 paired평균={full_paired_mean}%p → 제거 후={rest_paired_mean}%p")

        report["top_days"].append(day_entry)

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
    print(f"\n=== 분기3 세부 진단 시작: {q3_dates[0]}~{q3_dates[-1]}, 표본 {len(q3_rows)}건 ===")

    report = _diagnose_quarter3(q3_rows)
    report["as_of"] = datetime.now(_KST).isoformat()
    report["quarter3_date_range"] = f"{q3_dates[0]}~{q3_dates[-1]}"
    report["symbol_count_used"] = len(symbols) - len(fetch_failures)
    report["fetch_failures"] = fetch_failures

    out_path = "logs/signal_ic_r3b_q3_day_level_diagnostics_2026-07-16.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
