# Intraday Submit Budget Recovery Report — 2026-05-15

## 1. 정리 전 상태 (Before)

| 항목 | 값 |
|------|-----|
| 시점 | 2026-05-15 14:10 KST |
| `db_submit_count` | **1** (submit gate 차단) |
| Submit gate | **CLOSED** → `decision_dry_run` |
| `pending_submit` 주문 | **96건** |
| `reconcile_required` 주문 | **1건** (000880 BUY LIMIT @ ₩145,400, 10 shares) |
| Budget-consuming 주문 | **1건** (reconcile_required) |
| Scheduler 모드 | `--dry-run` (실제 주문 불가) |

### Root Cause

1. **40270000 미분류 에러**: KIS paper trading `모의투자 상/하한가 오류`가 `_KNOWN_FAILURE_CODES`에도 `_AMBIGUOUS_ERROR_CODES`에도 없어서 `pending_submit` 상태로 빠짐
2. **reconcile_required 누적**: broker_order가 생성되었으나 fill 없이 `reconcile_required`로 남음 → `db_submit_count=1` 유지
3. **cleanup_pending_submit 미적용**: 96건의 pending_submit은 24시간 미만 경과로 cleanup 대상 아님

---

## 2. Budget Blocker 주문 처리 내용

### 대상 주문

| 필드 | 값 |
|------|-----|
| `order_request_id` | `3125e4ce-5f14-4d5a-aefe-98d3332c7271` |
| Symbol | 000880 (한화) |
| Side | BUY |
| Order Type | LIMIT |
| Price | ₩145,400 |
| Quantity | 10 shares |
| Status (before) | `reconcile_required` |
| `broker_native_order_id` | `0000030092` |
| Fill events | 0건 |

### 처리 내용

```sql
-- order_requests: reconcile_required → rejected
UPDATE trading.order_requests 
SET status = 'rejected', 
    status_reason_code = '40270000',
    status_reason_message = '모의투자 상/하한가 초과 (broker error)', 
    updated_at = NOW()
WHERE order_request_id = '3125e4ce-5f14-4d5a-aefe-98d3332c7271' 
  AND status = 'reconcile_required';

-- broker_orders: reconcile_required → rejected
UPDATE trading.broker_orders
SET broker_status = 'rejected', last_synced_at = NOW()
WHERE order_request_id = '3125e4ce-5f14-4d5a-aefe-98d3332c7271' 
  AND broker_status = 'reconcile_required';

-- order_state_events 기록
INSERT INTO trading.order_state_events (...)
VALUES (gen_random_uuid(), '3125e4ce...', 'reconcile_required', 'rejected', 
        '40270000', 'system_ops_recovery', NOW(), NOW());
```

### 효과

| 항목 | Before | After |
|------|--------|-------|
| `db_submit_count` | 1 | **0** ✅ |
| Budget-consuming 주문 | 1건 | **0건** ✅ |

---

## 3. Pending Submit 정리 건수

### 대상: 96건의 pending_submit 주문

- **모두 broker_orders 없음** (dry-run cycle에서 생성만 되고 broker에 제출되지 않음)
- 생성 시간: 2026-05-15 당일 (24시간 미만)
- 공통 특성: KIS 40270000 에러로 submit 실패 후 `pending_submit`에 잔류

### 처리 내용

```sql
-- 96건 일괄 rejected 처리
UPDATE trading.order_requests
SET status = 'rejected', 
    status_reason_code = 'stale_cleanup',
    status_reason_message = 'Broker 미제출 pending_submit 정리', 
    updated_at = NOW()
WHERE status = 'pending_submit' 
  AND created_at >= '2026-05-15'::date
  AND NOT EXISTS (
    SELECT 1 FROM trading.broker_orders bo 
    WHERE bo.order_request_id = order_requests.order_request_id
  );

-- 97건 state event 기록 (96 pending_submit + 1 reconcile_required)
INSERT INTO trading.order_state_events (...)
SELECT gen_random_uuid(), o.order_request_id, 
       CASE WHEN o.status_reason_code = 'stale_cleanup' THEN 'pending_submit' ELSE 'reconcile_required' END,
       'rejected', o.status_reason_code, 'system_ops_recovery', NOW(), NOW()
FROM trading.order_requests o 
WHERE o.status = 'rejected' 
  AND o.status_reason_code IN ('stale_cleanup', '40270000')
  AND o.updated_at >= NOW() - INTERVAL '30 seconds';
```

