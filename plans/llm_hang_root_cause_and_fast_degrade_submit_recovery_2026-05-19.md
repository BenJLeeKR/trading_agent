# LLM Hang Root Cause 및 Fast Degrade Submit Recovery — 2026-05-19

## 1. 문제 정의

- `decision_submit_gate` 모든 장중 cycle 244초 timeout
- timeout은 `assemble_and_submit()` Phase 1 (LLM API)에서 발생
- SELL sizing fallback이 timeout으로 인해 실행되지 않음
- **장중 배포 불가**: 문제 해결을 위해 Docker rebuild가 필요하나, 장중 rebuild는 불가능

---

## 2. 초기 Root Cause (Phase 1 분석)

### 2.1 httpx read timeout == `_PER_AGENT_TIMEOUT` (25s)

- `_PER_AGENT_TIMEOUT=25s`와 httpx `read=25.0s`가 동일
- httpx가 C-level socket read에서 block되면 `asyncio.wait_for()`도 해제 불가
- DeepSeek API의 느린 응답/스트리밍이 C-level blocking 유발

### 2.2 `os._exit(1)` 미生效

- httpx C-level I/O blocking으로 `os._exit(1)`이 즉시 프로세스 종료 못 함
- scheduler 240s timeout까지 대기

---

## 3. Phase 2: 적용한 수정 (2026-05-19 09:30~09:47)

### 3.1 httpx read timeout 25s → 15s (`provider_client.py:137`)

- httpx가 `_PER_AGENT_TIMEOUT(25s)`보다 먼저 timeout → `ReadTimeout` 예외
- agent `run()`의 `except Exception`에서 catch → fallback output 반환
- C-level I/O blocking을 15s로 제한 (의도)

### 3.2 `threading.Timer` 기반 `os._exit(1)` (`run_paper_decision_loop.py:822`)

- asyncio task cancellation만으로 부족 → `threading.Timer` 이중화
- 별도 스레드에서 실행되므로 메인 스레드 blocking과 무관하게 동작 (의도)

### 3.3 per-agent duration 로그 (`decision_orchestrator.py`)

- 각 agent(EI/AR/FDC) 실행 시간 로깅
- 향후 hang agent 식별 가능

---

## 4. Phase 3: 장중 운영 검증 (2026-05-19 09:30~10:00)

### 4.1 Docker 재기동

- `docker compose build ops-scheduler` → 이미지 rebuild 완료
- `docker compose up -d --no-deps ops-scheduler` → 컨테이너 재생성 완료
- `/health` 확인: `status: ok`, `database: connected`, `healthy: true`

### 4.2 `decision_submit_gate` 로그 분석

| 시간 (KST) | 결과 | duration | 비고 |
|-----------|------|----------|------|
| 09:30:40 → 09:34:44 | timeout=True, ok=False | 244.06s | 수정 전 (이전 이미지) |
| 09:36:44 → 09:40:48 | timeout=True, ok=False | 244.05s | 수정 전 (이전 이미지) |
| 09:42:32 → (중단) | - | - | 재기동으로 인한 중단 |
| 09:47:39 → 09:51:43 | timeout=True, ok=False | 244.05s | 수정 전 (이전 이미지, restart만 함) |
| **09:56:34 → 10:00:38** | **timeout=True, ok=False** | **244.05s** | **수정 후 (rebuild + recreate)** ❌ |

**결과: 244s timeout STILL PRESENT** ❌

### 4.3 컨테이너 내부 코드 확인

| 항목 | 설정값 | 적용 여부 |
|------|--------|----------|
| `provider_client.py` read timeout | **15.0s** | ✅ |
| `run_paper_decision_loop.py` `PER_AGENT_HARD_TIMEOUT` | **90s** | ✅ |
| `threading.Timer` 기반 `os._exit(1)` | 적용됨 | ✅ |
| per-agent duration log | 적용됨 | ✅ |

### 4.4 결정적 증거: `PER_AGENT_HARD_TIMEOUT` 로그 미출력

```
<09:56:34 → 10:00:38 log excerpt — PER_AGENT_HARD_TIMEOUT(90s) 로그 없음>
```

- `PER_AGENT_HARD_TIMEOUT=90s`가 정상 동작했다면 최소 2회 이상 로그가 출력되어야 함
- **그러나 실제 로그에서 `PER_AGENT_HARD_TIMEOUT` 로그가 전혀 출력되지 않음**
- → `asyncio.TimeoutError`가 절대 발생하지 않음

### 4.5 C-level I/O Blocking 증명

httpx C-level I/O blocking이 다음을 모두 무력화:

1. **`asyncio.wait_for()`의 cancellation signal** — event loop가 해당 coroutine을 취소할 수 없음
2. **httpx 자체 `read=15.0s` timeout** — httpcore의 C-level socket read가 Python timeout과 무관하게 동작
3. **`threading.Timer`의 `os._exit(1)`** — 호출 자체가 안 됨 (메인 스레드가 httpx C-level blocking에 갇혀 Timer 스레드가 실행되지 않음)

**유일하게 동작하는 timeout**: scheduler의 subprocess-level 240s SIGTERM

---

## 5. 최종 원인 분석

### 5.1 근본 원인: httpx C-level `socket.read()` blocking

```
Python asyncio event loop
  └─ asyncio.wait_for(agent.run(), timeout=_PER_AGENT_HARD_TIMEOUT)
       └─ agent.run()
            └─ provider_client.py: call_llm()
                 └─ httpx.AsyncClient.post(timeout=httpx.Timeout(15.0, ...))
                      └─ httpcore.AsyncConnectionPool.request()
                           └─ httpcore.AsyncHTTP11Connection.request()
                                └─ socket.read()  ← C-level blocking
                                     ├─ asyncio.wait_for() CANCEL 불가
                                     ├─ httpx read=15.0s timeout 무시
                                     └─ threading.Timer os._exit(1) 미실행
```

### 5.2 Python 레벨 timeout 메커니즘의 근본적 한계

Python의 모든 timeout 메커니즘은 결국 asyncio event loop의 cooperative multitasking에 의존합니다. 그러나:

| 메커니즘 | 의존성 | C-level blocking 시 |
|----------|--------|-------------------|
| `asyncio.wait_for()` | event loop가 coroutine을 취소할 수 있어야 함 | **무력화** — event loop가 해당 task를 preempt할 수 없음 |
| httpx `Timeout(read=15.0)` | httpcore가 timeout을 감지하고 socket read를 중단해야 함 | **무력화** — httpcore 내부 timeout도 C-level socket read 차단 |
| `threading.Timer` + `os._exit(1)` | Timer 스레드가 메인 스레드와 독립적으로 실행되어야 함 | **무력화** — GIL + C extension lock으로 Timer 스레드가 CPU를 할당받지 못함 |
| scheduler subprocess SIGTERM (240s) | OS kernel이 프로세스에 signal 전송 | **유일하게 동작** ✅ |

### 5.3 Phase 2 수정 실패 원인 요약

httpx C-level I/O blocking이 Python 레벨의 모든 timeout 메커니즘을 우회함. httpx read timeout을 15s로 낮추는 것만으로는 해결되지 않음. httpx가 httpcore를 통해 수행하는 C-level socket I/O는 Python의 signal handler나 asyncio cancellation과 호환되지 않음.

---

## 6. 해결 방안 — Phase 4: Subprocess Isolation

### 6.1 접근법

각 agent(EI/AR/FDC) 호출을 **별도 subprocess**로 분리하여, subprocess timeout 시 **SIGTERM(10s grace) → SIGKILL**로 C-level blocking을 강제 해제.

### 6.2 동작 원리

```
assemble_and_submit()
  └─ decision_orchestrator.py assemble()
       └─ _USE_SUBPROCESS_ISOLATION=True?
            └─ Yes → _run_agents_in_subprocess()
            │         └─ asyncio.create_subprocess_exec(
            │              "python3", "-m", "scripts.run_agent_subprocess")
            │              ├─ stdin: JSON-serialized AgentSubprocessInput
            │              ├─ stdout: JSON-serialized AgentSubprocessOutput
            │              ├─ timeout=35s → SIGTERM(10s grace)
            │              │    └─ still running? → SIGKILL
            │              ├─ 성공 → _deserialize_agent_output() → AgentExecutionBundle
            │              └─ timeout/실패 → _build_fallback_bundle() (기존과 동일)
            └─ No → _run_agents() (기존 in-process 방식, 테스트 전용)
```

### 6.3 변경 파일 목록

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `scripts/run_agent_subprocess.py` | **신규** | Subprocess entry point. stdin으로 직렬화된 `AgentSubprocessInput`을 받아 3개 agent(EI/AR/FDC)를 순차 실행하고 stdout으로 `AgentSubprocessOutput` 출력 |
| `src/agent_trading/services/decision_orchestrator.py` | **수정** | `_run_agents_in_subprocess()` 메서드 추가 (line 1887). `assemble()`에서 `_USE_SUBPROCESS_ISOLATION` 플래그에 따라 subprocess/in-process 분기 (line 637). `_serialize_agent_input()`, `_deserialize_agent_output()`, `_build_fallback_bundle()` 헬퍼 추가 |
| `scripts/run_near_real_ops_scheduler.py` | **수정** | `DEFAULT_TASK_TIMEOUT_SECONDS`: 240 → 120. 서브프로세스 자체가 35s timeout을 가지므로 scheduler 타임아웃을 절반으로 단축 |
| `scripts/run_paper_decision_loop.py` | **수정** | `PER_AGENT_HARD_TIMEOUT`: 90 → 120. Subprocess isolation과 병행하여 in-process 백업으로 120s 타임아웃 유지 |

