# KIS Paper Dry-Run Blocker 수정 설계

## 1. Blocker 분석

### Blocker 1: correlation_id 중복 → `UniqueViolationError` → transaction abort

**발생 경로:**
```
run_orchestrator_once.py:309
  → correlation_id="entrypoint-correlation-001" (고정값)

_ensure_or_create_decision_context():1230-1242
  → DecisionContextEntity 생성 (correlation_id 고정값 사용)
  → repos.decision_contexts.add(context)
  → uq_decision_context_correlation 위반 (2회차 실행 시)

catch (except Exception) at line 1253
  → return None  (Python 레벨에서는 예외 처리됨)
  → BUT asyncpg transaction은 aborted 상태로 남음

_agent_recorder.record() → repos.agent_runs.add()
  → InFailedSQLTransactionError (transaction aborted)
  → 전체 dry-run 실패
```

**핵심 원인:** `postgres_runtime()`이 **단일 transaction** 안에서 모든 DB 작업을 수행 (line 464). PostgreSQL에서 한 statement 실패 시 전체 transaction이 aborted 상태가 되며, 이를 Python에서 catch해도 복구 불가.

### Blocker 2: DeepSeek structured-output 호환성

**2a. `generate_json_schema()` 타입 해석 오류**
```python
# schemas.py:46 — 문제 코드
field_type = f.type  # from __future__ import annotations → str!
origin = getattr(field_type, "__origin__", None)  # str에는 __origin__ 없음 → None
```
- `tuple[InterpretedEvent, ...]`가 문자열 `"tuple[InterpretedEvent, ...]"`로 해석됨
- nested dataclass field (`AggregateEventView`)도 문자열로 해석됨
- LLM에 잘못된 schema 전달 → malformed JSON 응답 유도

**2b. `EventInterpretationOutput.__post_init__()` 방어 부족**
```python
# schemas.py:250 — 문제 코드
av = self.aggregate_view
if isinstance(av, str):
    parsed = json.loads(av)  # "중립적" → JSONDecodeError!
    ...
```
- `aggregate_view`가 일반 문자열이면 `json.loads()` 실패
- `events` 필드 문자열 처리 누락
- 예외가 `__post_init__` 밖으로 전파 → agent safe fallback 유도

---

## 2. 변경 설계

### 변경 1: `scripts/run_orchestrator_once.py` — unique correlation_id

```python
# line 309 변경 전
correlation_id="entrypoint-correlation-001",

# line 309 변경 후
correlation_id=f"entrypoint-correlation-{uuid4()}",
```

**효과:** 매 실행 새로운 correlation_id → `uq_decision_context_correlation` 위반 없음

---

### 변경 2: `src/agent_trading/services/decision_orchestrator.py` — savepoint 보호 (UniqueViolationError 한정)

`_ensure_or_create_decision_context()`에서 decision_context `add()` 호출 시 savepoint(sub-transaction) 사용:

```python
# 1227-1250 라인 — savepoint로 감싸기 (UniqueViolationError만 격리)
try:
    async with repos.tx.connection.transaction() as sp:
        context = DecisionContextEntity(...)
        saved = await repos.decision_contexts.add(context)
        decision_context_id = saved.decision_context_id
except asyncpg.exceptions.UniqueViolationError:
    # savepoint rollback → outer transaction 정상 유지
    # correlation_id 중복 → decision_context_id=None 으로 계속 진행
    logger.warning("correlation_id 중복, savepoint rollback 후 None으로 진행")
    decision_context_id = None
```

**예외 범위:** `UniqueViolationError`만 catch. 다른 DB 예외는 그대로 전파되어 caller가 처리.

**Post-rollback 정책:** `decision_context_id=None` 반환. `assemble()` 경로에서 None을 받으면:
- `_run_agents()`는 `decision_context_id=None`으로 정상 실행 (dry-run unblock)
- `_ensure_trade_decision()`도 None 처리 가능
- AI agent 실행이 dry-run의 목적이므로 None 경로로 진행하는 것이 올바름

**`repos.tx` 접근법:** `TransactionManager`는 `connection` property를 제공. asyncpg의 중첩 `connection.transaction()`은 자동으로 savepoint를 생성하므로 추가 설정 불필요.