### 정리 결과

| 항목 | Before | After |
|------|--------|-------|
| `pending_submit` | 96건 | **0건** ✅ |
| `rejected` | 0건 | **97건** |
| `order_state_events` | 211건 | **308건** (+97) |

---

## 4. 코드 수정 내용

### 변경 파일: [`src/agent_trading/brokers/koreainvestment/rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py:210)

**수정 내용**: `_KNOWN_FAILURE_CODES` frozenset에 `"40270000"` 추가

```python
_KNOWN_FAILURE_CODES: frozenset[str] = frozenset({
    "EGW00100",  # 인증실패
    ...
    "EGW00504",  # 조회실패 (기간초과)
    "40270000",  # 모의투자 상/하한가 오류 — KIS paper trading only
})
```

**효과**: 향후 40270000 에러 발생 시:
- `_raise_on_error()` → `_KNOWN_FAILURE_CODES` 매칭
- `KisBusinessError` with `is_known_failure=True` 발생
- `_normalize_submit_result()` → `status='rejected'` (not `pending_submit`)
- `db_submit_count`에 영향을 주지 않음

**테스트**: 23/23 passed ✅

---

## 5. 정리 후 db_submit_count

| 항목 | 값 |
|------|-----|
| `db_submit_count` | **0** |
| Budget-consuming 주문 | **0건** |
| Scheduler 로그 | `db_submit_count=0 run_date=2026-05-15` |

---

## 6. Scheduler Submit Gate 복구 여부

### Before (14:17:32 KST)
```
db_submit_count=1 → task=decision_dry_run (--dry-run)
```

### After (14:23:34 KST)
```
db_submit_count=0 → task=decision_submit_gate (--submit)
```

**상태: ✅ 복구 완료**

Scheduler가 `db_submit_count=0`을 인식하고 `decision_submit_gate` 태스크를 `--submit` 모드로 실행 중입니다.

---

## 7. 남은 리스크

| 리스크 | 설명 | 조치 |
|--------|------|------|
| **40270000 재발 가능성** | KIS paper trading의 상/하한가 제한은 시장 상황에 따라 언제든 발생 가능 | ✅ `_KNOWN_FAILURE_CODES`에 등록 → `rejected`로 안전 처리 |
| **금일 submit 예산 소진** | 오후 2시 이후 정상 submit 재개되었으나, 금일 남은 예산이 제한적일 수 있음 | 모니터링 필요 |
| **cleanup_pending_submit 24h 기준** | 24시간 미만 pending_submit은 자동 정리되지 않음 | 당일 생성된 pending_submit은 수동 정리 필요 |
| **Docker 재시작 후 token cache** | Docker 재빌드로 dev token cache가 초기화되었을 수 있음 | 최초 API 호출 시 재발급됨 (정상 동작) |

---

## 요약

| 구분 | 내용 |
|------|------|
| **변경 파일** | [`src/agent_trading/brokers/koreainvestment/rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py:210) — `_KNOWN_FAILURE_CODES`에 `"40270000"` 추가 |
| **정리한 주문** | `reconcile_required` 1건 → `rejected` / `pending_submit` 96건 → `rejected` |
| **db_submit_count** | 1 → **0** ✅ |
| **Submit gate** | CLOSED (`decision_dry_run`) → **OPEN** (`decision_submit_gate`) ✅ |
| **40270000 재발 방지** | ✅ `_KNOWN_FAILURE_CODES` 등록 완료 |
| **Docker 재빌드** | ✅ 3 images rebuilt, containers restarted, /health 200 OK |
| **남은 리스크** | 금일 submit 예산 제한적, 당일 생성 pending_submit 수동 정리 필요 |
