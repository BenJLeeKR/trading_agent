# 버그 수정 보고서: `_split_phase()`가 tuple 대신 `None` 반환

## 1. 직접 원인 (Root Cause)

[`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py:290)의 `_split_phase()` 함수는 **함수 시그니처와 docstring만 존재하고 본문(body)이 완전히 누락**된 상태였다.

```python
# BEFORE (버그 발생 코드)
def _split_phase(phase: str) -> tuple[str, str | None]:
    """Split a compound phase key into (phase, detail)."""
    # ← 본문 없음 → None 반환
```

Python에서 함수 본문이 없으면 암시적으로 `None`을 반환한다. 따라서 [`_split_phase(raw_phase)`](src/agent_trading/api/schemas.py:438) 호출 결과를 언패킹하려는 코드에서 `TypeError: cannot unpack non-iterable NoneType object`가 발생했다.

### 영향받은 테스트 (3개)
- `tests/api/test_inspection.py::TestTradeDecisionPhaseTrace::test_phase_trace_derived_fields`
- `tests/api/test_inspection.py::TestTradeDecisionPhaseTrace::test_phase_trace_derived_fields_single_phase`
- `tests/api/test_inspection.py::TestTradeDecisionPhaseTrace::test_phase_trace_derived_fields_no_detail`

### 발생 맥락
Phase 4(`execution_attempt` primary truth 승격) 리팩토링 과정에서 `_split_phase()` 함수 본문이 실수로 유실된 것으로 추정됨.

---

## 2. 적용한 수정 (Fix)

### 수정 내용
[`_split_phase()`](src/agent_trading/api/schemas.py:290) 함수에 다음 변경사항 적용:

1. **파라미터 타입**: `phase: str` → `phase: str | None` (None 입력 허용)
2. **반환 타입**: `tuple[str, str | None]` → `tuple[str | None, str | None]` (phase도 None 가능)
3. **함수 본문 구현**: 항상 tuple을 반환하도록 3가지 케이스 처리
4. **주석**: 한국어 docstring으로 변경

```python
# AFTER (수정된 코드)
def _split_phase(phase: str | None) -> tuple[str | None, str | None]:
    """복합 phase 문자열(예: "broker_submit/AAPL")을 (phase, detail)로 분할합니다.

    Returns:
        (phase, detail) 튜플. "/" 구분자가 없으면 detail은 None.
        입력이 None이거나 빈 문자열이면 (None, None) 반환.
    """
    if not phase:
        return (None, None)
    if "/" in phase:
        parts = phase.split("/", 1)
        return (parts[0], parts[1])
    return (phase, None)
```

### 계약 보장
| 입력 | 반환값 |
|------|--------|
| `None` | `(None, None)` |
| `""` (빈 문자열) | `(None, None)` |
| `"broker_submit"` | `("broker_submit", None)` |
| `"broker_submit/AAPL"` | `("broker_submit", "AAPL")` |
| `"phase/detail/extra"` | `("phase", "detail/extra")` |

---

## 3. 수정한 파일 목록

| 파일 | 변경 |
|------|------|
| [`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py:290) | `_split_phase()` 함수 본문 추가 및 시그니처/반환타입 수정 |

---

## 4. 테스트 결과

### Before (수정 전) — 3개 실패
```
tests/api/test_inspection.py::TestTradeDecisionPhaseTrace::test_phase_trace_derived_fields FAILED
tests/api/test_inspection.py::TestTradeDecisionPhaseTrace::test_phase_trace_derived_fields_single_phase FAILED
tests/api/test_inspection.py::TestTradeDecisionPhaseTrace::test_phase_trace_derived_fields_no_detail FAILED
```

### After (수정 후) — 59개 전부 통과
```
tests/api/test_inspection.py::TestTradeDecisionPhaseTrace::test_phase_trace_fields_in_response        PASSED
tests/api/test_inspection.py::TestTradeDecisionPhaseTrace::test_phase_trace_derived_fields            PASSED
tests/api/test_inspection.py::TestTradeDecisionPhaseTrace::test_phase_trace_derived_fields_single_phase PASSED
tests/api/test_inspection.py::TestTradeDecisionPhaseTrace::test_phase_trace_derived_fields_no_detail  PASSED
tests/api/test_inspection.py::TestTradeDecisionPhaseTrace::test_phase_trace_null_handling             PASSED
tests/api/test_inspection.py::TestTradeDecisionPhaseTrace::test_phase_trace_empty_list_handling       PASSED
... (총 59 passed, 0 failed, 0.04s ~ 1.06s)
```

---

## 5. 최종 완료 판정

| 항목 | 상태 |
|------|------|
| ✅ `_split_phase()` 함수 본문 복원 및 계약 안정화 | 완료 |
| ✅ 항상 `tuple[str \| None, str \| None]` 반환 (None 반환 제거) | 완료 |
| ✅ `test_inspection.py::TestTradeDecisionPhaseTrace` 6개 통과 | 완료 |
| ✅ `test_inspection.py` 전체 59개 테스트 통과 | 완료 |
| ✅ `docker compose build api` + 재기동 | 완료 |
| ✅ Docker health check 통과 (HTTP 200) | 완료 |
| ✅ 본 보고서 생성 | 완료 |

**결론**: 근본 원인이 파악되었고, 최소 침습적 수정으로 모든 테스트가 통과하였으며 Docker 서비스도 정상 동작함. 추가 조치 불필요.
