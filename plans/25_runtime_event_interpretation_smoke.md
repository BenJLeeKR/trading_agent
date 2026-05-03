# Plan 25: Real EventInterpretationAgent Runtime Smoke Verification

## 1. 목적

현재 wiring된 DeepSeek/OpenAI-compatible provider 경로가 실제 runtime에서 안전하게 동작하는지 검증한다. 기존 unit test는 `_build_provider_agent()`가 올바른 타입(real vs None)을 반환하는지만 확인하고, 실제 `agent.run()` 호출 경로는 검증하지 않는다.

## 2. 현재 커버리지 갭

| 영역 | 기존 테스트 | 갭 |
|------|-----------|-----|
| `_build_provider_agent()` 타입 검증 | `TestBuildProviderAgent` (5 tests) ✅ | agent.run() 호출 없음 |
| Runtime dict shape (3 factories) | `TestBuildDefaultRuntime`, `TestBuildPostgresRuntime`, `TestPostgresRuntimeContext` (15 tests) ✅ | agent.run() 호출 없음 |
| LLM_PROVIDER 분기 | `TestOpenAIWiring` (7 tests) ✅ | 실제 HTTP 호출 없음 |
| Provider client raw smoke | `test_deepseek_provider.py` (2 tests) ✅ | runtime wiring 없이 standalone client만 사용 |
| Real agent + mock provider unit | `test_agents.py::TestEventInterpretationAgent` (5 tests) ✅ | orchestrator/recorder 통합 경로 없음 |
| Orchestrator + mock agents | `test_orchestrator_agents.py` (9 tests) ✅ | mock agent만 사용, real EI agent 없음 |
| **Runtime + real agent + 실제 호출** | **❌ 없음** | **runtime에서 주입된 real agent로 실제 provider 호출 → structured output까지 검증하는 테스트 없음** |

## 3. 설계

### 3.1 새 파일: `tests/smoke/test_runtime_event_interpretation_smoke.py`

두 개의 테스트 클래스로 구성:

#### Class A: `TestRuntimeEventInterpretationFallback` (always runs, env 설정 불필요)

| 테스트 | 내용 |
|--------|------|
| `test_default_runtime_stub_when_no_credential` | 모든 provider env var 제거 → `event_interpretation_agent`가 `None`인지 확인 |
| `test_orchestrator_assemble_with_stub` | stub 상태에서 `orchestrator.assemble()`이 정상 동작하는지 확인 (기존 동작 regression 방지) |

#### Class B: `TestRuntimeEventInterpretationSmoke` (`@pytest.mark.smoke`, 모든 DeepSeek 설정 필요)

**Skip 조건 (4개 모두 확인):**
- `LLM_PROVIDER=deepseek`
- `DEEPSEEK_API_KEY` 설정됨
- `DEEPSEEK_BASE_URL` 설정됨 (또는 default 사용 가능하나 명시적 체크)
- `DEEPSEEK_MODEL_ID` 설정됨 (또는 default 사용 가능하나 명시적 체크)

**API 호출 최소화:** `runtime` fixture를 class-scope로 한 번만 빌드하여 3개 테스트에서 재사용.
실제 provider 호출은 총 2회로 제한 (agent.run + orchestrator.assemble).

| 테스트 | 내용 | API 호출 |
|--------|------|----------|
| `test_runtime_creates_real_agent` | `build_default_runtime()` → agent type 확인 (fixture 재사용) | 0회 |
| `test_agent_run_returns_structured_output` | `agent.run()` → `EventInterpretationOutput` 반환 + 결정적 필드/shape 검증 | 1회 |
| `test_agent_run_preserves_fields` | `test_agent_run_returns_structured_output`의 결과 재사용 또는 별도 호출 없이, 결정적 필드 타입 위주 검증 (symbol=str, events=tuple, aggregate_view=AggregateEventView 등). **모델의 의미 해석 결과값 고정 검증하지 않음** | 0회 (1회 결과 재활용) |
| `test_orchestrator_assemble_with_real_agent` | `orchestrator.assemble()` → `OrderIntent` 반환 + recorder 3개 entry + EI run은 real agent, AR/FDC는 stub임을 명확히 검증 | 1회 |

### 3.2 Smoke 테스트 상세

#### `test_agent_run_returns_structured_output`

```python
runtime = build_default_runtime()
agent = runtime["event_interpretation_agent"]
assert isinstance(agent, EventInterpretationAgent)

request = AgentExecutionRequest(
    decision_context_id=None,
    correlation_id="runtime-smoke-ei-001",
    context=AssembledContext(),  # 모든 필드 empty/None
)
result = await agent.run(request)

# Shape 검증
assert isinstance(result, EventInterpretationOutput)
assert result.schema_version == "v1"
assert result.agent_name == "event_interpretation"
assert result.decision_context_id is None  # None 전달
assert isinstance(result.symbol, str)
assert isinstance(result.events, tuple)
assert isinstance(result.aggregate_view, AggregateEventView)
```