**변경 2 핵심 요약:**
| 항목 | 내용 |
|------|------|
| 예외 범위 | `UniqueViolationError` **only** |
| rollback 후 | `decision_context_id=None` → 계속 진행 |
| 목적 | dry-run unblock (중복 실행 시 transaction abort 방지) |
| outer tx 영향 | 없음 (savepoint rollback으로 격리) |

---

### 변경 3: `src/agent_trading/services/ai_agents/schemas.py` — `generate_json_schema()` 타입 해석 보강

```python
def generate_json_schema(dataclass_type: type) -> dict[str, Any]:
    import dataclasses
    import typing
    
    # from __future__ import annotations 대응: string annotation을 실제 타입으로
    try:
        resolved_hints = typing.get_type_hints(dataclass_type)
    except Exception:
        resolved_hints = {}

    for f in dataclasses.fields(dataclass_type):
        field_type = resolved_hints.get(f.name, f.type)  # ← resolved_hints 우선
        origin = getattr(field_type, "__origin__", None)
        ...
```

**역할 범위 명시:**
- `generate_json_schema()` 보강은 **Prompt quality improvement** 목적
- 올바른 schema를 LLM에 전달하여 **잘못된 응답 확률을 낮추는 것**
- **Runtime 보장이 아님.** LLM이 schema를 따르지 않을 수 있음
- Runtime 방어는 별도 `__post_init__()`에서 수행 (변경 4)

---

### 변경 4: `src/agent_trading/services/ai_agents/schemas.py` — `EventInterpretationOutput.__post_init__()` 방어 보강

```python
def __post_init__(self) -> None:
    import json
    
    # --- aggregate_view 방어 ---
    av = self.aggregate_view
    if isinstance(av, str):
        try:
            parsed = json.loads(av)  # JSON object 문자열 → parse
            if isinstance(parsed, dict):
                object.__setattr__(self, "aggregate_view", AggregateEventView(**parsed))
            else:
                object.__setattr__(self, "aggregate_view", AggregateEventView())
        except (json.JSONDecodeError, TypeError, ValueError):
            # 일반 문자열("중립적") → safe default
            object.__setattr__(self, "aggregate_view", AggregateEventView())
    elif isinstance(av, dict) and not isinstance(av, AggregateEventView):
        try:
            object.__setattr__(self, "aggregate_view", AggregateEventView(**av))
        except (TypeError, ValueError):
            # dict지만 필수 shape mismatch → default
            object.__setattr__(self, "aggregate_view", AggregateEventView())
    
    # --- events 방어 ---
    ev = self.events
    if isinstance(ev, str):
        # 문자열 events → 빈 tuple (malformed item skip)
        object.__setattr__(self, "events", ())
    elif isinstance(ev, (list, tuple)):
        # 각 item이 유효한 dict인지 확인, 아니면 item 단위 skip
        safe: list[InterpretedEvent] = []
        for item in ev:
            if isinstance(item, dict):
                try:
                    safe.append(InterpretedEvent(**item))
                except (TypeError, ValueError):
                    pass  # malformed item skip
            elif isinstance(item, InterpretedEvent):
                safe.append(item)
        # 모든 item이 실패하면 () 빈 tuple
        object.__setattr__(self, "events", tuple(safe))
```

**malformed events item 처리 규칙:**
| 상황 | 처리 |
|------|------|
| `events`가 문자열 | `()` 빈 tuple로 강등 |
| 리스트 내 malformed item (dict지만 shape mismatch) | **item 단위 skip**, 유효 item만 유지 |
| 모든 item이 실패 | `()` 빈 tuple |
| 리스트 내 이미 InterpretedEvent 객체 | 그대로 유지 |

**malformed aggregate_view 처리 규칙:**
| 상황 | 처리 |
|------|------|
| JSON object 문자열 (`'{"overall_bias":"positive"}'`) | `json.loads()` → `AggregateEventView(**parsed)` |
| 일반 문자열 (`"중립적"`) | `AggregateEventView()` default |
| dict지만 필수 shape mismatch | `AggregateEventView()` default |
| 이미 AggregateEventView 객체 | 그대로 유지 |

---

### ~~변경 5 (선택): `run_orchestrator_once.py` — dry-run 실패해도 exit 0~~

**제거됨.** 사용자 요청사항:
- "submit semantics 변경 금지"
- dry-run의 exit code는 진단 정보로 유지
- 실제 blocker 해결 후 dry-run이 자연스럽게 green이 되는 것이 목표

---

## 3. 변경 파일 목록

