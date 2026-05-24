# EI Provider Error Failure Metadata — 구현 보고서

**날짜:** 2026-05-24  
**관련 설계:** [`persist_and_expose_event_interpretation_provider_error_metadata_for_root_cause_analysis_2026-05-24.md`](plans/persist_and_expose_event_interpretation_provider_error_metadata_for_root_cause_analysis_2026-05-24.md)  
**변경 범위:** `event_interpretation.py`, `decision_orchestrator.py`, `test_agents.py`

---

## 1. 문제

Event Interpretation Agent 실패 시 `degraded_reason="provider_error"` 또는 `degraded_reason="timeout"`만 로깅되었고, **구체적인 예외 원인**(timeout / HTTP 4xx/5xx / rate limit / JSON decode / schema parse)은 추적 불가능했다. 운영자가 장애 원인을 파악하려면 raw 로그를 뒤져야 했고, API를 통해 실패 원인을 확인할 방법이 없었다.

## 2. 해결 방안

기존 `agent_runs.structured_output_json` (JSONB, NOT NULL) 컬럼을 활용하여 DB 마이그레이션 없이 실패 메타데이터를 저장한다. 실패 시 `structured_output` 딕셔너리에 `__error__` 키를 추가한다. 성공 경로에서는 `__error__`가 절대 포함되지 않는다.

### 2.1 저장 구조

```json
{
  "__error__": {
    "error_type": "timeout | http_error | parse_failure | provider_error | unknown",
    "error_message": "Connection timed out",
    "http_status": 429 | null,
    "retryable": true | false | null,
    "timeout_source": "orchestrator" | "provider_client" | null
  }
}
```

| `error_type` | 조건 | `retryable` | `timeout_source` |
|---|---|---|---|
| `timeout` | `httpx.TimeoutException` | `true` | `"provider_client"` |
| `timeout` | `asyncio.TimeoutError` (orchestrator) | `true` | `"orchestrator"` |
| `http_error` | `httpx.HTTPStatusError` | 429/5xx=`true`, 4xx(≠429)=`false` | `null` |
| `parse_failure` | `json.JSONDecodeError`, `TypeError`, `ValueError` | `false` | `null` |
| `provider_error` | 기타 모든 `Exception` | `null` | `null` |

## 3. 변경 파일

### 3.1 `src/agent_trading/services/ai_agents/event_interpretation.py`

**함수 추가: `_classify_exception()`** (lines 301-375)

`sys.exc_info()`로 현재 예외 컨텍스트를 읽어 6가지 분기로 분류:
1. 예외 정보 없음 → `error_type: "unknown"`
2. `httpx.TimeoutException` → `error_type: "timeout"`, `timeout_source: "provider_client"`
3. `httpx.HTTPStatusError` → `error_type: "http_error"`, `http_status`, `retryable` 계산
4. `json.JSONDecodeError` → `error_type: "parse_failure"`
5. `TypeError`/`ValueError` → `error_type: "parse_failure"`
6. 기타 `Exception` → `error_type: "provider_error"`

**필드 추가: `_last_error_metadata`** (line 479)

`EventInterpretationAgent.__init__()`에 `dict[str, object] | None` 타입의 인스턴스 변수 추가. lifecycle contract를 docstring으로 명시:
- `run()` 시작 시 `None`으로 리셋
- `except` 블록에서만 설정
- 호출자는 동일 async task 내에서 즉시 읽어야 함
- 성공 경로에서는 `None` 보장

**프로퍼티 추가: `last_error_metadata`** (lines 489-505)

읽기 전용 property. contract docstring에 호출 규약을 명확히 문서화.

**run() 메서드 변경:**
- 시작 부분 (line 533): `self._last_error_metadata = None` — 이전 호출의 메타데이터 초기화
- `except Exception` 블록 (line 664): `self._last_error_metadata = _classify_exception()` — 실패 원인 저장

### 3.2 `src/agent_trading/services/decision_orchestrator.py`

**`_run_agents()` 메서드 — EI 블록 (lines 1298-1379)**

3가지 경로 각각에서 `ei_error_metadata` 변수 구성:

| 경로 | `ei_error_metadata` 출처 |
|---|---|
| **성공** (line 1315) | `self._event_interpretation_agent.last_error_metadata` — agent 내부에서 fallback한 경우 분류된 메타데이터, 정상 성공 시 `None` |
| **asyncio.TimeoutError** (lines 1335-1340) | orchestrator 레벨 timeout: `error_type="timeout"`, `timeout_source="orchestrator"`, `retryable=True` |
| **Exception** (lines 1359-1365) | orchestrator 레벨 예외: `error_type="provider_error"`, `retryable=None` |

