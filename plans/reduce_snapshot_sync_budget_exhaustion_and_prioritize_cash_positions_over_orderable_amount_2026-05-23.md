# Snapshot-sync Budget Exhaustion 분석 및 최적화 방안

> 분석일: 2026-05-23
> 대상: snapshot-sync 1회 사이클의 budget 소비 패턴 및 최적화

---

## 1. Budget Consumption Map

### 1.1 호출 순서도

snapshot-sync 1회 사이클(`sync_kis_account_snapshots()` 또는 `KISSyncSnapshotProvider.fetch_snapshot()`)에서 **1개 계좌**에 대해 발생하는 KIS REST API 호출과 budget 소비:

```
[snapshot-sync cycle]                [RateLimitBudgetManager]          [KIS REST API]
       |                                     |                              |
       | === Phase 1: Cash Balance ===       |                              |
       |-- consume_or_raise(INQUIRY) ------->|                              |
       |   + global_rest 1 token             |                              |
       |<-- OK ------------------------------|                              |
       |-- GET inquire-balance (VTTC8434R) -->|                             |
       |<-- output2 (cash summary) -----------|                             |
       |                                     |                              |
       | asyncio.sleep(1.0) ← Paper 1 RPS    |                              |
       |                                     |                              |
       | === Phase 1b: Orderable Cash ===    |                              |
       |-- consume_or_raise(INQUIRY) ------->|                              |
       |   + global_rest 1 token             |                              |
       |<-- OK (or BudgetExhaustedError) ----|                              |
       |-- GET inquire-psbl-order (VTTC8908R) |                             |
       |<-- ord_psbl_cash -------------------|                              |
       |                                     |                              |
       | === Phase 2: Positions ===          |                              |
       |-- consume_or_raise(INQUIRY) ------->|                              |
       |   + global_rest 1 token             |                              |
       |<-- OK (or BudgetExhaustedError) ----|                              |
       |-- GET inquire-balance (VTTC8434R) -->|                             |
       |<-- output (positions array) ---------|                             |
```

### 1.2 Budget 소비 테이블 (1계좌 기준)

| 순서 | 호출 함수 | KIS TR ID | Bucket | Global REST 소비 | Inquiry 소비 |
|------|-----------|-----------|--------|-----------------|-------------|
| 1 | [`get_cash_balance()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1246) | VTTC8434R (inquire-balance) | `INQUIRY` | 1 token | 1 token |
| 2 | [`get_orderable_cash()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1300) | VTTC8908R (inquire-psbl-order) | `INQUIRY` | 1 token | 1 token |
| 3 | [`get_positions()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1206) | VTTC8434R (inquire-balance) | `INQUIRY` | 1 token | 1 token |
| **합계** | | | | **3 tokens** | **3 tokens** |

### 1.3 계좌 수에 따른 총 소비

| 계좌 수 | Global REST 소비 | Inquiry 소비 |
|---------|-----------------|-------------|
| 1 | 3 | 3 |
| 2 | 6 | 6 |
| 3 | 9 | 9 |
| 4 | 12 | 12 |
| 5 | 15 | 15 |

### 1.4 Budget 설정값 (Paper 환경)

[`build_kis_budget_manager()`](src/agent_trading/brokers/rate_limit.py:498) 기준 (paper, total=1 RPS):

| Bucket | Capacity | Refill Rate | 초당 회복 |
|--------|----------|-------------|----------|
| **global_rest** | 1 | 1.0/s | 1 token/s |
| **INQUIRY** | 1 | 0.5/s | 0.5 token/s |
| ORDER | 3 | 0.1/s | 0.1 token/s |
| RECONCILIATION | 10 | 1.0/s | 1.0 token/s |
| MARKET_DATA | 1 | 0.5/s | 0.5 token/s |
| AUTH | 1 | 0.017/s | 0.017 token/s |

**Paper 환경의 핵심 제약:**
- `global_rest` capacity=1, refill=1.0/s → **초당 1회** REST 호출 가능
- `INQUIRY` capacity=1, refill=0.5/s → **2초에 1회** inquiry 가능
- [`FileBackedGlobalBucket`](src/agent_trading/brokers/shared_budget.py:18) 사용 시 프로세스 간에도 1 RPS 공유

### 1.5 문제 분석

**관찰된 로그 패턴:**
```
Failed to fetch orderable cash via VTTC8908R
BudgetExhaustedError: [inquiry] Bucket 'inquiry' exhausted (remaining=0/1)
Positions inquiry budget exhausted: [global] Global REST cap exhausted (remaining=0/1)
```

**원인:** 1개 계좌에 대해 3회의 INQUIRY 호출이 필요하지만, paper 환경의 INQUIRY bucket은 capacity=1, refill=0.5/s로 **2초에 1회만 허용**. 따라서:

1. [`get_cash_balance()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1246) → INQUIRY 소진 (remaining=0/1)
2. [`get_orderable_cash()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1300) → **BudgetExhaustedError** (inquiry exhausted)
3. [`get_positions()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1206) → **BudgetExhaustedError** (inquiry exhausted) → fallback으로 global_rest도 소진 시도하지만 이미 소진

