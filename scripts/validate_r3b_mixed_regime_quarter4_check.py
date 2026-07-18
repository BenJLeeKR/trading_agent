#!/usr/bin/env python3
"""SPPV-2.49 — 승인된 R3b+`entry_score risk_off_penalty` 제거
조합(B 시나리오)에서 "혼합 국면(분기1 유형) out-of-sample 재확인"
보조 잔여 조건을 검증 (read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §38.6(다음
단계 4 — out-of-sample 데이터 축적 시 혼합 국면 구간 재확인) 참고.

**이번 턴에 이 항목을 고른 이유**: §38이 정리한 3개 보조 잔여
조건(T+5 구조적 리스크/혼합 국면 재확인/entry_score 코드 반영
절차) 중 T+5 구조적 리스크는 실거래 청산 이력이 있어야 답할 수
있고("실거래 누적 없이는 못 푸는 조건"에 더 가깝다), entry_score
코드 반영 절차는 §21 게이트 충족 이후 별도 트랙이라 지금 전진
시켜도 실익이 작다. **혼합 국면 재확인만 유일하게 "진짜 미래
데이터"가 아니라 "이미 3년 캐시 안에 있지만 아직 들여다보지 않은
제4의 분기(분기4)"로 지금 당장 검증 가능하다** — §33(SPPV-2.43)이
분기1(2023-10~2024-06)만 "혼합 국면"(강세/횡보/약세 고른 분포)
임을 확인했지만, 4개 분기 중 분기4(2025-10~2026-06, 가장 최근)의
국면 구성은 아직 이번 세션에서 계측한 적이 없다 — 분기4가 분기1
처럼 혼합 국면이라면 "혼합 국면 → 변동성 확대"라는 가설이 표본
하나(분기1)의 우연이 아니라는 근거가 되고, 반대로 분기4가 분기2/
분기3처럼 단일 국면 지배적이라면 "혼합 국면은 3년 표본 중 분기1
1건뿐이었다"는 것을 확정해 리스크 범위를 좁힐 수 있다. 둘 중
어느 쪽이든 "혼합 국면 재확인" 조건을 유의미하게 전진시킨다.

**대상 candidate**: 승인된 조합 그대로 — R3b(alpha) + entry_score
risk_off_penalty 제거(§46/§47의 B 시나리오, eligibility 축은
불변). §33은 A(현행 risk_off_penalty 유지) 기준으로 분기1을
진단했으므로, 이번 턴은 **실제 승인된 B 시나리오 기준으로 분기1을
재계측(비교 기준선 확보)하고 분기4를 신규 계측**한다.

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
logger = logging.getLogger("validate_r3b_mixed_regime_quarter4_check")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_alpha_layer_r3_reproducibility import _split_into_quarters  # noqa: E402
from validate_alpha_layer_buy_funnel_comparison import _ALPHA_W_NEW_SIGNAL, _clamp01  # noqa: E402
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK, _mean, _newey_west_se_of_mean, _stdev  # noqa: E402
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
QUARTER_LABELS = {1: "분기1", 4: "분기4"}


def _collect_rows(symbol: str, bars: list, market_common_regime_by_date: dict[str, str]) -> list[dict]:
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

        non_alpha_b_scenario = _non_alpha(neutral_regime)  # 승인된 B 시나리오(entry_score risk_off_penalty 제거)

        base_close = bars[t].close_price
        row: dict = {
            "symbol": symbol, "trade_date": trade_date,
            "market_common_regime": market_common_label,
            "per_symbol_regime_label": per_symbol_regime.regime_label if per_symbol_regime else None,
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


def _score_b(row: dict) -> float | None:
    if row.get("candidate_percentile") is None:
        return None
    return _clamp01(_ALPHA_W_NEW_SIGNAL * row["candidate_percentile"] + row["non_alpha_b_scenario"])


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
        "selected_rate_of_eligible": round(len(selected_rows) / max(len(eligible_rows), 1) * 100, 2),
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


def _diagnose(rows: list[dict], label: str) -> dict:
    print(f"\n=== {label} 혼합 국면 재확인 (표본 {len(rows)}건, B 시나리오: entry_score risk_off_penalty 제거) ===")
    market_common_dist = dict(Counter(r["market_common_regime"] for r in rows))
    per_symbol_dist = dict(Counter(r["per_symbol_regime_label"] for r in rows))
    print(f"  시장 공통 국면 분포: {market_common_dist}")
    print(f"  종목별 개별 국면 분포: {per_symbol_dist}")

    report = _funnel_report(rows)
    print(f"  candidate={report['candidate_n']}, eligible={report['eligible_n']}, "
          f"selected={report['selected_n']}(rate={report['selected_rate_of_eligible']}%), "
          f"would_buy={report['would_buy_n']}")
    for h in FORWARD_HORIZONS_FOCUS:
        print(f"    T+{h}: {report['by_horizon'].get(f'T+{h}')}")

    return {
        "label": label, "n_rows": len(rows),
        "market_common_regime_distribution": market_common_dist,
        "per_symbol_regime_distribution": per_symbol_dist,
        "funnel": report,
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
        if len(bars) < _MIN_LOOKBACK + max(FORWARD_HORIZONS_FOCUS) + 5:
            fetch_failures.append(symbol)
            continue
        rows = _collect_rows(symbol, bars, market_common_regime_by_date)
        all_rows.extend(rows)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_rows))

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_rows), len(fetch_failures))
    _attach_candidate_percentile(all_rows)

    quarters = _split_into_quarters(all_rows)
    if len(quarters) < 4:
        raise SystemExit("분기 분할 실패 — quarters 개수 부족")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "quarters": {},
    }
    for qi, label in QUARTER_LABELS.items():
        report["quarters"][label] = _diagnose(quarters[qi - 1], label)

    out_path = "logs/signal_ic_r3b_mixed_regime_quarter4_check_2026-07-18.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
