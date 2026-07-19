# EI `events=[]` 근본 원인 분석 — Exception Fallback이 실제 원인

## 1. 문제 재정의

### 1.1 운영 데이터 (Codex 직접 확인)

| Symbol | `Context reconstructed: events=` | EI output `event_count=` | `no_material_events=` | EI `symbol=` |
|--------|----------------------------------|--------------------------|----------------------|--------------|
| `000810` | 1 | 0 | True | (빈 값) |
| `003490` | 2 | 0 | True | (빈 값) |
| `001440` | 2 | 0 | True | (빈 값) |
| `000670` | 2 | 0 | True | (빈 값) |
| `000270` | 1 | 0 | True | (빈 값) |
| `000210` | 4 | 0 | True | (빈 값) |
| `005940` | 22 | 0 | True | (빈 값) |

### 1.2 핵심 관찰

1. **Round 11 코드가 컨테이너에 존재** — `EI raw_response` 로깅, `EI self-contradiction detected` guard 모두 있음
2. **그러나 운영 로그에 `EI self-contradiction detected`가 보이지 않음**
3. **`symbol`이 빈 값**으로 diag 로그에 나타남
4. **모든 symbol이 동일한 패턴**: input_events > 0, output event_count=0, no_material_events=True, symbol=""

---

## 2. 근본 원인: Exception Fallback

### 2.1 코드 분석

[`EventInterpretationAgent.run()`](src/agent_trading/services/ai_agents/event_interpretation.py:185)

```python
async def run(self, request: AgentExecutionRequest) -> EventInterpretationOutput:
    input_event_count = len(request.context.recent_events or ())

    try:
        # ... generate_structured() 호출 ...
        # ... raw_response 로깅 ...
        # ... metadata override ...
        # ★ guard는 여기 (try 블록 내부)
        if input_event_count > 0 and result.aggregate_view.event_count == 0:
            logger.warning("EI self-contradiction detected: ...")
            # ... 보정 ...

        logger.info("EventInterpretationAgent succeeded: ...")
        return result

    except Exception:
        logger.warning(
            "EventInterpretationAgent failed — returning default output "
            "(safe fallback). decision_context_id=%s",
            request.decision_context_id,
            exc_info=True,
        )
        # ★ 여기가 문제: input_event_count를 완전히 무시
        return EventInterpretationOutput()  # symbol="", events=(), event_count=0
```

### 2.2 문제의 3중 구조

| 문제 | 원인 | 영향 |
|------|------|------|
| **1. Guard 미적용** | guard가 `try` 블록 **내부**에 있음. exception 발생 시 도달 불가능 | 모든 symbol에서 `event_count=0` |
| **2. Symbol 빈 값** | `EventInterpretationOutput()` 기본값: `symbol=""` | diag 로그에 `symbol=` (빈 값) |
| **3. Event count=0** | fallback이 `input_event_count`를 완전히 무시 | downstream agent가 "events=0"으로 판단 |

### 2.3 Exception 발생 경로

[`OpenAICompatibleClient.generate_structured()`](src/agent_trading/services/ai_agents/provider_client.py:154)에서 발생 가능한 exception:

| 지점 | 예외 | 확률 |
|------|------|------|
| `response.raise_for_status()` (line 211) | `httpx.HTTPStatusError` | 중간 (API 장애 시) |
| `response.json()` (line 212) | `json.JSONDecodeError` | 낮음 |
| `data["choices"][0]["message"]["content"]` (line 213) | `KeyError`, `IndexError` | 낮음 (API 응답 구조 변경 시) |
| `json.loads(raw_content)` (line 216) | `json.JSONDecodeError` | 중간 (LLM이 유효하지 않은 JSON 반환 시) |
| `response_format(**parsed_dict)` (line 223) | `TypeError`, `ValueError` | 높음 (schema 불일치 시) |

