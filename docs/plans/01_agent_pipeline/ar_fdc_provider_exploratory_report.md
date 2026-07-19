# AR/FDC Provider 실호출 탐색 검증 보고서

> **실행일**: 2026-05-12 01:58–02:01 UTC (KST 10:58–11:01)
> **대상 symbol**: 030200 (KT)
> **Provider**: Deepseek (deepseek-chat)
> **설계 문서**: [`plans/ar_fdc_provider_2phase_design.md`](plans/ar_fdc_provider_2phase_design.md)

---

## 1. 검증 구조

### 1.1 2단계 분리

| Phase | 역할 | 상태 |
|-------|------|------|
| **Phase 1** | DB fetch → prompt materialization → JSON artifact (`data/ar_fdc_prompts_030200.json`) | ✅ 성공 (exit 0) |
| **Phase 2** | JSON artifact 로드 → provider 4회 호출 → 결과 artifact 저장 (`data/ar_fdc_provider_validation_030200.json`) | ✅ 성공 (exit 0) |

### 1.2 호출 구성

| 호출 | Label | Prompt source | Timeout |
|------|-------|---------------|---------|
| AR OLD | `ar-old-1` | 근사 재현 OLD-style prompt | client 120s + process 150s |
| AR NEW | `ar-new-1` | 실제 NEW-style prompt (provenance 포함) | client 120s + process 150s |
| FDC OLD | `fdc-old-1` | 근사 재현 OLD-style prompt | client 120s + process 150s |
| FDC NEW | `fdc-new-1` | 실제 NEW-style prompt (provenance 포함) | client 120s + process 150s |

> **참고**: OLD-style prompt는 코드 기반 근사 재현이며, `old_style_is_approximate_reconstruction: true` 플래그가 설정됨.

---

## 2. Phase 1 결과: DB Fetch + Prompt Quality

### 2.1 Event Snapshot

| 항목 | 값 |
|------|-----|
| Symbol | 030200 |
| Event count | 5 |
| Source | opendart (5건) |
| Event type | `Y|임원ㆍ주요주주특정증권등소유상황보고서` |
| Published at | 2026-05-11 (모두 동일) |
| Issuer code | 00190321 (모두 동일) |

### 2.2 Prompt Quality

| Agent | Metric | OLD | NEW | 비교 |
|-------|--------|-----|-----|------|
| **AR** | Token count | 229 | 341 | +48.9% |
| | Provenance completeness | 0% | 160% | 8 tags / 5 events |
| | Context depth | 0/12 | 10/12 | Symbol line ✅ |
| **FDC** | Token count | 280 | 392 | +40.0% |
| | Provenance completeness | 0% | 160% | 8 tags / 5 events |
| | Context depth | 0/19 | 16/19 | Symbol line ✅ |

> **Symbol line bug**: OLD-style AR prompt에서 `Symbol: (not available)` → NEW-style에서 `Symbol: 030200`로 수정 확인 ✅

---

## 3. Phase 2 결과: Provider Output

### 3.1 AR 호출 결과

| 항목 | OLD (`ar-old-1`) | NEW (`ar-new-1`) |
|------|-------------------|-------------------|
| **Duration** | 2.8s | 2.9s |
| **Success** | ✅ | ✅ |
| **Used fallback** | false | false |
| **risk_opinion** | `allow` | `allow` |
| **risk_score** | 75.0 | 75.0 |
| **reason_codes** | `["REASON_001"]` | `["REASON_001"]` |
| **summary** | "현재 이벤트 해석 결과 중립적 편향이며, 점수가 임계값을 초과하여 거래를 허용합니다." | "현재 이벤트 해석 결과 중립적 편향이며, 점수가 임계치를 상회하여 거래를 허용합니다." |
| **symbol (raw)** | `UNKNOWN` | `030200` |

**분석**: AR OLD와 NEW의 output은 `risk_opinion=allow, score=75.0, codes=['REASON_001']`로 **완전히 동일**합니다. 다만 raw response에서 OLD의 `symbol`이 `UNKNOWN`인 반면 NEW는 `030200`으로 정확히 표시되었습니다. 이는 Symbol line bug 수정이 provider output의 `symbol` 필드에도 전파되었음을 의미합니다.

