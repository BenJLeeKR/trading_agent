#!/usr/bin/env python3
"""SPPV — 신호 feature 재설계 검토 (SPPV-2.9, read-only).

``plans/[DESIGN] signal_predictive_power_validation.md`` §14.5/§17 참고.

배경: §14(SPPV-2.7)는 `overall_score`/`slow_score`/`fast_score` 합성
점수가 3년 확장 검증에서 안정적 종목 선택 알파를 보여주지 못했고,
`fast_score`는 하락장에서 통계적으로 유의하게 역방향이었다고 결론지었다.
이 스크립트는 그 다음 단계로 "가중치를 조정"하는 대신 **`fast_score`/
`slow_score`를 구성하는 개별 raw sub-component를 그대로 분해**해 어떤
조각이 예측력을 갖는지(또는 아무도 갖지 못하는지) 직접 검증한다:

기존 6개 sub-component(운영 코드 `signal_backbone._score_features()`가
그대로 계산하는 값, 새 로직 아님):
  slow_momentum, slow_trend        (slow_score 구성)
  fast_trend, volume_confirmation, rsi_signal, volatility_penalty
                                    (fast_score 구성)

신규 후보 feature 2개(raw TechnicalFeatureSnapshot 값으로부터 계산,
운영 가중치 체계와 무관하게 독립적으로 검증):
  risk_adj_momentum_3m = return_3m_pct / max(volatility_20d_pct, 1.0)
    — "변동성 대비 모멘텀"(quality momentum) 가설.
  reversal_1m = -return_1m_pct
    — 단기 역추세(mean reversion) 가설. `fast_score`가 하락장에서 유의하게
      역방향이었다는 §14 관측이 "단기 역추세가 오히려 진짜 신호일 수
      있다"는 가설을 세울 근거가 된다.

방법론은 §16(SPPV-2.8)에서 확정한 이원 기준을 그대로 적용한다:
  1차(primary) = 최근 12개월, 2차(supplementary, 필수 국면 게이트) = 3년
  (시장 공통 국면, KODEX 200 벤치마크). 3년 캐시를 재사용해 **신규 KIS
  호출 없이** 검증한다 — 새 로직을 새로 설계하지 않고 기존 함수
  (`build_signal_snapshot`, `classify_market_regime`, SPPV-2.7/2.8의
  cross-sectional IC/quintile/Newey-West 함수)를 그대로 재사용한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_signal_predictive_power_v6_feature_redesign")

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

# 기존 sub-component(운영 코드 component_scores 그대로) + 신규 후보 feature
EXISTING_SUB_COMPONENTS = [
    "slow_momentum", "slow_trend",
    "fast_trend", "volume_confirmation", "rsi_signal", "volatility_penalty",
]
NEW_CANDIDATE_FEATURES = ["risk_adj_momentum_3m", "reversal_1m"]
ALL_CANDIDATES = EXISTING_SUB_COMPONENTS + NEW_CANDIDATE_FEATURES

RECENT_WINDOW_CALENDAR_DAYS = 365
MIN_REGIME_TRADING_DAYS = 30

_ROUND_TRIP_COST_BPS = 30.0


def _collect_feature_samples(symbol: str, bars: list) -> list[dict]:
    """운영 코드(build_signal_snapshot)를 그대로 재사용해 sub-component와
    신규 후보 feature를 함께 rolling 재계산한다."""
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

        for name in EXISTING_SUB_COMPONENTS:
            if name in card.component_scores:
                row[name] = float(card.component_scores[name])

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
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")

    common_regime_counts_3y: dict[str, int] = defaultdict(int)
    common_regime_counts_recent: dict[str, int] = defaultdict(int)
    for d, r in regime_by_date.items():
        common_regime_counts_3y[r] += 1
        if d >= cutoff:
            common_regime_counts_recent[r] += 1
    logger.info("3년 국면 분포: %s", dict(common_regime_counts_3y))
    logger.info("최근 12개월(cutoff=%s) 국면 분포: %s", cutoff, dict(common_regime_counts_recent))

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

    recent_samples = [r for r in all_samples if r["trade_date"] >= cutoff]
    logger.info(
        "전체 표본 %d건(3년), 최근 12개월 표본 %d건, 실패 %d종목",
        len(all_samples), len(recent_samples), len(fetch_failures),
    )

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_samples),
        "total_rolling_samples_recent_12m": len(recent_samples),
        "recent_window_cutoff": cutoff,
        "common_market_regime_distribution_3y": dict(common_regime_counts_3y),
        "common_market_regime_distribution_recent_12m": dict(common_regime_counts_recent),
        "by_candidate": {},
    }

    print("\n=== SPPV-2.9 신호 feature 재설계 검토 — sub-component 분해 + 신규 후보 ===")
    print(f"3년 국면 분포: {dict(common_regime_counts_3y)}")
    print(f"최근 12개월 국면 분포: {dict(common_regime_counts_recent)}")

    def summarize_tier(samples: list[dict], sig: str, h: int, regime_filter: str | None = None) -> dict:
        ic = _cross_sectional_ic_by_date(samples, sig, h, f"fwd_{h}", common_regime_filter=regime_filter)
        spread = _quintile_spread_series(samples, sig, f"fwd_{h}_net", common_regime_filter=regime_filter)
        return {
            "ic": _summarize_series(ic, h, is_pct=False),
            "spread": _summarize_series(spread, h),
        }

    for sig in ALL_CANDIDATES:
        report["by_candidate"][sig] = {}
        print(f"\n[{sig}]")
        for h in FORWARD_HORIZONS_FOCUS:
            entry: dict = {}
            entry["primary_recent_12m_pooled"] = summarize_tier(recent_samples, sig, h)
            entry["supplementary_3y_pooled"] = summarize_tier(all_samples, sig, h)
            entry["supplementary_3y_by_regime"] = {}
            for regime in ["bullish_trend", "bearish_trend", "range_bound", "event_driven_unstable"]:
                entry["supplementary_3y_by_regime"][regime] = summarize_tier(all_samples, sig, h, regime)
            report["by_candidate"][sig][f"T+{h}"] = entry

            p = entry["primary_recent_12m_pooled"]
            s = entry["supplementary_3y_pooled"]
            print(f"  T+{h}: 1차(최근12m) spread t_NW={p['spread'].get('t_newey_west')}, "
                  f"2차(3년) spread t_NW={s['spread'].get('t_newey_west')}")
            for regime, v in entry["supplementary_3y_by_regime"].items():
                nd = v["spread"].get("n_days", 0)
                if nd >= MIN_REGIME_TRADING_DAYS:
                    print(f"        {regime}(n={nd}): spread t_NW={v['spread'].get('t_newey_west')}")
                else:
                    print(f"        {regime}(n={nd}): 표본 부족 — 판정 제외")

    out_path = "logs/signal_ic_sppv2_9_feature_redesign_2026-07-14.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
