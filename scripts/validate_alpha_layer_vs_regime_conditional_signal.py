#!/usr/bin/env python3
"""SPPV-3 사전 실험 — 현행 entry_score alpha layer vs regime_conditional_signal
직접 비교 (read-only).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §3(entry_score
통합 방안), §11.8(다음 단계 3 — 무게중심을 alpha layer 통합 검증으로
이동) 참고.

§10~§11(SPPV-2.20/2.21)은 "국면 정의(종목별 vs 시장 공통) 자체를
바꾸는 것"을 검증했고, 결론은 "시장 공통 정의는 종목별 정의의
부분집합일 뿐 새 기회를 만들지 못한다"(Watch, No-Go에 근접)였다. 이는
**차단(risk 축) 정의의 문제**였지, **alpha(누구를 위로 올릴지) 축의
문제**가 아니었다. 이번 스크립트는 무게중심을 옮겨, `entry_score`의
**alpha layer 자체**(현재 `overall_score`/`fast_score`/`slow_score`를
0.45/0.20/0.15로 가중합)와 `regime_conditional_signal`(§2, 국면별로
`risk_adj_momentum_3m`/`reversal_1m`을 전환)을 **같은 3년 rolling
표본에서 직접** cross-sectional 순위화 성능으로 비교한다.

핵심 수학적 사실(코드 확인, `deterministic_trigger_engine.py:1252-1255`):
`_normalize_signed_score(x) = clamp((x+1)/2)`는 각 성분에 대해 동일한
선형 변환(기울기 0.5, 절편 0.5)이므로,

    entry_score의 alpha 항 = 0.45·norm(overall) + 0.20·norm(fast) + 0.15·norm(slow)
                             = 0.4 + 0.5·(0.45·overall + 0.20·fast + 0.15·slow)

즉 **순위(ranking)만 놓고 보면** `0.45·overall + 0.20·fast + 0.15·slow`
(이하 `current_alpha_composite`)와 완전히 동일한 순서를 만든다 — 새
근사가 아니라 코드 자체의 수학적 귀결이다. 이 스크립트는 그 원 가중치
그대로 `current_alpha_composite`를 계산해 `regime_conditional_signal`
과 직접 맞대결시킨다.

방법(§16 이원 검증 도구 그대로 재사용, 신규 통계 기법 없음):
  1. 3년 rolling 표본(87종목, 캐시 재사용)에 대해 거래일마다
     `current_alpha_composite`와 `regime_conditional_signal`을 함께
     계산한다.
  2. 각 신호로 그날 cross-sectional quintile spread(top20%-bottom20%
     forward return)와 Spearman IC를 계산, 전체 기간 평균 + Newey-West
     t-stat + 양수 비율을 비교한다.
  3. 1차(최근 12개월)/2차(3년) 이원 기준을 그대로 적용한다.

DB write / 주문 경로 / 실시간 구독 없음. 실제 KIS 호출 여부는 가정하지
않고 로그의 `HTTP Request:` 카운트로 그대로 보고한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_alpha_layer_vs_regime_conditional_signal")

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

_ROUND_TRIP_COST_BPS = 30.0
RECENT_WINDOW_CALENDAR_DAYS = 365

# entry_score alpha layer 원 가중치(deterministic_trigger_engine.py:1128-1130, 그대로 인용)
_ALPHA_W_OVERALL = 0.45
_ALPHA_W_FAST = 0.20
_ALPHA_W_SLOW = 0.15


def _collect_symbol_rows(symbol: str, bars: list, market_common_regime_by_date: dict[str, str]) -> list[dict]:
    from agent_trading.services.signal_backbone import build_signal_snapshot

    rows: list[dict] = []
    last_t = len(bars) - 1 - max(FORWARD_HORIZONS_FOCUS)
    if last_t < _MIN_LOOKBACK - 1:
        return rows

    for t in range(_MIN_LOOKBACK - 1, last_t + 1):
        window = bars[: t + 1]
        try:
            features, card = build_signal_snapshot(symbol, window)
        except Exception:
            continue

        overall = float(card.overall_score)
        fast = float(card.fast_score)
        slow = float(card.slow_score)

        current_alpha_composite = (
            _ALPHA_W_OVERALL * overall + _ALPHA_W_FAST * fast + _ALPHA_W_SLOW * slow
        )

        trade_date = bars[t].timestamp.strftime("%Y-%m-%d")
        market_common_label = market_common_regime_by_date.get(trade_date)

        ret3m = features.return_3m_pct
        ret1m = features.return_1m_pct
        vol = features.volatility_20d_pct
        risk_adj_momentum_3m = (ret3m / max(vol, 1.0)) if (ret3m is not None and vol is not None) else None
        reversal_1m = (-ret1m) if ret1m is not None else None

        regime_conditional_signal = None
        if market_common_label in ("bullish_trend", "range_bound"):
            regime_conditional_signal = risk_adj_momentum_3m
        elif market_common_label == "bearish_trend":
            regime_conditional_signal = reversal_1m
        # event_driven_unstable/None → 신호 미산출(§2 표, 근거 없이 채우지 않음)

        base_close = bars[t].close_price
        row: dict = {
            "symbol": symbol,
            "trade_date": trade_date,
            "market_common_regime": market_common_label,
            "current_alpha_composite": current_alpha_composite,
            "regime_conditional_signal": regime_conditional_signal,
        }
        for h in FORWARD_HORIZONS_FOCUS:
            fwd_close = bars[t + h].close_price
            raw_ret = (fwd_close / base_close) - 1.0
            row[f"fwd_{h}"] = raw_ret
            row[f"fwd_{h}_net"] = raw_ret - (_ROUND_TRIP_COST_BPS / 10_000.0)

        rows.append(row)
    return rows


def summarize_tier(rows: list[dict], sig: str, h: int) -> dict:
    ic = _cross_sectional_ic_by_date(rows, sig, h, f"fwd_{h}")
    spread = _quintile_spread_series(rows, sig, f"fwd_{h}_net")
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
    market_common_regime_by_date, _ = _build_benchmark_daily_series(bench_bars)
    if not market_common_regime_by_date:
        raise SystemExit("시장 공통 국면 계산 실패")

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})
    all_rows: list[dict] = []
    fetch_failures: list[str] = []
    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        if len(bars) < _MIN_LOOKBACK + max(FORWARD_HORIZONS_FOCUS) + 5:
            fetch_failures.append(symbol)
            continue
        rows = _collect_symbol_rows(symbol, bars, market_common_regime_by_date)
        all_rows.extend(rows)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_rows))

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_rows), len(fetch_failures))

    last_date = max(datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in all_rows)
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    recent_rows = [r for r in all_rows if r["trade_date"] >= cutoff]

    signal_rows = [r for r in all_rows if r["regime_conditional_signal"] is not None]
    signal_rows_recent = [r for r in recent_rows if r["regime_conditional_signal"] is not None]

    print("\n=== 현행 entry_score alpha layer vs regime_conditional_signal 직접 비교 ===")
    print(f"전체 3년 표본: {len(all_rows)}건, 최근 12개월(cutoff={cutoff}) 표본: {len(recent_rows)}건")
    print(f"regime_conditional_signal 산출 가능(판정불가 제외) 3년 표본: {len(signal_rows)}건, "
          f"최근 12개월: {len(signal_rows_recent)}건")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_rows),
        "total_rolling_samples_recent_12m": len(recent_rows),
        "recent_window_cutoff": cutoff,
        "signal_evaluable_samples_3y": len(signal_rows),
        "signal_evaluable_samples_recent_12m": len(signal_rows_recent),
        "supplementary_3y": {},
        "primary_recent_12m": {},
    }

    for window_label, key, rows_all, rows_signal in [
        ("supplementary_3y", "supplementary_3y", all_rows, signal_rows),
        ("primary_recent_12m", "primary_recent_12m", recent_rows, signal_rows_recent),
    ]:
        print(f"\n--- {window_label} ---")
        for h in FORWARD_HORIZONS_FOCUS:
            print(f"  [T+{h}]")
            current_summary = summarize_tier(rows_all, "current_alpha_composite", h)
            # regime_conditional_signal은 판정 가능한 표본에서만 비교(공정 비교를 위해
            # current_alpha_composite도 같은 부분집합으로 한 번 더 계산)
            current_on_signal_subset = summarize_tier(rows_signal, "current_alpha_composite", h)
            signal_summary = summarize_tier(rows_signal, "regime_conditional_signal", h)

            print(f"    current_alpha_composite(전체 표본): spread={current_summary['spread']}")
            print(f"    current_alpha_composite(신호 산출 가능 부분집합, 공정비교용): "
                  f"spread={current_on_signal_subset['spread']}")
            print(f"    regime_conditional_signal: spread={signal_summary['spread']}")

            report[key][f"T+{h}"] = {
                "current_alpha_composite_full_sample": current_summary,
                "current_alpha_composite_signal_evaluable_subset": current_on_signal_subset,
                "regime_conditional_signal": signal_summary,
            }

    out_path = "logs/signal_ic_alpha_layer_vs_regime_conditional_signal_2026-07-15.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
