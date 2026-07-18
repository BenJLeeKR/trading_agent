#!/usr/bin/env python3
"""SPPV-2.50 — "혼합 국면 약세" 가설의 직접 분해: 거래일 단위 시장
공통 국면 혼합도 버킷화 (read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §39.5(다음
단계 4 — 국면 혼합도 감지·대응 설계 검토) 및 §38.6 참고.

§39(SPPV-2.49)는 분기1(혼합 국면)과 분기4(단일 bullish 국면)를
대조해 "혼합 국면일수록 t_NW가 약하다"는 가설의 **지지 증거를
추가**했다 — 그러나 이는 분기 2개(N=2)의 대조일 뿐, "혼합도가
높을수록 성과가 나빠진다"는 것을 **직접** 분해해 확인한 것은
아니었다. 분기1이 우연히 약했던 다른 이유(예: 특정 소수 거래일의
극단치, §33 참고)일 가능성도 완전히 배제되지 않았다.

**이번 턴이 고른 분해 축**: 분기 단위 대조를 반복하지 않고,
**거래일 단위로 "최근 60거래일(약 1분기) 창의 시장 공통 국면
혼합도"를 직접 수치화**해 3년 전체 표본(4개 분기 경계를 넘나드는
연속 스펙트럼)에서 혼합도 상위/중위/하위 3분위로 버킷화한다. 이는
"분기1이라서 나쁘다"가 아니라 "혼합도가 높은 날일수록 나쁜가"를
분기 경계와 무관하게 직접 검증하는 가장 직접적인 방법이다 — 특정
분기 하나에 결과가 묶여 있는지, 혼합도라는 연속 변수 자체와 상관
관계가 있는지를 구분해낼 수 있다.

**혼합도 정의**: 각 거래일 d에 대해 최근 60거래일(d 포함) 구간의
시장 공통 국면 라벨 분포에서 `mixed_score = 1 - (최빈 라벨 비중)`
을 계산한다 — 0이면 그 구간이 완전히 단일 국면, 1에 가까울수록
여러 국면이 고르게 섞여 있다는 뜻이다.

**대상 candidate**: 승인된 조합 그대로 — R3b(alpha) + entry_score
risk_off_penalty 제거(§46/§47의 B 시나리오, eligibility 축은
불변). §39와 동일 candidate 정의를 유지해 비교 가능성을 지킨다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음. 실제 KIS
호출 여부는 가정하지 않고 로그의 `HTTP Request:` 카운트로 그대로
보고한다.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import sys as _sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_r3b_regime_mix_intensity_decomposition")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_alpha_layer_buy_funnel_comparison import _ALPHA_W_NEW_SIGNAL, _clamp01  # noqa: E402
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK, _mean, _newey_west_se_of_mean  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

TOP_QUINTILE_FRACTION = 0.20
BUY_CANDIDATE_THRESHOLD = 0.65
WATCH_TOP_K_BUY = 3
_STRATEGY_ALIGNMENT_BONUS = 0.05
_STRATEGY_ALIGNMENT_SET = {"swing_momentum", "event_continuation"}
MIX_WINDOW_TRADING_DAYS = 60  # 약 1분기 — 혼합도 계산용 trailing window
N_MIX_BUCKETS = 3


def _compute_mixed_scores(market_common_regime_by_date: dict[str, str]) -> dict[str, float]:
    """거래일마다 최근 60거래일(포함) 창의 국면 분포에서
    mixed_score = 1 - (최빈 라벨 비중)을 계산한다."""
    dates = sorted(market_common_regime_by_date.keys())
    labels = [market_common_regime_by_date[d] for d in dates]
    mixed_score_by_date: dict[str, float] = {}
    for i, d in enumerate(dates):
        start = max(0, i - MIX_WINDOW_TRADING_DAYS + 1)
        window_labels = labels[start : i + 1]
        if len(window_labels) < 20:
            continue
        counts = Counter(window_labels)
        max_share = max(counts.values()) / len(window_labels)
        mixed_score_by_date[d] = round(1.0 - max_share, 4)
    return mixed_score_by_date


def _collect_rows(symbol: str, bars: list, market_common_regime_by_date: dict[str, str],
                   mixed_score_by_date: dict[str, float]) -> list[dict]:
    from agent_trading.services.deterministic_trigger_engine import (
        _assess_buy_eligibility,
        _build_relative_activity_score,
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
        mixed_score = mixed_score_by_date.get(trade_date)

        ret3m, ret1m, vol = features.return_3m_pct, features.return_1m_pct, features.volatility_20d_pct
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
            "market_common_regime": market_common_label,
            "mixed_score": mixed_score,
            "regime_conditional_signal": regime_conditional_signal,
            "non_alpha_b_scenario": non_alpha_b_scenario,
            "eligible": eligible,
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


def _score_b(row: dict) -> float | None:
    if row.get("candidate_percentile") is None:
        return None
    return _clamp01(_ALPHA_W_NEW_SIGNAL * row["candidate_percentile"] + row["non_alpha_b_scenario"])


def _funnel_report(rows: list[dict]) -> dict:
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
            if r.get("candidate_percentile") is None or not r["eligible"]:
                continue
            eligible_rows.append(r)
            score = _score_b(r)
            if score is not None and score >= BUY_CANDIDATE_THRESHOLD:
                selected_rows.append(r)
                day_selected_ranked.append((r, score))
        day_selected_ranked.sort(key=lambda pair: pair[1], reverse=True)
        would_buy_rows.extend(r for r, _ in day_selected_ranked[:WATCH_TOP_K_BUY])

    report: dict = {
        "candidate_n": len(candidates), "eligible_n": len(eligible_rows),
        "selected_n": len(selected_rows), "would_buy_n": len(would_buy_rows),
        "n_active_days": len({r["trade_date"] for r in would_buy_rows}),
        "by_horizon": {},
    }
    for h in FORWARD_HORIZONS_FOCUS:
        xs = [r[f"fwd_{h}"] for r in would_buy_rows]
        if len(xs) < 5:
            report["by_horizon"][f"T+{h}"] = {"n": len(xs), "note": "표본부족"}
            continue
        m = _mean(xs)
        nw_se = _newey_west_se_of_mean(xs, lag=max(h - 1, 1))
        t_nw = (m / nw_se) if nw_se else None
        mfe = _mean([r[f"mfe_{h}"] for r in would_buy_rows])
        mae = _mean([r[f"mae_{h}"] for r in would_buy_rows])
        report["by_horizon"][f"T+{h}"] = {
            "n": len(xs), "mean_pct": round(m * 100, 4),
            "t_newey_west": round(t_nw, 2) if t_nw else None,
            "pct_positive": round(sum(1 for x in xs if x > 0) / len(xs), 4),
            "mfe_mean_pct": round(mfe * 100, 4), "mae_mean_pct": round(mae * 100, 4),
            "total_return_proxy": round(len(xs) * m * 100, 1),
        }
    return report


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

    mixed_score_by_date = _compute_mixed_scores(market_common_regime_by_date)
    scores_sorted = sorted(mixed_score_by_date.values())
    n = len(scores_sorted)
    tercile_cut1 = scores_sorted[n // 3]
    tercile_cut2 = scores_sorted[2 * n // 3]
    logger.info("혼합도 3분위 경계: cut1=%.4f, cut2=%.4f (전체 %d거래일)", tercile_cut1, tercile_cut2, n)

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})
    all_rows: list[dict] = []
    fetch_failures: list[str] = []
    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        if len(bars) < _MIN_LOOKBACK + max(FORWARD_HORIZONS_FOCUS) + 5:
            fetch_failures.append(symbol)
            continue
        rows = _collect_rows(symbol, bars, market_common_regime_by_date, mixed_score_by_date)
        all_rows.extend(rows)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_rows))

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_rows), len(fetch_failures))
    _attach_candidate_percentile(all_rows)

    def _bucket(score: float | None) -> str | None:
        if score is None:
            return None
        if score <= tercile_cut1:
            return "저혼합(단일 국면 지배)"
        if score <= tercile_cut2:
            return "중혼합"
        return "고혼합"

    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in all_rows:
        b = _bucket(r.get("mixed_score"))
        if b is not None:
            buckets[b].append(r)

    print("\n=== 거래일 단위 시장 공통 국면 혼합도 버킷화 (B 시나리오: R3b + entry_score risk_off_penalty 제거) ===")
    print(f"혼합도 3분위 경계: cut1={tercile_cut1:.4f}, cut2={tercile_cut2:.4f}")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "mix_window_trading_days": MIX_WINDOW_TRADING_DAYS,
        "tercile_cut1": round(tercile_cut1, 4),
        "tercile_cut2": round(tercile_cut2, 4),
        "buckets": {},
    }
    for label in ("저혼합(단일 국면 지배)", "중혼합", "고혼합"):
        rows = buckets.get(label, [])
        regime_dist = dict(Counter(r["market_common_regime"] for r in rows))
        n_days = len({r["trade_date"] for r in rows})
        avg_mixed = round(_mean([r["mixed_score"] for r in rows]), 4) if rows else None
        funnel = _funnel_report(rows)
        print(f"\n--- {label} (평균 혼합도={avg_mixed}, 거래일수={n_days}, 표본={len(rows)}) ---")
        print(f"  국면 분포: {regime_dist}")
        print(f"  candidate={funnel['candidate_n']}, eligible={funnel['eligible_n']}, "
              f"selected={funnel['selected_n']}, would_buy={funnel['would_buy_n']}")
        for h in FORWARD_HORIZONS_FOCUS:
            print(f"    T+{h}: {funnel['by_horizon'].get(f'T+{h}')}")
        report["buckets"][label] = {
            "n_trading_days": n_days, "n_rows": len(rows),
            "avg_mixed_score": avg_mixed, "regime_distribution": regime_dist,
            "funnel": funnel,
        }

    out_path = "logs/signal_ic_r3b_regime_mix_intensity_decomposition_2026-07-18.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
