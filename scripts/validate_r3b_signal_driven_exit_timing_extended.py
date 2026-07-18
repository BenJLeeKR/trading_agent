#!/usr/bin/env python3
"""SPPV-2.53 — T+5 horizon 구조적 리스크의 20거래일 초과 구간·경로
리스크(MAE) 확장 검증(read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §41(SPPV-2.52)
가 20거래일 관찰 창으로 남긴 두 가지 미확인 영역을 이번 턴에 직접
검증한다: (a) 20거래일을 넘겨도 실제 청산은 여전히 늦게 일어나는가
(censored 비율이 관찰 창을 늘리면 실제로 줄어드는가), (b) 보유 기간
중 경로 리스크(MAE, 최대 미실현 손실 구간)가 커서 Conditional Go
판정을 흔들 정도인가.

**방법**: §41과 동일한 candidate 정의(R3b + entry_score
risk_off_penalty 제거, B 시나리오, would_buy 후보)를 그대로 재사용
하되, 관찰 창을 **20 → 60거래일**로 확장하고, 각 candidate에 대해
보유 시작일부터 청산일(또는 관찰 창 끝)까지의 **MAE(최대 미실현
손실 구간)**를 추가로 계산한다. §41의 스크립트를 그대로 복사해
2군데만 바꿨다: ``MAX_EXIT_OBSERVATION_DAYS=60``, 보유 구간 MAE
추적 로직 추가. 청산 로직(`_build_exit_score`, 실제 임계값 0.75)과
would_buy candidate 선정 로직은 §41과 완전히 동일 — 운영 코드 변경
없음.

가정(§41과 동일, 전부 문서화): position_snapshot 보유 중(quantity=1)
고정, portfolio_allocation=None(§32 gap, 실거래 전까지 시뮬레이션
불가), source_type="held_position". market_regime은 각 시점 실제
`classify_market_regime` 결과 사용.

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
logger = logging.getLogger("validate_r3b_signal_driven_exit_timing_extended")

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
MAX_EXIT_OBSERVATION_DAYS = 60  # §41(20일) → 이번 턴 60일로 확장
FIXED_HORIZONS = (5, 20)

_HELD_POSITION = SimpleNamespace(
    position_snapshot_id=uuid4(), account_id=uuid4(), instrument_id=uuid4(),
    quantity=Decimal("1"), average_price=Decimal("1"), market_price=None,
    unrealized_pnl=None, source_of_truth="shadow_sim", snapshot_at=datetime.now(_KST),
    purchase_amount=None, evaluation_amount=None, created_at=None,
    fetch_status="success", snapshot_sync_run_id=None,
)


def _entry_scan(symbol: str, bars: list, market_common_regime_by_date: dict[str, str]) -> list[dict]:
    """1단계(저비용): 매수일 후보만 스캔 — exit 시뮬레이션은 하지 않는다."""
    from agent_trading.services.deterministic_trigger_engine import (
        _assess_buy_eligibility,
        _build_relative_activity_score,
    )
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot
    from agent_trading.services.strategy_selection import select_strategy

    rows: list[dict] = []
    last_t = len(bars) - 1 - MAX_EXIT_OBSERVATION_DAYS
    if last_t < _MIN_LOOKBACK - 1:
        return rows

    for t in range(_MIN_LOOKBACK - 1, last_t + 1):
        window = bars[: t + 1]
        try:
            features, card = build_signal_snapshot(symbol, window)
        except Exception:
            continue
        overall, fast, slow = float(card.overall_score), float(card.fast_score), float(card.slow_score)
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


def _simulate_exit(row: dict, bars: list) -> None:
    """2단계(고비용, would_buy 후보에만 적용): 60거래일 signal-driven
    청산 시뮬레이션 + 보유 구간 MAE 계산."""
    from agent_trading.services.deterministic_trigger_engine import _build_exit_score
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot

    t = row["entry_t"]
    base_close = bars[t].close_price
    exit_day_offset = None
    worst_drawdown = 0.0  # MAE: 보유 구간 중 최저 미실현 수익률(음수일수록 손실 큼)

    for offset in range(1, MAX_EXIT_OBSERVATION_DAYS + 1):
        fwd_t = t + offset
        if fwd_t >= len(bars):
            break
        low_ret = (bars[fwd_t].low_price / base_close) - 1.0
        if low_ret < worst_drawdown:
            worst_drawdown = low_ret

        window = bars[: fwd_t + 1]
        try:
            features, card = build_signal_snapshot(row["symbol"], window)
        except Exception:
            continue
        fwd_overall, fwd_fast, fwd_slow = float(card.overall_score), float(card.fast_score), float(card.slow_score)
        fwd_snapshot = SimpleNamespace(
            overall_score=fwd_overall, fast_score=fwd_fast, slow_score=fwd_slow,
            return_1m_pct=features.return_1m_pct, return_3m_pct=features.return_3m_pct,
            price_vs_sma_20_pct=features.price_vs_sma_20_pct, price_vs_sma_60_pct=features.price_vs_sma_60_pct,
            volatility_20d_pct=features.volatility_20d_pct, atr_14_pct=features.atr_14_pct,
            volume_surge_ratio=features.volume_surge_ratio, average_volume_20d=features.average_volume_20d,
            average_turnover_20d=features.average_turnover_20d, turnover_surge_ratio=features.turnover_surge_ratio,
            rsi_14=features.rsi_14, sma_5=features.sma_5, sma_20=features.sma_20, sma_60=features.sma_60,
            component_scores_json=None,
        )
        fwd_regime = classify_market_regime(fwd_snapshot)
        reason_codes: list[str] = []
        exit_score = _build_exit_score(
            overall=fwd_overall, fast=fwd_fast, slow=fwd_slow,
            market_regime=fwd_regime, portfolio_allocation=None,
            position_snapshot=_HELD_POSITION, source_type="held_position",
            reason_codes=reason_codes,
        )
        if exit_score >= SELL_CANDIDATE_THRESHOLD:
            exit_day_offset = offset
            break

    if exit_day_offset is not None:
        exit_close = bars[t + exit_day_offset].close_price
        row["exit_offset"] = exit_day_offset
        row["exit_censored"] = False
        row["exit_return"] = (exit_close / base_close) - 1.0
    else:
        exit_day_offset = min(MAX_EXIT_OBSERVATION_DAYS, len(bars) - 1 - t)
        row["exit_offset"] = exit_day_offset
        row["exit_censored"] = True
        exit_close = bars[t + exit_day_offset].close_price
        row["exit_return"] = (exit_close / base_close) - 1.0
    row["mae"] = worst_drawdown


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
    bars_by_symbol: dict[str, list] = {}
    all_rows: list[dict] = []
    fetch_failures: list[str] = []
    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        if len(bars) < _MIN_LOOKBACK + MAX_EXIT_OBSERVATION_DAYS + 5:
            fetch_failures.append(symbol)
            continue
        bars_by_symbol[symbol] = bars
        rows = _entry_scan(symbol, bars, market_common_regime_by_date)
        all_rows.extend(rows)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[1단계 entry scan %d/%d] 누적 표본 %d건", idx, len(symbols), len(all_rows))

    logger.info("1단계 완료 — 전체 표본 %d건, 실패 %d종목", len(all_rows), len(fetch_failures))
    _attach_candidate_percentile(all_rows)
    would_buy_rows = _would_buy_rows(all_rows)
    logger.info("would_buy 표본 %d건 — 2단계(60일 exit+MAE 시뮬레이션) 시작", len(would_buy_rows))

    for i, row in enumerate(would_buy_rows, start=1):
        _simulate_exit(row, bars_by_symbol[row["symbol"]])
        if i % 200 == 0 or i == len(would_buy_rows):
            logger.info("[2단계 %d/%d] 완료", i, len(would_buy_rows))

    offset_hist: dict[str, int] = defaultdict(int)
    for r in would_buy_rows:
        off = r["exit_offset"]
        if r["exit_censored"]:
            bucket = "censored(60일 도달, 미청산)"
        elif off <= 5:
            bucket = "1~5일"
        elif off <= 10:
            bucket = "6~10일"
        elif off <= 20:
            bucket = "11~20일"
        elif off <= 40:
            bucket = "21~40일"
        else:
            bucket = "41~60일"
        offset_hist[bucket] += 1

    print("\n=== signal-driven 청산 타이밍 확장 시뮬레이션(60거래일 관찰 창) — B 시나리오, would_buy 후보 ===")
    print(f"표본 수: {len(would_buy_rows)}")
    print(f"청산 시점 분포: {dict(offset_hist)}")

    t5_stats = _stats([r["fwd_5"] for r in would_buy_rows], lag_hint=5)
    t20_stats = _stats([r["fwd_20"] for r in would_buy_rows], lag_hint=20)
    exit_stats = _stats([r["exit_return"] for r in would_buy_rows], lag_hint=20)
    mean_offset = round(_mean([r["exit_offset"] for r in would_buy_rows]), 2) if would_buy_rows else None
    censored_n = sum(1 for r in would_buy_rows if r["exit_censored"])
    censored_rate = round(censored_n / len(would_buy_rows), 4) if would_buy_rows else None

    mae_list = [r["mae"] for r in would_buy_rows]
    mae_mean = round(_mean(mae_list) * 100, 4) if mae_list else None
    mae_median = round(sorted(mae_list)[len(mae_list) // 2] * 100, 4) if mae_list else None
    mae_p10 = round(sorted(mae_list)[int(len(mae_list) * 0.10)] * 100, 4) if mae_list else None
    mae_worst = round(min(mae_list) * 100, 4) if mae_list else None
    mae_severe_rate = round(sum(1 for x in mae_list if x <= -0.20) / len(mae_list), 4) if mae_list else None

    print(f"T+5(고정): {t5_stats}")
    print(f"T+20(고정): {t20_stats}")
    print(f"signal-driven 청산(60일 관찰, 실제 exit_score 기반): {exit_stats}")
    print(f"평균 보유일수: {mean_offset}, censored(60일 내 미청산) 비율: {censored_rate}")
    print(f"MAE 평균: {mae_mean}%, 중앙값: {mae_median}%, 하위 10%: {mae_p10}%, 최악값: {mae_worst}%, "
          f"-20% 이하 심각 손실 비율: {mae_severe_rate}")

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
        "mae": {
            "mean_pct": mae_mean, "median_pct": mae_median, "p10_pct": mae_p10,
            "worst_pct": mae_worst, "severe_loss_rate_below_neg20pct": mae_severe_rate,
        },
        "comparison_to_sppv_2_52_20day_window": {
            "censored_rate_20day": 0.9114, "mean_holding_days_20day": 19.35,
            "signal_driven_exit_mean_pct_20day": 6.1405, "signal_driven_exit_t_nw_20day": 4.73,
        },
    }
    out_path = "logs/signal_ic_r3b_signal_driven_exit_timing_extended60d_2026-07-18.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
