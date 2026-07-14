#!/usr/bin/env python3
"""SPPV-2.5 방법론 교정 — 시장 공통 국면(common market regime) 기준 재검증
(read-only).

``plans/[DESIGN] signal_predictive_power_validation.md`` 참고.

**교정 배경**: 기존 SPPV-2.5는 `classify_market_regime()`이 반환하는
`regime_label`로 "국면 내부(within-regime)" 분해를 수행했는데, 이 함수는
시장 지수가 아니라 **평가 대상 종목 자신의** `SignalFeatureSnapshotEntity`
(slow_score/return_3m/price_vs_sma_60 등)만 입력받아 라벨을 매긴다
(`market_regime.py:21-38`). 즉 "bullish_trend" 버킷은 "그날 시장이
상승장이었다"가 아니라 "그날 그 종목 자신의 slow_score가 이미 높았다"는
뜻이며, `slow_score`는 `overall_score`의 구성 요소이므로 이 라벨로
조건화하면 **검정 대상 신호와 같은 계열의 변수로 표본을 선택하는 것**이
된다(선택 편향/치우친 표본 범위 문제) — "시장 국면 대 개별종목 알파"를
가르려던 원래 목적과 다른 문제를 측정하고 있었다.

**이번 교정**: core universe에 이미 포함된 KODEX 200(`069500`, KOSPI200
추종 ETF)을 시장 벤치마크로 사용해:
1. 벤치마크 자신의 기술적 상태로 **거래일 단위 공통 국면 라벨**(그날 전
   종목이 공유하는 하나의 라벨)을 만든다.
2. 벤치마크의 forward return을 빼서 **초과수익(excess return)**을 계산한다.
3. 원신호(raw return) 기준과 초과수익 기준 모두에서 공통국면 내부 quintile
   spread를 재계산한다.

SPPV-2.5가 만든 로컬 캐시(`logs/_bars_cache_core88_2026-07-14/`)를 그대로
재사용한다 — `069500`이 이미 core universe 구성원이라 캐시에 포함되어
있으므로 이번 재검증은 **추가 KIS 호출이 필요 없다**(캐시 hit만 사용,
로그로 확인).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import sqrt
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_signal_predictive_power_v3_market_regime")

_KST = timezone(timedelta(hours=9))

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v2 import (  # noqa: E402
    _BARS_CACHE_DIR,
    _MIN_LOOKBACK,
    _collect_symbol_samples,
    _fetch_year_bars,
    _mean,
    _newey_west_se_of_mean,
    _rank,
    _spearman_ic,
    _stdev,
    _strength_label,
)

DIRECT_SIGNALS = ["slow_score", "fast_score", "overall_score"]
FORWARD_HORIZONS_FOCUS = [5, 20]
BENCHMARK_SYMBOL = "069500"  # KODEX 200 (KOSPI200 추종 ETF) — 이미 core universe 구성원


def _summarize_series(xs: list[float], horizon: int, *, is_pct: bool = True) -> dict:
    n = len(xs)
    if n < 5:
        return {"n_days": n, "note": "표본부족(<5일)"}
    m = _mean(xs)
    std = _stdev(xs)
    t_naive = (m / (std / sqrt(n))) if std else None
    nw_se = _newey_west_se_of_mean(xs, lag=max(horizon - 1, 1))
    t_nw = (m / nw_se) if nw_se else None
    return {
        "n_days": n,
        "mean_pct": round(m * 100, 3) if is_pct else round(m, 4),
        "t_naive": round(t_naive, 2) if t_naive else None,
        "t_newey_west": round(t_nw, 2) if t_nw else None,
        "pct_days_positive": round(sum(1 for x in xs if x > 0) / n, 3),
    }


def _build_benchmark_daily_series(bars) -> tuple[dict, dict]:
    """벤치마크(069500) rolling 재계산으로 거래일별 (공통국면 라벨, {h: fwd_return}) 산출."""
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot

    regime_by_date: dict[str, str] = {}
    fwd_by_date: dict[str, dict[int, float]] = {}

    last_t = len(bars) - 1 - max(FORWARD_HORIZONS_FOCUS)
    for t in range(_MIN_LOOKBACK - 1, last_t + 1):
        window = bars[: t + 1]
        try:
            features, card = build_signal_snapshot(BENCHMARK_SYMBOL, window)
        except Exception:
            continue

        snapshot = SimpleNamespace(
            overall_score=float(card.overall_score),
            fast_score=float(card.fast_score),
            slow_score=float(card.slow_score),
            return_1m_pct=features.return_1m_pct,
            return_3m_pct=features.return_3m_pct,
            price_vs_sma_20_pct=features.price_vs_sma_20_pct,
            price_vs_sma_60_pct=features.price_vs_sma_60_pct,
            volatility_20d_pct=features.volatility_20d_pct,
            atr_14_pct=features.atr_14_pct,
            volume_surge_ratio=features.volume_surge_ratio,
        )
        assessment = classify_market_regime(snapshot)
        trade_date = bars[t].timestamp.strftime("%Y-%m-%d")
        regime_by_date[trade_date] = assessment.regime_label if assessment else "unknown"

        base_close = bars[t].close_price
        fwd_by_date[trade_date] = {}
        for h in FORWARD_HORIZONS_FOCUS:
            fwd_close = bars[t + h].close_price
            fwd_by_date[trade_date][h] = (fwd_close / base_close) - 1.0

    return regime_by_date, fwd_by_date


def _cross_sectional_ic_by_date(
    all_samples: list[dict], signal: str, horizon: int, return_key: str,
    common_regime_filter: str | None = None,
) -> list[float]:
    by_date: dict[str, list[dict]] = defaultdict(list)
    for row in all_samples:
        if common_regime_filter is not None and row.get("common_market_regime") != common_regime_filter:
            continue
        if signal in row and return_key in row:
            by_date[row["trade_date"]].append(row)

    ic_series: list[float] = []
    for rows in by_date.values():
        if len(rows) < 5:
            continue
        xs = [r[signal] for r in rows]
        ys = [r[return_key] for r in rows]
        ic = _spearman_ic(xs, ys)
        if ic is not None:
            ic_series.append(ic)
    return ic_series


def _quintile_spread_series(
    all_samples: list[dict], signal: str, return_key: str,
    common_regime_filter: str | None = None,
) -> list[float]:
    by_date: dict[str, list[dict]] = defaultdict(list)
    for row in all_samples:
        if common_regime_filter is not None and row.get("common_market_regime") != common_regime_filter:
            continue
        if signal in row and return_key in row:
            by_date[row["trade_date"]].append(row)

    spreads: list[float] = []
    for rows in by_date.values():
        if len(rows) < 5:
            continue
        ordered = sorted(rows, key=lambda r: r[signal])
        q = max(1, len(ordered) // 5)
        bottom = ordered[:q]
        top = ordered[-q:]
        top_mean = _mean([r[return_key] for r in top])
        bottom_mean = _mean([r[return_key] for r in bottom])
        if top_mean is not None and bottom_mean is not None:
            spreads.append(top_mean - bottom_mean)
    return spreads


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")

    cache_populated_before = os.path.exists(
        os.path.join(_BARS_CACHE_DIR, f"{BENCHMARK_SYMBOL}.json")
    )
    logger.info("벤치마크(%s) 캐시 존재 여부(사전)=%s", BENCHMARK_SYMBOL, cache_populated_before)

    # 1) 벤치마크(시장 공통 국면 + forward return) 구축
    bench_bars = await _fetch_year_bars(client, BENCHMARK_SYMBOL, cache_dir=_BARS_CACHE_DIR)
    logger.info("%s(벤치마크) 일봉 %d개", BENCHMARK_SYMBOL, len(bench_bars))
    regime_by_date, bench_fwd_by_date = _build_benchmark_daily_series(bench_bars)
    common_regime_counts: dict[str, int] = defaultdict(int)
    for r in regime_by_date.values():
        common_regime_counts[r] += 1
    logger.info("시장 공통 국면 분포(거래일 기준): %s", dict(common_regime_counts))

    # 2) core 전체 종목 rolling 표본 수집 (SPPV-2.5와 동일 캐시 재사용 — 신규 KIS 호출 없음)
    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS)
    all_samples: list[dict] = []
    fetch_failures: list[str] = []
    cache_hits = 0
    cache_misses = 0

    for idx, symbol in enumerate(symbols, start=1):
        cache_path = os.path.join(_BARS_CACHE_DIR, f"{symbol}.json")
        was_cached = os.path.exists(cache_path)
        bars = await _fetch_year_bars(client, symbol, cache_dir=_BARS_CACHE_DIR)
        if was_cached:
            cache_hits += 1
        else:
            cache_misses += 1
        if len(bars) < _MIN_LOOKBACK + max(FORWARD_HORIZONS_FOCUS) + 5:
            fetch_failures.append(symbol)
            continue
        samples = _collect_symbol_samples(symbol, bars)
        # 시장 공통 국면/초과수익 부착
        for row in samples:
            d = row["trade_date"]
            row["common_market_regime"] = regime_by_date.get(d, "unknown")
            bench_fwd = bench_fwd_by_date.get(d, {})
            for h in FORWARD_HORIZONS_FOCUS:
                if h in bench_fwd and f"fwd_{h}" in row:
                    row[f"excess_fwd_{h}"] = row[f"fwd_{h}"] - bench_fwd[h]
        all_samples.extend(samples)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건 (캐시 hit=%d, miss=%d)",
                        idx, len(symbols), len(all_samples), cache_hits, cache_misses)

    logger.info("전체 rolling 표본: %d건 (종목 %d개, 실패 %d개) — 캐시 hit=%d/miss=%d",
                len(all_samples), len(symbols) - len(fetch_failures), len(fetch_failures),
                cache_hits, cache_misses)

    # 종목별(기존, 잘못된 방식) regime 분포도 참고용으로 재확인
    own_regime_counts: dict[str, int] = defaultdict(int)
    for row in all_samples:
        own_regime_counts[row.get("regime_label", "unknown")] += 1

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "total_rolling_samples": len(all_samples),
        "common_market_regime_distribution_by_trading_day": dict(common_regime_counts),
        "own_symbol_regime_distribution_by_sample": dict(own_regime_counts),
        "by_signal": {},
    }

    print("\n=== SPPV 방법론 교정 — 시장 공통 국면(KODEX 200) 기준 재검증 ===")
    print(f"표본: {len(all_samples)}건, 캐시 hit={cache_hits}/miss={cache_misses}")
    print(f"시장 공통 국면 분포(거래일 기준): {dict(common_regime_counts)}")
    print(f"(참고) 기존 종목별 regime_label 분포(표본 기준): {dict(own_regime_counts)}")

    for sig in DIRECT_SIGNALS:
        report["by_signal"][sig] = {}
        print(f"\n[{sig}]")
        for h in FORWARD_HORIZONS_FOCUS:
            entry: dict = {}

            # (a) raw return, 전체(pooled) — cross-sectional IC + quintile spread
            ic_raw = _cross_sectional_ic_by_date(all_samples, sig, h, f"fwd_{h}")
            spread_raw = _quintile_spread_series(all_samples, sig, f"fwd_{h}_net")
            entry["pooled_raw_ic"] = _summarize_series(ic_raw, h, is_pct=False)
            entry["pooled_raw_spread"] = _summarize_series(spread_raw, h)

            # (b) 초과수익(excess return, 벤치마크 차감) 기준, 전체(pooled)
            ic_excess = _cross_sectional_ic_by_date(all_samples, sig, h, f"excess_fwd_{h}")
            spread_excess = _quintile_spread_series(all_samples, sig, f"excess_fwd_{h}")
            entry["pooled_excess_ic"] = _summarize_series(ic_excess, h, is_pct=False)
            entry["pooled_excess_spread"] = _summarize_series(spread_excess, h)

            # (c) 시장 공통 국면 내부 분해 (raw return 기준, excess도 병기)
            entry["by_common_regime_raw_spread"] = {}
            entry["by_common_regime_excess_spread"] = {}
            for regime in ["bullish_trend", "bearish_trend", "range_bound", "event_driven_unstable"]:
                s_raw = _quintile_spread_series(
                    all_samples, sig, f"fwd_{h}_net", common_regime_filter=regime
                )
                s_excess = _quintile_spread_series(
                    all_samples, sig, f"excess_fwd_{h}", common_regime_filter=regime
                )
                entry["by_common_regime_raw_spread"][regime] = _summarize_series(s_raw, h)
                entry["by_common_regime_excess_spread"][regime] = _summarize_series(s_excess, h)

            report["by_signal"][sig][f"T+{h}"] = entry

            print(f"  T+{h}:")
            print(f"    pooled raw IC={entry['pooled_raw_ic']}")
            print(f"    pooled excess IC={entry['pooled_excess_ic']}")
            print(f"    pooled raw spread={entry['pooled_raw_spread']}")
            print(f"    pooled excess spread={entry['pooled_excess_spread']}")
            print("    공통국면별 raw spread:")
            for regime, v in entry["by_common_regime_raw_spread"].items():
                print(f"      {regime}: {v}")
            print("    공통국면별 excess spread:")
            for regime, v in entry["by_common_regime_excess_spread"].items():
                print(f"      {regime}: {v}")

    out_path = "logs/signal_ic_sppv_market_regime_correction_2026-07-14.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
