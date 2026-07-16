#!/usr/bin/env python3
"""SPPV-2.34 — R3b pooled 우위의 날짜 집중도 검증 + 교체효과/구성효과
정량 분리 (read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §23.7(다음
단계 1 — 분기3처럼 pooled/paired 부호가 갈리는 구간의 거래일 단위
세밀 진단) 참고.

§23(SPPV-2.33)은 common_kept/dropped_only/added_only 3분해로
"added_only가 8개 창 전부에서 더 우수하다"는 것과 "R0 자신의 구성이
저품질 dropped_only 비중이 커서 구성 효과도 상당히 기여한다"는 것,
그리고 "분기3에서 pooled와 paired 지표의 부호가 정반대"라는 것을
발견했다 — 그러나 (a) 이 pooled 우위가 소수 거래일에 집중된
것인지, (b) "교체효과"와 "구성효과"를 정량적으로 얼마씩 나눠
가지는지는 직접 계측하지 않았다. 이 스크립트는 그 두 가지를
직접 계측한다.

**작업 1 — 날짜 집중도 검증**: 거래일마다 스왑 개수(added+dropped)
를 계산하고, 스왑 개수 상위 10%(top-decile) 거래일을 제거했을 때
pooled aggregate 우위가 얼마나 남는지 재계산한다 — 소수 거래일에
효과가 몰려 있다면, 이 거래일들을 제외했을 때 우위가 크게 줄어들
것이다.

**작업 2 — 교체효과/구성효과 정확한 항등식 분해**: §23의 항등식
`mean(R0)=w0·mean_common+w0'·mean_dropped`,
`mean(new)=w1·mean_common+w1'·mean_added`(w는 각 시나리오 자체의
집합 내 가중치)에서 출발해, 두 평균의 차이를 다음처럼 정확히
분해한다(대수적 항등식, 근사 아님):

    aggregate_diff = replacement_effect + composition_effect
    replacement_effect  = w0'·(mean_added - mean_dropped)
    composition_effect  = (w1' - w0')·(mean_added - mean_common)

    여기서 w0' = n_dropped/(n_common+n_dropped)  (R0 자신의 dropped 비중)
          w1' = n_added/(n_common+n_added)        (신규안 자신의 added 비중)

`replacement_effect`는 "교체된 종목 자체의 품질 차이"만을, `composition_
effect`는 "두 시나리오의 표본 구성 비율이 다름"만을 순수하게
반영한다 — 각각을 창별로 정량 보고한다.

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
logger = logging.getLogger("validate_r3b_day_concentration_and_effect_decomposition")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_activity_filter_threshold_sweep import _split_first_second_half  # noqa: E402
from validate_alpha_layer_r3_reproducibility import _split_into_quarters  # noqa: E402
from validate_r3b_paired_replacement_analysis import _day_would_buy  # noqa: E402
from validate_r3b_strict_and_r3_failure_decomposition import (  # noqa: E402
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
TOP_DECILE_FRACTION = 0.10


def _build_day_groups(rows: list[dict], score_fn_base, score_fn_new) -> list[dict]:
    """거래일별로 common_kept/dropped_only/added_only 행 목록을 만든다."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["regime_conditional_signal"] is not None:
            by_date[r["trade_date"]].append(r)

    day_groups: list[dict] = []
    for trade_date, day_rows in by_date.items():
        if len(day_rows) < 5:
            continue
        ordered = sorted(day_rows, key=lambda r: r["regime_conditional_signal"], reverse=True)
        q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
        day_candidates = ordered[:q]

        base_wb = _day_would_buy(day_candidates, score_fn_base)
        new_wb = _day_would_buy(day_candidates, score_fn_new)

        base_ids = set(base_wb.keys())
        new_ids = set(new_wb.keys())
        common_ids = base_ids & new_ids
        dropped_ids = base_ids - new_ids
        added_ids = new_ids - base_ids

        day_groups.append({
            "trade_date": trade_date,
            "common_rows": [base_wb[i] for i in common_ids],
            "dropped_rows": [base_wb[i] for i in dropped_ids],
            "added_rows": [new_wb[i] for i in added_ids],
        })
    return day_groups