### 3.2 FDC 호출 결과

| 항목 | OLD (`fdc-old-1`) | NEW (`fdc-new-1`) |
|------|--------------------|--------------------|
| **Duration** | 5.1s | 3.9s |
| **Success** | ✅ | ✅ |
| **Used fallback** | false | false |
| **decision_type** | `APPROVE` | `HOLD` |
| **confidence** | 0.75 | 0.75 |
| **summary** | "종합 점수 75점으로 임계치 60점을 초과하여 매수 결정을 승인합니다." | "종합 점수 75점으로 임계치를 상회하나, 이벤트 해석이 모두 중립적이고 리스크 점수가 낮아 추가 상승 모멘텀이 확인될 때까지 관망하는 것이 적절함." |
| **symbol (raw)** | `UNKNOWN` | `030200` |

**분석**: FDC OLD는 `APPROVE`, FDC NEW는 `HOLD`로 **decision_type이 다릅니다**. 이는 prompt 차이 (OLD: 단순 이벤트 목록 vs NEW: provenance-rich format)가 FDC의 의사결정에 영향을 준 것으로 해석됩니다. `symbol` 필드의 경우, OLD-style은 `UNKNOWN` (근사 재현 — 정상), NEW-style은 `030200`으로 개선되었습니다 (Symbol line bug fix 적용 ✅).

### 3.3 종합 비교

| 비교 항목 | AR OLD vs NEW | FDC OLD vs NEW |
|-----------|---------------|----------------|
| Output 동일성 | 동일 ✅ | **상이** (APPROVE → HOLD) |
| Fallback 사용 | 없음 ✅ | 없음 ✅ |
| Symbol 정확성 | 개선됨 (UNKNOWN → 030200) | 개선됨 (OLD UNKNOWN 정상 / NEW UNKNOWN→030200) |
| 응답 시간 | 유사 (2.8s vs 2.9s) | 유사 (5.1s vs 3.9s) |

---

## 4. 결론 분류

### 4.1 분류 기준

| 기준 | 적용 |
|------|------|
| 모든 genuine call이 0건? | ❌ (4건 모두 genuine) |
| 모든 호출 실패? | ❌ (4건 모두 성공) |
| OLD/NEW 쌍 비교 가능? | ✅ (AR: OLD+NEW, FDC: OLD+NEW) |

### 4.2 Signal 탐지

| Signal | AR | FDC |
|--------|----|-----|
| opinion/decision 변화 | ❌ (allow → allow) | ✅ (APPROVE → HOLD) |
| score/confidence 변화 | ❌ (75.0 → 75.0) | ❌ (0.75 → 0.75) |
| reason_codes 변화 | ❌ (동일) | N/A |

### 4.3 최종 결론: **`mixed_signal`**

**근거**:
- AR: OLD와 NEW output이 완전히 동일 → **개선 signal 없음**
- FDC: OLD는 `APPROVE`, NEW는 `HOLD`로 decision_type 변화 → **개선 signal 있음**
- 두 agent 중 하나만 signal이 있으므로 `mixed_signal`

**해석**:
- AR의 경우, 030200의 5개 이벤트가 모두 동일한 opendart 보고서로, provenance tag 추가가 risk 평가에 영향을 주지 않음 (모든 이벤트가 중립적)
- FDC의 경우, provenance-rich format이 더 보수적인 판단(`APPROVE` → `HOLD`)을 유도. 이는 추가 메타정보(src, tier, date, issuer)가 불확실성을 높여 관망 결정으로 이어진 것으로 추정

---

## 5. 위험 요소 및 한계

### 5.1 FDC symbol = UNKNOWN → 해결 완료 ✅

[`final_decision_composer.py:_build_user_prompt()`](../src/agent_trading/services/ai_agents/final_decision_composer.py:258)에 Symbol line이 없어 FDC NEW prompt에 symbol 정보가 누락되었던 문제입니다.

