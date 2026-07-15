#!/usr/bin/env python3
"""SPPV-3 사전 실험 — regime_conditional_signal 상위군 vs 기존 차단 축
결합 효과 (read-only).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §12.7(다음
단계), §8(중복 penalty ablation), §3(entry_score 통합 방안) 참고.

§12(SPPV-2.22)는 `regime_conditional_signal`이 현행 alpha layer보다
2차(3년) 창에서 유의하게 나은 종목 선별력을 보인다는 것을 확인했다
(Conditional Go). 그러나 alpha만 바꾸고 기존 차단 축(§8에서 정량화한
세 축 — entry_score regime penalty, eligibility regime block,
eligibility negative floor)을 그대로 두면, 새 alpha가 상위로 올린
종목들이 다시 차단당해 개선 효과가 상쇄될 수 있다. 이 스크립트는 그
질문에 실측으로 답한다 — 새 로직을 만들지 않고 §8/§12의 함수를 그대로
재사용한다.

방법(§16 이원 검증 도구 재사용):
  1. 3년 rolling 표본(87종목)에서 거래일마다 `regime_conditional_
     signal`을 계산하고, **그날 cross-sectional 상위 20%**를
     "새 alpha 상위군"으로 정의한다(§12와 동일한 신호, 여기서는
     top-quintile 멤버십만 추가로 본다).
  2. 상위군 각 종목에 대해 §8과 동일하게 **종목별(per-symbol)**
     `classify_market_regime()`을 계산하고, 운영 함수 `_assess_buy_
     eligibility()`/`_build_entry_score()`를 그대로 호출해 세 차단
     축(A=entry_score regime penalty, B=eligibility regime block,
     C=eligibility negative floor)과 최종 통과 여부를 판정한다 —
     이것이 지금 **실제로 운영 중인** 차단 로직이다(국면 정의를
     시장 공통으로 바꾸는 것이 아니라, 현재 코드 그대로를 새 alpha
     위에 얹어본다).
  3. 상위군을 "생존(차단 통과)"과 "차단됨"으로 나눠 forward return을
     비교한다 — 차단된 표본의 forward return이 실제로 나쁘면 차단이
     유효한 것이고, 생존군과 비슷하거나 더 좋으면 과잉 차단이다.
  4. **ablation**: 상위군 전체(차단 없음)의 forward return과 "생존만"
     의 forward return을 비교해, 차단을 걷어냈을 때 기대수익이
     개선되는지/악화되는지를 직접 계산한다.
  5. 1차(최근 12개월)/2차(3년) 이원 기준을 그대로 적용한다.

DB write / 주문 경로 / 실시간 구독 없음. 실제 KIS 호출 여부는 가정하지
않고 로그의 `HTTP Request:` 카운트로 그대로 보고한다.
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
logger = logging.getLogger("validate_new_alpha_vs_existing_blocking_axes")

_KST = timezone(timedelta(hours=9))

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK, _mean, _newey_west_se_of_mean, _stdev  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

_ROUND_TRIP_COST_BPS = 30.0
RECENT_WINDOW_CALENDAR_DAYS = 365
TOP_QUINTILE_FRACTION = 0.20


def _collect_symbol_rows(symbol: str, bars: list, market_common_regime_by_date: dict[str, str]) -> list[dict]:
    from agent_trading.services.deterministic_trigger_engine import (
        _assess_buy_eligibility,
        _build_entry_score,
    )
    from agent_trading.services.market_regime import classify_market_regime
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

        snapshot = SimpleNamespace(
            overall_score=overall,
            fast_score=fast,
            slow_score=slow,
            return_1m_pct=features.return_1m_pct,
            return_3m_pct=features.return_3m_pct,
            price_vs_sma_20_pct=features.price_vs_sma_20_pct,
            price_vs_sma_60_pct=features.price_vs_sma_60_pct,
            volatility_20d_pct=features.volatility_20d_pct,
            atr_14_pct=features.atr_14_pct,
            volume_surge_ratio=features.volume_surge_ratio,
            average_volume_20d=features.average_volume_20d,
            average_turnover_20d=features.average_turnover_20d,
            turnover_surge_ratio=features.turnover_surge_ratio,
            rsi_14=features.rsi_14,
            sma_5=features.sma_5,
            sma_20=features.sma_20,
            sma_60=features.sma_60,
            component_scores_json=None,
        )
        per_symbol_regime = classify_market_regime(snapshot)

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

        # 운영 함수 그대로 호출 — 새 alpha 위에 "현재 실제로 도는" 차단 로직을 얹는다.
        reason_codes: list[str] = []
        entry_score = _build_entry_score(
            overall=overall,
            fast=fast,
            slow=slow,
            signal_feature_snapshot=snapshot,
            market_regime=per_symbol_regime,
            strategy_selection=None,
            portfolio_allocation=None,
            source_type="core",
            reason_codes=reason_codes,
        )
        eligible, eligibility_reasons = _assess_buy_eligibility(
            source_type="core",
            coverage_score=1.0,
            allocation_budget_ok=True,
            market_regime=per_symbol_regime,
            overall=overall,
            slow=slow,
            signal_feature_snapshot=snapshot,
            portfolio_allocation=None,
            ranking_score=None,
        )

        axis_a = per_symbol_regime is not None and per_symbol_regime.risk_tone == "risk_off"
        axis_b = (
            per_symbol_regime is not None
            and per_symbol_regime.risk_tone == "risk_off"
            and per_symbol_regime.regime_label == "bearish_trend"
        )
        axis_c = (overall < -0.10) or (slow < -0.15)

        base_close = bars[t].close_price
        row: dict = {
            "symbol": symbol,
            "trade_date": trade_date,
            "market_common_regime": market_common_label,
            "regime_conditional_signal": regime_conditional_signal,
            "entry_score": entry_score,
            "eligible": eligible,
            "eligibility_first_fail_reason": eligibility_reasons[-1] if not eligible else None,
            "axis_a_entry_score_regime_penalty": axis_a,
            "axis_b_eligibility_regime_block": axis_b,
            "axis_c_eligibility_negative_floor": axis_c,
        }
        for h in FORWARD_HORIZONS_FOCUS:
            fwd_close = bars[t + h].close_price
            raw_ret = (fwd_close / base_close) - 1.0
            row[f"fwd_{h}"] = raw_ret
            row[f"fwd_{h}_net"] = raw_ret - (_ROUND_TRIP_COST_BPS / 10_000.0)

        rows.append(row)
    return rows


def _summarize(xs: list[float], horizon: int) -> dict:
    n = len(xs)
    if n < 5:
        return {"n": n, "note": "표본부족(<5)"}
    m = _mean(xs)
    std = _stdev(xs)
    from math import sqrt

    t_naive = (m / (std / sqrt(n))) if std else None
    nw_se = _newey_west_se_of_mean(xs, lag=max(horizon - 1, 1))
    t_nw = (m / nw_se) if nw_se else None
    return {
        "n": n,
        "mean_pct": round(m * 100, 4),
        "t_naive": round(t_naive, 2) if t_naive else None,
        "t_newey_west": round(t_nw, 2) if t_nw else None,
        "pct_positive": round(sum(1 for x in xs if x > 0) / n, 4),
    }


def _top_quintile_rows(rows: list[dict]) -> list[dict]:
    """거래일별 cross-sectional 상위 20%(regime_conditional_signal 기준)만 추출."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["regime_conditional_signal"] is not None:
            by_date[r["trade_date"]].append(r)

    top: list[dict] = []
    for day_rows in by_date.values():
        if len(day_rows) < 5:
            continue
        ordered = sorted(day_rows, key=lambda r: r["regime_conditional_signal"], reverse=True)
        q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
        top.extend(ordered[:q])
    return top


