#!/usr/bin/env python3
"""SPPV-2.5 — quintile spread 정체 진단: 시장 베타 착시 vs 잔여 알파 (read-only).

``plans/[DESIGN] signal_predictive_power_validation.md`` §9.7(SPPV-2.5) 참고.

SPPV-2에서 발견한 `overall_score` quintile spread(T+20 +3.88%p)가 실제
알파인지, 아니면 표본 기간에 상승장(bullish_trend)이 절반을 차지해 생긴
시장 베타 착시인지를 두 가지 진단으로 가른다.

1. **spread 자체의 통계적 유의성**: SPPV-2는 IC(순위상관)의 유의성만
   Newey-West로 검정했다. 이번엔 "그날의 상위 20% 평균 수익률 - 하위 20%
   평균 수익률" 시계열 자체에 동일한 Newey-West 보정을 적용해 spread가
   0과 통계적으로 다른지 검정한다.
2. **국면 내부(within-regime) 분해**: bullish_trend/bearish_trend/
   range_bound 각각의 내부에서만 상위/하위 quintile을 다시 나눠 spread가
   유지되는지 확인한다. 전체 표본 spread는 유지되는데 국면 내부에서
   사라지면, 이는 "그날의 신호가 종목을 잘 골랐다"가 아니라 "상승장에
   전체적으로 몰려 있었다"는 베타 착시라는 뜻이다. 반대로 국면 내부에서도
   spread가 유지되면 국면과 무관한 잔여 알파일 가능성이 있다.

같은 KIS 일봉을 반복 조회하지 않도록 SPPV-2가 만든 로컬 캐시
(`logs/_bars_cache_core88_2026-07-14/`)를 그대로 재사용한다(있으면 캐시
히트, 없으면 자동으로 새로 받아 캐시에 저장 — `_fetch_year_bars`의 기존
동작). 운영 코드(`build_signal_snapshot`, `classify_market_regime`)를 그대로
재사용 — 검증용 로직을 새로 만들지 않는다. DB write/주문 경로/실시간 구독
없음.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import sqrt

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_signal_predictive_power_v2_5")

_KST = timezone(timedelta(hours=9))

# SPPV-2 모듈 재사용 (신규 로직 재작성 금지 원칙)
import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v2 import (  # noqa: E402
    _BARS_CACHE_DIR,
    _collect_symbol_samples,
    _fetch_year_bars,
    _mean,
    _newey_west_se_of_mean,
    _stdev,
)

DIRECT_SIGNALS = ["slow_score", "fast_score", "overall_score"]
FORWARD_HORIZONS_FOCUS = [5, 20]  # SPPV-2에서 spread가 관측된 horizon 위주로 검정


def _daily_quintile_spread_series(
    all_samples: list[dict], signal: str, horizon: int, regime_filter: str | None = None
) -> list[float]:
    """거래일별 (상위 20% 평균 net return - 하위 20% 평균 net return) 시계열.

    ``regime_filter``가 주어지면 그 국면(regime_label)에 속하는 표본만으로
    그날의 quintile을 다시 나눈다(국면 내부 분해).
    """
    by_date: dict[str, list[dict]] = defaultdict(list)
    for row in all_samples:
        if regime_filter is not None and row.get("regime_label") != regime_filter:
            continue
        if signal in row and f"fwd_{horizon}_net" in row:
            by_date[row["trade_date"]].append(row)

    spreads: list[float] = []
    for rows in by_date.values():
        if len(rows) < 5:
            continue
        ordered = sorted(rows, key=lambda r: r[signal])
        q = max(1, len(ordered) // 5)
        bottom = ordered[:q]
        top = ordered[-q:]
        top_mean = _mean([r[f"fwd_{horizon}_net"] for r in top])
        bottom_mean = _mean([r[f"fwd_{horizon}_net"] for r in bottom])
        if top_mean is not None and bottom_mean is not None:
            spreads.append(top_mean - bottom_mean)
    return spreads


def _summarize_spread_series(spreads: list[float], horizon: int) -> dict:
    n = len(spreads)
    if n < 5:
        return {"n_days": n, "note": "표본부족(<5일)"}
    mean_spread = _mean(spreads)
    std_spread = _stdev(spreads)
    t_naive = (mean_spread / (std_spread / sqrt(n))) if std_spread else None
    nw_se = _newey_west_se_of_mean(spreads, lag=max(horizon - 1, 1))
    t_nw = (mean_spread / nw_se) if nw_se else None
    pct_positive = sum(1 for x in spreads if x > 0) / n
    return {
        "n_days": n,
        "mean_spread_pct": round(mean_spread * 100, 3),
        "t_naive": round(t_naive, 2) if t_naive else None,
        "t_newey_west": round(t_nw, 2) if t_nw else None,
        "pct_days_positive_spread": round(pct_positive, 3),
    }


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")
    logger.info("KIS client env=%s (캐시 디렉터리=%s)", getattr(client, "env", None), _BARS_CACHE_DIR)

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS)
    all_samples: list[dict] = []
    fetch_failures: list[str] = []

    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_year_bars(client, symbol, cache_dir=_BARS_CACHE_DIR)
        if len(bars) < 61 + 20 + 5:
            fetch_failures.append(symbol)
            continue
        samples = _collect_symbol_samples(symbol, bars)
        all_samples.extend(samples)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_samples))

    logger.info("전체 rolling 표본: %d건 (종목 %d개, 실패 %d개)",
                len(all_samples), len(symbols) - len(fetch_failures), len(fetch_failures))

    # 국면 분포 재확인 (SPPV-2와 동일 표본인지 대조)
    regime_counts: dict[str, int] = defaultdict(int)
    for row in all_samples:
        regime_counts[row.get("regime_label", "unknown")] += 1
    logger.info("국면 분포: %s", dict(regime_counts))

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "total_rolling_samples": len(all_samples),
        "regime_counts": dict(regime_counts),
        "by_signal": {},
    }

    print("\n=== SPPV-2.5 quintile spread 정체 진단 ===")
    print(f"표본: {len(all_samples)}건, 국면 분포: {dict(regime_counts)}")

    for sig in DIRECT_SIGNALS:
        report["by_signal"][sig] = {}
        print(f"\n[{sig}]")
        for h in FORWARD_HORIZONS_FOCUS:
            # 1) 전체 표본 spread 유의성
            overall_spreads = _daily_quintile_spread_series(all_samples, sig, h)
            overall_summary = _summarize_spread_series(overall_spreads, h)
            report["by_signal"][sig][f"T+{h}_overall"] = overall_summary
            print(f"  T+{h} 전체: {overall_summary}")

            # 2) 국면 내부 분해
            report["by_signal"][sig][f"T+{h}_by_regime"] = {}
            for regime in ["bullish_trend", "bearish_trend", "range_bound", "event_driven_unstable"]:
                regime_spreads = _daily_quintile_spread_series(all_samples, sig, h, regime_filter=regime)
                regime_summary = _summarize_spread_series(regime_spreads, h)
                report["by_signal"][sig][f"T+{h}_by_regime"][regime] = regime_summary
                print(f"    {regime}: {regime_summary}")

    out_path = "logs/signal_ic_sppv2_5_regime_decomposition_2026-07-14.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
