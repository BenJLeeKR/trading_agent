# KIS Paper REST RPS=1 Smoke Test 전략 문서

- **작성일**: 2026-05-25
- **대상 환경**: `KIS_PAPER_REST_RPS=1` (canonical)
- **참고 문서**:
  - [`kis_rest_strict_global_cap.md`](plans/kis_rest_strict_global_cap.md) — 2-Tier Token Bucket 설계
  - [`57_kis_rest_rps_config.md`](plans/57_kis_rest_rps_config.md) — RPS 환경변수 반영
  - [`fix_intraday_cash_snapshot_sync_budget_exhaustion_2026-05-22.md`](plans/fix_intraday_cash_snapshot_sync_budget_exhaustion_2026-05-22.md) — Budget exhaustion 실사례
  - [`59_kis_paper_smoke_rate_limit_mitigation.md`](plans/59_kis_paper_smoke_rate_limit_mitigation.md) — Smoke fixture skip 전략

---

## 1. RPS=1 제약 분석

### 1.1 Budget 구조

[`KIS_PAPER_REST_RPS=1`](docker-compose.yml:65) 환경에서 [`build_kis_budget_manager()`](src/agent_trading/brokers/rate_limit.py:351)는 다음 2-Tier bucket을 생성한다:

| Bucket | Capacity (burst) | Refill Rate | 비고 |
|--------|-----------------|-------------|------|
| **global_rest** | 1 | 1.0/sec | Tier 1 — 모든 REST 호출 선검문 |
| INQUIRY | 1 | 0.5/sec (2초) | Tier 2 — 조회용 |
| ORDER | 1 | 0.1/sec (10초) | Tier 2 — 주문용 |
| auth | 1 | 0.017/sec (≈60초) | Tier 2 — 인증 갱신 |
| market_data | 1 | 0.5/sec (2초) | Tier 2 — 시세 |
| reconciliation | 1 | 0.1/sec (10초) | Tier 2 — 정산 |

**2-Tier 동작 방식** ([`consume_or_raise()`](src/agent_trading/brokers/rate_limit.py:97)):

```
Request → Tier 1: global_rest bucket (capacity=1, refill=1.0/s)
            ↓ 통과
          Tier 2: per-operation bucket (inquiry/order/auth/md/recon)
            ↓ 통과
          HTTP Request (httpx)
```

- `global_rest`가 소진되면 per-operation bucket에 여유가 있어도 `BudgetExhaustedError` 발생
- 각 REST 호출은 **정확히 1개의 global token** + **정확히 1개의 per-operation token**을 소모

### 1.2 Cycle당 REST 호출 소요량

하나의 decision cycle에서 발생하는 REST 호출:

| 작업 | global token | inquiry token | order token |
|------|-------------|---------------|-------------|
| `quote_resolution` (005930) | 1 | 1 | 0 |
| `order submit` (005930) | 1 | 0 | 1 |
| **합계** | **2** | **1** | **1** |

> **참고**: snapshot sync는 별도 cycle로 실행되며 inquiry token만 소모 (global token도 1 소모).
> snapshot sync: get_cash_balance(1) + get_orderable_cash(1) + get_positions(1) = **global 3, inquiry 3**.

### 1.3 최소 필요 시간

```
T=0.0s: quote_resolution 호출
        → global_rest: 0/1 (refill 시작), inquiry: 0/1 (refill 시작)
T=1.0s: global_rest: 1/1 (refill 완료)
        → submit 가능
T=1.0s: submit 호출
        → global_rest: 0/1, order: 0/1
T=2.0s: global_rest: 1/1 (다음 cycle 가능)
        inquiry: 1/1 (2초 소요, 0.5/s)
```

- **한 cycle 최소 2초** (global refill 기준)
- **안정적 실행: 3~4초** (inquiry refill 2초 + 버퍼)

### 1.4 Snapshot sync와 decision loop의 budget 충돌

snapshot sync (`sync_kis_account_snapshots`)가 decision loop와 동시 실행되면:

| 시점 | 작업 | global | inquiry |
|------|------|--------|---------|
| T=0s | snapshot: get_cash_balance | 0/1 | 0/1 |
| T=1s | snapshot: get_orderable_cash | **BudgetExhausted** | - |
| T=2s | snapshot: get_positions | 불가 | 불가 |

→ snapshot sync는 decision loop와 **절대 동시 실행 금지**

---

## 2. Budget Exhaustion은 정상

### 2.1 핵심 원칙

RPS=1에서 `BudgetExhaustedError`는 **버그가 아니라 예상된 동작**이다.

### 2.2 발생 시나리오