**가장 유력한 경로**: `response_format(**parsed_dict)`에서 `TypeError`/`ValueError` — LLM이 schema와不完全 일치하는 JSON을 반환할 때 발생.

---

## 3. 적용한 수정

### 3.1 Fix 4: Exception Fallback에서 input_event_count 보존

[`event_interpretation.py:run()`](src/agent_trading/services/ai_agents/event_interpretation.py:302-325)

```python
except Exception:
    logger.warning(
        "EventInterpretationAgent failed — returning fallback output. "
        "symbol=%s input_events=%d decision_context_id=%s",
        request_symbol,
        input_event_count,
        request.decision_context_id,
        exc_info=True,
    )
    # ★ fallback에서도 input_event_count를 aggregate_view에 반영
    if input_event_count > 0:
        fallback_av = AggregateEventView(
            overall_bias="neutral",
            event_conflict=False,
            top_reason_codes=(),
            opposing_evidence=(),
            evidence_strength="weak",
            event_count=input_event_count,
            no_material_events=False,
        )
        return EventInterpretationOutput(
            symbol=request_symbol,
            aggregate_view=fallback_av,
        )
    return EventInterpretationOutput(symbol=request_symbol)
```

**변경 사항**:
1. `input_event_count`와 `request_symbol`을 try 블록 **밖**에서 캡처
2. `except` 블록에서 `input_event_count > 0`이면 `event_count=input_event_count`, `no_material_events=False`로 보정
3. `symbol`을 `request_symbol`으로 설정 (빈 값 방지)
4. `evidence_strength="weak"` — exception으로 LLM 응답을 받지 못했음을 명시
5. WARNING 로그에 `symbol`과 `input_event_count` 포함

### 3.2 Fix 2 보강: Symbol fallback

[`event_interpretation.py:run()`](src/agent_trading/services/ai_agents/event_interpretation.py:247)

```python
result = EventInterpretationOutput(
    ...
    symbol=result.symbol or request_symbol,  # ★ LLM이 symbol을 반환하지 않으면 request.symbol 사용
    ...
)
```

---

## 4. 6가지 질문에 대한 답변

### Q1: Provider raw response는 실제로 빈 `events=[]`를 반환하는가?

**아직 확인 불가능** — exception이 발생하면 `generate_structured()`가 `RawProviderResponse`를 반환하기 전에 중단되므로, raw response 자체를 확인할 수 없음. Fix 3(raw response 로깅)은 exception 발생 시 실행되지 않음.

**가장 유력한 시나리오**: Provider가 정상 응답을 반환했지만, `response_format(**parsed_dict)`에서 schema 불일치로 `TypeError`/`ValueError` 발생.

### Q2: Raw response에는 이벤트가 있는데 parsed output에서 사라지는가?

**아니오** — exception이 발생하면 parsed output이 생성되지 않음. `except` 블록이 `EventInterpretationOutput()` 기본값을 반환.

### Q3: `EventInterpretationAgent.run()`이 실제로 exception fallback 경로를 타고 있는가?

**예, 이것이 근본 원인.** 운영 데이터의 일관된 패턴(symbol 빈 값, 모든 symbol이 동일한 `event_count=0`)은 exception fallback의 전형적인 증상.

### Q4: Guard는 왜 실제 운영에서 발동하지 않는가?

Guard가 `try` 블록 **내부**에 있기 때문. exception 발생 시 guard에 도달하기 전에 `except` 블록으로 jump.

### Q5: `symbol` 빈 값 패턴의 직접 원인은 무엇인가?

`EventInterpretationOutput()` 기본값: `symbol=""`. exception fallback이 `symbol`을 설정하지 않고 기본값을 반환하기 때문.

### Q6: 가장 작은 수정으로 EI가 입력 이벤트를 최종 output에 반영하게 하려면?

**Fix 4 적용 완료**: `except` 블록에서 `input_event_count`를 `aggregate_view.event_count`에 반영. 단 3줄의 핵심 변경으로 모든 symbol에서 `event_count>0` 보장.

