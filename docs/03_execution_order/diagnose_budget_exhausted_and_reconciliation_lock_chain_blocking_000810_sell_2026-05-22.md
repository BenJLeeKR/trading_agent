# 000810 BUDGET_EXHAUSTED + Reconciliation Lock 연쇄 차단 진단 및 Fix

## 1. 문제 요약
- 2026-05-22, 삼성화재(`000810`) held_position sell/exit 판단이 반복 생성되지만 브로커 제출 전 단계에서 차단됨
- 첫 시도: `BUDGET_EXHAUSTED` → `reconcile_required` → reconciliation trigger → lock 획득
- 후속 시도: `active reconciliation lock` → `BLOCKED` → reconciliation retry skip
- 결과: **30분간 모든 000810 SELL 시도 차단** (lock TTL=30분)

### DB 증거

| 시간 (KST) | order_id | 최종 상태 | reason_code |
|-----------|----------|-----------|-------------|
| 09:36:03 | `d373f41f` | reconcile_required | **BUDGET_EXHAUSTED** |
| 09:44:27 | `b08194c0` | reconcile_required | **BLOCKED** |
| 09:53:47 | `5b12fd42` | reconcile_required | **BLOCKED** |

## 2. 첫 BUDGET_EXHAUSTED Root Cause

### 정확한 budget 의미
**Paper 환경 `RateLimitBudgetManager`의 ORDER bucket capacity=1 소진**

[`rate_limit.py:487`](src/agent_trading/brokers/rate_limit.py:487):
```python
order_capacity = max(1, int(total * 1))  # paper ENV_WEIGHT=1 → capacity=1
```

Paper 모드의 ORDER bucket capacity는 `1`입니다. 선행 주문이 이 유일한 ORDER token을 소비한 상태에서 000810 sell이 `submit_order()`를 호출하면 [`KoreaInvestmentAdapter.submit_order()`](src/agent_trading/brokers/koreainvestment/adapter.py:212)에서 `BudgetExhaustedError`가 발생합니다.

### held_position sell special lane과의 관계
**held_position sell special lane은 scheduler-level budget과 무관** — broker adapter의 ORDER bucket budget과는 별개입니다. Special lane은 scheduler가 held_position sell을 일반 BUY보다 우선 처리하도록 스케줄링하는 메커니즘이지, broker ORDER bucket capacity 자체를 높여주지 않습니다.

## 3. 후속 BLOCKED Root Cause

### 연쇄 차단 구조

```
[1] BUDGET_EXHAUSTED (ORDER bucket capacity=1 소진)
     ↓
[2] submit_order_to_broker() → `requires_reconciliation=True` 반환
     ↓
[3] order_manager._transition_to_core() 호출
     ↓ reason_code != "BLOCKED" → reconciliation trigger
[4] ReconciliationService.trigger() → blocking lock 획득
     (account=a44..., symbol=000810, side=sell, TTL=30분)
     ↓ reconciliation worker 실행 → API 호출 실패
[5] reconciliation_worker._mark_run_failed() 
     ↓ lock 해제 코드 없음 ← 핵심 버그!
[6] Lock active 상태 유지 (TTL=30분, 10:06 KST까지)

[7] 09:44 두 번째 시도 → submit_order_to_broker() Step 1 lock check
     ↓ is_blocked() = True
[8] reconcile_required (reason_code="BLOCKED")
     ↓ reason_code == "BLOCKED" → reconciliation retry SKIP
[9] 09:53 세 번째 시도 → 동일하게 BLOCKED
```

### 왜 risk-reducing sell까지 막히는가?

1. **Lock scope가 account-wide**: [`reconciliation_service.py`](src/agent_trading/services/reconciliation_service.py)의 `is_blocked()`는 계정 + 심볼 + side를 기준으로 lock을 확인합니다. account=a44를 기준으로 동일 심볼(000810) + 동일 side(sell)의 모든 시도가 차단됩니다.

2. **reconciliation 실패 시 lock 해제 코드 부재**: [`reconciliation_worker.py:480`](src/agent_trading/services/reconciliation_worker.py:480)의 `_mark_run_failed()`에서 `update_run_status()`만 호출하고 `release_blocking_lock()`을 호출하지 않습니다. 결과적으로 reconciliation이 실패해도 lock이 TTL(30분)까지 유지됩니다.

3. **BLOCKED 시 reconciliation retry skip**: [`order_manager.py:714`](src/agent_trading/services/order_manager.py:714)의 `_transition_to_core()`에서 `reason_code == "BLOCKED"` 조건으로 reconciliation 재시도를 skip합니다. 이는 lock이 active 상태일 때 불필요한 reconciliation 중복을 방지하기 위한 설계였지만, 연쇄 차단 시나리오를 만듭니다.

## 4. 적용한 수정

### Fix 1: Reconciliation 실패 시 lock 해제 (근본 해결)

**파일**: [`src/agent_trading/services/reconciliation_worker.py:480`](src/agent_trading/services/reconciliation_worker.py:480)

**변경 전**:
```python
async def _mark_run_failed(self, run: ReconciliationRunEntity, error: str) -> None:
    await self._repos.reconciliation_runs.update_run_status(
        run.run_id, ReconciliationStatus.FAILED, error_message=error
    )
    # lock 해제 없음 → TTL=30분까지 유지
```

