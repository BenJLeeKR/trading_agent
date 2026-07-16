#!/usr/bin/env python3
"""SPPV-3 alpha layer 교체 검증 — 현행 alpha layer vs
`regime_conditional_signal`을 BUY funnel(candidate→eligible→
would_buy→blocked) 관점에서 비교 (read-only, shadow 검증).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §3(entry_score
통합 방안, 미적용 제안), §12(alpha layer vs regime_conditional_signal
직접 비교, Conditional Go), §13(결합 효과 검증, Watch) 참고.

§12는 순수 cross-sectional 순위 성능(quintile spread/IC)만으로
`regime_conditional_signal`이 현행 alpha layer보다 낫다는 것을
확인했다(Conditional Go). §13은 그 새 alpha를 "차단 축은 그대로 둔
채" 얹었을 때 60~68%가 차단된다는 것을 보였다. 이번 스크립트는 이
둘을 하나의 **BUY funnel** 관점으로 통합한다 — "무엇을 덜 막을까"가
아니라 **"alpha를 무엇으로 교체하면 실제로 더 좋은 종목이 앞줄에
서는가"**를 candidate/eligible/would_buy 단계별로 직접 비교한다.

시나리오 정의(운영 코드 그대로 재사용, 새 로직 없음):
  - **시나리오 A(현행)**: alpha = `current_alpha_composite`
    (`0.45*overall+0.20*fast+0.15*slow`, entry_score의 alpha 항과
    순위 동치 — §12에서 코드로 증명됨). entry_score는 운영 함수
    `_build_entry_score()`를 그대로 호출(현행 alpha 항 포함).
  - **시나리오 B(제안)**: alpha = `regime_conditional_signal`(§2).
    entry_score는 §3이 제안한 그대로 **alpha 항(0.80 가중치)만
    교체**하고 나머지(국면 bonus/penalty, allocation/strategy/
    source/relative-activity)는 `_build_entry_score()`와 동일한
    코드를 로컬에서 재구성한다(운영 함수 수정 없음, §3 제안 공식을
    그대로 구현) — `_build_entry_score`가 alpha 항을 무조건 3개
    항으로 하드코딩하고 있어 alpha만 교체한 값을 얻으려면 이 방법이
    유일하다.

funnel 4단계(하루·표본 단위):
  1. **candidate**: 그날 cross-sectional 상위 20%(quintile, 시나리오별
     alpha 기준) — §12/§13과 동일한 20% 정의.
  2. **eligible**: 운영 함수 `_assess_buy_eligibility()`를 그대로
     호출(어떤 alpha를 쓰든 이 판정 로직 자체는 동일 — eligibility는
     overall/slow raw 값과 activity/liquidity 원시값만 본다). 즉
     차단 축 자체는 이번 턴의 조작 대상이 아니라 "새 alpha가 이
     차단을 얼마나 통과하는지"를 보는 보조 지표로만 쓰인다(작업
     지시 6항).
  3. **would_buy**: eligible 중 그날 entry_score(시나리오별) 상위
     `WATCH_TOP_K_BUY`(=3, `trigger_proxy_attribution.py:38`에서
     실제 운영 중인 하루 매수 후보 top-K 상수를 그대로 재사용 —
     새 K를 임의로 정하지 않음).
  4. **blocked**: candidate이지만 eligible이 아닌 표본.

DB write / 주문 경로 / 실시간 구독 없음. 실제 KIS 호출 여부는 가정하지
않고 로그의 `HTTP Request:` 카운트로 그대로 보고한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys as _sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_alpha_layer_buy_funnel_comparison")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_activity_filter_threshold_sweep import _split_first_second_half  # noqa: E402
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

# entry_score alpha layer 원 가중치(deterministic_trigger_engine.py:1128-1130)
_ALPHA_W_OVERALL = 0.45
_ALPHA_W_FAST = 0.20
_ALPHA_W_SLOW = 0.15
_ALPHA_W_NEW_SIGNAL = 0.80  # §3 제안: 0.45+0.20+0.15 블록을 통째로 교체

# 하루 매수 후보 top-K(실제 운영 상수 재사용, trigger_proxy_attribution.py:38)
WATCH_TOP_K_BUY = 3


def _entry_score_non_alpha_terms(market_regime, snapshot) -> tuple[float, list[str]]:
    """`_build_entry_score()`의 alpha 항(0.80 가중치 블록)을 제외한
    나머지(국면 bonus/penalty, relative-activity bonus)를 운영 함수와
    동일한 공식으로 재구성한다. portfolio_allocation/strategy_selection은
    이 세션 전체의 shadow 재구성 관례대로 None(재구성 불가)이므로 두
    분기 모두 기여가 0이고, source_type="core"도 기여 0이다 — 이 세
    항목은 alpha와 무관하며 §3 제안도 "그대로 유지"를 명시한다."""
    from agent_trading.services.deterministic_trigger_engine import _build_relative_activity_score

    score = 0.0
    reasons: list[str] = []
    if market_regime is not None:
        if market_regime.regime_label == "bullish_trend":
            score += 0.10
            reasons.append("trigger_bullish_regime")
        if market_regime.risk_tone == "risk_on":
            score += 0.05
            reasons.append("trigger_risk_on")
        if market_regime.risk_tone == "risk_off":
            score -= 0.15
            reasons.append("trigger_risk_off_penalty")

    relative_activity_bonus = _build_relative_activity_score(snapshot)
    if relative_activity_bonus > 0:
        score += min(0.10, relative_activity_bonus * 0.10)
        reasons.append("trigger_relative_activity_bonus")

    return score, reasons


def _normalize_signed_score(value) -> float:
    if value is None:
        return 0.5
    return max(0.0, min(1.0, (value + 1.0) / 2.0))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


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

        current_alpha_composite = _ALPHA_W_OVERALL * overall + _ALPHA_W_FAST * fast + _ALPHA_W_SLOW * slow

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

        # eligibility: 운영 함수 그대로(alpha와 무관, 종목별 regime 사용 — 현행 운영 로직)
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

        # entry_score 시나리오 A(현행): 운영 함수 그대로 호출
        entry_score_a = _build_entry_score(
            overall=overall,
            fast=fast,
            slow=slow,
            signal_feature_snapshot=snapshot,
            market_regime=per_symbol_regime,
            strategy_selection=None,
            portfolio_allocation=None,
            source_type="core",
            reason_codes=[],
        )

        # entry_score 시나리오 B(제안): alpha 항만 교체, 나머지는 동일 공식으로 재구성
        non_alpha_b, _ = _entry_score_non_alpha_terms(per_symbol_regime, snapshot)
        if regime_conditional_signal is not None:
            entry_score_b = _clamp01(_ALPHA_W_NEW_SIGNAL * _normalize_signed_score(regime_conditional_signal) + non_alpha_b)
        else:
            entry_score_b = None

        base_close = bars[t].close_price
        row: dict = {
            "symbol": symbol,
            "trade_date": trade_date,
            "market_common_regime": market_common_label,
            "current_alpha_composite": current_alpha_composite,
            "regime_conditional_signal": regime_conditional_signal,
            "eligible": eligible,
            "eligibility_first_fail_reason": eligibility_reasons[-1] if not eligible else None,
            "entry_score_a": entry_score_a,
            "entry_score_b": entry_score_b,
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


def _funnel_for_scenario(rows: list[dict], signal_key: str, entry_score_key: str) -> dict:
    """cross-sectional 상위 20%(candidate) → eligible → would_buy(top-K) 4단계 funnel."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get(signal_key) is not None:
            by_date[r["trade_date"]].append(r)

    candidates: list[dict] = []
    eligible_rows: list[dict] = []
    would_buy_rows: list[dict] = []
    blocked_rows: list[dict] = []

    for day_rows in by_date.values():
        if len(day_rows) < 5:
            continue
        ordered = sorted(day_rows, key=lambda r: r[signal_key], reverse=True)
        q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
        day_candidates = ordered[:q]
        candidates.extend(day_candidates)

        day_eligible = [r for r in day_candidates if r["eligible"]]
        day_blocked = [r for r in day_candidates if not r["eligible"]]
        eligible_rows.extend(day_eligible)
        blocked_rows.extend(day_blocked)

        day_eligible_ranked = sorted(
            [r for r in day_eligible if r.get(entry_score_key) is not None],
            key=lambda r: r[entry_score_key],
            reverse=True,
        )
        would_buy_rows.extend(day_eligible_ranked[:WATCH_TOP_K_BUY])

    return {
        "candidate": candidates,
        "eligible": eligible_rows,
        "would_buy": would_buy_rows,
        "blocked": blocked_rows,
    }


