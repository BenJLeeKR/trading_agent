# EI Output → AIRiskAgent 전달 설계 변경 계획

## 1. 문제

현재 [`_run_agents()`](src/agent_trading/services/decision_orchestrator.py:381)는
Event Interpretation Agent의 출력(`event_output`)을 Recorder에만 저장하고,
이후 실행되는 AI Risk Agent에 전달하지 않는다.

```python
# Line 408-412: shared request
request = AgentExecutionRequest(
    decision_context_id=decision_context_id,
    correlation_id=correlation_id,
    context=assembled_context,
)

# Line 417: EI 실행
event_output = await self._event_interpretation_agent.run(request)
await self._agent_recorder.record(...)          # recorder 저장만 함

# Line 436: AR 실행 — 동일한 request (event_output 미전달!)
risk_output = await self._ai_risk_agent.run(request)
```

## 2. 영향

- AIRiskAgent의 `_build_user_prompt()`는 `context.score`(deterministic ScoreResult)만 볼 수 있음
- EI의 `InterpretedEvent` 목록, `aggregate_view`, `recommendation` 등에 접근 불가
- "최근 이벤트"는 `AssembledContext.recent_events`의 `ExternalEventEntity` 목록만 제공
- EI가 분석한 의미론적 이벤트 해석(event_summary, news_impact, market_regime 등)이 AR에 전달되지 않음

## 3. 설계 변경 방향

### 3.1 AgentExecutionRequest 확장 (권장)

`AgentExecutionRequest`에 `event_interpretation_output` 필드를 추가하여
EI 실행 결과를 AR과 FDC가 사용할 수 있게 한다.

```python
@dataclass(slots=True, frozen=True)
class AgentExecutionRequest:
    decision_context_id: UUID | None
    correlation_id: str
    context: AssembledContext
    event_interpretation_output: EventInterpretationOutput | None = None  # ← 신규
    model_id: str | None = None
    prompt_id: str | None = None
```

### 3.2 Orchestrator 수정

`_run_agents()`에서 EI 실행 직후 `event_output`을 request에 설정:

```python
# EI 실행
event_output = await self._event_interpretation_agent.run(request)

# EI 출력을 request에 설정 (불변 객체이므로 새 request 생성)
request_with_ei = AgentExecutionRequest(
    decision_context_id=request.decision_context_id,
    correlation_id=request.correlation_id,
    context=request.context,
    event_interpretation_output=event_output,
    model_id=request.model_id,
    prompt_id=request.prompt_id,
)

# AR 실행 — EI 출력 포함
risk_output = await self._ai_risk_agent.run(request_with_ei)
```

### 3.3 AIRiskAgent._build_user_prompt() 확장

`request.event_interpretation_output`이 존재하면 prompt에 추가 정보 포함:

```python
ei_output = request.event_interpretation_output
if ei_output:
    lines.append(f"Event Interpretation: {ei_output.aggregate_view.summary or 'N/A'}")
    lines.append(f"Market regime: {ei_output.market_regime or 'N/A'}")
    # 등등
```

## 4. 변경 대상 파일

| 파일 | 변경 내용 |
|------|----------|
| [`src/agent_trading/services/ai_agents/base.py`](src/agent_trading/services/ai_agents/base.py:27) | `AgentExecutionRequest`에 `event_interpretation_output` 필드 추가 |
| [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:381) | `_run_agents()`에서 EI→AR 출력 전달 로직 추가 |
| [`src/agent_trading/services/ai_agents/ai_risk.py`](src/agent_trading/services/ai_agents/ai_risk.py:226) | `_build_user_prompt()`에서 EI 출력 활용 |
| [`tests/services/ai_agents/test_base.py`](tests/services/ai_agents/test_base.py) | `AgentExecutionRequest` 새 필드 테스트 |
| [`tests/services/ai_agents/test_orchestrator_agents.py`](tests/services/ai_agents/test_orchestrator_agents.py:358) | EI→AR 전달 통합테스트 보강 |

## 5. 주의사항

- `AgentExecutionRequest`가 frozen dataclass이므로 새 객체 생성 필요
- stub agent와 기존 테스트에 영향 없도록 `None` 기본값 유지
- 이 변경은 AIRiskAgent의 입력 품질만 개선하고 출력 스키마는 변경하지 않음
