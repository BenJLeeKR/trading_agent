#!/usr/bin/env python3
"""SPPV-2.31 — R3b(candidate 내부 percentile) 엄격 재검증 + R3가
분기1/분기3에서 R0보다 밀린 원인 분해 (read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §20.6(다음
단계 1 — R3b를 R1과 동일한 엄격도로 별도 검증, 다음 단계 2 — 분기1/
분기3에서 R3가 R0보다 못한 원인 규명) 참고.

§20(SPPV-2.30)은 분기 4분할 재검증에서 R3(그날 전체 universe 기준
percentile)가 분기1·분기3에서 R0보다 못하다는 것, 그리고 candidate
컷 이후 내부에서 재계산한 R3b가 8개 창 전부에서 R0보다 낫다는 것을
발견했다 — 다만 R3b는 selected_rate가 30%대까지 낮아져 §19에서
기각한 R1(가중치 축소)과 같은 "극단적 선별" 우려가 있어 별도
검증이 필요하다고 판단했다. 이 스크립트는 그 두 후속 과제를 실행한다.

**작업 1 — R3b 엄격 검증(R1과 동일 기준)**: §19에서 R1을 기각한
기준은 "selected_rate 회복만으로는 부족하고, 4개 창 중 하나라도
forward return이 악화되면 기각"이었다. 이번에는 4개 창(2차/1차/
전후반)+분기 4분할 총 8개 창에서 R3b가 R0 대비 **어느 하나라도
악화되는 창이 있는지** 엄격히 확인한다. 추가로 R3b가 진짜 선별
품질 개선인지, 아니면 (a) 표본 급감에 따른 통계적 착시(작은 n에서
극단값 몇 개가 평균을 크게 흔드는 현상), (b) 특정 강세 구간(분기4)
편향, (c) R0/R3의 would_buy 집합을 단순히 "더 강하게 걸러낸 부분
집합"인지(=선별 순서 자체는 같고 개수만 줄인 것인지, 아니면 실제로
다른 종목을 고르는지)를 분리해서 본다 — **overlap 비율**(R3b의
would_buy 중 R0/R3의 would_buy와 겹치는 비율)을 계측해 답한다.

**작업 2 — R3 실패 구간(분기1/분기3) 원인 분해**: §16과 동일한
방법론(시장 공통 regime 분포, activity_ratio/volatility/turnover
분포)에 추가로, **candidate 내부 alpha 값의 분산·saturation 비율**
(regime_conditional_signal이 1.0을 넘어 normalize에서 saturate되는
비율)과 **percentile 기준(전체 universe vs candidate 내부)의 차이가
만드는 순위 역전 빈도**를 분기별로 비교해, 왜 분기1·분기3에서
"그날 전체 universe 기준 percentile"이 오히려 나쁜 선택을 만드는지
설명한다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음. 실제 KIS
호출 여부는 가정하지 않고 로그의 `HTTP Request:` 카운트로 그대로
보고한다.
"""

from __future__ import annotations

import asyncio
import bisect
import json
import logging
import sys as _sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_r3b_strict_and_r3_failure_decomposition")

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
from validate_alpha_layer_r3_reproducibility import _split_into_quarters  # noqa: E402
from validate_alpha_layer_virtual_buy_funnel_extended import BUY_CANDIDATE_THRESHOLD  # noqa: E402
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