def _funnel_report(funnel: dict) -> dict:
    n_candidate = len(funnel["candidate"])
    n_eligible = len(funnel["eligible"])
    n_would_buy = len(funnel["would_buy"])
    n_blocked = len(funnel["blocked"])

    report: dict = {
        "candidate_n": n_candidate,
        "eligible_n": n_eligible,
        "would_buy_n": n_would_buy,
        "blocked_n": n_blocked,
        "eligible_rate_of_candidate": round(n_eligible / max(n_candidate, 1) * 100, 2),
        "would_buy_rate_of_candidate": round(n_would_buy / max(n_candidate, 1) * 100, 2),
        "would_buy_rate_of_eligible": round(n_would_buy / max(n_eligible, 1) * 100, 2),
        "by_stage_horizon": {},
    }
    for stage_name, stage_rows in (("candidate", funnel["candidate"]), ("eligible", funnel["eligible"]),
                                    ("would_buy", funnel["would_buy"]), ("blocked", funnel["blocked"])):
        report["by_stage_horizon"][stage_name] = {}
        for h in FORWARD_HORIZONS_FOCUS:
            xs = [r[f"fwd_{h}"] for r in stage_rows]
            report["by_stage_horizon"][stage_name][f"T+{h}"] = _summarize(xs, h)
    return report


