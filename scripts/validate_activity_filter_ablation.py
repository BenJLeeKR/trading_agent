#!/usr/bin/env python3
"""SPPV-3 사전 실험 — `eligibility_low_relative_activity` 활동성 필터
정밀 ablation (read-only).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §13.7(다음
단계 1 — 활동성 필터 ablation 신규 최우선) 참고.

§13(SPPV-2.23)은 `regime_conditional_signal` 상위군의 60~68%가
차단되는데, 그 압도적 원인이 국면(regime) 관련 축이 아니라
`_assess_buy_eligibility()`의 활동성 필터

```python
if (
    volume_surge_ratio is not None
    and turnover_surge_ratio is not None
    and max(volume_surge_ratio, turnover_surge_ratio) < 1.10
):
    reasons.append("eligibility_low_relative_activity")
    return False, tuple(reasons)
```

(`deterministic_trigger_engine.py:493-499`, 코드 기준 재확인 완료)임을
발견했다. 이 스크립트는 그 필터 하나만 골라 **제거/완화 시 forward
return이 실제로 개선되는지**를 3개 시나리오로 정밀 비교한다 — "차단이
많다"가 아니라 "차단을 걷어냈을 때 기대수익이 좋아지는가"로 판단한다.

시나리오 정의(운영 함수 `_assess_buy_eligibility()`의 체크 순서를
그대로 따름 — 이 필터를 통과하면 바로 다음 체크는 `portfolio_
allocation`이 필요한 참여율 검사인데, 이 실험에서는 그 값을 재구성할
수 없어 `None`으로 두므로 자동으로 통과 처리된다는 점을 코드로 확인
했다. 즉 "필터 제거"는 곧바로 최종 통과를 뜻한다):

  1. **현행 유지**: threshold=1.10(운영 값 그대로).
  2. **필터 완전 제거**: 이 체크를 건너뛴다(threshold 없음).
  3. **완화(threshold=1.00)**: 급증 비율 요구치를 10%p 낮춘다.

세 시나리오 각각에 대해 `regime_conditional_signal` 상위 20% 표본
중 (a) 다른 모든 체크(source_type/coverage/allocation/regime/signal
floor/유동성 하한/거래대금 하한)를 이미 통과한 표본만 대상으로, 활동성
조건만 바꿔가며 최종 통과 여부와 forward return을 비교한다. §16
이원 기준(1차=최근 12개월, 2차=3년)을 그대로 적용한다.

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
logger = logging.getLogger("validate_activity_filter_ablation")

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

# 활동성 필터 threshold 시나리오(운영 값=1.10). None=필터 완전 제거.
THRESHOLD_SCENARIOS = {"current_1.10": 1.10, "relaxed_1.00": 1.00, "removed": None}


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

        # 활동성 필터를 제외한 다른 모든 체크를 통과했는지(=활동성 필터가
        # "유일한" 탈락 사유였는지) — 운영 함수 그대로 호출한 결과와
        # first_fail_reason만으로 판별 가능(새 로직 없음).
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
        }
        for h in FORWARD_HORIZONS_FOCUS:
            fwd_close = bars[t + h].close_price
            raw_ret = (fwd_close / base_close) - 1.0
            row[f"fwd_{h}"] = raw_ret
            row[f"fwd_{h}_net"] = raw_ret - (_ROUND_TRIP_COST_BPS / 10_000.0)

        rows.append(row)
    return rows


def _eligible_under_threshold(row: dict, threshold: float | None) -> bool:
    if not row["passes_all_except_activity"]:
        return False
    if threshold is None:
        return True  # 필터 완전 제거
    if row["activity_ratio"] is None:
        return True  # 원 코드와 동일하게, 값이 없으면 이 체크 자체를 건너뜀(통과)
    return row["activity_ratio"] >= threshold


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
    print(f"\n--- {window_label} ---")
    print(f"새 alpha 상위 20% 표본: {len(top)}건")

    window_report: dict = {"window": window_label, "top_quintile_n": len(top), "scenarios": {}}

    for scenario_name, threshold in THRESHOLD_SCENARIOS.items():
        survives = [r for r in top if _eligible_under_threshold(r, threshold)]
        blocked = [r for r in top if not _eligible_under_threshold(r, threshold)]
        pct_survive = len(survives) / max(len(top), 1) * 100
        print(f"\n  [시나리오: {scenario_name}, threshold={threshold}] "
              f"생존={len(survives)}건({pct_survive:.1f}%), 차단={len(blocked)}건")

        scenario_report: dict = {
            "threshold": threshold,
            "survives_n": len(survives),
            "blocked_n": len(blocked),
            "survives_pct": round(pct_survive, 2),
            "by_horizon": {},
        }
        for h in FORWARD_HORIZONS_FOCUS:
            key = f"fwd_{h}"
            survives_summary = _summarize([r[key] for r in survives], h)
            print(f"    T+{h} 생존군: {survives_summary}")
            scenario_report["by_horizon"][f"T+{h}"] = survives_summary
        window_report["scenarios"][scenario_name] = scenario_report

    # 참고: top quintile 전체(무차단) 요약도 함께 기록
    window_report["top_quintile_all_no_block"] = {}
    for h in FORWARD_HORIZONS_FOCUS:
        key = f"fwd_{h}"
        s = _summarize([r[key] for r in top], h)
        window_report["top_quintile_all_no_block"][f"T+{h}"] = s
    print(f"  [참고] 상위군 전체(모든 차단 무시): "
          f"{ {h: window_report['top_quintile_all_no_block'][f'T+{h}'] for h in FORWARD_HORIZONS_FOCUS} }")

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

    print("\n=== eligibility_low_relative_activity 활동성 필터 정밀 ablation ===")
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

    out_path = "logs/signal_ic_activity_filter_ablation_2026-07-16.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