**`__error__` 주입** (lines 1371-1373):
```python
ei_structured_output: dict[str, object] = _dataclass_to_dict(event_output)
if ei_error_metadata is not None:
    ei_structured_output["__error__"] = ei_error_metadata
```

**record() 호출** (lines 1375-1379): `structured_output=ei_structured_output`로 전달.

### 3.3 `tests/services/ai_agents/test_agents.py`

**5개의 신규 테스트 추가** (`TestEventInterpretationAgent` 클래스):

| 테스트 | 시나리오 | 검증 |
|---|---|---|
| `test_run_fallback_stores_error_metadata_on_provider_error` | `RuntimeError` | `error_type="provider_error"`, `retryable=None` |
| `test_run_fallback_stores_error_metadata_on_parse_failure` | `ValueError` | `error_type="parse_failure"`, `retryable=False` |
| `test_run_fallback_stores_error_metadata_on_timeout` | `httpx.TimeoutException` | `error_type="timeout"`, `timeout_source="provider_client"` |
| `test_run_fallback_stores_error_metadata_on_http_error_429` | `httpx.HTTPStatusError(429)` | `error_type="http_error"`, `http_status=429`, `retryable=True` |
| `test_run_success_path_no_error_metadata` | 정상 응답 | `last_error_metadata is None` (성공 경로 오염 금지) |

## 4. 변경 불필요 파일

| 파일 | 이유 |
|---|---|
| `provider_client.py` | 예외 throw는 그대로 유지 — `event_interpretation.py`의 `except` 블록에서 분류 |
| `recorder.py` | `structured_output`에 `__error__` 키 포함 가능 — 시그니처 변경 불필요 |
| `schemas.py` | `EventInterpretationOutput`은 fallback path에서만 `__error__` 주입 — dataclass 변경 불필요 |
| `entities.py` | `AgentRunEntity.structured_output_json` (JSONB)은 이미 dict 수용 |
| `api/schemas.py` | `AgentRunResponse.structured_output_json`은 자동 노출 |
| `api/routes/agent_runs.py` | 변경 불필요 |
| `repositories/postgres/agent_runs.py` | JSONB 컬럼은 dict를 native JSON으로 직렬화 |
| `decision_orchestrator.py`의 subprocess 경로 | subprocess 실패 시 `_build_fallback_bundle()`이 record() 이전에 early return |

## 5. `_last_error_metadata` 계약

```
run() 시작 ──→ _last_error_metadata = None (리셋)
      │
      ├── 성공 ──→ _last_error_metadata 유지 (None)
      │
      └── 예외 ──→ _classify_exception() → _last_error_metadata 설정
                        │
                        └── caller가 즉시 last_error_metadata 읽음
                              (동일 async task, 동기 컨텍스트)
```

- **reset rule**: `run()` 시작 시 `self._last_error_metadata = None`
- **set rule**: `except Exception` 블록에서만 `self._last_error_metadata = _classify_exception()`
- **read rule**: 호출자는 동일 async task 내에서 **즉시** 읽어야 함 (다른 `run()` 호출 전)
- **success guarantee**: 성공 경로에서는 `None`이 보장됨 → `structured_output_json["__error__"]` 미포함
- **thread safety**: 단일 스레드 async 컨텍스트만 가정 (thread-safe 아님)

## 6. 검증 결과

- **pytest**: `tests/services/ai_agents/test_agents.py` + `test_event_interpretation.py` — **142 passed**
- **pytest (전체)**: `tests/services/ai_agents/` — 215 passed, **1 pre-existing failure** (unrelated FDC prompt test)
- **Docker build**: `app`, `api` 이미지 rebuild 성공
- **Docker restart**: `app`, `api` 컨테이너 정상 기동
- **/health**: `{"status":"ok","database":"connected","runtime_mode":"postgres"}`

## 7. 운영 확인 사항

- **실패 시 API 응답**: `GET /agent-runs/{id}` → `structured_output_json`에 `__error__` 키 포함
  ```json
  {
    "structured_output_json": {
      "symbol": "AAPL",
      "__error__": {
        "error_type": "http_error",
        "error_message": "429 Rate limit exceeded",
        "http_status": 429,
        "retryable": true,
        "timeout_source": null
      }
    }
  }
  ```
- **성공 시**: `__error__` 키 없음 (기존 응답과 동일)
- **DB 쿼리 예시**:
  ```sql
  SELECT agent_run_id, structured_output_json->'__error__' AS error_metadata
  FROM agent_runs
  WHERE structured_output_json ? '__error__'
  ORDER BY created_at DESC;
  ```