def _analyze_window(rows: list[dict], window_label: str) -> dict:
    print(f"\n=== {window_label} (표본 {len(rows)}건) ===")

    funnel_a = _funnel_for_scenario(rows, "current_alpha_composite", "entry_score_a")
    funnel_b = _funnel_for_scenario(rows, "regime_conditional_signal", "entry_score_b")

    report_a = _funnel_report(funnel_a)
    report_b = _funnel_report(funnel_b)

    print(f"  [시나리오 A: 현행 alpha] candidate={report_a['candidate_n']}, "
          f"eligible={report_a['eligible_n']}({report_a['eligible_rate_of_candidate']}%), "
          f"would_buy={report_a['would_buy_n']}, blocked={report_a['blocked_n']}")
    for h in FORWARD_HORIZONS_FOCUS:
        print(f"    would_buy T+{h}: {report_a['by_stage_horizon']['would_buy'][f'T+{h}']}")

    print(f"  [시나리오 B: regime_conditional_signal] candidate={report_b['candidate_n']}, "
          f"eligible={report_b['eligible_n']}({report_b['eligible_rate_of_candidate']}%), "
          f"would_buy={report_b['would_buy_n']}, blocked={report_b['blocked_n']}")
    for h in FORWARD_HORIZONS_FOCUS:
        print(f"    would_buy T+{h}: {report_b['by_stage_horizon']['would_buy'][f'T+{h}']}")

    return {"window": window_label, "scenario_a_current_alpha": report_a, "scenario_b_new_alpha": report_b}


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
    first_half, second_half = _split_first_second_half(all_rows)

    print("\n=== 현행 alpha layer vs regime_conditional_signal — BUY funnel 비교 ===")
    print(f"전체 3년 표본: {len(all_rows)}건, 최근 12개월(cutoff={cutoff}) 표본: {len(recent_rows)}건")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_rows),
        "total_rolling_samples_recent_12m": len(recent_rows),
        "recent_window_cutoff": cutoff,
        "watch_top_k_buy": WATCH_TOP_K_BUY,
        "windows": {},
    }

    report["windows"]["supplementary_3y"] = _analyze_window(all_rows, "2차(3년, 전체 표본)")
    report["windows"]["primary_recent_12m"] = _analyze_window(recent_rows, "1차(최근 12개월)")
    report["windows"]["3y_first_half"] = _analyze_window(first_half, "3년 전반부")
    report["windows"]["3y_second_half"] = _analyze_window(second_half, "3년 후반부")

    out_path = "logs/signal_ic_alpha_layer_buy_funnel_comparison_2026-07-16.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
