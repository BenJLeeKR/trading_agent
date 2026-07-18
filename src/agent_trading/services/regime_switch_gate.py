"""`§21 게이트`(regime_switch_v1) config 기반 판정 — mode-agnostic gating.

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §47(SPPV-2.58)
참고. 이 모듈은 SPPV 세션 내내 `scripts/monitor_regime_switch_v1_gate.py`
가 순수 모니터링(read-only, JSON 산출)으로만 계산해온 `regime_switch_v1`
게이트 상태(TRIGGERED/PARTIAL/NOT_TRIGGERED)를, **환경(paper/real/
production)이 아니라 config 스위치 하나만으로** 판정하는 순수 함수를
제공한다.

**핵심 원칙(mode-agnostic config-aware gating)**:
- 이 모듈은 ``AppSettings.regime_switch_v1_gate_override_enabled``
  (env: ``REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED``, 기본값 ``False``)
  단 하나의 boolean만 본다.
- ``KIS_ENV``/``environment``/"paper"/"real"/"production" 같은 실행
  모드 값은 이 모듈 어디에서도 참조하지 않는다 — 검증 가능(아래 §
  참고): 이 파일에 ``environment``, ``KIS_ENV``, ``"paper"``,
  ``"real"``, ``"production"`` 문자열이 전혀 등장하지 않는다.
- override가 꺼져 있으면(기본값) 게이트는 `regime_switch_v1` 모니터
  상태를 그대로 반영한다(TRIGGERED일 때만 열림) — 기존 동작과 100%
  동일.
- override가 켜지면 실제 국면 상태와 무관하게 게이트가 열린다(강제
  통과) — 그 이유는 ``reason_code``로 항상 추적 가능하게 남긴다.

**이 모듈의 현재 위치**: 아직 실제 운영 파이프라인
(`deterministic_trigger_engine.py`의 `assess_deterministic_triggers`)
에는 연결돼 있지 않다 — 그 함수는 이 세션 내내 "절대 수정하지 않는다,
shadow/read-only만" 원칙이 적용된 대상이기 때문이다. 이 모듈은 향후
그 파이프라인에 실제로 연결하기 위한 **격리된, 검증 가능한 준비
단계**다. 지금 당장은 shadow 스크립트에서만 소비된다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음.
"""

from __future__ import annotations

from dataclasses import dataclass

TRIGGERED = "TRIGGERED"
PARTIAL = "PARTIAL"
NOT_TRIGGERED = "NOT_TRIGGERED"

_VALID_TRIGGER_STATUSES = (TRIGGERED, PARTIAL, NOT_TRIGGERED)

REASON_GATE_OPEN_TRIGGERED = "gate_open_regime_switch_v1_triggered"
"""기본 경로 — 게이트가 실제로 TRIGGERED 상태라서 열림(override 없음)."""

REASON_GATE_CLOSED_DEFAULT = "gate_closed_regime_switch_v1_not_triggered"
"""기본 경로 — 게이트가 TRIGGERED가 아니라서 닫힘(override 없음, 기존
동작과 동일)."""

REASON_GATE_OPEN_CONFIG_OVERRIDE = "gate_open_config_override_bypass"
"""override 경로 — `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true`로
실제 국면 상태와 무관하게 강제로 열림."""


@dataclass(slots=True, frozen=True)
class RegimeSwitchGateAssessment:
    """§21 게이트의 config 기반 판정 결과."""

    trigger_status: str
    """`monitor_regime_switch_v1_gate.py`가 계산한 실제 국면 상태
    (TRIGGERED/PARTIAL/NOT_TRIGGERED) — 그대로 보존해 판정 근거를
    감사(audit) 가능하게 남긴다."""

    gate_open: bool
    """최종 판정 — True면 이 게이트를 통과(§21 전제조건 충족)로 간주."""

    override_applied: bool
    """이 판정이 config override에 의한 것인지(True) 기본 경로인지
    (False) 구분."""

    reason_code: str
    """`REASON_GATE_*` 상수 중 하나 — 왜 이 판정이 나왔는지 로그/
    diagnostics에서 추적 가능."""


def assess_regime_switch_v1_gate(
    *,
    trigger_status: str,
    override_enabled: bool,
) -> RegimeSwitchGateAssessment:
    """§21 게이트를 판정한다 — **오직 `override_enabled`(config 스위치)
    와 `trigger_status`(실제 국면 관측치)만 입력으로 받는다.**

    paper/real/production 같은 실행 환경 값은 이 함수의 인자로도,
    본문 로직으로도 전혀 등장하지 않는다 — 호출자가 어떤 환경에서
    이 함수를 부르든(paper 운영 중이든, 향후 real 운영으로 전환하든)
    동작은 오직 `override_enabled` 값에만 좌우된다(mode-agnostic).

    Args:
        trigger_status: `monitor_regime_switch_v1_gate.py`가 계산한
            실제 국면 상태. `TRIGGERED`/`PARTIAL`/`NOT_TRIGGERED` 중
            하나여야 한다.
        override_enabled: `AppSettings.regime_switch_v1_gate_override_
            enabled`(env: `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`,
            기본값 False)를 그대로 전달받는다.

    Returns:
        판정 결과. `override_enabled=False`(기본값)이면 기존 §21
        게이트 해석과 완전히 동일하게 동작한다(TRIGGERED일 때만 열림).
        `override_enabled=True`이면 `trigger_status`와 무관하게 항상
        열린다(강제 통과) — `reason_code`로 이 사실이 항상 기록된다.
    """
    if trigger_status not in _VALID_TRIGGER_STATUSES:
        raise ValueError(
            f"알 수 없는 trigger_status: {trigger_status!r} "
            f"(허용값: {_VALID_TRIGGER_STATUSES})"
        )

    if override_enabled:
        return RegimeSwitchGateAssessment(
            trigger_status=trigger_status,
            gate_open=True,
            override_applied=True,
            reason_code=REASON_GATE_OPEN_CONFIG_OVERRIDE,
        )

    gate_open = trigger_status == TRIGGERED
    return RegimeSwitchGateAssessment(
        trigger_status=trigger_status,
        gate_open=gate_open,
        override_applied=False,
        reason_code=REASON_GATE_OPEN_TRIGGERED if gate_open else REASON_GATE_CLOSED_DEFAULT,
    )
