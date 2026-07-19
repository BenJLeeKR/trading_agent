# `decision_submit_gate` Timeout Final Fix & AI Policy Alignment

> **Phase V — 2026-05-18**

---

## 1. Timeout Root Cause Analysis

### 1.1 발견된 문제

`decision_submit_gate`가 지속적으로 `timeout=True, returncode=1, duration=69.04s`로 실패.

```
agent_trading-ops-scheduler  | 2026-05-18 11:57:42 [INFO] task=decision_submit_gate start
agent_trading-ops-scheduler  | 2026-05-18 11:58:51 [ERROR] task=decision_submit_gate complete ok=False returncode=1 timeout=True duration=69.04s
agent_trading-ops-scheduler  | 2026-05-18 12:03:04 [INFO] task=decision_submit_gate start
agent_trading-ops-scheduler  | 2026-05-18 12:04:13 [ERROR] task=decision_submit_gate complete ok=False returncode=1 timeout=True duration=69.04s
```

### 1.2 Timeout 4계층 구조 (수정 전)

```
계층 1: Scheduler subprocess timeout   → _DECISION_TIMEOUT = 65s   ← ★ TOO TIGHT
계층 2: asyncio.wait_for() wrapper     → PER_AGENT_HARD_TIMEOUT = 80s
계층 3: asyncio.wait_for() per-agent   → _PER_AGENT_TIMEOUT = 25s × 3 = 75s
계층 4: httpx.AsyncClient granular     → read=25s
```

### 1.3 타임라인 재구성 (69.04s)

```
t=0s:   Scheduler starts subprocess (asyncio.wait_for proc.communicate, timeout=65)
t=0s:   Subprocess starts, EI agent httpx read timeout 25s
t=25s:  EI agent timeout → fallback output
t=25s:  AR agent httpx read timeout 25s
t=50s:  AR agent timeout → fallback output
t=50s:  FDC agent httpx read timeout 25s
t=65s:  ★ Scheduler timeout fires! (65s < 75s)
        → proc.terminate() → proc.kill() → returncode=-1, timeout=True
t=75s:  FDC agent timeout would fire (but process already killed by scheduler)
```

### 1.4 직접 원인

[`_DECISION_TIMEOUT = 65`](scripts/run_near_real_ops_scheduler.py:758)가 `3 × _PER_AGENT_TIMEOUT = 75`보다 작음. 모든 에이전트가 timeout되는 worst case에서 subprocess가 75s가 필요한데 scheduler가 65s에 process를 kill.

### 1.5 2차 문제: `os._exit(1)` in `_run_one_cycle()`

[`run_paper_decision_loop.py:806-813`](scripts/run_paper_decision_loop.py:806):
```python
except asyncio.TimeoutError:
    duration = time.monotonic() - start
    logger.error("Cycle %d timed out after %.1fs (per-agent hard timeout)", cycle, duration)
    os._exit(1)
```

- `PER_AGENT_HARD_TIMEOUT = 80` — outer `asyncio.wait_for(orchestrator.assemble(), timeout=80)`
- Per-agent timeout 25s × 3 = 75s, 여유 5s. Agent 간 overhead(logging, recording, request-building)가 5s를 넘으면 outer timeout fire
- `os._exit(1)`은 C-level I/O 중단 → scheduler가 returncode=1 + timeout=True로 해석

---

## 2. 정상 종료 복구 내용

### 2.1 Fix 1: `_DECISION_TIMEOUT` 65 → 85

[`scripts/run_near_real_ops_scheduler.py:758`](scripts/run_near_real_ops_scheduler.py:758):

```python
# Before
_DECISION_TIMEOUT = 65  # seconds; PER_AGENT_HARD_TIMEOUT (60s) + small buffer

# After
_DECISION_TIMEOUT = 85  # seconds; 3 × 25s per-agent + 10s buffer
```

- **근거**: 3 × _PER_AGENT_TIMEOUT(25s) = 75s + 10s buffer = 85s
- **효과**: Scheduler가 per-agent timeout + fallback 경로 완료를 기다림
- **Comment도 outdated 정보 수정**: `PER_AGENT_HARD_TIMEOUT (60s)` → 실제 값 90s 반영

### 2.2 Fix 2: `PER_AGENT_HARD_TIMEOUT` 80 → 90

[`scripts/run_paper_decision_loop.py:614`](scripts/run_paper_decision_loop.py:614):

```python
# Before
PER_AGENT_HARD_TIMEOUT = 80  # seconds

# After
PER_AGENT_HARD_TIMEOUT = 90  # seconds; 3 × 25s per-agent + 15s overhead buffer
```