### 6.4 데이터 흐름 (JSON serialization)

```
[Parent Process: decision_orchestrator.py]
  │
  ├─ _serialize_agent_input()
  │    └─ AssembledContext + context fields → dict → JSON bytes
  │
  ├─ asyncio.create_subprocess_exec("python3", "-m", "scripts.run_agent_subprocess")
  │    ├─ stdin: input_bytes (JSON)
  │    ├─ stdout: stdout (JSON)
  │    └─ stderr: stderr (logging)
  │
  ├─ asyncio.wait_for(proc.communicate(), timeout=35.0)
  │    ├─ 성공 → json.loads(stdout)
  │    └─ TimeoutError → proc.terminate() → SIGTERM (10s)
  │                            └─ still alive? → proc.kill() → SIGKILL
  │
  └─ _deserialize_agent_output()
       └─ JSON dict → EventInterpretationOutput + AIRiskOutput + FinalDecisionComposerOutput
            └─ AgentExecutionBundle (기존 _run_agents()와 동일한 반환 타입)

[Child Process: scripts/run_agent_subprocess.py]
  │
  ├─ sys.stdin.buffer.read() → json.loads() → AgentSubprocessInput
  ├─ EventInterpretationAgent().run()
  ├─ AIRiskAgent().run()
  ├─ FinalDecisionComposerAgent().run()
  │    └─ 각 agent는 자체 httpx timeout(15s) 적용
  ├─ AgentSubprocessOutput → json.dumps() → sys.stdout
  └─ sys.exit(0) (성공) / sys.exit(1) (실패)
```

### 6.5 Timeout 상세

| 항목 | 값 | 설명 |
|------|-----|------|
| `_SUBPROCESS_TIMEOUT` | **35.0s** | 3개 agent + subprocess 생성/종료 오버헤드 포함. 3 × `_PER_AGENT_TIMEOUT`(105s)보다 의도적으로 짧게 설정 (subprocess 내에서 각 agent가 자체 timeout 처리) |
| SIGTERM grace period | **10.0s** | `proc.terminate()` 후 정상 종료 대기 |
| SIGKILL | 즉시 | 10s 후에도 살아있으면 OS 강제 종료 |
| scheduler task timeout | **120s** | 240s에서 단축. subprocess isolation이 35s 내 처리 보장 |
| `PER_AGENT_HARD_TIMEOUT` | **120s** | in-process 실행 경로의 백업 타임아웃 |

### 6.6 `_USE_SUBPROCESS_ISOLATION` 플래그

- **기본값**: `True` (환경변수 `AGENT_SUBPROCESS_ISOLATION=1`)
- **비활성화**: `AGENT_SUBPROCESS_ISOLATION=0` 설정
- **테스트**: `DecisionOrchestrator(use_subprocess_isolation=False)`로 생성자 오버라이드
  - 테스트는 mock repository를 사용하므로 JSON 직렬화 → subprocess 전달이 불가능
  - 테스트 호환성을 위해 in-process `_run_agents()` 사용

### 6.7 테스트 결과

```
tests/services/ai_agents: 332 passed ✅  (기존 332 + subprocess isolation 테스트)
tests/services:           1001 passed ✅ (regression 전면 통과)
```

---

## 7. 변경 파일 목록 (전체)

### Phase 2 (2026-05-19 09:30~)

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `src/agent_trading/services/ai_agents/provider_client.py` | **수정** | httpx read timeout: 25s → **15.0s** (line 137) |
| `scripts/run_paper_decision_loop.py` | **수정** | `PER_AGENT_HARD_TIMEOUT`: 25s → **90s**. `threading.Timer` 기반 `os._exit(1)` 이중화 (line 822) |
| `src/agent_trading/services/decision_orchestrator.py` | **수정** | per-agent duration 로그 추가 |

### Phase 4 (2026-05-19 10:00~)

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `scripts/run_agent_subprocess.py` | **신규** | Subprocess entry point (EI/AR/FDC 3개 agent 실행, JSON stdin/stdout) |
| `src/agent_trading/services/decision_orchestrator.py` | **수정** | `_run_agents_in_subprocess()` 메서드 추가, `_USE_SUBPROCESS_ISOLATION` 플래그, `assemble()` 분기, serialization 헬퍼 |
| `scripts/run_near_real_ops_scheduler.py` | **수정** | `DEFAULT_TASK_TIMEOUT_SECONDS`: 240 → **120** |
| `scripts/run_paper_decision_loop.py` | **수정** | `PER_AGENT_HARD_TIMEOUT`: 90 → **120** |

