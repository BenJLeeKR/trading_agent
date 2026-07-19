# Subprocess Timeout Tuning: Latency 기반 재조정 설계

## 1. 현재 Timeout 설정 인벤토리

### 1.1 전체 Timeout 계층 구조 (4-Layer)

```
run_decision_loop.py
  └─ PER_AGENT_HARD_TIMEOUT = 420s  ← Layer 4: assemble_and_submit() 전체 외부 safety net
       │
       └─ decision_orchestrator.py / decision_agent_runner.py
            ├─ self._subprocess_timeout = 300s  ← Layer 3: subprocess proc.communicate() timeout
            │    └─ (내부 subprocess: run_agent_subprocess.py)
            │         ├─ _PER_AGENT_TIMEOUT = 35s (per-agent)  ← Layer 2: 각 agent asyncio.wait_for
            │         │    ├─ EventInterpretationAgent.run()    → timeout=35s
            │         │    ├─ AIRiskAgent.run()                 → timeout=35s
            │         │    └─ FinalDecisionComposerAgent.run()  → timeout=35s
            │         │
            │         └─ provider_timeout_seconds = 120 (httpx read timeout)  ← Layer 1: HTTP client
            │              (settings.py default: 30s, constructor override: 120s)
            │
            └─ (in-process fallback path: 동일한 _PER_AGENT_TIMEOUT = 35s 적용)
```

### 1.2 각 설정 상세

