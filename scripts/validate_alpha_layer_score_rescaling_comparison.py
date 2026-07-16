#!/usr/bin/env python3
"""SPPV-2.29 — `regime_conditional_signal` 기반 새 alpha의 entry_score
스케일 재보정 shadow 검증 (read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §18.6(다음
단계 1 — §3 공식 재보정 설계 검토) 참고.

§18(SPPV-2.28)은 §3 제안 공식(`score += 0.80 *
_normalize_signed_score(regime_conditional_signal)`)을 그대로
적용했을 때 **`selected(entry_score>=0.65)` 통과율이 4개 창 전부에서
정확히 100.0%**임을 계측했다 — 즉 0.65 문턱이 새 alpha에는 사실상
무력화된다. 원인은 스케일 불일치다:

  - `overall_score`/`fast_score`/`slow_score`는 `signal_backbone`이
    이미 대략 [-1, 1] 범위로 정규화해 산출하는 값이다.
  - `regime_conditional_signal`(`risk_adj_momentum_3m` = `return_3m_
    pct / max(volatility_20d_pct, 1.0)`, 또는 `reversal_1m` =
    `-return_1m_pct`)은 **퍼센트 단위 비율/차분값**으로, [-1, 1]과
    무관한 스케일이다(예: 3개월 수익률 12% / 변동성 2% = 6.0).
  - `_normalize_signed_score(x) = clamp((x+1)/2)`를 이 값에 그대로
    적용하면 x>=1인 경우 전부 1.0으로 saturate된다 — 상위 20%
    quintile(양의 모멘텀이 강한 종목군)에서는 이 조건이 거의 항상
    성립해 alpha 항이 사실상 상수(0.80)가 된다.

이 스크립트는 그 스케일 불일치를 shadow로 재보정하는 3가지 방안을
비교한다(모두 **운영 코드 미수정**, candidate 정의 자체는
`regime_conditional_signal`의 원 값으로 그대로 유지 — 재보정은
entry_score 계산에만 적용):

  - **R0(기준선, SPPV-2.28 원안)**: 재보정 없음 —
    `0.80 * normalize(signal_raw)`.
  - **R1(가중치 축소)**: alpha 가중치를 0.80 → 0.50으로 낮춘다 —
    `0.50 * normalize(signal_raw)`. normalize 자체는 그대로라
    saturate 문제는 남지만, 문턱(0.65) 대비 여유가 줄어 0.65
    통과가 non-alpha 보너스 유무에 더 민감해진다.
  - **R2(그날 cross-sectional z-score 재정규화)**: 그날 전체
    평가 가능 universe(quintile 컷 이전, 87종목 중 신호 산출
    가능한 전체) 기준 `z = (signal_raw - day_mean) / day_std`를
    구하고, 이 z를 normalize에 통과시킨다 — `0.80 *
    normalize(z)`. 이는 신호의 절대 스케일이 아니라 "그날 다른
    종목 대비 상대적으로 얼마나 강한가"로 재정의하는 방식이다.
  - **R3(그날 percentile 기반 스케일링)**: 그날 전체 universe
    기준 signal의 백분위(0~1)를 그대로 alpha 항에 사용한다 —
    `0.80 * day_percentile_rank(signal_raw)`(normalize 불필요,
    이미 [0,1]로 유계). 상위 20% 멤버는 백분위가 대략 0.80~1.00
    구간에 분포해, saturate 없이 자연스럽게 그라데이션이 생긴다.

funnel은 §18과 동일한 5단계(candidate→eligible→selected→would_buy→
blocked_by_*)를 그대로 재사용하고, MFE/MAE도 동일 방식으로 계측한다.
2차(3년)/1차(최근 12개월)/전반부/후반부 4개 창 모두 반복한다.

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
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_alpha_layer_score_rescaling_comparison")

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
_ALPHA_W_R1_REDUCED = 0.50  # R1: 가중치 축소(0.80 → 0.50)


def _collect_symbol_rows(symbol: str, bars: list, market_common_regime_by_date: dict[str, str]) -> list[dict]:
    """§18의 수집 로직 재사용 + entry_score_b는 여기서 만들지 않고
    원시 alpha 신호·non_alpha 항만 저장한다(재보정 변형별 계산은
    day-level 통계가 필요해 전체 수집 이후 별도 단계에서 수행)."""
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


def _attach_day_level_rescaled_scores(rows: list[dict]) -> None:
    """그날 전체 evaluable universe(신호 산출 가능한 전체 종목) 기준
    z-score/percentile을 계산해 R2/R3용 재보정 alpha 값을 각 row에
    부착한다. candidate 정의(quintile 컷)는 바꾸지 않는다 — 이
    함수는 entry_score 계산에 쓰일 재보정 값만 추가한다."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["regime_conditional_signal"] is not None:
            by_date[r["trade_date"]].append(r)

    for day_rows in by_date.values():
        signals = [r["regime_conditional_signal"] for r in day_rows]
        n = len(signals)
        day_mean = _mean(signals)
        day_std = _stdev(signals) if n > 1 else 0.0
        sorted_signals = sorted(signals)

        for r in day_rows:
            s = r["regime_conditional_signal"]
            z = (s - day_mean) / day_std if day_std else 0.0
            r["z_score"] = z
            if n > 1:
                idx = bisect.bisect_left(sorted_signals, s)
                r["day_percentile"] = idx / (n - 1)
            else:
                r["day_percentile"] = 0.5


