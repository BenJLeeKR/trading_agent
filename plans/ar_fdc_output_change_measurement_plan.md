# AR/FDC Prompt/Context Quality 계측 계획 — EI→AR→FDC provenance 전파 이후

## 1. 목적

EI provenance 개선 + AR/FDC 전파 개선이 실제 AR/FDC **prompt/context quality**에
어떤 변화를 주는지 계측. "구조 개선(provenance tag 포함)"과 "context quality 개선"을
구분하여 보고.

**중요**: 이번 턴은 `output quality 개선 가능성을 높이는 prompt/context 개선`을 계측하는 것이지,
`output quality 자체를 증명`하는 것이 아니다. Provider 호출 결과는 탐색적 관찰(exploratory observation)로만 기록.

## 2. 현재 상태 요약

| 개선 단계 | 상태 | 계측 가능 여부 |
|-----------|------|---------------|
| EI prompt provenance 강화 (P1-A) | ✅ 완료 | token +72.9%, 5종 tag 정상 |
| 72h retention (P1-B) | ✅ 완료 | 코드 레벨 검증 완료 |
| AR events section provenance 전파 | ✅ 완료 | 모든 symbol에서 tag 정상 |
| FDC events section provenance 전파 | ✅ 완료 | 모든 symbol에서 tag 정상 |
| AR Symbol line BUG 수정 | ✅ 완료 | `DecisionContextEntity` repr 없음 |
| **AR/FDC context quality 변화** | **❌ 미계측** | **이번 작업 대상** |

## 3. 측정 불가능한 항목과 대체 방법

### 3.1 Provider 호출 없이 직접 측정 불가능

| 항목 | 이유 | 대체 방법 |
|------|------|-----------|
| `risk_opinion` 변화 | LLM 출력 결과 | **context quality**(정보 밀도) 간접 계측 |
| `decision_type` 변화 | LLM 출력 결과 | **context quality**(정보 밀도) 간접 계측 |
| `summary` 텍스트 품질 | LLM 생성 결과 | **context depth** 계량 정의로 대체 |
| `opposing_evidence` 텍스트 | LLM 생성 결과 | **context depth** 계량 정의로 대체 |

### 3.2 Provider 없이 계측 가능한 항목

| 항목 | 계측 방법 | 지표 유형 |
|------|-----------|-----------|
| Prompt token 증가 (old vs new AR/FDC) | `_estimate_tokens()` | **보조 지표** |
| Provenance tag 수 (AR/FDC) | `_count_provenance_tags()` | **핵심 지표** |
| EI structured field 전파 범위 | field별 포함 여부 → % coverage | **핵심 지표** |
| AR structured field 전파 범위 (→FDC) | field별 포함 여부 → % coverage | **핵심 지표** |
| Symbol line 정상화 확인 | Symbol line 문자열 비교 | **핵심 지표** |
| Useful tags per event | `provenance_tags_count / event_count` | **정보 밀도** |
| Critical context fields present | 연속성 필드 complete 비율 | **정보 밀도** |
| Reason-code-related upstream fields 수 | score/reason_codes/event_tags 동시 존재 여부 | **context depth** |

### 3.3 `context depth`의 계량 정의

`context depth`는 아래 3개 하위 항목의 종합 점수로 정의:

| 항목 | 계량 방법 | 최대값 |
|------|-----------|--------|
| **Reason-code upstream fields** | prompt 내 `score.reason_codes` + `event provenance tags` + `aggregate_view.top_reason_codes` 동시 존재 여부 | 3점 |
| **Event context richness** | headline + summary + provenance tag(5종) 동시 존재 event 비율 | 5점 |
| **Agent continuity coverage** | 상위 agent output field 전파율 (EI→AR: 4fields, EI+AR→FDC: 4+7fields) | 11점 |

### 3.4 선택적 Provider 호출 (2차, 탐색적 관찰)

**대상**: `030200` (event 5건)

선택 근거:
- Event count 5건으로 가장 풍부한 context 보유
- Provenance tags 풍부 (src/tier/issuer 모두 정상)
- OpenDART row 안정적 (동일 유형 5회 반복 → provider 일관성 평가에 유리)
- 이전 계측에서도 baseline 역할 수행

**호출 방식**:
- 동일 symbol/event set으로 old-style vs new-style prompt 각각 provider 호출
- 가능하면 2~3회 반복하여 비결정성(nondeterminism) 확인
- 결과가 흔들리면 "탐색적 관찰"로만 기록, definitive proof로 사용하지 않음

