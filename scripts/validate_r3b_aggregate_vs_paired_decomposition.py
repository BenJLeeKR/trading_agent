#!/usr/bin/env python3
"""SPPV-2.33 — R3b aggregate 우위와 대응표본(paired) 음수 구간의
불일치를 3분해(common_kept/dropped_only/added_only)로 규명 (read-only,
broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §22.5(다음
단계 1 — aggregate 우위와 대체쌍 성과 불일치 원인 규명) 참고.

§21(SPPV-2.31)의 aggregate 비교는 "R3b의 would_buy 전체 평균이
R0의 would_buy 전체 평균보다 높다"는 것만 보였다. §22(SPPV-2.32)의
대응표본(paired) 비교는 "그날 R0가 버리고 R3b가 새로 고른 종목의
forward return 차이"만 보였고, 분기3에서 이 값이 음수임을
발견했다 — 그런데 §21에서는 분기3에서도 R3b의 aggregate 평균이
R0보다 높았다. 이 스크립트는 그 모순을 **algebra적으로 정확히**
분해해 설명한다.

핵심 아이디어: R0의 `would_buy` 집합과 R3b의 `would_buy` 집합은
그날그날 다음 3개 그룹으로 완전히 분해된다.

  - `common_kept`: R0와 R3b 둘 다 고른 종목(교체되지 않고 유지됨)
  - `dropped_only`: R0만 고른 종목(R3b가 버림)
  - `added_only`: R3b만 고른 종목(R3b가 새로 추가)

그러면 정확히 다음이 성립한다(근사 아님, 항등식):

  mean(R0_would_buy)  = (n_common*mean_common + n_dropped*mean_dropped)
                        / (n_common + n_dropped)
  mean(R3b_would_buy) = (n_common*mean_common + n_added*mean_added)
                        / (n_common + n_added)

이 항등식으로 aggregate 차이가 (a) `mean_added - mean_dropped`(진짜
교체 품질 차이, §22의 paired 지표와 같은 방향) 때문인지, (b) 두
집합의 총 표본 수(n_common+n_added ≠ n_common+n_dropped)가 달라
common_kept와 교체분의 가중치가 달라지는 "구성/표본수 효과" 때문
인지 정확히 갈라낸다.

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
logger = logging.getLogger("validate_r3b_aggregate_vs_paired_decomposition")

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
T_NW_SIGNIFICANCE_THRESHOLD = 1.96  # 근사 양측 95% 유의 수준(>= 포함)


def _summarize_group(rows: list[dict], horizon: int) -> dict:
    n = len(rows)
    if n < 5:
        return {"n": n, "note": "표본부족(<5)"}
    xs = [r[f"fwd_{horizon}"] for r in rows]
    m = _mean(xs)
    std = _stdev(xs)
    from math import sqrt

    t_naive = (m / (std / sqrt(n))) if std else None
    nw_se = _newey_west_se_of_mean(xs, lag=max(horizon - 1, 1))
    t_nw = (m / nw_se) if nw_se else None
    sorted_xs = sorted(xs)
    lo_idx = max(0, int(round(0.025 * (n - 1))))
    hi_idx = min(n - 1, int(round(0.975 * (n - 1))))
    return {
        "n": n,
        "mean_pct": round(m * 100, 4),
        "t_naive": round(t_naive, 2) if t_naive else None,
        "t_newey_west": round(t_nw, 2) if t_nw else None,
        "pct_positive": round(sum(1 for x in xs if x > 0) / n, 4),
        "empirical_2.5pct": round(sorted_xs[lo_idx] * 100, 4),
        "empirical_97.5pct": round(sorted_xs[hi_idx] * 100, 4),
    }


def _decompose_scenario_pair(rows: list[dict], score_fn_base, score_fn_new) -> dict:
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["regime_conditional_signal"] is not None:
            by_date[r["trade_date"]].append(r)

    common_kept: list[dict] = []
    dropped_only: list[dict] = []
    added_only: list[dict] = []

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
        common_ids = base_ids & new_ids
        dropped_ids = base_ids - new_ids
        added_ids = new_ids - base_ids

        common_kept.extend(base_wb[i] for i in common_ids)
        dropped_only.extend(base_wb[i] for i in dropped_ids)
        added_only.extend(new_wb[i] for i in added_ids)

    result: dict = {
        "n_common": len(common_kept),
        "n_dropped_only": len(dropped_only),
        "n_added_only": len(added_only),
        "n_base_total": len(common_kept) + len(dropped_only),
        "n_new_total": len(common_kept) + len(added_only),
        "by_horizon": {},
    }

    for h in FORWARD_HORIZONS_FOCUS:
        common_s = _summarize_group(common_kept, h)
        dropped_s = _summarize_group(dropped_only, h)
        added_s = _summarize_group(added_only, h)

        n_common, n_dropped, n_added = len(common_kept), len(dropped_only), len(added_only)
        mean_common = _mean([r[f"fwd_{h}"] for r in common_kept]) if n_common else None
        mean_dropped = _mean([r[f"fwd_{h}"] for r in dropped_only]) if n_dropped else None
        mean_added = _mean([r[f"fwd_{h}"] for r in added_only]) if n_added else None

        recon_base = None
        recon_new = None
        if mean_common is not None:
            if n_dropped and (n_common + n_dropped) > 0:
                recon_base = (n_common * mean_common + n_dropped * mean_dropped) / (n_common + n_dropped)
            if n_added and (n_common + n_added) > 0:
                recon_new = (n_common * mean_common + n_added * mean_added) / (n_common + n_added)

        replacement_effect_pct = (
            round((mean_added - mean_dropped) * 100, 4) if (mean_added is not None and mean_dropped is not None) else None
        )

        result["by_horizon"][f"T+{h}"] = {
            "common_kept": common_s,
            "dropped_only": dropped_s,
            "added_only": added_s,
            "reconstructed_mean_base_pct": round(recon_base * 100, 4) if recon_base is not None else None,
            "reconstructed_mean_new_pct": round(recon_new * 100, 4) if recon_new is not None else None,
            "reconstructed_aggregate_diff_pct": (
                round((recon_new - recon_base) * 100, 4) if (recon_new is not None and recon_base is not None) else None
            ),
            "replacement_effect_added_minus_dropped_pct": replacement_effect_pct,
        }

    return result


def _analyze_window(rows: list[dict], window_label: str) -> dict:
    print(f"\n=== {window_label} (표본 {len(rows)}건) ===")
    window_report: dict = {"window": window_label, "comparisons": {}}

    for comp_name, score_fn_new in (("R0_vs_R3", _score_b_r3), ("R0_vs_R3b", _score_b_r3b)):
        decomp = _decompose_scenario_pair(rows, _score_b_r0, score_fn_new)
        window_report["comparisons"][comp_name] = decomp
        print(f"  [{comp_name}] common={decomp['n_common']}, dropped_only={decomp['n_dropped_only']}, "
              f"added_only={decomp['n_added_only']} | base_total={decomp['n_base_total']}, "
              f"new_total={decomp['n_new_total']}")
        for h in FORWARD_HORIZONS_FOCUS:
            bh = decomp["by_horizon"][f"T+{h}"]
            print(f"    T+{h}: common_kept={bh['common_kept'].get('mean_pct')}%, "
                  f"dropped_only={bh['dropped_only'].get('mean_pct')}%, "
                  f"added_only={bh['added_only'].get('mean_pct')}% | "
                  f"재구성 R0평균={bh['reconstructed_mean_base_pct']}%, "
                  f"재구성 new평균={bh['reconstructed_mean_new_pct']}%, "
                  f"aggregate차이={bh['reconstructed_aggregate_diff_pct']}%p, "
                  f"교체효과(added-dropped)={bh['replacement_effect_added_minus_dropped_pct']}%p")

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

    print("\n=== R3b aggregate 우위 vs 대응표본 음수 구간 3분해(common/dropped/added) ===")
    print(f"전체 3년 표본: {len(all_rows)}건, 최근 12개월(cutoff={cutoff}) 표본: {len(recent_rows)}건")
    print(f"(참고) t_NW 유의성 판정 기준: |t_NW| >= {T_NW_SIGNIFICANCE_THRESHOLD}(근사 양측 95%, 경계값 포함)")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_rows),
        "total_rolling_samples_recent_12m": len(recent_rows),
        "recent_window_cutoff": cutoff,
        "t_nw_significance_threshold": T_NW_SIGNIFICANCE_THRESHOLD,
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

    out_path = "logs/signal_ic_r3b_aggregate_vs_paired_decomposition_2026-07-16.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
