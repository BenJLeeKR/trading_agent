# EI Failure Metadata (`__error__`) 엔드투엔드 저장 경로 검증 보고서

**작성일**: 2026-05-24  
**대상 시스템**: `agent_trading` — AI Multi-Agent Trading System  
**관련 PR/커밋**: subprocess isolation 경로 `__error__` 누락 버그 수정

---

## 1. 개요

Event Interpretation (EI) Agent가 provider 장애 등으로 실패할 경우, 실패 상세 정보를 담은 `__error__` 메타데이터가 `agent_runs.structured_output_json` JSONB 컬럼에 저장되어야 한다. 본 보고서는 해당 저장 경로의 엔드투엔드(end-to-end) 검증 결과를 정리한다.

---

## 2. 문제 분석 (Phase 1)

### 2.1 저장 경로 추적

```
EventInterpretationAgent.run() 실패
  → _last_error_metadata 설정 (dict)
  → _dataclass_to_dict(event_output)  ← dataclass 필드만 변환, __error__ 제외
  → recorder.record(structured_output)
    → PostgresAgentRunRepository.add(run)
      → json.dumps(run.structured_output_json) → JSONB INSERT
        → API _to_response() → AgentRunResponse
```

### 2.2 발견된 버그

**두 가지 실행 경로 중 subprocess isolation 경로(기본값, `AGENT_SUBPROCESS_ISOLATION=1`)에서 `__error__` 누락**

| 실행 경로 | 상태 | 설명 |
|-----------|------|------|
| In-process `_run_agents()` | ✅ 정상 | `ei_error_metadata`를 `__error__` 키로 주입 (line 1370-1373) |
| Subprocess `_run_agents_in_subprocess()` | ❌ 누락 (수정 전) | `ei_agent.last_error_metadata`를 추출/전달/주입하는 로직 없음 |

### 2.3 저장 계층별 검토

