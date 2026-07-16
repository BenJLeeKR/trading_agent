#!/usr/bin/env python3
"""SPPV-3 후속 — 활동성 필터(`eligibility_low_relative_activity`)
threshold sweep + 기간 분할 재현성 검증 (read-only).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §14.6(다음
단계 1·2)이 지시한 후속 검증이다. §14(SPPV-2.24)는 threshold
1.10(현행)/1.00(완화)/제거 3개 시나리오만 비교해 "1.00 완화는 방향은
유력하나 확정 근거 부족(Watch)"이라는 판정을 내렸다. 이번 스크립트는
그 판정을 Conditional Go 이상으로 올릴 수 있는지, 아니면 우연한 단일
threshold 결과였는지를 아래 두 축으로 검증한다:

1. **threshold sweep 확장**: 1.10(현행)/1.05/1.00/0.95/0.90 5개
   threshold를 동일 표본·동일 정의(상위 20% quintile, 다른 모든
   eligibility 체크는 통과한 표본만 대상)로 비교한다. "표본이 늘어난
   만큼 t값이 커지는 것"과 "평균 수익률·양수율 자체가 개선되는 것"을
   분리해서 본다.
2. **기간 분할(out-of-sample 성격) 재현성**: 3년 rolling 표본을 거래일
   기준 전반부/후반부로 나눠, 완화 효과가 특정 구간(예: 특정 국면이
   몰린 시기)의 우연이 아니라 두 반기 모두에서 일관되게 나타나는지
   확인한다.

기존 `scripts/validate_activity_filter_ablation.py`(SPPV-2.24)의
`_collect_symbol_rows`/`_eligible_under_threshold`/`_summarize`/
`_top_quintile_rows`를 그대로 재사용한다 — 신규 실측 로직이 아니라
같은 표본·같은 계산 방식을 다른 threshold/구간으로 반복 적용한다.

DB write / 주문 경로 / 실시간 구독 없음. 실제 KIS 호출 여부는 가정하지
않고 로그의 `HTTP Request:` 카운트로 그대로 보고한다.
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
logger = logging.getLogger("validate_activity_filter_threshold_sweep")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_activity_filter_ablation import (  # noqa: E402
    RECENT_WINDOW_CALENDAR_DAYS,
    _collect_symbol_rows,
    _eligible_under_threshold,
    _summarize,
    _top_quintile_rows,
)
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

# 현행(1.10) 대비 완화/강화 방향 모두 포함한 threshold sweep.
THRESHOLD_SWEEP = {
    "current_1.10": 1.10,
    "relaxed_1.05": 1.05,
    "relaxed_1.00": 1.00,
    "relaxed_0.95": 0.95,
    "relaxed_0.90": 0.90,
}


def _sweep_window(rows: list[dict], window_label: str) -> dict:
    top = _top_quintile_rows(rows)
    print(f"\n--- {window_label} (상위 20% 표본 {len(top)}건) ---")

    window_report: dict = {"window": window_label, "top_quintile_n": len(top), "scenarios": {}}
    baseline_mean: dict[int, float] = {}

    for scenario_name, threshold in THRESHOLD_SWEEP.items():
        survives = [r for r in top if _eligible_under_threshold(r, threshold)]
        pct_survive = len(survives) / max(len(top), 1) * 100
        print(f"\n  [threshold={threshold}] 생존={len(survives)}건({pct_survive:.1f}%)")

        scenario_report: dict = {
            "threshold": threshold,
            "survives_n": len(survives),
            "survives_pct": round(pct_survive, 2),
            "by_horizon": {},
        }
        for h in FORWARD_HORIZONS_FOCUS:
            key = f"fwd_{h}"
            s = _summarize([r[key] for r in survives], h)
            if scenario_name == "current_1.10":
                baseline_mean[h] = s.get("mean_pct")
            delta_vs_current = None
            if scenario_name != "current_1.10" and baseline_mean.get(h) is not None and s.get("mean_pct") is not None:
                delta_vs_current = round(s["mean_pct"] - baseline_mean[h], 4)
            s["delta_mean_pct_vs_current_1.10"] = delta_vs_current
            print(f"    T+{h} 생존군: {s}")
            scenario_report["by_horizon"][f"T+{h}"] = s
        window_report["scenarios"][scenario_name] = scenario_report

    return window_report


def _split_first_second_half(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    dates = sorted({r["trade_date"] for r in rows})
    if len(dates) < 10:
        return rows, []
    mid = dates[len(dates) // 2]
    first_half = [r for r in rows if r["trade_date"] < mid]
    second_half = [r for r in rows if r["trade_date"] >= mid]
    return first_half, second_half


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

    last_date = max(datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in all_rows)
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    recent_rows = [r for r in all_rows if r["trade_date"] >= cutoff]

    first_half, second_half = _split_first_second_half(all_rows)

    print("\n=== 활동성 필터 threshold sweep + 기간 분할 재현성 검증 ===")
    print(f"전체 3년 표본: {len(all_rows)}건, 최근 12개월(cutoff={cutoff}) 표본: {len(recent_rows)}건")
    if first_half and second_half:
        d_first = sorted({r["trade_date"] for r in first_half})
        d_second = sorted({r["trade_date"] for r in second_half})
        print(f"전반부: {d_first[0]}~{d_first[-1]}({len(first_half)}건), "
              f"후반부: {d_second[0]}~{d_second[-1]}({len(second_half)}건)")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_rows),
        "total_rolling_samples_recent_12m": len(recent_rows),
        "recent_window_cutoff": cutoff,
        "threshold_sweep": list(THRESHOLD_SWEEP.values()),
        "windows": {},
    }

    report["windows"]["supplementary_3y"] = _sweep_window(all_rows, "2차(3년, 전체 표본)")
    report["windows"]["primary_recent_12m"] = _sweep_window(recent_rows, "1차(최근 12개월)")
    if first_half and second_half:
        report["windows"]["3y_first_half"] = _sweep_window(first_half, "3년 전반부(out-of-sample 분할 1)")
        report["windows"]["3y_second_half"] = _sweep_window(second_half, "3년 후반부(out-of-sample 분할 2)")

    out_path = "logs/signal_ic_activity_filter_threshold_sweep_2026-07-16.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