**결과:** cash만 성공, orderable_cash와 positions는 budget 부족으로 partial 종료

---

## 2. Orderable Cash (VTTC8908R) 분석

### 2.1 Budget 소비 여부

[`get_orderable_cash()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1344-1350)는 `bucket=BucketType.INQUIRY`로 호출되므로:
- **global_rest 1 token 소비** (Tier 1)
- **INQUIRY 1 token 소비** (Tier 2)

즉, inquiry budget과 global REST cap을 모두 소모한다.

### 2.2 필수성 분석

**VTTC8908R이 필요한 이유:**
- [`get_cash_balance()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1246) (VTTC8434R)는 paper 환경에서 `ord_psbl_cash` 필드를 반환하지 않음 (항상 "0" 또는 누락)
- `orderable_amount`는 submit gate에서 매수 가능 금액 판단에 사용됨
- `orderable_amount=None`이면 submit gate가 보수적으로 동작 (매수 차단 가능)

**VTTC8908R이 불필요한 조건:**
- `after_hours=True` 모드에서는 cash-only sync이므로 orderable_amount가 필요 없음
- 이미 `available_cash`(dnca_tot_amt)로 충분한 경우 (예: 현금 잔고가 매우 낮아 orderable_amount가 의미 없는 상황)
- `fetch_positions=False` 모드에서도 여전히 호출됨 (cash+orderable 우선 확보 목적)

### 2.3 Fallback 경로

현재 fallback 구조 ([`kis_snapshot_sync.py:273-316`](src/agent_trading/services/kis_snapshot_sync.py:273)):

```
VTTC8908R 성공 → orderable_amount = ord_psbl_cash (정확)
VTTC8908R BudgetExhaustedError → available_cash (dnca_tot_amt)로 fallback
VTTC8908R 일반 Exception → available_cash (dnca_tot_amt)로 fallback
VTTC8908R 실패 + available_cash도 없음 → VTTC8434R output2.ord_psbl_amt fallback
```

**중요:** BudgetExhaustedError 발생 시 `available_cash`로 fallback하지만, 이 값은 이미 [`get_cash_balance()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1246)에서 확보한 값이다. 즉, **VTTC8908R이 실패해도 cash balance snapshot은 정상 저장**된다.

---

## 3. Positions Priority 분석

### 3.1 Budget 소비

[`get_positions()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1233-1239)는 `bucket=BucketType.INQUIRY`로 호출:
- **global_rest 1 token 소비**
- **INQUIRY 1 token 소비**

### 3.2 우선순위 분석

