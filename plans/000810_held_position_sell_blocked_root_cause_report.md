# 000810 (삼성화재) Held_Position Sell 반복 차단 근본 원인 분석 보고서

> **분석 일시**: 2026-05-22 09:59 KST  
> **대상**: Samsung Fire & Marine Insurance (000810)  
> **증상**: held_position sell/exit 결정이 3회 연속 생성되었으나 모두 broker 제출 전 차단됨

---

## 1. BUDGET_EXHAUSTED 근본 원인

### 1.1 최초 시도 (09:36 KST) — `order_request_id: d373f41f`

| 단계 | 상태 | 설명 |
|------|------|------|
| `trade_decision` 생성 | `source_type=held_position`, `decision_type=reduce`, `side=sell` | concentration_breach 로 인한 비중 축소 결정 |
| `order_request` 생성 | `status=draft` | `create_order()` 통과 (budget_manager.can_accept_new_entries 통과) |
| `draft → validated` | 정상 전이 | |
| `validated → pending_submit` | 정상 전이 | |
| `submit_order_to_broker()` 호출 | **Step 1: lock check 통과** (최초라 lock 없음) | |
| `KoreaInvestmentAdapter.submit_order()` → `KISRestClient.submit_order()` | **ORDER bucket exhausted → `BudgetExhaustedError` 발생** | |
| `requires_reconciliation=True` 반환 | `raw_code="BUDGET_EXHAUSTED"` | |
| `pending_submit → reconcile_required` | `reason_code="BUDGET_EXHAUSTED"` | |
| `_transition_to_core()` 자동 reconciliation 트리거 | `reason_code != "BLOCKED"` 이므로 실행 | |

### 1.2 ORDER Bucket 고갈 원인

[`RateLimitBudgetManager`](src/agent_trading/brokers/rate_limit.py:242)의 `consume_or_raise()`에서 `BudgetExhaustedError` 발생:

- **Paper 환경**: ORDER bucket `capacity=1`, `refill_rate=0.1 tokens/sec` (10초에 1토큰)
- 단일 ORDER 토큰이 이미 선행 주문(다른 종목)에 의해 소진된 상태
- 000810 sell 시도 시점에 ORDER bucket이 비어 있었음
- **`broker_capacity`와 `broker_api_call_log`는 in-memory 상태로 DB에 저장되지 않아 정확한 선행 주문 확인 불가**

> **결론**: Paper 환경의 ORDER bucket capacity=1 구조에서, 000810 sell 이전에 다른 주문이 ORDER 토큰을 소진하여 `BudgetExhaustedError` 발생.

---

## 2. Reconciliation Lock 구조 및 차단 메커니즘

### 2.1 Lock 생성

[`ReconciliationService.trigger()`](src/agent_trading/services/reconciliation_service.py:116)가 호출되면서 [`acquire_blocking_lock()`](src/agent_trading/services/reconciliation_service.py:187) 실행:

```sql
INSERT INTO trading.order_blocking_locks (account_id, strategy_id, symbol, side, ...)
VALUES ('a44a02d1-...', NULL, '000810', 'sell', ...)
ON CONFLICT (account_id, strategy_id, symbol, side) DO NOTHING
```

**실제 lock 데이터**:

| 필드 | 값 |
|------|-----|
| `lock_id` | `81b9e986-5c2f-471c-93e7-026a969ee32f` |
| `account_id` | `a44a02d1-7f32-5a62-99f7-235abeb58284` |
| `strategy_id` | `null` |
| `symbol` | `000810` |
| `side` | `sell` |
| `reason` | `reconciliation:requires_reconciliation` |
| `locked_by_run_id` | `ed177eba-...` (reconciliation_run) |
| `locked_at` | `2026-05-22T00:36:03.116Z` (09:36 KST) |
| `expires_at` | `2026-05-22T01:06:03.116Z` (10:06 KST) |

### 2.2 Lock 범위

- **Composite key**: `(account_id, strategy_id, symbol, side)`
- `strategy_id = null` 이므로, 동일 account + symbol=000810 + side=sell 에 대해 **모든 strategy**가 차단됨
- **TTL**: 30분 (09:36 → 10:06 KST)

### 2.3 Lock 판정 로직

[`is_blocked()`](src/agent_trading/services/reconciliation_service.py:301)는 다음 조건으로 조회:

