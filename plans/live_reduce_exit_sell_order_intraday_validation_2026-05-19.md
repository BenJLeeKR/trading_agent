# Live REDUCE/EXIT Sell Order 장중 실생성 검증 보고서

**검증 일시**: 2026-05-19 (화) 09:31~09:36 KST  
**작성자**: Roo (자동 분석)  
**상태**: ✅ 완료

---

## 1. 검증 대상 개요

### 검증 대상 Symbol
| Symbol | 종목명 | 비고 |
|--------|--------|------|
| `000150` | 두산 | 대표 과보유 종목 |
| `000810` | 삼성화재 | 대표 과보유 종목 |
| `000660` | SK하이닉스 | 대표 과보유 종목 |

### 검증 대상 Decision Type
- `REDUCE` — 전량 20건 (오늘 17건 + 어제 3건)

---

## 2. trade_decisions → order_requests → broker_orders 경로 결과

### 전체 통계 (2026-05-18 ~ 2026-05-19, sell side)

| 항목 | 값 |
|------|-----|
| 전체 REDUCE/EXIT sell trade_decisions | **30건** |
| order_requests 연결됨 | **2건** (6.7%) |
| broker_orders까지 연결됨 | **1건** (3.3%) |
| order_requests 미연결 | **28건** (93.3%) |

### 상세 내역 (최근 30건)

| Symbol | td_created (KST) | order_requests | broker_orders | or_status | broker_status |
|--------|-----------------|:--------------:|:-------------:|-----------|---------------|
| 000810 | 09:33:40 | ❌ | ❌ | N/A | N/A |
| 000660 | 09:33:04 | ❌ | ❌ | N/A | N/A |
| **000150** | **09:32:23** | **✅** | **✅** | **submitted** | **submitted** |
| **000150** | **09:28:12** | **✅** | **❌** | **pending_submit** | **N/A** |
| 000810 | 09:24:03 | ❌ | ❌ | N/A | N/A |
| 000660 | 09:23:38 | ❌ | ❌ | N/A | N/A |
| 000150 | 09:23:08 | ❌ | ❌ | N/A | N/A |
| 000810 | 09:17:41 | ❌ | ❌ | N/A | N/A |
| 000150 | 09:16:40 | ❌ | ❌ | N/A | N/A |
| 000660 | 09:15:46 | ❌ | ❌ | N/A | N/A |
| 000810 | 09:12:39 | ❌ | ❌ | N/A | N/A |
| 000660 | 09:11:58 | ❌ | ❌ | N/A | N/A |
| 000150 | 09:11:33 | ❌ | ❌ | N/A | N/A |
| 000810 | 09:06:24 | ❌ | ❌ | N/A | N/A |
| 000660 | 09:05:02 | ❌ | ❌ | N/A | N/A |
| 000150 | 09:04:49 | ❌ | ❌ | N/A | N/A |
| 000810 | 09:02:17 | ❌ | ❌ | N/A | N/A |
| ... | (이전 데이터) | ❌ | ❌ | N/A | N/A |

### 오늘(2026-05-19) 데이터

| 항목 | 값 |
|------|-----|
| 오늘 sell trade_decisions | **17건** |
| 오늘 order_requests (sell) | **2건** |
| order_requests 연결 성공률 | **11.8%** (2/17) |

---

## 3. decision_submit_gate timeout 분석

### Timeout 이력 (오늘)

| 시작 시간 | 종료 시간 | Duration | Timeout | Return Code |
|-----------|-----------|:--------:|:-------:|:-----------:|
| 08:02:07 | 08:06:11 | 244.05s | ✅ True | 1 |
| 08:04:41 | 08:08:45 | 244.05s | ✅ True | 1 |
| 08:10:04 | 08:14:08 | 244.06s | ✅ True | 1 |
| 08:15:31 | 08:19:35 | 244.06s | ✅ True | 1 |
| 08:21:32 | 08:25:36 | 244.05s | ✅ True | 1 |
| 08:28:02 | 08:32:06 | 244.06s | ✅ True | 1 |
| 08:30:40 | 08:34:44 | 244.06s | ✅ True | 1 |

**모든 decision_submit_gate가 timeout=True로 실패했습니다.**

### Timeout 메커니즘

```
scheduler-level timeout (240s) → subprocess (run_paper_decision_loop)
  └─ PER_AGENT_HARD_TIMEOUT (90s) → asyncio.wait_for() on assemble_and_submit
       └─ LLM API 호출 또는 DB I/O stall → 90초 내 미완료
            └─ asyncio.TimeoutError → os._exit(1) 시도
                 └─ C-level I/O (httpx) blocking → 프로세스 즉시 종료 실패
                      └─ scheduler 240초 timeout → SIGTERM → 종료
```

**핵심 문제**: `PER_AGENT_HARD_TIMEOUT = 90s`이지만, `os._exit(1)`이 C-level I/O blocking으로 인해 즉시生效하지 않아 scheduler-level 240s timeout이 먼저 동작합니다. 실제로는 244s (240s + 4s grace) 후에 종료됩니다.

---

## 4. 대표 과보유 종목 상세 결과

### 000150 (두산) — 부분 성공