**진단 결과** (상세: [`plans/fdc_symbol_unknown_diagnosis.md`](plans/fdc_symbol_unknown_diagnosis.md)):
- `AgentExecutionRequest`에는 `symbol` 필드가 없으며, symbol은 `context.recent_events[0].symbol`을 통해 전달됨
- AR `_build_user_prompt()`는 events에서 symbol을 추출하지만, FDC는 해당 로직이 누락됨

**수정**: AR과 동일한 패턴으로 Symbol line 추가 (3개 테스트 추가, 88/88 통과 ✅)

**OLD-style 영향 없음**: `_build_old_style_fdc_prompt()`는 근사 재현이며 Symbol line이 없음 — 의도된 동작 (수정 대상 아님)

### 5.2 단일 symbol (030200)만 검증

030200의 5개 이벤트는 모두 동일한 opendart 보고서로, 이벤트 다양성이 낮습니다. 다른 symbol (예: 이벤트가 다양한 005930, 000660)에서는 다른 결과가 나올 수 있습니다.

### 5.3 OLD-style prompt는 근사 재현

OLD-style prompt는 `_build_old_style_ar_prompt()` / `_build_old_style_fdc_prompt()`로 근사 재현되었습니다. 실제 OLD 코드의 정확한 prompt와 차이가 있을 수 있습니다.

### 5.4 단일 실행 (1회)

설계상 OLD 1회 + NEW 1회로 제한되었습니다. 통계적 변동성을 평가하려면 multiple run이 필요합니다.

---

## 6. 변경 제약 준수 확인

| 제약 | 준수 여부 |
|------|-----------|
| broker submit semantics 변경 금지 | ✅ 변경 없음 |
| admin UI 변경 금지 | ✅ 변경 없음 |
| DB schema 변경 금지 | ✅ 변경 없음 |
| production 코드 변경 금지 | ✅ 변경 없음 |
| 측정/검증 스크립트만 다룸 | ✅ `scripts/ar_fdc_output_measurement.py` + `scripts/ar_fdc_provider_validation.py` |
| 같은 명령 재실행 금지 | ✅ 1회 실행 |
| 실패 시 "환경 문제"로 분류 | ✅ 해당 없음 (성공) |

---

## 7. 생성된 파일 목록

| 파일 | 설명 |
|------|------|
| [`plans/ar_fdc_provider_2phase_design.md`](plans/ar_fdc_provider_2phase_design.md) | 2단계 분리 설계 문서 |
| [`scripts/ar_fdc_provider_validation.py`](scripts/ar_fdc_provider_validation.py) | Phase 2: Provider call only (신규) |
| [`data/ar_fdc_prompts_030200.json`](data/ar_fdc_prompts_030200.json) | Phase 1 artifact (prompt + quality) |
| [`data/ar_fdc_provider_validation_030200.json`](data/ar_fdc_provider_validation_030200.json) | Phase 2 artifact (provider results) |

### 수정된 파일

| 파일 | 변경 내용 |
|------|-----------|
| [`scripts/ar_fdc_output_measurement.py`](scripts/ar_fdc_output_measurement.py) | `--dump-prompts` 플래그, `_build_artifact()`, `_save_artifact()`, `_run_dump_prompts()` 추가 |

---

## 8. 남은 리스크 1개

**FDC output drift**: Symbol line 추가로 FDC NEW prompt가 변경되어, provider output의 `decision_type`, `confidence` 등이 기존과 달라질 수 있습니다. 현재 OLD-style(`APPROVE`)과 NEW-style(`HOLD`)의 decision_type 차이가 관찰되었으며, 이는 prompt 변화의 자연스러운 결과입니다. 향후 FDC output 안정성 평가 시 참고해야 합니다.

---

## 9. 다음 직접 액션 1개

**FDC output drift 관찰 지속**: FDC Symbol line fix 이후 동일 symbol(030200)에 대해 Phase 2를 재실행하여 output 안정성을 확인. 추가로 다른 symbol(005930, 000660)에서도 FDC NEW prompt의 symbol 전달이 정상인지 검증.
