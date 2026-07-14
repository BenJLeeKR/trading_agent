#!/usr/bin/env python3
"""SPPV-2.11 — §18.6 후속: fast_score 전면 분해 + 창 경계 민감도 + shadow 후보 (read-only).

``plans/[DESIGN] signal_predictive_power_validation.md`` §18.6 참고.

§18(SPPV-2.10)은 `rsi_signal` 제거/반전만으로는 `fast_score`의 하락장
역전(T+5 t_NW=-2.79)이 해소되지 않음을 확인했다(-2.41/-2.32로 소폭
개선에 그침). 이 스크립트는 그 다음 단계로 세 과제를 함께 수행한다 —
새 검증 방법론은 만들지 않고 §16 이원 기준·기존 함수를 그대로 재사용한다.

1. **`fast_score` leave-one-out 전면 분해**: `rsi_signal` 제거(§18에서
   이미 확인)에 더해, `fast_trend`/`volume_confirmation`/
   `volatility_penalty`도 각각 하나씩 제거한 변형(나머지 3개 가중치
   재정규화)을 만들어 어떤 성분을 빼야 하락장 역전이 실제로 해소되는지
   확인한다. 넷 다 개선되지 않으면 "단일 성분 문제가 아니라 조합 자체의
   구조적 문제"라는 §18 해석이 더 강하게 뒷받침된다.
2. **`risk_adj_momentum_3m` 창 경계 민감도**: 1차(primary) 창을
   12/15/18/21개월로 바꿔가며 T+5/T+20 spread를 비교해, §18의 18개월
   t_NW=2.03이 우연한 경계 효과인지 안정적 추세인지 판별한다.
3. **국면 전환형 shadow 후보 제안·검증**: 지금까지 가장 방향성 있었던
   두 신호 — 상승/횡보 국면에는 `risk_adj_momentum_3m`, 하락 국면에는
   `reversal_1m` — 를 국면에 따라 전환해 쓰는 복합 신호
   (`regime_switch_v1`)를 shadow로 정의하고, 같은 §16 기준으로 검증한다.

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
logger = logging.getLogger("validate_signal_predictive_power_v8_fast_score_teardown")

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

# 운영 fast_score 원 가중치(signal_backbone._score_features, 그대로 인용)
_W = {"fast_trend": 0.3, "volume_confirmation": 0.2, "rsi_signal": 0.15, "volatility_penalty": 0.35}
LEAVE_ONE_OUT_VARIANTS = ["drop_fast_trend", "drop_volume_confirmation", "drop_rsi_signal", "drop_volatility_penalty"]

WINDOW_VARIANTS_DAYS = {"12m": 365, "15m": 456, "18m": 548, "21m": 639}


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

        cs = card.component_scores
        comp = {
            "fast_trend": cs.get("fast_trend"),
            "volume_confirmation": cs.get("volume_confirmation"),
            "rsi_signal": cs.get("rsi_signal"),
            "volatility_penalty": cs.get("volatility_penalty"),
        }
        row: dict = {"symbol": symbol, "trade_date": bars[t].timestamp.strftime("%Y-%m-%d")}

        if None not in comp.values():
            for drop_key in ("fast_trend", "volume_confirmation", "rsi_signal", "volatility_penalty"):
                remaining = {k: v for k, v in _W.items() if k != drop_key}
                w_sum = sum(remaining.values())
                value = sum(remaining[k] * comp[k] for k in remaining) / w_sum
                row[f"drop_{drop_key}"] = value
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

    # 국면 전환형 shadow 후보: bearish_trend 날은 reversal_1m, 그 외는 risk_adj_momentum_3m
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
        "task1_fast_score_leave_one_out": {},
        "task2_risk_adj_momentum_3m_window_sensitivity": {},
        "task3_regime_switch_shadow_candidate": {},
    }

    print("\n=== SPPV-2.11 — §18.6 후속: fast_score 전면 분해 + 창 경계 민감도 + shadow 후보 ===")

    # ── 과제 1: fast_score leave-one-out 4종 ─────────────────────────────
    print("\n[과제 1] fast_score leave-one-out 4종 — 어떤 성분을 빼야 하락장 역전이 해소되는가")
    for sig in [f"drop_{k}" for k in ("fast_trend", "volume_confirmation", "rsi_signal", "volatility_penalty")] + [
        "fast_score_orig_recomputed"
    ]:
        report["task1_fast_score_leave_one_out"][sig] = {}
        print(f"  [{sig}]")
        for h in FORWARD_HORIZONS_FOCUS:
            primary = summarize_tier(recent_samples_12m, sig, h)
            supplementary = summarize_tier(all_samples, sig, h)
            by_regime = {
                regime: summarize_tier(all_samples, sig, h, regime)
                for regime in ["bullish_trend", "bearish_trend", "range_bound", "event_driven_unstable"]
            }
            report["task1_fast_score_leave_one_out"][sig][f"T+{h}"] = {
                "primary_recent_12m": primary,
                "supplementary_3y": supplementary,
                "supplementary_3y_by_regime": by_regime,
            }
            print(f"    T+{h}: 1차(12m) spread t_NW={primary['spread'].get('t_newey_west')}, "
                  f"2차(3년) spread t_NW={supplementary['spread'].get('t_newey_west')}, "
                  f"bearish_trend t_NW={by_regime['bearish_trend']['spread'].get('t_newey_west')}")

    # ── 과제 2: risk_adj_momentum_3m 창 경계 민감도 12/15/18/21개월 ──────
    print("\n[과제 2] risk_adj_momentum_3m — 1차 창 12/15/18/21개월 민감도")
    for label, days in WINDOW_VARIANTS_DAYS.items():
        cutoff = (last_date - timedelta(days=days)).strftime("%Y-%m-%d")
        recent = [r for r in all_samples if r["trade_date"] >= cutoff]
        regime_counts = defaultdict(int)
        for r in recent:
            regime_counts[r["common_market_regime"]] += 1
        entry: dict = {"window_days": days, "cutoff": cutoff, "n_samples": len(recent),
                       "regime_distribution": dict(regime_counts), "by_horizon": {}}
        print(f"  [{label} 창, cutoff={cutoff}, 표본={len(recent)}건]")
        for h in FORWARD_HORIZONS_FOCUS:
            s = summarize_tier(recent, "risk_adj_momentum_3m", h)
            entry["by_horizon"][f"T+{h}"] = s
            print(f"    T+{h}: spread t_NW={s['spread'].get('t_newey_west')}, ic t_NW={s['ic'].get('t_newey_west')}")
        report["task2_risk_adj_momentum_3m_window_sensitivity"][label] = entry

    # ── 과제 3: 국면 전환형 shadow 후보 regime_switch_v1 — §16 기준 검증 ──
    print("\n[과제 3] regime_switch_v1(비하락장=risk_adj_momentum_3m, 하락장=reversal_1m) — §16 이원 기준")
    for h in FORWARD_HORIZONS_FOCUS:
        primary = summarize_tier(recent_samples_12m, "regime_switch_v1", h)
        supplementary = summarize_tier(all_samples, "regime_switch_v1", h)
        by_regime = {
            regime: summarize_tier(all_samples, "regime_switch_v1", h, regime)
            for regime in ["bullish_trend", "bearish_trend", "range_bound", "event_driven_unstable"]
        }
        report["task3_regime_switch_shadow_candidate"][f"T+{h}"] = {
            "primary_recent_12m": primary,
            "supplementary_3y": supplementary,
            "supplementary_3y_by_regime": by_regime,
        }
        print(f"  T+{h}: 1차(12m) spread t_NW={primary['spread'].get('t_newey_west')}, "
              f"2차(3년) spread t_NW={supplementary['spread'].get('t_newey_west')}")
        for regime, v in by_regime.items():
            nd = v["spread"].get("n_days", 0)
            tag = f"t_NW={v['spread'].get('t_newey_west')}" if nd >= MIN_REGIME_TRADING_DAYS else "표본부족"
            print(f"        {regime}(n={nd}): {tag}")

    out_path = "logs/signal_ic_sppv2_11_fast_score_teardown_2026-07-14.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
