# EI Provider가 events를 받고도 `events=[]` 반환하는 문제 — 분석 및 수정 보고서

## 1. 문제 상황

### 1.1 운영 데이터 확인 (Round 10 debug logging)

| Symbol | `_reconstruct_context` recent_events_raw count | reconstructed count | EI output `events=` | EI output `event_count=` |
|--------|-------------------------------------------------|---------------------|---------------------|--------------------------|
| `000810` | 1 | 1 | `[]` | 0 |
| `003490` | 2 | 2 | `[]` | 0 |
| `000150` | 0 | 0 | `[]` | 0 (정상) |

**핵심 발견**: `000810`(1개), `003490`(2개)는 serialization/deserialization 경로를 정상 통과하여 `reconstructed count`가 input과 일치하지만, EI의 최종 output은 `events=[]`, `event_count=0`, `no_material_events=true`를 반환.

### 1.2 이전 수정과의 차별점

- **Round 9**: `include_seeded_news` 파라미터 도입 — `list_by_symbol()`이 `seeded_news` 타입 이벤트를 포함하도록 수정. **이미 해결됨.**
- **Round 10**: 4개 checkpoint debug logging 추가. serialization/deserialization 경로가 정상임을 확인.
- **Round 11 (본 분석)**: Provider(LLM)가 prompt에 events를 받고도 `events=[]`를 반환하는 문제를 추적.

---

## 2. 코드 분석: EI 전체 흐름

### 2.1 흐름도

```
_build_user_prompt()  →  generate_structured()  →  _coerce_nested_json_strings()  →  response_format(**parsed_dict)  →  RawProviderResponse  →  run() post-processing
```

### 2.2 각 단계 분석

#### 단계 1: `_build_user_prompt()` (event_interpretation.py:358)

- `context.recent_events`를 순회하며 각 event의 `headline`, `body_summary`, provenance tags(source, tier, type, date, issuer, severity, direction, stale)를 prompt에 포함
- **문제 없음** — prompt에 실제 event headline/summary가 포함됨

#### 단계 2: `generate_structured()` (provider_client.py:154)

- HTTP POST `/v1/chat/completions` → JSON 파싱 → `_coerce_nested_json_strings()` → `response_format(**parsed_dict)` → `RawProviderResponse(parsed, raw_content)`
- **문제 없음** — DeepSeek의 nested object serialization을 `_coerce_nested_json_strings()`가 정상 처리

#### 단계 3: `_coerce_nested_json_strings()` (provider_client.py:21)

- JSON-string 필드를 재귀적으로 dict로 변환 (DeepSeek가 nested dataclass를 JSON string으로 직렬화하는 현상 대응)
- **문제 없음** — `events` 필드가 JSON string이면 list로, `aggregate_view`가 JSON string이면 dict로 변환

#### 단계 4: `response_format(**parsed_dict)` → `EventInterpretationOutput.__post_init__()` (schemas.py:284)

- `events`가 string이면 `()`로 fallback
- `aggregate_view`가 string이면 `AggregateEventView()` default로 fallback
- **문제 없음** — 정상적인 dict/list가 전달되면 fallback이 발동하지 않음

#### 단계 5: `run()` post-processing (event_interpretation.py:185)

- `raw_response.parsed`를 `EventInterpretationOutput`으로 사용
- metadata fields override (schema_version, agent_name, decision_context_id, symbol, issuer_code)
- **문제 발견**: Provider(LLM)가 `events=[]`, `event_count=0`, `no_material_events=true`를 반환하면 그대로 사용됨

### 2.3 근본 원인

**Provider(LLM)가 prompt에 events가 포함되어 있음에도 `events=[]`를 반환함.**

`EventInterpretationOutput`의 기본값:
- `events: tuple[InterpretedEvent, ...] = ()`
- `aggregate_view: AggregateEventView = field(default_factory=AggregateEventView)`
- `AggregateEventView` 기본값: `event_count=0`, `no_material_events=True`

LLM이 `events=[]`를 반환하면 위 기본값이 그대로 사용되어 `event_count=0`, `no_material_events=true`가 됨.

---

## 3. 적용한 수정 (3가지)

### 3.1 Fix 1: Prompt 강화 — "CRITICAL: Event count MUST match input" 섹션 추가

**파일**: [`src/agent_trading/services/ai_agents/event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py:311) — `_build_system_prompt()`

**내용**:
- "Recent events (N):" 섹션에 N > 0이면 반드시 `event_count=N`, `no_material_events=false`를 설정하도록 지시
- `event_count=0`은 오직 "Recent events (0):"일 때만 유효
- events가 제공되었지만 material하지 않다고 판단해도 `event_count=N`, `no_material_events=false` 유지, `evidence_strength='weak'`로 표현

### 3.2 Fix 2: Deterministic post-processing guard

**파일**: [`src/agent_trading/services/ai_agents/event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py:185) — `run()`

**내용**:
- `input_event_count = len(request.context.recent_events or ())` — 입력 events 수를 미리 기록
- `input_event_count > 0 and result.aggregate_view.event_count == 0` 조건에서:
  - WARNING 로그 출력 ("EI self-contradiction detected")
  - `AggregateView`의 `event_count`를 `input_event_count`로, `no_material_events`를 `False`로 보정
  - LLM이 반환한 `events` tuple, `overall_bias`, `evidence_strength`, `top_reason_codes` 등은 **그대로 유지**
  - `events` tuple이 빈 tuple이어도 보정하지 않음 (LLM이 events를 해석하지 못한 것은 별도 문제)

### 3.3 Fix 3: Raw response 로깅

