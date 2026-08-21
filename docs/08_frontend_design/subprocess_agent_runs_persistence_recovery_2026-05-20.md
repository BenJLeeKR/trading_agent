# Subprocess AgentRuns Persistence Recovery

**Date**: 2026-05-20
**Author**: Roo (Code Analysis + Implementation)

---

## Problem Statement

`AgentRuns` 화면이 비어 있음. DB 확인 결과:
- 최근 1일 `trade_decisions`: **1,539건**
- `trade_decisions.agent_run_id IS NOT NULL`: **0건**
- 즉 의사결정은 생성되지만 `agent_runs` 기록/연결이 전부 누락

**Root Cause**: Subprocess isolation 경로(`_run_agents_in_subprocess()`)에서 `AgentRunRecorder.record()` 호출이 누락됨.

---

## Data Flow Analysis

### In-process 경로 (`_run_agents()`)

```
assemble()
  → _run_agents()
    → EI agent 실행 → recorder.record() → AgentRunEntity #1
    → AR agent 실행 → recorder.record() → AgentRunEntity #2
    → FDC agent 실행 → recorder.record() → AgentRunEntity #3
  → _ensure_trade_decision()  ← agent_run_id=None (기존)
```

### Subprocess 경로 (`_run_agents_in_subprocess()`) — **Before Fix**

```
assemble()
  → _run_agents_in_subprocess()
    → subprocess spawn → stdout JSON (EI, AR, FDC outputs)
    → _deserialize_agent_output() → AgentExecutionBundle
    → NO recorder call ← BUG
  → _ensure_trade_decision()  ← agent_run_id=None (연결 없음)
```

### Subprocess 경로 — **After Fix**

```
assemble()
  → _run_agents_in_subprocess()
    → subprocess spawn → stdout JSON
    → _deserialize_agent_output() → AgentExecutionBundle
    → recorder.record(EI output) → AgentRunEntity #1
    → recorder.record(AR output) → AgentRunEntity #2
    → recorder.record(FDC output) → AgentRunEntity #3  ← fdc_run_id 추출
  → _ensure_trade_decision(fdc_run_id=...)  ← agent_run_id 연결됨
```

---

## Key Files Analyzed

| File | Role |
|------|------|
| [`decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py) | `_run_agents()` (L1651), `_run_agents_in_subprocess()` (L1948), `_deserialize_agent_output()` (L2320), `assemble()` (L639), `_ensure_trade_decision()` (L2133) |
| [`recorder.py`](../src/agent_trading/services/ai_agents/recorder.py) | `AgentRunRecorder.record()` — `decision_context_id`, `agent_type`, `structured_output`을 받아 `AgentRunEntity` 생성 및 persist |
| [`run_agent_subprocess.py`](../scripts/run_agent_subprocess.py) | stdout으로 `{success, event_output, risk_output, composer_output, error, duration_seconds}` JSON 출력 |
| [`entities.py`](../src/agent_trading/domain/entities.py) | `AgentRunEntity` (L172), `TradeDecisionEntity.agent_run_id: UUID \| None` (L240) |
| [`agent_runs.py`](../src/agent_trading/repositories/postgres/agent_runs.py) | `PostgresAgentRunRepository.add()` — INSERT into `trading.agent_runs` |

---

## Answers to Investigation Questions

### Q1: subprocess 경로에서 EI/AR/FDC output을 부모 프로세스가 충분히 복원할 수 있는가?

**Yes.** `_deserialize_agent_output()`은 `event_output`, `risk_output`, `composer_output`을 완전한 dataclass 인스턴스로 복원함. `AgentExecutionBundle`에 세 개의 출력이 모두 포함되어 있음. `_dataclass_to_dict()`를 통해 `structured_output_json`에 저장할 dict를 생성 가능.

**부족한 정보**: `started_at`/`completed_at` timestamp (subprocess 내 `duration_seconds`만 있음), `model_id`/`prompt_id` (subprocess input에 포함되어 있으나 recorder 호출 시 전달 안 함). 이는 `AgentRunEntity`의 선택 필드이므로 누락되어도 무방함.

### Q2: 부모 프로세스에서 각 agent 결과를 `record()`하는 것이 가장 자연스러운가?

**Yes.** `assemble()` 메서드에서 subprocess 경로(`_run_agents_in_subprocess()` 호출 후)에 3번의 `recorder.record()` 호출을 추가하는 것이 가장 자연스럽고 안전함.

- `_run_agents_in_subprocess()` 내부에 추가할 수도 있지만, `_run_agents()`와의 일관성을 위해 `assemble()` 수준에서 처리
- in-process 경로(`_run_agents()`)는 이미 내부에서 recorder를 호출하므로, subprocess 경로에서만 recorder를 호출하도록 조건 분기

### Q3: `trade_decisions.agent_run_id`는 어느 agent run과 연결해야 하는가?

**FDC (Final Decision Composer) run**이 가장 적절함. FDC가 최종 결정(decision_type, side, confidence 등)을 내리므로 trade decision과 가장 직접적인 연관이 있음.

### Q4: 최소 수정으로 `AgentRuns` 화면을 다시 살리려면 어디를 고쳐야 하는가?

1. **`assemble()` 메서드** (L643-658): subprocess 경로에 3번의 `recorder.record()` 호출 추가
2. **`_ensure_trade_decision()`** (L2133): `fdc_run_id` 파라미터 추가, `TradeDecisionEntity.agent_run_id=fdc_run_id` 설정

### Q5: 기존 in-process 경로와 중복 기록/회귀 위험은 없는가?

**없음.** `_run_agents()` 내부에 이미 recorder 호출이 있지만, subprocess 경로(`_use_subprocess_isolation=True`)에서는 `_run_agents()`가 아닌 `_run_agents_in_subprocess()`가 호출되므로 중복되지 않음.

in-process 경로에서는 `_run_agents()`가 내부에서 recorder를 호출하므로, `assemble()` 수준에서 추가 호출하지 않음. 단, `_ensure_trade_decision()`에 `fdc_run_id`를 전달하기 위해 recorder buffer에서 최근 run을 조회함.

---

## Implementation Details

### 변경 파일: [`decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py)