def _sum_and_n(rows: list[dict], h: int) -> tuple[float, int]:
    if not rows:
        return 0.0, 0
    return sum(r[f"fwd_{h}"] for r in rows), len(rows)


def _pooled_summary_from_days(day_groups: list[dict], h: int) -> dict:
    """전체 day_groups를 풀링해 3그룹 평균과 재구성 aggregate, 교체효과/
    구성효과를 정확한 항등식으로 계산한다."""
    s_common = s_dropped = s_added = 0.0
    n_common = n_dropped = n_added = 0
    for dg in day_groups:
        sc, nc = _sum_and_n(dg["common_rows"], h)
        sd, nd = _sum_and_n(dg["dropped_rows"], h)
        sa, na = _sum_and_n(dg["added_rows"], h)
        s_common += sc
        n_common += nc
        s_dropped += sd
        n_dropped += nd
        s_added += sa
        n_added += na

    if n_common + n_dropped == 0 or n_common + n_added == 0:
        return {"note": "표본부족"}

    mean_common = s_common / n_common if n_common else None
    mean_dropped = s_dropped / n_dropped if n_dropped else None
    mean_added = s_added / n_added if n_added else None

    mean_base = (s_common + s_dropped) / (n_common + n_dropped)
    mean_new = (s_common + s_added) / (n_common + n_added)
    aggregate_diff = mean_new - mean_base

    replacement_effect = None
    composition_effect = None
    if mean_added is not None and mean_dropped is not None and mean_common is not None:
        w0_prime = n_dropped / (n_common + n_dropped)  # R0 자신의 dropped 비중
        w1_prime = n_added / (n_common + n_added)       # 신규안 자신의 added 비중
        replacement_effect = w0_prime * (mean_added - mean_dropped)
        composition_effect = (w1_prime - w0_prime) * (mean_added - mean_common)

    return {
        "n_common": n_common,
        "n_dropped": n_dropped,
        "n_added": n_added,
        "mean_common_pct": round(mean_common * 100, 4) if mean_common is not None else None,
        "mean_dropped_pct": round(mean_dropped * 100, 4) if mean_dropped is not None else None,
        "mean_added_pct": round(mean_added * 100, 4) if mean_added is not None else None,
        "mean_base_pct": round(mean_base * 100, 4),
        "mean_new_pct": round(mean_new * 100, 4),
        "aggregate_diff_pct": round(aggregate_diff * 100, 4),
        "replacement_effect_pct": round(replacement_effect * 100, 4) if replacement_effect is not None else None,
        "composition_effect_pct": round(composition_effect * 100, 4) if composition_effect is not None else None,
        "check_sum_matches": (
            round(
                abs(
                    aggregate_diff
                    - ((replacement_effect or 0) + (composition_effect or 0))
                )
                * 100,
                6,
            )
        ),
    }


def _day_swap_count(dg: dict) -> int:
    return len(dg["dropped_rows"]) + len(dg["added_rows"])


def _summarize_paired_series(diffs: list[float], horizon: int) -> dict:
    n = len(diffs)
    if n < 5:
        return {"n_days": n, "note": "표본부족(<5일)"}
    m = _mean(diffs)
    std = _stdev(diffs)
    from math import sqrt

    t_naive = (m / (std / sqrt(n))) if std else None
    nw_se = _newey_west_se_of_mean(diffs, lag=max(horizon - 1, 1))
    t_nw = (m / nw_se) if nw_se else None
    return {
        "n_days": n,
        "mean_diff_pct": round(m * 100, 4),
        "t_naive": round(t_naive, 2) if t_naive else None,
        "t_newey_west": round(t_nw, 2) if t_nw else None,
        "pct_days_added_better": round(sum(1 for x in diffs if x > 0) / n, 4),
    }


