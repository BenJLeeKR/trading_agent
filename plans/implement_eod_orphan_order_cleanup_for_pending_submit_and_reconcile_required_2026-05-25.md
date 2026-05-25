# EOD Orphan Order Cleanup: PENDING_SUBMIT / RECONCILE_REQUIRED 정리

## 1. Orphan Cleanup 대상 조건

### 1.1 DB 현황 (2026-05-25 14:42 KST 기준)

#### pending_submit orphan (총 21건)

| 구분 | 값 |
|------|-----|
| 총 건수 | **21건** |
| oldest | 2026-05-14 14:12:06 KST (11일 경과) |
| newest | 2026-05-25 13:27:51 KST (~1시간 전) |
| submitted_at IS NULL | **21/21 (100%)** |
| broker_orders 레코드 | **0건 (100%)** |
| broker_native_order_id | **전부 NULL** |
| Side 분포 | BUY 19건, SELL 2건 |
| 일자별 분포 | 2026-05-14: 7건, 2026-05-18: 4건, 2026-05-24: 2건, 2026-05-25: 8건 |

모든 `pending_submit` orphan은 `submitted_at IS NULL`이고 `broker_orders`에 대응 레코드가 전혀 없음. 즉, `submit_order_to_broker()`가 호출되기 전에 실패하여 broker에 도달한 적이 없는 주문들.

#### reconcile_required orphan (총 17건)

| 구분 | 값 |
|------|-----|
| 총 건수 | **17건** |
| oldest | 2026-05-22 09:36:06 KST (3일 경과) |
| newest | 2026-05-25 13:23:25 KST (~1시간 전) |
| submitted_at IS NULL | **17/17 (100%)** |
| broker_orders 레코드 | **0건 (100%)** |
| broker_native_order_id | **전부 NULL** |
| Side 분포 | BUY 3건 (오늘), SELL 14건 (5/22) |
| status_reason_code | BUDGET_EXHAUSTED 9건, BLOCKED 8건 |
| Reconciliation 연결 | linked: 7건 (모두 failed), unlinked: 10건 |

모든 `reconcile_required` orphan도 `submitted_at IS NULL`이고 `broker_orders` 레코드가 없음. 즉, broker 제출 시도조차 이루어지지 않고 budget 부족 또는 reconciliation lock에 의해 차단된 주문들.

#### execution_attempts 연계 (오늘 날짜)

| order_request_id | trade_decision_id | execution_attempt.status | stop_phase | order.status |
|---|---|---|---|---|
| 4798ba42 | e6bccf3d | **failed** | broker_submit | pending_submit |
| 7c8d1538 | 7252f024 | **reconcile_required** | completed | reconcile_required |
| 0cc91ad3 | d1957862 | **reconcile_required** | completed | reconcile_required |
| d6e76e54 | 67ba8db8 | **stopped** | stale_snapshot_guard | pending_submit |
| 3d06c66b | 07f47128 | **reconcile_required** | completed | reconcile_required |
| 5e1b1709 | cc7133b7 | **failed** | broker_submit | pending_submit |
| f2fb9af5 | 81f07cab | **stopped** | stale_snapshot_guard | pending_submit |
| 35ec90a1 | e40b93c9 | **failed** | broker_submit | pending_submit |
| 964d1e49 | f4d42c6e | **failed** | broker_submit | pending_submit |
| f139aa45 | 60afa701 | **stopped** | stale_snapshot_guard | pending_submit |

`failed(broker_submit)` / `stopped(stale_snapshot_guard)` → `pending_submit` 상태로 이행.
`reconcile_required`(completed) → `reconcile_required` 상태로 이행.

### 1.2 전제 조건 (기존 정리 메커니즘)

이미 적용된 정리 메커니즘:

1. **Post-submit sync** ([`order_sync_service.py`](src/agent_trading/services/order_sync_service.py:72)):
   - `_PENDING_SUBMIT_STALE_SECONDS = 1800` (30분)
   - `_expire_stale_pending_submit_orders()`가 30분 이상 stuck된 `PENDING_SUBMIT`을 조회하여 `REJECTED`로 전이
   - **단, 이 로직은 post-submit sync loop가 실행 중일 때만 동작**

2. **RECONCILE_REQUIRED 해소** ([`order_sync_service.py`](src/agent_trading/services/order_sync_service.py:798)):
   - `_sync_reconcile_required_orders()`가 broker truth 조회로 해소 시도
   - after-hours에만 EXPIRED fallback 허용
   - intraday에는 RECONCILE_REQUIRED 유지

3. **EOD Cleanup 필요성**:
   - 위 메커니즘이 있지만, post-submit sync loop가 중단된 기간에 생성된 orphan은 cleanup되지 않음
   - `reconcile_required` 중 `failed` reconciliation run만 있는 경우 추가 조치 필요
   - EOD(End of Day) 시점에 일괄 정리하는 안전장치 필요

### 1.3 필수 안전 조건 (ALL must be true)

Cleanup(REJECTED/EXPIRED 전이)을 수행하기 위해 **모두** 충족되어야 하는 조건:

| # | 조건 | SQL 검증 | 근거 |
|---|------|----------|------|
| 1 | **broker_orders.count = 0** | `LEFT JOIN trading.broker_orders bo ON bo.order_request_id = o.order_request_id WHERE bo.broker_order_id IS NULL` | broker_orders 레코드가 하나라도 있으면 broker에 전송된 기록이 있다는 의미. cleanup 시 데이터 소실 위험. |
| 2 | **broker_native_order_id IS NULL** | 조건 1이 만족되면 자동 충족 | broker_native_order_id가 존재하면 broker에서 주문을 접수했다는 증거. cleanup 시 복구 불가. |
| 3 | **submitted_at IS NULL** | `o.submitted_at IS NULL` | submitted_at이 설정되었다면 broker_submit()이 적어도 호출된 것. cleanup 시 실제 전송된 주문을 손상시킬 위험. |
| 4 | **age >= threshold** | `o.created_at < NOW() - INTERVAL '1 hour'` | threshold 미만 young order는 아직 정리 대상이 아님. post-submit sync loop가 정리할 기회를 줘야 함. threshold: 1시간 (EOD cleanup 기준) |
| 5 | **(reconcile_required 전용) 연결된 reconciliation run이 failed 상태이거나 존재하지 않음** | `rr.status IS NULL OR rr.status = 'failed'` | reconciliation run이 `completed` 또는 `pending` 상태이면 아직 해소 중. cleanup 시 중간 상태를 손상시킬 위험. |

### 1.4 제외 조건 (하나라도 해당되면 cleanup 대상 아님)

| # | 제외 조건 | 설명 | 위험도 |
|---|-----------|------|--------|
| E1 | `broker_orders` 레코드 존재 (broker_order_id IS NOT NULL) | broker로 전송된 기록이 있음 | **CRITICAL** |
| E2 | `broker_native_order_id`가 NULL이 아님 | broker가 주문을 접수/처리함 | **CRITICAL** |
| E3 | `submitted_at`이 NULL이 아님 | submit_order_to_broker()가 실행됨 | **HIGH** |
| E4 | 연결된 reconciliation run이 `completed` 또는 `pending` | reconciliation이 진행 중이거나 완료됨 | **HIGH** |
| E5 | `status = pending_submit` + `age < 1시간` | young order — post-submit sync가 처리할 기회를 줘야 함 | **MEDIUM** |

### 1.5 상태 전이 대상

| 현재 상태 | 전이 대상 | reason_code | 근거 |
|-----------|----------|-------------|------|
| `pending_submit` | `REJECTED` | `"stale_pending_submit_orphan"` | broker에 제출된 적 없는 주문. REJECTED는 "제출 실패" 의미에 적합. ([`order_manager.py`](src/agent_trading/services/order_manager.py:68)에 `PENDING_SUBMIT → REJECTED` 경로 이미 존재) |
| `reconcile_required` | `REJECTED` | `"stale_reconcile_required_orphan"` | broker_orders가 없고 reconciliation run이 failed인 Orphan. 최종 정리 대상. ([`order_manager.py`](src/agent_trading/services/order_manager.py:94)에 `RECONCILE_REQUIRED → REJECTED` 경로 이미 존재) |

### 1.6 SQL 기반 Cleanup 시뮬레이션

```sql
-- pending_submit cleanup 대상 (안전 조건 ALL 만족)
SELECT COUNT(*) FROM trading.order_requests o
LEFT JOIN trading.broker_orders bo ON bo.order_request_id = o.order_request_id
WHERE o.status = 'pending_submit'
  AND bo.broker_order_id IS NULL
  AND o.submitted_at IS NULL
  AND o.created_at < NOW() - INTERVAL '1 hour';
-- 결과: 13건 (오늘 1시간 미만 8건 제외)

-- reconcile_required cleanup 대상 (안전 조건 ALL 만족)
SELECT COUNT(*) FROM trading.order_requests o
LEFT JOIN trading.broker_orders bo ON bo.order_request_id = o.order_request_id
LEFT JOIN trading.reconciliation_order_links rol ON rol.order_request_id = o.order_request_id
LEFT JOIN trading.reconciliation_runs rr ON rr.reconciliation_run_id = rol.reconciliation_run_id
WHERE o.status = 'reconcile_required'
  AND bo.broker_order_id IS NULL
  AND o.submitted_at IS NULL
  AND (rr.status IS NULL OR rr.status = 'failed')
  AND o.created_at < NOW() - INTERVAL '1 hour';
-- 결과: 17건 (2건은 1시간 미만이지만 함께 카운트)
```

### 1.7 EOD Cleanup 실행 시점

| 시점 | 조건 | 비고 |
|------|------|------|
| 장 종료 후 (15:30 KST ~) | `is_after_hours = True` | intraday EXPIRED fallback 금지 정책과 일관성 유지 |
| post-submit sync loop 시작 직전 | before sync cycle | stale PENDING_SUBMIT 정리 후 broker truth sync 수행 |
| EOD 배치 | 별도 스크립트 또는 near-real-ops scheduler task | `--eod-cleanup` 플래그로 실행 |

### 1.8 복구 가능성

안전 조건을 만족하는 orphan은 `broker_orders` 레코드가 없고 `submitted_at IS NULL`이므로 복구가 불필요함. broker가 해당 주문을 인지할 방법이 없음. 따라서 `REJECTED`로의 전이는 데이터 무결성을 해치지 않음.

단, `execution_attempts`는 cleanup의 영향을 받지 않도록 해야 함. execution_attempts의 `trade_decision_id`는 order_requests와 별도로 존재하며, cleanup 후에도 audit trail로 보존되어야 함.