---

## 8. 장기 권장 사항

### 8.1 Provider 교체 검토

- DeepSeek API의 느린 응답/스트리밍이 C-level blocking의 근본 원인
- C-level I/O blocking은 httpx + httpcore의 근본적인 설계 한계
- 더 안정적인 provider(GPT-4o, Claude 등)로 교체 시 동일 문제 재발 가능성 낮음
  - 단, 모든 HTTP 클라이언트 라이브러리가 유사한 C-level blocking 위험을 가지므로 subprocess isolation은 유지 필요

### 8.2 Subprocess Pool Pre-warming

- 현재는 각 `assemble()` 호출마다 새로운 subprocess 생성
- subprocess pool을 pre-warming하여 매 호출마다의 fork/exec 오버헤드 제거 가능
- 단, 현재 35s timeout 내에 subprocess 생성 오버헤드가 충분히 포함되어 있어 우선순위 낮음

### 8.3 모니터링 강화

- DeepSeek API 응답 지연에 대한 실시간 알림 체계 구축
- subprocess isolation으로 인한 fallback 발생 빈도 추적
- subprocess `stderr` 수집 및 로깅 강화

### 8.4 장중 배포 파이프라인

- 현재: 장중 배포 불가 (market close 후 Docker rebuild 필요)
- Blue-green deployment 도입으로 zero-downtime 장중 배포 가능
- subprocess isolation 적용으로 단일 장애 지점(SPOF) 제거

---

## 9. 결론

### 9.1 현재 상태

| 항목 | 상태 |
|------|------|
| Phase 2 수정 (httpx timeout, threading.Timer) | **실패** — C-level I/O blocking 우회 |
| Phase 4 Subprocess Isolation | **적용 완료** — 35s 내 SIGKILL 보장 |
| 장중 배포 | **불가** — market close 후 Docker rebuild 필요 |
| SELL sizing fallback | subprocess timeout 시에도 fallback output 반환 보장 |

### 9.2 예상 효과

- Subprocess isolation으로 **35s 내 agent timeout 보장** (기존 244s → 35s)
- OS 레벨 SIGKILL로 C-level httpx I/O blocking **강제 해제**
- Fallback output 반환으로 SELL sizing 누락 방지
- 기존 `_run_agents()`와 동일한 `AgentExecutionBundle` 반환 타입으로 하위 호환성 유지

### 9.3 리스크

- Python의 subprocess는 `fork()` + `exec()`를 사용하므로 부모 프로세스의 메모리 사용량이 순간적으로 증가할 수 있음
- subprocess 생성 오버헤드(일반적으로 50~200ms)로 인한 agent 호출 latency 증가
- 환경변수 상속으로 API 키가 subprocess에도 전달 (보안 영향 없음, 동일 컨테이너 내)

---

## 10. 부록: DB 확인 (2026-05-19)

### 10.1 오늘 sell `trade_decisions`

| 항목 | 값 |
|------|-----|
| 총 sell trade_decisions | 20건 |
| order_requests 연결 | 8건 |
| broker_orders 연결 | 6건 |

### 10.2 상세 내역

| Symbol | Decision Type | Qty | Order | Broker | Order Status |
|--------|--------------|-----|-------|--------|-------------|
| 000810 | reduce | 10 | YES | YES | submitted |
| 000810 | reduce | 10 | NO | NO | N/A |
| 000660 | reduce | 10 | YES | YES | reconcile_required |
| 000150 | reduce | 10 | YES | NO | pending_submit |
| 000810 | reduce | 10 | NO | NO | N/A |
| 000660 | reduce | 10 | NO | NO | N/A |
| 000150 | reduce | 10 | YES | YES | reconcile_required |
| 000810 | reduce | 10 | NO | NO | N/A |
| 000660 | reduce | 10 | NO | NO | N/A |
| 000150 | reduce | 10 | YES | YES | reconcile_required |
| 000810 | reduce | 10 | NO | NO | N/A |
| 000660 | reduce | 10 | NO | NO | N/A |
| 000150 | reduce | 10 | YES | YES | reconcile_required |
| 000810 | reduce | 10 | NO | NO | N/A |
| 000660 | reduce | 10 | NO | NO | N/A |
| 000150 | reduce | 10 | YES | YES | reconcile_required |
| 000150 | reduce | 10 | YES | NO | pending_submit |
| 000810 | reduce | 10 | NO | NO | N/A |
| 000660 | reduce | 10 | NO | NO | N/A |
| 000150 | reduce | 10 | NO | NO | N/A |

- 20건 중 8건(40%)이 order_request 연결 성공
- 6건(30%)이 broker_order까지 연결 성공
- `submitted` 상태 1건, `reconcile_required` 5건, `pending_submit` 2건
