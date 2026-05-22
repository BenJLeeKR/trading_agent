# Round 12: EI Summary 불일치 수정 + 0-event 분류 진단 로깅

**날짜:** 2026-05-22  
**관련 PR:** (Round 12)  
**관련 이슈:** Fix 4 (exception fallback) 배포 후 일부 symbol은 `event_count` 보정 성공했으나 summary 불일치 발생

---

## 1. 문제 상황

### 1.1 Fix 4 배포 후 상태

Fix 4 (exception fallback에서 `input_event_count` 보존) 배포 후 운영 데이터:

| Symbol | Input Events | Output event_count | no_material_events | Summary |
|--------|-------------|-------------------|-------------------|---------|
| 000670 | 2 | 2 | False | ❌ "유의미한 신규 이벤트 없음" |
| 000990 | 3 | 3 | False | ❌ "유의미한 신규 이벤트 없음" |
| 001740 | 2 | 2 | False | ❌ "유의미한 신규 이벤트 없음" |
| 009150 | 4 | 4 | False | ❌ "유의미한 신규 이벤트 없음" |
| 000210 | 4 | 4 | False | ❌ "유의미한 신규 이벤트 없음" |
| 000810 | 1 | 0 | True | "유의미한 신규 이벤트 없음" (정상) |
| 000660 | ? | 0 | True | "유의미한 신규 이벤트 없음" (정상) |
| 000100 | ? | 0 | True | "유의미한 신규 이벤트 없음" (정상) |
| 000270 | ? | 0 | True | "유의미한 신규 이벤트 없음" (정상) |
| 001440 | ? | 0 | True | "유의미한 신규 이벤트 없음" (정상) |

### 1.2 근본 원인: `_build_ei_summary()` 조건

[`_build_ei_summary()`](src/agent_trading/services/ai_agents/event_interpretation.py:46)의 원래 조건:

```python
if av.no_material_events or not output.events:
    return "유의미한 신규 이벤트 없음..."
```

- Fix 4는 `aggregate_view.event_count`와 `no_material_events`만 보정
- `events` tuple은 여전히 `()` (빈 튜플)
- `not output.events`가 `True` → 무조건 "유의미한 신규 이벤트 없음" 반환
- `event_count > 0`, `no_material_events=False`여도 summary는 거짓 정보

### 1.3 미분류 0-event symbol

일부 symbol은 여전히 `event_count=0`:
- `fallback_applied`: Fix 4가 적용되어 `event_count`가 보정된 경우
- `provider_zero`: Provider가 정상 응답했지만 `events=[]` 반환
- `unknown_zero`: 기타 예외 경로 (exception 발생 + input_events=0)

---

## 2. 적용한 수정

### 2.1 Fix 5: `_build_ei_summary()` 3-way 분기

[`_build_ei_summary()`](src/agent_trading/services/ai_agents/event_interpretation.py:46)의 조건을 3가지 Case로 분리:

```python
# Case 1: 진정한 "이벤트 없음" (no_material_events=True)
if av.no_material_events and not output.events:
    return "유의미한 신규 이벤트 없음..."

# Case 2: event_count > 0 이지만 events=[] (exception fallback 등)
if av.event_count > 0 and not av.no_material_events and not output.events:
    return f"({av.event_count}건) 입력 이벤트 {av.event_count}건 감지됨. "
           f"세부 이벤트 추출 누락. 전반 {bias_str}, 근거:{strength}"

# Case 3: 정상 events 존재
event_count = len(output.events)
# ... 기존 상세 요약
```

**변경 사항:**
- `or` 조건 → 개별 `and` 조건으로 분리
- Case 2에서 `"유의미한 신규 이벤트 없음"` 문구 완전히 제거
- fallback summary 예시: `"(3건) 입력 이벤트 3건 감지됨. 세부 이벤트 추출 누락. 전반 중립, 근거:weak"`

### 2.2 진단 로깅 추가

[`run()`](src/agent_trading/services/ai_agents/event_interpretation.py:201) 메서드에 3가지 분류 로깅 추가:

