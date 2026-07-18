#!/usr/bin/env python3
"""SPPV-2.56 — entry_score 코드 반영 절차 구체화: 이 세션 내내 사용한
수작업 재구현(`_non_alpha`)이 실제 운영 함수(`_build_entry_score`)와
정확히 일치하는지 shadow 검증(read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §38의 보조
잔여 조건 "entry_score 코드 반영 절차"를 이번 턴에 전진시킨다.

**배경**: `_build_entry_score`(`deterministic_trigger_engine.py:
1115-1170`)는 시나리오 A(현행 regime)로는 이미 이전 스크립트
(`validate_alpha_layer_buy_funnel_comparison.py`,
`validate_r3b_point_in_time_pipeline_shadow.py`)에서 직접 호출돼
왔다. **[SPPV-2.57에서 정정]** 다만 SPPV-2.46부터 이번 세션 내내,
R3b+entry_score risk_off_penalty 제거(B 시나리오, `risk_tone=
"neutral"`로 치환한 market_regime)의 non-alpha(regime/strategy/
activity 조정) 부분은 검증 스크립트마다 `_non_alpha`라는 이름의
**수작업 재구현 함수**로만 계산해왔다 — **B 시나리오(neutral 치환)
입력으로 `_build_entry_score`를 직접 호출한 적은 이 검증 이전까지
없었다.** 코드 대조 결과 `_build_entry_score`에는 `_non_alpha`가
누락한 항목이 있다: portfolio_allocation 예산 보너스/차단 패널티
(+0.10/-0.20, 1143-1149행), source_type 조정(market_overlay +0.05
/ held_position -0.35, 1158-1163행), 그리고 최종 `_clamp()`(1170행).
이 세션에서는 항상 `source_type="core"`, `portfolio_allocation=
None`으로 호출해 앞의 두 항목은 이론상 no-op이었지만, **실제로
no-op인지, 그리고 clamp를 포함해도 결과가 완전히 같은지는 지금까지
한 번도 직접 검증되지 않았다.**

이는 단순한 문구 정리가 아니라, **entry_score 코드 반영 절차(실제
운영 코드 변경 PR 작성)의 전제조건**이다 — 지금까지 이 세션에서
계산한 모든 B 시나리오 funnel·수익률 결과가 실제 운영 코드가
그대로 반영됐을 때의 결과와 일치하는지 확인되지 않으면, "이 조합을
운영에 반영하자"는 권고 자체의 신뢰도가 흔들린다. 이번 검증으로
일치가 확인되면 코드 반영 절차를 실제로 착수해도 좋다는 근거가
되고, 불일치가 발견되면 지금까지의 결과를 재검토해야 한다는 뜻이다.

**방법**: 3년 전체 core 87종목의 모든 거래일 point-in-time
스냅샷(candidate 선별·eligibility 필터링 없이 모집단 전체, 약
5.8만 행)에 대해 각 행마다 실제
`_build_entry_score`를 `overall=fast=slow=0.0`으로 호출해(이러면
alpha 항은 `_normalize_signed_score(0)=0.5` 기준의 상수
`0.45*0.5+0.20*0.5+0.15*0.5=0.40`이 되어 조정 항만 분리해낼 수
있다) `real_adjustment = 실제 반환값 - 0.40`을 구하고, 같은 행의
`_non_alpha(neutral_regime)`(수작업 재구현)와 직접 비교한다. 두
값의 차이가 0(부동소수점 오차 이내)이면 완전 일치, 아니면 실제
발산 지점을 보고한다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음. 운영 코드
(`deterministic_trigger_engine.py`)는 이번 검증에서도 전혀 수정하지
않는다 — `_build_entry_score`를 있는 그대로 import해서 호출할 뿐이다.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import sys as _sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_r3b_entry_score_shadow_fidelity")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

_STRATEGY_ALIGNMENT_BONUS = 0.05
_STRATEGY_ALIGNMENT_SET = {"swing_momentum", "event_continuation"}
_ALPHA_AT_ZERO = 0.45 * 0.5 + 0.20 * 0.5 + 0.15 * 0.5  # = 0.40, _normalize_signed_score(0)=0.5 기준
_EPS = 1e-9


def _non_alpha_shadow(regime_obj, strategy_selection, snapshot) -> float:
    """이 세션 내내 여러 스크립트에서 반복 사용된 수작업 재구현
    그대로(예: validate_r3b_stop_loss_ablation.py의 _non_alpha)."""
    from agent_trading.services.deterministic_trigger_engine import _build_relative_activity_score

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


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS
    from agent_trading.services.deterministic_trigger_engine import _build_entry_score
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot
    from agent_trading.services.strategy_selection import select_strategy

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")

    bench_bars = await _fetch_extended_bars(client, BENCHMARK_SYMBOL)
    market_common_regime_by_date, _ = _build_benchmark_daily_series(bench_bars)
    if not market_common_regime_by_date:
        raise SystemExit("시장 공통 국면 계산 실패")

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})
    n_checked = 0
    n_exact_match = 0
    max_abs_diff = 0.0
    mismatches: list[dict] = []
    fetch_failures: list[str] = []

    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        if len(bars) < _MIN_LOOKBACK + 5:
            fetch_failures.append(symbol)
            continue

        last_t = len(bars) - 1
        for t in range(_MIN_LOOKBACK - 1, last_t + 1):
            window = bars[: t + 1]
            try:
                features, card = build_signal_snapshot(symbol, window)
            except Exception:
                continue
            snapshot = SimpleNamespace(
                overall_score=float(card.overall_score), fast_score=float(card.fast_score),
                slow_score=float(card.slow_score),
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

            reason_codes: list[str] = []
            real_score_zero_alpha = _build_entry_score(
                overall=0.0, fast=0.0, slow=0.0,
                signal_feature_snapshot=snapshot, market_regime=neutral_regime,
                strategy_selection=strategy_selection, portfolio_allocation=None,
                source_type="core", reason_codes=reason_codes,
            )
            real_adjustment = real_score_zero_alpha - _ALPHA_AT_ZERO
            shadow_adjustment = _non_alpha_shadow(neutral_regime, strategy_selection, snapshot)

            diff = real_adjustment - shadow_adjustment
            n_checked += 1
            if abs(diff) <= _EPS:
                n_exact_match += 1
            else:
                max_abs_diff = max(max_abs_diff, abs(diff))
                if len(mismatches) < 20:
                    mismatches.append({
                        "symbol": symbol, "trade_date": bars[t].timestamp.strftime("%Y-%m-%d"),
                        "real_adjustment": round(real_adjustment, 6),
                        "shadow_adjustment": round(shadow_adjustment, 6),
                        "diff": round(diff, 6),
                    })

        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 검사 %d건, 불일치 %d건", idx, len(symbols), n_checked, n_checked - n_exact_match)

    print("\n=== entry_score shadow 재구현 정합성 검증 (3년 전체 시점 스냅샷, 모집단 전체) ===")
    print(f"검사 표본 수: {n_checked}")
    print(f"완전 일치: {n_exact_match}건 ({round(n_exact_match / n_checked * 100, 4) if n_checked else None}%)")
    print(f"불일치: {n_checked - n_exact_match}건, 최대 절대 오차: {max_abs_diff}")
    if mismatches:
        print(f"불일치 샘플(최대 20건): {mismatches}")

    report = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "n_checked": n_checked,
        "n_exact_match": n_exact_match,
        "n_mismatch": n_checked - n_exact_match,
        "match_rate": round(n_exact_match / n_checked, 6) if n_checked else None,
        "max_abs_diff": max_abs_diff,
        "mismatch_samples": mismatches,
    }
    out_path = "logs/signal_ic_r3b_entry_score_shadow_fidelity_2026-07-18.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