1. **quote_resolution → submit 연속 실행**
   - `quote_resolution()`에서 global token 소진 (0/1)
   - submit 실행 전까지 최소 1초 refill 대기 필요
   - refill 전 submit 시도 → `BudgetExhaustedError(global)`

2. **Decision loop 연속 실행**
   - Cycle 1: quote + submit = global 2 소모 (refill 2초 필요)
   - Cycle 2가 2초 이내 시작 → budget exhaustion

3. **Snapshot sync 직후 quote_resolution**
   - Snapshot sync가 global 3, inquiry 3 소모
   - 이후 quote_resolution 시도 → global/inquiry 모두 exhaustion

### 2.3 Fallback 동작

[`consume_or_raise()`](src/agent_trading/brokers/rate_limit.py:97)에서 `BudgetExhaustedError` 발생 시:

1. `quote_resolution` 단계:
   - `quote = None` 처리
   - 캐시/마지막 quote 사용 fallback
   - `reconcile_required` auto-trigger

2. Submit 단계 ([`decision_submit_gate.py`](src/agent_trading/services/decision_submit_gate.py)):
   - `reconcile_required` 상태로 전환
   - `broker_orders` 테이블 비어 있음 (KIS 미도달)
   - `error_message`에 `"BUDGET_EXHAUSTED"` 포함

3. Snapshot sync 단계:
   - Cash/stale guardrail로 submit 차단 (예: `CASH_SYNC_ZERO`)
   - 다음 sync에서 복구 시도

### 2.4 검증 포인트 (정상 동작 확인)

Budget exhaustion 발생 시 반드시 확인할 항목:

- [ ] `reconcile_required` auto-trigger가 정상 동작하는가?
- [ ] `broker_orders` 테이블이 비어있는가? (KIS 미도달 확인)
- [ ] `error_message`에 `"BUDGET_EXHAUSTED"`가 포함되는가?
- [ ] 시스템이 crash되지 않고 graceful fallback으로 전환되는가?

---

## 3. Smoke Test 전략 재설계

### 3.1 순차 검증 전략 (동시 검증 금지)

**원칙**: 모든 테스트는 순차적으로 실행하며, 각 테스트 사이에 budget refill 대기 시간을 확보한다.

#### Step 1: Snapshot Sync 단독 실행

```
목적: snapshot sync가 단독으로 정상 동작하는지 검증
소모: global 3, inquiry 3
필요 대기: 3초 (global) + 6초 (inquiry) → 6초 후 다음 테스트 가능
```

**검증 항목**:
- [ ] `get_cash_balance()` 정상 응답
- [ ] `get_orderable_cash()` 정상 응답 (또는 fallback)
- [ ] `get_positions()` 정상 응답
- [ ] `cash_stale = False`
- [ ] Budget exhaustion 발생 시 cash/stale fallback 처리

#### Step 2: Quote Resolution 단독 검증

```
목적: quote_resolution이 단독으로 정상 동작하는지 검증
소모: global 1, inquiry 1
필요 대기: 2초 (inquiry refill)
```

**검증 항목**:
- [ ] `quote_resolution()` 정상 응답 (1 global token + 1 inquiry token 소모)
- [ ] Quote 데이터가 정상적으로 반환되는지
- [ ] Budget exhaustion 시 `quote = None` fallback 처리

#### Step 3: Assemble-only 검증

```
목적: quote 없이 assemble(path)만 단독 검증
소모: global REST 호출 없음 (내부 연산만)
필요 대기: 별도 budget refill 불필요
```

**검증 항목**:
- [ ] AI assemble이 정상 동작하는지
- [ ] Event interpretation이 캐시/마지막 quote로 동작하는지
- [ ] `summary`가 정상 생성되는지

#### Step 4: Submit 단독 검증

```
목적: 사전 budget 확보 후 1회 submit 검증
소모: global 1, order 1
필요 대기: submit 전 최소 1초 대기 (global refill)
```

**검증 항목**:
- [ ] Submit이 budget exhaustion 없이 실행되는지
- [ ] Broker 응답 코드가 정상인지 (40100000 제외)
- [ ] `broker_orders` 테이블에 정상 기록되는지

### 3.2 Budget-aware 실행 순서 (실행 타임라인)

```
T=0s:  [Step 2] quote_resolution (global=0/1, inquiry=0/1)
T=1s:  global=1/1 → [Step 4] submit 가능
T=1s:  [Step 4] submit (global=0/1, order=0/1)
T=2s:  global=1/1 → 다음 cycle 가능
       inquiry=1/1 (2초, 0.5/s refill)
T=3s:  → 안정적인 다음 cycle 시작 (버퍼 1초 포함)
```

