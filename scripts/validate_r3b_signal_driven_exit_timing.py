#!/usr/bin/env python3
"""SPPV-2.52 — T+5 horizon 구조적 리스크 추가 정량화: 실제 exit_score
로직을 이용한 signal-driven 청산 타이밍 shadow 시뮬레이션(read-only,
broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §38(SPPV-2.48)
§40(SPPV-2.50)의 보조 잔여 조건 3개 중 "T+5 horizon 구조적 리스크"를
이번 턴에 전진시킨다.

**배경**: 이 시스템에는 강제된 보유기간이 없다(§31/§41에서 이미 확인
— ``max_holding_days=20`` 은 LLM 힌트일 뿐 어떤 코드 경로도 이를 읽어
강제 청산하지 않는다). 실제 SELL/청산 여부는 100% `_build_exit_score`
(`deterministic_trigger_engine.py`)의 값이 `sell_candidate_threshold`
(0.75) 를 넘는지에 달려 있다. 그런데 지금까지의 모든 검증은 T+5·T+20
"고정 시계"의 평균 수익률만 측정해왔다 — 실제 운영에서 포지션이 며칠
만에 청산될지(그리고 그 청산 시점의 실현 수익률이 T+5/T+20 중 무엇에
더 가까운지)는 한 번도 직접 시뮬레이션되지 않았다.

**이번 턴이 고른 방법**: R3b + entry_score risk_off_penalty 제거(B
시나리오)의 would_buy candidate 각각에 대해, 실제 운영 함수
`_build_exit_score`를 매일 point-in-time으로 재호출해 "언제 처음
sell_candidate_threshold(0.75)를 넘는가"를 찾는다(최대 20거래일
관찰, 넘지 않으면 T+20에서 censored 처리). 이 "signal-driven 청산
시점"의 실현 수익률 분포를 T+5·T+20 고정 시계와 비교한다 — 이는
"T+5가 너무 이르다"는 우려가 실제 청산 로직 관점에서도 타당한지를
직접 검증하는 가장 직접적인 방법이다.

가정(전부 문서화): position_snapshot은 보유 중(quantity=1)으로 고정,
portfolio_allocation=None(§32 gap, 실거래 전까지 시뮬레이션 불가 —
기존과 동일 가정), source_type="held_position"(매수 이후 보유 중
포지션 모니터링 관례를 반영). market_regime은 각 시점의 실제
`classify_market_regime` 결과를 그대로 사용(운영 코드 미변경).

DB write / 주문 경로 / 실시간 구독 / broker submit 없음.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import sys as _sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_r3b_signal_driven_exit_timing")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_alpha_layer_buy_funnel_comparison import _ALPHA_W_NEW_SIGNAL, _clamp01  # noqa: E402
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK, _mean, _newey_west_se_of_mean  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

TOP_QUINTILE_FRACTION = 0.20
BUY_CANDIDATE_THRESHOLD = 0.65
WATCH_TOP_K_BUY = 3
_STRATEGY_ALIGNMENT_BONUS = 0.05
_STRATEGY_ALIGNMENT_SET = {"swing_momentum", "event_continuation"}
SELL_CANDIDATE_THRESHOLD = 0.75
MAX_EXIT_OBSERVATION_DAYS = 20
FIXED_HORIZONS = (5, 20)

_HELD_POSITION = SimpleNamespace(
    position_snapshot_id=uuid4(), account_id=uuid4(), instrument_id=uuid4(),
    quantity=Decimal("1"), average_price=Decimal("1"), market_price=None,
    unrealized_pnl=None, source_of_truth="shadow_sim", snapshot_at=datetime.now(_KST),
    purchase_amount=None, evaluation_amount=None, created_at=None,
    fetch_status="success", snapshot_sync_run_id=None,
)


def _collect_rows(symbol: str, bars: list, market_common_regime_by_date: dict[str, str]) -> list[dict]:
    from agent_trading.services.deterministic_trigger_engine import (
        _assess_buy_eligibility,
        _build_exit_score,
        _build_relative_activity_score,
    )
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot
    from agent_trading.services.strategy_selection import select_strategy

    rows: list[dict] = []
    last_t = len(bars) - 1 - MAX_EXIT_OBSERVATION_DAYS
    if last_t < _MIN_LOOKBACK - 1:
        return rows

    snapshot_cache: dict[int, tuple] = {}

    def _snapshot_at(t: int):
        if t in snapshot_cache:
            return snapshot_cache[t]
        window = bars[: t + 1]
        try:
            features, card = build_signal_snapshot(symbol, window)
        except Exception:
            snapshot_cache[t] = None
            return None
        overall, fast, slow = float(card.overall_score), float(card.fast_score), float(card.slow_score)
        snap = SimpleNamespace(
            overall_score=overall, fast_score=fast, slow_score=slow,
            return_1m_pct=features.return_1m_pct, return_3m_pct=features.return_3m_pct,
            price_vs_sma_20_pct=features.price_vs_sma_20_pct, price_vs_sma_60_pct=features.price_vs_sma_60_pct,
            volatility_20d_pct=features.volatility_20d_pct, atr_14_pct=features.atr_14_pct,
            volume_surge_ratio=features.volume_surge_ratio, average_volume_20d=features.average_volume_20d,
            average_turnover_20d=features.average_turnover_20d, turnover_surge_ratio=features.turnover_surge_ratio,
            rsi_14=features.rsi_14, sma_5=features.sma_5, sma_20=features.sma_20, sma_60=features.sma_60,
            component_scores_json=None,
        )
        per_symbol_regime = classify_market_regime(snap)
        result = (snap, per_symbol_regime, overall, fast, slow)
        snapshot_cache[t] = result
        return result

    for t in range(_MIN_LOOKBACK - 1, last_t + 1):
        entry = _snapshot_at(t)
        if entry is None:
            continue
        snapshot, per_symbol_regime, overall, fast, slow = entry
        neutral_regime = dataclasses.replace(per_symbol_regime, risk_tone="neutral") if per_symbol_regime else None
        strategy_selection = select_strategy(market_regime=per_symbol_regime, source_type="core")

        trade_date = bars[t].timestamp.strftime("%Y-%m-%d")
        market_common_label = market_common_regime_by_date.get(trade_date)

        ret3m, ret1m, vol = snapshot.return_3m_pct, snapshot.return_1m_pct, snapshot.volatility_20d_pct
        risk_adj_momentum_3m = (ret3m / max(vol, 1.0)) if (ret3m is not None and vol is not None) else None
        reversal_1m = (-ret1m) if ret1m is not None else None
        regime_conditional_signal = None
        if market_common_label in ("bullish_trend", "range_bound"):
            regime_conditional_signal = risk_adj_momentum_3m
        elif market_common_label == "bearish_trend":
            regime_conditional_signal = reversal_1m

        eligible, _ = _assess_buy_eligibility(
            source_type="core", coverage_score=1.0, allocation_budget_ok=True,
            market_regime=per_symbol_regime, overall=overall, slow=slow,
            signal_feature_snapshot=snapshot, portfolio_allocation=None, ranking_score=None,
        )

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
            bonus = _build_relative_activity_score(snapshot)
            if bonus > 0:
                score += min(0.10, bonus * 0.10)
            return score

        non_alpha_b_scenario = _non_alpha(neutral_regime)
        base_close = bars[t].close_price

        row: dict = {
            "symbol": symbol, "trade_date": trade_date,
            "regime_conditional_signal": regime_conditional_signal,
            "non_alpha_b_scenario": non_alpha_b_scenario,
            "eligible": eligible,
            "entry_t": t,
        }
        for h in FIXED_HORIZONS:
            fwd_close = bars[t + h].close_price
            row[f"fwd_{h}"] = (fwd_close / base_close) - 1.0

        exit_day_offset = None
        exit_reason_codes: list[str] = []
        for offset in range(1, MAX_EXIT_OBSERVATION_DAYS + 1):
            fwd_t = t + offset
            fwd_snap = _snapshot_at(fwd_t)
            if fwd_snap is None:
                continue
            _, fwd_regime, fwd_overall, fwd_fast, fwd_slow = fwd_snap
            reason_codes: list[str] = []
            exit_score = _build_exit_score(
                overall=fwd_overall, fast=fwd_fast, slow=fwd_slow,
                market_regime=fwd_regime, portfolio_allocation=None,
                position_snapshot=_HELD_POSITION, source_type="held_position",
                reason_codes=reason_codes,
            )
            if exit_score >= SELL_CANDIDATE_THRESHOLD:
                exit_day_offset = offset
                exit_reason_codes = reason_codes
                break

        if exit_day_offset is not None:
            exit_close = bars[t + exit_day_offset].close_price
            row["exit_offset"] = exit_day_offset
            row["exit_censored"] = False
            row["exit_return"] = (exit_close / base_close) - 1.0
            row["exit_reason_codes"] = exit_reason_codes
        else:
            row["exit_offset"] = MAX_EXIT_OBSERVATION_DAYS
            row["exit_censored"] = True
            row["exit_return"] = row["fwd_20"]
            row["exit_reason_codes"] = []

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


def _score_b(row: dict) -> float | None:
    if row.get("candidate_percentile") is None:
        return None
    return _clamp01(_ALPHA_W_NEW_SIGNAL * row["candidate_percentile"] + row["non_alpha_b_scenario"])


def _would_buy_rows(rows: list[dict]) -> list[dict]:
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["regime_conditional_signal"] is not None:
            by_date[r["trade_date"]].append(r)

    would_buy_rows: list[dict] = []
    for day_rows in by_date.values():
        if len(day_rows) < 5:
            continue
        ordered = sorted(day_rows, key=lambda r: r["regime_conditional_signal"], reverse=True)
        q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
        day_candidates = ordered[:q]
        day_selected_ranked = []
        for r in day_candidates:
            if r.get("candidate_percentile") is None or not r["eligible"]:
                continue
            score = _score_b(r)
            if score is not None and score >= BUY_CANDIDATE_THRESHOLD:
                day_selected_ranked.append((r, score))
        day_selected_ranked.sort(key=lambda pair: pair[1], reverse=True)
        would_buy_rows.extend(r for r, _ in day_selected_ranked[:WATCH_TOP_K_BUY])
    return would_buy_rows


def _stats(xs: list[float], lag_hint: int) -> dict:
    if len(xs) < 5:
        return {"n": len(xs), "note": "표본부족"}
    m = _mean(xs)
    nw_se = _newey_west_se_of_mean(xs, lag=max(lag_hint - 1, 1))
    t_nw = (m / nw_se) if nw_se else None
    return {
        "n": len(xs), "mean_pct": round(m * 100, 4),
        "t_newey_west": round(t_nw, 2) if t_nw else None,
        "pct_positive": round(sum(1 for x in xs if x > 0) / len(xs), 4),
        "total_return_proxy": round(len(xs) * m * 100, 1),
    }


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
        if len(bars) < _MIN_LOOKBACK + MAX_EXIT_OBSERVATION_DAYS + 5:
            fetch_failures.append(symbol)
            continue
        rows = _collect_rows(symbol, bars, market_common_regime_by_date)
        all_rows.extend(rows)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_rows))

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_rows), len(fetch_failures))
    _attach_candidate_percentile(all_rows)
    would_buy_rows = _would_buy_rows(all_rows)
    logger.info("would_buy 표본 %d건", len(would_buy_rows))

    offset_hist: dict[str, int] = defaultdict(int)
    for r in would_buy_rows:
        off = r["exit_offset"]
        if r["exit_censored"]:
            bucket = "censored(T+20 도달, 미청산)"
        elif off <= 5:
            bucket = "1~5일"
        elif off <= 10:
            bucket = "6~10일"
        elif off <= 15:
            bucket = "11~15일"
        else:
            bucket = "16~20일"
        offset_hist[bucket] += 1

    print("\n=== signal-driven 청산 타이밍 시뮬레이션 (B 시나리오, would_buy 후보) ===")
    print(f"표본 수: {len(would_buy_rows)}")
    print(f"청산 시점 분포: {dict(offset_hist)}")

    t5_stats = _stats([r["fwd_5"] for r in would_buy_rows], lag_hint=5)
    t20_stats = _stats([r["fwd_20"] for r in would_buy_rows], lag_hint=20)
    exit_stats = _stats([r["exit_return"] for r in would_buy_rows], lag_hint=10)
    mean_offset = round(_mean([r["exit_offset"] for r in would_buy_rows]), 2) if would_buy_rows else None
    censored_n = sum(1 for r in would_buy_rows if r["exit_censored"])
    censored_rate = round(censored_n / len(would_buy_rows), 4) if would_buy_rows else None

    print(f"T+5(고정): {t5_stats}")
    print(f"T+20(고정): {t20_stats}")
    print(f"signal-driven 청산(실제 exit_score 기반): {exit_stats}")
    print(f"평균 보유일수: {mean_offset}, censored(20일 내 미청산) 비율: {censored_rate}")

    report = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "sell_candidate_threshold": SELL_CANDIDATE_THRESHOLD,
        "max_exit_observation_days": MAX_EXIT_OBSERVATION_DAYS,
        "would_buy_n": len(would_buy_rows),
        "exit_offset_distribution": dict(offset_hist),
        "mean_holding_days": mean_offset,
        "censored_rate": censored_rate,
        "fixed_T5": t5_stats,
        "fixed_T20": t20_stats,
        "signal_driven_exit": exit_stats,
    }
    out_path = "logs/signal_ic_r3b_signal_driven_exit_timing_2026-07-18.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
