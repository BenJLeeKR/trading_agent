#!/usr/bin/env python3
"""SPPV-2.46 — R3b 채택 시 `risk_off_penalty` 중복 해소 ablation
(read-only, broker submit 없음, 운영 코드 미수정).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §3(SPPV-3
착수 조건) 및 §8(활동성 필터 ablation 방법론) 참고.

§3은 SPPV-3(창 교체 본작업) 착수 전제조건으로 "①§21 게이트
TRIGGERED 전환"과 "②`risk_off_penalty`와 `regime_conditional_
signal`의 하락장 분기 로직 간 의미 중복 해소"를 명시해왔다. ①은
시장 상황 의존적 외생 변수이므로(§34/§2.44에서 이미 NOT_TRIGGERED
재확인, 이번 턴은 건드리지 않음), 이번 턴은 ②만 다룬다.

**코드 조사로 확정한 사실(신규 실측 이전에 먼저 고정)**:
1. `entry_score`의 국면 조정항(`deterministic_trigger_engine.
   _build_entry_score:1139-1141`) — `market_regime.risk_tone ==
   "risk_off"`이면 `score -= 0.15`(reason `trigger_risk_off_
   penalty`). 이것이 문서가 "risk_off_penalty"라 불러온 축이다.
2. `_assess_buy_eligibility`(같은 파일:421-438)에 **별도의 독립된
   억제 축**이 있다 — `risk_tone=="risk_off"` **그리고**
   `regime_label=="bearish_trend"`이면 core 종목은 예외
   (`risk_off_exception_eligible`) 없이 즉시 차단(`eligibility_
   risk_off_block`/`eligibility_core_risk_off_guard_blocked`).
   entry_score의 -0.15 조정항과는 다른 함수, 다른 단계(eligible
   단계 자체를 막음)다.
3. 두 축 모두 `classify_market_regime()`(같은 정책 함수)의 결과를
   쓰지만, **입력이 다르다** — entry_score/eligibility는 **종목별
   개별 스냅샷**으로 이 함수를 호출하고, `regime_conditional_
   signal`의 하락장 분기(`reversal_1m`)는 **시장 공통(벤치마크
   KODEX 200) 국면**으로 갈린다. 즉 "같은 판정 로직, 다른 기준
   단위"라는 것이 중복의 정확한 성격이다.

이번 턴은 R3b(alpha layer 후보)를 alpha 항에 넣은 상태에서, 이
**entry_score 축(1번)**과 **eligibility 축(2번)** 중 어느 쪽이
실제로 R3b의 기대수익을 깎는 진짜 병목인지, 아니면 유지해야 할
정당한 방어 장치인지를 다음 3개 시나리오로 분리 계측한다:

  - **A(현행 유지)**: 두 축 모두 실제 운영 로직 그대로.
  - **B(entry_score risk_off_penalty만 무력화)**: eligibility
    축은 그대로 두고, entry_score 계산에 넘기는 `market_regime`만
    `risk_tone`을 중립화(dataclasses.replace)해 -0.15 조정항이
    걸리지 않게 한다 — **운영 코드를 수정하지 않고, 입력만 다르게
    구성**하는 것으로 재현한다(이 세션 전체의 일관된 shadow 관례).
  - **C(eligibility risk_off 축만 완화)**: entry_score는 그대로
    (risk_off_penalty 유지), `_assess_buy_eligibility`에 넘기는
    `market_regime`만 중립화해 `eligibility_risk_off_block`/
    `eligibility_core_risk_off_guard_blocked`이 걸리지 않게 한다.

candidate→eligible→selected→would_buy funnel을 3년 rolling(2차)과
최근 12개월(1차) 두 창에서 계측한다. DB write / 주문 경로 / 실시간
구독 / broker submit 없음. 실제 KIS 호출 여부는 로그의 `HTTP
Request:` 카운트로 그대로 보고한다.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import sys as _sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_r3b_risk_off_penalty_duplication_ablation")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_activity_filter_threshold_sweep import _split_first_second_half  # noqa: E402
from validate_alpha_layer_buy_funnel_comparison import (  # noqa: E402
    _ALPHA_W_NEW_SIGNAL,
    _clamp01,
    _normalize_signed_score,
)
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK, _mean, _newey_west_se_of_mean, _stdev  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

RECENT_WINDOW_CALENDAR_DAYS = 365
TOP_QUINTILE_FRACTION = 0.20
BUY_CANDIDATE_THRESHOLD = 0.65
WATCH_TOP_K_BUY = 3
_STRATEGY_ALIGNMENT_BONUS = 0.05
_STRATEGY_ALIGNMENT_SET = {"swing_momentum", "event_continuation"}


def _neutralize_risk_off(market_regime):
    """운영 코드를 수정하지 않고, 함수에 넘기는 market_regime 입력만
    risk_tone을 중립화한 복사본을 만든다(frozen dataclass, 실제
    classify_market_regime 결과 그대로 복제 후 risk_tone만 교체)."""
    if market_regime is None:
        return None
    return dataclasses.replace(market_regime, risk_tone="neutral")


def _collect_rows(symbol: str, bars: list, market_common_regime_by_date: dict[str, str]) -> list[dict]:
    from agent_trading.services.deterministic_trigger_engine import (
        _assess_buy_eligibility,
        _build_entry_score,
    )
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot
    from agent_trading.services.strategy_selection import select_strategy

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
            overall_score=overall, fast_score=fast, slow_score=slow,
            return_1m_pct=features.return_1m_pct, return_3m_pct=features.return_3m_pct,
            price_vs_sma_20_pct=features.price_vs_sma_20_pct, price_vs_sma_60_pct=features.price_vs_sma_60_pct,
            volatility_20d_pct=features.volatility_20d_pct, atr_14_pct=features.atr_14_pct,
            volume_surge_ratio=features.volume_surge_ratio, average_volume_20d=features.average_volume_20d,
            average_turnover_20d=features.average_turnover_20d, turnover_surge_ratio=features.turnover_surge_ratio,
            rsi_14=features.rsi_14, sma_5=features.sma_5, sma_20=features.sma_20, sma_60=features.sma_60,
            component_scores_json=None,
        )
        per_symbol_regime = classify_market_regime(snapshot)
        neutral_regime = _neutralize_risk_off(per_symbol_regime)
        strategy_selection = select_strategy(market_regime=per_symbol_regime, source_type="core")

        trade_date = bars[t].timestamp.strftime("%Y-%m-%d")
        market_common_label = market_common_regime_by_date.get(trade_date)

        ret3m, ret1m, vol = features.return_3m_pct, features.return_1m_pct, features.volatility_20d_pct
        risk_adj_momentum_3m = (ret3m / max(vol, 1.0)) if (ret3m is not None and vol is not None) else None
        reversal_1m = (-ret1m) if ret1m is not None else None
        regime_conditional_signal = None
        if market_common_label in ("bullish_trend", "range_bound"):
            regime_conditional_signal = risk_adj_momentum_3m
        elif market_common_label == "bearish_trend":
            regime_conditional_signal = reversal_1m

        # eligible: A/B는 실제 market_regime, C는 risk_off 중립화
        eligible_normal, _ = _assess_buy_eligibility(
            source_type="core", coverage_score=1.0, allocation_budget_ok=True,
            market_regime=per_symbol_regime, overall=overall, slow=slow,
            signal_feature_snapshot=snapshot, portfolio_allocation=None, ranking_score=None,
        )
        eligible_c, _ = _assess_buy_eligibility(
            source_type="core", coverage_score=1.0, allocation_budget_ok=True,
            market_regime=neutral_regime, overall=overall, slow=slow,
            signal_feature_snapshot=snapshot, portfolio_allocation=None, ranking_score=None,
        )

        # entry_score의 non-alpha 조정항: A/C는 실제 market_regime, B는 risk_off 중립화
        # (alpha 항은 R3b 방식: 0.80 * candidate_percentile, non_alpha는 real _build_entry_score의
        #  나머지 조정과 동일하게 별도 함수로 재구성 — 이 세션의 기존 관례를 그대로 재사용)
        def _non_alpha(regime_obj) -> float:
            score = 0.0
            if regime_obj is not None:
                if regime_obj.regime_label == "bullish_trend":
                    score += 0.10
                if regime_obj.risk_tone == "risk_on":
                    score += 0.05
                if regime_obj.risk_tone == "risk_off":
                    score -= 0.15
            if strategy_selection is not None and strategy_selection.preferred_strategy in _STRATEGY_ALIGNMENT_SET:
                score += _STRATEGY_ALIGNMENT_BONUS
            from agent_trading.services.deterministic_trigger_engine import _build_relative_activity_score
            relative_activity_bonus = _build_relative_activity_score(snapshot)
            if relative_activity_bonus > 0:
                score += min(0.10, relative_activity_bonus * 0.10)
            return score

        non_alpha_a = _non_alpha(per_symbol_regime)
        non_alpha_b_ablated = _non_alpha(neutral_regime)

        base_close = bars[t].close_price
        row: dict = {
            "symbol": symbol, "trade_date": trade_date,
            "regime_conditional_signal": regime_conditional_signal,
            "non_alpha_a": non_alpha_a, "non_alpha_b_ablated": non_alpha_b_ablated,
            "eligible_normal": eligible_normal, "eligible_c": eligible_c,
        }
        for h in FORWARD_HORIZONS_FOCUS:
            fwd_close = bars[t + h].close_price
            fwd_bars = bars[t + 1 : t + h + 1]
            raw_ret = (fwd_close / base_close) - 1.0
            row[f"fwd_{h}"] = raw_ret
            if fwd_bars:
                row[f"mfe_{h}"] = max((b.high_price / base_close) - 1.0 for b in fwd_bars)
                row[f"mae_{h}"] = min((b.low_price / base_close) - 1.0 for b in fwd_bars)
            else:
                row[f"mfe_{h}"] = row[f"mae_{h}"] = raw_ret
        rows.append(row)
    return rows


def _attach_candidate_percentile(rows: list[dict]) -> None:
    import bisect
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["regime_conditional_signal"] is not None:
            by_date[r["trade_date"]].append(r)
    for day_rows in by_date.values():
        if len(day_rows) < 5:
            for r in day_rows:
                r["candidate_percentile"] = None
            continue
        ordered = sorted(day_rows, key=lambda r: r["regime_conditional_signal"], reverse=True)
        q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
        day_candidates = ordered[:q]
        cand_signals = sorted(r["regime_conditional_signal"] for r in day_candidates)
        n = len(cand_signals)
        for r in day_rows:
            if r not in day_candidates:
                r["candidate_percentile"] = None
                continue
            idx = bisect.bisect_left(cand_signals, r["regime_conditional_signal"])
            r["candidate_percentile"] = idx / (n - 1) if n > 1 else 0.5


SCENARIO_DEFS = {
    "A_baseline": {"eligible_key": "eligible_normal", "non_alpha_key": "non_alpha_a"},
    "B_remove_entry_score_penalty": {"eligible_key": "eligible_normal", "non_alpha_key": "non_alpha_b_ablated"},
    "C_relax_eligibility_block": {"eligible_key": "eligible_c", "non_alpha_key": "non_alpha_a"},
}


def _funnel_for_scenario(rows: list[dict], eligible_key: str, non_alpha_key: str) -> dict:
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["regime_conditional_signal"] is not None:
            by_date[r["trade_date"]].append(r)

    candidates, eligible_rows, selected_rows, would_buy_rows = [], [], [], []
    for day_rows in by_date.values():
        if len(day_rows) < 5:
            continue
        ordered = sorted(day_rows, key=lambda r: r["regime_conditional_signal"], reverse=True)
        q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
        day_candidates = ordered[:q]
        candidates.extend(day_candidates)

        day_selected_ranked = []
        for r in day_candidates:
            if r.get("candidate_percentile") is None or not r[eligible_key]:
                continue
            eligible_rows.append(r)
            score = _clamp01(_ALPHA_W_NEW_SIGNAL * r["candidate_percentile"] + r[non_alpha_key])
            if score >= BUY_CANDIDATE_THRESHOLD:
                selected_rows.append(r)
                day_selected_ranked.append((r, score))
        day_selected_ranked.sort(key=lambda pair: pair[1], reverse=True)
        would_buy_rows.extend(r for r, _ in day_selected_ranked[:WATCH_TOP_K_BUY])

    n_days_active = len({r["trade_date"] for r in would_buy_rows})
    report: dict = {
        "candidate_n": len(candidates), "eligible_n": len(eligible_rows),
        "selected_n": len(selected_rows), "would_buy_n": len(would_buy_rows),
        "selected_rate_of_eligible": round(len(selected_rows) / max(len(eligible_rows), 1) * 100, 2),
        "n_active_days": n_days_active,
        "would_buy_per_active_day": round(len(would_buy_rows) / n_days_active, 3) if n_days_active else None,
        "by_horizon": {},
    }
    for h in FORWARD_HORIZONS_FOCUS:
        xs = [r[f"fwd_{h}"] for r in would_buy_rows]
        if len(xs) < 5:
            report["by_horizon"][f"T+{h}"] = {"n": len(xs), "note": "표본부족"}
            continue
        m = _mean(xs)
        std = _stdev(xs)
        nw_se = _newey_west_se_of_mean(xs, lag=max(h - 1, 1))
        t_nw = (m / nw_se) if nw_se else None
        mfe = _mean([r[f"mfe_{h}"] for r in would_buy_rows])
        mae = _mean([r[f"mae_{h}"] for r in would_buy_rows])
        total_proxy = round(len(xs) * m * 100, 1)
        report["by_horizon"][f"T+{h}"] = {
            "n": len(xs), "mean_pct": round(m * 100, 4),
            "t_newey_west": round(t_nw, 2) if t_nw else None,
            "pct_positive": round(sum(1 for x in xs if x > 0) / len(xs), 4),
            "mfe_mean_pct": round(mfe * 100, 4), "mae_mean_pct": round(mae * 100, 4),
            "total_return_proxy": total_proxy,
        }
    return report


def _analyze_window(rows: list[dict], label: str) -> dict:
    print(f"\n=== {label} (표본 {len(rows)}건) ===")
    window_report: dict = {"label": label, "scenarios": {}}
    for skey, cfg in SCENARIO_DEFS.items():
        report = _funnel_for_scenario(rows, cfg["eligible_key"], cfg["non_alpha_key"])
        window_report["scenarios"][skey] = report
        print(f"  [{skey}] candidate={report['candidate_n']}, eligible={report['eligible_n']}, "
              f"selected={report['selected_n']}(rate={report['selected_rate_of_eligible']}%), "
              f"would_buy={report['would_buy_n']}(활동일당={report['would_buy_per_active_day']})")
        for h in FORWARD_HORIZONS_FOCUS:
            print(f"    T+{h}: {report['by_horizon'].get(f'T+{h}')}")
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
        rows = _collect_rows(symbol, bars, market_common_regime_by_date)
        all_rows.extend(rows)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_rows))

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_rows), len(fetch_failures))
    _attach_candidate_percentile(all_rows)

    last_date = max(datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in all_rows)
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    recent_rows = [r for r in all_rows if r["trade_date"] >= cutoff]

    print("\n=== R3b 채택 시 risk_off_penalty 중복 해소 ablation(A/B/C) ===")
    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "windows": {},
    }
    report["windows"]["supplementary_3y"] = _analyze_window(all_rows, "2차(3년, 전체 표본)")
    report["windows"]["primary_recent_12m"] = _analyze_window(recent_rows, "1차(최근 12개월)")

    out_path = "logs/signal_ic_r3b_risk_off_penalty_duplication_ablation_2026-07-17.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