**현재 우선순위 (코드 순서):**
1. [`get_cash_balance()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1246) (VTTC8434R) — **가장 중요**
2. [`get_orderable_cash()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1300) (VTTC8908R) — **두 번째**
3. [`get_positions()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1206) (VTTC8434R) — **세 번째**

**올바른 우선순위 판단:**

| 데이터 | 중요도 | 이유 |
|--------|--------|------|
| **cash_balance** | 🔴 최우선 | submit gate가 매수 가능 여부 판단. stale cash = submit block |
| **positions** | 🟠 중요 | 보유 포지션 파악, zero-out, 매도 가능 수량 판단 |
| **orderable_amount** | 🟡 낮음 | available_cash fallback 가능. submit gate에서 추가 정밀도 제공 |

**결론:** [`orderable_amount`](src/agent_trading/brokers/koreainvestment/rest_client.py:1300)(VTTC8908R)는 `available_cash`로 대체 가능하므로, budget이 부족한 상황에서는 **positions보다 우선순위가 낮아야 한다.**

### 3.3 Positions 실패 시 영향

- `fetch_status`가 설정되지 않음 (기본값 없음) → snapshot 레코드는 생성되지 않음
- zero-out 로직은 `had_actual_positions` 또는 `had_cash_response`가 True면 실행됨
- cash는 성공했으므로 `had_cash_response=True` → zero-out은 실행됨
- **단점:** zero-out은 이전 snapshot 기준으로만 동작하므로, 신규 매수한 포지션이 반영되지 않음

---

## 4. 최적화 권장사항

### 4.1 호출 순서 변경 (Priority 1)

**현재:** cash → orderable_cash → positions
**제안:** cash → positions → orderable_cash (조건부)

```
[Start Cycle] → [get_cash_balance]
                     ↓
              {INQUIRY budget > 0?}
              /        \
             Yes       No
              ↓         ↓
        [get_positions] [Skip positions]
              ↓         |
        {INQUIRY budget > 0?}
              /        \
             Yes       No
              ↓         ↓
   [get_orderable_cash] [Fallback: available_cash]
              ↓         |
           [Complete] ←─┘
```

**효과:** budget이 1회분만 남아도 positions는 확보 가능. orderable_cash는 fallback 가능.

### 4.2 Orderable Cash 조건부 호출 (Priority 2)

VTTC8908R 호출 전에 budget을 확인하고, budget이 부족하면 바로 fallback:

```python
# 제안: budget 사전 확인 후 조건부 호출
if budget_manager is not None:
    inquiry_remaining = budget_manager.inquiry.remaining
    global_remaining = budget_manager.global_rest.remaining if budget_manager.global_rest else 1
    if inquiry_remaining < 1 or global_remaining < 1:
        logger.info("Budget insufficient for VTTC8908R — using available_cash fallback")
        orderable_cash = available_cash
    else:
        # 정상 호출
        orderable_cash = await rest_client.get_orderable_cash(...)
```

**효과:** BudgetExhaustedError 예외 발생을 피하고, 불필요한 예외 로그를 제거.

### 4.3 fetch_positions=False 모드에서 orderable_cash 생략 (Priority 3)

[`fetch_positions=False`](src/agent_trading/services/kis_snapshot_sync.py:183) 모드는 cash+orderable만 확보하는 목적이지만, orderable_cash가 항상 필요한 것은 아님:

- `after_hours=True`에서는 orderable_cash 불필요 (장 마감 후 매수 불가)
- cash-only sync 목적이라면 VTTC8908R 생략 가능

### 4.4 Paper 환경 INQUIRY Capacity 증가 검토 (Priority 4)

현재 paper 환경 INQUIRY capacity=1, refill=0.5/s는 너무 보수적:

| 항목 | 현재 | 제안 |
|------|------|------|
| INQUIRY capacity | 1 | 3 |
| INQUIRY refill_rate | 0.5/s | 1.0/s |
| global_rest capacity | 1 | 1 (변경 없음) |

단, global_rest capacity=1은 유지하여 **초당 1회 REST 호출** 제약은 그대로 둠. INQUIRY capacity만 증가시켜 burst 허용.

### 4.5 계좌별 Budget 소비 최적화 (Priority 5)

현재 N개 계좌에 대해 순차적으로 3N회 호출. 계좌가 많을수록 budget 부족 심화.

**제안:** 모든 계좌의 cash_balance를 먼저 확보한 후, 남은 budget으로 positions를 순차 처리:

```
Cycle 1: 모든 계좌 cash_balance (N회 호출)
Cycle 2: 남은 budget으로 positions (최대한 많은 계좌)
Cycle 3: 남은 budget으로 orderable_cash (최대한 많은 계좌)
```

---

## 5. 구현 계획

### Priority 1: 호출 순서 변경

**변경 파일:** [`src/agent_trading/services/kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py) 및 [`src/agent_trading/brokers/koreainvestment/snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py)

**변경 내용:**
1. [`get_cash_balance()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1246) 호출 (변경 없음)
2. [`get_positions()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1206) 호출 (orderable_cash보다 먼저)
3. [`get_orderable_cash()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1300) 호출 (budget 확인 후 조건부)

**리스크:** VTTC8908R 실패 시 `available_cash`로 fallback하므로 orderable_amount 정확도가 떨어질 수 있음. 단, 이미 동일한 fallback이 구현되어 있음.

### Priority 2: Budget 사전 확인 로직 추가

**변경 파일:** [`src/agent_trading/services/kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py)

**변경 내용:**
- `rest_client.budget_manager` 접근하여 `inquiry.remaining`과 `global_rest.remaining` 확인
- budget 부족 시 예외 발생 없이 바로 fallback

**리스크:** budget_manager가 None일 수 있음 (테스트 환경). None-safe 처리 필요.

### Priority 3: after-hours 모드에서 VTTC8908R 생략

**변경 파일:** [`src/agent_trading/brokers/koreainvestment/snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py)

**변경 내용:**
- `after_hours=True`이면 VTTC8908R 호출 건너뛰고 `available_cash` 사용

**리스크:** after-hours에도 orderable_amount가 필요한 경우가 있다면 생략 불가. 현재 after-hours는 cash-only sync 목적이므로 영향 없음.

### Priority 4: Paper INQUIRY Capacity 조정

**변경 파일:** [`src/agent_trading/brokers/rate_limit.py`](src/agent_trading/brokers/rate_limit.py)