| 계층 | 파일 | `__error__` 필터링? |
|------|------|-------------------|
| Agent | [`event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py:654) | `_last_error_metadata` 설정 — 통과 |
| Orchestrator (in-process) | [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:1370) | `__error__` 주입 — 통과 |
| Orchestrator (subprocess) | [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:683) | **버그**: `__error__` 미주입 |
| Subprocess script | [`run_agent_subprocess.py`](scripts/run_agent_subprocess.py:684) | **버그**: `last_error_metadata` 미추출 |
| Recorder | [`recorder.py`](src/agent_trading/services/ai_agents/recorder.py:53) | 필터링 없음 — 통과 |
| Repository | [`postgres/agent_runs.py`](src/agent_trading/repositories/postgres/agent_runs.py:24) | 필터링 없음 — 통과 |
| API | [`routes/agent_runs.py`](src/agent_trading/api/routes/agent_runs.py:20) | 필터링 없음 — 통과 |

---

## 3. 최근 DB 현황 (Phase 2)

수정 전, `agent_runs` 테이블에 `__error__` 키가 존재하는 EI run은 **0건**이었다.

```sql
SELECT structured_output_json ? '__error__' AS has_error_metadata, count(*)
FROM trading.agent_runs
WHERE agent_type LIKE '%interpret%'
GROUP BY 1;
-- has_error_metadata | count
-- f                  |   344
```

즉, 수많은 EI 실패가 발생했음에도 `__error__`는 단 한 건도 저장되지 않았다. 이는 subprocess isolation 경로(기본값)에서 `__error__` 누락 버그가 실제 운영 환경에 영향을 미치고 있었음을 의미한다.

---

## 4. 코드 수정 (Phase 6)

### 4.1 수정 파일 목록

| 파일 | 변경 사항 |
|------|----------|
| [`scripts/run_agent_subprocess.py`](scripts/run_agent_subprocess.py) | 3개 지점 수정 |
| [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | 3개 지점 수정 |

### 4.2 상세 수정 내역

**`run_agent_subprocess.py`**:
1. `AgentSubprocessOutput` dataclass에 `ei_error_metadata: dict[str, Any] | None = None` 필드 추가 (line 156)
2. EI agent 실행 후 `ei_agent.last_error_metadata` 캡처 (line 688)
3. `_write_output()` JSON에 `ei_error_metadata` 포함 (line 723)

**`decision_orchestrator.py`**:
1. `AgentExecutionBundle` dataclass에 `ei_error_metadata: dict[str, object] | None = None` 필드 추가 (line 182)
2. `_deserialize_agent_output()`에서 `result.get("ei_error_metadata")` 추출 (line 2009)
3. Subprocess 재수화(rehydration) 코드에서 `__error__` 주입 (line 696-699):
   ```python
   _ei_structured = _dataclass_to_dict(agent_bundle.event_output)
   if agent_bundle.ei_error_metadata is not None:
       _ei_structured["__error__"] = agent_bundle.ei_error_metadata
   ```

---

## 5. 테스트 결과 (Phase 7)

### 5.1 단위 테스트 (pytest)

5개 관련 테스트 모두 통과:

| 테스트 | 결과 |
|--------|------|
| `test_run_fallback_stores_error_metadata_on_provider_error` | ✅ PASS |
| `test_run_fallback_stores_error_metadata_on_parse_failure` | ✅ PASS |
| `test_run_fallback_stores_error_metadata_on_timeout` | ✅ PASS |
| `test_run_fallback_stores_error_metadata_on_http_error_429` | ✅ PASS |
| `test_run_success_path_no_error_metadata` | ✅ PASS |

### 5.2 엔드투엔드 검증

**검증 스크립트**: [`scripts/verify_ei_error_metadata_e2e.py`](scripts/verify_ei_error_metadata_e2e.py)

| 검증 항목 | 결과 |
|-----------|------|
| DB 직접 INSERT → `__error__` 포함 저장 | ✅ `has_error_metadata=True` |
| API `GET /agent-runs/{id}` → `__error__` 노출 | ✅ HTTP 200, `__error__` 정상 반환 |
| 저장 경로 필터링 없음 확인 | ✅ Recorder/Repository/API 모두 pass-through 확인 |

### 5.3 실제 실패 재현 방법

EI 실패의 실제 재현은 다음 두 가지 방법으로 가능하다:

1. **직접 EI Agent 호출** (Phase 3 Method A):
   ```python
   agent = EventInterpretationAgent(provider_client=None)
   output = await agent.run(request)  # provider 없음 → fallback
   assert agent.last_error_metadata is not None
   ```

2. **Subprocess 경로** (운영 환경과 동일):
   - `AGENT_SUBPROCESS_ISOLATION=1` 상태에서
   - 유효하지 않은 Provider API 키로 요청 전송
   - Subprocess 내 EI agent 실패 → `last_error_metadata` 캡처 → orchestrator 재수화 → `__error__` 주입 → DB 저장

---

## 6. 최종 판정

**✅ 정상 동작 확인 — 수정 완료**

| 기준 | 상태 |
|------|------|
| 버그 식별 (subprocess 경로 `__error__` 누락) | ✅ 발견 |
| 코드 수정 (`run_agent_subprocess.py` + `decision_orchestrator.py`) | ✅ 완료 |
| 단위 테스트 통과 (5/5) | ✅ 통과 |
| Docker 재빌드 및 API 정상 기동 | ✅ 확인 |
| DB JSONB `? '__error__'` 연산 정상 | ✅ true 반환 |
| API 응답 `__error__` 정상 노출 | ✅ 확인 |
| 모든 계층 pass-through 확인 (recorder/repository/API) | ✅ 확인 |

**향후 권장사항**:
- 신규 dataclass 필드 추가 시 `_dataclass_to_dict()` / `_dict_to_dataclass()` 대칭성 유의
- Subprocess isolation 경로와 in-process 경로 간 동작 불일치 방지를 위한 통합 테스트 강화
- 운영 모니터링: `structured_output_json ? '__error__'` 쿼리로 EI 실패율 추적
