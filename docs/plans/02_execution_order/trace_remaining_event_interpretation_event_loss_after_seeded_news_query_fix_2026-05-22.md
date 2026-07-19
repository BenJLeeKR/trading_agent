# EI Event Loss 추적 보고서 — `seeded_news` Query Fix 이후에도 `event_count=0`인 원인

## 1. 개요

**문제**: Round 9에서 `external_events.list_by_symbol()`의 `seeded_news` 필터 누락 버그를 수정하고, `decision_orchestrator.assemble()` 및 `_collect_persisted_seeded_events()`에서 `include_seeded_news=True`를 전달했음에도 불구하고, 운영상 최신 EI run은 여전히 `events=[]`, `event_count=0`, `no_material_events=true`로 나오고 있음.

**Codex 확인 결과**:
1. 코드 수정 자체는 실제 반영됨 (5개 파일)
2. `ops-scheduler` 컨테이너에도 수정 반영 확인
3. 실제 `external_events`에는 seeded 뉴스가 존재 (000720: 8건, 001040: 6건 등)
4. 그런데 최신 EI run은 전부 `event_count=0`

## 2. 단계별 Event Flow 분석

### 2.1 전체 Event Flow

```
DB (external_events)
  → list_by_symbol(include_seeded_news=True)  [Round 9 fix]
    → assemble() recent_events                 [Round 9 fix]
      → _serialize_agent_input()               [_dataclass_to_dict()]
        → subprocess stdin (JSON)
          → _reconstruct_context()             [_reconstruct_external_event()]
            → AgentExecutionRequest.context.recent_events
              → EI._build_user_prompt()         [prompt에 이벤트 포함]
                → provider.generate_structured()
                  → provider 응답 (JSON)
                    → EI output (EventInterpretationOutput)
                      → _deserialize_agent_output()
                        → AgentExecutionBundle
```

### 2.2 코드 분석 결과: 직렬화/역직렬화 경로에는 문제 없음

| 단계 | 파일 | 함수 | 결과 |
|------|------|------|------|
| 1. DB 조회 | `external_events.py` | `list_by_symbol(include_seeded_news=True)` | ✅ SQL에 `OR event_type = 'seeded_news'` 추가됨 |
| 2. Context 조립 | `decision_orchestrator.py` | `assemble()` | ✅ `include_seeded_news=True` 전달, sort/limit 20 |
| 3. 직렬화 | `decision_orchestrator.py` | `_dataclass_to_dict()` | ✅ `ExternalEventEntity` 모든 필드 dict로 변환 |
| 4. Subprocess 입력 | `run_agent_subprocess.py` | `main()` → `json.loads()` | ✅ `AgentSubprocessInput(**data)` 정상 파싱 |
| 5. Context 재구성 | `run_agent_subprocess.py` | `_reconstruct_context()` | ✅ `_reconstruct_external_event()`로 각 dict → Entity 복원 |
| 6. EI Prompt | `event_interpretation.py` | `_build_user_prompt()` | ✅ `context.recent_events`를 prompt에 포함 (최대 20건) |
| 7. Provider 호출 | `base.py` | `generate_structured()` | ✅ Provider에 prompt 전송 |
| 8. Provider 응답 파싱 | `event_interpretation.py` | `run()` | ✅ `raw_response.parsed` → `EventInterpretationOutput` |
| 9. 역직렬화 | `decision_orchestrator.py` | `_deserialize_agent_output()` | ✅ `_dict_to_dataclass()`로 복원 |

**결론: 코드상 직렬화/역직렬화 경로에서 `event_type='seeded_news'`가 유실될 지점은 없음.**

### 2.3 실제 유실 가능성이 높은 지점

#### 가설 A: 컨테이너 재시작 누락 (가장 가능성 높음)
- 코드는 수정됐지만 Docker 컨테이너가 재시작되지 않아서 구버전 코드가 실행 중
- `ops-scheduler` 컨테이너에 수정 반영 확인했다고 하지만, `run_paper_decision_loop.py`를 실행하는 컨테이너가 별도로 있을 수 있음
- **확인 방법**: 컨테이너 내부에서 `grep -r "include_seeded_news" scripts/run_paper_decision_loop.py` 실행