**파일**: [`src/agent_trading/services/ai_agents/event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py:185) — `run()`

**내용**:
- `raw_response.raw_content` 길이를 INFO 레벨에 로깅
- `raw_response.raw_content` 전체 내용을 DEBUG 레벨에 로깅
- 성공 로그에 `input_events`, `output_events`, `event_count`, `no_material_events`, `overall_bias`, `evidence_strength` 포함

**파일**: [`scripts/run_agent_subprocess.py`](scripts/run_agent_subprocess.py:571) — `main()`

**내용**:
- `_diag()`에 `input_events`, `output_events`, `event_count`, `no_material_events` 포함

---

## 4. 5가지 질문에 대한 답변

### Q1: EI prompt에 실제 어떤 이벤트 텍스트가 들어가는가?

`_build_user_prompt()` (event_interpretation.py:358)는 `context.recent_events`의 각 `ExternalEventEntity`에 대해 다음 정보를 포함:

```
## Recent events (N):
### Event 1
- **Headline**: {headline}
- **Summary**: {body_summary}
- **Source**: {source_name} (Tier: {source_reliability_tier})
- **Type**: {event_type}
- **Published**: {published_at}
- **Issuer**: {issuer_code}
- **Severity**: {severity}
- **Direction**: {direction}
- **Stale**: {stale}
```

운영 데이터에서 `000810`은 1개, `003490`은 2개의 event headline/summary가 prompt에 포함됨.

### Q2: Provider raw response가 무엇을 반환하는가?

`generate_structured()` (provider_client.py:154)는 HTTP POST 응답을 JSON 파싱 후 `_coerce_nested_json_strings()`로 nested field를 정규화하고 `RawProviderResponse(parsed, raw_content)`로 반환.

**Fix 3**에서 추가한 DEBUG 로깅으로 실제 raw_content를 확인 가능:
```python
logger.debug("EI raw_response raw_content: symbol=%s raw_content=%s",
             request.symbol, raw_response.raw_content)
```

### Q3: `EventInterpretationOutput` parsing/normalization 과정에서 event loss가 발생하는가?

**분석 결과: Loss 없음.**

- `_coerce_nested_json_strings()`: JSON string → dict/list 변환 정상
- `response_format(**parsed_dict)`: dataclass 생성 정상
- `EventInterpretationOutput.__post_init__()`: string fallback은 정상 dict/list가 전달되면 발동하지 않음
- `run()` post-processing: metadata override만 수행, events/aggregate_view는 그대로 유지

**결론**: Serialization/deserialization 경로는 정상. Loss는 Provider(LLM)가 `events=[]`를 반환하는 데서 발생.

### Q4: 최소한의 fix로 이 문제를 해결할 수 있는가?

**3가지 fix 적용 완료**:
1. **Prompt 강화** (최소 fix) — LLM이 `event_count=0`을 반환하지 않도록 지시
2. **Post-processing guard** (안전장치) — LLM이 지시를 무시해도 `event_count` 보정
3. **Raw response 로깅** (운영 디버깅) — 실제 raw response 확인 가능

### Q5: Deterministic guard가 self-contradiction을 완전히 해결하는가?

**부분적 해결**:
- `aggregate_view.event_count`와 `no_material_events`는 보정됨 → downstream agent가 "events=0"으로 판단하는 문제 해결
- `events` tuple은 LLM이 반환한 그대로 유지 → `events`가 빈 tuple이면 downstream agent가 event detail을 볼 수 없음
- **Prompt 강화**가 근본적인 해결책이며, guard는 안전장치 역할

---

## 5. 테스트 결과

### 5.1 신규 테스트: `TestEIPostProcessingGuard` (3개)

| 테스트 | 설명 | 결과 |
|--------|------|------|
| `test_guard_corrects_when_input_events_exist_but_output_zero` | input events > 0, output event_count=0 → guard 보정 | ✅ PASS |
| `test_guard_does_not_correct_when_input_events_zero` | input events = 0 → guard 보정하지 않음 | ✅ PASS |
| `test_guard_preserves_llm_events_when_output_has_events` | LLM 정상 반환 → guard 개입하지 않음 | ✅ PASS |

### 5.2 전체 테스트: `test_decision_submit_pipeline.py`

**49개全部 PASS** — 기존 테스트 회귀 없음.

---

## 6. 수정된 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| [`src/agent_trading/services/ai_agents/event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py:185) | `run()`: input_event_count 추적, raw response 로깅, post-processing guard, enhanced success logging |
| [`src/agent_trading/services/ai_agents/event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py:311) | `_build_system_prompt()`: "CRITICAL: Event count MUST match input" 섹션 추가 |
| [`scripts/run_agent_subprocess.py`](scripts/run_agent_subprocess.py:571) | `main()`: `_diag()`에 input/output event counts 포함 |
| [`tests/services/test_decision_submit_pipeline.py`](tests/services/test_decision_submit_pipeline.py:1421) | `TestEIPostProcessingGuard` 클래스 추가 (3개 테스트) |

---

## 7. 운영 배포 시 확인 사항

1. **Docker rebuild 필요**: `docker-compose build` + `docker-compose up -d`
2. **로그 확인**: 배포 후 `000810`, `003490`에서 EI 로그 확인
   - `EI raw_response: symbol=000810 ... input_events=1 raw_content_len=...`
   - `EI self-contradiction detected: symbol=000810 input_events=1 but output event_count=0` (guard 발동 시)
   - `EventInterpretationAgent succeeded: symbol=000810 input_events=1 output_events=0 event_count=1 no_material_events=false`
3. **DEBUG 레벨 로깅**: 필요시 `raw_content` 전체 내용 확인
4. **`000150` 회귀 확인**: genuinely 0 event symbol에서 `event_count=0` 유지되는지 확인
