#!/usr/bin/env python3
"""SPPV-2.60 — `§21 게이트`(regime_switch_v1)의 상위 호출부
(`services/decision_orchestrator.py`) 배선 검증(read-only, in-memory
repos, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §49 참고.

§48(SPPV-2.59)은 `deterministic_trigger_engine.py`의 `assess_
deterministic_triggers` **함수 내부**까지만 게이트를 연결했다 — 실제
상위 호출부인 `DecisionOrchestratorService`(`decision_orchestrator.
py`)는 그 신규 파라미터를 전혀 넘기지 않고 있었다("실제 판단 경로
연결 완료"라는 §48의 표현은 이 지점에서 과장이었다).

이번 스크립트는 그 gap이 실제로 메워졌는지, **`DecisionOrchestratorService`
를 실제로 구성(construct)하고 그 인스턴스의 실제 메서드 `_derive_
deterministic_context_components`(내부에서 `assess_deterministic_
triggers`를 호출하는 바로 그 코드)를 통해서** 검증한다 — 즉 `assess_
deterministic_triggers`를 스크립트가 직접 호출하는 것이 아니라,
`decision_orchestrator.py`를 실제로 거쳐서 호출되는 경로를 그대로
사용한다.

**Repos는 in-memory 더블**(`build_in_memory_repositories()`, 이
코드베이스의 기존 테스트 스위트 전반에서 쓰이는 표준 패턴)을 사용해
실제 Postgres 연결이나 KIS 호출 없이 순수 read-only로 검증한다 — DB
write, 주문 경로, broker submit이 전혀 발생하지 않는다.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_r3b_orchestrator_gate_wiring")

_KST = timezone(timedelta(hours=9))


async def _build_scenario():
    from agent_trading.domain.entities import (
        ConfigVersionEntity,
        InstrumentEntity,
        SignalFeatureSnapshotEntity,
    )
    from agent_trading.domain.enums import Environment, OrderSide, OrderType, TimeInForce
    from agent_trading.domain.models import SubmitOrderRequest
    from agent_trading.repositories.bootstrap import build_in_memory_repositories

    repos = build_in_memory_repositories()

    config_version = ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=uuid4(),
        environment=Environment.PAPER,
        version_tag="v1.0",
        config_json={"max_order_size": 100},
        checksum="abc123",
        activated_at=datetime.now(timezone.utc),
    )
    repos.config_versions._items[config_version.config_version_id] = config_version

    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="005930",
        market_code="KRX",
        asset_class="KR_STOCK",
        currency="KRW",
        name="삼성전자",
    )
    repos.instruments._items[instrument.instrument_id] = instrument

    # 실제 candidate가 BUY_CANDIDATE 자격을 확실히 얻도록 강한 bullish
    # 신호 값을 사용한다(entry_score >= 0.65, eligible=True 유도).
    snapshot = SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=uuid4(),
        instrument_id=instrument.instrument_id,
        timeframe="1d",
        snapshot_at=datetime.now(timezone.utc),
        feature_set_version="signal_backbone_v1",
        bar_count=80,
        fast_score=Decimal("0.85"),
        slow_score=Decimal("0.80"),
        overall_score=Decimal("0.90"),
        return_1m_pct=Decimal("6.00"),
        return_3m_pct=Decimal("15.00"),
        price_vs_sma_20_pct=Decimal("4.00"),
        price_vs_sma_60_pct=Decimal("8.00"),
        volatility_20d_pct=Decimal("18.00"),
        component_scores_json={},
    )
    await repos.signal_feature_snapshots.add(snapshot)

    request = SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="gate-wiring-001",
        correlation_id="gate-wiring-001",
        strategy_id=str(uuid4()),
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
        metadata={"source_type": "core"},
    )

    return repos, config_version, instrument, request


async def _derive_via_orchestrator(repos, config_version, instrument, request, **gate_kwargs):
    """실제 `DecisionOrchestratorService`를 구성하고, 그 실제 메서드를
    거쳐 `assess_deterministic_triggers`를 호출한다 — 이번 검증의 핵심."""
    from agent_trading.services.decision_orchestrator import DecisionOrchestratorService

    orchestrator = DecisionOrchestratorService(
        repos=repos, use_subprocess_isolation=False, **gate_kwargs
    )
    bundle = await orchestrator._derive_deterministic_context_components(
        request=request,
        config_version=config_version,
        instrument=instrument,
        position_snapshot=None,
        cash_balance_snapshot=None,
        risk_limit_snapshot=None,
    )
    return bundle


async def main() -> None:
    repos, config_version, instrument, request = await _build_scenario()

    print("\n=== 1. DecisionOrchestratorService 실제 구성 — 게이트 파라미터 없음(기존 방식) ===")
    bundle_a = await _derive_via_orchestrator(repos, config_version, instrument, request)
    trig_a = bundle_a.deterministic_trigger
    print(f"[A] buy_candidate={trig_a.buy_candidate}, entry_score={trig_a.entry_score}, "
          f"regime_switch_v1_gate_open={trig_a.metadata.get('regime_switch_v1_gate_open')}")

    print("\n=== 2. 동일 시나리오, DecisionOrchestratorService에 §21 게이트 config 전달 ===")
    bundle_b = await _derive_via_orchestrator(
        repos, config_version, instrument, request,
        regime_switch_v1_trigger_status="NOT_TRIGGERED",
        regime_switch_v1_gate_override_enabled=False,
    )
    trig_b = bundle_b.deterministic_trigger
    print(f"[B] override=False(기본값): buy_candidate={trig_b.buy_candidate}, "
          f"regime_switch_v1_gate_open={trig_b.metadata.get('regime_switch_v1_gate_open')}, "
          f"reason_codes={trig_b.reason_codes}")

    bundle_c = await _derive_via_orchestrator(
        repos, config_version, instrument, request,
        regime_switch_v1_trigger_status="NOT_TRIGGERED",
        regime_switch_v1_gate_override_enabled=True,
    )
    trig_c = bundle_c.deterministic_trigger
    print(f"[C] override=True: buy_candidate={trig_c.buy_candidate}, "
          f"regime_switch_v1_gate_open={trig_c.metadata.get('regime_switch_v1_gate_open')}, "
          f"reason_codes={trig_c.reason_codes}")

    gate_blocks_via_orchestrator = trig_a.buy_candidate is True and trig_b.buy_candidate is False
    override_restores_via_orchestrator = trig_c.buy_candidate == trig_a.buy_candidate

    print(f"\nDecisionOrchestratorService를 거쳐 게이트가 실제로 buy_candidate를 차단: "
          f"{gate_blocks_via_orchestrator}")
    print(f"DecisionOrchestratorService를 거쳐 override가 실제로 그 차단을 해제: "
          f"{override_restores_via_orchestrator}")

    print("\n=== 3. resolve_cached_trigger_status() — run_decision_loop.py가 실제로 쓰는 배선 확인 ===")
    from agent_trading.services.regime_switch_gate import resolve_cached_trigger_status

    cached_status = resolve_cached_trigger_status()
    print(f"현재 캐시된 §21 게이트 상태(logs/regime_switch_v1_gate_monitor_*.json에서 읽음): "
          f"{cached_status}")

    report = {
        "as_of": datetime.now(_KST).isoformat(),
        "A_no_gate_param_via_orchestrator": {
            "buy_candidate": trig_a.buy_candidate,
            "entry_score": trig_a.entry_score,
        },
        "B_gate_override_off_via_orchestrator": {
            "buy_candidate": trig_b.buy_candidate,
            "regime_switch_v1_gate_open": trig_b.metadata.get("regime_switch_v1_gate_open"),
            "reason_codes": list(trig_b.reason_codes),
        },
        "C_gate_override_on_via_orchestrator": {
            "buy_candidate": trig_c.buy_candidate,
            "regime_switch_v1_gate_open": trig_c.metadata.get("regime_switch_v1_gate_open"),
            "reason_codes": list(trig_c.reason_codes),
        },
        "gate_blocks_via_orchestrator": gate_blocks_via_orchestrator,
        "override_restores_via_orchestrator": override_restores_via_orchestrator,
        "resolve_cached_trigger_status_current_value": cached_status,
        "note": (
            "이번 검증은 assess_deterministic_triggers를 스크립트가 직접 호출한 것이 아니라, "
            "실제 DecisionOrchestratorService를 구성하고 그 인스턴스 메서드 "
            "_derive_deterministic_context_components(내부에서 assess_deterministic_triggers를 "
            "호출)를 통해 검증했다 — decision_orchestrator.py를 실제로 거친 경로다. "
            "repos는 build_in_memory_repositories()(기존 테스트 스위트 표준 패턴)를 사용해 "
            "실제 Postgres/KIS 호출 없이 read-only로 수행됨."
        ),
    }
    out_path = "logs/signal_ic_r3b_orchestrator_gate_wiring_2026-07-18.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
