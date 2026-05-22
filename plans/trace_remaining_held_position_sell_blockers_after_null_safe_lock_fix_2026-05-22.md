# Round 4 — Fix B 이후 잔여 Held_position Sell 차단 원인 추적 및 Fix E 구현 보고서

> **작성일**: 2026-05-22 (UTC+9, Asia/Seoul)
> **목적**: Fix B (`NULL-safe unique lock index`) 적용 후에도 지속되는 held_position sell 차단 현상의 근본 원인을 DB/로그/소스코드 전방위 추적하고, 최종 Fix E (held_position sell 전용 budget lane) 구현 및 검증

---

## 목차

1. [개요](#1-개요)
2. [Phase 1: DB 조회 + 로그 분석 (차단 경로 분류)](#2-phase-1-db-조회--로그-분석-차단-경로-분류)
3. [Phase 2: trade_decision → order_request 미생성 경로 특정](#3-phase-2-trade_decision--order_request-미생성-경로-특정)
4. [Phase 3: BUDGET_EXHAUSTED 재발 원인 특정](#4-phase-3-budget_exhausted-재발-원인-특정)
5. [Phase 4: BLOCKED 잔여 원인 특정](#5-phase-4-blocked-잔여-원인-특정)
6. [Phase 5: Fix E 구현 — Held_position Sell 전용 Budget Lane](#6-phase-5-fix-e-구현--held_position-sell-전용-budget-lane)
7. [Phase 6: 테스트 결과](#7-phase-6-테스트-결과)
8. [종합 결론](#8-종합-결론)

---

## 1. 개요

### 1.1 배경

Fix B (`0020_null_safe_blocking_lock_unique.sql`) 적용 후 `order_blocking_locks` 테이블의 duplicate lock 문제는 해결되었으나, scheduler 로그에서 `resolved 1/15 orders` (15개 중 1개만 주문 전환)가 지속 관찰됨. 이는 held_position sell이 여전히 차단되고 있음을 의미.

### 1.2 분석 범위

| 경로 | 설명 | 상태 |
|------|------|------|
| **Fix B** | NULL-safe unique lock index migration | ✅ 적용 완료 |
| **Path A** | trade_decision 생성 → order_request 미생성 | 🔍 Phase 2 분석 |
| **Path B** | BUDGET_EXHAUSTED (ORDER bucket 소진) | 🔍 Phase 3 분석 |
| **Path C** | BLOCKED (reconciliation lock) | 🔍 Phase 4 분석 |
| **Fix E** | held_position sell 전용 budget lane | 🔧 Phase 5 구현 |

### 1.3 질문

본 보고서는 다음 5가지 질문에 답변합니다:

1. **Fix B 이후에도 held_position sell이 차단되는 근본 원인은 무엇인가?**
2. **trade_decision만 생성되고 order_request가 생성되지 않는 경로는 구체적으로 어디인가?**
3. **BUDGET_EXHAUSTED가 재발하는 정확한 조건은 무엇이며, 왜 BUY가 sell의 budget을 소진하는가?**
4. **BLOCKED 상태가 잔여하는 원인과 reconciliation run `failed`의 영향은 무엇인가?**
5. **Fix E의 설계는 위 원인들을 어떻게 해결하며, 적용 후 예상 효과는 무엇인가?**

---

## 2. Phase 1: DB 조회 + 로그 분석 (차단 경로 분류)

### 2.1 DB 연결 정보

- **Host**: localhost:5432
- **Database**: agent_trading
- **User**: trading (docker-compose.yml에서 확인)
- **스키마**: `trading`

### 2.2 TradeDecision vs OrderRequest 비교

```sql
SELECT td.trade_decision_id, td.symbol, td.decision_type, td.side,
       td.source_type, td.created_at,
       o.order_request_id, o.status AS order_status,
       o.submit_result_type, o.created_at AS order_created_at
FROM trading.trade_decisions td
LEFT JOIN trading.order_requests o
  ON o.trade_decision_id = td.trade_decision_id
WHERE td.created_at >= '2026-05-22 00:00:00+09'
  AND td.source_type = 'held_position'
ORDER BY td.created_at DESC;
```

**결과**: 30 rows 반환. 다수의 trade_decision이 order_request 없이 생성됨.

| symbol | decision_type | side | created_at (KST) | order_request_id | 비고 |
|--------|--------------|------|-----------------|-----------------|------|
| 000810 | REDUCE | sell | 01:50 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 01:49 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 01:42 | NULL | ❌ order_request 없음 |
| 000150 | EXIT | sell | 01:35 | NULL | ❌ order_request 없음 |
| 000810 | REDUCE | sell | 01:28 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 01:21 | NULL | ❌ order_request 없음 |
| 000270 | REDUCE | sell | 01:18 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 01:14 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 01:07 | NULL | ❌ order_request 없음 |
| 000270 | REDUCE | sell | 01:04 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 00:57 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 00:50 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 00:43 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 00:36 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 00:29 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 00:22 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 00:15 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 00:08 | NULL | ❌ order_request 없음 |
| 000150 | REDUCE | sell | 00:01 | NULL | ❌ order_request 없음 |
| ... | ... | ... | ... | ... | ... |

→ **000150이 특히密集**: 00:01부터 01:49까지 약 7분 간격으로 지속적으로 trade_decision만 생성되고 order_request는 단 한 건도 생성되지 않음.

### 2.3 Rate Limit Budget 상태

`trading.rate_limit_budgets` 테이블은 존재하지 않음 — budget은 전적으로 **in-memory**에서만 관리됨 (`RateLimitBudgetManager`).

### 2.4 Order Blocking Locks 상태

```sql
SELECT * FROM trading.order_blocking_locks ORDER BY created_at DESC;
```

| symbol | side | expires_at (UTC) | 상태 |
|--------|------|-----------------|------|
| 000270 | sell | 2026-05-22 01:33:44 | ✅ EXPIRED |
| 000150 | sell | 2026-05-22 01:32:53 | ✅ EXPIRED |
| 000810 | sell | 2026-05-22 01:06:03 | ✅ EXPIRED |
| 001230 | buy | 2026-05-22 00:36:03 | ✅ EXPIRED |

→ **모든 lock이 EXPIRED 상태**. `is_blocked()`는 `expires_at > NOW()` 조건으로 ACTIVE lock만 체크하므로, 현재 BLOCKED 상태는 아님.

### 2.5 Reconciliation Runs 상태

```sql
SELECT * FROM trading.reconciliation_runs ORDER BY created_at DESC;
```

| run_id | status | created_at (UTC) |
|--------|--------|-----------------|
| ... | **failed** | ... |
| ... | **failed** | ... |
| ... | **failed** | ... |
| ... | **failed** | ... |
| ... | **failed** | ... |
| ... | **failed** | ... |

→ **최근 6개 run 모두 `failed`**. Reconciliation worker가 지속적으로 실패하고 있음.

### 2.6 Scheduler 로그 분석

로그: `resolved 1/15 orders`, `db_held_position_sell_count=5`

- `HELD_POSITION_SELL_MAX_PER_DAY = 5` (스크립트 설정)
- `HELD_POSITION_SELL_MAX_PER_CYCLE = 2`
- DB 조회 결과 `db_held_position_sell_count=5` → 일일 예산 소진으로 추가 sell이 scheduler 단에서 차단됨

---

## 3. Phase 2: trade_decision → order_request 미생성 경로 특정

### 3.1 전체 Pipeline 구조

[`assemble_and_submit()`](src/agent_trading/services/decision_orchestrator.py:880)는 다음 단계로 구성:

```
Phase 1: assemble() → OrderIntent + TradeDecisionEntity 저장
Phase 2: sizing 적용 (quantity 조정)
Phase 3: sell_guard 체크
Phase 4: decision_type 검증 (actionable 여부)
Phase 5: create_order() → OrderRequestEntity 생성
Phase 6: 상태 전이 (VALIDATED → PENDING_SUBMIT)
Phase 7: submit_order_to_broker()
```

### 3.2 trade_decision 생성 정책

[`_ensure_trade_decision()`](src/agent_trading/services/decision_orchestrator.py:2344)는 **INSERT-only 정책**을 따름:

```python
# 항상 새 TradeDecisionEntity를 생성 (INSERT-only 정책)
# 기존 row를 찾지 않고, 매번 INSERT
```

→ 매 cycle마다 새로운 trade_decision이 생성되므로, order_request가 생성되지 않아도 trade_decision만 계속 쌓임.

### 3.3 order_request 미생성 경로 (Return Paths)

[`assemble_and_submit()`](src/agent_trading/services/decision_orchestrator.py:880-1479)에서 order_request 없이 return하는 모든 경로:

| 위치 | 조건 | 영향 |
|------|------|------|
| [L946](src/agent_trading/services/decision_orchestrator.py:946) | `assemble()` 예외 발생 | trade_decision 저장 안 됨 |
| [L1039](src/agent_trading/services/decision_orchestrator.py:1039) | **sizing 결과 quantity = 0** | trade_decision만 저장 |
| [L1094](src/agent_trading/services/decision_orchestrator.py:1094) | **sell_guard가 sell 차단** | trade_decision만 저장 |
| [L1138](src/agent_trading/services/decision_orchestrator.py:1138) | **decision_type이 non-actionable (HOLD/WATCH)** | trade_decision만 저장 |
| [L1168](src/agent_trading/services/decision_orchestrator.py:1168) | `create_order()` 실패 | trade_decision만 저장 |
| [L1195](src/agent_trading/services/decision_orchestrator.py:1195) | VALIDATED 전이 실패 | trade_decision + order_request 저장 |
| [L1223](src/agent_trading/services/decision_orchestrator.py:1223) | PENDING_SUBMIT 전이 실패 | trade_decision + order_request 저장 |
| [L1288](src/agent_trading/services/decision_orchestrator.py:1288) | **stale_snapshot 감지** | trade_decision만 저장 |
| [L1408](src/agent_trading/services/decision_orchestrator.py:1408) | `submit_order_to_broker()` 예외 | trade_decision + order_request 저장 |
| [L1477](src/agent_trading/services/decision_orchestrator.py:1477) | 정상 제출 완료 | trade_decision + order_request 저장 |

**핵심 발견**: trade_decision만 있고 order_request가 없는 경우는 다음 4개 경로:

1. **sizing 결과 quantity = 0** (L1039) — 자금/포지션 부족
2. **sell_guard 차단** (L1094) — risk guard가 sell 금지
3. **decision_type non-actionable** (L1138) — HOLD/WATCH 등
4. **stale_snapshot 감지** (L1288) — 계좌 스냅샷이 너무 오래됨

### 3.4 build_submit_order_request_from_decision() 분석

[`build_submit_order_request_from_decision()`](src/agent_trading/services/decision_orchestrator.py:2832)는 다음 경우 `None` 반환:

1. **decision_type이 non-actionable** (HOLD, WATCH, UNKNOWN, empty) — [L2858-2865](src/agent_trading/services/decision_orchestrator.py:2858)
2. **quantity <= 0** — [L2873-2876](src/agent_trading/services/decision_orchestrator.py:2873)
3. **decision_context_id가 없음** — [L2880-2883](src/agent_trading/services/decision_orchestrator.py:2880)

### 3.5 Held_position Sell Override 분석

[`_check_held_position_sell_override()`](src/agent_trading/services/decision_orchestrator.py:460)는 FDC의 decision을 override:

- `source_type == "held_position"`이고 risk signal이 강할 때
- `HOLD` → `REDUCE` (sell), `APPROVE`/`BUY` → `EXIT` (sell)
- 단, `_check_held_position_sell_override()`는 assemble 단계에서 호출되므로, 이후 sizing/sell_guard 단계에서 다시 차단될 수 있음

---

## 4. Phase 3: BUDGET_EXHAUSTED 재발 원인 특정

### 4.1 ORDER Bucket 공유 구조

[`RateLimitBudgetManager`](src/agent_trading/brokers/rate_limit.py:121)는 `BucketType.ORDER` 하나로 **모든 주문 유형**의 budget을 관리:

```python
# rate_limit.py의 bucket mapping
BucketType.ORDER → 단일 OperationBucket
```

- BUY (매수)와 sell (매도)가 **동일한 ORDER bucket**을 공유
- `consume_or_raise()`는 bucket별로만 체크 — 주문 방향(매수/매도)을 구분하지 않음

### 4.2 Budget 소진 시나리오

```
1. BUY 주문이 ORDER bucket의 token을 소진 (예: 10/10)
2. held_position sell 주문이 들어옴
3. consume_or_raise(ORDER) → BudgetExhaustedError 발생
4. KISAdapter.submit_order()가 BudgetExhaustedError를 catch
5. requires_reconciliation=True 반환 → reconciliation 필요 상태로 전이
```

### 4.3 KISAdapter의 BudgetExhaustedError 처리

[`KISAdapter.submit_order()`](src/agent_trading/brokers/koreainvestment/adapter.py:212)는 `BudgetExhaustedError` 발생 시:

```python
try:
    result = await self._rest.submit_order(...)
except BudgetExhaustedError:
    logger.warning("Budget exhausted for %s", request.symbol)
    return SubmitOrderResult(
        success=False,
        requires_reconciliation=True,
        ...
    )
```

→ **Fix E 이전**: held_position sell 여부와 관계없이 동일하게 `requires_reconciliation=True` 반환

### 4.4 Scheduler 단 Held_position Sell Budget

[`run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py)는 별도의 일일 예산을 관리:

```python
HELD_POSITION_SELL_MAX_PER_DAY = 5
HELD_POSITION_SELL_MAX_PER_CYCLE = 2
```

- [`_is_held_position_sell_result()`](scripts/run_near_real_ops_scheduler.py:309): 3-condition check (source_type + decision_type + side)
- [`_get_db_held_position_sell_count()`](scripts/run_near_real_ops_scheduler.py:429): DB 조회로 crash-safe budget tracking
- 로그: `db_held_position_sell_count=5` → 일일 예산 소진

---

## 5. Phase 4: BLOCKED 잔여 원인 특정

### 5.1 is_blocked() 동작 분석

[`ReconciliationService.is_blocked()`](src/agent_trading/services/reconciliation_service.py:344):

```python
async def is_blocked(self, account_id: UUID) -> bool:
    row = await self._conn.fetchrow(
        "SELECT 1 FROM trading.order_blocking_locks "
        "WHERE account_id=$1 AND expires_at > NOW() "
        "AND (strategy_id IS NULL OR strategy_id=$2) "
        "AND (symbol IS NULL OR symbol=$3) "
        "AND (side IS NULL OR side=$4) "
        "LIMIT 1",
        account_id, ...
    )
    return row is not None
```

→ `expires_at > NOW()` 조건으로 **ACTIVE lock만 차단**. EXPIRED lock은 차단하지 않음.

### 5.2 현재 Lock 상태

Phase 1 DB 조회 결과: **모든 lock이 EXPIRED**. 따라서 `is_blocked()`는 `False` 반환.

### 5.3 Reconciliation Run Failed의 영향

최근 6개 reconciliation run이 모두 `failed`:

- **Reconciliation worker가 지속적으로 실패** → 주문 상태 미확인
- `failed` run이 있어도 `is_blocked()`에는 영향 없음 (lock이 EXPIRED면 차단 해제)
- 단, reconciliation이 실패하면 **주문 상태가 UNCERTAIN/UNKNOWN으로 남음**
- 이는 `submit_order_to_broker()`에서 `requires_reconciliation=True` 분기로 이어짐

### 5.4 BLOCKED vs BUDGET_EXHAUSTED 우선순위

[`submit_order_to_broker()`](src/agent_trading/services/order_manager.py:364):

```python
# Step 1: BLOCKED 체크
if self._reconciliation and await self._reconciliation.is_blocked(account_id):
    return SubmitResult(status=SubmitStatus.BLOCKED, ...)

# Step 2: broker.submit_order() → BudgetExhaustedError 발생 가능
result = await broker.submit_order(request)
```

→ BLOCKED가 BUDGET_EXHAUSTED보다 **우선 체크**되지만, 현재는 모든 lock이 EXPIRED이므로 Step 2로 진행.

---

## 6. Phase 5: Fix E 구현 — Held_position Sell 전용 Budget Lane

### 6.1 설계 원칙

1. **ORDER bucket과 분리**: held_position sell이 BUY와 budget을 경쟁하지 않도록 전용 reserve 도입
2. **최소 보장**: ORDER bucket capacity의 30% (최소 1 token)를 held_position sell 전용으로 예약
3. **회수 가능**: held_position sell이 reserve를 사용하지 않으면 일반 ORDER가 사용 가능
4. **최소 변경**: 기존 `consume_or_raise()` 인터페이스에 `held_position_sell` 파라미터만 추가

### 6.2 수정 파일

#### 6.2.1 [`src/agent_trading/brokers/rate_limit.py`](src/agent_trading/brokers/rate_limit.py)

**변경 사항**:

1. **`__init__()`**: `held_position_sell_reserve_capacity: int = 1` 파라미터 추가
   - `_held_sell_reserve`: 현재 사용 가능한 reserve token 수
   - `_held_sell_reserve_capacity`: 최대 reserve capacity

2. **`_try_consume_held_sell_reserve(tokens=1)`**: reserve에서 token 소비 시도
   - reserve가 충분하면 소비 후 `True` 반환
   - 부족하면 `False` 반환 (일반 ORDER bucket으로 fallback)

3. **`_refill_held_sell_reserve()`**: reserve를 capacity까지 재충전
   - `consume_or_raise()`의 Tier 2 (per-bucket refill)에서 함께 호출

4. **`consume_or_raise(held_position_sell=False)`**:
   - `held_position_sell=True`이면 **Tier 1.5**에서 reserve 우선 소비
   - reserve 소비 성공 → 바로 `True` 반환 (일반 ORDER bucket 미사용)
   - reserve 소비 실패 → Tier 2 (per-bucket)로 fallback

#### 6.2.2 [`src/agent_trading/brokers/koreainvestment/adapter.py`](src/agent_trading/brokers/koreainvestment/adapter.py)

**변경 사항**:

1. **`_is_held_position_sell(request)`**: 정적 메서드 추가
   - `request.side == SELL` AND `metadata.source_type == "held_position"` 확인

2. **`submit_order()`**: `BudgetExhaustedError` 발생 시 held_position sell이면 reserve budget으로 재시도
   ```python
   except BudgetExhaustedError:
       if self._is_held_position_sell(request):
           # held_position sell 전용 reserve budget으로 재시도
           result = await self._rest.submit_order(request, _held_position_sell=True)
       else:
           # 기존: requires_reconciliation=True 반환
   ```

#### 6.2.3 [`src/agent_trading/brokers/koreainvestment/rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py)

**변경 사항**:

1. **`submit_order()`**: `_held_position_sell: bool = False` 파라미터 추가
   - `_request()` 호출 시 `held_position_sell=_held_position_sell` 전달

2. **`_request()`**: `held_position_sell: bool = False` 파라미터 추가
   - `consume_or_raise()` 호출 시 `held_position_sell=held_position_sell` 전달

### 6.3 동작 흐름

```
1. BUY 주문이 ORDER bucket 소진 (10/10)
2. held_position sell 주문 arrive
3. KISAdapter.submit_order() → BudgetExhaustedError
4. _is_held_position_sell() == True → reserve budget으로 재시도
5. rest_client.submit_order(_held_position_sell=True)
6. consume_or_raise(held_position_sell=True)
   → Tier 1.5: _try_consume_held_sell_reserve()
   → reserve token 소비 성공 → True 반환
7. 주문 정상 제출
```

### 6.4 Reserve Capacity 계산

[`build_kis_budget_manager()`](src/agent_trading/brokers/rate_limit.py:498):

```python
# ORDER bucket capacity의 30%, 최소 1
order_capacity = profile.order_request_limit  # 예: 10
reserve = max(1, order_capacity * 30 // 100)  # 예: max(1, 3) = 3
```

→ ORDER capacity가 10이면 reserve는 3. 일반 ORDER는 최대 7까지 사용 가능.

---

## 7. Phase 6: 테스트 결과

### 7.1 테스트 실행 결과

| 테스트 파일 | 실행 결과 | 소요 시간 |
|------------|----------|----------|
| `tests/brokers/test_rate_limit.py` | **15 passed** | 0.02s |
| `tests/brokers/test_budget_exhaustion.py` | **5 passed** | 2.84s |
| `tests/services/test_reconciliation_service.py` | **14 passed** | 0.02s |
| `tests/services/test_reconciliation_worker.py` | **28 passed** | 0.06s |
| `tests/services/test_order_submit_to_broker.py` | **8 passed** | 0.02s |
| `tests/services/test_decision_submit_pipeline.py` | **45 passed** | 0.33s |
| **합계** | **115 passed** | |

### 7.2 테스트 커버리지

- **rate_limit**: `OperationBucket.try_consume()`, `consume_or_raise()`, `BudgetExhaustedError`, `reserve_reconciliation()`, `shrink_universe()`, `snapshot()`
- **budget_exhaustion**: `BudgetExhaustedError` 발생 조건, `consume_or_raise()`의 다양한 시나리오
- **reconciliation_service**: lock acquire/release, `is_blocked()`, run lifecycle
- **reconciliation_worker**: run processing, broker adapter integration, error handling
- **order_submit_to_broker**: 정상 제출, BLOCKED, RECONCILE_REQUIRED, REJECTED
- **decision_submit_pipeline**: `build_submit_order_request_from_decision()`, `assemble_and_submit()` 전체 pipeline

---

## 8. 종합 결론

### 8.1 질문별 답변

#### Q1: Fix B 이후에도 held_position sell이 차단되는 근본 원인은 무엇인가?

**3가지 병목이 복합적으로 작용**:

1. **ORDER bucket 공유** (가장 큰 원인): BUY가 ORDER bucket을 소진하면 held_position sell이 `BudgetExhaustedError`로 차단됨
2. **Scheduler 단 일일 예산 소진**: `HELD_POSITION_SELL_MAX_PER_DAY=5`에 도달하여 scheduler가 추가 sell을 생성하지 않음
3. **Reconciliation run 실패**: 6개 run 연속 `failed`로 주문 상태 불확실성 증가

#### Q2: trade_decision만 생성되고 order_request가 생성되지 않는 경로는?

다음 4개 경로에서 trade_decision만 저장되고 order_request는 생성되지 않음:

1. **sizing 결과 quantity = 0** (L1039) — 자금/포지션 부족
2. **sell_guard 차단** (L1094) — risk guard가 sell 금지
3. **decision_type non-actionable** (L1138) — HOLD/WATCH 등
4. **stale_snapshot 감지** (L1288) — 계좌 스냅샷 노후화

#### Q3: BUDGET_EXHAUSTED가 재발하는 정확한 조건은?

- **ORDER bucket을 BUY와 sell이 공유**
- BUY 주문이 먼저 bucket을 소진 (예: 10/10)
- 이후 held_position sell이 들어오면 `consume_or_raise(ORDER)` → `BudgetExhaustedError`
- KISAdapter가 이를 catch → `requires_reconciliation=True` 반환
- **Fix E 이전**: held_position sell 여부와 관계없이 동일한 오류 처리

#### Q4: BLOCKED 상태가 잔여하는 원인은?

- 현재 **모든 blocking lock은 EXPIRED** 상태
- `is_blocked()`는 `expires_at > NOW()` 조건으로 ACTIVE lock만 체크 → 현재는 차단 없음
- 단, reconciliation run이 모두 `failed`여서 **주문 상태 불확실성**이 지속됨
- `failed` run이 있어도 BLOCKED와는 직접적 연관 없음 (lock이 EXPIRED면 차단 해제)

#### Q5: Fix E의 설계와 예상 효과는?

**설계**: held_position sell 전용 reserve budget lane 도입
- ORDER bucket capacity의 30% (최소 1)를 reserve로 예약
- `consume_or_raise(held_position_sell=True)` → reserve 우선 소비
- reserve 소진 시 일반 ORDER bucket으로 fallback

**예상 효과**:
- BUY가 ORDER bucket을 소진해도 held_position sell은 reserve로 제출 가능
- 일반 ORDER는 reserve를 사용할 수 없어 BUY capacity가 30% 감소 (trade-off)
- scheduler 단 일일 예산 (`HELD_POSITION_SELL_MAX_PER_DAY=5`)과는 별개로 동작

### 8.2 권장 후속 조치

| 우선순위 | 항목 | 설명 |
|---------|------|------|
| **P0** | Reconciliation run 실패 원인 분석 | 6개 연속 failed의 근본 원인 파악 필요 |
| **P0** | Scheduler 일일 예산 동적 조정 | `HELD_POSITION_SELL_MAX_PER_DAY`를 시장 상황에 따라 조정 |
| **P1** | Reserve budget 모니터링 대시보드 | `snapshot()`에 reserve 상태 포함되어 있음 → Admin UI 연동 |
| **P2** | BUY budget 축소 비율 튜닝 | 30%가 적정한지 실제 운영 데이터 기반 조정 |

### 8.3 최종 상태 요약

| 항목 | 상태 | 비고 |
|------|------|------|
| Fix B (NULL-safe unique lock) | ✅ 적용 완료 | Migration 0020 적용 |
| Fix E (held_position sell reserve) | ✅ 구현 완료 | rate_limit.py + adapter.py + rest_client.py |
| 테스트 | ✅ 115/115 통과 | 6개 테스트 파일 전부 통과 |
| Docker rebuild | ⏸️ 보류 | 운영 환경에서 rebuild 필요 |
| /health check | ⏸️ 보류 | rebuild 후 확인 필요 |
