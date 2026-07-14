#!/usr/bin/env python3
"""SPPV 검증 기간 재설계 — 최근성 우선(primary) + 기존 3년 국면 커버리지(supplementary) (read-only).

``plans/[DESIGN] signal_predictive_power_validation.md`` §16 참고.

배경: 이 시스템은 장기 보유형이 아니라 3개월 이하 중단기 공격형이다. 따라서
검증의 기본값(default)은 "3년 전체를 균등하게 pooled"하는 것이 아니라, 신호가
**최근 시장에서** 짧은 horizon(T+5/T+20)에 유효한지를 우선 확인해야 한다. 다만
최근 구간만 보면 SPPV-2.6(1년, bearish_trend 0일)처럼 특정 국면 표본이 아예
없을 수 있으므로, "필수 국면(하락장 포함) 표본 확보"라는 하드 게이트는 유지한다.

이 스크립트는 SPPV-2.7(``validate_signal_predictive_power_v4_extended_period.py``)
이 이미 채워둔 3년 캐시(``logs/_bars_cache_core87_3y_2026-07-14/``)를 그대로
재사용한다 — **신규 KIS 호출 없음**. 새 로직을 만들지 않고 기존 함수(SPPV-2.7의
표본 수집·IC·quintile·Newey-West 함수)를 재사용하되, 다음 한 가지만 바꾼다:

  - 표본을 trade_date 기준으로 "최근 N개월(기본 12개월)"로 잘라 **1차(primary)**
    판정 대상으로 삼는다.
  - 이미 산출된 3년 전체 결과(``logs/signal_ic_sppv2_7_extended_period_2026-07-14.json``)
    를 **2차(supplementary, 필수 국면 커버리지 게이트)**로 그대로 인용한다 —
    다시 계산하지 않는다(중복 KIS 호출/연산 방지).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_signal_predictive_power_v5_recency_window")

_KST = timezone(timedelta(hours=9))

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v2 import (  # noqa: E402
    _MIN_LOOKBACK,
    _collect_symbol_samples,
)
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    DIRECT_SIGNALS,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _cross_sectional_ic_by_date,
    _fetch_extended_bars,
    _quintile_spread_series,
    _summarize_series,
)

# 1차(primary) 판정 창 — "최근성 우선": 짧은 horizon 신호가 최근 시장에서도
# 유효한지가 핵심이므로 기본값은 최근 12개월로 둔다(§16.2 근거).
RECENT_WINDOW_CALENDAR_DAYS = 365
# 필수 국면(하락장) 최소 표본(거래일) 기준 — 이 미만이면 "국면 커버리지 부족"으로
# 1차 결과만으로 Go 판정하지 않고 2차(3년) 결과를 함께 봐야 한다.
MIN_REGIME_TRADING_DAYS = 30

SUPPLEMENTARY_SPPV27_PATH = "logs/signal_ic_sppv2_7_extended_period_2026-07-14.json"


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")

    # 1) 벤치마크 — SPPV-2.7과 동일 캐시(신규 KIS 호출 없이 캐시 hit 기대)
    bench_bars = await _fetch_extended_bars(client, BENCHMARK_SYMBOL)
    regime_by_date, bench_fwd_by_date = _build_benchmark_daily_series(bench_bars)

    last_date = max(datetime.strptime(d, "%Y-%m-%d") for d in regime_by_date)
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    logger.info("최근성 창(primary) cutoff=%s (최근 %d일)", cutoff, RECENT_WINDOW_CALENDAR_DAYS)

    recent_regime_counts: dict[str, int] = {}
    for d, r in regime_by_date.items():
        if d >= cutoff:
            recent_regime_counts[r] = recent_regime_counts.get(r, 0) + 1
    logger.info("최근 %d일 시장 공통 국면 분포: %s", RECENT_WINDOW_CALENDAR_DAYS, recent_regime_counts)

    # 2) 평가 universe = core 전체 - 벤치마크 (SPPV-2.7과 동일, 자기참조 제거 유지)
    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})

    all_samples: list[dict] = []
    fetch_failures: list[str] = []
    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        if len(bars) < _MIN_LOOKBACK + max(FORWARD_HORIZONS_FOCUS) + 5:
            fetch_failures.append(symbol)
            continue
        samples = _collect_symbol_samples(symbol, bars)
        for row in samples:
            d = row["trade_date"]
            row["common_market_regime"] = regime_by_date.get(d, "unknown")
            bench_fwd = bench_fwd_by_date.get(d, {})
            for h in FORWARD_HORIZONS_FOCUS:
                if h in bench_fwd and f"fwd_{h}" in row:
                    row[f"excess_fwd_{h}"] = row[f"fwd_{h}"] - bench_fwd[h]
        all_samples.extend(samples)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_samples))

    recent_samples = [r for r in all_samples if r["trade_date"] >= cutoff]
    logger.info("전체 표본 %d건 중 최근 %d일 표본 %d건", len(all_samples), RECENT_WINDOW_CALENDAR_DAYS, len(recent_samples))

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "primary_window": {
            "recent_window_calendar_days": RECENT_WINDOW_CALENDAR_DAYS,
            "cutoff_trade_date": cutoff,
            "common_market_regime_distribution": recent_regime_counts,
            "total_rolling_samples": len(recent_samples),
        },
        "supplementary_reference": SUPPLEMENTARY_SPPV27_PATH,
        "min_regime_trading_days_gate": MIN_REGIME_TRADING_DAYS,
        "by_signal": {},
    }

    print("\n=== SPPV 최근성 우선(primary) 검증 — 최근 12개월 ===")
    print(f"cutoff={cutoff}, 최근 표본={len(recent_samples)}건")
    print(f"최근 12개월 시장 공통 국면 분포: {recent_regime_counts}")

    insufficient_regimes = [
        r for r in ["bullish_trend", "range_bound", "bearish_trend", "event_driven_unstable"]
        if recent_regime_counts.get(r, 0) < MIN_REGIME_TRADING_DAYS
    ]
    if insufficient_regimes:
        print(f"⚠️ 최근 12개월 창에서 최소 표본({MIN_REGIME_TRADING_DAYS}거래일) 미달 국면: "
              f"{insufficient_regimes} — 해당 국면 판정은 1차 결과만으로 내리지 않고 "
              f"2차(3년, {SUPPLEMENTARY_SPPV27_PATH})를 함께 참고해야 한다.")
    report["insufficient_regimes_in_primary_window"] = insufficient_regimes

    for sig in DIRECT_SIGNALS:
        report["by_signal"][sig] = {}
        print(f"\n[{sig}]")
        for h in FORWARD_HORIZONS_FOCUS:
            entry: dict = {}
            ic_raw = _cross_sectional_ic_by_date(recent_samples, sig, h, f"fwd_{h}")
            spread_raw = _quintile_spread_series(recent_samples, sig, f"fwd_{h}_net")
            entry["pooled_raw_ic"] = _summarize_series(ic_raw, h, is_pct=False)
            entry["pooled_raw_spread"] = _summarize_series(spread_raw, h)

            entry["by_common_regime_raw_spread"] = {}
            for regime in ["bullish_trend", "bearish_trend", "range_bound", "event_driven_unstable"]:
                s_raw = _quintile_spread_series(
                    recent_samples, sig, f"fwd_{h}_net", common_regime_filter=regime
                )
                entry["by_common_regime_raw_spread"][regime] = _summarize_series(s_raw, h)

            report["by_signal"][sig][f"T+{h}"] = entry
            print(f"  T+{h}: pooled raw IC={entry['pooled_raw_ic']}")
            print(f"        pooled raw spread={entry['pooled_raw_spread']}")
            for regime, v in entry["by_common_regime_raw_spread"].items():
                print(f"        {regime}: {v}")

    out_path = "logs/signal_ic_sppv_recency_window_primary_2026-07-14.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