def _analyze_window(rows: list[dict], window_label: str) -> dict:
    top = _top_quintile_rows(rows)
    survives = [r for r in top if r["eligible"]]
    blocked = [r for r in top if not r["eligible"]]

    blocked_a = [r for r in top if r["axis_a_entry_score_regime_penalty"]]
    blocked_b = [r for r in top if r["axis_b_eligibility_regime_block"]]
    blocked_c = [r for r in top if r["axis_c_eligibility_negative_floor"]]

    print(f"\n--- {window_label} ---")
    print(f"새 alpha 상위 20% 표본: {len(top)}건 (전체 표본 대비)")
    print(f"  생존(eligibility 통과)={len(survives)}건({len(survives)/max(len(top),1)*100:.1f}%), "
          f"차단됨={len(blocked)}건({len(blocked)/max(len(top),1)*100:.1f}%)")
    print(f"  축A(entry_score regime penalty) 발동={len(blocked_a)}건, "
          f"축B(eligibility regime block) 발동={len(blocked_b)}건, "
          f"축C(eligibility negative floor) 발동={len(blocked_c)}건")

    window_report: dict = {
        "window": window_label,
        "top_quintile_n": len(top),
        "survives_n": len(survives),
        "blocked_n": len(blocked),
        "axis_a_n": len(blocked_a),
        "axis_b_n": len(blocked_b),
        "axis_c_n": len(blocked_c),
        "by_horizon": {},
    }

    for h in FORWARD_HORIZONS_FOCUS:
        key = f"fwd_{h}"
        print(f"  [T+{h}]")
        top_all_summary = _summarize([r[key] for r in top], h)
        survives_summary = _summarize([r[key] for r in survives], h)
        blocked_summary = _summarize([r[key] for r in blocked], h)
        print(f"    상위군 전체(ablation, 차단 없다고 가정): {top_all_summary}")
        print(f"    생존(현재 운영 로직 그대로 통과): {survives_summary}")
        print(f"    차단됨(현재 운영 로직이 걸러낸 표본): {blocked_summary}")
        window_report["by_horizon"][f"T+{h}"] = {
            "top_quintile_all_ablation_no_block": top_all_summary,
            "survives_current_operational_logic": survives_summary,
            "blocked_by_current_operational_logic": blocked_summary,
        }

    return window_report


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

    print("\n=== regime_conditional_signal 상위군 vs 기존 차단 축 결합 효과 ===")
    print(f"전체 3년 표본: {len(all_rows)}건, 최근 12개월(cutoff={cutoff}) 표본: {len(recent_rows)}건")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_rows),
        "total_rolling_samples_recent_12m": len(recent_rows),
        "recent_window_cutoff": cutoff,
        "windows": {},
    }

    report["windows"]["supplementary_3y"] = _analyze_window(all_rows, "2차(3년, 전체 표본)")
    report["windows"]["primary_recent_12m"] = _analyze_window(recent_rows, "1차(최근 12개월)")

    out_path = "logs/signal_ic_new_alpha_vs_existing_blocking_axes_2026-07-15.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
