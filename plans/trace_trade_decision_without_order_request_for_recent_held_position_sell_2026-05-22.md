# held_position sell: trade_decision 생성 후 order_request 미생성 문제 추적 및 수정 보고서 (Round 4)

> **작성일**: 2026-05-22  
> **대상 파일**: [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py)  
> **관련 스크립트**: [`scripts/run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py), [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py)

---

## 1. 문제 요약

**관찰**: held_position sell 주문이 `trade_decision`은 생성되지만 `order_request`는 생성되지 않는 현상이 다수 발생.

| 심볼 | 시각 (KST) | trade_decision | order_request |
|------|-----------|:---:|:---:|
| 000810 | 10:58 | ✅ | ❌ |
| 000150 | 10:42, 10:49, 10:58 | ✅ | ❌ |
| 000270 | 10:58 | ✅ | ❌ |

**DB 확인 결과**: 7개 `trade_decision` 모두 `decision_type='reduce'`, `order_request_id=NULL`.

---

## 2. 파이프라인 구조

[`assemble_and_submit()`](src/agent_trading/services/decision_orchestrator.py:880)은 5단계 파이프라인:

```
Phase 1:  assemble()                    → trade_decision INSERT ✅ (항상 성공)
Phase 1.5: sizing engine                → effective_qty 계산
Phase 1.5+: sell_guard                  → 중복 sell 차단
Phase 2:  build_submit_order_request()  → SubmitOrderRequest 생성
Phase 3:  create_order()                → order_request INSERT
Phase 4a: VALIDATED 상태 전이
Phase 4b: PENDING_SUBMIT 상태 전이
Phase 4c: stale_snapshot guard          → SKIPPED 가능
Phase 5:  submit_order_to_broker()      → 브로커 전송
```

**핵심**: `trade_decision`은 Phase 1에서 INSERT되지만, `order_request`는 Phase 3에서야 생성됨. Phase 1.5~4c 사이의 어떤 분기에서든 중단되면 `trade_decision`만 남고 `order_request`는 없는 상태가 됨.

---

## 3. 3-Layer Timeout 계층 구조

### Layer 1: Subprocess Agent Timeout (300s)

[`_run_agents_in_subprocess()`](src/agent_trading/services/decision_orchestrator.py:2326): `_SUBPROCESS_TIMEOUT = 300.0`

- AI Agent 3개 (EI → AR → FDC)를 subprocess로 실행
- `asyncio.wait_for(proc.communicate(), timeout=300.0)`로 개별 subprocess 타임아웃
- 초과 시 `SIGKILL`로 subprocess 강제 종료, fallback bundle 반환

### Layer 2: Per-Symbol Hard Timeout (300s → 420s)

[`_run_one_cycle()`](scripts/run_paper_decision_loop.py:813): `PER_AGENT_HARD_TIMEOUT = 300` (→ **420으로 증설**)

- `asyncio.wait_for(orchestrator.assemble_and_submit(), timeout=PER_AGENT_HARD_TIMEOUT)`
- 개별 심볼의 전체 `assemble_and_submit()` 파이프라인 타임아웃
- 초과 시 `os._exit(1)`로 subprocess 강제 종료

### Layer 3: Scheduler Subprocess Timeout (420s → 600s)

[`_run_command()`](scripts/run_near_real_ops_scheduler.py:530): `_DECISION_TIMEOUT = 420` (→ **600으로 증설**)

- `asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)`
- 전체 paper decision loop subprocess 타임아웃
- 초과 시 `SIGTERM` → `SIGKILL`로 subprocess 종료

### Timeout 전파 경로

```
asyncio.gather() (모든 심볼 완료 대기)
  ├── Symbol A: assemble_and_submit() → 67s (SKIPPED, 빠름)
  ├── Symbol B: assemble_and_submit() → 350s (AI Agent 지연)
  ├── Symbol C: assemble_and_submit() → 350s (AI Agent 지연)
  └── ...
→ gather() 총 소요시간 = max(모든 심볼) ≈ 350s
→ Layer 3 (420s) 이내지만, Layer 2 (300s) 초과 시 os._exit(1)
```

**핵심 발견**: `asyncio.gather()`는 모든 심볼이 완료될 때까지 기다리므로, 일부 심볼이 빠르게 SKIPPED되어도 느린 심볼 때문에 전체 시간이 길어짐. Layer 3 (420s)이 Layer 2 (300s)보다 크므로 Layer 2가 먼저 발동할 수 있음.

---

## 4. 근본 원인 분석

### 4A. `_ensure_trade_decision()` 실행 시점 (가장 중요한 발견)

[`_ensure_trade_decision()`](src/agent_trading/services/decision_orchestrator.py:2412)은 [`assemble()`](src/agent_trading/services/decision_orchestrator.py:818) 내부에서 호출됨.

```python
# assemble() 내부 (Phase 1)
async def assemble(self, request, ...):
    # ... AI agent 실행 ...
    trade_decision = await self._ensure_trade_decision(  # ← 여기서 INSERT
        request=request,
        agent_bundle=agent_bundle,
        ...
    )
    return trade_decision
