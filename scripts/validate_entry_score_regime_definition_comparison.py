#!/usr/bin/env python3
"""SPPV-3 본작업 사전 실험 — 종목별 regime vs 시장 공통 regime의
eligibility 통과군 forward return 비교 (read-only).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §9.6에서
설계한 실험을 그대로 실행한다. 새 방법론을 만들지 않고 §16 이원 검증이
확립한 도구(cross-sectional quintile spread, Newey-West 보정, 3년
rolling 표본)와 운영 함수(`_assess_buy_eligibility`)를 그대로 재사용
한다.

핵심 질문: SPPV-2.19가 확인한 "종목별 regime_label은 시장 공통 국면과
69%가 다르다"는 사실이, 실제로 **더 나은 종목을 걸러내는 유의미한
차이**인지, 아니면 그냥 다른 잣대일 뿐 forward return에는 차이가
없는지(또는 시장 공통 정의가 오히려 나쁜지)를 실측으로 가린다.

방법:
  1. 3년 rolling 표본(87종목, 캐시 재사용)에 대해 거래일마다
     - **변형 A(현행)**: 그 종목 자신의 스냅샷으로 `classify_market_
       regime()`을 호출한 결과를 eligibility의 `market_regime`으로 사용.
     - **변형 B(시장 공통)**: 벤치마크(069500) 자신의 rolling 상태로
       판정한, 그날 전 종목이 공유하는 국면을 eligibility의
       `market_regime`으로 사용.
     둘 다 운영 함수 `_assess_buy_eligibility()`를 그대로 호출한다
     (allocation/strategy 등 재구성 불가 항목은 None으로 자연스럽게
     건너뛴다 — Phase 0 경계, 기존 스크립트들과 동일).
  2. 각 변형의 eligibility 통과 표본에 대해 T+5/T+20 forward return의
     평균, Newey-West t-stat(평균이 0과 다른지), 양수 비율(승률에 대응)을
     계산하고, 전체 표본(baseline, eligibility 무관)과 비교한다.
  3. 통과 표본 내부에서 `overall_score` 기준 상위/하위 quintile spread도
     함께 계산해, 통과 이후에도 신호가 종목을 가려내는지 확인한다.

DB write / 주문 경로 / 실시간 구독 없음. 3년 캐시를 재사용하며, 캐시가
없는 신규 심볼만 KIS 조회한다 — 이번 실행의 실제 KIS 호출 여부는
가정하지 않고 로그의 `HTTP Request:` 카운트로 그대로 보고한다.
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
logger = logging.getLogger("validate_entry_score_regime_definition_comparison")

_KST = timezone(timedelta(hours=9))

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v2 import (  # noqa: E402
    _MIN_LOOKBACK,
    _mean,
    _newey_west_se_of_mean,
    _rank,
    _spearman_ic,
    _stdev,
)
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

_ROUND_TRIP_COST_BPS = 30.0


def _collect_symbol_rows(symbol: str, bars: list, market_common_regime_by_date: dict[str, str]) -> list[dict]:
    from agent_trading.services.deterministic_trigger_engine import _assess_buy_eligibility
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
        slow = float(card.slow_score)

        snapshot = SimpleNamespace(
            overall_score=overall,
            fast_score=float(card.fast_score),
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
        if market_common_label is None:
            market_common_regime = None
        else:
            # eligibility가 실제로 보는 필드는 regime_label/risk_tone뿐이므로
            # 시장 공통 판정에 맞춰 risk_tone도 함께 재구성한다(운영 classify_
            # market_regime의 risk_tone 산정 규칙과 동일한 매핑 — bearish_trend
            # 는 risk_off, 나머지는 neutral로 그대로 재사용).
            market_common_risk_tone = "risk_off" if market_common_label == "bearish_trend" else "neutral"
            market_common_regime = SimpleNamespace(
                regime_label=market_common_label,
                risk_tone=market_common_risk_tone,
            )

        eligible_a, _ = _assess_buy_eligibility(
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
        eligible_b = None
        if market_common_regime is not None:
            eligible_b, _ = _assess_buy_eligibility(
                source_type="core",
                coverage_score=1.0,
                allocation_budget_ok=True,
                market_regime=market_common_regime,
                overall=overall,
                slow=slow,
                signal_feature_snapshot=snapshot,
                portfolio_allocation=None,
                ranking_score=None,
            )

        base_close = bars[t].close_price
        row: dict = {
            "symbol": symbol,
            "trade_date": trade_date,
            "overall_score": overall,
            "per_symbol_regime_label": per_symbol_regime.regime_label if per_symbol_regime else None,
            "market_common_regime_label": market_common_label,
            "eligible_a_per_symbol": eligible_a,
            "eligible_b_market_common": eligible_b,
        }
        for h in FORWARD_HORIZONS_FOCUS:
            fwd_close = bars[t + h].close_price
            raw_ret = (fwd_close / base_close) - 1.0
            row[f"fwd_{h}"] = raw_ret
            row[f"fwd_{h}_net"] = raw_ret - (_ROUND_TRIP_COST_BPS / 10_000.0)

        rows.append(row)
    return rows


def _summarize_series(xs: list[float], horizon: int, *, is_pct: bool = True) -> dict:
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
        "mean_pct": round(m * 100, 4) if is_pct else round(m, 4),
        "t_naive": round(t_naive, 2) if t_naive else None,
        "t_newey_west": round(t_nw, 2) if t_nw else None,
        "pct_positive": round(sum(1 for x in xs if x > 0) / n, 4),
    }


def _quintile_spread_within(rows: list[dict], return_key: str) -> list[float]:
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_date[r["trade_date"]].append(r)
    spreads: list[float] = []
    for day_rows in by_date.values():
        if len(day_rows) < 5:
            continue
        ordered = sorted(day_rows, key=lambda r: r["overall_score"])
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

    bench_bars = await _fetch_extended_bars(client, BENCHMARK_SYMBOL)
    market_common_regime_by_date, _ = _build_benchmark_daily_series(bench_bars)
    if not market_common_regime_by_date:
        raise SystemExit("시장 공통 국면 계산 실패")

    from collections import Counter

    market_common_dist = dict(Counter(market_common_regime_by_date.values()))
    logger.info("시장 공통 국면 분포(3년): %s", market_common_dist)

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

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples": len(all_rows),
        "market_common_regime_distribution_3y": market_common_dist,
        "baseline": {},
        "variant_a_per_symbol": {},
        "variant_b_market_common": {},
    }

    print("\n=== 종목별 regime vs 시장 공통 regime — eligibility 통과군 forward return 비교 ===")
    print(f"전체 표본: {len(all_rows)}건, 시장 공통 국면 분포(3년): {market_common_dist}")

    rows_a = [r for r in all_rows if r["eligible_a_per_symbol"]]
    rows_b = [r for r in all_rows if r["eligible_b_market_common"] is True]
    rows_b_evaluable = [r for r in all_rows if r["eligible_b_market_common"] is not None]

    print(f"\n[통과 종목 수] 변형 A(종목별) 통과 {len(rows_a)}/{len(all_rows)} "
          f"({len(rows_a)/len(all_rows)*100:.2f}%)")
    print(f"[통과 종목 수] 변형 B(시장 공통) 통과 {len(rows_b)}/{len(rows_b_evaluable)} "
          f"({len(rows_b)/len(rows_b_evaluable)*100:.2f}%, 시장 공통 라벨이 존재하는 표본 기준)")

    for h in FORWARD_HORIZONS_FOCUS:
        key = f"fwd_{h}"
        print(f"\n[T+{h}]")

        baseline_summary = _summarize_series([r[key] for r in all_rows], h)
        report["baseline"][f"T+{h}"] = baseline_summary
        print(f"  baseline(전체 표본, eligibility 무관): {baseline_summary}")

        a_summary = _summarize_series([r[key] for r in rows_a], h)
        a_spread = _quintile_spread_within(rows_a, f"{key}_net")
        a_spread_summary = _summarize_series(a_spread, h)
        report["variant_a_per_symbol"][f"T+{h}"] = {
            "eligible_forward_return": a_summary,
            "within_eligible_quintile_spread": a_spread_summary,
        }
        print(f"  변형 A(종목별) 통과군 forward return: {a_summary}")
        print(f"  변형 A 통과군 내부 quintile spread: {a_spread_summary}")

        b_summary = _summarize_series([r[key] for r in rows_b], h)
        b_spread = _quintile_spread_within(rows_b, f"{key}_net")
        b_spread_summary = _summarize_series(b_spread, h)
        report["variant_b_market_common"][f"T+{h}"] = {
            "eligible_forward_return": b_summary,
            "within_eligible_quintile_spread": b_spread_summary,
        }
        print(f"  변형 B(시장 공통) 통과군 forward return: {b_summary}")
        print(f"  변형 B 통과군 내부 quintile spread: {b_spread_summary}")

    out_path = "logs/signal_ic_entry_score_regime_definition_comparison_2026-07-15.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
