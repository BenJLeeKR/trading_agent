#!/usr/bin/env python3
"""SPPV-2.10 — §17.5 후속 3과제 실측 검증 (read-only).

``plans/[DESIGN] signal_predictive_power_validation.md`` §17.5 참고.

SPPV-2.9(§17)가 남긴 세 과제를 그대로 이어간다 — 새 검증 방법론을 다시
설계하지 않고, §16(SPPV-2.8)에서 확정한 1차(최근 창)/2차(3년, 시장 공통
국면 게이트) 이원 기준을 그대로 재사용한다.

1. **`fast_score_v2` shadow 정의·검증**: `rsi_signal`이 T+20에서 유의하게
   역방향(§17, t_NW=-2.94)이었으므로, 이를 (a) 제거하고 나머지 3개 sub-
   component 가중치를 재정규화한 버전(`fast_score_v2_drop`)과 (b) 부호를
   반전한 버전(`fast_score_v2_flip`) 두 가지를 shadow로 만들어 같은 §16
   기준으로 검증한다 — 운영 `fast_score` 가중치 상수(0.3/0.2/0.15/0.35)는
   그대로 두고 rsi_signal 항만 바꾼다(새 로직 설계 아님, 기존 조합 변형).
2. **`risk_adj_momentum_3m` 재검증**: §17에서 1차(최근 12개월) 유의성이
   |t_NW|=1.47로 게이트(≥2) 미달이었다. 1차 창을 12개월→18개월로 넓혀
   재검증한다.
3. **`reversal_1m` 하락장 조건부 오버레이 분리 검증**: 이 신호는 시장 공통
   국면이 `bearish_trend`로 판정된 날에만 활성화하는 오버레이로 검증
   대상을 좁힌다. 하락장은 3년 표본(96거래일)에서만 확보되므로(§16.3,
   최근 12개월 창은 bearish_trend 0일), 이 신호에는 "1차=최근 창" 기준을
   그대로 적용할 수 없다 — 대신 **하락장 96거래일을 시간순으로 반분해
   전반부/후반부 각각에서 유의성이 유지되는지**로 표본 내 안정성(poor-man's
   out-of-sample)을 확인한다.

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
logger = logging.getLogger("validate_signal_predictive_power_v7_followup")

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

# 과제 2: 1차 창을 12개월→18개월로 확장
RECENT_WINDOW_VARIANTS_DAYS = {"12m": 365, "18m": 548}

# fast_score 원 가중치(signal_backbone._score_features, 그대로 인용)
_FAST_TREND_W = 0.3
_VOLUME_CONFIRM_W = 0.2
_RSI_W = 0.15
_VOLATILITY_PENALTY_W = 0.35


def _collect_feature_samples(symbol: str, bars: list) -> list[dict]:
    from agent_trading.services.signal_backbone import build_signal_snapshot

    samples: list[dict] = []
    last_t = len(bars) - 1 - max(FORWARD_HORIZONS_FOCUS)
    if last_t < _MIN_LOOKBACK - 1:
        return samples

    drop_w_sum = _FAST_TREND_W + _VOLUME_CONFIRM_W + _VOLATILITY_PENALTY_W  # rsi 제외 재정규화 분모

    for t in range(_MIN_LOOKBACK - 1, last_t + 1):
        window = bars[: t + 1]
        try:
            features, card = build_signal_snapshot(symbol, window)
        except Exception:
            continue

        cs = card.component_scores
        fast_trend = cs.get("fast_trend")
        volume_confirmation = cs.get("volume_confirmation")
        rsi_signal = cs.get("rsi_signal")
        volatility_penalty = cs.get("volatility_penalty")

        row: dict = {"symbol": symbol, "trade_date": bars[t].timestamp.strftime("%Y-%m-%d")}

        if None not in (fast_trend, volume_confirmation, rsi_signal, volatility_penalty):
            # (a) rsi_signal 제거 + 나머지 가중치 재정규화(합=1 유지)
            row["fast_score_v2_drop"] = (
                _FAST_TREND_W * fast_trend
                + _VOLUME_CONFIRM_W * volume_confirmation
                + _VOLATILITY_PENALTY_W * volatility_penalty
            ) / drop_w_sum
            # (b) rsi_signal 부호만 반전(가중치·다른 항은 원안과 동일)
            row["fast_score_v2_flip"] = (
                _FAST_TREND_W * fast_trend
                + _VOLUME_CONFIRM_W * volume_confirmation
                + (-_RSI_W) * rsi_signal
                + _VOLATILITY_PENALTY_W * volatility_penalty
            )
            # 비교 기준(원안 fast_score, 재계산 — card.fast_score와 동일해야 함)
            row["fast_score_orig_recomputed"] = float(card.fast_score)

        vol = features.volatility_20d_pct
        ret3m = features.return_3m_pct
        ret1m = features.return_1m_pct
        if ret3m is not None:
            row["risk_adj_momentum_3m"] = ret3m / max(vol, 1.0) if vol is not None else ret3m
        if ret1m is not None:
            row["reversal_1m"] = -ret1m

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

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_samples), len(fetch_failures))

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_samples),
        "task1_fast_score_v2": {},
        "task2_risk_adj_momentum_3m_window_variants": {},
        "task3_reversal_1m_bearish_overlay": {},
    }

    print("\n=== SPPV-2.10 — §17.5 후속 3과제 실측 ===")

    # ── 과제 1: fast_score_v2 (drop / flip) — §16 이원 기준 ──────────────
    print("\n[과제 1] fast_score_v2 (rsi_signal 제거/반전) — §16 이원 기준")
    recent_cutoff_12m = (last_date - timedelta(days=365)).strftime("%Y-%m-%d")
    recent_samples_12m = [r for r in all_samples if r["trade_date"] >= recent_cutoff_12m]

    for sig in ["fast_score_v2_drop", "fast_score_v2_flip", "fast_score_orig_recomputed"]:
        report["task1_fast_score_v2"][sig] = {}
        print(f"  [{sig}]")
        for h in FORWARD_HORIZONS_FOCUS:
            primary = summarize_tier(recent_samples_12m, sig, h)
            supplementary = summarize_tier(all_samples, sig, h)
            by_regime = {
                regime: summarize_tier(all_samples, sig, h, regime)
                for regime in ["bullish_trend", "bearish_trend", "range_bound", "event_driven_unstable"]
            }
            report["task1_fast_score_v2"][sig][f"T+{h}"] = {
                "primary_recent_12m": primary,
                "supplementary_3y": supplementary,
                "supplementary_3y_by_regime": by_regime,
            }
            print(f"    T+{h}: 1차(12m) spread t_NW={primary['spread'].get('t_newey_west')}, "
                  f"2차(3년) spread t_NW={supplementary['spread'].get('t_newey_west')}")
            for regime, v in by_regime.items():
                nd = v["spread"].get("n_days", 0)
                tag = f"t_NW={v['spread'].get('t_newey_west')}" if nd >= MIN_REGIME_TRADING_DAYS else "표본부족"
                print(f"          {regime}(n={nd}): {tag}")

    # ── 과제 2: risk_adj_momentum_3m — 1차 창 12개월 vs 18개월 ───────────
    print("\n[과제 2] risk_adj_momentum_3m — 1차 창 12개월 vs 18개월 재검증")
    for label, days in RECENT_WINDOW_VARIANTS_DAYS.items():
        cutoff = (last_date - timedelta(days=days)).strftime("%Y-%m-%d")
        recent = [r for r in all_samples if r["trade_date"] >= cutoff]
        regime_counts = defaultdict(int)
        for r in recent:
            regime_counts[r["common_market_regime"]] += 1
        report["task2_risk_adj_momentum_3m_window_variants"][label] = {
            "window_days": days,
            "cutoff": cutoff,
            "n_samples": len(recent),
            "regime_distribution": dict(regime_counts),
            "by_horizon": {},
        }
        print(f"  [{label} 창, cutoff={cutoff}, 표본={len(recent)}건, 국면분포={dict(regime_counts)}]")
        for h in FORWARD_HORIZONS_FOCUS:
            entry = summarize_tier(recent, "risk_adj_momentum_3m", h)
            report["task2_risk_adj_momentum_3m_window_variants"][label]["by_horizon"][f"T+{h}"] = entry
            print(f"    T+{h}: spread t_NW={entry['spread'].get('t_newey_west')}, "
                  f"ic t_NW={entry['ic'].get('t_newey_west')}")

    # ── 과제 3: reversal_1m 하락장 조건부 오버레이 — 표본 내 안정성 ──────
    print("\n[과제 3] reversal_1m 하락장 조건부 오버레이 — 표본 내(전반부/후반부) 안정성")
    bearish_dates = sorted(d for d, r in regime_by_date.items() if r == "bearish_trend")
    mid = len(bearish_dates) // 2
    first_half_dates = set(bearish_dates[:mid])
    second_half_dates = set(bearish_dates[mid:])
    report["task3_reversal_1m_bearish_overlay"]["bearish_days_total"] = len(bearish_dates)
    report["task3_reversal_1m_bearish_overlay"]["bearish_date_range"] = (
        [bearish_dates[0], bearish_dates[-1]] if bearish_dates else []
    )
    report["task3_reversal_1m_bearish_overlay"]["first_half_range"] = (
        [min(first_half_dates), max(first_half_dates)] if first_half_dates else []
    )
    report["task3_reversal_1m_bearish_overlay"]["second_half_range"] = (
        [min(second_half_dates), max(second_half_dates)] if second_half_dates else []
    )
    print(f"  하락장 거래일 총 {len(bearish_dates)}일, "
          f"전반부 {len(first_half_dates)}일 / 후반부 {len(second_half_dates)}일")

    bearish_all = [r for r in all_samples if r["common_market_regime"] == "bearish_trend"]
    bearish_first = [r for r in bearish_all if r["trade_date"] in first_half_dates]
    bearish_second = [r for r in bearish_all if r["trade_date"] in second_half_dates]

    report["task3_reversal_1m_bearish_overlay"]["by_horizon"] = {}
    for h in FORWARD_HORIZONS_FOCUS:
        full = summarize_tier(bearish_all, "reversal_1m", h)
        first = summarize_tier(bearish_first, "reversal_1m", h)
        second = summarize_tier(bearish_second, "reversal_1m", h)
        report["task3_reversal_1m_bearish_overlay"]["by_horizon"][f"T+{h}"] = {
            "full_bearish": full, "first_half": first, "second_half": second,
        }
        print(f"    T+{h}: 전체(n={full['spread'].get('n_days')}) spread t_NW={full['spread'].get('t_newey_west')}, "
              f"전반부(n={first['spread'].get('n_days')}) t_NW={first['spread'].get('t_newey_west')}, "
              f"후반부(n={second['spread'].get('n_days')}) t_NW={second['spread'].get('t_newey_west')}")

    out_path = "logs/signal_ic_sppv2_10_followup_2026-07-14.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