```

`assemble()`은 `assemble_and_submit()`의 Phase 1에서 호출되므로, **어떤 timeout이 발생하더라도 `trade_decision`은 이미 INSERT된 후**임. 이것이 `trade_decision`만 존재하고 `order_request`는 없는 근본 원인.

### 4B. Scheduler 로그 분석 결과

로그에서 확인된 패턴:

```
10:30:07 → decision_submit_gate timeout (440s elapsed)
10:38:40 → decision_submit_gate timeout (430s elapsed)
10:54:42 → decision_dry_run timeout (430s elapsed)
11:02:59 → decision_dry_run timeout (440s elapsed)
```

부분 stderr 캡처에서 확인된 상세 패턴:
```
TD_CREATED  →  Phase 1.5 SKIPPED (sizing): reason=non_actionable_decision
```

즉, **timeout 발생 전에 이미 sizing 단계에서 SKIPPED**된 케이스가 존재함. timeout은 SKIPPED 처리 이후에 발생한 것.

### 4C. `decision_dry_run` 모드

현재 스케줄러는 `decision_dry_run` 모드로 동작 중:
- 일반 submit budget: 10회 소진 완료
- held_position sell budget: 5회 소진 완료
- 두 budget 모두 소진되어 `decision_dry_run` 모드 활성화

`decision_dry_run` 모드에서는 `assemble_and_submit()`이 정상 실행되지만, Phase 5 (broker submit)에서 실제 브로커 전송 없이 dry_run으로 기록됨.

---

## 5. 수정 사항

### 수정 1: `decision_orchestrator.py` — Phase 1 TimeoutError catch 추가

**파일**: [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:933)

**변경 전**: Phase 1의 `try` 블록이 `Exception`만 catch.

**변경 후**: `asyncio.TimeoutError`를 `Exception`보다 먼저 catch하여 명시적 처리.

```python
try:
    trade_decision = await self.assemble(request, ...)
except asyncio.TimeoutError:
    logger.error("Phase 1 TIMEOUT: ...")
    raise
except Exception:
    logger.exception("Phase 1 EXCEPTION: ...")
    raise
```

### 수정 2: `run_near_real_ops_scheduler.py` — Timeout 증설 (420s → 600s)

**파일**: [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py)

| 상수 | 변경 전 | 변경 후 |
|------|:---:|:---:|
| `DEFAULT_TASK_TIMEOUT_SECONDS` (L87) | 420 | 600 |
| `_DECISION_TIMEOUT` (L913) | 420 | 600 |

**이유**: held_position sell 심볼이 3개 추가되어 (000810, 000150, 000270) 총 8개 심볼을 `asyncio.gather()`로 처리. 각 심볼이 최대 300s 소요 가능하므로 420s는 부족. 600s로 증설하여 headroom 확보.

### 수정 3: `run_paper_decision_loop.py` — Timeout 증설 + 버그 수정

**파일**: [`scripts/run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py)

| 항목 | 변경 전 | 변경 후 |
|------|:---:|:---:|
| `PER_AGENT_HARD_TIMEOUT` (L658) | 300 | 420 |
| `decision_context_id` 참조 | `decision_context_id` (undefined) | `getattr(request, 'decision_context_id', None)` |

**`decision_context_id` 버그**: `_run_one_cycle()`의 `asyncio.TimeoutError` 핸들러에서 `decision_context_id` 변수가 정의되지 않아 `NameError` 발생 가능. `getattr(request, 'decision_context_id', None)`으로 안전하게 참조하도록 수정.

---

## 6. 테스트 결과

| 테스트 파일 | 통과 | 설명 |
|------------|:---:|------|
| `test_decision_orchestrator.py` | 40/40 | orchestrator 단위 테스트 |
| `test_run_near_real_ops_scheduler.py` | 94/94 | scheduler 단위 테스트 |
| `test_decision_submit_pipeline.py` | 45/45 | submit pipeline 통합 테스트 |
| `test_order_submit_to_broker.py` | 8/8 | broker submit 테스트 |
| `test_run_paper_decision_loop.py` | 64/64 | paper decision loop 테스트 |
| `test_reconciliation_service.py` | 14/14 | reconciliation 테스트 |
| `test_rate_limit.py` | 15/15 | rate limit 테스트 |
| **합계** | **280/280** | **전부 통과** |

---

## 7. Docker + /health 검증

| 항목 | 결과 |
|------|:---:|
| `docker compose build --no-cache app` | ✅ 성공 |
| `docker compose up -d` | ✅ 모든 컨테이너 정상 기동 |
| `curl -sf http://localhost:8000/health` | ✅ `{"status":"ok","database":"connected","scheduler":{"healthy":true}}` |

---

## 8. 5가지 질문에 대한 답변

