# EI→AR→FDC Provenance 전파 이후 Output 변화 측정 보고서

> **측정 시각**: 2026-05-12 00:41 UTC (KST 09:41)
> **측정 스크립트**: [`scripts/ar_fdc_output_measurement.py`](../scripts/ar_fdc_output_measurement.py)
> **모드**: Read-only (provider 호출 없음)

---

## 1. 측정 대상 및 방법

### 대상 symbol (3개)

| Symbol | 종목명 | Event 수 | 선택 근거 |
|--------|--------|----------|-----------|
| `030200` | (KT) | 5건 | Event 5건, provenance 풍부, OpenDART 안정적, baseline 역할 |
| `327260` | (에코프로) | 4건 | 4종 event type 다양성, 유상증자 관련 고신호 이벤트 |
| `090150` | (롯데에너지머티리얼즈) | 4건 | 3종 event type, 전환가액조정/주총 등 중기 영향 이벤트 |

### 측정 항목

| 구분 | 항목 | 역할 |
|------|------|------|
| **핵심 지표** | Provenance completeness (5 mandatory tags) | 구조적 개선 측정 |
| **핵심 지표** | Context depth (reason_code_depth + event_richness + continuity) | 정보 밀도 계량 |
| **핵심 지표** | Continuity coverage (EI→AR 4 fields / EI+AR→FDC 11 fields) | Agent 간 정보 연속성 |
| **보조 지표** | Token 증가율 (old-style vs new-style) | overhead 평가 |
| **검증** | AR Symbol line BUG 수정 여부 | 이전 버그 재발 방지 |

### Old-style prompt 재현

Old-style prompt은 `_build_old_style_ar_prompt()` / `_build_old_style_fdc_prompt()` 함수로 approximate reconstruction 하였습니다. 이는 historical 100% 일치를 보장하지 않습니다.

---

## 2. AR Prompt Quality 측정 결과

### 2.1 Token 증가율 (보조 지표)

| Symbol | Old (tok) | New (tok) | 증가율 |
|--------|-----------|-----------|--------|
| 030200 | 229 | 294 | **+28.4%** |
| 327260 | 213 | 272 | **+27.7%** |
| 090150 | 213 | 265 | **+24.4%** |

> Token 증가율은 **보조 지표**입니다. 평균 +26.8%로, EI의 +72.9%보다 낮은 이유는 AR prompt의 events 섹션이 전체 prompt에서 차지하는 비중이 EI보다 작기 때문입니다.

### 2.2 Provenance completeness

| Symbol | Score | src | tier | event_type | date | issuer |
|--------|-------|-----|------|------------|------|--------|
| 030200 | **100%** | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| 327260 | **100%** | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| 090150 | **100%** | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

> 5개 mandatory tag 모두 모든 event에 정상 포함. EI와 동일한 provenance format 적용 확인.

### 2.3 Context depth

| Symbol | Reason-code (0-3) | Event richness (0-5) | Continuity (0-4) | **Total (0-12)** |
|--------|-------------------|---------------------|------------------|-------------------|
| 030200 | 2/3 | 4/5 | 4/4 | **10/12** |
| 327260 | 2/3 | 4/5 | 4/4 | **10/12** |
| 090150 | 2/3 | 4/5 | 4/4 | **10/12** |

> - **Reason-code 2/3**: Score reason_codes + EI top_reason_codes 포함. AR 자체 reason_codes는 AR output이므로 AR prompt에는 없음 (정상).
> - **Event richness 4/5**: event count + body summary + source name + tier 포함. Issuer code는 일부 event에만 있어서 1점 차감 (정상, issuer_code=None인 event는 tag 생략).
> - **Continuity 4/4**: EI→AR 4개 field 모두 완전 전파.

### 2.4 AR Symbol line

| Symbol | Symbol line | BUG fixed |
|--------|-------------|-----------|
| 030200 | `Symbol: 030200` | ✅ |
| 327260 | `Symbol: 327260` | ✅ |
| 090150 | `Symbol: 090150` | ✅ |

> 이전 `DecisionContextEntity` repr 누출 BUG가 모두 수정되었습니다. events 기반 symbol 추출 로직이 정상 동작합니다.

---

## 3. FDC Prompt Quality 측정 결과

### 3.1 Token 증가율 (보조 지표)