```sql
SELECT 1 FROM trading.order_blocking_locks
WHERE account_id = $1
  AND expires_at > NOW()
  AND (strategy_id IS NULL OR strategy_id = $2)
  AND (symbol IS NULL OR symbol = $3)
  AND (side IS NULL OR side = $4)
```

→ `strategy_id=null` 이므로 모든 strategy 매치, `symbol='000810'`, `side='sell'` 이므로 정확히 매치

---

## 3. 체인별 차단 구조

### 3.1 1차 시도 (09:36 KST) — `d373f41f`

```
trade_decision (held_position, reduce, sell)
  → create_order (draft)
    → validated
      → pending_submit
        → submit_order_to_broker()
          → [Step 1] is_blocked()? → False (lock 없음)
            → [Step 2] broker.submit_order()
              → KISRestClient.submit_order()
                → ORDER bucket exhausted!
                  → BudgetExhaustedError
                    → requires_reconciliation=True, raw_code="BUDGET_EXHAUSTED"
                      → reconcile_required (reason_code="BUDGET_EXHAUSTED")
                        → _transition_to_core() → trigger_and_link()
                          → reconciliation_run 생성 (ed177eba)
                            → acquire_blocking_lock() → LOCK 획득 (09:36~10:06)
```

### 3.2 2차 시도 (09:44 KST) — `b08194c0`

```
trade_decision (held_position, reduce, sell)
  → create_order (draft)
    → validated
      → pending_submit
        → submit_order_to_broker()
          → [Step 1] is_blocked()? → TRUE! (lock active, expires 10:06)
            → reconcile_required (reason_code="BLOCKED")
              → _transition_to_core() → reason_code=="BLOCKED" → SKIP auto-trigger
```

### 3.3 3차 시도 (09:53 KST) — `5b12fd42`

```
동일 패턴 → is_blocked()? → TRUE → reconcile_required (reason_code="BLOCKED")
```

### 3.4 상태 전이 요약

| 시도 | 시간 | Order ID | 최종 상태 | Reason Code | Broker 제출 여부 |
|------|------|----------|-----------|-------------|----------------|
| 1차 | 09:36 | `d373f41f` | `reconcile_required` | `BUDGET_EXHAUSTED` | ❌ (budget 소진) |
| 2차 | 09:44 | `b08194c0` | `reconcile_required` | `BLOCKED` | ❌ (lock 차단) |
| 3차 | 09:53 | `5b12fd42` | `reconcile_required` | `BLOCKED` | ❌ (lock 차단) |

---

## 4. Held_Position Sell 정책 평가

### 4.1 Scheduler Budget (정상 작동 중)