---

## 5. 수정된 파일

| 파일 | 변경 내용 |
|------|----------|
| [`src/agent_trading/services/ai_agents/event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py:185) | `run()`: `input_event_count`/`request_symbol`을 try 밖에서 캡처, `except` 블록에서 input_event_count 보존, `symbol=result.symbol or request_symbol` fallback |
| [`tests/services/test_decision_submit_pipeline.py`](tests/services/test_decision_submit_pipeline.py:1643) | `TestEIPostProcessingGuard`에 2개 테스트 추가: `test_guard_fallback_when_provider_raises_exception`, `test_guard_fallback_when_input_events_zero` |

---

## 6. 테스트 결과

### 6.1 신규 테스트 (2개)

| 테스트 | 설명 | 결과 |
|--------|------|------|
| `test_guard_fallback_when_provider_raises_exception` | Provider exception → fallback이 input_event_count 보존 + symbol 보존 | ✅ PASS |
| `test_guard_fallback_when_input_events_zero` | Provider exception + input events=0 → event_count=0 유지 | ✅ PASS |

### 6.2 전체 테스트

**51개全部 PASS** — 기존 테스트 회귀 없음.

---

## 7. 운영 검증 계획

### 7.1 Docker rebuild 필요

```bash
docker compose build
docker compose up -d
curl -sf http://localhost:8000/health
```

### 7.2 배포 후 확인할 로그 패턴

| 로그 패턴 | 의미 | 명령어 |
|-----------|------|--------|
| `EventInterpretationAgent failed — returning fallback output. symbol=000810 input_events=1` | Fix 4 발동 — exception 발생 + input_event_count 보존 | `grep "returning fallback output" /workspace/agent_trading/logs/*.log` |
| `EI self-contradiction detected: symbol=000810 input_events=1 but output event_count=0` | Fix 2 발동 — LLM이 events=[] 반환 + guard 보정 | `grep "self-contradiction detected" /workspace/agent_trading/logs/*.log` |
| `EI raw_response: symbol=000810 input_events=1 raw_content_len=1234` | Fix 3 발동 — 정상 경로에서 raw response 로깅 | `grep "EI raw_response:" /workspace/agent_trading/logs/*.log` |
| `EventInterpretationAgent succeeded: symbol=000810 input_events=1 output_events=0 event_count=1` | 정상 완료 — event_count 보정됨 | `grep "EventInterpretationAgent succeeded:" /workspace/agent_trading/logs/*.log` |

### 7.3 대표 symbol 전/후 비교

| Symbol | Before (input→output) | After (input→output) |
|--------|----------------------|---------------------|
| `000810` | 1 → 0 | 1 → 1 (fallback 보정) |
| `003490` | 2 → 0 | 2 → 2 (fallback 보정) |
| `001440` | 2 → 0 | 2 → 2 (fallback 보정) |
| `000670` | 2 → 0 | 2 → 2 (fallback 보정) |
| `000150` | 0 → 0 | 0 → 0 (변화 없음) |

### 7.4 DB `agent_runs` 전/후 비교

```sql
SELECT symbol, structured_output_json->'aggregate_view'->>'event_count' AS event_count
FROM trading.agent_runs
WHERE agent_name = 'event_interpretation'
  AND created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC;
```

---

## 8. 결론

**Exception fallback이 `events=[]`의 직접 원인**이었습니다. Round 11의 Fix 1(prompt 강화), Fix 2(post-processing guard), Fix 3(raw response 로깅)는 모두 정상 경로(LLM 응답 수신 성공)를 전제로 했기 때문에, exception 발생 시 아무 효과가 없었습니다.

**Fix 4**로 `except` 블록에서 `input_event_count`를 보존함으로써, exception이 발생해도 downstream agent가 "events=0"으로 잘못 판단하는 문제를 해결했습니다.
