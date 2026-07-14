#!/usr/bin/env python3
"""SPPV-2.14 — fast 계열 완전 신규 신호 2종 실측 (read-only).

``plans/[DESIGN] signal_predictive_power_validation.md`` §20.5, §22 참고.

지금까지 실패한 fast 계열 후보(`fast_trend`=SMA20 이격 계단함수,
`sma5_over_sma20_gap`=단기 이동평균 격차 연속값, `rsi_signal`=RSI
계단함수, `rsi_mean_reversion`=RSI 연속 반전)는 **전부 "자기 자신의
과거 가격 수준"만 보는 절대(absolute) 기술적 지표**였다 — 계산 창의
길이나 계단함수 여부와 무관하게, 하락장에서 구조적으로 실패하거나
(추세추종형) 하락장에서만 통하는(평균회귀형) 동일한 패턴을 반복했다.

이번엔 **구조적으로 다른 두 축**에서 신규 후보를 만든다 — 새 raw
데이터 소스를 추가하지 않고, 기존 `PriceBar`/`TechnicalFeatureSnapshot`
필드만으로 계산하되 "가격 수준 대비" 로직 자체를 쓰지 않는다.

1. **`money_flow_5d`(자금 흐름 축)**: 가격 *수준*이 아니라 최근 5거래일
   동안 상승일/하락일에 실린 거래대금(turnover)의 비대칭을 본다 —
   ``sum(sign(당일수익률) × turnover) / sum(turnover)``. 추세추종도
   평균회귀도 아니고, "최근 거래대금이 매수 쪽에 쏠렸는가"를 직접
   측정하는 자금 흐름(volume-price flow) 지표다. `volume_confirmation`
   (거래량 급증 여부만 봄, 방향 무관)과도 다르다 — 방향까지 함께 본다.
2. **`relative_strength_rank_1m`(상대강도 축)**: 절대 수익률이 아니라
   그날 표본에 포함된 종목들 사이에서 `return_1m_pct`의 **상대 순위**를
   [-1, 1]로 스케일링한 cross-sectional feature다. "이 종목이 좋은가
   나쁜가"가 아니라 "이 종목이 그날 다른 종목들보다 상대적으로 강한가"
   를 묻는다 — 시장 베타(그날 전체가 오르든 내리든)를 구조적으로
   제거한다는 점이 절대 수준 지표(`fast_trend` 등)와 근본적으로 다르다.

§16 이원 기준(1차=최근 12개월, 2차=3년 국면 게이트)을 그대로 적용한다.
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
logger = logging.getLogger("validate_signal_predictive_power_v10_new_fast_features")

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
_MONEY_FLOW_WINDOW = 5


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

        # 후보 1: money_flow_5d — 최근 5거래일 상승/하락일 거래대금 비대칭
        signed_turnover = 0.0
        total_turnover = 0.0
        start = max(1, t - _MONEY_FLOW_WINDOW + 1)
        for i in range(start, t + 1):
            close_i = bars[i].close_price
            close_prev = bars[i - 1].close_price
            turnover_i = bars[i].turnover if bars[i].turnover is not None else bars[i].volume
            if turnover_i is None:
                continue
            sign = 1.0 if close_i > close_prev else (-1.0 if close_i < close_prev else 0.0)
            signed_turnover += sign * turnover_i
            total_turnover += turnover_i
        if total_turnover > 0:
            row["money_flow_5d"] = signed_turnover / total_turnover

        # 후보 2 원재료: 그날의 return_1m_pct(절대값) — cross-sectional 순위는
        # 전체 표본 수집 후 후처리(post-process)로 계산한다.
        if features.return_1m_pct is not None:
            row["_return_1m_pct_raw"] = features.return_1m_pct

        base_close = bars[t].close_price
        for h in FORWARD_HORIZONS_FOCUS:
            fwd_close = bars[t + h].close_price
            raw_ret = (fwd_close / base_close) - 1.0
            row[f"fwd_{h}"] = raw_ret
            row[f"fwd_{h}_net"] = raw_ret - (_ROUND_TRIP_COST_BPS / 10_000.0)

        samples.append(row)
    return samples


def _attach_relative_strength_rank(all_samples: list[dict]) -> None:
    """거래일별 cross-sectional return_1m_pct 순위를 [-1, 1]로 스케일링해 부여."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for row in all_samples:
        if "_return_1m_pct_raw" in row:
            by_date[row["trade_date"]].append(row)

    for rows in by_date.values():
        n = len(rows)
        if n < 2:
            for row in rows:
                row["relative_strength_rank_1m"] = 0.0
            continue
        ordered = sorted(rows, key=lambda r: r["_return_1m_pct_raw"])
        for idx, row in enumerate(ordered):
            row["relative_strength_rank_1m"] = (idx / (n - 1)) * 2.0 - 1.0


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

    _attach_relative_strength_rank(all_samples)
    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_samples), len(fetch_failures))

    recent_cutoff_12m = (last_date - timedelta(days=365)).strftime("%Y-%m-%d")
    recent_samples_12m = [r for r in all_samples if r["trade_date"] >= recent_cutoff_12m]

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_samples),
        "by_candidate": {},
    }

    print("\n=== SPPV-2.14 — fast 계열 완전 신규 신호 2종 실측 ===")
    for sig in ["money_flow_5d", "relative_strength_rank_1m"]:
        report["by_candidate"][sig] = {}
        print(f"\n[{sig}]")
        for h in FORWARD_HORIZONS_FOCUS:
            primary = summarize_tier(recent_samples_12m, sig, h)
            supplementary = summarize_tier(all_samples, sig, h)
            by_regime = {
                regime: summarize_tier(all_samples, sig, h, regime)
                for regime in ["bullish_trend", "bearish_trend", "range_bound", "event_driven_unstable"]
            }
            report["by_candidate"][sig][f"T+{h}"] = {
                "primary_recent_12m": primary, "supplementary_3y": supplementary,
                "supplementary_3y_by_regime": by_regime,
            }
            print(f"  T+{h}: 1차(12m) spread t_NW={primary['spread'].get('t_newey_west')}, "
                  f"2차(3년) spread t_NW={supplementary['spread'].get('t_newey_west')}")
            for regime, v in by_regime.items():
                nd = v["spread"].get("n_days", 0)
                tag = f"t_NW={v['spread'].get('t_newey_west')}" if nd >= MIN_REGIME_TRADING_DAYS else "표본부족"
                print(f"        {regime}(n={nd}): {tag}")

    out_path = "logs/signal_ic_sppv2_14_new_fast_features_2026-07-14.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