**결과 해석 규칙**:
```
- old/new 모두 동일 output = "변화 없음" (context quality 불충분 또는 기존으로도 충분)
- new에서만 특정 field 변화 = "탐색적 관찰: context quality 개선 가능성"
- 2~3회 중 결과不一致 = "비결정성으로 인해 결론 보류"
- 절대 "prompt 개선이 output을 개선했다"는 인과 주장 금지
```

## 4. 측정 항목 상세

### 4.1 AR Prompt 비교 (old vs new)

**Old-style AR prompt** (P1-A + AR 전파 이전) — `_build_old_style_ar_prompt()`:

```
※ approximate reconstruction: 실제 historical format과 100% 일치하지 않을 수 있음
※ P1-A 이전 ai_risk.py의 _build_user_prompt()를 측정 스크립트 기준으로 재현

events:
  - [{event_type}] {headline}
  (dash prefix, no provenance tags)
Symbol line:
  Symbol: {decision_context or '(not available)'}
  (BUG 상태: decision_context=None → fallback, 설정 시 객체 repr)
EI section, position/cash/risk sections:
  동일 (변경 없음)
```

**New-style AR prompt** (현재) — 현재 `_build_user_prompt()` 그대로 사용:
```
events: provenance-rich format (5종 tag + stale + default omission)
Symbol line: events 기반 symbol (BUG 수정됨)
EI section, position/cash/risk sections: 동일
```

**비교 항목**:

| 지표 | 유형 | 측정 방식 |
|------|------|-----------|
| Useful tags per event | **핵심** | `provenance_tags_count / event_count` |
| Symbol line correctness | **핵심** | `"Symbol: {symbol}"` vs `"DecisionContextEntity" in symbol_line` |
| EI field continuity coverage | **핵심** | `overall_bias + event_conflict + top_reason_codes + interpreted_events` = 4/4 |
| Reason-code upstream fields | **context depth** | score.reason_codes + event tags + aggregate_view.top_reason_codes |
| Token 증가율 | **보조** | `(new - old) / old * 100` |

### 4.2 FDC Prompt 비교 (old vs new)

**Old-style FDC prompt** — `_build_old_style_fdc_prompt()`:

```
※ approximate reconstruction
events:   - [{event_type}] {headline} (dash prefix, no provenance)
EI section, AR section: 동일 (변경 없음)
```

**New-style FDC prompt** (현재):
```
events: provenance-rich format
EI section + AR section: 동일
```

**비교 항목**:

| 지표 | 유형 | 측정 방식 |
|------|------|-----------|
| Useful tags per event | **핵심** | `provenance_tags_count / event_count` |
| EI field continuity coverage | **핵심** | 4 fields 전파 여부 |
| **AR field continuity coverage** | **핵심** | `risk_opinion + risk_score + confidence + size_adj + reason_codes + opposing_evidence + summary` = 7/7 |
| **EI+AR combined continuity** | **핵심** | 4+7 = 11 fields coverage % |
| Token 증가율 | **보조** | `(new - old) / old * 100` |

### 4.3 Context depth 계량

| 항목 | 점수 | AR | FDC |
|------|------|----|-----|
| score.reason_codes 존재 | 1 | ✅/❌ | ✅/❌ |
| Event provenance tags 존재 | 1 | ✅/❌ | ✅/❌ |
| aggregate_view.top_reason_codes 존재 | 1 | ✅/❌ | ✅/❌ |
| **Reason-code depth (0-3)** | | **n/3** | **n/3** |
| Headline + summary + 5종 tag 동시 존재 event 비율 | 0-5 | **n/5** | **n/5** |
| **상위 agent continuity** | | EI→AR 4fields | EI+AR→FDC 11fields |
| **Context depth 종합** | | **가중합** | **가중합** |

## 5. 판정 기준

### 5.1 `명확한 개선` ✅

아래 4가지 조건을 모두 충족:
1. **Provenance tags complete**: 모든 event에 `[src:]`, `[tier:]`, `[issuer:]` 정상 포함
2. **Symbol line corrected** (AR): `DecisionContextEntity` repr 완전 제거, 정상 symbol 출력
3. **EI→AR continuity improved** (AR): 4/4 fields 전파
   **EI+AR→FDC continuity improved** (FDC): 11/11 fields 전파
4. **Token overhead acceptable**: token 증가율이 context quality 대비 합리적 수준

### 5.2 `제한적 개선` 🟡

아래 조건 중 하나라도 해당:
1. **Partial provenance/continuity**: 일부 tag/field 전파는 있으나 critical gap 존재
2. **Symbol line conditional**: 특정 조건에서만 정상 (예: events 있을 때만)
3. **Token overhead 경고**: token 증가 대비 useful information 증가가 미미

