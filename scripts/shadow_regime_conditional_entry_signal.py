#!/usr/bin/env python3
"""국면 분기형 진입 신호 shadow 계산기 (read-only, Phase 1 스냅샷).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §2/§4/§5 참고.

`plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_direction.md`
§4의 판정("국면 분기형 entry 설계로 전환")과, SPPV-2.9~2.14(§17~§20)
에서 검증된 `regime_switch_v1` 정의를 그대로 가져와 **"오늘(캐시 기준
최신 거래일) core universe 각 종목에 이 신호가 어떤 값을 내는가"**를
1회 계산·기록한다.

정의(신규 로직 없음, 기존 검증된 함수·상수 그대로 재사용):
  common_market_regime(date) — KODEX 200(069500) 자기 자신의 rolling
    기술적 상태를 `classify_market_regime()`에 입력해 판정(SPPV-2.6
    이후 확립).
  regime_conditional_signal(symbol, date) =
    risk_adj_momentum_3m  if 국면 in {bullish_trend, range_bound}
    reversal_1m           if 국면 == bearish_trend
    None(미산출)           if 국면 == event_driven_unstable 또는 판정 불가

DB write / 주문 경로 / 실시간 구독 없음. 3년 캐시를 재사용하며, 캐시가
없는 신규 심볼만 KIS 조회한다(rate budget 보호를 위해 종목 간 sleep 유지).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shadow_regime_conditional_entry_signal")

_KST = timezone(timedelta(hours=9))

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    _fetch_extended_bars,
)


def _latest_regime_and_signal(symbol: str, bars: list, benchmark_regime_by_date: dict[str, str]) -> dict | None:
    """가장 최근 봉 하루에 대해서만 regime_conditional_signal을 계산한다."""
    from agent_trading.services.signal_backbone import build_signal_snapshot

    if len(bars) < _MIN_LOOKBACK:
        return None

    t = len(bars) - 1
    window = bars[: t + 1]
    try:
        features, _card = build_signal_snapshot(symbol, window)
    except Exception:
        return None

    trade_date = bars[t].timestamp.strftime("%Y-%m-%d")
    regime = benchmark_regime_by_date.get(trade_date, "unknown")

    ret3m = features.return_3m_pct
    ret1m = features.return_1m_pct
    vol = features.volatility_20d_pct

    risk_adj_momentum_3m = (ret3m / max(vol, 1.0)) if (ret3m is not None and vol is not None) else None
    reversal_1m = (-ret1m) if ret1m is not None else None

    if regime in ("bullish_trend", "range_bound"):
        signal_value = risk_adj_momentum_3m
        signal_source = "risk_adj_momentum_3m"
    elif regime == "bearish_trend":
        signal_value = reversal_1m
        signal_source = "reversal_1m"
    else:
        signal_value = None
        signal_source = "none(판정불가)"

    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "common_market_regime": regime,
        "signal_source": signal_source,
        "regime_conditional_signal": signal_value,
        "risk_adj_momentum_3m_raw": risk_adj_momentum_3m,
        "reversal_1m_raw": reversal_1m,
    }


def _build_benchmark_regime_by_date(bench_bars: list) -> dict[str, str]:
    """벤치마크 자기 자신의 rolling 국면 라벨(전 구간, forward return 불필요)."""
    from types import SimpleNamespace

    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot

    regime_by_date: dict[str, str] = {}
    for t in range(_MIN_LOOKBACK - 1, len(bench_bars)):
        window = bench_bars[: t + 1]
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
        trade_date = bench_bars[t].timestamp.strftime("%Y-%m-%d")
        regime_by_date[trade_date] = assessment.regime_label if assessment else "unknown"
    return regime_by_date


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")

    bench_bars = await _fetch_extended_bars(client, BENCHMARK_SYMBOL)
    benchmark_regime_by_date = _build_benchmark_regime_by_date(bench_bars)
    if not benchmark_regime_by_date:
        raise SystemExit("벤치마크 국면 라벨 계산 실패")

    latest_bench_date = max(benchmark_regime_by_date)
    latest_regime = benchmark_regime_by_date[latest_bench_date]
    logger.info("기준일 %s, 시장 공통 국면=%s", latest_bench_date, latest_regime)

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})

    rows: list[dict] = []
    fetch_failures: list[str] = []
    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        row = _latest_regime_and_signal(symbol, bars, benchmark_regime_by_date)
        if row is None:
            fetch_failures.append(symbol)
            continue
        rows.append(row)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 처리 완료", idx, len(symbols))

    valid_signal_rows = [r for r in rows if r["regime_conditional_signal"] is not None]

    report = {
        "as_of": datetime.now(_KST).isoformat(),
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "latest_benchmark_trade_date": latest_bench_date,
        "latest_common_market_regime": latest_regime,
        "symbol_count_total": len(symbols),
        "symbol_count_with_signal": len(valid_signal_rows),
        "fetch_failures": fetch_failures,
        "rows": rows,
    }

    print("\n=== 국면 분기형 진입 신호 shadow 스냅샷(Phase 1) ===")
    print(f"기준일: {latest_bench_date}, 시장 공통 국면: {latest_regime}")
    print(f"신호 산출 종목: {len(valid_signal_rows)}/{len(symbols)} (판정불가/실패 {len(symbols) - len(valid_signal_rows)}종목)")
    if valid_signal_rows:
        top5 = sorted(valid_signal_rows, key=lambda r: r["regime_conditional_signal"], reverse=True)[:5]
        bottom5 = sorted(valid_signal_rows, key=lambda r: r["regime_conditional_signal"])[:5]
        print("상위 5종목(신호값 기준):")
        for r in top5:
            print(f"  {r['symbol']}: {r['regime_conditional_signal']:.4f} ({r['signal_source']})")
        print("하위 5종목(신호값 기준):")
        for r in bottom5:
            print(f"  {r['symbol']}: {r['regime_conditional_signal']:.4f} ({r['signal_source']})")

    out_path = "logs/shadow_regime_conditional_entry_signal_2026-07-15.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
