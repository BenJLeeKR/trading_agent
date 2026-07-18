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

**이 모듈의 현재 위치(SPPV-2.60에서 갱신)**: `deterministic_trigger_
engine.py`의 `assess_deterministic_triggers`(§48/SPPV-2.59)와
`services/decision_orchestrator.py`(§49/SPPV-2.60, 실제 상위 호출부)
양쪽에 실제로 연결됐다. `resolve_cached_trigger_status()`는 그 상위
호출부가 매 결정마다 새로운 KIS 호출 없이 최신 `regime_switch_v1`
게이트 상태를 읽기 위한 read-only 파일 접근 헬퍼다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음.
"""

from __future__ import annotations

import glob
import json
import os

from dataclasses import dataclass
from pathlib import Path

# 프로젝트 루트를 이 파일 위치 기준으로 고정한다(SPPV-2.61) —
# resolve_cached_trigger_status()의 기본 glob 패턴이 호출자의 현재
# 작업 디렉터리(cwd)에 의존하지 않도록 하기 위함이다. 이 파일은
# <root>/src/agent_trading/services/regime_switch_gate.py에 위치하므로
# parents[3]이 <root>다(db/migrations/run.py의 기존 관례와 동일한
# 패턴).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

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


def resolve_cached_trigger_status(
    glob_pattern: str | None = None,
) -> str | None:
    """가장 최근에 저장된 `regime_switch_v1` 게이트 모니터링 JSON
    (`scripts/monitor_regime_switch_v1_gate.py`가 read-only로 계산해
    저장하는 산출물)에서 `trigger_status`를 읽어온다.

    **[SPPV-2.61에서 수정]** 기본 `glob_pattern`을 `_PROJECT_ROOT`
    (이 파일 위치 기준으로 고정된 절대경로) 기준으로 앵커링한다 —
    이전 버전은 상대경로("logs/regime_switch_v1_gate_monitor_*.json")
    를 그대로 써서 **호출자의 현재 작업 디렉터리(cwd)에 의존**했다.
    이 때문에 cwd가 프로젝트 루트가 아닌 환경(예: 검증 스크립트를
    다른 cwd에서 실행한 경우)에서는 실제로 파일이 있어도 찾지 못해
    `None`을 반환하는 문제가 있었다 — glob 자체나 JSON 파싱, status
    검증 로직에는 결함이 없었고, 오직 **경로가 cwd 의존적이었다는
    것**이 원인이었다. `glob_pattern`을 명시적으로 넘기면 그 값을
    그대로 쓰고(하위 호환), 넘기지 않으면(기본값) 항상 프로젝트
    루트 기준 절대경로를 사용한다.

    실제 상위 호출부(`decision_orchestrator.py`)가 매 결정마다 새로운
    KIS 호출 없이 최신 게이트 상태를 저렴하게 읽기 위한 헬퍼다 — 순수
    파일 read-only 접근이며 DB write/주문 경로/실시간 구독/broker
    submit과 무관하다. 파일이 없거나(모니터링이 아직 한 번도 실행되지
    않았거나) 파싱에 실패하면 ``None``을 반환한다 — 호출자는 이 경우
    게이트 체크를 건너뛰도록(=기존 동작 유지) 설계돼 있다(§48 참고,
    `assess_deterministic_triggers`의 `regime_switch_v1_trigger_
    status=None` 기본값과 동일한 안전 기본값).
    """
    pattern = glob_pattern or str(_PROJECT_ROOT / "logs" / "regime_switch_v1_gate_monitor_*.json")
    matches = glob.glob(pattern)
    if not matches:
        return None
    latest_path = max(matches, key=os.path.getmtime)
    try:
        with open(latest_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    status = data.get("trigger_status")
    if status not in _VALID_TRIGGER_STATUSES:
        return None
    return status