| td_created | order_requests | broker_orders | or_status | broker_status |
|-----------|:-------------:|:-------------:|-----------|---------------|
| 09:32:23 | ✅ | ✅ | submitted | submitted |
| 09:28:12 | ✅ | ❌ | pending_submit | N/A |
| 09:23:08 | ❌ | ❌ | N/A | N/A |
| 09:16:40 | ❌ | ❌ | N/A | N/A |
| 09:11:33 | ❌ | ❌ | N/A | N/A |
| 09:04:49 | ❌ | ❌ | N/A | N/A |
| 08:55:46 | ❌ | ❌ | N/A | N/A |
| 08:50:40 | ❌ | ❌ | N/A | N/A |
| ... | ❌ | ❌ | N/A | N/A |

### 000810 (삼성화재) — 전량 실패

| td_created | order_requests | broker_orders |
|-----------|:-------------:|:-------------:|
| 09:33:40 | ❌ | ❌ |
| 09:24:03 | ❌ | ❌ |
| 09:17:41 | ❌ | ❌ |
| 09:12:39 | ❌ | ❌ |
| 09:06:24 | ❌ | ❌ |
| 09:02:17 | ❌ | ❌ |
| (이전 4건) | ❌ | ❌ |

### 000660 (SK하이닉스) — 전량 실패

| td_created | order_requests | broker_orders |
|-----------|:-------------:|:-------------:|
| 09:33:04 | ❌ | ❌ |
| 09:23:38 | ❌ | ❌ |
| 09:15:46 | ❌ | ❌ |
| 09:11:58 | ❌ | ❌ |
| 09:05:02 | ❌ | ❌ |
| (이전 4건) | ❌ | ❌ |

---

## 5. SELL Sizing Fallback 코드 검증

[`decision_orchestrator.py:787-801`](../src/agent_trading/services/decision_orchestrator.py:787)에서 SELL sizing fallback 로직이 존재함을 확인했습니다.

```python
# For SELL/REDUCE/EXIT: fallback to request quantity when sizing returns 0.
effective_qty = sizing_result.quantity
if effective_qty <= 0 and intent.request.side == OrderSide.SELL:
    req_qty = intent.request.quantity
    if req_qty > 0:
        effective_qty = req_qty
        logger.info(
            "Phase 1.5: sizing returned 0 for SELL; "
            "fallback to request quantity=%s (skip_reason=%s)",
            req_qty,
            sizing_result.skip_reason,
        )
```

**그러나 이 fallback 로그가 ops-scheduler 로그에 한 번도 출력되지 않았습니다.** 이는 `assemble_and_submit()`이 sizing 단계 이전(Phase 1 AI assemble)에서 이미 timeout이 발생했거나, LLM API 호출에서 hang이 발생하여 sizing 로직까지 도달하지 못했음을 시사합니다.

---

## 6. 최종 판정

### 판정: **C — 미동작** ❌

**근거**:

1. **30건 중 2건만 order_requests 생성 (6.7%)** — 대다수 sell decision이 order request로 전환되지 않음
2. **모든 decision_submit_gate가 timeout=True로 실패** — 244초 duration으로 일관되게 timeout
3. **000810, 000660은 전량 order_requests 미생성** — 대표 과보유 종목 중 2/3가 완전히 미동작
4. **000150만 2건 성공** (1건은 broker까지 제출) — 유일하게 일부 동작했으나, 이는 특정 조건에서만 우연히 성공한 것으로 보임
5. **SELL sizing fallback 로그 미출력** — sizing fallback 로직이 실행되지 않음 (timeout으로 인해 Phase 1.5 이전에서 중단)

### 근본 원인

`assemble_and_submit()` 내부에서 LLM API 호출(`assemble()` Phase 1)이 90초(`PER_AGENT_HARD_TIMEOUT`) 내에 완료되지 않아 `asyncio.TimeoutError`가 발생합니다. 이후 `os._exit(1)`이 C-level I/O blocking으로 즉시生效하지 않아 scheduler-level 240s timeout까지 지연됩니다.

**즉, sell order 생성 실패의 직접적 원인은 sizing fallback 문제가 아니라, LLM API 호출 단계(Phase 1 AI assemble)의 timeout입니다.**

---

## 7. Follow-up 항목

| # | 항목 | 우선순위 | 설명 |
|---|------|---------|------|
| 1 | **LLM API timeout 진단** | 🔴 긴급 | `assemble()`에서 어떤 LLM API가 hang되는지 식별 필요. httpx read timeout 설정 확인 |
| 2 | **PER_AGENT_HARD_TIMEOUT 증가 검토** | 🟡 보통 | 현재 90s → 180s로 증가하여 정상적인 LLM 응답을 기다릴 시간 확보 |
| 3 | **os._exit(1) 대체 방안** | 🟡 보통 | C-level I/O blocking 우회를 위해 `loop.run_in_executor` 또는 `signal.SIGALRM` 사용 검토 |
| 4 | **scheduler-level timeout 조정** | 🟢 낮음 | `DEFAULT_TASK_TIMEOUT_SECONDS` 240s → 300s로 증가하여 정상 subprocess에 시간 확보 |
| 5 | **000150 성공 사례 분석** | 🟢 낮음 | 000150만 2건 성공한 이유 분석 — 특정 조건(예: position snapshot 존재)에서만 sizing 통과 |