#### `test_orchestrator_assemble_with_real_agent`

```python
runtime = build_default_runtime()
agent = runtime["event_interpretation_agent"]
assert isinstance(agent, EventInterpretationAgent)

orchestrator = runtime["orchestrator"]
request = SubmitOrderRequest(
    client_order_id="smoke-ei-001",
    correlation_id="runtime-smoke-asm-001",
    account_ref="smoke-test",
    symbol="005930",
    market="KRX",
    side="buy",
    order_type="limit",
    time_in_force="day",
    quantity=Decimal("10"),
    price=Decimal("50000"),
    idempotency_key="idem-smoke-001",
)
intent = await orchestrator.assemble(request)

assert isinstance(intent, OrderIntent)
runs = orchestrator._agent_recorder.list_all()
assert len(runs) == 3
ei_run = runs[0]
assert ei_run.agent_type == "event_interpretation"
assert ei_run.structured_output_json is not None
assert ei_run.structured_output_json.get("schema_version") == "v1"
assert ei_run.structured_output_json.get("agent_name") == "event_interpretation"
```

### 3.3 수정/추가할 파일

| 파일 | 작업 | 변경 사유 |
|------|------|-----------|
| `tests/smoke/test_runtime_event_interpretation_smoke.py` | **신규 생성** | runtime smoke 검증 |
| `plans/README.md` | 수정 | Entry 25 인덱스 추가 |
| 기존 파일 | **변경 없음** | 기존 코드나 테스트 수정 불필요 |

### 3.4 기존 테스트와의 관계

- `test_bootstrap.py::TestBuildProviderAgent` — `_build_provider_agent()`가 올바른 타입을 반환하는지 검증 (unit)
- `test_bootstrap.py::TestBuildDefaultRuntime` — runtime dict에 올바른 키와 agent 타입이 포함되는지 검증 (unit)
- `test_bootstrap.py::TestOpenAIWiring` — LLM_PROVIDER 분기 env 설정 검증 (unit)
- `test_deepseek_provider.py` — raw provider client standalone smoke (smoke)
- `test_orchestrator_agents.py` — orchestrator + mock agent (unit)
- **신규 smoke** — runtime → real agent → 실제 provider 호출 → structured output 검증 (integration/smoke)

### 3.5 credential 없는 환경에서의 동작

- `TestRuntimeEventInterpretationFallback` — **항상 실행**, credential 불필요
- `TestRuntimeEventInterpretationSmoke` — `DEEPSEEK_API_KEY` 없으면 **skip** (pytest.skipif)
- skip 메시지: `"DEEPSEEK_API_KEY not set — skipping runtime smoke test"`
- 전체 테스트: 367 + 2 (fallback) = 369 passed (+ 4 skipped when no credential)

### 3.6 credential 있는 환경에서의 기대 동작

1. `build_default_runtime()` → real `EventInterpretationAgent` (HTTP client 포함)
2. `agent.run()` → `EventInterpretationOutput` (symbol, events, aggregate_view populated by LLM)
3. `orchestrator.assemble()` → `OrderIntent` + recorder entries (EI run has structured_output_json from provider)
4. 전체 테스트: 367 + 2 (fallback) + 4 (smoke) = 373 passed

## 4. 실행 순서

1. `tests/smoke/test_runtime_event_interpretation_smoke.py` 생성
2. `TestRuntimeEventInterpretationFallback` 구현 (always-run, 2 tests)
3. `TestRuntimeEventInterpretationSmoke` 구현 (credential-conditional, 4 tests)
4. `plans/README.md`에 Entry 25 추가
5. 전체 테스트 실행 및 green 확인 (367 → 369 passed without credential / 373 with credential)

## 5. 완료 기준

- [x] `TestRuntimeEventInterpretationFallback` — runtime에서 stub fallback 동작 검증 (credential 불필요)
- [x] `TestRuntimeEventInterpretationSmoke` — real agent → `agent.run()` → structured output 검증 (credential 필요)
- [x] `test_orchestrator_assemble_with_real_agent` — orchestrator 전체 경로 검증
- [x] 기존 테스트 green 유지
- [x] `plans/README.md` 인덱스 업데이트

## 6. 다음 단계 (이번 범위 아님)

- AIRiskAgent real 구현 계획 수립
- FinalDecisionComposerAgent real 구현 계획 수립
- multi-agent composition 확장