def _entry_score_variants(row: dict) -> dict:
    """R0~R3 4개 재보정 시나리오의 entry_score_b를 계산한다."""
    non_alpha_b = row["non_alpha_b"]
    signal = row["regime_conditional_signal"]
    if signal is None:
        return {"R0_raw": None, "R1_weight_down": None, "R2_zscore": None, "R3_percentile": None}

    r0 = _clamp01(_ALPHA_W_NEW_SIGNAL * _normalize_signed_score(signal) + non_alpha_b)
    r1 = _clamp01(_ALPHA_W_R1_REDUCED * _normalize_signed_score(signal) + non_alpha_b)
    r2 = _clamp01(_ALPHA_W_NEW_SIGNAL * _normalize_signed_score(row.get("z_score", 0.0)) + non_alpha_b)
    r3 = _clamp01(_ALPHA_W_NEW_SIGNAL * row.get("day_percentile", 0.5) + non_alpha_b)
    return {"R0_raw": r0, "R1_weight_down": r1, "R2_zscore": r2, "R3_percentile": r3}


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


def _funnel_for_variant(rows: list[dict], variant_key: str) -> dict:
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("regime_conditional_signal") is not None:
            by_date[r["trade_date"]].append(r)

    candidates: list[dict] = []
    eligible_rows: list[dict] = []
    selected_rows: list[dict] = []
    would_buy_rows: list[dict] = []
    blocked_by_eligibility: list[dict] = []
    blocked_by_score_threshold: list[dict] = []

    for day_rows in by_date.values():
        if len(day_rows) < 5:
            continue
        ordered = sorted(day_rows, key=lambda r: r["regime_conditional_signal"], reverse=True)
        q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
        day_candidates = ordered[:q]
        candidates.extend(day_candidates)

        day_selected_ranked = []
        for r in day_candidates:
            score = r["score_variants"][variant_key]
            if not r["eligible"]:
                blocked_by_eligibility.append(r)
                continue
            eligible_rows.append(r)
            if score is not None and score >= BUY_CANDIDATE_THRESHOLD:
                selected_rows.append(r)
                day_selected_ranked.append(r)
            else:
                blocked_by_score_threshold.append(r)

        day_selected_ranked.sort(key=lambda r: r["score_variants"][variant_key], reverse=True)
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
        "would_buy_rate_of_selected": round(n_would_buy / max(n_selected, 1) * 100, 2),
        "by_stage_horizon": {},
        "mfe_mae_would_buy": {},
    }
    for h in FORWARD_HORIZONS_FOCUS:
        report["by_stage_horizon"][f"T+{h}"] = _summarize([r[f"fwd_{h}"] for r in funnel["would_buy"]], h)
        report["mfe_mae_would_buy"][f"T+{h}"] = _mfe_mae_summary(funnel["would_buy"], h)
    return report


def _analyze_window(rows: list[dict], window_label: str) -> dict:
    print(f"\n=== {window_label} (표본 {len(rows)}건) ===")

    variant_keys = ["R0_raw", "R1_weight_down", "R2_zscore", "R3_percentile"]
    window_report: dict = {"window": window_label, "variants": {}}

    for vkey in variant_keys:
        funnel = _funnel_for_variant(rows, vkey)
        report = _funnel_report(funnel)
        window_report["variants"][vkey] = report
        print(f"  [{vkey}] candidate={report['candidate_n']}, "
              f"eligible={report['eligible_n']}, "
              f"selected={report['selected_n']}(selected_rate_of_eligible="
              f"{report['selected_rate_of_eligible']}%), "
              f"would_buy={report['would_buy_n']}, "
              f"blocked_score={report['blocked_by_score_threshold_n']}")
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
    for r in all_rows:
        r["score_variants"] = _entry_score_variants(r)

    last_date = max(datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in all_rows)
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    recent_rows = [r for r in all_rows if r["trade_date"] >= cutoff]
    first_half, second_half = _split_first_second_half(all_rows)

    print("\n=== 새 alpha entry_score 스케일 재보정 shadow 비교(R0 기준선/R1/R2/R3) ===")
    print(f"전체 3년 표본: {len(all_rows)}건, 최근 12개월(cutoff={cutoff}) 표본: {len(recent_rows)}건")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples_3y": len(all_rows),
        "total_rolling_samples_recent_12m": len(recent_rows),
        "recent_window_cutoff": cutoff,
        "variants_tested": ["R0_raw(기준선)", "R1_weight_down(0.80→0.50)",
                             "R2_zscore(그날 cross-sectional z-score)",
                             "R3_percentile(그날 cross-sectional percentile)"],
        "windows": {},
    }

    report["windows"]["supplementary_3y"] = _analyze_window(all_rows, "2차(3년, 전체 표본)")
    report["windows"]["primary_recent_12m"] = _analyze_window(recent_rows, "1차(최근 12개월)")
    report["windows"]["3y_first_half"] = _analyze_window(first_half, "3년 전반부")
    report["windows"]["3y_second_half"] = _analyze_window(second_half, "3년 후반부")

    out_path = "logs/signal_ic_alpha_layer_score_rescaling_comparison_2026-07-16.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