| 파일 | 변경 내용 | 영향 범위 |
|------|----------|-----------|
| `scripts/run_orchestrator_once.py` | correlation_id 고정값 → unique 생성 | dry-run 전용 |
| `src/agent_trading/services/decision_orchestrator.py` | savepoint로 decision_context insert 보호 (UniqueViolationError 한정) | assemble 경로 전체 |
| `src/agent_trading/services/ai_agents/schemas.py` | `generate_json_schema()` 타입 해석 + `__post_init__()` 방어 | schema 생성 + 파싱 |
| `tests/services/test_decision_orchestrator.py` | correlation duplicate → transaction 유지 테스트 | 테스트 |
| `tests/services/ai_agents/test_agents.py` | malformed DeepSeek 응답 보정 테스트 | 테스트 |
| `tests/services/ai_agents/test_settings.py` | Schema 생성 테스트 (`typing.get_type_hints()` 적용 확인) | 테스트 |

---

## 4. Migration 필요 여부

**없음.** DB 스키마 변경이 없음. `uq_decision_context_correlation` 제약조건은 그대로 유지 (중복 방지 목적).

---

## 5. 테스트 계획

### 5.1 correlation duplicate → transaction 유지 테스트

**목표:** `decision_context insert 충돌이 있어도 outer transaction이 깨지지 않음`

**테스트 시나리오:**
1. 동일 `_ensure_or_create_decision_context()`를 2회 연속 호출
2. 첫 번째 호출: 정상 insert → context_id 반환
3. 두 번째 호출: 동일 correlation_id로 insert 시도 → `UniqueViolationError` → savepoint rollback → `decision_context_id=None` 반환
4. **검증 포인트:** outer transaction이 정상 상태(aborted 아님) → 후속 DB 작업 가능

**검증 기준 (기존과 다른 점):**
- ~~"고정 correlation 재실행 성공"~~ ❌
- ✅ **"insert 충돌 후에도 transaction이 유지되어 후속 작업 가능"**
- 즉, `await repos.agent_runs.add(...)` 같은 후속 호출이 `InFailedSQLTransactionError`를 발생시키지 않는지

```python
# in-memory repository로 검증 (savepoint 동작은 모의)
@pytest.mark.asyncio
async def test_correlation_duplicate_preserves_transaction(seeded_service):
    """중복 correlation_id insert → UniqueViolationError → transaction 유지"""
    request = sample_request()
    request.correlation_id = "duplicate-test-001"
    
    # 1차: 정상 insert
    ctx_id1 = await seeded_service._ensure_or_create_decision_context(request, None)
    assert ctx_id1 is not None
    
    # 2차: 동일 correlation_id → savepoint rollback → None
    ctx_id2 = await seeded_service._ensure_or_create_decision_context(request, ctx_id1)
    assert ctx_id2 is not None  # 이미 존재하는 context 재사용
    
    # 실제 UniqueViolationError 테스트는 integration test 필요
    # in-memory repo는 unique constraint가 없으므로 savepoint 동작을 별도 검증
```

**참고:** savepoint의 실제 동작(UniqueViolationError catch + rollback)은 **postgres integration test** 영역. Unit test에서는:
- `_ensure_or_create_decision_context()`가 `repos.tx.connection.transaction()`을 호출하는지 확인
- 예외 처리 구조가 올바른지 확인

### 5.2 malformed DeepSeek 응답 보정 테스트

- `events="최근 이벤트가 없습니다."` → safe fallback 빈 tuple
- `aggregate_view="중립적"` → `AggregateEventView()` default
- `aggregate_view='{"overall_bias": "positive"}'` → 파싱 후 dict 변환
- `events=[{"title": "good"}, {"bad": "item"}]` → 첫 번째만 유지, 두 번째 skip
- 모든 events item 실패 → `()`

### 5.3 Schema 생성 테스트 (`typing.get_type_hints()` 적용 확인)

- `generate_json_schema(EventInterpretationOutput)` 호출
- `events` 필드가 `{"type": "array", "items": {...}}`로 올바르게 해석되는지
- `aggregate_view` 필드가 nested object로 올바르게 해석되는지

### 5.4 기존 테스트 통과

- `tests/services/test_decision_orchestrator.py` — 전체 통과
- `tests/services/ai_agents/test_agents.py` — 전체 통과
- `tests/services/ai_agents/test_settings.py` — 전체 통과
- 기타 연관 테스트