**변경 내용:**
- [`build_kis_budget_manager()`](src/agent_trading/brokers/rate_limit.py:498)에서 paper 환경 INQUIRY capacity=1 → 3, refill_rate=0.5 → 1.0

**리스크:** KIS paper 환경의 실제 RPS 제한(1 RPS)을 초과할 수 있음. 단, global_rest capacity=1이 상위 제한으로 작동하므로 안전.

### Priority 5: 계좌별 Budget 분배 최적화

**변경 파일:** [`src/agent_trading/services/kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py)

**변경 내용:**
- [`sync_kis_accounts_by_ids()`](src/agent_trading/services/kis_snapshot_sync.py:488)에서 계좌 목록을 순회하기 전에 budget 상태 확인
- budget이 부족하면 cash-only 모드로 fallback

**리스크:** 구현 복잡도 증가. 현재 단일 계좌 운영에서는 불필요.

---

## 6. 요약

| 항목 | 현재 상태 | 문제점 | 권장 조치 |
|------|----------|--------|----------|
| 호출 순서 | cash → orderable → positions | orderable이 positions보다 우선 | cash → positions → orderable (조건부) |
| VTTC8908R | 항상 호출, 실패 시 fallback | budget 부족 시 예외 발생 | budget 사전 확인 후 조건부 호출 |
| after-hours | VTTC8908R 계속 호출 | 불필요한 budget 소비 | after-hours에서 생략 |
| INQUIRY capacity (paper) | 1 | 3회 연속 호출 불가 | 3으로 증가 (global_rest는 유지) |
| 계좌 수 증가 | 선형 budget 소비 | 다계좌에서 budget 부족 심화 | cash 우선, positions/orderable은 남은 budget으로 |

### 핵심 결론

**가장 효과적인 단일 변경:** 호출 순서를 `cash → positions → orderable_cash`로 변경하고, VTTC8908R 호출 전 budget을 사전 확인하여 조건부로 호출하는 것. 이 변경만으로도 budget이 1회분만 남은 상황에서 positions까지 확보할 수 있다.

---

## 7. Implementation Design

> 설계일: 2026-05-23
> 대상 파일: [`rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py), [`snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py), [`kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py)
> **P4 (INQUIRY capacity 증가)는 이번 턴 제외** — 구조 최적화 효과를 먼저 검증

### 7.1 변경 대상 코드 경로

현재 **2개의 독립적인 snapshot fetch 경로**가 존재:

| 경로 | 파일 | 함수 | 사용처 |
|------|------|------|--------|
| **Old (legacy)** | [`kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py):176 | `sync_kis_account_snapshots()` | `sync_kis_accounts_by_ids()`, scripts |
| **New** | [`snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py):66 | `KISSyncSnapshotProvider.fetch_snapshot()` | `snapshot_sync.py` runner |

두 경로 모두 동일한 문제(cash → orderable_cash → positions)를 가지고 있으므로, **두 경로 모두 변경 필요**.

---

### 7.2 P1: 호출 순서 변경 (cash → positions → orderable_cash)

#### 7.2.1 [`snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py) — `fetch_snapshot()`

**현재 (line 117-253):**
```
1. get_cash_balance()         # line 118
2. asyncio.sleep(1.0)         # line 165 (Paper 1 RPS pacing)
3. get_orderable_cash()       # line 168 (VTTC8908R)
4. get_positions()            # line 243 (after_hours 체크 있음)
```

**변경 후:**
```
1. get_cash_balance()         # 변경 없음
2. asyncio.sleep(1.0)         # cash → positions 사이 1 RPS pacing
3. get_positions()            # positions를 orderable_cash 보다 먼저
4. asyncio.sleep(1.0)         # positions → orderable_cash 사이 1 RPS pacing
5. get_orderable_cash()       # 조건부 (budget 사전 확인)
```

**상세 변경:**

(a) positions 호출을 after_hours 체크 직후로 이동 (현재 line 232-253에서 242-253):
```python
# 변경 후: cash 다음 positions (after_hours 체크는 유지)
if after_hours:
    logger.info("After-hours mode — skipping positions fetch cash-only sync")
    raw_positions = []
elif not fetch_positions:
    logger.info("fetch_positions=False — skipping positions fetch ...")
    raw_positions = []
else:
    await asyncio.sleep(1.0)  # Paper 1 RPS pacing (cash → positions)
    try:
        raw_positions = await self._rest.get_positions()
    except BudgetExhaustedError as exc:
        ...
```