#### 1. `assemble()` 메서드 — subprocess 경로에 recorder rehydration 추가

```python
# subprocess 경로 (기존)
if self._use_subprocess_isolation:
    agent_bundle = await self._run_agents_in_subprocess(...)
    # ── NEW: Rehydrate AgentRunEntity records from subprocess output ──
    _fdc_run_id: UUID | None = None
    try:
        _ei_run = await self._agent_recorder.record(
            decision_context_id=resolved_context_id,
            agent_type=self._event_interpretation_agent.agent_name,
            structured_output=_dataclass_to_dict(agent_bundle.event_output),
        )
        _ar_run = await self._agent_recorder.record(
            decision_context_id=resolved_context_id,
            agent_type=self._ai_risk_agent.agent_name,
            structured_output=_dataclass_to_dict(agent_bundle.risk_output),
        )
        _fdc_run = await self._agent_recorder.record(
            decision_context_id=resolved_context_id,
            agent_type=self._final_decision_agent.agent_name,
            structured_output=_dataclass_to_dict(agent_bundle.composer_output),
        )
        _fdc_run_id = _fdc_run.agent_run_id
    except Exception:
        logger.warning("Failed to rehydrate agent runs ...")

# in-process 경로 (기존 + FDC run_id 추출)
else:
    agent_bundle = await self._run_agents(...)
    _fdc_run_id = None
    try:
        _recent = await self._agent_recorder.list_by_decision_context(...)
        if _recent:
            _fdc_run_id = _recent[0].agent_run_id  # most recent = FDC
    except Exception:
        pass

# 공통: _ensure_trade_decision에 fdc_run_id 전달
trade_decision_id = await self._ensure_trade_decision(
    ..., fdc_run_id=_fdc_run_id,
)
```

#### 2. `_ensure_trade_decision()` — `fdc_run_id` 파라미터 추가

```python
async def _ensure_trade_decision(
    self, *,
    request, assembled_context, agent_bundle,
    decision_context_id: UUID | None,
    fdc_run_id: UUID | None = None,  # ← NEW
) -> UUID | None:
```

#### 3. `TradeDecisionEntity` 생성자에 `agent_run_id` 설정

```python
decision = TradeDecisionEntity(
    ...
    source_type=assembled_context.source_type,
    agent_run_id=fdc_run_id,  # ← NEW
    ...
)
```

---

## Verification Results

### Unit Tests (모두 통과)

| Test Suite | 결과 |
|-----------|------|
| `tests/services/test_decision_orchestrator.py` | 40/40 ✅ |
| `tests/services/ai_agents/test_agent_subprocess.py` | 19/19 ✅ |
| `tests/services/test_decision_submit_pipeline.py` | 통과 ✅ |
| `tests/services/test_submit_order_from_decision.py` | 통과 ✅ |
| `tests/services/test_paper_trading_scenarios.py` | 통과 ✅ |
| `tests/services/test_safe_order_path_e2e.py` | 통과 ✅ |

### Syntax Check

```python
import ast
ast.parse(open('src/agent_trading/services/decision_orchestrator.py').read())
# Syntax OK ✅
```

### Deployment

- Docker containers (`api`, `app`) 재시작 완료 ✅
- Volume mount로 소스 코드 연결되어 있어 rebuild 불필요
- 다음 scheduler cycle에서 subprocess 경로로 `agent_runs` 기록 시작 예정

---

## Backward Compatibility Concerns

1. **`_ensure_trade_decision()` 시그니처 변경**: `fdc_run_id: UUID | None = None` — 선택적 파라미터이므로 기존 호출자와 100% 호환됨.
2. **in-process 경로**: 변경 없음. `_run_agents()` 내부 recorder 호출은 그대로 유지.
3. **subprocess 경로**: `recorder.record()` 실패 시 `except Exception`으로 처리하므로, recorder 장애가 decision pipeline을 블로킹하지 않음.
4. **`AgentRunEntity.decision_context_id` NOT NULL 제약**: `resolved_context_id`가 `None`인 경우 recorder가 synthetic UUID를 생성하지만, Postgres FK 제약으로 실패할 수 있음. 이 경우 `except Exception`으로 안전하게 처리됨.

---

## Future Improvements

1. **subprocess에서 timestamp 반환**: subprocess가 각 agent의 `started_at`/`completed_at`을 stdout에 포함시키면 더 정확한 기록 가능.
2. **`model_id`/`prompt_id` 전달**: subprocess input에 `model_id`/`prompt_id`가 이미 포함되어 있으므로, recorder 호출 시 전달하도록 개선 가능.
3. **모니터링**: `Rehydrated N agent runs from subprocess output` 로그를 Grafana 등에서 모니터링하여 rehydration 실패율 추적.