| 로그 레벨 | 분류 | 조건 | 메시지 |
|-----------|------|------|--------|
| `WARNING` | `provider_zero` | 정상 경로, `event_count=0`, `input_events>0` | Provider가 events 반환했지만 event_count=0 |
| `INFO` | `no_input_events` | 정상 경로, `event_count=0`, `input_events=0` | 정상 케이스 |
| `WARNING` | `fallback_applied` | Exception 경로, `input_events>0` | Fix 4가 event_count 보정 |
| `WARNING` | `unknown_zero` | Exception 경로, `input_events=0` | 기타 예외 |

---

## 3. 테스트

### 3.1 신규 테스트 (5개)

[`TestEIPostProcessingGuard`](tests/services/test_decision_submit_pipeline.py:1421)에 5개 테스트 추가:

| # | 테스트명 | 검증 내용 |
|---|---------|----------|
| 1 | `test_summary_fallback_when_event_count_positive_but_events_empty` | `event_count=3`, `events=[]` → fallback summary, "유의미한 신규 이벤트 없음" 금지 |
| 2 | `test_summary_fallback_with_positive_bias` | `event_count=2`, `events=[]`, bias=positive → fallback with 긍정 |
| 3 | `test_summary_preserves_no_events_when_no_material_events_true` | `no_material_events=True` → "유의미한 신규 이벤트 없음" 유지 (회귀 방지) |
| 4 | `test_summary_normal_path_with_events` | 정상 events 존재 → 기존 상세 요약 경로 유지 (회귀 방지) |
| 5 | `test_summary_fallback_when_event_count_positive_but_events_empty_negative_bias` | `event_count=5`, `events=[]`, bias=negative → fallback with 부정 |

### 3.2 테스트 결과

```
56 passed in 0.35s  (기존 51 + 신규 5)
```

---

## 4. 운영 영향

### 4.1 Fix 5 적용 후 예상 동작

| Symbol | Input | event_count | no_material | events | Summary (after Fix 5) |
|--------|-------|-------------|-------------|--------|----------------------|
| 000670 | 2 | 2 | False | [] | `"(2건) 입력 이벤트 2건 감지됨. 세부 이벤트 추출 누락. 전반 중립, 근거:weak"` |
| 000990 | 3 | 3 | False | [] | `"(3건) 입력 이벤트 3건 감지됨..."` |
| 000810 | 1 | 0 | True | [] | `"유의미한 신규 이벤트 없음. 전반 중립."` (변화 없음) |

### 4.2 진단 로그로 확인 가능한 분류

운영 로그에서 다음 패턴 검색:
- `EI diagnostic: fallback_applied` — Fix 4가 적용된 symbol
- `EI diagnostic: provider_zero` — Provider가 정상 응답했지만 events=0
- `EI diagnostic: unknown_zero` — 기타 예외 (input_events=0 + exception)
- `EI diagnostic: no_input_events` — 정상적으로 입력 events가 없는 경우

---

## 5. 파일 변경 사항

| 파일 | 변경 내용 |
|------|----------|
| [`event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py:46) | `_build_ei_summary()` 3-way 분기 (Case 1/2/3) |
| [`event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py:302) | 진단 로깅 추가 (provider_zero / fallback_applied / unknown_zero / no_input_events) |
| [`test_decision_submit_pipeline.py`](tests/services/test_decision_submit_pipeline.py:1754) | 5개 신규 테스트 추가 |

---

## 6. 다음 단계 (권장)

1. **Docker rebuild & restart** 후 운영 배포
2. **진단 로그 모니터링**: `grep "EI diagnostic"`로 0-event symbol 분류 확인
3. **provider_zero symbol 분석**: Provider가 왜 events=[]를 반환하는지 추가 분석 필요
   - Fix 1 (prompt 강화)가 효과가 없는 symbol 식별
   - Provider 응답(raw_content) 로그 확인
4. **unknown_zero symbol 분석**: exception 발생 원인 추적