(b) orderable_cash 호출을 positions 이후로 이동:
```python
# 변경 후: positions 다음 orderable_cash (조건부)
if after_hours:
    logger.info("After-hours mode — skipping orderable_cash fetch")
    orderable_amount = available_cash  # 또는 None
elif not _has_budget_for_inquiry(self._rest):
    logger.warning("Budget insufficient for VTTC8908R — using available_cash fallback")
    orderable_amount = available_cash
else:
    await asyncio.sleep(1.0)  # Paper 1 RPS pacing (positions → orderable_cash)
    try:
        orderable_cash = await self._rest.get_orderable_cash(account_ref="")
    except BudgetExhaustedError:
        ...
```

#### 7.2.2 [`kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py) — `sync_kis_account_snapshots()`

**현재 (line 229-370):**
```
1. get_cash_balance()         # line 230
2. asyncio.sleep(1.0)         # line 271
3. get_orderable_cash()       # line 274 (VTTC8908R)
4. get_positions()            # line 360
```

**변경 후:**
```
1. get_cash_balance()         # 변경 없음
2. asyncio.sleep(1.0)         # cash → positions 사이 1 RPS pacing
3. get_positions()            # positions를 orderable_cash 보다 먼저
4. asyncio.sleep(1.0)         # positions → orderable_cash 사이 1 RPS pacing
5. get_orderable_cash()       # 조건부 (budget 사전 확인)
```

**구체적 변경:**

(a) positions 블록을 orderable_cash 블록보다 앞으로 이동 (line 358-368를 line 271 앞으로)

(b) orderable_cash 블록을 positions 이후로 이동하고 budget 사전 확인 추가

---

### 7.3 P2: Budget 사전 확인 + 조건부 fallback

#### 7.3.1 공통 helper 함수 추가

**신규 함수** — [`snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py) 또는 공통 유틸:

```python
def _has_budget_for_inquiry(rest_client: KISRestClient) -> bool:
    """VTTC8908R 호출 전 budget 사전 확인.
    
    BudgetExhaustedError 발생을 피하기 위해 inquiry + global_rest budget을
    사전 확인한다. budget_manager가 None이면 True 반환 (테스트 호환성).
    """
    mgr = rest_client.budget_manager
    if mgr is None:
        return True  # budget 관리 미적용 환경 (테스트 등)
    
    # inquiry bucket 확인
    mgr.inquiry._refill()  # refill 우선 적용
    if mgr.inquiry.remaining < 1:
        return False
    
    # global_rest bucket 확인 (FileBackedGlobalBucket 포함)
    if mgr.global_rest is not None:
        # FileBackedGlobalBucket.remaining은 best-effort
        if mgr.global_rest.remaining < 1:
            return False
    
    return True
```

> **참고:** `OperationBucket._refill()`은 public 메서드이므로 직접 호출 가능.
> `FileBackedGlobalBucket.remaining`은 flock-protected file에서 읽은 근사값이지만,
> budget이 명확히 0인 경우를 감지하는 용도로 충분.

#### 7.3.2 [`rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py) — `get_orderable_cash()`

**변경 사항:**
`fallback_cash` 파라미터 추가. budget 부족 시 API 호출 없이 fallback 반환.

```python
async def get_orderable_cash(
    self,
    account_ref: str = "",
    symbol: str = "",
    price: str = "",
    order_type: str = "00",
    fallback_cash: Decimal | None = None,  # NEW
) -> Decimal | None:
    # Budget 사전 확인 (BudgetExhaustedError 방지)
    if not _has_budget_for_inquiry(self):
        logger.warning(
            "Inquiry budget insufficient for VTTC8908R; "
            "using fallback_cash=%s",
            fallback_cash,
        )
        return fallback_cash
    
    # 기존 로직 (변경 없음)
    try:
        ...
```

> **설계 결정:** P2 로직을 `rest_client.py`의 `get_orderable_cash()`에 구현하면
> 두 호출 경로(snapshot.py + kis_snapshot_sync.py)가 모두 혜택을 받음.
> 단, `_has_budget_for_inquiry` helper는 공유 필요.

#### 7.3.3 Budget 소비 비교 (변경 전/후)

**변경 전** — 1계좌 기준, budget 1회분만 남은 상황:

| 순서 | 호출 | Budget | 결과 |
|------|------|--------|------|
| 1 | get_cash_balance | 1 → 0 | 성공 |
| 2 | get_orderable_cash | 0 | **BudgetExhaustedError** → fallback |
| 3 | get_positions | 0 | **BudgetExhaustedError** → 실패 |

**변경 후** — 동일 상황:

| 순서 | 호출 | Budget | 결과 |
|------|------|--------|------|
| 1 | get_cash_balance | 1 → 0 | 성공 |
| 2 | get_positions | 사전 확인 → budget 부족 | **실패** (순서 변경으로 인해) |
| ... | ... | ... | ... |