### 5.5 실제 dry-run 2회 연속 재실행 검증

```bash
export DATABASE_URL="..."
export KIS_PAPER_REST_RPS="${KIS_PAPER_REST_RPS:-1}"   # canonical=1

# 1차 dry-run
python scripts/run_orchestrator_once.py --dry-run --output json
echo "Exit code: $?"

# 2차 dry-run (동일 조건, UniqueViolationError 검증)
python scripts/run_orchestrator_once.py --dry-run --output json
echo "Exit code: $?"
```

**dry-run 2회 연속 재실행 검증 기준:**
| 검증 항목 | 기준 |
|-----------|-------|
| 1차 dry-run | `exit 0` |
| 2차 dry-run | `exit 0` (1차와 동일 조건, correlation_id 자동 unique) |
| `UniqueViolationError` 재발 | `InFailedSQLTransactionError` 없이 정상 동작 확인 |
| LLM 응답 fallback | `JSONDecodeError` 없이 정상 동작 확인 |

**합격 기준:** 최소 2회 연속 `exit 0` + no `InFailedSQLTransactionError` + no `JSONDecodeError`

---

## 6. Mermaid: 변경 흐름

```mermaid
flowchart TD
    A[run_orchestrator_once.py\n--dry-run] --> B[correlation_id=\nf\"entrypoint-correlation-{uuid4()}\"]
    B --> C[assemble]
    C --> D[_ensure_or_create_decision_context]
    D --> E[savepoint: add DecisionContext]
    E --> F{UniqueViolationError?}
    F -->|Yes| G[savepoint rollback\nreturn None]
    F -->|No| H[return new context id]
    G --> I[_run_agents with\ndecision_context_id=None]
    H --> I
    I --> J[EventInterpretationAgent]
    J --> K{__post_init__ validation}
    K -->|aggregate_view=JSON string| L[try json.loads]
    L -->|success| M[AggregateEventView parsed]
    L -->|fail| N[default AggregateEventView]
    K -->|aggregate_view=plain string| N
    K -->|events=string| O[empty tuple]
    K -->|events list with bad items| P[item-level skip]
    K -->|valid| Q[정상 처리]
    P --> O
    M --> R[safe fallback or normal]
    N --> R
    O --> R
    Q --> R
    R --> S[dry-run output]
    S --> T[exit 0]
    T --> U[2회 연속 검증]
    U -->|1회차 exit 0| V[2회차 exit 0]
    U -->|실패| W[진단 필요]
```

---

## 7. 변경 원칙 요약

사용자가 지정한 변경 원칙:

| 원칙 | 설명 |
|------|------|
| **Minimal additive changes** | 기존 로직을 건드리지 않고 방어 코드만 추가 |
| **No submit semantics change** | broker submit / live order 경로 변경 금지 |
| **No guardrail change** | guardrail/reconciliation 경계 변경 금지 |
| **No admin UI change** | admin_ui 경로 변경 금지 |
| **Generic fallback first** | DeepSeek-specific hardcoding 없이 일반적인 방어 우선 |
| **Schema fix = prompt quality** | `generate_json_schema()` 보강은 LLM prompt 품질 개선이 목적, runtime 보장 아님 |
| **Dry-run green 목표** | blocker 해결 후 dry-run이 자연스럽게 green |

---

## 8. TODO 리스트

- [x] Blocker 1 분석 완료: correlation_id 중복 + transaction abort
- [x] Blocker 2 분석 완료: DeepSeek structured-output 호환성
- [x] 설계 문서 업데이트 (savepoint 범위, fallback 규칙, test 목표 재정의)
- [ ] 변경 1: `run_orchestrator_once.py` — unique correlation_id
- [ ] 변경 2: `decision_orchestrator.py` — savepoint 보호 (UniqueViolationError 한정)
- [ ] 변경 3: `schemas.py` — `generate_json_schema()` 타입 해석 (prompt quality)
- [ ] 변경 4: `schemas.py` — `__post_init__()` 방어 보강 (runtime fallback)
- [ ] 테스트 1: correlation duplicate → transaction 유지 테스트
- [ ] 테스트 2: malformed DeepSeek 응답 보정 테스트
- [ ] 테스트 3: schema 생성 테스트 (`typing.get_type_hints()` 적용 확인)
- [ ] 기존 테스트 전체 통과 확인
- [ ] 실제 dry-run 2회 연속 재실행 검증