### 3.3 테스트 러너 수정 사항

#### 3.3.1 [`run_orchestrator_once.py`](scripts/run_orchestrator_once.py)

각 cycle 사이에 최소 대기 시간 확보:

```python
# After each cycle, wait for budget refill
await asyncio.sleep(3)  # 최소 3초 대기
```

**변경 사항**:
- `quote_resolution()` 후 `asyncio.sleep(1.5)` → global refill 대기
- `submit()` 후 `asyncio.sleep(2)` → global + inquiry refill 대기
- Cycle 완료 후 `asyncio.sleep(3)` → 다음 cycle 대기

#### 3.3.2 [`run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py)

Decision loop interval을 60초 이상으로 설정:

```python
# Paper RPS=1 환경: 최소 60초 interval
INTERVAL_SECONDS = 60  # 또는 env override KIS_PAPER_DECISION_INTERVAL
```

**근거**:
- 1 cycle = global 2 소모 → refill 2초 필요
- 여유를 위해 60배 버퍼 (120초 소모분 복구)
- Snapshot sync (global 3 소모)와의 충돌 방지

#### 3.3.3 Snapshot-sync loop

- **Decision loop와 동시 실행 금지**
- Snapshot sync schedule은 decision loop 실행 전/후에 배치
- 최소 간격: snapshot sync 완료 후 10초 대기 후 decision loop 시작

### 3.4 Budget exhaustion 발생 시 검증 포인트

Budget exhaustion은 실패가 아닌 검증 포인트로 활용:

| 검증 항목 | 기대 결과 | 확인 방법 |
|-----------|----------|----------|
| `reconcile_required` auto-trigger | True로 전환 | `agent_runs` 테이블 상태 |
| `broker_orders` 비어 있음 | KIS 미도달 확인 | `broker_orders` 테이블 조회 |
| `error_message` 포맷 | `"BUDGET_EXHAUSTED"` 포함 | 로그 또는 agent_runs 상세 |
| 시스템 안정성 | Crash 없음 | 프로세스存活 확인 |
| Fallback 처리 | 캐시/마지막 값 사용 | Quote/Snapshot 값 확인 |

---

## 4. 시장일 vs 휴장일 테스트 전략

### 4.1 시나리오별 동작 매트릭스

| 시나리오 | 시장일 | 휴장일 |
|---------|-------|--------|
| **snapshot sync** | ✅ 정상 동작 | ✅ 정상 동작 (stale 방지) |
| **quote resolution** | ✅ 실시간 quote 응답 | ✅ 캐시/마지막 quote (KIS 40100000) |
| **assemble (AI)** | ✅ 정상 | ✅ 정상 (영업일 무관) |
| **sizing** | ✅ 실시간 snapshot 기반 | ✅ 마지막 snapshot 기반 |
| **submit → KIS API** | ✅ broker submit 정상 | ❌ 40100000 reject |
| **budget exhaustion** | ✅ 발생 가능 | ✅ 발생 가능 |

### 4.2 시장일 검증 프로토콜

1. **사전 조건 확인**
   - [ ] Snapshot sync 완료 (`cash_stale=False`)
   - [ ] KIS API 정상 응답 (40100000 아님)
   - [ ] Global budget: `remaining >= 2` (quote + submit)

2. **실행 순서**
   ```
   T-6s: snapshot sync 완료 대기
   T-3s: budget 확인 (remaining >= 2)
   T=0s: quote_resolution
   T=1s: submit (global refill 완료)
   T=2s: broker 응답 검증
   ```

3. **검증 범위**
   - KIS API 응답까지 end-to-end 검증
   - `broker_orders` 테이블 기록 확인
   - Broker 응답 코드 검증 (40100000 제외)

### 4.3 휴장일 검증 프로토콜

1. **사전 조건 확인**
   - [ ] 마지막 snapshot 존재 (stale 가능)
   - [ ] `is_trading_day = False` 확인

2. **실행 순서**
   ```
   T=0s: quote_resolution → 40100000 (예상)
   T=0s: cache/market-data quote fallback 사용
   T=1s: assemble 실행 (quote fallback 기반)
   T=1s: submit 시도 → budget exhaustion 또는 40100000
   T=1s: reconcile_required auto-trigger 확인
   ```

3. **검증 범위**
   - Submit path 진입까지만 검증 (KIS API까지 가지 않음)
   - Budget exhaustion → `reconcile_required` 전환 확인
   - **RPS를 올리지 않음** — budget exhaustion이 발생해도 RPS 증가 금지

### 4.4 공통 검증 (시장일/휴장일 무관)

