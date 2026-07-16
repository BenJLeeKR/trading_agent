#!/usr/bin/env python3
"""SPPV-2.28 — alpha layer 교체안 virtual BUY funnel 확장 검증
(candidate→eligible→selected(buy_candidate)→would_buy(submitted proxy)
→blocked), read-only.

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §17.5(다음
단계) 참고. §17(SPPV-2.27)은 candidate→eligible→would_buy(top-K)→
blocked 4단계에서 새 alpha가 4개 창·2개 horizon 전부(8/8)에서
현행보다 나음을 확인했다(Conditional Go 보강, 확정 Go는 아님). 이번
스크립트는 그 "would_buy"를 실제 운영 판단 경로에 한 단계 더
가깝게 확장한다 — **broker submit은 절대 호출하지 않고**, 이미
운영 중인 코드(`assess_deterministic_triggers()`가 실제로 쓰는
`buy_candidate_threshold=0.65` 상수, `deterministic_trigger_engine.
py:89`)를 그대로 재사용해 "결정론적 엔진이 실제로 BUY_CANDIDATE로
분류하는 조건"을 재현한다.

funnel 5단계(모두 기존 운영 코드/상수 재사용, 새 로직 없음):
  1. **candidate**: 그날 cross-sectional 상위 20%(quintile, 시나리오
     별 alpha 기준) — §12/§13/§17과 동일 정의.
  2. **eligible**: 운영 함수 `_assess_buy_eligibility()` 그대로
     (alpha와 무관, 이번 턴의 조작 대상 아님 — 보조 지표로만 관찰).
  3. **selected(buy_candidate)**: `assess_deterministic_triggers()`가
     실제로 쓰는 조건 `eligible AND entry_score >= 0.65(운영 상수
     buy_candidate_threshold) AND allocation_budget_ok(=True,
     세션 전체의 shadow 관례)`를 그대로 재현 — 이것이 결정론적
     엔진이 실제로 "매수 후보"로 표시하는 시점이다.
  4. **would_buy(virtual submitted proxy)**: selected 중 그날
     entry_score 상위 `WATCH_TOP_K_BUY=3`(`trigger_proxy_
     attribution.py:38`, 실제 운영 하루 매수 후보 cap을 그대로
     재사용) — 이 이후 단계(FDC AI 판단, compliance/guardrail,
     broker submit)는 실시간 상태·LLM 판단을 요구해 과거 데이터
     만으로 재현할 수 없으므로(Phase 0/1-3 경계, 이 세션 전체에서
     일관되게 적용해온 원칙) 여기서 멈춘다 — 이 지점이 이번
     검증에서 "실제 주문경로에 가장 가깝게 재구성 가능한 지점"이다.
  5. **blocked**: 두 세부 사유로 분리한다 —
     `blocked_by_eligibility`(candidate이지만 eligible 아님),
     `blocked_by_score_threshold`(eligible이지만 entry_score<0.65).

각 단계에 대해 표본 수·전환율과 함께 T+5/T+20 forward return
(평균/Newey-West t/양수 비율)뿐 아니라 **MFE/MAE**(각 horizon 내
고가/저가 기준 최대 유리·불리 이탈폭, `validate_signal_predictive_
power_v2.py`의 기존 계산 패턴 재사용)까지 계측한다. 2차(3년)/1차
(최근 12개월)/전반부/후반부 4개 창 모두 반복한다.

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
logger = logging.getLogger("validate_alpha_layer_virtual_buy_funnel_extended")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_activity_filter_threshold_sweep import _split_first_second_half  # noqa: E402
from validate_alpha_layer_buy_funnel_comparison import (  # noqa: E402
    _ALPHA_W_FAST,
    _ALPHA_W_NEW_SIGNAL,
    _ALPHA_W_OVERALL,
    _ALPHA_W_SLOW,
    _clamp01,
    _entry_score_non_alpha_terms,
    _normalize_signed_score,
    WATCH_TOP_K_BUY,
)
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

# 운영 상수 그대로 재사용(deterministic_trigger_engine.py:89)
BUY_CANDIDATE_THRESHOLD = 0.65


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

        non_alpha_b, _ = _entry_score_non_alpha_terms(per_symbol_regime, snapshot)
        if regime_conditional_signal is not None:
            entry_score_b = _clamp01(
                _ALPHA_W_NEW_SIGNAL * _normalize_signed_score(regime_conditional_signal) + non_alpha_b
            )
        else:
            entry_score_b = None

        # 운영 함수 assess_deterministic_triggers()가 실제로 쓰는
        # BUY_CANDIDATE 조건(eligibility_passed AND entry_score>=0.65
        # AND allocation_budget_ok) 그대로 재현.
        buy_candidate_a = bool(eligible and entry_score_a >= BUY_CANDIDATE_THRESHOLD)
        buy_candidate_b = bool(eligible and entry_score_b is not None and entry_score_b >= BUY_CANDIDATE_THRESHOLD)

        base_close = bars[t].close_price
        row: dict = {
            "symbol": symbol,
            "trade_date": trade_date,
            "market_common_regime": market_common_label,
            "current_alpha_composite": current_alpha_composite,
            "regime_conditional_signal": regime_conditional_signal,
            "eligible": eligible,
            "entry_score_a": entry_score_a,
            "entry_score_b": entry_score_b,
            "buy_candidate_a": buy_candidate_a,
            "buy_candidate_b": buy_candidate_b,
        }
        for h in FORWARD_HORIZONS_FOCUS:
            fwd_bars = bars[t + 1 : t + h + 1]
            fwd_close = bars[t + h].close_price
            raw_ret = (fwd_close / base_close) - 1.0
            row[f"fwd_{h}"] = raw_ret
            row[f"fwd_{h}_net"] = raw_ret - (_ROUND_TRIP_COST_BPS / 10_000.0)
            if fwd_bars:
                row[f"mfe_{h}"] = max((b.high_price / base_close) - 1.0 for b in fwd_bars)
                row[f"mae_{h}"] = min((b.low_price / base_close) - 1.0 for b in fwd_bars)
            else:
                row[f"mfe_{h}"] = row[f"mae_{h}"] = raw_ret

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


def _mfe_mae_summary(rows: list[dict], h: int) -> dict:
    if not rows:
        return {"n": 0}
    return {
        "n": len(rows),
        "mfe_mean_pct": round(_mean([r[f"mfe_{h}"] for r in rows]) * 100, 4),
        "mae_mean_pct": round(_mean([r[f"mae_{h}"] for r in rows]) * 100, 4),
    }


def _funnel_for_scenario(rows: list[dict], signal_key: str, buy_candidate_key: str, entry_score_key: str) -> dict:
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get(signal_key) is not None:
            by_date[r["trade_date"]].append(r)

    candidates: list[dict] = []
    eligible_rows: list[dict] = []
    selected_rows: list[dict] = []  # buy_candidate(threshold 통과)
    would_buy_rows: list[dict] = []  # top-K/day 캡 적용(virtual submitted proxy)
    blocked_by_eligibility: list[dict] = []
    blocked_by_score_threshold: list[dict] = []

    for day_rows in by_date.values():
        if len(day_rows) < 5:
            continue
        ordered = sorted(day_rows, key=lambda r: r[signal_key], reverse=True)
        q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
        day_candidates = ordered[:q]
        candidates.extend(day_candidates)

        for r in day_candidates:
            if not r["eligible"]:
                blocked_by_eligibility.append(r)
                continue
            eligible_rows.append(r)
            if r[buy_candidate_key]:
                selected_rows.append(r)
            else:
                blocked_by_score_threshold.append(r)

        day_selected_ranked = sorted(
            [r for r in day_candidates if r[buy_candidate_key] and r.get(entry_score_key) is not None],
            key=lambda r: r[entry_score_key],
            reverse=True,
        )
        would_buy_rows.extend(day_selected_ranked[:WATCH_TOP_K_BUY])

    return {
        "candidate": candidates,
        "eligible": eligible_rows,
        "selected": selected_rows,
        "would_buy": would_buy_rows,
        "blocked_by_eligibility": blocked_by_eligibility,
        "blocked_by_score_threshold": blocked_by_score_threshold,
    }


def _funnel_report(funnel: dict) -> dict:
    n_candidate = len(funnel["candidate"])
    n_eligible = len(funnel["eligible"])
    n_selected = len(funnel["selected"])
    n_would_buy = len(funnel["would_buy"])

    report: dict = {
        "candidate_n": n_candidate,
        "eligible_n": n_eligible,
        "selected_n": n_selected,
        "would_buy_n": n_would_buy,
        "blocked_by_eligibility_n": len(funnel["blocked_by_eligibility"]),
        "blocked_by_score_threshold_n": len(funnel["blocked_by_score_threshold"]),
        "eligible_rate_of_candidate": round(n_eligible / max(n_candidate, 1) * 100, 2),
        "selected_rate_of_eligible": round(n_selected / max(n_eligible, 1) * 100, 2),
        "selected_rate_of_candidate": round(n_selected / max(n_candidate, 1) * 100, 2),
        "would_buy_rate_of_selected": round(n_would_buy / max(n_selected, 1) * 100, 2),
        "by_stage_horizon": {},
        "mfe_mae_by_stage_horizon": {},
    }
    for stage_name, stage_rows in (
        ("candidate", funnel["candidate"]),
        ("eligible", funnel["eligible"]),
        ("selected", funnel["selected"]),
        ("would_buy", funnel["would_buy"]),
    ):
        report["by_stage_horizon"][stage_name] = {}
        report["mfe_mae_by_stage_horizon"][stage_name] = {}
        for h in FORWARD_HORIZONS_FOCUS:
            report["by_stage_horizon"][stage_name][f"T+{h}"] = _summarize([r[f"fwd_{h}"] for r in stage_rows], h)
            report["mfe_mae_by_stage_horizon"][stage_name][f"T+{h}"] = _mfe_mae_summary(stage_rows, h)
    return report


def _analyze_window(rows: list[dict], window_label: str) -> dict:
    print(f"\n=== {window_label} (표본 {len(rows)}건) ===")

    funnel_a = _funnel_for_scenario(rows, "current_alpha_composite", "buy_candidate_a", "entry_score_a")
    funnel_b = _funnel_for_scenario(rows, "regime_conditional_signal", "buy_candidate_b", "entry_score_b")

    report_a = _funnel_report(funnel_a)
    report_b = _funnel_report(funnel_b)

    for label, report in (("A(현행)", report_a), ("B(신규)", report_b)):
        print(f"  [시나리오 {label}] candidate={report['candidate_n']}, "
              f"eligible={report['eligible_n']}({report['eligible_rate_of_candidate']}%), "
              f"selected(0.65 통과)={report['selected_n']}({report['selected_rate_of_eligible']}% of eligible), "
              f"would_buy(top-{WATCH_TOP_K_BUY}/일)={report['would_buy_n']}, "
              f"blocked_eligibility={report['blocked_by_eligibility_n']}, "
              f"blocked_score={report['blocked_by_score_threshold_n']}")
        for h in FORWARD_HORIZONS_FOCUS:
            wb = report["by_stage_horizon"]["would_buy"][f"T+{h}"]
            mm = report["mfe_mae_by_stage_horizon"]["would_buy"][f"T+{h}"]
            print(f"    would_buy T+{h}: {wb} | MFE/MAE: {mm}")

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

    print("\n=== alpha layer 교체 — virtual BUY funnel 확장 검증(candidate→eligible→selected→would_buy) ===")
    print(f"전체 3년 표본: {len(all_rows)}건, 최근 12개월(cutoff={cutoff}) 표본: {len(recent_rows)}건")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_rows),
        "total_rolling_samples_recent_12m": len(recent_rows),
        "recent_window_cutoff": cutoff,
        "buy_candidate_threshold": BUY_CANDIDATE_THRESHOLD,
        "watch_top_k_buy": WATCH_TOP_K_BUY,
        "windows": {},
    }

    report["windows"]["supplementary_3y"] = _analyze_window(all_rows, "2차(3년, 전체 표본)")
    report["windows"]["primary_recent_12m"] = _analyze_window(recent_rows, "1차(최근 12개월)")
    report["windows"]["3y_first_half"] = _analyze_window(first_half, "3년 전반부")
    report["windows"]["3y_second_half"] = _analyze_window(second_half, "3년 후반부")

    out_path = "logs/signal_ic_alpha_layer_virtual_buy_funnel_extended_2026-07-16.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
