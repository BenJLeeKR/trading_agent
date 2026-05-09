# Korean Enforcement 후속 정리 — `risk_opinion` 정규화로 깨진 2개 테스트

## Root Cause

`mock_ar_provider` fixture에서 생성된 `AIRiskOutput`은 다음 narrative 필드를 포함합니다:

| 필드 | 원본 값 | 정규화 후 |
|------|---------|-----------|
| `risk_opinion` | `"reduce"` | `"[ko: reduce]"` |
| `summary` | `"Reduce position due to concentration risk"` | `"[ko: Reduce position due to concentration risk]"` |

`AgentRunRecorder.record()` → `normalize_structured_output()`이 `risk_opinion`을 `_NARRATIVE_KEYS`로 인식하여 `[ko: ...]` 래핑합니다.

2개 테스트가 원본 영어값 `"reduce"`를 기대하지만, 실제 저장값은 `"[ko: reduce]"`입니다.

## 해결 방안

**테스트 기대값 수정 (normalizer 변경 없음)**

`[ko: ...]` 포맷은 의도된 설계입니다:
- `korean_normalizer.py` docstring: "Non-Korean text is wrapped with a `[ko: ...]` marker"
- `recorder.py` 주석 (lines 96-100): 동일한 설명
- 이는 "이 필드는 한국어로 작성되어야 함"을 나타내는 디버깅 마커

정규화 로직 자체를 바꾸는 것은 LLM 기반 번역 메커니즘이 필요하므로 현재 범위를 벗어납니다.

## 변경 파일

### 1. `tests/services/ai_agents/test_orchestrator_agents.py`

2곳의 assertion을 수정:

```
# Line 553 (test_real_ei_and_real_ar_with_stub_fdc)
assert ar_run.structured_output_json.get("risk_opinion") == "reduce"
→
assert ar_run.structured_output_json.get("risk_opinion") == "[ko: reduce]"

# Line 691 (test_real_ei_real_ar_real_fdc)
assert ar_run.structured_output_json.get("risk_opinion") == "reduce"
→
assert ar_run.structured_output_json.get("risk_opinion") == "[ko: reduce]"
```

### 2. `plans/BACKLOG.md`

Gap 2 완료 기록에서 "Pre-existing 2건(Gap 4 Korean AR mock) 제외" 문구 제거. 더 이상 pre-existing failure가 없음을 반영.

## 테스트 검증

- 2개 테스트 개별 실행 통과 확인
- 전체 `test_orchestrator_agents.py` 묶음 통과 확인 (71/71 → 73/73)
- Korean enforcement 테스트 묶음 회귀 확인

## 영향 범위

- `korean_normalizer.py`: 변경 없음 (정책 유지)
- `recorder.py`: 변경 없음
- `decision_orchestrator.py`: 변경 없음
- 기타 테스트: 영향 없음 (다른 테스트들은 `risk_opinion`을 assertion하지 않음)