- [ ] Budget exhaustion 시 `reconcile_required` auto-trigger
- [ ] Error message에 `"BUDGET_EXHAUSTED"` 포함
- [ ] 시스템 crash 없음
- [ ] Fallback 처리 정상 동작

---

## 5. Budget-Sensitive 테스트 지침

### 5.1 기존 Smoke Test 분리

기존 smoke test (`test_kis_paper_smoke.py`)에서 KIS API 호출이 필요한 부분은 **별도 테스트로 분리**한다.

| 테스트 | API 호출 | Budget 소모 | 분리 여부 |
|--------|---------|------------|----------|
| `test_authentication` | auth | global 1 + auth 1 | ✅ 기존 유지 |
| `test_inquire_price` | inquiry | global 1 + inquiry 1 | ✅ 기존 유지 (EGW00133 skip) |
| `test_inquire_daily_ccld` | inquiry | global 1 + inquiry 1 | ⚠️ budget 확인 후 실행 |
| `test_order_submit` | order | global 1 + order 1 | ⚠️ 별도 step으로 분리 |

### 5.2 금지 사항

- ❌ `_test_real_sizing.py` 같은 임시 파일 사용 금지
- ❌ KIS 실전(live) 경로 사용 금지
- ❌ RPS=1을 override하여 증가 금지
- ❌ Decision loop와 snapshot sync 동시 실행 금지
- ❌ `time.sleep(0)` 또는 `await asyncio.sleep(0)`으로 budget bypass 시도 금지

### 5.3 권장 도구

대신 다음 도구를 활용:

| 도구 | 용도 | 파일 위치 |
|------|------|----------|
| `scripts/inject_events_real_sizing.py` | 실제 sizing 데이터 주입 | [`scripts/inject_events_real_sizing.py`](scripts/inject_events_real_sizing.py) |
| `scripts/seed_smoke_test.py` | 시드 데이터 기반 smoke test | [`scripts/seed_smoke_test.py`](scripts/seed_smoke_test.py) |
| `tests/fixtures/...` | Mock budget manager fixture | [`tests/`](tests/) |

### 5.4 Budget 대기 시간 규칙

각 테스트 실행 전 반드시 budget refill 대기:

| 이전 작업 | 대기 시간 | 근거 |
|-----------|----------|------|
| Snapshot sync 완료 후 | `time.sleep(6)` | global 3 + inquiry 3 refill |
| Quote resolution 후 | `time.sleep(2)` | global 1 + inquiry 1 refill |
| Submit 후 | `time.sleep(2)` | global 1 + order 1 refill |
| Budget exhaustion 후 | `time.sleep(3)` | global 1 refill + 버퍼 |
| Decision loop 1회 완료 후 | `time.sleep(3)` | global 2 refill (quote+submit) |

### 5.5 Mock Budget Manager 전략

Budget-sensitive 테스트에서는 [`RateLimitBudgetManager`](src/agent_trading/brokers/rate_limit.py:117)를 mock/override하여 budget exhaustion을 회피할 수 있다:

```python
# Mock: budget exhaustion 없이 항상 통과
from unittest.mock import patch

with patch.object(RateLimitBudgetManager, "consume_or_raise", return_value=None):
    # Budget 제약 없이 테스트 실행
    ...
```

**사용 조건**:
- KIS API 호출이 없는 로직 검증에만 사용
- Budget exhaustion fallback 로직 검증 시에는 사용 금지

---

## 6. 운영 검증 항목

### 6.1 시장일 첫 실행 체크리스트

Paper 환경 시장일 첫 실행 시 반드시 확인할 항목:

| # | 검증 항목 | 기대 결과 | 확인 위치 |
|---|----------|----------|----------|
| 1 | 사전 snapshot sync 완료 | `cash_stale=False` | `cash_balance_snapshots` 테이블 |
| 2 | `quote_resolution` token 소모 | global 1 + inquiry 1 정상 소모 | `broker_capacity` API |
| 3 | Submit budget exhaustion | 없음 (정상 실행) | `agent_runs` 상태 |
| 4 | Budget exhaustion fallback | `reconcile_required` 전환 | `agent_runs.reconcile_required` |
| 5 | Broker 응답 코드 | 정상 (40100000 제외) | `broker_orders` 테이블 |

### 6.2 모니터링 항목

운영 중 지속 모니터링할 항목:

