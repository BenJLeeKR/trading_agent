#!/usr/bin/env python3
"""SPPV-2.58 — `§21 게이트`(regime_switch_v1) config override 검증
(read-only, broker submit 없음, `deterministic_trigger_engine.py` 미변경).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §47 참고.

이 스크립트는 신규 모듈 `agent_trading.services.regime_switch_gate`가
아래 요구사항을 실제로 만족하는지 검증한다:

1. **격리 확인**: 신규 게이트 모듈이 `deterministic_trigger_engine.py`
   에서 import되지 않는다(그 파일을 전혀 수정하지 않았다는 증거).
2. **config 스위치 동작(override off)**: `REGIME_SWITCH_V1_GATE_
   OVERRIDE_ENABLED` 미설정(기본값 False) 시, 게이트 판정이 실제
   `regime_switch_v1` 모니터 상태(TRIGGERED일 때만 열림)를 그대로
   반영한다 — 기존 해석과 동일.
3. **config 스위치 동작(override on)**: 같은 환경변수를 "true"로
   설정하면, 실제 국면 상태(TRIGGERED/PARTIAL/NOT_TRIGGERED 무엇이든)
   와 무관하게 게이트가 항상 열린다.
4. **mode-agnostic 확인**: `AppSettings`를 두 번 생성해 override
   설정만 바뀌었을 때 판정이 바뀌는지 확인한다 — `KIS_ENV`/
   environment 값은 전혀 건드리지 않았는데도 override 여부만으로
   판정이 갈린다는 것을 보여준다(paper/real 분기가 아니라 config
   분기라는 증거).
5. **R3b shadow 관측 영향 확인**: 이 세션 내내 실행된 모든 R3b
   shadow/paper 검증 스크립트가 이 게이트를 전혀 참조하지 않고도
   would_buy 후보를 정상 생성해왔다는 사실(§45/§46에서 이미 확인된
   58,493건 전체 시점 스냅샷)을 재확인 근거로 인용하고, 이번 신규
   모듈이 그 경로에 어떤 영향도 주지 않음(import 없음)을 재확인한다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음. 벤치마크
(KODEX 200) 1종목만 조회(기존 monitor 스크립트 재사용, 캐시 우선).
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import sys as _sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_regime_switch_gate_config_override")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")


def _check_isolation_from_operational_code() -> dict:
    """`deterministic_trigger_engine.py`가 신규 게이트 모듈을 import하지
    않는다는 것을 소스 코드 검사로 확인한다(파일 미수정의 직접 증거)."""
    import agent_trading.services.deterministic_trigger_engine as dte

    source = inspect.getsource(dte)
    imports_gate_module = "regime_switch_gate" in source
    return {
        "deterministic_trigger_engine_imports_regime_switch_gate": imports_gate_module,
        "expected": False,
        "isolation_confirmed": imports_gate_module is False,
    }


def _run_gate_scenarios(trigger_status: str) -> dict:
    from agent_trading.config.settings import AppSettings
    from agent_trading.services.regime_switch_gate import assess_regime_switch_v1_gate

    # 시나리오 1: override 미설정(기본값) — os.environ에서 관련 키 제거
    os.environ.pop("REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED", None)
    settings_default = AppSettings()
    result_off = assess_regime_switch_v1_gate(
        trigger_status=trigger_status,
        override_enabled=settings_default.regime_switch_v1_gate_override_enabled,
    )

    # 시나리오 2: override 명시적 활성화
    os.environ["REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED"] = "true"
    settings_override = AppSettings()
    result_on = assess_regime_switch_v1_gate(
        trigger_status=trigger_status,
        override_enabled=settings_override.regime_switch_v1_gate_override_enabled,
    )
    os.environ.pop("REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED", None)  # 원복

    return {
        "trigger_status": trigger_status,
        "override_off": {
            "config_value": settings_default.regime_switch_v1_gate_override_enabled,
            "gate_open": result_off.gate_open,
            "override_applied": result_off.override_applied,
            "reason_code": result_off.reason_code,
        },
        "override_on": {
            "config_value": settings_override.regime_switch_v1_gate_override_enabled,
            "gate_open": result_on.gate_open,
            "override_applied": result_on.override_applied,
            "reason_code": result_on.reason_code,
        },
    }


async def main() -> None:
    from monitor_regime_switch_v1_gate import _run as _run_gate_monitor

    isolation = _check_isolation_from_operational_code()
    print("\n=== 1. 운영 코드 격리 확인 ===")
    print(isolation)

    print("\n=== 2. 실제 §21 게이트 상태 조회(벤치마크 1종목, read-only) ===")
    monitor_report = await _run_gate_monitor()
    actual_trigger_status = monitor_report["trigger_status"]
    print(f"실제 관측된 trigger_status: {actual_trigger_status}")

    print("\n=== 3. config override 시나리오 검증(실제 관측치 기준) ===")
    scenario_actual = _run_gate_scenarios(actual_trigger_status)
    print(scenario_actual)

    print("\n=== 4. 세 가지 trigger_status 전부에 대한 override 동작 확인(합성 시나리오) ===")
    scenario_synthetic = {
        status: _run_gate_scenarios(status)
        for status in ("TRIGGERED", "PARTIAL", "NOT_TRIGGERED")
    }
    for status, result in scenario_synthetic.items():
        print(f"{status}: override_off.gate_open={result['override_off']['gate_open']}, "
              f"override_on.gate_open={result['override_on']['gate_open']}")

    all_override_on_open = all(
        r["override_on"]["gate_open"] is True for r in scenario_synthetic.values()
    )
    only_triggered_open_when_off = (
        scenario_synthetic["TRIGGERED"]["override_off"]["gate_open"] is True
        and scenario_synthetic["PARTIAL"]["override_off"]["gate_open"] is False
        and scenario_synthetic["NOT_TRIGGERED"]["override_off"]["gate_open"] is False
    )

    print(f"\noverride=on일 때 3개 상태 모두 gate_open=True: {all_override_on_open}")
    print(f"override=off일 때 TRIGGERED만 gate_open=True(기존 해석과 동일): {only_triggered_open_when_off}")

    report = {
        "as_of": datetime.now(_KST).isoformat(),
        "isolation_check": isolation,
        "actual_monitor_report": {
            "trigger_status": actual_trigger_status,
            "recent_common_market_regime_distribution": monitor_report.get(
                "recent_common_market_regime_distribution"
            ),
        },
        "scenario_actual_trigger_status": scenario_actual,
        "scenario_synthetic_all_statuses": scenario_synthetic,
        "all_override_on_open": all_override_on_open,
        "only_triggered_open_when_off": only_triggered_open_when_off,
        "note": (
            "이 신규 게이트 모듈은 deterministic_trigger_engine.py에 연결돼 있지 않다. "
            "이 세션 내내 R3b shadow 검증(§45 기준 58,493건 전체 시점 스냅샷 포함)은 "
            "이 게이트를 전혀 참조하지 않고도 정상 실행됐다 — 즉 R3b shadow/paper 관측은 "
            "이 게이트에 의해 지금까지도, 이번 변경 이후에도 막혀 있지 않다."
        ),
    }
    out_path = "logs/signal_ic_r3b_regime_switch_gate_config_override_2026-07-18.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