Wait — 이 경우 budget이 1회만 있으면 cash_balance 소진 후 positions도 실패한다.
**올바른 분석:**

변경 후에도 3회의 budget이 모두 필요한 것은 동일.
**핵심 개선점은 budget이 정확히 1회 남았을 때**:

**변경 전** (budget 1회 남음, 이미 cash 소진):
| 순서 | 호출 | Budget | 결과 |
|------|------|--------|------|
| 1 | get_cash_balance | 이미 소진됨 | cash 없음 → 전체 실패 |

**변경 후** (budget 1회 남음, cash 이미 소진):
| 순서 | 호출 | Budget | 결과 |
|------|------|--------|------|
| 1 | get_cash_balance | 1 → 0 | 성공 |
| 2 | get_positions | 사전 확인 → budget 부족 | **fallback 없음 → 실패** |
| 3 | get_orderable_cash | 사전 확인 → budget 부족 | **fallback: available_cash** |

**즉, 가장 중요한 변경은:**
1. **호출 순서 변경만으로는 budget 1회 상황에서 positions를 구할 수 없음** (cash가 먼저 소모하므로)
2. **진정한 개선은 P2(budget 사전 확인) + P4(capacity 증가)의 조합**

**올바른 최적화 효과:**

| 시나리오 | 변경 전 | 변경 후 | 개선 |
|----------|---------|---------|------|
| Budget 충분 (3회) | cash + orderable + positions 전부 성공 | 동일 | 동일 |
| Budget 2회 | cash + orderable 성공, positions 실패 | **cash + positions 성공**, orderable fallback | positions 확보 |
| Budget 1회 | cash 성공, orderable/positions 실패 | cash 성공, positions 실패, **orderable fallback** | cash + fallback orderable |
| Budget 0회 | 전부 실패 | 전부 실패 | 동일 |

**핵심 개선:** Budget이 2회 남은 상황에서 **positions가 orderable_cash보다 우선**되어
positions 데이터를 확보할 수 있게 됨. orderable_cash는 available_cash로 fallback 가능.

---

### 7.4 P3: After-hours에서 VTTC8908R 생략

#### 7.4.0 after-hours orderable_cash skip 조건 (명확화)

```
after_hours=True → VTTC8908R(inquire-psbl-order) 완전 생략
이유: 장 마감 후(15:30 KST 이후)에는 매수 주문이 불가능하므로
orderable_amount(orderable_cash)가 의미 없음.
cash balance(dnca_tot_amt)만으로 충분.
```

이 조건은 두 가지 코드 경로 모두에 적용된다:
- [`snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py) — `after_hours` 파라미터 이미 존재
- [`kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py) — `after_hours` 파라미터 **신규 추가**

#### 7.4.1 [`snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py)

`after_hours=True` 컨텍스트에서는 이미 positions를 생략하고 있음 (line 232-234).
orderable_cash도 동일하게 생략. after-hours일 때는 asyncio.sleep도 생략 (API 호출 없음):

```python
# 변경 후: positions 다음 orderable_cash (조건부)
# after-hours skip: 장 마감 후 매수 주문 불가 → orderable_amount 불필요
if after_hours:
    logger.info(
        "AFTER_HOURS_SKIP account=%s — skipping VTTC8908R; "
        "after-hours mode, orderable_amount not needed",
        account_id,
    )
    orderable_amount = None  # after-hours: orderable_amount 불필요
elif not _has_budget_for_inquiry(self._rest):
    logger.warning(
        "BUDGET_FALLBACK account=%s — inquiry budget insufficient "
        "for VTTC8908R; using available_cash=%s as fallback",
        account_id, available_cash,
    )
    orderable_amount = available_cash
else:
    await asyncio.sleep(1.0)  # Paper 1 RPS pacing (positions → orderable_cash)
    try:
        orderable_cash = await self._rest.get_orderable_cash(
            account_ref="",
            fallback_cash=available_cash,  # P2: budget 부족 시 자체 fallback
        )
    except BudgetExhaustedError:
        logger.warning(
            "BUDGET_EXHAUSTED account=%s — VTTC8908R budget exhausted "
            "despite pre-check; race condition, using available_cash=%s",
            account_id, available_cash,
        )
        orderable_cash = available_cash
    except Exception:
        logger.warning(
            "API_FAILURE account=%s — VTTC8908R unexpected error; "
            "using available_cash=%s as fallback",
            account_id, available_cash,
            exc_info=True,
        )
        orderable_cash = available_cash

    if orderable_cash is not None:
        orderable_amount = Decimal(str(orderable_cash))
```

#### 7.4.2 [`kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py)

