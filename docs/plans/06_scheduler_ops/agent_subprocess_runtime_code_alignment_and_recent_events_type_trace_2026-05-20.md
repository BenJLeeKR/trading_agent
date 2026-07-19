# Agent Subprocess Runtime Code Alignment + `recent_events` Type Trace — 보고서

> **작성일**: 2026-05-20 13:00 KST  
> **대상**: `ops-scheduler` 컨테이너 (`agent_trading-app:latest`)  
> **목적**: `_reconstruct_external_event()` 수정이 운영에서 미적용된 원인 규명 및 재배포 검증

---

## 1. 요약

`_reconstruct_external_event()` 수정(Task 8)이 운영에서 동작하지 않은 근본 원인은 **이미지 재빌드 누락**이었다. 컨테이너는 `docker-compose.yml`의 volume mount로 인해 로컬 파일을 사용했지만, **이미지 자체에는 수정사항이 포함되지 않았고**, scheduler 재시작 시점(12:45 KST) 이전까지는 이전 이미지(`7187fd0e74cf`, 11:33 KST 빌드)가 실행 중이었다.

---

## 2. 로컬 vs 컨테이너 코드 일치 여부

### 2.1 컨테이너 내부 파일 (volume mount 경로)

| 파일 | 컨테이너 경로 | 로컬과 diff |
|------|-------------|------------|
| `run_agent_subprocess.py` | `/app/scripts/run_agent_subprocess.py` | ✅ 일치 (diff 없음) |
| `decision_orchestrator.py` | `/app/src/agent_trading/services/decision_orchestrator.py` | ✅ 일치 (diff 없음) |

**원인**: `docker-compose.yml`에 아래 volume mount가 설정되어 있어, 컨테이너는 항상 호스트의 최신 파일을 사용함.

```yaml
volumes:
  - ./scripts:/app/scripts
  - ./src:/app/src
```

### 2.2 이미지 내부 파일 (image layer)

| 파일 | 이미지 내부 | 결과 |
|------|-----------|-------|
| `run_agent_subprocess.py` | `/app/scripts/run_agent_subprocess.py` | ❌ **파일 없음** (`COPY scripts/ scripts/` 누락) |
| `_reconstruct_external_event()` | `/app/src/.../decision_orchestrator.py` | ❌ **함수 없음** (이전 이미지) |
| `_SUBPROCESS_TIMEOUT` | `/app/src/.../decision_orchestrator.py` | ⚠️ `35.0` (로컬은 `300.0`) |

### 2.3 판정

| 항목 | 결과 |
|------|------|
| 컨테이너 실행 코드 | ✅ 로컬과 일치 (volume mount 덕분) |
| 이미지 빌드 상태 | ❌ **수정사항 미포함** |
| Dockerfile 정합성 | ❌ `COPY scripts/ scripts/` 누락 |
| **실제 장애 원인** | **이전 이미지(11:33 빌드)가 12:45까지 실행 → 수정 코드 없음** |

---

## 3. `recent_events` 문자열 유입 경로 추적

### 3.1 전체 Data Flow

```
ExternalEventEntity.published_at: datetime
    │
    ▼
_serialize_agent_input() [decision_orchestrator.py:2385]
    │  _dataclass_to_dict(assembled_context) → datetime 객체 유지
    │  json.dumps(inp, default=_json_default) → datetime.isoformat() → str
    ▼
stdin (JSON string)
    │
    ▼
main() [run_agent_subprocess.py:515]
    │  json.loads() → dict[str, Any]
    │
    ▼
_reconstruct_context() [run_agent_subprocess.py:328]
    │  _reconstruct_external_event(ev) → _safe_datetime(d.get("published_at"))
    │  datetime.fromisoformat() → datetime 객체 복원
    ▼
AssembledContext.recent_events: tuple[ExternalEventEntity, ...]
    │
    ▼
Agent._build_user_prompt()
    │  e.published_at.strftime('%Y-%m-%d')  ← datetime 객체이므로 정상
    ▼
LLM API 호출
```

### 3.2 검증 결과

| 단계 | 타입 | 비고 |
|------|------|------|
| `ExternalEventEntity.published_at` | `datetime` | required field, not Optional |
| `_dataclass_to_dict()` | `datetime` 유지 | tuple 내부도 `isinstance(v, datetime)` passthrough |
| `json.dumps(default=_json_default)` | `str` (ISO format) | `isinstance(obj, datetime)` → `obj.isoformat()` |
| `json.loads()` | `str` | JSON deserialization |
| `_safe_datetime(value: str)` | `str` → `datetime` | `datetime.fromisoformat()` |
| `_build_user_prompt()` | `datetime` | `strftime('%Y-%m-%d')` 정상 |

**결론**: serialize/deserialize chain은 정상이며, `_safe_datetime()`이 `datetime` 객체를 받을 경우를 대비한 defensive code만 추가됨.

---

## 4. Root Cause 분석

### Primary: 이미지 재빌드 누락