def _analyze_comparison(rows: list[dict], score_fn_base, score_fn_new, label: str) -> dict:
    day_groups = _build_day_groups(rows, score_fn_base, score_fn_new)
    swap_days = [dg for dg in day_groups if dg["dropped_rows"] and dg["added_rows"]]

    swap_counts = sorted((_day_swap_count(dg) for dg in swap_days), reverse=True)
    n_swap_days = len(swap_days)
    top_decile_n = max(1, int(round(n_swap_days * TOP_DECILE_FRACTION))) if n_swap_days else 0

    # 스왑 개수 상위 10% 거래일 식별
    ranked_by_swap = sorted(swap_days, key=_day_swap_count, reverse=True)
    top_decile_dates = {dg["trade_date"] for dg in ranked_by_swap[:top_decile_n]}
    rest_day_groups = [dg for dg in day_groups if dg["trade_date"] not in top_decile_dates]

    report: dict = {
        "label": label,
        "n_swap_days": n_swap_days,
        "swap_count_distribution": {
            "mean": round(_mean(swap_counts), 2) if swap_counts else None,
            "median": swap_counts[len(swap_counts) // 2] if swap_counts else None,
            "max": swap_counts[0] if swap_counts else None,
            "top_decile_n_days": top_decile_n,
        },
        "by_horizon": {},
    }

    for h in FORWARD_HORIZONS_FOCUS:
        full_summary = _pooled_summary_from_days(day_groups, h)
        rest_summary = _pooled_summary_from_days(rest_day_groups, h)

        # paired(일별 동일가중) 지표 — §22와 동일 정의, 재확인용
        daily_diffs = []
        for dg in swap_days:
            added_mean = _mean([r[f"fwd_{h}"] for r in dg["added_rows"]])
            dropped_mean = _mean([r[f"fwd_{h}"] for r in dg["dropped_rows"]])
            daily_diffs.append(added_mean - dropped_mean)
        paired_summary = _summarize_paired_series(daily_diffs, h)

        remaining_pct = None
        if full_summary.get("aggregate_diff_pct") not in (None,) and full_summary["aggregate_diff_pct"] != 0:
            if "aggregate_diff_pct" in rest_summary:
                remaining_pct = round(
                    rest_summary["aggregate_diff_pct"] / full_summary["aggregate_diff_pct"] * 100, 1
                )

        report["by_horizon"][f"T+{h}"] = {
            "full_pooled": full_summary,
            "excl_top_decile_swap_days": rest_summary,
            "aggregate_diff_remaining_pct_of_full": remaining_pct,
            "paired_daily_equal_weight": paired_summary,
        }

    return report


def _print_report(report: dict) -> None:
    print(f"\n  [{report['label']}] 스왑 발생일수={report['n_swap_days']}, "
          f"스왑개수 분포={report['swap_count_distribution']}")
    for h_key, bh in report["by_horizon"].items():
        fp = bh["full_pooled"]
        rp = bh["excl_top_decile_swap_days"]
        pp = bh["paired_daily_equal_weight"]
        print(f"    {h_key} 전체 pooled: aggregate차이={fp.get('aggregate_diff_pct')}%p "
              f"(교체효과={fp.get('replacement_effect_pct')}%p, "
              f"구성효과={fp.get('composition_effect_pct')}%p)")
        print(f"    {h_key} 스왑상위10%일 제외 후: aggregate차이={rp.get('aggregate_diff_pct')}%p "
              f"(잔존비율={bh.get('aggregate_diff_remaining_pct_of_full')}%)")
        print(f"    {h_key} paired(일별 동일가중) 재확인: {pp}")


def _analyze_window(rows: list[dict], window_label: str) -> dict:
    print(f"\n=== {window_label} (표본 {len(rows)}건) ===")
    window_report: dict = {"window": window_label, "comparisons": {}}

    r0_vs_r3 = _analyze_comparison(rows, _score_b_r0, _score_b_r3, "R0_vs_R3")
    _print_report(r0_vs_r3)
    window_report["comparisons"]["R0_vs_R3"] = r0_vs_r3

    r0_vs_r3b = _analyze_comparison(rows, _score_b_r0, _score_b_r3b, "R0_vs_R3b")
    _print_report(r0_vs_r3b)
    window_report["comparisons"]["R0_vs_R3b"] = r0_vs_r3b

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

    print("\n=== R3b pooled 우위 날짜 집중도 검증 + 교체효과/구성효과 정량 분리 ===")
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

    out_path = "logs/signal_ic_r3b_day_concentration_and_effect_decomposition_2026-07-16.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
