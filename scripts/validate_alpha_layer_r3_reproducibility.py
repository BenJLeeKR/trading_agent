#!/usr/bin/env python3
"""SPPV-2.30 — R3(percentile 기반 스케일링) 재현성 검증 + percentile
계산 민감도 점검 (read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §19.6(다음
단계 2 — R3 재현성을 다른 기간 분할로 추가 확인) 참고.

§19(SPPV-2.29)는 R3(그날 cross-sectional percentile 기반 alpha
재보정)가 2차(3년)/1차(최근 12개월)/전반부/후반부 4개 창 전부에서
R0(재보정 없음)보다 forward return이 개선되고, 문턱(0.65) 통과율도
100%에서 93.7~96.5%로 의미 있게 내려온다는 것을 **단일 실험**으로
확인했다. 이 스크립트는 그 결과가 특정 기간(특히 최근 강세장)의
우연이 아닌지, 더 잘게 쪼갠 기간(분기 4분할)에서도 재현되는지
검증한다.

비교 대상 3개(§18/§19와 동일한 운영 코드/상수 재사용, 새 로직 없음):
  - **A(현행 alpha layer)**: candidate=`current_alpha_composite`
    상위 20%, entry_score는 운영 함수 그대로.
  - **B_R0(재보정 없음)**: candidate=`regime_conditional_signal`
    상위 20%, entry_score alpha 항 = `0.80*normalize(signal_raw)`
    (§18/§19의 기준선).
  - **B_R3(percentile 재보정)**: candidate는 B_R0와 동일, entry_score
    alpha 항 = `0.80*day_percentile_rank(signal_raw)`(§19에서 가장
    균형 잡힌 결과를 보인 안).

funnel은 §18/§19와 동일한 candidate→eligible→selected→would_buy→
blocked_by_*이며, MFE/MAE도 동일 방식으로 계측한다.

검증 창: 2차(3년)/1차(최근 12개월)/전반부/후반부(§15~§19와 동일
정의) + **분기 4분할**(3년 표본을 거래일 기준 4등분, out-of-sample
성격을 §15보다 더 잘게 쪼개 확인).

percentile 계산 민감도 점검(§19.6이 지시한 후속 과제): R3는 "그날
신호 산출 가능한 전체 universe(quintile 컷 이전)" 기준 백분위를
쓴다. 이 스크립트는 추가로 **R3b(candidate 컷 이후, 상위 20% 내부
에서만 재계산한 백분위)**를 함께 계측해 percentile 기준(base
universe)에 따라 결과가 민감하게 바뀌는지 확인한다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음. 실제 KIS
호출 여부는 가정하지 않고 로그의 `HTTP Request:` 카운트로 그대로
보고한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys as _sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_alpha_layer_r3_reproducibility")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_activity_filter_threshold_sweep import _split_first_second_half  # noqa: E402
from validate_alpha_layer_buy_funnel_comparison import WATCH_TOP_K_BUY  # noqa: E402
from validate_alpha_layer_score_rescaling_comparison import (  # noqa: E402
    _ALPHA_W_NEW_SIGNAL,
    _attach_day_level_rescaled_scores,
    _clamp01,
    _collect_symbol_rows,
    _normalize_signed_score,
)
from validate_alpha_layer_virtual_buy_funnel_extended import BUY_CANDIDATE_THRESHOLD  # noqa: E402
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK, _mean, _newey_west_se_of_mean, _stdev  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

RECENT_WINDOW_CALENDAR_DAYS = 365
TOP_QUINTILE_FRACTION = 0.20


def _split_into_quarters(rows: list[dict]) -> list[list[dict]]:
    """3년 표본을 거래일 기준 4등분한다(§15의 2등분을 확장)."""
    dates = sorted({r["trade_date"] for r in rows})
    n = len(dates)
    if n < 20:
        return [rows]
    cut_points = [dates[int(n * i / 4)] for i in range(1, 4)]
    q1 = [r for r in rows if r["trade_date"] < cut_points[0]]
    q2 = [r for r in rows if cut_points[0] <= r["trade_date"] < cut_points[1]]
    q3 = [r for r in rows if cut_points[1] <= r["trade_date"] < cut_points[2]]
    q4 = [r for r in rows if r["trade_date"] >= cut_points[2]]
    return [q1, q2, q3, q4]


def _attach_candidate_only_percentile(rows: list[dict]) -> None:
    """R3b(candidate 컷 이후 백분위) 계산 — 그날 상위 20% quintile
    멤버들만 모아 그 안에서 다시 백분위를 매긴다(민감도 점검용)."""
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
        "blocked_by_eligibility_n": len(funnel["blocked_by_eligibility"]),
        "blocked_by_score_threshold_n": len(funnel["blocked_by_score_threshold"]),
        "eligible_rate_of_candidate": round(n_eligible / max(n_candidate, 1) * 100, 2),
        "selected_rate_of_eligible": round(n_selected / max(n_eligible, 1) * 100, 2),
        "by_stage_horizon": {},
        "mfe_mae_would_buy": {},
    }
    for h in FORWARD_HORIZONS_FOCUS:
        report["by_stage_horizon"][f"T+{h}"] = _summarize([r[f"fwd_{h}"] for r in funnel["would_buy"]], h)
        report["mfe_mae_would_buy"][f"T+{h}"] = _mfe_mae_summary(funnel["would_buy"], h)
    return report


def _analyze_window(rows: list[dict], window_label: str) -> dict:
    print(f"\n=== {window_label} (표본 {len(rows)}건) ===")
    window_report: dict = {"window": window_label, "scenarios": {}}

    for skey, (signal_key, score_fn) in SCENARIOS.items():
        funnel = _funnel_for_scenario(rows, signal_key, score_fn)
        report = _funnel_report(funnel)
        window_report["scenarios"][skey] = report
        print(f"  [{skey}] candidate={report['candidate_n']}, eligible={report['eligible_n']}, "
              f"selected={report['selected_n']}(rate={report['selected_rate_of_eligible']}%), "
              f"would_buy={report['would_buy_n']}")
        for h in FORWARD_HORIZONS_FOCUS:
            wb = report["by_stage_horizon"][f"T+{h}"]
            mm = report["mfe_mae_would_buy"][f"T+{h}"]
            print(f"    would_buy T+{h}: {wb} | MFE/MAE: {mm}")

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

    _attach_day_level_rescaled_scores(all_rows)
    _attach_candidate_only_percentile(all_rows)

    last_date = max(datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in all_rows)
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    recent_rows = [r for r in all_rows if r["trade_date"] >= cutoff]
    first_half, second_half = _split_first_second_half(all_rows)
    quarters = _split_into_quarters(all_rows)

    print("\n=== R3(percentile) 재현성 검증 + percentile 계산 민감도 점검 ===")
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

    out_path = "logs/signal_ic_alpha_layer_r3_reproducibility_2026-07-16.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
