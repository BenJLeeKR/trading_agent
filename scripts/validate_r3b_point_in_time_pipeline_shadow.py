#!/usr/bin/env python3
"""SPPV-2.42 — R3b를 실제 point-in-time `entry_score` 파이프라인에
한 단계 더 가깝게 연결한 shadow 검증 (read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §31.4(다음
단계 3 — point-in-time `entry_score` 파이프라인 반영 shadow 실행
설계) 참고.

**기존 검증(§18~§30)이 이미 실제 운영 함수를 상당 부분 재사용해
왔다는 것을 먼저 확인한다** — `scripts/validate_alpha_layer_score_
rescaling_comparison.py`/`validate_alpha_layer_buy_funnel_
comparison.py`는 이미 `signal_backbone.build_signal_snapshot`(실제
피처/스코어 계산), `deterministic_trigger_engine._assess_buy_
eligibility`, `deterministic_trigger_engine._build_entry_score`를
운영 코드에서 직접 import해 호출해왔다 — 이 부분은 "오프라인
재구현"이 아니라 이미 실제 함수 호출이었다.

**다만 한 가지 실제 조정항이 그동안 누락돼 있었다** — `_build_entry_
score()`는 `strategy_selection`(선호 전략이 `swing_momentum`/
`event_continuation`이면 +0.05 보너스, `deterministic_trigger_
engine.py`의 `_build_entry_score` 참고)을 받는데, 기존 검증들은
이 인자에 항상 `None`을 넘겨왔다(포트폴리오 상태가 필요한 `alloc
ation`/실거래 이력이 없는 `position` 계열과 달리, `strategy_
selection`은 `market_regime`과 `source_type`만으로 계산 가능한
순수 함수라 **오프라인에서도 실제 값으로 채울 수 있다**). 이
스크립트는 실제 `select_strategy()`를 호출해 이 누락된 조정항을
채우고, `entry_score_a`(현행 alpha, A 시나리오)와 R0/R3b(가상
alpha 교체) 양쪽에 동일하게 반영한 뒤 8개 창 BUY funnel을 다시
계측해 §20/§27의 기존 결과와 비교한다.

`portfolio_allocation`(계좌 잔고/포지션 필요)은 여전히 재구성
불가능해 이전과 동일하게 `None`으로 둔다(§18부터 이어진 관례,
이번 턴 범위 밖 — 실거래 계좌 상태가 필요해 shadow로 재현할 수
없다).

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
logger = logging.getLogger("validate_r3b_point_in_time_pipeline_shadow")

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
)
from validate_alpha_layer_r3_reproducibility import (  # noqa: E402
    _analyze_window,
    _split_into_quarters,
)
from validate_alpha_layer_score_rescaling_comparison import _attach_day_level_rescaled_scores  # noqa: E402
from validate_alpha_layer_virtual_buy_funnel_extended import BUY_CANDIDATE_THRESHOLD  # noqa: E402
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK, _mean  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

_ROUND_TRIP_COST_BPS = 30.0
RECENT_WINDOW_CALENDAR_DAYS = 365
TOP_QUINTILE_FRACTION = 0.20
_STRATEGY_ALIGNMENT_BONUS = 0.05  # _build_entry_score()의 실제 상수(신규 아님)
_STRATEGY_ALIGNMENT_SET = {"swing_momentum", "event_continuation"}


def _collect_symbol_rows_with_strategy(
    symbol: str, bars: list, market_common_regime_by_date: dict[str, str]
) -> list[dict]:
    """§18/§19의 수집 로직에 실제 `select_strategy()` 조정항을 추가한
    버전. 나머지(피처/스코어/eligibility/entry_score_a 계산)는 §18
    부터 이미 실제 운영 함수(`build_signal_snapshot`, `_assess_buy_
    eligibility`, `_build_entry_score`)를 그대로 호출해왔다 — 이번
    턴은 그중 빠져 있던 `strategy_selection` 인자 하나만 실제 값으로
    채운다."""
    from agent_trading.services.deterministic_trigger_engine import (
        _assess_buy_eligibility,
        _build_entry_score,
    )
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot
    from agent_trading.services.strategy_selection import select_strategy
    from types import SimpleNamespace

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
        strategy_selection = select_strategy(market_regime=per_symbol_regime, source_type="core")

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

        # 실제 entry_score_a — strategy_selection을 실제 값으로 채운 버전(이번 턴의 유일한 신규 반영분)
        entry_score_a = _build_entry_score(
            overall=overall,
            fast=fast,
            slow=slow,
            signal_feature_snapshot=snapshot,
            market_regime=per_symbol_regime,
            strategy_selection=strategy_selection,
            portfolio_allocation=None,
            source_type="core",
            reason_codes=[],
        )

        non_alpha_b, _ = _entry_score_non_alpha_terms(per_symbol_regime, snapshot)
        if strategy_selection is not None and strategy_selection.preferred_strategy in _STRATEGY_ALIGNMENT_SET:
            non_alpha_b += _STRATEGY_ALIGNMENT_BONUS

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
            "preferred_strategy": strategy_selection.preferred_strategy if strategy_selection else None,
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


def _attach_candidate_only_percentile(rows: list[dict]) -> None:
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


def _score_b_r3b(row: dict) -> float | None:
    if row.get("candidate_percentile") is None:
        return None
    return _clamp01(_ALPHA_W_NEW_SIGNAL * row["candidate_percentile"] + row["non_alpha_b"])


SCENARIOS = {
    "A_current_alpha_with_strategy": ("current_alpha_composite", _score_a),
    "B_R0_no_rescale": ("regime_conditional_signal", _score_b_r0),
    "B_R3b_percentile_candidateonly": ("regime_conditional_signal", _score_b_r3b),
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
    strategy_counts: dict[str, int] = defaultdict(int)
    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        if len(bars) < _MIN_LOOKBACK + max(FORWARD_HORIZONS_FOCUS) + 5:
            fetch_failures.append(symbol)
            continue
        rows = _collect_symbol_rows_with_strategy(symbol, bars, market_common_regime_by_date)
        all_rows.extend(rows)
        for r in rows:
            strategy_counts[r["preferred_strategy"] or "none"] += 1
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_rows))

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_rows), len(fetch_failures))
    logger.info("preferred_strategy 분포: %s", dict(strategy_counts))

    _attach_day_level_rescaled_scores(all_rows)
    _attach_candidate_only_percentile(all_rows)

    last_date = max(datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in all_rows)
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    recent_rows = [r for r in all_rows if r["trade_date"] >= cutoff]
    first_half, second_half = _split_first_second_half(all_rows)
    quarters = _split_into_quarters(all_rows)

    print("\n=== R3b point-in-time entry_score 파이프라인 shadow(strategy_selection 반영) ===")
    print(f"전체 3년 표본: {len(all_rows)}건, preferred_strategy 분포: {dict(strategy_counts)}")

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "preferred_strategy_distribution": dict(strategy_counts),
        "scenarios_tested": list(SCENARIOS.keys()),
        "windows": {},
    }

    # _analyze_window은 SCENARIOS 전역을 참조하므로 모듈 레벨에 주입한다
    import validate_alpha_layer_r3_reproducibility as _repro_mod
    _repro_mod.SCENARIOS = SCENARIOS

    report["windows"]["supplementary_3y"] = _analyze_window(all_rows, "2차(3년, 전체 표본)")
    report["windows"]["primary_recent_12m"] = _analyze_window(recent_rows, "1차(최근 12개월)")
    report["windows"]["3y_first_half"] = _analyze_window(first_half, "3년 전반부")
    report["windows"]["3y_second_half"] = _analyze_window(second_half, "3년 후반부")
    for i, q_rows in enumerate(quarters, start=1):
        if q_rows:
            report["windows"][f"quarter_{i}"] = _analyze_window(q_rows, f"3년 분기{i}")

    out_path = "logs/signal_ic_r3b_point_in_time_pipeline_shadow_2026-07-17.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
