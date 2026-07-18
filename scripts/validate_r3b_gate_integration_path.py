#!/usr/bin/env python3
"""SPPV-2.59 — `§21 게이트`(regime_switch_v1)의 config override를
실제 판단 경로(`assess_deterministic_triggers`, 실제 BUY 후보 판정
함수)에서 검증(read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §48 참고.

§47(SPPV-2.58)은 `services/regime_switch_gate.py`를 신규 격리 모듈로
만들었을 뿐, 실제로 소비되는 경로에 연결하지는 않았다 — 이번 턴은
그 미완 지점을 메운다. `deterministic_trigger_engine.py`의
`assess_deterministic_triggers`(실제 BUY_CANDIDATE 판정 함수, 실제
운영에서 주문 결정으로 이어지는 함수)에 신규 optional 파라미터
`regime_switch_v1_trigger_status`/`regime_switch_v1_gate_override_
enabled`를 추가해 게이트를 실제 판정 로직(entry_score/eligibility
와 함께 `buy_candidate` bool을 결정하는 조건문)에 연결했다.

**이 스크립트가 증명하는 것**: 동일한 R3b-스타일 candidate 입력
(실제 `build_signal_snapshot`/`classify_market_regime`/`select_
strategy`로 만든 실제 데이터, `risk_tone="neutral"`로 치환한 B
시나리오 regime)을 **동일한 실제 함수 `assess_deterministic_
triggers`**에 3가지 방식으로 호출해 `buy_candidate` 결과가 실제로
달라지는지 확인한다:

  A. 게이트 파라미터 없이 호출(기존 호출부와 동일한 방식) — baseline.
  B. `regime_switch_v1_trigger_status="NOT_TRIGGERED"`(실제 관측
     상태), `override_enabled=False`(기본값) — 게이트가 실제로
     BUY_CANDIDATE를 차단하는지 확인.
  C. 동일 trigger_status, `override_enabled=True` — override가
     실제로 그 차단을 해제해 baseline과 같은 결과로 되돌리는지 확인.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음.
`_bars_cache_core87_3y_2026-07-14` 캐시를 그대로 재사용(신규 KIS
호출 0건 목표).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sys as _sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_r3b_gate_integration_path")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")


def _find_qualifying_candidate(client, symbols, min_lookback):
    """entry_score(neutral regime, 실제 _build_entry_score 기준) >=
    0.65이고 eligible=True인 실제 R3b-스타일 candidate 1건을 찾는다."""
    import asyncio

    from agent_trading.services.deterministic_trigger_engine import (
        _assess_buy_eligibility,
        assess_deterministic_triggers,
    )
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot
    from agent_trading.services.strategy_selection import select_strategy
    from validate_signal_predictive_power_v4_extended_period import _fetch_extended_bars

    async def _scan():
        for symbol in symbols:
            bars = await _fetch_extended_bars(client, symbol)
            if len(bars) < min_lookback + 5:
                continue
            for t in range(min_lookback - 1, len(bars) - 1):
                window = bars[: t + 1]
                try:
                    features, card = build_signal_snapshot(symbol, window)
                except Exception:
                    continue
                snapshot = SimpleNamespace(
                    overall_score=float(card.overall_score), fast_score=float(card.fast_score),
                    slow_score=float(card.slow_score),
                    return_1m_pct=features.return_1m_pct, return_3m_pct=features.return_3m_pct,
                    price_vs_sma_20_pct=features.price_vs_sma_20_pct,
                    price_vs_sma_60_pct=features.price_vs_sma_60_pct,
                    volatility_20d_pct=features.volatility_20d_pct, atr_14_pct=features.atr_14_pct,
                    volume_surge_ratio=features.volume_surge_ratio,
                    average_volume_20d=features.average_volume_20d,
                    average_turnover_20d=features.average_turnover_20d,
                    turnover_surge_ratio=features.turnover_surge_ratio,
                    rsi_14=features.rsi_14, sma_5=features.sma_5, sma_20=features.sma_20,
                    sma_60=features.sma_60, component_scores_json=None,
                )
                per_symbol_regime = classify_market_regime(snapshot)
                neutral_regime = (
                    dataclasses.replace(per_symbol_regime, risk_tone="neutral")
                    if per_symbol_regime else None
                )
                strategy_selection = select_strategy(market_regime=per_symbol_regime, source_type="core")

                assessment = assess_deterministic_triggers(
                    source_type="core",
                    signal_feature_snapshot=snapshot,
                    market_regime=neutral_regime,
                    strategy_selection=strategy_selection,
                    portfolio_allocation=None,
                    position_snapshot=None,
                )
                if assessment is not None and assessment.buy_candidate:
                    return {
                        "symbol": symbol,
                        "trade_date": bars[t].timestamp.strftime("%Y-%m-%d"),
                        "snapshot": snapshot,
                        "neutral_regime": neutral_regime,
                        "strategy_selection": strategy_selection,
                        "baseline_assessment": assessment,
                    }
        return None

    return asyncio.run(_scan())


def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS
    from agent_trading.services.deterministic_trigger_engine import assess_deterministic_triggers

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")

    sys_path_added = "scripts"
    if sys_path_added not in _sys.path:
        _sys.path.insert(0, sys_path_added)
    from validate_signal_predictive_power_v2 import _MIN_LOOKBACK  # noqa: E402

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {"069500"})
    print("\n=== 1. 실제 R3b-스타일 BUY_CANDIDATE 후보 탐색(실제 assess_deterministic_triggers 호출) ===")
    found = _find_qualifying_candidate(client, symbols, _MIN_LOOKBACK)
    if found is None:
        raise SystemExit("qualifying BUY_CANDIDATE를 찾지 못함 — 표본 확장 필요")

    print(f"후보 발견: {found['symbol']} / {found['trade_date']}")
    baseline = found["baseline_assessment"]
    print(f"[A] 게이트 파라미터 없음(기존 호출부와 동일): buy_candidate={baseline.buy_candidate}, "
          f"entry_score={baseline.entry_score}, reason_codes={baseline.reason_codes}")

    print("\n=== 2. 동일 입력을 실제 함수에 §21 게이트 파라미터와 함께 재호출 ===")
    assessment_off = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=found["snapshot"],
        market_regime=found["neutral_regime"],
        strategy_selection=found["strategy_selection"],
        portfolio_allocation=None,
        position_snapshot=None,
        regime_switch_v1_trigger_status="NOT_TRIGGERED",
        regime_switch_v1_gate_override_enabled=False,
    )
    print(f"[B] trigger_status=NOT_TRIGGERED, override=False(기본값): "
          f"buy_candidate={assessment_off.buy_candidate}, "
          f"regime_switch_v1_gate_open={assessment_off.metadata.get('regime_switch_v1_gate_open')}, "
          f"reason_codes={assessment_off.reason_codes}")

    assessment_on = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=found["snapshot"],
        market_regime=found["neutral_regime"],
        strategy_selection=found["strategy_selection"],
        portfolio_allocation=None,
        position_snapshot=None,
        regime_switch_v1_trigger_status="NOT_TRIGGERED",
        regime_switch_v1_gate_override_enabled=True,
    )
    print(f"[C] trigger_status=NOT_TRIGGERED, override=True: "
          f"buy_candidate={assessment_on.buy_candidate}, "
          f"regime_switch_v1_gate_open={assessment_on.metadata.get('regime_switch_v1_gate_open')}, "
          f"reason_codes={assessment_on.reason_codes}")

    gate_actually_blocks = baseline.buy_candidate is True and assessment_off.buy_candidate is False
    override_actually_restores = assessment_on.buy_candidate == baseline.buy_candidate

    print(f"\n게이트가 실제 판정 경로에서 BUY_CANDIDATE를 실제로 차단함: {gate_actually_blocks}")
    print(f"override가 실제 판정 경로에서 그 차단을 실제로 해제해 baseline과 동일해짐: {override_actually_restores}")

    report = {
        "as_of": datetime.now(_KST).isoformat(),
        "candidate": {"symbol": found["symbol"], "trade_date": found["trade_date"]},
        "A_baseline_no_gate_param": {
            "buy_candidate": baseline.buy_candidate,
            "entry_score": baseline.entry_score,
            "reason_codes": list(baseline.reason_codes),
        },
        "B_gate_override_off_not_triggered": {
            "buy_candidate": assessment_off.buy_candidate,
            "regime_switch_v1_gate_open": assessment_off.metadata.get("regime_switch_v1_gate_open"),
            "regime_switch_v1_gate_override_applied": assessment_off.metadata.get(
                "regime_switch_v1_gate_override_applied"
            ),
            "reason_codes": list(assessment_off.reason_codes),
        },
        "C_gate_override_on": {
            "buy_candidate": assessment_on.buy_candidate,
            "regime_switch_v1_gate_open": assessment_on.metadata.get("regime_switch_v1_gate_open"),
            "regime_switch_v1_gate_override_applied": assessment_on.metadata.get(
                "regime_switch_v1_gate_override_applied"
            ),
            "reason_codes": list(assessment_on.reason_codes),
        },
        "gate_actually_blocks_real_path": gate_actually_blocks,
        "override_actually_restores_real_path": override_actually_restores,
        "note": (
            "assess_deterministic_triggers는 deterministic_trigger_engine.py의 실제 운영 함수이며 "
            "이번 검증에서 신규 optional 파라미터(regime_switch_v1_trigger_status/"
            "regime_switch_v1_gate_override_enabled)를 통해 실제로 호출됐다. "
            "기존 호출부(이 파라미터를 모르는 모든 호출)는 기본값 None으로 게이트 체크가 "
            "완전히 비활성화되어 동작이 전혀 바뀌지 않는다."
        ),
    }
    out_path = "logs/signal_ic_r3b_gate_integration_path_2026-07-18.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    main()