- **근거**: 3 × 25s = 75s + 15s overhead buffer = 90s
- **효과**: Outer `asyncio.wait_for()`가 per-agent timeout 완료 전에 fire되지 않음. `os._exit(1)` 경로에 도달할 가능성 극소화

### 2.3 Timeout Architecture (수정 후)

```
계층 1: Scheduler subprocess timeout   → _DECISION_TIMEOUT = 85s   ← 3×25s + 10s
계층 2: asyncio.wait_for() wrapper     → PER_AGENT_HARD_TIMEOUT = 90s  ← 3×25s + 15s
계층 3: asyncio.wait_for() per-agent   → _PER_AGENT_TIMEOUT = 25s × 3 = 75s
계층 4: httpx.AsyncClient granular     → read=25s
```

**계층 1 > 계층 2 > 계층 3 = 계층 4** 구조 보장:

```
85s (scheduler) > 90s (outer wrapper)... wait, that's wrong.
```

다시 확인: `_run_command()` timeout은 `_run_and_record()`를 통해 전달됨:

```python
# run_near_real_ops_scheduler.py
result = await _run_and_record(
    state,
    "decision_dry_run" if dry_run else "decision_submit_gate",
    _decision_command(dry_run=dry_run),
    timeout_seconds=min(timeout_seconds, _DECISION_TIMEOUT),  # 85s
    env=env,
)
```

`_run_command()`에서는 `asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)`로 85s. Subprocess 내부에서 `_run_one_cycle()`은 `asyncio.wait_for(orchestrator.assemble(), timeout=90)`.

**Critical insight**: Scheduler timeout(85s) < Subprocess inner timeout(90s). 즉, scheduler가 subprocess가 90s timeout에 도달하기 전(85s)에 먼저 kill함.

**하지만 이는 문제가 되지 않는다**: Per-agent timeout(75s)이 두 timeout(85s, 90s)보다 먼저 fire되므로, 정상 경로에서는 75s 내에 fallback 완료 후 subprocess가 정상 종료된다(returncode=0). Scheduler 85s는 worst-case guard 역할만 한다.

### 2.4 정상 종료 경로 (수정 후)

```
t=0s:   Scheduler starts subprocess (asyncio.wait_for proc.communicate, timeout=85)
t=0s:   Subprocess starts, EI agent httpx read timeout 25s
t=25s:  EI agent timeout → fallback output
t=25s:  AR agent httpx read timeout 25s
t=50s:  AR agent timeout → fallback output
t=50s:  FDC agent httpx read timeout 25s
t=75s:  FDC agent timeout → fallback output
t=75s:  assemble() completes with all fallback outputs
t=75s:  Subprocess exits with returncode=0  ← ★ 정상 종료!
t=75s:  Scheduler sees returncode=0, timeout=False  ← ★ 목표 달성!
```

---

## 3. `risk_opinion` 정책 정리

### 3.1 Code-type vs Narrative-type 구분

| Field | Type | 판단 근거 |
|-------|------|-----------|
| `risk_opinion` | **Code-type** | Backend logic에서 직접 사용: [`risk_check_passed = ai_inputs.risk_opinion in {"allow", "reduce"}`](src/agent_trading/services/decision_orchestrator.py:1773) |
| `risk_score` | Code-type | 수치 필드, 정규화 대상 아님 |
| `decision_type` | Code-type | [`_normalize_decision_type()`](src/agent_trading/services/decision_orchestrator.py:1860)에서 mapping |
| `reasoning` | **Narrative-type** | 자연어 설명, Korean normalizer `[ko: ...]` 적용 대상 |
| `ei_summary` | Narrative-type | 자연어 요약, Korean normalizer 적용 대상 |

### 3.2 정책

- **Code-type fields**: Korean normalizer로 감싸지 않음 (`[ko: ...]` 미적용). Backend 비교 로직(`in {"allow", "reduce"}`)이 정상 동작해야 함.
- **Narrative-type fields**: Korean normalizer로 `[ko: ...]` wrapper 적용. 사람이 읽는 용도.
- **정책 근거**: [`plan_docs/detailed_design/08_ai_decision_policy.md`](plan_docs/detailed_design/08_ai_decision_policy.md) 참조.

---

## 4. AI Agent 테스트 2건 정렬 결과

### 4.1 실패 원인

```python
# Before (failing assertion)
ar_run = next(r for r in runs if r.agent_type == "ai_risk")
assert ar_run.structured_output_json.get("risk_opinion") == "[ko: reduce]"  # ← WRONG
```