#### 가설 B: `assemble()` 예외 발생 (try/except pass)
- `assemble()`의 `list_by_symbol()` 호출이 `try/except pass`로 감싸져 있음
- DB 연결 문제, 타임아웃 등으로 예외가 발생하면 `recent_events`가 빈 tuple로 남음
- **영향**: `recent_events=()` → EI prompt에 이벤트 없음 → provider가 `events=[]` 반환
- **확인 방법**: 컨테이너 로그에서 `"assemble() failed to query recent_events"` 검색 (이번 수정으로 추가된 로그)

#### 가설 C: Provider가 이벤트를 무시
- EI prompt에 이벤트가 포함되어도 provider가 `events=[]`를 반환할 수 있음
- Provider의 판단을 코드 레벨에서 강제로 덮어쓸 수 없음
- **영향**: EI output의 `events=()`, `aggregate_view.no_material_events=True`
- **확인 방법**: 컨테이너 로그에서 `"EI _build_user_prompt: recent_events=N"`와 `"EventInterpretationAgent succeeded: events=0"` 비교

#### 가설 D: `_diag()`가 `/tmp`를 사용 (수정 완료)
- `run_agent_subprocess.py`의 `_diag()`가 `/tmp/subprocess_diag_{pid}.log`에 로그를 기록
- `/tmp`는 컨테이너 재시작 시 소멸되므로 디버그 정보 유실
- **수정**: `/workspace/agent_trading/logs/subprocess_diag_{pid}.log`로 변경 완료

## 3. 적용한 수정

### 3.1 `run_agent_subprocess.py` — `_diag()` 경로 변경

**변경 전**:
```python
_DIAG_LOG = f"/tmp/subprocess_diag_{os.getpid()}.log"
```

**변경 후**:
```python
_DIAG_LOG_DIR = "/workspace/agent_trading/logs"
os.makedirs(_DIAG_LOG_DIR, exist_ok=True)
_DIAG_LOG = f"{_DIAG_LOG_DIR}/subprocess_diag_{os.getpid()}.log"
```

**이유**: `/tmp` 사용 금지 정책 준수. 컨테이너 재시작 후에도 로그가 유지됨.

### 3.2 `run_agent_subprocess.py` — `_reconstruct_context()` 로깅 강화

`_reconstruct_context()`에서 `recent_events_raw`의 개수와 재구성된 `recent_events`의 개수를 `_diag()`로 기록.

```python
_diag(
    f"_reconstruct_context: recent_events_raw count={len(recent_events_raw)} "
    f"→ reconstructed count={len(recent_events)}"
)
```

### 3.3 `decision_orchestrator.py` — `assemble()` 로깅 추가

`assemble()`에서 `recent_events` 조립 후 개수 로깅:
```python
logger.info(
    "assemble() recent_events: symbol=%s count=%d "
    "(list_by_symbol=%d seeded_supplement=%d)",
    request.symbol, len(recent_events), ...
)
```

예외 발생 시에도 로깅:
```python
logger.warning(
    "assemble() failed to query recent_events: symbol=%s",
    request.symbol, exc_info=True,
)
```

### 3.4 `decision_orchestrator.py` — `_deserialize_agent_output()` 로깅 추가

Subprocess output 역직렬화 후 EI output의 event count 로깅:
```python
logger.info(
    "_deserialize_agent_output: symbol=%s "
    "event_output.events=%d event_output.aggregate_view.no_material_events=%s "
    "event_output.aggregate_view.event_count=%s",
    ...
)
```

### 3.5 `event_interpretation.py` — `_build_user_prompt()` 로깅 추가

EI prompt 구성 시점에 실제 이벤트 수 로깅:
```python
logger.info(
    "EI _build_user_prompt: symbol=%s correlation_id=%s "
    "recent_events=%d",
    request.symbol, request.correlation_id, len(events),
)
```

### 3.6 `event_interpretation.py` — `run()` 로깅 강화

Provider 응답 파싱 후 상세 로깅:
```python
logger.info(
    "EventInterpretationAgent succeeded: "
    "symbol=%s events=%d aggregate_view.event_count=%s "
    "no_material_events=%s overall_bias=%s evidence_strength=%s",
    ...
)
```

## 4. 디버그 로그 추적 방법 (운영 검증)

컨테이너 재시작 후 다음 로그를 단계별로 확인:

### 4.1 `assemble()` 단계
```bash
docker logs ops-scheduler 2>&1 | grep "assemble() recent_events"
```
- 예상: `assemble() recent_events: symbol=000720 count=8`
- 만약 `count=0`이면 → 가설 B (DB 조회 실패)

### 4.2 Subprocess 입력 단계
```bash
cat /workspace/agent_trading/logs/subprocess_diag_*.log | grep "_reconstruct_context"
```
- 예상: `_reconstruct_context: recent_events_raw count=8 → reconstructed count=8`
- 만약 `count=0`이면 → 직렬화 문제

### 4.3 EI Prompt 단계
```bash
docker logs ops-scheduler 2>&1 | grep "EI _build_user_prompt"
```
- 예상: `EI _build_user_prompt: symbol=000720 recent_events=8`
- 만약 `recent_events=0`이면 → subprocess 전달 문제

### 4.4 EI Output 단계
```bash
docker logs ops-scheduler 2>&1 | grep "EventInterpretationAgent succeeded"
```
- 예상: `EventInterpretationAgent succeeded: symbol=000720 events=8 event_count=8 no_material_events=False`
- 만약 `events=0`이면 → 가설 C (provider 무시)

### 4.5 역직렬화 단계
```bash
docker logs ops-scheduler 2>&1 | grep "_deserialize_agent_output"
```
- 예상: `_deserialize_agent_output: symbol=000720 event_output.events=8`

## 5. 수정된 파일

| 파일 | 변경 내용 |
|------|----------|
| [`run_agent_subprocess.py`](scripts/run_agent_subprocess.py) | `_diag()` 경로 `/tmp` → `/workspace/agent_trading/logs/`, `_reconstruct_context()` 로깅 강화 |
| [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | `assemble()` 로깅 추가, `_deserialize_agent_output()` 로깅 추가 |
| [`event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py) | `_build_user_prompt()` 로깅 추가, `run()` 로깅 강화 |

## 6. 테스트 결과

| 테스트 | 결과 |
|--------|------|
| `test_external_events.py` (InMemory 8개) | ✅ 통과 |
| `TestEventQueryWindow` (2개) | ✅ 통과 |
| `TestCollectPersistedSeededEvents` (4개) | ✅ 통과 |
| `TestIsT3FreshForSymbol` (4개) | ✅ 통과 |

## 7. 운영 검증 절차

### 7.1 Docker 재빌드 및 재시작
```bash
docker compose build && docker compose up -d
```

### 7.2 Health check
```bash
curl -sf http://localhost:8000/health
```

### 7.3 로그 확인 (대표 종목 000720)
```bash
# assemble() 단계
docker logs ops-scheduler 2>&1 | grep "assemble() recent_events: symbol=000720"

# EI prompt 단계
docker logs ops-scheduler 2>&1 | grep "EI _build_user_prompt:.*000720"

# EI output 단계
docker logs ops-scheduler 2>&1 | grep "EventInterpretationAgent succeeded:.*000720"

# 역직렬화 단계
docker logs ops-scheduler 2>&1 | grep "_deserialize_agent_output:.*000720"
```

### 7.4 Subprocess diag 로그 확인
```bash
ls -la /workspace/agent_trading/logs/subprocess_diag_*.log
cat /workspace/agent_trading/logs/subprocess_diag_*.log | grep -E "recent_events|EventInterpretationAgent"
```

## 8. 결론

### 8.1 코드상 발견된 문제

1. **`_diag()` 경로 문제** (`/tmp` 사용) → **수정 완료**
2. **디버그 로깅 부족** → **수정 완료** (4개 지점에 로깅 추가)

### 8.2 코드상 발견되지 않은 문제 (운영 확인 필요)

1. **컨테이너 재시작 누락** — 가장 가능성 높음. 코드 수정 후 Docker 재빌드/재시작 필요.
2. **`assemble()` 예외 발생** — `try/except pass`로 감춰짐. 추가된 로그로 확인 가능.
3. **Provider가 이벤트 무시** — 추가된 로그로 EI prompt의 이벤트 수와 EI output의 이벤트 수 비교 가능.

### 8.3 권장 조치 순서

1. **Docker 재빌드 및 재시작** (필수)
2. **로그 확인** (4.1~4.5 단계별)
3. **Provider 무시 확인 시**: EI prompt 강화 (system prompt에 이벤트 처리 강조) 또는 fallback 로직 검토
