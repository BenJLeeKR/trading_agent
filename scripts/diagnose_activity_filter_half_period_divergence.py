#!/usr/bin/env python3
"""SPPV-2.25 후속 — 활동성 필터 완화 효과가 3년 전반부/후반부에서
정반대로 나타난 원인 분해 (read-only, shadow 검증).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §15.6(다음
단계 1 — 전반부/후반부가 왜 반대 방향을 보이는지 원인 규명) 참고.

§15(SPPV-2.25)는 threshold를 1.10(현행)/1.05/1.00/0.95/0.90으로
스윕하고 3년 표본을 전반부(2023-10-10~2025-02-11)/후반부
(2025-02-12~2026-06-16)로 양분한 결과, **전체 3년·최근 12개월·
후반부에서는 완화할수록 개선되지만 전반부에서는 정반대로 악화**
됨을 발견했다. 이 스크립트는 그 원인을 아래 네 축으로 분해한다:

1. **시장 공통 regime 분포 차이** — 전반부/후반부 각각 bullish_
   trend/range_bound/bearish_trend 거래일 비중.
2. **거래대금/거래량 surge level(활동성 비율) 분포 차이** — 상위
   20% quintile 내 `activity_ratio` 분포(평균/중앙값/사분위)가
   두 반기에서 얼마나 다른지.
3. **상위 20% 진입 후보군의 기본 수익률 레벨 차이** — 차단 없는
   상위군 전체(top quintile, no block)의 T+5/T+20 평균이 두 반기
   에서 얼마나 다른지(시장 자체의 베타/알파 레벨 차이).
4. **"완화 시 추가로 살아나는 표본"의 성격 차이** — threshold를
   1.10→1.00/0.95/0.90으로 낮췄을 때 새로 통과하는 표본만 따로
   골라, 그 표본의 T+5/T+20 평균·t_NW·양수율·activity_ratio·
   volatility_20d_pct·turnover 레벨·trend 강도(price_vs_sma_60_pct)
   를 두 반기에서 비교한다.

기존 `scripts/validate_activity_filter_ablation.py`(SPPV-2.24)와
`scripts/validate_activity_filter_threshold_sweep.py`(SPPV-2.25)의
표본 수집·집계 로직(`_eligible_under_threshold`, `_summarize`,
`_top_quintile_rows`, 기간 분할 방식)을 그대로 재사용한다 — 새 통계
공식이나 새 실험 설계를 도입하지 않는다. 다만 원인 분해에 필요한
추가 원시값(volatility_20d_pct, average_turnover_20d, price_vs_
sma_60_pct)을 수집하기 위해 `_collect_symbol_rows`를 확장한
로컬 버전을 사용한다(운영 코드 변경 없음, read-only).

DB write / 주문 경로 / 실시간 구독 없음. 실제 KIS 호출 여부는 가정하지
않고 로그의 `HTTP Request:` 카운트로 그대로 보고한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys as _sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("diagnose_activity_filter_half_period_divergence")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_activity_filter_ablation import (  # noqa: E402
    _eligible_under_threshold,
    _summarize,
    _top_quintile_rows,
)
from validate_activity_filter_threshold_sweep import _split_first_second_half  # noqa: E402
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK, _mean  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

_ROUND_TRIP_COST_BPS = 30.0
RELAXED_THRESHOLDS_TO_DIAGNOSE = [1.00, 0.95, 0.90]


def _collect_symbol_rows_extended(symbol: str, bars: list, market_common_regime_by_date: dict[str, str]) -> list[dict]:
    """§14의 `_collect_symbol_rows`와 동일한 계산에 원인 분해용 원시값
    (volatility_20d_pct, average_turnover_20d, price_vs_sma_60_pct)만
    추가로 저장한다 — 신호/eligibility 계산 로직은 변경하지 않는다."""
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
        first_fail_reason = eligibility_reasons[-1] if not eligible else None
        passes_all_except_activity = eligible or (first_fail_reason == "eligibility_low_relative_activity")

        volume_surge_ratio = features.volume_surge_ratio
        turnover_surge_ratio = features.turnover_surge_ratio
        activity_ratio = None
        if volume_surge_ratio is not None and turnover_surge_ratio is not None:
            activity_ratio = max(volume_surge_ratio, turnover_surge_ratio)

        base_close = bars[t].close_price
        row: dict = {
            "symbol": symbol,
            "trade_date": trade_date,
            "market_common_regime": market_common_label,
            "regime_conditional_signal": regime_conditional_signal,
            "eligible_current": eligible,
            "eligibility_first_fail_reason": first_fail_reason,
            "passes_all_except_activity": passes_all_except_activity,
            "activity_ratio": activity_ratio,
            "volatility_20d_pct": features.volatility_20d_pct,
            "average_turnover_20d": features.average_turnover_20d,
            "trend_strength_price_vs_sma_60_pct": features.price_vs_sma_60_pct,
        }
        for h in FORWARD_HORIZONS_FOCUS:
            fwd_close = bars[t + h].close_price
            raw_ret = (fwd_close / base_close) - 1.0
            row[f"fwd_{h}"] = raw_ret
            row[f"fwd_{h}_net"] = raw_ret - (_ROUND_TRIP_COST_BPS / 10_000.0)

        rows.append(row)
    return rows


def _regime_day_distribution(rows: list[dict]) -> dict:
    by_date: dict[str, str] = {}
    for r in rows:
        by_date.setdefault(r["trade_date"], r["market_common_regime"])
    counts = Counter(by_date.values())
    total = sum(counts.values()) or 1
    return {k: {"days": v, "pct": round(v / total * 100, 1)} for k, v in counts.items()}


def _quartiles(xs: list[float]) -> dict:
    if not xs:
        return {}
    ordered = sorted(xs)
    n = len(ordered)

    def pct(p: float) -> float:
        idx = min(n - 1, max(0, int(round(p * (n - 1)))))
        return ordered[idx]

    return {
        "n": n,
        "mean": round(_mean(ordered), 4),
        "median": round(pct(0.5), 4),
        "p25": round(pct(0.25), 4),
        "p75": round(pct(0.75), 4),
    }


def _analyze_half(rows: list[dict], label: str) -> dict:
    top = _top_quintile_rows(rows)
    print(f"\n=== {label} (상위 20% 표본 {len(top)}건) ===")

    result: dict = {"label": label, "top_quintile_n": len(top)}

    # 1) regime 분포
    regime_dist = _regime_day_distribution(rows)
    print(f"  국면 분포(거래일 기준): {regime_dist}")
    result["regime_day_distribution"] = regime_dist

    # 2) activity_ratio 분포 (상위 20% quintile 내부)
    activity_ratios = [r["activity_ratio"] for r in top if r["activity_ratio"] is not None]
    activity_stats = _quartiles(activity_ratios)
    print(f"  activity_ratio 분포(상위 20% 내부): {activity_stats}")
    result["activity_ratio_distribution"] = activity_stats

    # 3) 상위 20% quintile 전체(무차단) 기본 수익률 레벨
    baseline_by_horizon = {}
    for h in FORWARD_HORIZONS_FOCUS:
        s = _summarize([r[f"fwd_{h}"] for r in top], h)
        baseline_by_horizon[f"T+{h}"] = s
    print(f"  상위 20% 전체(무차단) 기본 수익률: {baseline_by_horizon}")
    result["top_quintile_all_no_block"] = baseline_by_horizon

    # 4) 보조 축: 상위 20% 내부 volatility / turnover / trend 레벨
    vol_stats = _quartiles([r["volatility_20d_pct"] for r in top if r["volatility_20d_pct"] is not None])
    turnover_stats = _quartiles([r["average_turnover_20d"] for r in top if r["average_turnover_20d"] is not None])
    trend_stats = _quartiles(
        [r["trend_strength_price_vs_sma_60_pct"] for r in top if r["trend_strength_price_vs_sma_60_pct"] is not None]
    )
    print(f"  volatility_20d_pct 분포: {vol_stats}")
    print(f"  average_turnover_20d 분포: {turnover_stats}")
    print(f"  trend_strength(price_vs_sma_60_pct) 분포: {trend_stats}")
    result["volatility_20d_pct_distribution"] = vol_stats
    result["average_turnover_20d_distribution"] = turnover_stats
    result["trend_strength_distribution"] = trend_stats

    # 5) threshold별 "완화 시 새로 살아나는 표본"만 분리해 성격 비교
    baseline_eligible = {r["symbol"] + r["trade_date"] for r in top if _eligible_under_threshold(r, 1.10)}
    newly_freed_by_threshold: dict = {}
    for threshold in RELAXED_THRESHOLDS_TO_DIAGNOSE:
        eligible_now = [r for r in top if _eligible_under_threshold(r, threshold)]
        newly_freed = [r for r in eligible_now if (r["symbol"] + r["trade_date"]) not in baseline_eligible]
        print(f"\n  [threshold={threshold}] 신규 생존(현행 1.10 대비 추가): {len(newly_freed)}건")

        entry: dict = {"threshold": threshold, "newly_freed_n": len(newly_freed), "by_horizon": {}}
        for h in FORWARD_HORIZONS_FOCUS:
            s = _summarize([r[f"fwd_{h}"] for r in newly_freed], h)
            print(f"    T+{h} 신규 생존군: {s}")
            entry["by_horizon"][f"T+{h}"] = s

        if newly_freed:
            entry["activity_ratio_of_newly_freed"] = _quartiles(
                [r["activity_ratio"] for r in newly_freed if r["activity_ratio"] is not None]
            )
            entry["volatility_of_newly_freed"] = _quartiles(
                [r["volatility_20d_pct"] for r in newly_freed if r["volatility_20d_pct"] is not None]
            )
            entry["turnover_of_newly_freed"] = _quartiles(
                [r["average_turnover_20d"] for r in newly_freed if r["average_turnover_20d"] is not None]
            )
            entry["trend_of_newly_freed"] = _quartiles(
                [r["trend_strength_price_vs_sma_60_pct"] for r in newly_freed
                 if r["trend_strength_price_vs_sma_60_pct"] is not None]
            )
            print(f"    신규 생존군 activity_ratio: {entry['activity_ratio_of_newly_freed']}")
            print(f"    신규 생존군 volatility_20d_pct: {entry['volatility_of_newly_freed']}")
            print(f"    신규 생존군 average_turnover_20d: {entry['turnover_of_newly_freed']}")
            print(f"    신규 생존군 trend_strength: {entry['trend_of_newly_freed']}")

        newly_freed_by_threshold[f"threshold_{threshold}"] = entry

    result["newly_freed_analysis"] = newly_freed_by_threshold
    return result


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
        rows = _collect_symbol_rows_extended(symbol, bars, market_common_regime_by_date)
        all_rows.extend(rows)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_rows))

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_rows), len(fetch_failures))

    first_half, second_half = _split_first_second_half(all_rows)
    d_first = sorted({r["trade_date"] for r in first_half})
    d_second = sorted({r["trade_date"] for r in second_half})

    print("\n=== 활동성 필터 완화 효과 전반부/후반부 반전 원인 분해 ===")
    print(f"전반부: {d_first[0]}~{d_first[-1]}({len(first_half)}건)")
    print(f"후반부: {d_second[0]}~{d_second[-1]}({len(second_half)}건)")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_rows),
        "relaxed_thresholds_diagnosed": RELAXED_THRESHOLDS_TO_DIAGNOSE,
        "halves": {},
    }

    report["halves"]["first_half"] = _analyze_half(first_half, "3년 전반부(2023-10-10~2025-02-11)")
    report["halves"]["second_half"] = _analyze_half(second_half, "3년 후반부(2025-02-12~2026-06-16)")

    out_path = "logs/signal_ic_activity_filter_half_period_divergence_2026-07-16.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
