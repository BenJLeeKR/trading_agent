#!/usr/bin/env python3
"""`entry_score` 중복 penalty ablation — Phase 0(재구성 가능 구간) shadow 분석
(read-only).

``plans/[ANALYSIS] foundational_design_review_objective_alignment.md`` §2
(근본 원인 진단 — "공격·방어 책임 중복"), `plans/[DESIGN] signal_
predictive_power_validation.md`(§1 Phase 0~3 경계), `plans/[DESIGN]
regime_conditional_entry_signal_v1.md`(§3 entry_score 통합 방안) 참고.

§2(근본 진단)는 코드 검토만으로 "약한 signal이 이미 entry_score에
반영된 뒤 risk_off_penalty가 다시 차감되고, BUY eligibility가 동일한
bearish_trend+risk_off를 다시 차단한다"는 **삼중 중복**을 지적했다.
이 스크립트는 그 지적을 **오늘 시점 실제 데이터로 정량화**한다 —
운영 DB(`trade_decisions`)는 조회하지 않는다(자동 승인 경계 밖의
프로덕션 읽기이므로 이번 턴에서 시도하지 않았다). 대신 SPPV 트랙
전체가 지금까지 해온 것과 동일한 방식 — **운영 코드
(`build_signal_snapshot`, `classify_market_regime`, `_build_entry_score`,
`_assess_buy_eligibility`)를 그대로 재사용해 read-only로 재계산**하는
방식을 그대로 따른다.

Phase 0(재구성 가능) vs Phase 1~3(외부 상태 필요, 재구성 불가) 경계는
`signal_predictive_power_validation.md` §1에서 이미 확립됐다:
  - 재구성 가능: `overall_score`/`fast_score`/`slow_score`(signal_backbone
    순수 함수), `market_regime`(종목 자신의 스냅샷으로 classify_market_
    regime 호출 — production과 동일한 **종목별(per-symbol)** 국면).
  - 재구성 불가(이번 스크립트에서 `None`으로 둠, 운영 함수의 자연스러운
    분기를 그대로 이용): `strategy_selection`, `portfolio_allocation`,
    `signal_feature_snapshot`의 거래량 지표(있으면 사용, 없어도 동작).

이 스크립트가 실제로 하는 것: 오늘(3년 캐시 기준 최신 봉) 87종목에
대해, 운영 함수 `_build_entry_score()`/`_assess_buy_eligibility()`를
**그대로 호출**하되 세 가지 penalty 축(entry_score의 regime bonus/
penalty, eligibility의 regime 차단, eligibility의 signal floor 차단)이
각각 개별적으로 어떤 종목을 걸러내는지 독립적으로 평가해 **중복(교집합)
크기를 정량화**한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shadow_entry_score_penalty_ablation")

_KST = timezone(timedelta(hours=9))

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    _fetch_extended_bars,
)


def _reconstruct_symbol_state(symbol: str, bars: list) -> dict | None:
    """Phase 0 재구성 가능 구간만으로 오늘 시점 signal + regime을 복원한다."""
    from types import SimpleNamespace

    from agent_trading.services.deterministic_trigger_engine import (
        _assess_buy_eligibility,
        _build_entry_score,
    )
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot

    if len(bars) < _MIN_LOOKBACK:
        return None

    t = len(bars) - 1
    try:
        features, card = build_signal_snapshot(symbol, bars[: t + 1])
    except Exception:
        return None

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
    regime = classify_market_regime(snapshot)

    # (a) 운영 함수 그대로 호출 — baseline entry_score(재구성 가능 항만 반영,
    # allocation/strategy=None은 운영 함수가 자연스럽게 건너뛴다)
    reason_codes_baseline: list[str] = []
    entry_score_baseline = _build_entry_score(
        overall=overall,
        fast=fast,
        slow=slow,
        signal_feature_snapshot=snapshot,
        market_regime=regime,
        strategy_selection=None,
        portfolio_allocation=None,
        source_type="core",
        reason_codes=reason_codes_baseline,
    )

    # (b) regime을 제거한 entry_score — "regime penalty 없는" 반사실
    reason_codes_no_regime: list[str] = []
    entry_score_no_regime_penalty = _build_entry_score(
        overall=overall,
        fast=fast,
        slow=slow,
        signal_feature_snapshot=snapshot,
        market_regime=None,
        strategy_selection=None,
        portfolio_allocation=None,
        source_type="core",
        reason_codes=reason_codes_no_regime,
    )

    # (c) 운영 함수 그대로 호출 — eligibility(연쇄 실패라 첫 실패 사유만 나옴)
    eligible_baseline, eligibility_reasons = _assess_buy_eligibility(
        source_type="core",
        coverage_score=1.0,
        allocation_budget_ok=True,
        market_regime=regime,
        overall=overall,
        slow=slow,
        signal_feature_snapshot=snapshot,
        portfolio_allocation=None,
        ranking_score=None,
    )

    # (d) 세 penalty 축을 "독립적으로" 평가(운영 함수의 연쇄 return 없이,
    # 같은 조건식만 그대로 인용해 중복/교집합을 셀 수 있게 함 — eligibility
    # 로직 자체를 바꾸지 않고 분석 목적으로만 별도 평가)
    entry_score_regime_penalty_applied = (
        regime is not None and regime.risk_tone == "risk_off"
    )
    eligibility_regime_block_would_fire = (
        regime is not None
        and regime.risk_tone == "risk_off"
        and regime.regime_label == "bearish_trend"
    )
    eligibility_signal_floor_would_fire = (overall < -0.10) or (slow < -0.15)

    axes_fired = sum(
        [
            entry_score_regime_penalty_applied,
            eligibility_regime_block_would_fire,
            eligibility_signal_floor_would_fire,
        ]
    )

    return {
        "symbol": symbol,
        "trade_date": bars[t].timestamp.strftime("%Y-%m-%d"),
        "overall_score": overall,
        "fast_score": fast,
        "slow_score": slow,
        "regime_label": regime.regime_label if regime else None,
        "risk_tone": regime.risk_tone if regime else None,
        "entry_score_baseline": entry_score_baseline,
        "entry_score_no_regime_penalty": entry_score_no_regime_penalty,
        "entry_score_delta_from_regime_penalty": round(
            entry_score_no_regime_penalty - entry_score_baseline, 4
        ),
        "eligibility_baseline_pass": eligible_baseline,
        "eligibility_baseline_first_fail_reason": (
            eligibility_reasons[-1] if not eligible_baseline else None
        ),
        "axis_entry_score_regime_penalty": entry_score_regime_penalty_applied,
        "axis_eligibility_regime_block": eligibility_regime_block_would_fire,
        "axis_eligibility_signal_floor": eligibility_signal_floor_would_fire,
        "axes_fired_count": axes_fired,
    }


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})

    rows: list[dict] = []
    fetch_failures: list[str] = []
    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        row = _reconstruct_symbol_state(symbol, bars)
        if row is None:
            fetch_failures.append(symbol)
            continue
        rows.append(row)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 처리 완료", idx, len(symbols))

    n = len(rows)
    axis_a = sum(1 for r in rows if r["axis_entry_score_regime_penalty"])
    axis_b = sum(1 for r in rows if r["axis_eligibility_regime_block"])
    axis_c = sum(1 for r in rows if r["axis_eligibility_signal_floor"])
    overlap_ab = sum(
        1 for r in rows if r["axis_entry_score_regime_penalty"] and r["axis_eligibility_regime_block"]
    )
    overlap_ac = sum(
        1 for r in rows if r["axis_entry_score_regime_penalty"] and r["axis_eligibility_signal_floor"]
    )
    overlap_bc = sum(
        1 for r in rows if r["axis_eligibility_regime_block"] and r["axis_eligibility_signal_floor"]
    )
    overlap_abc = sum(1 for r in rows if r["axes_fired_count"] == 3)
    none_fired = sum(1 for r in rows if r["axes_fired_count"] == 0)

    report = {
        "as_of": datetime.now(_KST).isoformat(),
        "symbol_count_total": len(symbols),
        "symbol_count_reconstructed": n,
        "fetch_failures": fetch_failures,
        "venn": {
            "A_entry_score_regime_penalty": axis_a,
            "B_eligibility_regime_block": axis_b,
            "C_eligibility_signal_floor": axis_c,
            "A_and_B": overlap_ab,
            "A_and_C": overlap_ac,
            "B_and_C": overlap_bc,
            "A_and_B_and_C": overlap_abc,
            "none_fired": none_fired,
        },
        "eligibility_baseline_pass_count": sum(1 for r in rows if r["eligibility_baseline_pass"]),
        "eligibility_baseline_fail_count": sum(1 for r in rows if not r["eligibility_baseline_pass"]),
        "rows": rows,
    }

    print("\n=== entry_score 중복 penalty ablation — Phase 0 shadow 분석 ===")
    print(f"재구성 종목: {n}/{len(symbols)} (실패 {len(fetch_failures)})")
    print(f"[축 A] entry_score regime penalty(-0.15) 적용: {axis_a}건")
    print(f"[축 B] eligibility regime 차단(bearish+risk_off): {axis_b}건")
    print(f"[축 C] eligibility signal floor(overall<-0.10 또는 slow<-0.15): {axis_c}건")
    print(f"[교집합] A∩B={overlap_ab}, A∩C={overlap_ac}, B∩C={overlap_bc}, A∩B∩C={overlap_abc}")
    print(f"[비교] 3축 중 아무것도 안 걸림={none_fired}건")
    print(f"[운영 eligibility 함수 그대로 호출] 통과={report['eligibility_baseline_pass_count']}건, "
          f"차단={report['eligibility_baseline_fail_count']}건")

    out_path = "logs/shadow_entry_score_penalty_ablation_2026-07-15.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