[`run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:858)의 `_run_intraday_due_tasks()`:

- `HELD_POSITION_SELL_MAX_PER_DAY=5` — 000810에 대해 3회 시도 모두 scheduler budget 내에서 정상 submit 모드로 실행됨
- `_BUDGET_CONSUMING_STATUSES`에 `reconcile_required`가 **포함되지 않음** → scheduler budget은 소진되지 않음
- **Scheduler 레벨의 held_position sell 정책은 문제 없음**

### 4.2 Broker-level ORDER Bucket (근본 원인)

- Paper 환경 ORDER bucket `capacity=1`은 **단일 주문만 허용**
- 000810 sell 이전에 다른 주문이 ORDER 토큰을 소진
- ORDER bucket은 **모든 종목/전략 공유** — 특정 종목의 sell이 다른 종목의 buy에 의해 차단될 수 있음
- `refill_rate=0.1/sec` 이므로 10초마다 1회 주문 가능하나, scheduler loop 주기(~8분)보다 훨씬 짧아 refill은 문제 아님

### 4.3 Reconciliation Lock (2차/3차 차단 원인)

- 1차 시도의 BUDGET_EXHAUSTED가 reconciliation을 트리거하고 lock을 생성
- Lock TTL=30분 동안 모든 후속 000810 sell 시도 차단
- Reconciliation run은 `status=failed`로 종료되었으나 **lock은 해제되지 않음** (`mark_resolved()`가 호출되지 않음)
- **Lock이 해제되지 않는 것이 핵심 문제** — reconciliation이 실패했지만 lock cleanup 로직 부재

---

## 5. 권장 개선 방향

### 5.1 즉시 조치 가능

1. **Reconciliation 실패 시 Lock 자동 해제**
   - [`reconciliation_service.py`](src/agent_trading/services/reconciliation_service.py:460)의 `mark_resolved()`를 reconciliation 실패 시에도 호출
   - 또는 `trigger()`에서 reconciliation run 실패 감지 시 lock TTL 단축

2. **BLOCKED → Reconciliation 재시도 연계**
   - [`order_manager.py`](src/agent_trading/services/order_manager.py:714)에서 `reason_code="BLOCKED"`인 경우에도 reconciliation 재시도 허용 (단, rate-limited)
   - 현재는 `reason_code != "BLOCKED"` 조건으로 auto-trigger를 skip → lock이 해제될 때까지 영구 대기

### 5.2 중기 개선

3. **ORDER Bucket Capacity 증가 (Paper)**
   - [`rate_limit.py`](src/agent_trading/brokers/rate_limit.py:176)의 paper env ORDER capacity를 1→3~5로 증가
   - 또는 held_position sell에 별도 ORDER bucket 할당

4. **Lock Scope 세분화**
   - 현재 `strategy_id=null`로 lock이 모든 strategy에 적용됨
   - strategy_id를 명시적으로 설정하여 lock 범위 축소

5. **Held_position Sell Bypass 로직**
   - held_position sell(risk management 목적)의 경우 reconciliation lock을 우회할 수 있는 옵션 추가
   - 단, 이는 정합성 위험이 있으므로 신중한 설계 필요

### 5.3 모니터링 개선

6. **Lock 상태 가시화**
   - Admin UI에 현재 활성 lock과 잔여 TTL 표시
   - Lock으로 인해 BLOCKED된 order 수 대시보드 추가

7. **Budget Exhaustion Alert**
   - ORDER bucket exhaustion 발생 시 즉시 알림
   - 연속 BLOCKED 발생 시 escalation

---

## 부록: DB 조회 결과

### order_requests (000810, 2026-05-22)

| order_request_id | status | reason_code | created_at (KST) |
|---|---|---|---|
| `d373f41f` | `reconcile_required` | `BUDGET_EXHAUSTED` | 09:36 |
| `b08194c0` | `reconcile_required` | `BLOCKED` | 09:44 |
| `5b12fd42` | `reconcile_required` | `BLOCKED` | 09:53 |

### order_state_events (상태 전이)

| order_id | 이전 상태 | 새 상태 | reason_code | 시간 |
|----------|---------|---------|-------------|------|
| `d373f41f` | draft | validated | - | 09:36 |
| `d373f41f` | validated | pending_submit | - | 09:36 |
| `d373f41f` | pending_submit | reconcile_required | **BUDGET_EXHAUSTED** | 09:36 |
| `b08194c0` | pending_submit | reconcile_required | **BLOCKED** | 09:44 |
| `5b12fd42` | pending_submit | reconcile_required | **BLOCKED** | 09:53 |

### order_blocking_locks (활성 lock)

| lock_id | symbol | side | locked_at | expires_at | locked_by_run_id |
|---------|--------|------|-----------|------------|-----------------|
| `81b9e986` | **000810** | **sell** | **09:36** | **10:06** | `ed177eba` |

### reconciliation_runs

| run_id | trigger_type | status | started_at |
|--------|-------------|--------|-----------|
| `ed177eba` | `requires_reconciliation` | **failed** | 09:36 |

### trade_decisions (000810, 2026-05-22)

| trade_decision_id | source_type | decision_type | side | created_at (KST) |
|---|---|---|---|---|
| `f2c7d69f` | held_position | reduce | sell | 08:52 (전일 장후) |
| `3cdf083b` | core | hold | buy | 09:04 |
| `9c2ccf17` | **held_position** | **exit** | **sell** | **09:12** |
| `546a1523` | held_position | reduce | sell | 09:19 |
| `58178529` | held_position | reduce | sell | 09:27 |
| `dd5b391e` | **held_position** | **reduce** | **sell** | **09:36** ← 1차 시도 |
| `ede3ee2e` | **held_position** | **reduce** | **sell** | **09:44** ← 2차 시도 |
| `2932aee1` | **held_position** | **reduce** | **sell** | **09:53** ← 3차 시도 |