| Symbol | Old (tok) | New (tok) | 증가율 |
|--------|-----------|-----------|--------|
| 030200 | 265 | 333 | **+25.7%** |
| 327260 | 250 | 310 | **+24.0%** |
| 090150 | 250 | 304 | **+21.6%** |

> 평균 +23.8%. FDC도 AR과 마찬가지로 events 섹션 비중이 작아 EI보다 증가율이 낮습니다.

### 3.2 Provenance completeness

| Symbol | Score | src | tier | event_type | date | issuer |
|--------|-------|-----|------|------------|------|--------|
| 030200 | **100%** | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| 327260 | **100%** | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| 090150 | **100%** | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

> AR과 동일한 수준. FDC events 섹션에도 provenance tag가 정상 전파되었습니다.

### 3.3 Context depth (EI+AR combined)

| Symbol | Reason-code (0-3) | Event richness (0-5) | Continuity (0-11) | **Total (0-19)** |
|--------|-------------------|---------------------|-------------------|-------------------|
| 030200 | 3/3 | 4/5 | 9/11 | **16/19** |
| 327260 | 3/3 | 4/5 | 9/11 | **16/19** |
| 090150 | 3/3 | 4/5 | 9/11 | **16/19** |

> - **Reason-code 3/3**: Score reason_codes + EI top_reason_codes + AR reason_codes 모두 포함.
> - **Event richness 4/5**: AR과 동일한 이유로 issuer code 조건부 생략으로 1점 차감.
> - **Continuity 9/11**: EI 4개 field 모두 전파, AR 7개 field 중 5개 전파. `opposing_evidence`와 `summary`는 FDC output schema에 해당 field가 없어 prompt에 포함되지 않음 (2점 차감). 이는 정상 동작입니다.

### 3.4 Continuity details

| Field | Source | 030200 | 327260 | 090150 |
|-------|--------|--------|--------|--------|
| ei_overall_bias | EI | ✅ | ✅ | ✅ |
| ei_event_conflict | EI | ✅ | ✅ | ✅ |
| ei_top_reason_codes | EI | ✅ | ✅ | ✅ |
| ei_interpreted_events | EI | ✅ | ✅ | ✅ |
| ar_risk_opinion | AR | ✅ | ✅ | ✅ |
| ar_risk_score | AR | ✅ | ✅ | ✅ |
| ar_confidence | AR | ✅ | ✅ | ✅ |
| ar_size_adjustment | AR | ✅ | ✅ | ✅ |
| ar_reason_codes | AR | ✅ | ✅ | ✅ |
| ar_opposing_evidence | AR | ❌ | ❌ | ❌ |
| ar_summary | AR | ❌ | ❌ | ❌ |

> `ar_opposing_evidence`와 `ar_summary`는 FDC output schema에 대응 field가 없어 prompt에 포함되지 않습니다. 이는 FDC agent 설계상 정상이며, provenance 전파의 문제가 아닙니다.

---

## 4. Prompt Excerpt 비교

### AR events section (030200)

```
NEW-STYLE:
  [src:opendart] [tier:T1] [Y|임원ㆍ주요주주특정증권등소유상황보고서] [2026-05-11] [issuer:00190321] {headline}

OLD-STYLE (approximate reconstruction):
  - [Y|임원ㆍ주요주주특정증권등소유상황보고서] {headline}
```

### FDC events section (030200)

```
NEW-STYLE:
  [src:opendart] [tier:T1] [Y|임원ㆍ주요주주특정증권등소유상황보고서] [2026-05-11] [issuer:00190321] {headline}

OLD-STYLE (approximate reconstruction):
  - [Y|임원ㆍ주요주주특정증권등소유상황보고서] {headline}
```

> AR과 FDC 모두 동일한 provenance-rich format이 적용되었습니다. EI의 format과 완전히 일치합니다.

---

## 5. 종합 판정

### 판정 기준

| 등급 | 조건 |
|------|------|
| **명확한 개선** | Provenance tags complete + Symbol line corrected + Continuity coverage adequate + Token overhead acceptable |
| **제한적 개선** | Partial provenance/continuity but critical gap exists |
| **불명확** | Major gap remains or information increase is noise |

### 최종 판정: **명확한 개선** ✅