def _collect_symbol_rows(symbol: str, bars: list, market_common_regime_by_date: dict[str, str]) -> list[dict]:
    """§19/§20 수집 로직 + §16 스타일의 원인 분해용 원시값
    (volatility_20d_pct/average_turnover_20d/activity_ratio)을 추가."""
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

        eligible, _reasons = _assess_buy_eligibility(
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
            "current_alpha_composite": current_alpha_composite,
            "regime_conditional_signal": regime_conditional_signal,
            "non_alpha_b": non_alpha_b,
            "eligible": eligible,
            "entry_score_a": entry_score_a,
            "volatility_20d_pct": features.volatility_20d_pct,
            "average_turnover_20d": features.average_turnover_20d,
            "activity_ratio": activity_ratio,
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


def _attach_day_level_stats(rows: list[dict]) -> None:
    """R3(전체 universe 기준 percentile)용 day_percentile과 candidate
    내부(quintile 컷 이후) 기준 candidate_percentile을 모두 부착한다."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["regime_conditional_signal"] is not None:
            by_date[r["trade_date"]].append(r)

    for day_rows in by_date.values():
        signals = [r["regime_conditional_signal"] for r in day_rows]
        n = len(signals)
        sorted_signals = sorted(signals)
        for r in day_rows:
            s = r["regime_conditional_signal"]
            if n > 1:
                idx = bisect.bisect_left(sorted_signals, s)
                r["day_percentile"] = idx / (n - 1)
            else:
                r["day_percentile"] = 0.5
            r["saturated_raw"] = s >= 1.0  # normalize_signed_score saturate 조건

        ordered = sorted(day_rows, key=lambda r: r["regime_conditional_signal"], reverse=True)
        q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
        day_candidates = ordered[:q]
        cand_signals = sorted(r["regime_conditional_signal"] for r in day_candidates)
        cn = len(cand_signals)
        cand_id_set = {(r["symbol"], r["trade_date"]) for r in day_candidates}
        for r in day_rows:
            key = (r["symbol"], r["trade_date"])
            if key not in cand_id_set:
                r["candidate_percentile"] = None
                continue
            idx = bisect.bisect_left(cand_signals, r["regime_conditional_signal"])
            r["candidate_percentile"] = idx / (cn - 1) if cn > 1 else 0.5


def _score_a(row: dict) -> float:
    return row["entry_score_a"]


def _score_b_r0(row: dict) -> float | None:
    signal = row["regime_conditional_signal"]
    if signal is None:
        return None
    return _clamp01(_ALPHA_W_NEW_SIGNAL * _normalize_signed_score(signal) + row["non_alpha_b"])


def _score_b_r3(row: dict) -> float | None:
    if row["regime_conditional_signal"] is None:
        return None
    return _clamp01(_ALPHA_W_NEW_SIGNAL * row.get("day_percentile", 0.5) + row["non_alpha_b"])


def _score_b_r3b(row: dict) -> float | None:
    if row.get("candidate_percentile") is None:
        return None
    return _clamp01(_ALPHA_W_NEW_SIGNAL * row["candidate_percentile"] + row["non_alpha_b"])


SCENARIOS = {
    "A_current_alpha": ("current_alpha_composite", _score_a),
    "B_R0_no_rescale": ("regime_conditional_signal", _score_b_r0),
    "B_R3_percentile_fulluniverse": ("regime_conditional_signal", _score_b_r3),
    "B_R3b_percentile_candidateonly": ("regime_conditional_signal", _score_b_r3b),
}


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


def _funnel_for_scenario(rows: list[dict], signal_key: str, score_fn) -> dict:
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get(signal_key) is not None:
            by_date[r["trade_date"]].append(r)

    candidates, eligible_rows, selected_rows, would_buy_rows = [], [], [], []
    blocked_by_eligibility, blocked_by_score_threshold = [], []

    for day_rows in by_date.values():
        if len(day_rows) < 5:
            continue
        ordered = sorted(day_rows, key=lambda r: r[signal_key], reverse=True)
        q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
        day_candidates = ordered[:q]
        candidates.extend(day_candidates)

        day_selected_ranked = []
        for r in day_candidates:
            score = score_fn(r)
            if not r["eligible"]:
                blocked_by_eligibility.append(r)
                continue
            eligible_rows.append(r)
            if score is not None and score >= BUY_CANDIDATE_THRESHOLD:
                selected_rows.append(r)
                day_selected_ranked.append((r, score))
            else:
                blocked_by_score_threshold.append(r)

        day_selected_ranked.sort(key=lambda pair: pair[1], reverse=True)
        would_buy_rows.extend(r for r, _ in day_selected_ranked[:WATCH_TOP_K_BUY])

    return {
        "candidate": candidates,
        "eligible": eligible_rows,
        "selected": selected_rows,
        "would_buy": would_buy_rows,
        "blocked_by_eligibility": blocked_by_eligibility,
        "blocked_by_score_threshold": blocked_by_score_threshold,
    }


def _funnel_report(funnel: dict) -> dict:
    n_candidate, n_eligible = len(funnel["candidate"]), len(funnel["eligible"])
    n_selected, n_would_buy = len(funnel["selected"]), len(funnel["would_buy"])
    report: dict = {
        "candidate_n": n_candidate,
        "eligible_n": n_eligible,
        "selected_n": n_selected,
        "would_buy_n": n_would_buy,
        "selected_rate_of_eligible": round(n_selected / max(n_eligible, 1) * 100, 2),
        "by_stage_horizon": {},
        "mfe_mae_would_buy": {},
    }
    for h in FORWARD_HORIZONS_FOCUS:
        report["by_stage_horizon"][f"T+{h}"] = _summarize([r[f"fwd_{h}"] for r in funnel["would_buy"]], h)
        report["mfe_mae_would_buy"][f"T+{h}"] = _mfe_mae_summary(funnel["would_buy"], h)
    report["_would_buy_ids"] = {(r["symbol"], r["trade_date"]) for r in funnel["would_buy"]}
    return report


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

    return {"n": n, "mean": round(_mean(ordered), 4), "median": round(pct(0.5), 4),
            "p25": round(pct(0.25), 4), "p75": round(pct(0.75), 4)}


def _analyze_window(rows: list[dict], window_label: str) -> dict:
    print(f"\n=== {window_label} (표본 {len(rows)}건) ===")
    window_report: dict = {"window": window_label, "scenarios": {}}
    reports: dict = {}

    for skey, (signal_key, score_fn) in SCENARIOS.items():
        funnel = _funnel_for_scenario(rows, signal_key, score_fn)
        report = _funnel_report(funnel)
        reports[skey] = report
        wb_ids = report.pop("_would_buy_ids")
        report["_wb_ids_internal"] = wb_ids  # 임시 보관(직렬화 전 제거)
        window_report["scenarios"][skey] = {k: v for k, v in report.items() if k != "_wb_ids_internal"}
        print(f"  [{skey}] candidate={report['candidate_n']}, eligible={report['eligible_n']}, "
              f"selected={report['selected_n']}(rate={report['selected_rate_of_eligible']}%), "
              f"would_buy={report['would_buy_n']}")
        for h in FORWARD_HORIZONS_FOCUS:
            wb = report["by_stage_horizon"][f"T+{h}"]
            mm = report["mfe_mae_would_buy"][f"T+{h}"]
            print(f"    would_buy T+{h}: {wb} | MFE/MAE: {mm}")

    # overlap 진단: R3b/R3의 would_buy가 R0의 would_buy와 얼마나 겹치는가
    r0_ids = reports["B_R0_no_rescale"]["_wb_ids_internal"]
    r3_ids = reports["B_R3_percentile_fulluniverse"]["_wb_ids_internal"]
    r3b_ids = reports["B_R3b_percentile_candidateonly"]["_wb_ids_internal"]

    def _overlap_rate(a: set, b: set) -> float:
        return round(len(a & b) / max(len(a), 1) * 100, 2)

    overlap_report = {
        "r3_overlap_with_r0_pct": _overlap_rate(r3_ids, r0_ids),
        "r3b_overlap_with_r0_pct": _overlap_rate(r3b_ids, r0_ids),
        "r3b_overlap_with_r3_pct": _overlap_rate(r3b_ids, r3_ids),
    }
    print(f"  [overlap 진단] R3∩R0={overlap_report['r3_overlap_with_r0_pct']}%, "
          f"R3b∩R0={overlap_report['r3b_overlap_with_r0_pct']}%, "
          f"R3b∩R3={overlap_report['r3b_overlap_with_r3_pct']}%")
    window_report["would_buy_overlap"] = overlap_report

    # R3 실패 원인 분해용 보조 지표
    regime_dist = _regime_day_distribution(rows)
    candidates_all = []
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["regime_conditional_signal"] is not None:
            by_date[r["trade_date"]].append(r)
    for day_rows in by_date.values():
        if len(day_rows) < 5:
            continue
        ordered = sorted(day_rows, key=lambda r: r["regime_conditional_signal"], reverse=True)
        q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
        candidates_all.extend(ordered[:q])

    saturated_n = sum(1 for r in candidates_all if r.get("saturated_raw"))
    saturation_rate = round(saturated_n / max(len(candidates_all), 1) * 100, 2)
    activity_stats = _quartiles([r["activity_ratio"] for r in candidates_all if r["activity_ratio"] is not None])
    vol_stats = _quartiles([r["volatility_20d_pct"] for r in candidates_all if r["volatility_20d_pct"] is not None])
    turnover_stats = _quartiles(
        [r["average_turnover_20d"] for r in candidates_all if r["average_turnover_20d"] is not None]
    )

    print(f"  [R3 원인분해 보조지표] 국면분포={regime_dist}, saturation_rate={saturation_rate}%, "
          f"activity_ratio={activity_stats}, volatility={vol_stats}")

    window_report["r3_failure_diagnostics"] = {
        "regime_day_distribution": regime_dist,
        "candidate_n": len(candidates_all),
        "saturation_rate_pct": saturation_rate,
        "activity_ratio_distribution": activity_stats,
        "volatility_20d_pct_distribution": vol_stats,
        "average_turnover_20d_distribution": turnover_stats,
    }

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

    _attach_day_level_stats(all_rows)

    last_date = max(datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in all_rows)
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    recent_rows = [r for r in all_rows if r["trade_date"] >= cutoff]
    first_half, second_half = _split_first_second_half(all_rows)
    quarters = _split_into_quarters(all_rows)

    print("\n=== R3b 엄격 검증 + R3 실패 구간(분기1/분기3) 원인 분해 ===")
    print(f"전체 3년 표본: {len(all_rows)}건, 최근 12개월(cutoff={cutoff}) 표본: {len(recent_rows)}건")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_rows),
        "total_rolling_samples_recent_12m": len(recent_rows),
        "recent_window_cutoff": cutoff,
        "scenarios_tested": list(SCENARIOS.keys()),
        "windows": {},
    }

    report["windows"]["supplementary_3y"] = _analyze_window(all_rows, "2차(3년, 전체 표본)")
    report["windows"]["primary_recent_12m"] = _analyze_window(recent_rows, "1차(최근 12개월)")
    report["windows"]["3y_first_half"] = _analyze_window(first_half, "3년 전반부")
    report["windows"]["3y_second_half"] = _analyze_window(second_half, "3년 후반부")
    for i, q_rows in enumerate(quarters, start=1):
        if q_rows:
            dates = sorted({r["trade_date"] for r in q_rows})
            label = f"3년 분기{i}({dates[0]}~{dates[-1]})"
            report["windows"][f"quarter_{i}"] = _analyze_window(q_rows, label)

    out_path = "logs/signal_ic_r3b_strict_and_r3_failure_decomposition_2026-07-16.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