이 파일에는 `after_hours` 파라미터가 없음. 따라서:
- `sync_kis_account_snapshots()`는 `after_hours`를 인식하지 않음
- 이 경로를 사용하는 caller에서 after-hours 판단 후 이 함수를 호출하지 않거나, `fetch_positions=False`로 호출

**변경:** `sync_kis_account_snapshots()`에 `after_hours: bool = False` 파라미터 추가:
```python
async def sync_kis_account_snapshots(
    rest_client: KISRestClient,
    ...
    *,
    fetch_positions: bool = True,
    after_hours: bool = False,  # NEW
) -> SyncResult:
```

`after_hours=True`이면 orderable_cash 호출 생략:
```python
# cash 확보 후, positions 이후 (변경된 순서):
if after_hours:
    logger.info(
        "AFTER_HOURS_SKIP account=%s — skipping VTTC8908R; "
        "after-hours mode, orderable_amount not needed",
        account_id,
    )
    orderable_amount = None
elif _has_budget_for_inquiry(rest_client):
    await asyncio.sleep(1.0)
    try:
        orderable_cash = await rest_client.get_orderable_cash(
            account_ref="",
            fallback_cash=available_cash,
        )
    except BudgetExhaustedError:
        logger.warning(
            "BUDGET_EXHAUSTED account=%s — VTTC8908R budget exhausted; "
            "using available_cash=%s",
            account_id, available_cash,
        )
        orderable_cash = available_cash
    except Exception:
        logger.warning(
            "API_FAILURE account=%s — VTTC8908R unexpected error; "
            "using available_cash=%s",
            account_id, available_cash,
            exc_info=True,
        )
        orderable_cash = available_cash
    
    if orderable_cash is not None:
        orderable_amount = Decimal(str(orderable_cash))
else:
    # Budget 부족 → available_cash fallback (사전 확인에서 판단)
    logger.warning(
        "BUDGET_FALLBACK account=%s — inquiry budget insufficient "
        "for VTTC8908R; using available_cash=%s",
        account_id, available_cash,
    )
    orderable_amount = available_cash
```


### 7.6 Budget 소비 계산 (변경 전/후 비교)

#### 변경 전 (1계좌, paper 환경, INQUIRY capacity=1)

| # | 시점 | 호출 | INQUIRY 남음 | global_rest 남음 | 결과 |
|---|------|------|-------------|-----------------|------|
| 0 | t=0 | - | 1 | 1 | - |
| 1 | t=0 | get_cash_balance | 0 | 0 | 성공 |
| 2 | t=1.0 | get_orderable_cash | 0.5 refill → 0 | 1 refill → 1, consume → 0 | **성공** (1초 대기 후) |
| 3 | t=2.0 | get_positions | 0.5 refill → 0 | 1 refill → 1, consume → 0 | **성공** (1초 대기 후) |

> **참고:** refill_rate=0.5/s이므로 1초 대기 후 inquiry는 0→0 (0.5 tokens, 정수로 0).
> 2초 대기 후 inquiry는 0→1 (1.0 tokens). 실제로는 3회 호출에 2초 이상 소요.

실제 문제 상황 (asyncio.sleep(1.0)만 있고 추가 대기 없음):
| # | 시점 | 호출 | INQUIRY 남음 | 결과 |
|---|------|------|-------------|------|
| 1 | t=0 | get_cash_balance | 1→0 | 성공 |
| 2 | t=1.0 | get_orderable_cash | 0.5→0 (refill不足) | **BudgetExhaustedError** |
| 3 | t=2.0 | get_positions | 1.0→0 (2초 refill) | 성공 (하지만 orderable 실패) |

**→ budget이 충분해도 패턴에 따라 orderable_cash가 실패할 수 있음.**

#### 변경 후 (P1+P2+P3 적용, INQUIRY capacity=1 유지)

> **참고:** positions은 `get_cash_balance()`(VTTC8434R) 응답에서 output1(positions list)으로
> 함께 반환되므로 **별도의 API 호출이 필요 없음.** 따라서 budget 소비는 cash_balance 1회 +
> orderable_cash 1회 = 최대 2회 INQUIRY 소비.

정상 상황 (cash + positions 성공, orderable_cash 2초 대기 후 성공):
| # | 시점 | 호출 | INQUIRY 남음 | global_rest 남음 | 결과 |
|---|------|------|-------------|-----------------|------|
| 1 | t=0 | get_cash_balance | 1→0 | 1→0 | 성공 (cash + positions) |
| 2 | t=2.0 | get_orderable_cash | 1.0→0 | 1→0 | **성공** (2초 refill) |