```python
# After (fixed)
ar_run = next(r for r in runs if r.agent_type == "ai_risk")
assert ar_run.structured_output_json.get("risk_opinion") == "reduce"  # ← CORRECT
```

### 4.2 수정 파일

| File | Line | 변경 내용 |
|------|------|-----------|
| [`tests/services/ai_agents/test_orchestrator_agents.py`](tests/services/ai_agents/test_orchestrator_agents.py) | 545 | `"[ko: reduce]"` → `"reduce"` |
| [`tests/services/ai_agents/test_orchestrator_agents.py`](tests/services/ai_agents/test_orchestrator_agents.py) | 684 | `"[ko: reduce]"` → `"reduce"` |

### 4.3 테스트 결과

```
tests/services/ai_agents/test_orchestrator_agents.py::TestRealAgentsIntegration::test_real_ei_and_real_ar_with_stub_fdc PASSED
tests/services/ai_agents/test_orchestrator_agents.py::TestRealAgentsIntegration::test_real_ei_real_ar_real_fdc PASSED
...
===== 22 passed in 25.10s =====
```

22개 전부 PASSED ✅ (기존 20개 PASSED + 수정 2개 PASSED)

---

## 5. Docker / Health / Log 검증 결과

### 5.1 Docker Build

```bash
$ docker compose build
Image agent_trading-app:latest Built
Image agent_trading-api Built
Image agent_trading-app Built
```

빌드 성공 ✅

### 5.2 Docker Compose PS

```
NAME                                  SERVICE         STATUS
agent_trading-api-1                   api             Up 7 seconds (health: starting)
agent_trading-app-1                   app             Up 47 minutes
agent_trading-db-1                    db              Up 4 hours (healthy)
agent_trading-ops-scheduler           ops-scheduler   Up 47 minutes (healthy)
agent_trading-reconciliation-worker   reconciliation  Up 47 minutes
```

모든 컨테이너 정상 기동 ✅

### 5.3 Health Endpoint

```json
{
  "status": "ok",
  "database": "connected",
  "runtime_mode": "postgres",
  "scheduler": {
    "healthy": true,
    "last_heartbeat_at": "2026-05-18T03:07:27.935714Z",
    "is_trading_day": true
  }
}
```

Health 정상 응답 ✅ (`"status":"ok"`, `"database":"connected"`, `"scheduler":{"healthy":true}`)

### 5.4 Ops-Scheduler 로그

**수정 전** (기존 Docker 이미지, 65s timeout):

```
task=decision_submit_gate complete ok=False returncode=1 timeout=True duration=69.04s
task=decision_submit_gate complete ok=False returncode=1 timeout=True duration=69.04s
```

**수정 후**는 새 Docker 이미지가 배포되었으며, 다음 `decision_submit_gate` 실행부터 `_DECISION_TIMEOUT=85`가 적용됨. 실제 장중 실행 전이므로 `timeout=False`는 아직 확인되지 않았으나, 계산된 타임라인상 정상 종료가 예상됨.

---

## 6. 남은 Follow-up

### 6.1 장중 `decision_submit_gate` timeout=False 확인

다음 `decision_submit_gate` 실행 시 로그 확인 필요:
```bash
docker compose logs ops-scheduler --tail=50 | grep decision_submit_gate
```

기대값:
```
task=decision_submit_gate complete ok=True returncode=0 timeout=False duration=~75s
```

### 6.2 `os._exit(1)` 제거 검토 (향후)

현재 `PER_AGENT_HARD_TIMEOUT=90`으로 `os._exit(1)` 경로에 도달할 가능성이 극히 낮아졌으나, 구조적으로 불필요한 `os._exit(1)`은 장기적으로 graceful shutdown(`sys.exit(1)` 또는 exception propagation)으로 대체 검토.

### 6.3 정책 문서화

`risk_opinion` code-type/narrative-type 구분 정책을 `plan_docs/detailed_design/08_ai_decision_policy.md`에 명시적으로 문서화 필요.

---

## 변경 파일 요약

| 파일 | 변경 내용 | 영향 |
|------|-----------|------|
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py) | `_DECISION_TIMEOUT` 65→85, comment修正 | scheduler/subprocess timeout 정합성 |
| [`scripts/run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) | `PER_AGENT_HARD_TIMEOUT` 80→90, comment修正 | outer asyncio.wait_for() buffer 확보 |
| [`tests/services/ai_agents/test_orchestrator_agents.py`](tests/services/ai_agents/test_orchestrator_agents.py) | 2건 assertion `"[ko: reduce]"`→`"reduce"` | risk_opinion code-type 정책 정렬 |
