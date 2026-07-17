#!/usr/bin/env python3
"""SPPV-2.37 — R3b의 SPPV-3(창 교체 본작업) 진입 후보 여부 판단을 위한
최소 검증 (read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §26.8(다음
단계) 및 사용자 지시(SPPV-2.36 이후 "그래서 이 창을 교체 후보로 올릴
수 있는가"를 판단) 참고.

§20(SPPV-2.30)이 이미 A(현행 alpha)/B_R0(재보정 없음)/B_R3(전체
universe percentile)/B_R3b(candidate 내부 percentile)의 실제 BUY
funnel(candidate→eligible→selected→would_buy)을 8개 창(2차/1차/
전반부/후반부/분기1~4)에서 계측했다(`logs/signal_ic_alpha_layer_r3_
reproducibility_2026-07-16.json`) — candidate/eligible/selected/
would_buy 단계별 표본 수, T+5/T+20 평균, Newey-West t, 양수 비율이
이미 존재한다. **이번 스크립트는 그 결과를 재실행하지 않고 그대로
재사용**하며, 다음 한 가지만 신규로 계측한다:

**would_buy 단계 결과가 거래일 단위로 얼마나 편중돼 있는가** —
R0와 R3b 각각의 would_buy 표본을 거래일별로 묶어 일별 평균을 구하고,
스왑 상위 10%(top-decile) 거래일을 제거했을 때 전체 평균이 얼마나
남는지(leave-top-decile-day-out) 8개 창 전부에서 계측한다. 이는
§24~§26이 분기3의 R0-vs-R3b **교체쌍(swap)**에서만 확인했던 날짜
집중도 검증을, 이번에는 **전체 would_buy 모집단(교체쌍이 아닌 실제
매수 후보 전체)**에 대해 8개 창 전부로 확장한 것이다 — SPPV-3 착수
여부를 판단하려면 Q3의 스왑 구조뿐 아니라 "전체 8개 창에서 R3b의
우위가 소수 거래일에 의존하는지"를 알아야 하기 때문이다.

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
logger = logging.getLogger("validate_r3b_sppv3_entry_readiness_check")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_alpha_layer_r3_reproducibility import (  # noqa: E402
    SCENARIOS,
    _attach_candidate_only_percentile,
    _funnel_for_scenario,
    _split_into_quarters,
)
from validate_activity_filter_threshold_sweep import _split_first_second_half  # noqa: E402
from validate_alpha_layer_score_rescaling_comparison import (  # noqa: E402
    _attach_day_level_rescaled_scores,
    _collect_symbol_rows,
)
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK, _mean  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

TOP_DECILE_FRACTION = 0.10
TARGET_SCENARIOS = ("B_R0_no_rescale", "B_R3b_percentile_candidateonly")


def _day_level_concentration(would_buy_rows: list[dict], h: int) -> dict:
    """would_buy 표본을 거래일별로 묶어 top-decile 거래일 의존도를 계측."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in would_buy_rows:
        by_date[r["trade_date"]].append(r)

    day_means = []
    for trade_date, rows in by_date.items():
        day_means.append((trade_date, _mean([r[f"fwd_{h}"] for r in rows]), len(rows)))

    if len(day_means) < 5:
        return {"note": "거래일 수 부족(<5)", "n_days": len(day_means)}

    overall_mean = _mean([r[f"fwd_{h}"] for r in would_buy_rows])

    ranked = sorted(day_means, key=lambda x: x[1], reverse=True)
    n_days = len(ranked)
    top_n = max(1, int(n_days * TOP_DECILE_FRACTION))
    top_days = {d for d, _, _ in ranked[:top_n]}

    rest_rows = [r for r in would_buy_rows if r["trade_date"] not in top_days]
    rest_mean = _mean([r[f"fwd_{h}"] for r in rest_rows]) if rest_rows else None

    remaining_pct = None
    if overall_mean:
        remaining_pct = round((rest_mean / overall_mean) * 100, 1) if rest_mean is not None else None

    return {
        "n_days": n_days,
        "n_rows": len(would_buy_rows),
        "overall_mean_pct": round(overall_mean * 100, 4),
        "top_decile_n_days": top_n,
        "mean_after_top_decile_removal_pct": round(rest_mean * 100, 4) if rest_mean is not None else None,
        "remaining_pct_of_original": remaining_pct,
    }


def _analyze_window(rows: list[dict], window_label: str) -> dict:
    print(f"\n=== {window_label} (표본 {len(rows)}건) — 거래일 단위 편중도 ===")
    window_report: dict = {"window": window_label, "scenarios": {}}

    for skey in TARGET_SCENARIOS:
        signal_key, score_fn = SCENARIOS[skey]
        funnel = _funnel_for_scenario(rows, signal_key, score_fn)
        would_buy_rows = funnel["would_buy"]

        scenario_report: dict = {"would_buy_n": len(would_buy_rows), "by_horizon": {}}
        print(f"  [{skey}] would_buy={len(would_buy_rows)}")
        for h in FORWARD_HORIZONS_FOCUS:
            conc = _day_level_concentration(would_buy_rows, h)
            scenario_report["by_horizon"][f"T+{h}"] = conc
            print(f"    T+{h}: {conc}")

        window_report["scenarios"][skey] = scenario_report

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

    _attach_day_level_rescaled_scores(all_rows)
    _attach_candidate_only_percentile(all_rows)

    last_date = max(datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in all_rows)
    cutoff = (last_date - timedelta(days=365)).strftime("%Y-%m-%d")
    recent_rows = [r for r in all_rows if r["trade_date"] >= cutoff]

    first_half_rows, second_half_rows = _split_first_second_half(all_rows)
    quarters = _split_into_quarters(all_rows)

    report: dict = {"windows": {}}
    window_defs = [
        ("supplementary_3y", "2차(3년, 전체 표본)", all_rows),
        ("primary_recent_12m", "1차(최근 12개월)", recent_rows),
        ("3y_first_half", "3년 전반부", first_half_rows),
        ("3y_second_half", "3년 후반부", second_half_rows),
        ("quarter_1", "3년 분기1", quarters[0]),
        ("quarter_2", "3년 분기2", quarters[1]),
        ("quarter_3", "3년 분기3", quarters[2]),
        ("quarter_4", "3년 분기4", quarters[3]),
    ]
    for key, label, window_rows in window_defs:
        report["windows"][key] = _analyze_window(window_rows, label)

    report["as_of"] = datetime.now(_KST).isoformat()
    report["symbol_count_used"] = len(symbols) - len(fetch_failures)
    report["fetch_failures"] = fetch_failures
    report["note"] = (
        "기존 SPPV-2.30 산출(logs/signal_ic_alpha_layer_r3_reproducibility_"
        "2026-07-16.json)의 funnel 표본수/평균/t_NW/양수비율은 재사용하고, "
        "이 산출은 would_buy 단계의 거래일 단위 편중도(top-decile-day "
        "leave-out)만 신규 계측한 것이다."
    )

    out_path = "logs/signal_ic_r3b_sppv3_entry_readiness_check_2026-07-17.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