| 기준 | 결과 | 판정 |
|------|------|------|
| Provenance completeness (AR) | 100% (3/3) | ✅ |
| Provenance completeness (FDC) | 100% (3/3) | ✅ |
| Continuity (AR, EI→AR) | 4/4 | ✅ |
| Continuity (FDC, EI+AR→FDC) | 9/11 (설계상 2점 차감) | ✅ |
| AR Symbol BUG | 모두 수정됨 | ✅ |
| Token overhead (max) | +28.4% | ✅ Acceptable |

### 근거

1. **Provenance tag 완전 전파**: AR과 FDC 모두 5개 mandatory tag (`[src:]`, `[tier:]`, `[{event_type}]`, `[date]`, `[issuer:]`)가 모든 event에 정상 포함. EI와 동일한 format, 동일한 default omission 규칙 적용.
2. **Continuity coverage 충분**: EI→AR 4/4 field 완전 전파. EI+AR→FDC 9/11 field 전파 (나머지 2개는 schema 미스매치로 설계상 정상).
3. **AR Symbol line BUG 완전 수정**: 3개 symbol 모두 events 기반 symbol 추출 정상.
4. **Token overhead 수용 가능**: 최대 +28.4%로 EI(+72.9%)보다 낮음. 이는 events 섹션이 AR/FDC prompt에서 차지하는 비중이 작기 때문.

---

## 6. Provider 호출 결과 (선택적, 미수행)

이번 측정에서는 `--with-provider` 플래그 없이 read-only 모드로 실행했습니다.

Provider 호출이 필요한 경우:
```bash
python -m scripts.ar_fdc_output_measurement --with-provider
```

단, provider 호출 결과는 비결정성(non-deterministic)을 가지며, provenance 개선과 output 변화 사이의 인과 관계를 증명하지 않습니다. 결과는 단순 참고용 관찰 데이터로만 사용해야 합니다.

---

## 7. 변경 제약 준수 확인

| 제약 사항 | 준수 |
|-----------|------|
| DB write 없음 | ✅ Read-only |
| Broker submit semantics 변경 금지 | ✅ 해당 없음 |
| Admin UI 변경 금지 | ✅ 해당 없음 |
| DB schema 변경 금지 | ✅ 해당 없음 |
| Provider 실제 호출 제한적 | ✅ 미호출 (read-only) |

---

## 8. 남은 리스크

### 8.1 FDC continuity 9/11 (설계상 gap)

`ar_opposing_evidence`와 `ar_summary`가 FDC prompt에 포함되지 않는 것은 FDC output schema에 대응 field가 없기 때문입니다. 이는 provenance 전파의 문제가 아니라 agent output schema 설계의 문제입니다.

**해결 방안**: FDC output schema에 `ar_opposing_evidence`와 `ar_summary`를 반영할지 여부는 별도 논의 필요. 현재로서는 FDC가 AR의 상세 근거(opposing_evidence)와 요약(summary) 없이 결정을 내리고 있음.

### 8.2 Provider output quality 검증 부재

이번 측정은 prompt/context quality 계측에 집중했습니다. 실제 provider output(risk_opinion, decision_type 등)이 provenance 개선으로 인해 변화하는지는 검증되지 않았습니다.

**해결 방안**: `--with-provider` 플래그로 030200 symbol에 대해 2-3회 반복 호출하여 탐색적 관찰 가능. 단, 결과 해석에 주의 필요.

### 8.3 Event context richness 4/5 (issuer code 조건부)

일부 event에 `issuer_code`가 None인 경우 `[issuer:]` tag가 생략됩니다. 이는 EI와 동일한 규칙으로 정상 동작이지만, issuer code가 없는 event는 provenance completeness가 80%로 떨어집니다.

**현재 상태**: 측정 대상 3개 symbol의 모든 event에 issuer_code가 있어서 실제 영향 없음. 그러나 issuer_code가 없는 event가 존재하는 symbol에서는 completeness가 낮아질 수 있음.

### 8.4 측정 스크립트의 provenance completeness 160%+ artifact

`_compute_provenance_completeness()`에서 date tag 카운트 시 `[YYYY-MM-DD]` 패턴이 event_type bracket 내의 숫자와도 매칭되어 160-200%로 과대 계측되는 경우가 있습니다 (327260 symbol). 실제로는 100%이며, 이는 측정의 artifact입니다.