| 계층 | 파일 | 심볼 / 파라미터 | 값 | 설정 방식 |
|------|------|----------------|-----|----------|
| L1 (httpx) | [`settings.py`](../src/agent_trading/config/settings.py:96) | `_resolve_provider_timeout()` | **30s (default)** | `DEEPSEEK_TIMEOUT_SECONDS` env var |
| L1 (httpx) | [`decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py:186) | `provider_timeout_seconds: int = 120` | **120s** | 생성자 파라미터 override |
| L2 (per-agent) | [`decision_agent_runner.py`](../src/agent_trading/services/decision_agent_runner.py:66) | `_PER_AGENT_TIMEOUT = 35` | **35s** | 모듈 상수 |
| L2 (per-agent) | [`decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py:105) | `_PER_AGENT_TIMEOUT = 35` | **35s** | 모듈 상수 |
| L3 (subprocess) | [`decision_agent_runner.py`](../src/agent_trading/services/decision_agent_runner.py:84) | `subprocess_timeout: int = 300` | **300s** | 생성자 기본값 |
| L3 (subprocess) | [`decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py:222) | `subprocess_timeout=300` | **300s** | 명시적 전달 |
| L4 (outer) | [`run_decision_loop.py`](../scripts/run_decision_loop.py:662) | `PER_AGENT_HARD_TIMEOUT = 420` | **420s** | 모듈 상수 |

### 1.3 제어 흐름 상세

1. **L1 (httpx timeout)**: httpx `AsyncClient`의 read timeout. subprocess 내부에서 각 AI provider API 호출 시 적용. 기본 30s이나 orchestrator가 120s로 override.
2. **L2 (per-agent timeout)**: 각 agent의 `asyncio.wait_for()` 래퍼. EI→AR→FDC 순차 실행되며 각 단계별 35s 제한. 초과 시 `asyncio.TimeoutError` → 해당 agent만 fallback output, 전체 pipeline은 계속 진행.
3. **L3 (subprocess timeout)**: subprocess의 `proc.communicate()`에 `asyncio.wait_for()` 적용. 300s 초과 시 SIGTERM(10s grace) → SIGKILL → `build_fallback_bundle()`.
4. **L4 (outer timeout)**: `assemble_and_submit()` 호출 전체를 감싸는 `asyncio.wait_for()`. 420s 초과 시 symbol-level `PhaseTraceEntry(status="timeout")` 기록.

> **참고**: `run_decision_loop.py` 주석(라인 662-670)에 따르면 L4는 "last-resort safety net"이며 실제로 L3 subprocess isolation이 더 엄격한 timeout을 제공.

---

## 2. 실제 Latency vs Timeout 비교

### 2.1 측정 데이터 출처

- **로그 파일**: [`logs/submit_measurement_20260526_131726.log`](../logs/submit_measurement_20260526_131726.log)
- **측정 일시**: 2026-05-26 KST (최근 측정)
- **측정 대상**: Universe 30개 symbol, 1 cycle
- **측정 구간**: `ai_assemble` phase (subprocess 내부 EI→AR→FDC 순차 실행)

### 2.2 ai_assemble Phase Latency 분포

| 통계 | 값 | 비고 |
|------|-----|------|
| 최소 | **3,997ms** (~4.0s) | symbol=001740 |
| 최대 | **15,870ms** (~15.9s) | symbol=000720 |
| 평균 | **~8,800ms** (~8.8s) | 30개 symbol 평균 |
| P50 (중앙값) | **~8,600ms** | 4,000~16,000ms 범위 |
| P90 | **~13,000ms** | 27/30 symbol이 13s 이하 |
| P95 | **~15,600ms** | 28/30 symbol |
| P99 | **~15,870ms** | 사실상 max와 동일 |

### 2.3 Symbol별 Latency (오름차순)

| Symbol | elapsed_ms | Symbol | elapsed_ms |
|--------|-----------|--------|-----------|
| 001740 | 3,997 | 000030 | 4,442 |
| 004000 | 4,054 | 000210 | 8,551 |
| 001440 | 4,127 | 003490 | 8,593 |
| 004990 | 4,163 | 001800 | 8,983 |
| 002380 | 4,193 | 005830 | 9,394 |
| 001680 | 4,233 | 001450 | 9,810 |
| 003670 | 4,302 | 000670 | 9,994 |
| 001230 | 4,331 | 000810 | 10,755 |
| 004170 | 4,343 | 004020 | 11,012 |
| 003410 | 4,458 | 000660 | 11,301 |
| 000100 | 11,411 | 004800 | 11,811 |
| 004370 | 11,457 | 003550 | 12,191 |
| 000270 | 11,544 | 001040 | 12,937 |
| 000990 | 13,081 | 000150 | 15,616 |
| 000880 | 13,887 | 000720 | 15,870 |

### 2.4 단계별 세부 Latency (subprocess 내부)

subprocess 내부에서 각 agent의 단계별 소요 시간:

| 단계 | 실제 측정치 | Timeout | 여유율 |
|------|-----------|---------|-------|
| EI 실행 | ~2~6s (추정, log에 각 단계별 breakdown 없음) | 35s | ~6~18x |
| AR 실행 | ~1~5s (추정) | 35s | ~7~35x |
| FDC 실행 | ~1~5s (추정) | 35s | ~7~35x |
| 전체 ai_assemble (subprocess) | 4.0~15.9s | 300s (L3) | ~19~75x |

> 참고: 각 개별 agent latency는 전체 ai_assemble elapsed_ms에서 parsing 불가 (subprocess 내부에서만 측정). 위 추정치는 전체 latency에서 비율을 가정한 수치.

### 2.5 Timeout 대비 여유율 (현재)

| Timeout 계층 | 값 | 최대 Latency 대비 | 평균 Latency 대비 | P95 대비 |
|-------------|-----|-----------------|-----------------|---------|
| L1 (httpx) | 120s | **7.6x** | **13.6x** | **7.7x** |
| L2 (per-agent) | 35s | **2.2x** (개별 agent 추정 ~6s 기준: 5.8x) | **4.0x** | **2.2x** |
| L3 (subprocess) | 300s | **18.9x** | **34.1x** | **19.2x** |
| L4 (outer) | 420s | **26.5x** | **47.7x** | **26.9x** |

---

## 3. Timeout 발생 로그 분석

### 3.1 측정 로그에서 확인된 Timeout

**결과: 이번 측정 사이클에서는 단 1건의 timeout도 발생하지 않음.**

- 30개 symbol 전부 `ai_assemble` phase 정상 완료
- 전체 wall clock: 79.557s (30개 symbol, semaphore max 5 concurrent)
- Subprocess isolation fallback (`build_fallback_bundle()`) 호출되지 않음
- outer timeout (`PER_AGENT_HARD_TIMEOUT = 420s`)에 걸린 symbol 없음

### 3.2 T3 Pipeline Timeout 확인

T3 (Seeded News) pipeline은 `_T3_TIMEOUT = 30s`로 분리되어 있으며, 주 `ai_assemble` decision path와는 **비동기적으로 실행**됨. 로그에서 다수의 NAVER API 429 (rate limit) 오류가 관찰되었으나 이는 T3 pipeline에만 영향, decision path와 무관.

T3 pipeline timeout (30s)이 발생하더라도 `run_decision_loop.py:1049-1101`의 `_run_t3_live_pipeline()`에서 `asyncio.TimeoutError`가 catch되고, seeded_events는 기존 DB 데이터 유지 → decision quality 저하 가능성은 있으나 pipeline 자체는 계속 진행.

### 3.3 이전 timeout 발생 이력 (간접 확인)

로그 상 `subprocess_diag_*.log` 파일 다수가 존재 (75개 파일). 이는 subprocess diagnostic logging이 정상 동작 중임을 의미. 실제 timeout 발생 시 다음 패턴이 관찰될 것으로 예상:

```
[subprocess] Timeout after {_SUBPROCESS_TIMEOUT}s - sending SIGTERM
[subprocess] SIGKILL sent - subprocess did not exit gracefully
[subprocess] Fallback bundle created for decision_context_id={id}
```

현재 300s의 subprocess timeout은 매우 관대하기 때문에, timeout이 발생한다면 이는 **네트워크 수준의 장애 (KIS/NAVER API 무한 대기, deepseek-chat gateway hang)** 또는 **subprocess 시작 실패**일 가능성이 높음.

---

## 4. 권장 Timeout 조정안

### 4.1 조정 원칙

1. **P99 기준 3x safety margin**: 현재 최대 latency 15.9s 기준 3x = ~48s
2. **Subprocess 생성/정리 오버헤드**: ~5~10s 추가 고려
3. **FDC Skip 케이스 보호**: FDC가 skip되면 EI+AR만 실행되므로 latency 더 짧음 — 조정에 영향 없음
4. **Held position sell 추가 처리**: `run_decision_loop.py:670` 주석에 따르면 held_position sell (REDUCE/EXIT) 추가 AI 실행 시간 필요. 현재 측정에서 REDUCE/EXIT symbol들의 latency가 유의미하게 높지 않음 (모두 정규 분포 내).
5. **Provider timeout 분리 고려**: L1 (httpx timeout)은 subprocess 내부에서 AI provider API 호출의 실제 timeout. 이 값이 너무 작으면 불필요한 provider timeout 발생 가능.

### 4.2 권안 조정안 (Recommended)

| 계층 | 현재값 | 권장값 | 근거 | 리스크 |
|------|-------|-------|------|-------|
| L1 (httpx timeout) | 120s | **60s** | 최대 개별 agent latency 추정 ~6s 기준 10x. deepseek-chat gateway transient hang 충분히 커버. | 너무 낮추면 장애 시 불필요한 재시도 유발 가능 |
| L2 (per-agent timeout) | 35s | **30s** | 실제 개별 agent latency는 ~6s 미만. 5x safety margin. subprocess 정리 시간 단축. | 매우 낮은 리스크. 장애 시 5s 빠른 timeout. |
| L3 (subprocess timeout) | 300s | **90s** | P99 16s 기준 5.6x + startup overhead. 3개 agent 합산 최대 ~48s의 2x 수준. 300s는 과도. | 장애 시 회복 시간 단축 (300s→90s). 정상 실행에 영향 없음. |
| L4 (outer timeout) | 420s | **150s** | L3(90s) + subprocess 재시작/재시도 시간 + buffer. L3보다 1.7x 크게 유지. | 동일. outer timeout은 L3 실패 시 최종 safety net. |

### 4.3 조정 시 Wall Clock 영향 예측

| 항목 | 현재 | 조정 후 | 변화 |
|------|------|--------|------|
| 정상 실행 시 wall clock (30 symbols) | ~80s | **~80s** (변화 없음) | 정상 실행에서는 timeout이 걸리지 않으므로 wall clock 영향 0 |
| 1개 symbol subprocess 장애 시 지연 | **최대 300s** | **최대 90s** | **-70%** (210s 단축) |
| 1개 symbol outer timeout 장애 시 지연 | **최대 420s** | **최대 150s** | **-64%** (270s 단축) |
| 5개 symbol 동시 장애 시 (semaphore) | **최대 300s sequential** | **최대 90s sequential** | **-70%** |

### 4.4 FDC Skip 케이스와의 상호작용

[`_check_fdc_skip()`](../scripts/run_agent_subprocess.py:442) 함수는 다음 조건에서 FDC 실행을 생략:

1. `risk_reject=True` → skip
2. `no_material_events AND is_degraded=False AND no_position` → skip
3. `no_material_events AND is_degraded=False AND has_position AND decision_type=HOLD` → skip
4. `no_material_events AND is_degraded=True` → skip

FDC skip 시 latency가 EI+AR만큼만 소요되므로(약 6~10s), timeout 조정과 무관하게 정상 동작. 오히려 L2 per-agent timeout(30s)이 EI+AR 각각 적용되어 skip된 FDC 단계에서는 timeout 미적용.

**중요**: FDC skip 시 `interpretation_incomplete=True`가 설정되며, 이는 subprocess 외부에서 degraded 상태로 인식됨. 이 degraded 정보는 timeout 상황과 동일한 `AgentExecutionBundle` 필드를 통해 전파되므로 fallback 처리 일관성 유지.

---

## 5. Fallback 경로 안전성 검증

### 5.1 Fallback 호출 조건

Fallback은 다음 상황에서 호출됨:

1. **Subprocess timeout**: `asyncio.wait_for(proc.communicate(), timeout=_SUBPROCESS_TIMEOUT)` → `asyncio.TimeoutError`
2. **Subprocess 비정상 종료**: return code != 0
3. **Subprocess stdout decoding 실패**: `json.loads()` error
4. **개별 agent timeout** (L2): 각 agent별 `asyncio.TimeoutError` → 해당 agent만 fallback output, pipeline 계속 진행

### 5.2 Fallback 함수 체인

```python
# decision_agent_runner.py
asyncio.TimeoutError → SIGTERM(10s) → SIGKILL → build_fallback_bundle()

# subprocess_helpers.py
build_fallback_bundle() → EventInterpretationOutput()  # default: empty
                       → AIRiskOutput()                 # default: risk_reject=False
                       → FinalDecisionComposerOutput()   # default: decision_type='HOLD'
                       → _finalize_ei_output() 호출
```

### 5.3 Fallback Output 상세

| 출력 | 필드 | 값 | 의미 |
|------|------|-----|------|
| `EventInterpretationOutput` | `events` | `[]` (empty) | 해석된 이벤트 없음 |
| `EventInterpretationOutput` | `summary` | `""` (empty) | 요약 없음 |
| `EventInterpretationOutput` | `confidence` | `0` | 신뢰도 0 |
| `EventInterpretationOutput` | `error_type` | `None` (or "timeout") | 에러 없음 (degraded=False) |
| `AIRiskOutput` | `risk_reject` | `False` | 리스크 거절 아님 |
| `AIRiskOutput` | `summary` | `""` (empty) | 요약 없음 |
| `FinalDecisionComposerOutput` | `decision_type` | `HOLD` | **HOLD 결정** |
| `FinalDecisionComposerOutput` | `reason` | `""` (empty) | 사유 없음 |
| `FinalDecisionComposerOutput` | `suggested_order_type` | `None` | 주문 유형 없음 |

### 5.4 FDC Degraded 상태와의 조합

FDC skip(`_check_fdc_skip`) 시 `interpretation_incomplete=True`, `degraded_reason="fdc_skipped:..."` 설정.

이 degraded 상태와 subprocess timeout fallback 간 우선순위:

1. subprocess 정상 완료 + FDC skip → `interpretation_incomplete=True`, agents_output 정상
2. subprocess timeout → `build_fallback_bundle()`으로 완전 대체, `is_degraded=True`
3. subprocess 정상 + EI/AR timeout (L2) → EI/AR fallback output + FDC 정상 실행 → `is_degraded=True`

**안전성 평가**: 모든 fallback 경로에서 최종 결정은 `HOLD`로 수렴. `_finalize_ei_output()`이 default instance에도 호출되므로 모든 필드가 안전하게 초기화됨. `is_degraded=True`로 상위 계층에 전파되어 fallback 발생 사실을 추적 가능.

### 5.5 잠재적 이슈

- `build_fallback_bundle()`의 [`_finalize_ei_output()`](../src/agent_trading/services/subprocess_helpers.py:208)이 default `EventInterpretationOutput()`에 호출됨 — 이는 빈 events, empty summary에 finalization 로직을 적용하므로 안전하나, finalization이 특정 필드 계산에 events 존재를 가정한다면 edge case 가능. 현재 코드상 events=[], confidence=0에서 `_finalize_ei_output()`은 단순 timestamp 설정 등으로 안전.

---

## 6. 예상 Wall Clock 영향

### 6.1 정상 실행 (No Timeout)

**변화 없음.** timeout이 발생하지 않는 정상 상황에서는 모든 timeout 설정이 단순 safety net 역할만 하므로 execution path에 전혀 영향을 주지 않음.

```
현재: ai_assemble 4.0~15.9s → subprocess timeout 300s (unused) → 완료
조정 후: ai_assemble 4.0~15.9s → subprocess timeout 90s (unused) → 완료
```

### 6.2 장애 상황 (Timeout 발생)

| 시나리오 | 현재 Wall Clock 영향 | 조정 후 Wall Clock 영향 | 개선 |
|---------|-------------------|---------------------|------|
| 1개 symbol subprocess hang | 300s (L3) + 10s (SIGTERM grace) = **310s** 지연 | 90s (L3) + 10s (SIGTERM grace) = **100s** 지연 | **-68%** |
| 여러 symbol 순차 hang | 310s × N | 100s × N | 동일 비율 |
| 1개 symbol outer timeout (L3 실패 시) | 420s (L4) 지연 → symbol fail | 150s (L4) 지연 → symbol fail | **-64%** |
| 1 cycle 전체 blocking | 420s (L4)까지 다른 symbol들도 gather에서 대기 | 150s (L4)까지 대기 | **-64%** |

### 6.3 30-Symbol Cycle Wall Clock 추정

| 조건 | 현재 (300s/420s) | 조정 후 (90s/150s) | 차이 |
|------|----------------|------------------|------|
| 정상 (timeout 0) | ~80s | ~80s | 0 |
| 1개 symbol hang 발생 | ~80s + 310s = **~390s** | ~80s + 100s = **~180s** | **-210s** |
| 2개 symbol 순차 hang | ~80s + 620s = **~700s** | ~80s + 200s = **~280s** | **-420s** |
| 5개 symbol 동시 hang | ~80s + 310s = **~390s** (semaphore) | ~80s + 100s = **~180s** | **-210s** |

> semaphore=5이므로 동시 hang도 sequential 처리됨. 따라서 5개 동시 hang은 5개 sequential과 동일.

### 6.4 Scheduler 수준 영향

[`run_decision_loop.py`](../scripts/run_decision_loop.py)의 `_run_one_cycle()` 내에서 `asyncio.gather()`로 모든 symbol 처리. `PER_AGENT_HARD_TIMEOUT`(현재 420s, 권장 150s)이 각 symbol별로 적용되므로 한 symbol의 장애가 다른 symbol을 무한정 block하지는 않음.

scheduler-level timeout (`decision_submit_gate` timeout, `run_near_real_ops_scheduler.py`에서 설정 — 파일 미존재로 정확한 값 확인 불가)은 별도 계층이므로 본 조정과 독립적으로 검토 필요.

---

## 부록 A: 변경 대상 파일 목록

| 파일 | 변경 내용 | 변경 유형 |
|------|---------|----------|
| [`decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py:186) | `provider_timeout_seconds: int = 120` → `= 60` | L1 httpx timeout 축소 |
| [`decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py:105) | `_PER_AGENT_TIMEOUT = 35` → `= 30` | L2 per-agent timeout 축소 |
| [`decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py:222) | `subprocess_timeout=300` → `= 90` | L3 subprocess timeout 축소 |
| [`decision_agent_runner.py`](../src/agent_trading/services/decision_agent_runner.py:66) | `_PER_AGENT_TIMEOUT = 35` → `= 30` | L2 per-agent timeout 축소 (동기화) |
| [`decision_agent_runner.py`](../src/agent_trading/services/decision_agent_runner.py:84) | `subprocess_timeout: int = 300` → `= 90` | L3 subprocess timeout 기본값 축소 |
| [`run_decision_loop.py`](../scripts/run_decision_loop.py:662) | `PER_AGENT_HARD_TIMEOUT = 420` → `= 150` | L4 outer timeout 축소 |
| [`run_agent_subprocess.py`](../scripts/run_agent_subprocess.py:144) | `provider_timeout_seconds: int = 120` → `= 60` | L1 동기화 (subprocess input dataclass) |

## 부록 B: 구현 우선순위

1. **L3 (subprocess timeout) 300s → 90s**: 가장 큰 효과 예상. 장애 시 회복 시간 70% 단축.
2. **L4 (outer timeout) 420s → 150s**: L3와 함께 조정하여 consistency 유지.
3. **L2 (per-agent) 35s → 30s**: 미세 조정. 장애 탐지 시간 5s 단축.
4. **L1 (httpx) 120s → 60s**: provider 호출 timeout. subprocess 내부 실제 HTTP timeout이므로 과도한 값 조정.

## 부록 C: 측정 데이터 신뢰도

- **1 cycle, 30 symbols** 측정만으로 산출된 통계. P99 추정의 신뢰 구간이 넓음.
- 향후 10+ cycle 측정 데이터가 축적되면 더 정밀한 조정 가능.
- **권장**: 현재 조정안을 적용한 후 1주일간 모니터링하여 추가 조정 필요성 평가.