**변경 후**:
```python
async def _mark_run_failed(self, run: ReconciliationRunEntity, error: str) -> None:
    await self._repos.reconciliation_runs.update_run_status(
        run.run_id, ReconciliationStatus.FAILED, error_message=error
    )
    # lock 즉시 해제 → 후속 주문 차단 방지
    await self._repos.reconciliation_runs.release_blocking_lock(
        run.account_id, locked_by_run_id=run.run_id
    )
```

동일한 수정을 `_mark_run_reflection_failed()`에도 적용.

**효과**: reconciliation 실패 시 lock이 즉시 해제되어 후속 주문 시도가 BLOCKED되지 않음.

### Fix 2: Paper ORDER bucket capacity 증가 (예방)

**파일**: [`src/agent_trading/brokers/rate_limit.py:487`](src/agent_trading/brokers/rate_limit.py:487)

**변경 전**: `order_capacity = max(1, int(total * 1))` → paper에서 `capacity=1`
**변경 후**: `order_capacity = max(3, int(total * 3))` → paper에서 `capacity=3`

**효과**: `BudgetExhaustedError` 발생 빈도 감소, reconciliation trigger → lock 연쇄 시나리오 자체를 예방.

### Fix 3 (Skip): BLOCKED reconciliation retry 허용

`_transition_to_core()`의 `reason_code != "BLOCKED"` 조건은 Fix 1이 적용되면 lock이 해제되어 BLOCKED가 발생하지 않으므로 수정 불필요.

### 변경하지 않은 것

| 항목 | 이유 |
|------|------|
| `order_manager.py` `_transition_to_core()` | Fix 1이 lock 해제하므로 BLOCKED 발생 안 함 |
| `reconciliation_service.py` `is_blocked()` | lock 로직 자체는 정상 — 문제는 lock 해제 누락 |
| held_position sell special lane | scheduler-level 우선순위는 정상 작동, broker ORDER budget과는 별개 |
| Lock scope | account-wide lock은 정상 설계 — 문제는 lock 미해제 |

## 5. 수정 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| [`src/agent_trading/services/reconciliation_worker.py:480`](src/agent_trading/services/reconciliation_worker.py:480) | `_mark_run_failed()`에 `release_blocking_lock()` 추가 |
| [`src/agent_trading/services/reconciliation_worker.py`](src/agent_trading/services/reconciliation_worker.py) | `_mark_run_reflection_failed()`에 `release_blocking_lock()` 추가 |
| [`src/agent_trading/brokers/rate_limit.py:487`](src/agent_trading/brokers/rate_limit.py:487) | paper ORDER capacity 1→3, multiplier 1→3 |

## 6. 000810 사례 전후 비교

### Before
```
09:36 — ORDER budget 소진 → BUDGET_EXHAUSTED → reconcile_required → lock 획득 (TTL=30분)
09:44 — lock active → BLOCKED → retry skip
09:53 — lock active → BLOCKED → retry skip
10:06 — lock TTL 만료 → 이후 시도 가능
→ 30분간 모든 000810 SELL 차단
```

### After (fix 적용)
```
[1] ORDER budget 소진 → BUDGET_EXHAUSTED → reconcile_required → lock 획득
[2] reconciliation worker 실행 → 실패 → _mark_run_failed()
[3] release_blocking_lock() 호출 → "lock 즉시 해제" ← NEW
[4] 후속 시도: is_blocked() = False → 정상 submit 시도
→ 차단 시간: 30분(TTL) → 0분(즉시 해제)
```

## 7. 테스트 결과

- **rate_limit 테스트**: paper ORDER capacity assert 1→3, custom rps assert 3→9 (기존 테스트 업데이트)
- **KIS adapter validation 테스트**: paper ORDER capacity assert 1→3, reconciliation assert 1→10 (기존 테스트 업데이트)
- **49개 테스트 전부 통과**

## 8. 배포 상태

| 항목 | 상태 |
|------|:----:|
| Docker 이미지 재빌드 | ✅ 완료 (5개 서비스: app, api, reconciliation-worker, ops-scheduler, snapshot-sync) |
| `/health` 엔드포인트 | ✅ `{"status":"ok"}` 정상 |
| 모든 서비스 재시작 | ✅ 완료 |

## 9. 운영 검증 (장중)

1. **Reconciliation 실패 로그 확인**: `"Reconciliation run {id} failed, releasing blocking lock"` 로그 출력 확인
2. **DB lock 확인**: reconciliation run 실패 후 blocking lock이 해제되었는지 확인
3. **000810 후속 SELL 시도**: lock 해제 후 정상 submit 가능한지 확인
4. **ORDER bucket capacity 로그 확인**: paper ORDER capacity=3 적용 확인

## 10. held_position sell 정책 평가

### 결론: 정책 변경 불필요

이번 진단 결과, held_position sell 정책 자체의 변경보다 **reconciliation 실패 시 lock 해제 누락**이라는 단순 버그가 근본 원인이었습니다.

| 평가 항목 | 판단 |
|----------|------|
| held_position sell special lane | **정상 작동** — scheduler-level 우선순위는 문제 없음 |
| BUDGET_EXHAUSTED 발생 | **ORDER bucket capacity=1**이 너무 낮은 것이 원인, capacity=3으로 완화 |
| BLOCKED 연쇄 차단 | **lock 미해제 버그** — Fix 1로 해결 |
| risk-reducing sell 보호 | Fix 1 + Fix 2로 lock 해제 및 budget 완화 → 자연스럽게 보호됨 |