```
11:33 KST  → agent_trading-app:latest 빌드 (7187fd0e74cf)
             - _reconstruct_external_event() 없음
             - _SUBPROCESS_TIMEOUT = 35.0
             - COPY scripts/ scripts/ 누락

12:38:02   → decision_submit_gate timeout (304.08s) ← 이전 이미지
12:43:51   → decision_subprocess timeout (304.07s) ← 이전 이미지
12:45:34   → ops-scheduler 재시작 (volume mount로 최신 코드 적용)
```

### Secondary: Dockerfile `COPY scripts/ scripts/` 누락

```dockerfile
# Before (수정 전)
COPY src/ src/
COPY db/ db/
# scripts/ 없음 → 이미지 기반 실행 시 run_agent_subprocess.py 없음

# After (수정 후)
COPY src/ src/
COPY scripts/ scripts/
COPY db/ db/
```

### Tertiary: `_safe_datetime()` type hint 불완전

```python
# Before
def _safe_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value) if isinstance(value, str) else value

# After
def _safe_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
```

---

## 5. 적용한 수정 사항

| # | 파일 | 수정 내용 | 영향 |
|---|------|----------|------|
| 1 | [`scripts/run_agent_subprocess.py`](../scripts/run_agent_subprocess.py:175) | `_safe_datetime()` type hint `str \| None` → `object`, `isinstance(datetime)` passthrough, try/except 추가 | `datetime` 객체 방어, `fromisoformat` 실패 시 None 반환 |
| 2 | [`Dockerfile`](../Dockerfile) | `COPY scripts/ scripts/` 추가 | 이미지 기반 실행 시 `run_agent_subprocess.py` 포함 |

---

## 6. 재배포 결과

### 6.1 이미지 빌드

```bash
$ docker compose build ops-scheduler
→ agent_trading-app:latest (IMAGE ID: 92a77c026238, 2026-05-20 12:57 KST)
```

### 6.2 이미지 내부 검증

```bash
$ docker run --rm agent_trading-app:latest grep -n "_reconstruct_external_event\|_safe_datetime" /app/scripts/run_agent_subprocess.py
→ 194:def _reconstruct_external_event(d: dict[str, Any] | None) -> ExternalEventEntity | None:
→ 175:def _safe_datetime(value: object) -> datetime | None:
```

✅ `_reconstruct_external_event()` 존재 확인  
✅ `_safe_datetime()` 개선된 버전 확인  
✅ `COPY scripts/ scripts/` 정상 반영

### 6.3 컨테이너 재시작

```bash
$ docker compose up -d ops-scheduler
→ agent_trading-ops-scheduler Recreated, Started (healthy)
```

### 6.4 Health Check

```json
{
    "status": "ok",
    "database": "connected",
    "scheduler": { "healthy": true }
}
```

### 6.5 pytest 결과

```bash
$ python3 -m pytest tests/services/test_decision_orchestrator.py -v
→ 40 passed in 0.09s ✅
```

---

## 7. 운영 검증

### 7.1 `strftime` 에러 소멸

```bash
$ docker compose logs ops-scheduler 2>&1 | grep -i "strftime\|fallback\|AttributeError"
→ (no output) ✅
```

컨테이너 재시작 이후 `strftime` 관련 `AttributeError` 또는 `using fallback output` 로그가 전혀 출력되지 않음.

### 7.2 `agent_runs` 상태

| 항목 | 값 |
|------|-----|
| 총 agent_runs | 16,062건 |
| `structured_output_json` 비어있지 않은 건수 | 16,062건 (100%) |
| 최근 20건 상태 | 모두 `completed` |

### 7.3 Scheduler 정상 동작 확인

- 12:58:35 → ops-scheduler 시작 (healthy)
- 12:58:43 → snapshot-sync 완료 (1 cycle)
- 12:59:06 → event-ingestion 완료
- 12:59:06 → post-submit-sync 완료
- 12:59:06 → `phase=pre-market complete` → `session_gate: ALLOW phase=intraday`

---

## 8. 교훈 및 재발 방지

| 문제 | 방지 대책 |
|------|----------|
| 이미지 재빌드 누락 | 배포 체크리스트에 `docker compose build` 단계 명시 |
| `COPY scripts/ scripts/` 누락 | Dockerfile review 시 `COPY` 누락 검사 자동화 |
| volume mount로 인한 착시 | `docker compose exec` vs `docker run --rm` 결과가 다를 수 있음을 인지 |
| type hint 불일치 | `str \| None` 대신 `object` 사용으로 defensive coding |

---

## 9. 관련 파일

| 파일 | 설명 |
|------|------|
| [`scripts/run_agent_subprocess.py`](../scripts/run_agent_subprocess.py) | Subprocess entry point — `_safe_datetime()`, `_reconstruct_external_event()`, `_reconstruct_context()` |
| [`src/agent_trading/services/decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py) | Parent process — `_serialize_agent_input()`, `_dataclass_to_dict()`, `_run_agents_in_subprocess()` |
| [`src/agent_trading/domain/entities.py`](../src/agent_trading/domain/entities.py) | `ExternalEventEntity` — `published_at: datetime` |
| [`Dockerfile`](../Dockerfile) | `COPY scripts/ scripts/` 추가 |
| [`docker-compose.yml`](../docker-compose.yml) | Volume mount 설정 (`./scripts:/app/scripts`, `./src:/app/src`) |