### 5.3 `불명확` ❌

아래 조건 중 하나라도 해당:
1. **Major gap 잔존**: provenance tag 미전파 또는 continuity 50% 미만
2. **Information 증가가 noise**: token만 증가하고 useful tag/field 증가 없음
3. **Symbol line 미수정**: `DecisionContextEntity` repr 여전히 노출

## 6. 구현할 측정 스크립트

**방식**: 기존 [`scripts/ei_improvement_measurement.py`](scripts/ei_improvement_measurement.py) 확장

**추가할 함수**:
- `_build_old_style_ar_prompt(events, score, correlation_id, context)` — old-style AR prompt 재현 (※ approximate reconstruction)
- `_build_old_style_fdc_prompt(events, score, correlation_id, context, ei_output, ar_output)` — old-style FDC prompt 재현 (※ approximate reconstruction)
- `_measure_prompt_quality(name, old_prompt, new_prompt, events)` — 핵심/보조 지표 계측
- `_compute_context_depth(prompt_text)` — context depth 계량

**Provider 호출 모드** (선택적):
- `--with-provider` 플래그 추가 시 1개 symbol(030200)만 provider 호출
- 기본은 read-only 모드
- 결과는 "탐색적 관찰"로만 기록

## 7. 측정 symbol

기존과 동일하게 3개 symbol 유지 (postgres 데이터 기반):

| Symbol | Event 수 | 특성 | 측정 적합성 |
|--------|----------|------|------------|
| `030200` | 5건 | 동일 유형(`Y|임원...`) 5회 반복 | 중복/반복 처리 평가 최적, **provider 호출 대상** |
| `327260` | 4건 | 유상증자 관련 다양한 이벤트 | 해석 다양성 평가 최적 |
| `090150` | 4건 | 채권/주총 관련 이벤트 | impact 방향성 평가 최적 |

## 8. Mermaid: 측정 흐름

```mermaid
flowchart TD
    A[Postgres: 3 symbols] --> B[list_by_symbol 72h]
    B --> C[동일 event set으로 old/new prompt 생성]
    
    C --> D[AR old prompt approx]
    C --> E[AR new prompt = 현재 _build_user_prompt]
    C --> F[FDC old prompt approx]
    C --> G[FDC new prompt = 현재 _build_user_prompt]
    
    D --> H[AR prompt 비교]
    E --> H
    H --> H1[provenance completeness 핵심]
    H --> H2[symbol line correctness 핵심]
    H --> H3[EI continuity 4/4 핵심]
    H --> H4[token overhead 보조]
    
    F --> I[FDC prompt 비교]
    G --> I
    I --> I1[provenance completeness 핵심]
    I --> I2[EI continuity 4/4 핵심]
    I --> I3[AR continuity 7/7 핵심]
    I --> I4[EI+AR combined 11/11 핵심]
    I --> I5[token overhead 보조]
    
    H --> J[context depth 계량]
    I --> J
    
    J --> K{--with-provider?}
    K -->|yes (030200 only)| L[old/new 각각 provider 호출 2-3회]
    K -->|no| M[Read-only report]
    L --> N[탐색적 관찰 기록]
    N --> O[최종 보고서]
    M --> O
```

## 9. 성공 조건

- [ ] 3개 symbol 모두 AR old/new prompt 비교 완료 (provenance completeness + symbol line + EI continuity + token)
- [ ] 3개 symbol 모두 FDC old/new prompt 비교 완료 (provenance completeness + EI+AR continuity + token)
- [ ] context depth 계량 완료 (reason-code depth + event context richness + agent continuity)
- [ ] 최종 판정: "명확한 개선 / 제한적 개선 / 불명확" 분류
- [ ] (선택) 030200 provider 호출 2-3회 → 탐색적 관찰 기록

## 10. 제약 조건

| 제약 | 준수 방법 |
|------|-----------|
| Provider 호출 최소화 | 기본 read-only, `--with-provider` 플래그로 선택적 분리 |
| DB write 금지 | Read-only 쿼리만 사용 |
| Production semantics 변경 금지 | 측정 스크립트만 변경, source code 건드리지 않음 |
| Source adapter 변경 금지 | 해당 없음 |
| Output schema 변경 금지 | 해당 없음 |
| Old prompt 재현 신뢰도 | `approximate reconstruction` 명시, historical 100% 일치 보장 없음 |
| Provider 결과 해석 | "탐색적 관찰"로 기록, 인과 주장 금지 |