Budget 회복 전 orderable_cash 호출 시나리오 (1초 후):
| # | 시점 | 호출 | INQUIRY 남음 | 결과 |
|---|------|------|-------------|------|
| 1 | t=0 | get_cash_balance | 1→0 | 성공 (cash + **positions 포함**) |
| 2 | t=1.0 | get_orderable_cash | 0.5→0 | **fallback: available_cash** (BudgetExhaustedError 방지) |

**핵심 개선:** positions이 `get_cash_balance()` 응답에 포함되므로 항상 확보됨.
orderable_cash는 budget 부족 시 예외 대신 available_cash로 fallback.

---

### 7.7 테스트 계획

#### 7.7.1 기존 테스트 수정

**파일:** [`tests/services/test_kis_snapshot_sync.py`](tests/services/test_kis_snapshot_sync.py)

기존 `FakeKISRestClient`는 `budget_manager` 속성이 없음. P2 helper(`_has_budget_for_inquiry`)는
`budget_manager is None`이면 `True` 반환하므로 기존 테스트에 영향 없음.

수정 필요한 테스트:
1. `test_cash_balance_budget_exhausted_cash_not_saved` — 호출 순서 변경 반영 (orderable vs positions 순서)
2. `test_orderable_cash_budget_exhausted_fallback_to_raw_cash` — 변경 없음 (fallback 동일)
3. `test_positions_budget_exhausted_cash_still_saved` — 변경 없음 (cash 우선)

#### 7.7.2 신규 테스트 추가

| 테스트 | 설명 | 검증 |
|--------|------|------|
| `test_positions_before_orderable_cash_when_budget_limited` | budget 2회로 제한 | positions 성공, orderable fallback |
| `test_orderable_cash_skipped_when_after_hours` | after-hours=True | VTTC8908R 미호출, orderable_amount=None |
| `test_orderable_cash_fallback_with_pre_check` | budget 부족 사전 확인 | BudgetExhaustedError 없이 fallback |

#### 7.7.3 FakeKISRestClient 확장

`budget_manager` 속성 추가 (선택적):

```python
class FakeKISRestClient:
    def __init__(self, ..., budget_manager=None):
        ...
        self.budget_manager = budget_manager
    
    # 기존 메서드 유지
```

---

### 7.8 리스크 및 롤백 방안

#### 7.8.1 리스크 매트릭스

| 리스크 | 확률 | 영향 | 완화 방안 |
|--------|------|------|----------|
| 호출 순서 변경으로 orderable_amount 누락 | 낮음 | submit gate가 보수적 동작 (매수 제한) | available_cash fallback 존재. 항상 0이나 None이 아님 |
| after-hours에 orderable_amount가 필요한 경우 | 매우 낮음 | after-hours 매수 불가 정책과 상충 | 현재 after-hours는 cash-only sync 목적 |
| `_has_budget_for_inquiry` race condition | 낮음 | false positive (budget 있다고 판단 후 소진) | BudgetExhaustedError try/except fallback이 보호 |
| `FileBackedGlobalBucket.remaining` 부정확 | 중간 | false negative (budget 없다고 판단) | `remaining=capacity` 기본값 반환. fallback으로 안전 |

#### 7.8.2 롤백 방안

각 변경이 독립적이므로 단계별 롤백 가능:

| 우선순위 | 변경 | 롤백 방법 |
|----------|------|----------|
| P2 | budget 사전 확인 + fallback | `get_orderable_cash()`에서 fallback 파라미터 제거 |
| P1 | 호출 순서 변경 | `kis_snapshot_sync.py` + `snapshot.py` 순서 복원 |
| P3 | after-hours 생략 | 조건부 로직 제거 |

#### 7.8.3 모니터링 포인트

변경 후 다음 로그 패턴 모니터링:

```
# 정상 fallback (예상)
VTTC8908R budget insufficient — using available_cash fallback

# orderable_amount None (주의)
orderable_amount=None (VTTC8908R unavailable...)

# cash 실패 (심각)
Cash balance inquiry budget exhausted
```

---

### 7.9 구현 순서 (단계별)

| 단계 | 파일 | 변경 내용 | 테스트 |
|------|------|----------|--------|
| **1** | [`snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py) | 호출 순서 변경 + after-hours 체크 추가 | 기존 테스트 + 신규 |
| **2** | [`kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py) | 호출 순서 변경 + after-hours 파라미터 추가 | 기존 테스트 + 신규 |
| **3** | [`rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py):1300 | `get_orderable_cash()`에 fallback_cash 파라미터 + budget 사전 확인 | 단위 테스트 |
| **4** | helper 함수 | `_has_budget_for_inquiry()` 공통 유틸 추가 | - |
| **5** | 테스트 파일 | 신규 테스트 추가 | pytest 실행 |
| **6** | Docker | 이미지 rebuild + 검증 | 통합 테스트 |