| 항목 | 임계값 | 조치 |
|------|--------|------|
| Global budget remaining | < 1 | 다음 cycle 대기 |
| 연속 budget exhaustion 횟수 | > 3회 | 수동 개입 검토 (RPS 증가 아님) |
| Quote 연속 실패 | > 2회 | 캐시/마지막 quote 사용 확인 |
| Submit 연속 실패 (budget) | > 3회 | Scheduler interval 증가 검토 |
| Snapshot stale 지속 | > 30분 | Snapshot sync 수동 트리거 |

### 6.3 비정상 상황 대응

| 상황 | 대응 | RPS 증가 여부 |
|------|------|--------------|
| Budget exhaustion 지속 | Scheduler interval 증가 | ❌ 절대 금지 |
| Quote 연속 실패 | 캐시/market-data quote fallback 확인 | ❌ |
| Submit 연속 실패 | Reconcile 경로 전환 확인 | ❌ |
| Snapshot stale | 수동 sync 트리거 | ❌ |

### 6.4 RPS 증가 금지 원칙

어떤 상황에서도 다음은 금지:

1. `KIS_PAPER_REST_RPS` 환경변수 1 이상으로 설정
2. `global_rest_capacity` 코드 상수 변경
3. `time.sleep(0)`으로 budget bypass 시도
4. Mock budget manager로 실제 KIS API 호출 우회
5. 실전(live) RPS 설정을 paper에 적용

---

## 7. 참고: Budget 구조 상세

### 7.1 2-Tier Bucket 생성 코드

[`build_kis_budget_manager()`](src/agent_trading/brokers/rate_limit.py:351)에서 paper 환경 생성:

```python
# Paper (total=1 rps)
RateLimitBudgetManager(
    ...,
    global_rest_capacity=max(1, int(total * 1)),      # = 1
    global_rest_refill_rate=1.0 * total,                # = 1.0
    # Per-operation buckets
    auth:     capacity=1,  refill_rate=0.017   (1/60 ≈ 1/min)
    order:    capacity=1,  refill_rate=0.1     (1 per 10s)
    inquiry:  capacity=1,  refill_rate=0.5     (1 per 2s)
    market_data: capacity=1, refill_rate=0.5   (1 per 2s)
    reconciliation: capacity=1, refill_rate=0.1 (reserve)
)
```

### 7.2 환경변수 설정

[`docker-compose.yml:65`](docker-compose.yml:65):

```yaml
environment:
  - KIS_PAPER_REST_RPS=1    # canonical
  # - KIS_REAL_REST_RPS=15  # live 환경 (변경 금지)
```

### 7.3 Budget Exhaustion Error 구조

[`consume_or_raise()`](src/agent_trading/brokers/rate_limit.py:97)에서 발생하는 에러:

```python
# Tier 1: Global REST cap exhausted
BudgetExhaustedError(
    bucket="global",
    message=f"Global REST cap exhausted "
            f"(remaining={self.global_rest.remaining}/{self.global_rest.capacity})",
)

# Tier 2: Per-operation bucket exhausted
BudgetExhaustedError(
    bucket=bucket.value,  # "inquiry", "order", etc.
    message=(
        f"Bucket '{bucket.value}' exhausted "
        f"(remaining={b.remaining}/{b.capacity})"
    ),
)
```

---

## 부록 A: 실행 명령어 모음

### A.1 Snapshot sync 단독 실행

```bash
# Budget refill 대기 후 실행
python -m scripts.run_snapshot_sync_once --env paper
```

### A.2 Quote resolution 단독 검증

```bash
# Snapshot sync 완료 후 6초 대기 필요
sleep 6 && python -c "
import asyncio
from src.agent_trading.brokers.koreainvestment.rest_client import KISRestClient
...
"
```

### A.3 Decision loop (안전 interval)

```bash
# Interval 60초, budget-aware
KIS_PAPER_DECISION_INTERVAL=60 python -m scripts.run_paper_decision_loop
```

### A.4 Budget 상태 확인

```bash
curl -s http://localhost:8000/api/v1/broker-capacity | jq '.rest_budget.global'
```

---

## 부록 B: Budget Exhaustion 로그 예시

```
2026-05-25 09:00:01 [WARNING] quote_resolution: BudgetExhaustedError
  bucket=global, remaining=0/1
  → fallback: using cached quote

2026-05-25 09:00:02 [INFO] quote_resolution: refill completed (global=1/1)
  → retry: quote resolution success

2026-05-25 09:00:03 [WARNING] submit: BudgetExhaustedError
  bucket=global, remaining=0/1
  → fallback: reconcile_required=True

2026-05-25 09:00:04 [INFO] reconcile_required auto-trigger confirmed
  broker_orders: empty (KIS not reached)
  error_message: "BUDGET_EXHAUSTED: Global REST cap exhausted (remaining=0/1)"
```
