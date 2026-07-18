#!/usr/bin/env python3
"""SPPV-2.55 — 손절(stop-loss) 정책 도입이 총 기대수익에 미치는
영향 ablation(read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §42(SPPV-2.53)
가 §38 보조 잔여 조건에 신규 추가한 "경로 리스크(MAE)·손절 정책
부재"를 이번 턴에 전진시킨다. §42가 확인한 것은 "MAE 평균 -11.08%,
심각 손실(-20% 이하) 비율 12.8%"라는 **리스크의 존재**뿐이었다 —
"손절선을 도입하면 총 기대수익이 개선되는지 악화되는지"는 §42가
아직 답하지 않은 질문이다. 이 질문은 SPPV-3 착수 여부에 직접
영향을 주는 신규 의사결정 정보다: 만약 손절이 총 기대수익을
개선한다면 SPPV-3 설계에 손절 로직을 포함해야 하고, 반대로 악화
시킨다면(예: 손절이 회복 전 조기 청산을 유발) 현재처럼 손절 없이
진행하는 것이 최고 기대수익 관점에서 더 낫다는 근거가 된다 —
단순 방어 논리가 아니라 **창 교체(R3b)의 실효성을 더 선명하게
만드는** 실측이다.

**방법**: §42와 완전히 동일한 candidate 정의(R3b + entry_score
risk_off_penalty 제거, B 시나리오, would_buy 후보, 60거래일 관찰
창)를 재사용하되, 청산 시뮬레이션에 손절 규칙을 추가한 3개 변형을
비교한다:
  - **A(baseline, 손절 없음)**: §42와 동일 — 매일 실제 저가 기준
    MAE만 추적하고, 청산은 `_build_exit_score`(실제 운영 함수)가
    임계값(0.75)을 넘을 때만 발생.
  - **B(손절 -15%)**: 위 A에 더해, 보유 중 어느 날이든 그날 저가
    기준 미실현 수익률이 -15% 이하로 떨어지면 그날 즉시 -15%
    가격에 청산(그 이후 관찰 중단).
  - **C(손절 -20%)**: 위와 동일하되 임계값 -20%.
  손절 체크는 그날의 `_build_exit_score` 체크보다 먼저 수행한다
  (같은 날 저가가 손절선을 건드리면 손절이 우선 발동한다고 가정 —
  보수적 가정, 전부 문서화).

손절 로직 자체는 이 스크립트 안에서만 시뮬레이션되는 shadow 계산
이며, 운영 코드(`deterministic_trigger_engine.py`)에는 어떤 손절
임계값도 추가하지 않는다 — 순수 read-only ablation이다.

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
logger = logging.getLogger("validate_r3b_stop_loss_ablation")

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
MAX_EXIT_OBSERVATION_DAYS = 60
STOP_LOSS_VARIANTS = {"A_no_stop": None, "B_stop_-15pct": -0.15, "C_stop_-20pct": -0.20}

_HELD_POSITION = SimpleNamespace(
    position_snapshot_id=uuid4(), account_id=uuid4(), instrument_id=uuid4(),
    quantity=Decimal("1"), average_price=Decimal("1"), market_price=None,
    unrealized_pnl=None, source_of_truth="shadow_sim", snapshot_at=datetime.now(_KST),
    purchase_amount=None, evaluation_amount=None, created_at=None,
    fetch_status="success", snapshot_sync_run_id=None,
)


def _entry_scan(symbol: str, bars: list, market_common_regime_by_date: dict[str, str]) -> list[dict]:
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


def _simulate_variants(row: dict, bars: list) -> None:
    """A(손절 없음)/B(-15%)/C(-20%) 3개 변형을 한 번의 60일 순회로 동시에 시뮬레이션."""
    from agent_trading.services.deterministic_trigger_engine import _build_exit_score
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot

    t = row["entry_t"]
    base_close = bars[t].close_price

    resolved: dict[str, dict] = {}  # variant_key -> {offset, censored, return, stop_triggered}
    pending = set(STOP_LOSS_VARIANTS.keys())

    for offset in range(1, MAX_EXIT_OBSERVATION_DAYS + 1):
        if not pending:
            break
        fwd_t = t + offset
        if fwd_t >= len(bars):
            break
        low_ret = (bars[fwd_t].low_price / base_close) - 1.0

        for key in list(pending):
            threshold = STOP_LOSS_VARIANTS[key]
            if threshold is not None and low_ret <= threshold:
                resolved[key] = {
                    "exit_offset": offset, "exit_censored": False,
                    "exit_return": threshold, "stop_triggered": True,
                }
                pending.discard(key)

        if not pending:
            break

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
            exit_close = bars[fwd_t].close_price
            for key in list(pending):
                resolved[key] = {
                    "exit_offset": offset, "exit_censored": False,
                    "exit_return": (exit_close / base_close) - 1.0, "stop_triggered": False,
                }
            pending.clear()
            break

    if pending:
        fallback_offset = min(MAX_EXIT_OBSERVATION_DAYS, len(bars) - 1 - t)
        fallback_close = bars[t + fallback_offset].close_price
        fallback_return = (fallback_close / base_close) - 1.0
        for key in pending:
            resolved[key] = {
                "exit_offset": fallback_offset, "exit_censored": True,
                "exit_return": fallback_return, "stop_triggered": False,
            }

    row["variants"] = resolved


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
    logger.info("would_buy 표본 %d건 — 2단계(3변형 동시 시뮬레이션) 시작", len(would_buy_rows))

    for i, row in enumerate(would_buy_rows, start=1):
        _simulate_variants(row, bars_by_symbol[row["symbol"]])
        if i % 200 == 0 or i == len(would_buy_rows):
            logger.info("[2단계 %d/%d] 완료", i, len(would_buy_rows))

    print("\n=== 손절(stop-loss) 정책 도입 ablation (60일 관찰, B 시나리오, would_buy 후보) ===")
    print(f"표본 수: {len(would_buy_rows)}")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "sell_candidate_threshold": SELL_CANDIDATE_THRESHOLD,
        "max_exit_observation_days": MAX_EXIT_OBSERVATION_DAYS,
        "would_buy_n": len(would_buy_rows),
        "variants": {},
    }

    for key in STOP_LOSS_VARIANTS:
        returns = [row["variants"][key]["exit_return"] for row in would_buy_rows]
        stop_triggered_n = sum(1 for row in would_buy_rows if row["variants"][key]["stop_triggered"])
        censored_n = sum(1 for row in would_buy_rows if row["variants"][key]["exit_censored"])
        mean_offset = round(_mean([row["variants"][key]["exit_offset"] for row in would_buy_rows]), 2)
        stats = _stats(returns, lag_hint=20)
        stats["stop_triggered_n"] = stop_triggered_n
        stats["stop_triggered_rate"] = round(stop_triggered_n / len(would_buy_rows), 4) if would_buy_rows else None
        stats["censored_n"] = censored_n
        stats["mean_holding_days"] = mean_offset
        report["variants"][key] = stats
        print(f"{key}: {stats}")

    out_path = "logs/signal_ic_r3b_stop_loss_ablation_2026-07-18.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
