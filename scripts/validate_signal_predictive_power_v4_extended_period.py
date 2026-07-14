#!/usr/bin/env python3
"""SPPV-2.7 — 하락장 포함 기간 확장 + 벤치마크 자기참조 제거 재검증 (read-only).

``plans/[DESIGN] signal_predictive_power_validation.md`` §12.6 참고.

SPPV-2.6(시장 공통 국면 기준 재검증)이 남긴 두 가지 과제를 처리한다:

1. **자기참조 문제 제거**: SPPV-2.6은 `069500`(KODEX 200)을 시장 벤치마크로
   쓰면서 동시에 평가 대상 core universe(88종목)에도 포함시켰다 —
   벤치마크가 자기 자신과도 비교되는 자기참조였다. 이번엔 **평가 universe
   에서 벤치마크 심볼을 제외**한다(core 87종목).
2. **기간 확장**: 기존 1년(약 190 rolling 거래일) 표본은 시장 공통 기준
   (KODEX 200)으로 bullish_trend 97%, bearish_trend **0일**이었다 —
   하락장 검증이 원천적으로 불가능했다. 이번엔 조회 기간을 **약 3년**으로
   늘려 실제 조정/하락 국면이 포함되는지 확인한다.

방법은 SPPV-2.6과 동일(시장 공통 국면 라벨 + 초과수익 + pooled/공통국면
내부 cross-sectional IC·quintile spread·Newey-West 보정)하되, 표본
universe와 기간만 교정한다 — 신규 로직을 다시 설계하지 않고 기존 함수를
그대로 재사용한다.

DB write / 주문 경로 / 실시간 구독 없음. KIS 과거 일봉 조회(read)만
수행한다. 3년치는 회당 ~100거래일 제한 때문에 슬라이딩 호출 수가
늘어나므로 rate budget 보호를 위해 종목 간 sleep을 유지한다.
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
logger = logging.getLogger("validate_signal_predictive_power_v4_extended_period")

_KST = timezone(timedelta(hours=9))

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v2 import (  # noqa: E402
    _MIN_LOOKBACK,
    _collect_symbol_samples,
    _mean,
    _newey_west_se_of_mean,
    _rows_to_bars,
    _spearman_ic,
    _stdev,
)

DIRECT_SIGNALS = ["slow_score", "fast_score", "overall_score"]
FORWARD_HORIZONS_FOCUS = [5, 20]
BENCHMARK_SYMBOL = "069500"  # KODEX 200 (KOSPI200 추종 ETF)

# SPPV-2.6과 별도 캐시 — 3년치는 데이터량이 달라 1년 캐시와 섞으면 안 됨
_BARS_CACHE_DIR_3Y = "logs/_bars_cache_core87_3y_2026-07-14"
_LOOKBACK_CALENDAR_DAYS = 1100  # 약 3년
_WINDOW_DAYS = 100  # KIS 100거래일 제한 보수적으로 잡음
_SLEEP_SECONDS = 0.3


async def _fetch_extended_bars(client, symbol: str):
    """약 3년치 일봉을 슬라이딩 조회 + 로컬 캐시(전용 디렉터리)."""
    cache_path = os.path.join(_BARS_CACHE_DIR_3Y, f"{symbol}.json")
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            merged = json.load(f)
        bars = _rows_to_bars(merged)
        if bars:
            return bars

    end = datetime.now(_KST).date()
    start = end - timedelta(days=_LOOKBACK_CALENDAR_DAYS)

    merged: dict[str, dict] = {}
    window_start = start
    while window_start < end:
        window_end = min(window_start + timedelta(days=_WINDOW_DAYS), end)
        try:
            raw_rows = await client.inquire_daily_itemchartprice(
                symbol=symbol,
                market_code="J",
                start_date=window_start.strftime("%Y%m%d"),
                end_date=window_end.strftime("%Y%m%d"),
                period_div_code="D",
                adjusted_price=True,
            )
        except Exception as exc:
            logger.warning("%s: 일봉 조회 실패(%s~%s) — %s", symbol, window_start, window_end, exc)
            raw_rows = []
        for raw in raw_rows:
            d = str(raw.get("stck_bsop_date", "")).strip()
            if d:
                merged[d] = raw
        await asyncio.sleep(_SLEEP_SECONDS)
        window_start = window_end + timedelta(days=1)

    os.makedirs(_BARS_CACHE_DIR_3Y, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)

    return _rows_to_bars(merged)


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
    logger.info("KIS client env=%s (3년 캐시=%s)", getattr(client, "env", None), _BARS_CACHE_DIR_3Y)

    # 1) 벤치마크(시장 공통 국면 + forward return) — 평가 universe에서 제외
    bench_bars = await _fetch_extended_bars(client, BENCHMARK_SYMBOL)
    logger.info("%s(벤치마크, 평가 universe 제외) 일봉 %d개", BENCHMARK_SYMBOL, len(bench_bars))
    regime_by_date, bench_fwd_by_date = _build_benchmark_daily_series(bench_bars)
    common_regime_counts: dict[str, int] = defaultdict(int)
    for r in regime_by_date.values():
        common_regime_counts[r] += 1
    logger.info("시장 공통 국면 분포(거래일 기준, 약 3년): %s", dict(common_regime_counts))

    # 2) 평가 universe = core 전체 - 벤치마크 심볼 (자기참조 제거)
    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})
    logger.info("평가 대상 종목 수(벤치마크 제외): %d", len(symbols))

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

    logger.info("전체 rolling 표본: %d건 (종목 %d개, 실패 %d개)",
                len(all_samples), len(symbols) - len(fetch_failures), len(fetch_failures))

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "benchmark_excluded_from_evaluation_universe": True,
        "lookback_calendar_days": _LOOKBACK_CALENDAR_DAYS,
        "symbol_count_total_excl_benchmark": len(symbols),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples": len(all_samples),
        "common_market_regime_distribution_by_trading_day": dict(common_regime_counts),
        "by_signal": {},
    }

    print("\n=== SPPV-2.7 하락장 포함 기간 확장 + 자기참조 제거 재검증 ===")
    print(f"평가 종목: {report['symbol_count_used']}/{report['symbol_count_total_excl_benchmark']} "
          f"(벤치마크 {BENCHMARK_SYMBOL} 제외), 표본: {len(all_samples)}건")
    print(f"시장 공통 국면 분포(거래일 기준, 약 3년): {dict(common_regime_counts)}")

    if not any(k for k in common_regime_counts if k == "bearish_trend"):
        print("⚠️ 경고: 이 기간에도 시장 공통 bearish_trend 거래일이 없습니다 — "
              "하락장 검증은 여전히 불가능합니다. 아래 결과는 이 한계를 안고 해석해야 합니다.")

    for sig in DIRECT_SIGNALS:
        report["by_signal"][sig] = {}
        print(f"\n[{sig}]")
        for h in FORWARD_HORIZONS_FOCUS:
            entry: dict = {}

            ic_raw = _cross_sectional_ic_by_date(all_samples, sig, h, f"fwd_{h}")
            spread_raw = _quintile_spread_series(all_samples, sig, f"fwd_{h}_net")
            entry["pooled_raw_ic"] = _summarize_series(ic_raw, h, is_pct=False)
            entry["pooled_raw_spread"] = _summarize_series(spread_raw, h)

            ic_excess = _cross_sectional_ic_by_date(all_samples, sig, h, f"excess_fwd_{h}")
            spread_excess = _quintile_spread_series(all_samples, sig, f"excess_fwd_{h}")
            entry["pooled_excess_ic"] = _summarize_series(ic_excess, h, is_pct=False)
            entry["pooled_excess_spread"] = _summarize_series(spread_excess, h)

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

    out_path = "logs/signal_ic_sppv2_7_extended_period_2026-07-14.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