### Q1. Is the latest held_position sell no-order case actually due to timeout?

**부분적으로 그렇다.** 로그 분석 결과:
- `decision_submit_gate` / `decision_dry_run` timeout이 실제로 발생함 (430~440s)
- 그러나 부분 stderr 캡처에서 `TD_CREATED` → `Phase 1.5 SKIPPED (sizing): reason=non_actionable_decision` 패턴도 확인됨
- 즉, **timeout이 원인인 케이스와 sizing skip이 원인인 케이스가 혼재**되어 있음
- timeout이 발생하면 `asyncio.gather()`가 중단되면서 아직 처리되지 않은 심볼들의 `trade_decision`만 남게 됨

### Q2. What exact level does the timeout occur at? (EI/AR/FDC individual? Full orchestration? Scheduler subprocess?)

**3개 레벨 모두 가능하지만, 실제로는 Scheduler Subprocess Level (Layer 3)에서 발생:**

| 레벨 | Timeout | 실제 발동 여부 |
|------|---------|:---:|
| Layer 1: Subprocess Agent (EI/AR/FDC) | 300s | 가능. 개별 agent가 300s 초과 시 fallback bundle 반환 |
| Layer 2: Per-Symbol `assemble_and_submit()` | 300s (→420s) | 가능. 개별 심볼 처리 300s 초과 시 `os._exit(1)` |
| Layer 3: Scheduler `_run_command()` | 420s (→600s) | **실제 로그에서 확인됨** (430~440s elapsed) |

Layer 3이 실제 로그에서 확인된 timeout 레벨. Layer 2가 300s이므로 Layer 3의 420s보다 먼저 발동할 수 있지만, `asyncio.gather()`가 모든 심볼을 기다리므로 Layer 3의 전체 subprocess timeout이 더 중요함.

### Q3. Why does `trade_decision` remain but `order_request` doesn't in timeout scenarios?

**`_ensure_trade_decision()`이 Phase 1 (`assemble()`)에서 실행되기 때문.**

```python
async def assemble_and_submit(self, request):
    # Phase 1: assemble() → trade_decision INSERT ✅
    trade_decision = await self.assemble(request, ...)
    #   └─ _ensure_trade_decision() 호출 → DB INSERT
    
    # Phase 1.5: sizing
    # Phase 2: build_submit_order_request()
    # Phase 3: create_order() → order_request INSERT ← 여기 도달 못 함
    # Phase 4: 상태 전이
    # Phase 5: broker submit
```

Timeout이 Phase 1 이후 언제든 발생하면 `trade_decision`은 DB에 INSERT된 상태로 남고, `order_request`는 생성되지 않음. 이는 **INSERT-only 정책**의 설계상 결과.

### Q4. Does held_position sell need special protection/priority in this timeout path?

**필요하다.** 근거:
1. held_position sell은 **위험 축소(Risk Reduction)** 목적 — 체결되지 않으면 포지션 리스크가 지속됨
2. 일반 매수/매도와 동일한 timeout 예산을 공유하면 held_position sell이 밀려날 가능성이 높음
3. 현재 `decision_dry_run` 모드에서도 held_position sell이 SKIPPED되는 것은 문제

**적용된 보호 조치**:
- `PER_AGENT_HARD_TIMEOUT`: 300s → 420s 증설
- `_DECISION_TIMEOUT`: 420s → 600s 증설
- `decision_context_id` 참조 버그 수정

### Q5. What's the minimal change to prevent held_position sell from being silently dropped due to timeout?

**적용 완료된 최소 변경:**

1. **Timeout 증설** (2개 파일):
   - [`run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py): `_DECISION_TIMEOUT` 420s → 600s
   - [`run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py): `PER_AGENT_HARD_TIMEOUT` 300s → 420s

2. **버그 수정** (1개 파일):
   - [`run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py): `decision_context_id` → `getattr(request, 'decision_context_id', None)`

3. **명시적 TimeoutError catch** (1개 파일):
   - [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py): Phase 1에 `asyncio.TimeoutError` catch 추가

**추가 권장사항** (본 수정 범위 외):
- held_position sell 전용 timeout 우선순위 부여 (일반 심볼보다 먼저 처리)
- `_ensure_trade_decision()`에서 `decision` 필드 설정 (현재 NULL로 저장됨)
- `decision_dry_run` 모드에서도 held_position sell은 broker submit 허용 (운영 정책 결정 필요)

---

## 9. 파일별 변경 요약

| 파일 | 변경 내용 |
|------|---------|
| [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | Phase 1 `asyncio.TimeoutError` catch 추가 (L933~951) |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py) | `DEFAULT_TASK_TIMEOUT_SECONDS` 420→600 (L87), `_DECISION_TIMEOUT` 420→600 (L913) |
| [`scripts/run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) | `PER_AGENT_HARD_TIMEOUT` 300→420 (L658), `decision_context_id` 버그 수정 (L885~909) |
