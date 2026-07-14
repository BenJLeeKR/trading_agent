#!/usr/bin/env python3
"""SPPV-2.12 — §19.6 후속: regime_switch_v1 1차 게이트 예외 규칙 + fast 계열 신규 feature (read-only).

``plans/[DESIGN] signal_predictive_power_validation.md`` §19.6 참고.

§19(SPPV-2.11)는 두 가지 과제를 남겼다 — 새 방법론을 다시 설계하지 않고
§16 이원 기준·기존 함수를 그대로 재사용한다.

1. **`regime_switch_v1`의 1차(primary) 게이트 예외 규칙 비교**: 최근
   12개월 창에 시장 공통 `bearish_trend`가 0일이라, 이 국면 조건부 신호의
   절반(`reversal_1m`)은 "최근성 창" 자체로는 검증할 방법이 없다. 이를
   억지로 통과시키지 않고, 방어 가능한 대안 규칙 3개를 정의·비교한다.
   - **규칙 A(관찰 유예, 절차적)**: 수치를 조작하지 않고, "그 국면이 실제
     재발할 때까지 Hold 상태를 유지하며, 재발 즉시 자동 재검증한다"는
     절차만 규정한다. 측정치 없음(정의상 당연) — 논리적 방어 가능성만
     평가한다.
   - **규칙 B(구성요소별 최근-실사례 게이트)**: 국면 조건부 구성요소는
     "최근 12개월 달력"이 아니라 "그 국면이 가장 최근에 발생한 실제
     사례 표본"을 1차 창으로 인정한다(예: 가장 최근 `bearish_trend`
     발생 48거래일 — §18/§19에서 이미 반분 검증한 후반부와 동일 표본).
   - **규칙 C(적응형 최소 국면 표본 창)**: "최근성 우선"을 지키되, 목표
     국면의 최소 표본(`MIN_REGIME_TRADING_DAYS=30`)을 채울 때까지만
     과거로 확장한 **적응형** 창을 1차로 쓴다 — 국면이 자주 나타나면
     창이 짧아지고, 드물면(하락장처럼) 창이 길어진다. 정적 12/18/21개월
     같은 임의 상수 대신, 게이트 자체가 요구하는 "최소 30일" 조건을
     정확히 만족하는 가장 짧은 창을 자동으로 계산한다.

2. **`fast` 계열 신규 feature 2종 실측**: `fast_score`가 leave-one-out
   으로도 살아나지 않는다는 §19 결론에 따라, 운영 하드코딩 계단함수
   대신 raw `TechnicalFeatureSnapshot` 값으로부터 **연속값** feature를
   새로 정의한다(운영 로직 변경 아님, 검증용 shadow).
   - `rsi_mean_reversion = -(rsi_14 - 50)` — 현재 `rsi_signal`(과매수를
     양(+)으로 취급하는 추세추종형 계단함수)이 §17/§19에서 유의하게
     역방향이었던 관측을 근거로, 아예 평균회귀(mean-reversion) 방향으로
     정의를 뒤집은 연속형 신호.
   - `sma5_over_sma20_gap = (sma_5/sma_20 - 1) * 100` — 현재 `fast_trend`
     (가격 대 SMA20 이격, 계단함수)가 §19에서 하락장 역전의 주된 원인
     으로 확인된 것과 달리, 더 짧은 이동평균 간 격차(단기 추세 가속도)를
     연속값으로 사용해 계단함수의 둔감함/지연 문제를 회피할 수 있는지
     확인.

3년 캐시(`logs/_bars_cache_core87_3y_2026-07-14/`)를 재사용해 **신규 KIS
호출 없이** 검증한다.
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
logger = logging.getLogger("validate_signal_predictive_power_v9_gate_and_fast_features")

_KST = timezone(timedelta(hours=9))

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _cross_sectional_ic_by_date,
    _fetch_extended_bars,
    _quintile_spread_series,
    _summarize_series,
)

MIN_REGIME_TRADING_DAYS = 30
_ROUND_TRIP_COST_BPS = 30.0


def _collect_feature_samples(symbol: str, bars: list) -> list[dict]:
    from agent_trading.services.signal_backbone import build_signal_snapshot

    samples: list[dict] = []
    last_t = len(bars) - 1 - max(FORWARD_HORIZONS_FOCUS)
    if last_t < _MIN_LOOKBACK - 1:
        return samples

    for t in range(_MIN_LOOKBACK - 1, last_t + 1):
        window = bars[: t + 1]
        try:
            features, card = build_signal_snapshot(symbol, window)
        except Exception:
            continue

        row: dict = {"symbol": symbol, "trade_date": bars[t].timestamp.strftime("%Y-%m-%d")}

        # 과제 1(게이트 비교)에 필요한 기존 신호 재사용
        vol = features.volatility_20d_pct
        ret3m = features.return_3m_pct
        ret1m = features.return_1m_pct
        if ret3m is not None:
            row["risk_adj_momentum_3m"] = ret3m / max(vol, 1.0) if vol is not None else ret3m
        if ret1m is not None:
            row["reversal_1m"] = -ret1m

        # 과제 2(신규 fast 계열 feature)
        if features.rsi_14 is not None:
            row["rsi_mean_reversion"] = -(features.rsi_14 - 50.0)
        if features.sma_5 is not None and features.sma_20 is not None and features.sma_20 != 0:
            row["sma5_over_sma20_gap"] = (features.sma_5 / features.sma_20 - 1.0) * 100.0

        base_close = bars[t].close_price
        for h in FORWARD_HORIZONS_FOCUS:
            fwd_close = bars[t + h].close_price
            raw_ret = (fwd_close / base_close) - 1.0
            row[f"fwd_{h}"] = raw_ret
            row[f"fwd_{h}_net"] = raw_ret - (_ROUND_TRIP_COST_BPS / 10_000.0)

        samples.append(row)
    return samples


def summarize_tier(samples: list[dict], sig: str, h: int, regime_filter: str | None = None) -> dict:
    ic = _cross_sectional_ic_by_date(samples, sig, h, f"fwd_{h}", common_regime_filter=regime_filter)
    spread = _quintile_spread_series(samples, sig, f"fwd_{h}_net", common_regime_filter=regime_filter)
    return {"ic": _summarize_series(ic, h, is_pct=False), "spread": _summarize_series(spread, h)}


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")

    bench_bars = await _fetch_extended_bars(client, BENCHMARK_SYMBOL)
    regime_by_date, _ = _build_benchmark_daily_series(bench_bars)
    last_date = max(datetime.strptime(d, "%Y-%m-%d") for d in regime_by_date)

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})
    all_samples: list[dict] = []
    fetch_failures: list[str] = []
    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        if len(bars) < _MIN_LOOKBACK + max(FORWARD_HORIZONS_FOCUS) + 5:
            fetch_failures.append(symbol)
            continue
        samples = _collect_feature_samples(symbol, bars)
        for row in samples:
            row["common_market_regime"] = regime_by_date.get(row["trade_date"], "unknown")
        all_samples.extend(samples)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_samples))

    for row in all_samples:
        if row.get("common_market_regime") == "bearish_trend":
            row["regime_switch_v1"] = row.get("reversal_1m")
        else:
            row["regime_switch_v1"] = row.get("risk_adj_momentum_3m")

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_samples), len(fetch_failures))

    recent_cutoff_12m = (last_date - timedelta(days=365)).strftime("%Y-%m-%d")
    recent_samples_12m = [r for r in all_samples if r["trade_date"] >= recent_cutoff_12m]

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_samples),
        "task1_gate_rules": {},
        "task2_new_fast_features": {},
    }

    print("\n=== SPPV-2.12 — §19.6 후속: regime_switch_v1 게이트 규칙 + fast 계열 신규 feature ===")

    # ── 과제 1: 게이트 규칙 A/B/C ─────────────────────────────────────────
    print("\n[과제 1] regime_switch_v1 1차 게이트 예외 규칙 비교")

    bearish_dates_sorted = sorted(d for d, r in regime_by_date.items() if r == "bearish_trend")
    n_bearish = len(bearish_dates_sorted)
    report["task1_gate_rules"]["bearish_days_total_3y"] = n_bearish

    # 규칙 B: 가장 최근 bearish_trend 발생 48거래일(§18/§19의 후반부와 동일 정의)
    rule_b_mid = n_bearish // 2
    rule_b_dates = set(bearish_dates_sorted[rule_b_mid:])
    rule_b_samples = [r for r in all_samples if r["trade_date"] in rule_b_dates]
    print(f"  [규칙 B] 최근 발생 bearish_trend {len(rule_b_dates)}거래일 표본으로 reversal_1m 재검증")
    report["task1_gate_rules"]["rule_b_recent_regime_occurrence"] = {
        "n_days": len(rule_b_dates), "date_range": [min(rule_b_dates), max(rule_b_dates)] if rule_b_dates else [],
        "by_horizon": {},
    }
    for h in FORWARD_HORIZONS_FOCUS:
        s = summarize_tier(rule_b_samples, "reversal_1m", h)
        report["task1_gate_rules"]["rule_b_recent_regime_occurrence"]["by_horizon"][f"T+{h}"] = s
        print(f"    T+{h}: reversal_1m spread t_NW={s['spread'].get('t_newey_west')} (n_days={s['spread'].get('n_days')})")

    # 규칙 C: 최소 30거래일을 채우는 가장 짧은(=가장 최근) 적응형 창
    if n_bearish >= MIN_REGIME_TRADING_DAYS:
        rule_c_dates = set(bearish_dates_sorted[-MIN_REGIME_TRADING_DAYS:])
    else:
        rule_c_dates = set(bearish_dates_sorted)
    rule_c_samples = [r for r in all_samples if r["trade_date"] in rule_c_dates]
    print(f"  [규칙 C] 적응형 최소 국면 표본 창(최근 {len(rule_c_dates)}거래일, 목표 {MIN_REGIME_TRADING_DAYS}일) 재검증")
    report["task1_gate_rules"]["rule_c_adaptive_min_regime_window"] = {
        "n_days": len(rule_c_dates), "date_range": [min(rule_c_dates), max(rule_c_dates)] if rule_c_dates else [],
        "by_horizon": {},
    }
    for h in FORWARD_HORIZONS_FOCUS:
        s = summarize_tier(rule_c_samples, "reversal_1m", h)
        report["task1_gate_rules"]["rule_c_adaptive_min_regime_window"]["by_horizon"][f"T+{h}"] = s
        print(f"    T+{h}: reversal_1m spread t_NW={s['spread'].get('t_newey_west')} (n_days={s['spread'].get('n_days')})")

    # regime_switch_v1 전체(2차/1차 참고용, §19 재확인)
    print("  [참고] regime_switch_v1 §19 재확인(1차=최근 12개월 달력, 2차=3년 전체)")
    report["task1_gate_rules"]["regime_switch_v1_reference"] = {}
    for h in FORWARD_HORIZONS_FOCUS:
        primary = summarize_tier(recent_samples_12m, "regime_switch_v1", h)
        supplementary = summarize_tier(all_samples, "regime_switch_v1", h)
        report["task1_gate_rules"]["regime_switch_v1_reference"][f"T+{h}"] = {
            "primary_recent_12m_calendar": primary, "supplementary_3y": supplementary,
        }
        print(f"    T+{h}: 1차(12m 달력) t_NW={primary['spread'].get('t_newey_west')}, "
              f"2차(3년) t_NW={supplementary['spread'].get('t_newey_west')}")

    # ── 과제 2: fast 계열 신규 feature 2종 — §16 이원 기준 ───────────────
    print("\n[과제 2] fast 계열 신규 feature — rsi_mean_reversion, sma5_over_sma20_gap")
    for sig in ["rsi_mean_reversion", "sma5_over_sma20_gap"]:
        report["task2_new_fast_features"][sig] = {}
        print(f"  [{sig}]")
        for h in FORWARD_HORIZONS_FOCUS:
            primary = summarize_tier(recent_samples_12m, sig, h)
            supplementary = summarize_tier(all_samples, sig, h)
            by_regime = {
                regime: summarize_tier(all_samples, sig, h, regime)
                for regime in ["bullish_trend", "bearish_trend", "range_bound", "event_driven_unstable"]
            }
            report["task2_new_fast_features"][sig][f"T+{h}"] = {
                "primary_recent_12m": primary, "supplementary_3y": supplementary,
                "supplementary_3y_by_regime": by_regime,
            }
            print(f"    T+{h}: 1차(12m) spread t_NW={primary['spread'].get('t_newey_west')}, "
                  f"2차(3년) spread t_NW={supplementary['spread'].get('t_newey_west')}")
            for regime, v in by_regime.items():
                nd = v["spread"].get("n_days", 0)
                tag = f"t_NW={v['spread'].get('t_newey_west')}" if nd >= MIN_REGIME_TRADING_DAYS else "표본부족"
                print(f"          {regime}(n={nd}): {tag}")

    out_path = "logs/signal_ic_sppv2_12_gate_and_fast_features_2026-07-14.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
