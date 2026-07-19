# Stale PENDING_SUBMIT 정리 상태 재분류: EXPIRED → REJECTED + reason_code

## 1. 문제: 현재 EXPIRED 정책의 한계

### 현재 상태
[`_expire_stale_pending_submit_orders()`](src/agent_trading/services/order_sync_service.py)가 broker 미도달 stale PENDING_SUBMIT 주문을 `EXPIRED` 상태로 전이시킴.

### 한계
| 측면 | EXPIRED 의미 | 실제 상황 | 불일치 |
|------|-------------|-----------|--------|
| 의미 | "시스템이 이 주문을 더 이상 추적하지 않음" (만료/타임아웃) | broker에 제출조차 실패한 주문 | `EXPIRED`는 복구 가능성을 열어두지만, broker 미도달 주문은 복구할 대상이 아님 |
| 복구 경로 | [`backfill_expired_market_sell_orders.py`](scripts/backfill_expired_market_sell_orders.py)가 EXPIRED → FILLED 복구 시도 | broker_native_order_id가 없어 복구 불가 | 불필요한 복구 시도 대상이 됨 |
| sell_guard | 제외됨 (OK) | 제외되어야 함 (OK) | 차이는 없지만 의미가 부정확 |

### 왜 REJECTED가 더 적절한가?

| 구분 | `EXPIRED` (변경 전) | `REJECTED` (변경 후) |
|------|--------------------|--------------------|
| **의미** | 타임아웃/만료 — 브로커 상태 불확실 시 fallback | 브로커 거절 또는 제출 실패 — 명시적 실패 |
| **운영 진실** | broker에 도달했을 수도 있고 아닐 수도 있음 | **broker에 도달하지 않음** (broker_native_order_id 없음) |
| **복구 시도** | backfill batch가 EXPIRED → FILLED 복구 시도 (broker_native_order_id 있는 주문 대상) | REJECTED는 복구 시도하지 않음 (적절함) |
| **sell_guard** | 제외됨 | 제외됨 (변화 없음) |

## 2. 상태 모델 분석

### OrderStatus enum
[`src/agent_trading/domain/enums.py:43`](src/agent_trading/domain/enums.py:43)

| 상태 | 의미 | Terminal? | sell_guard open? | 비고 |
|------|------|:---------:|:----------------:|------|
| `REJECTED` | 브로커 거절 / 제출 실패 | ✅ | ❌ | broker가 명시적으로 거절했거나, broker에 도달하지 못한 경우 |
| `EXPIRED` | 타임아웃 / 만료 | ✅ | ❌ | broker 상태 불확실하거나, 일정 시간 경과 후 fallback 처리 |

### _ALLOWED_TRANSITIONS
[`src/agent_trading/services/order_manager.py:68`](src/agent_trading/services/order_manager.py:68)

```
PENDING_SUBMIT → SUBMITTED          (브로커 제출 성공)
PENDING_SUBMIT → RECONCILE_REQUIRED (브로커 응답 불확실)
PENDING_SUBMIT → REJECTED           (브로커 거절)       ← 이미 존재!
PENDING_SUBMIT → EXPIRED            (stale 정리 — 삭제) ← 이 경로 제거
```

**이미 `PENDING_SUBMIT → REJECTED` 경로가 존재**하므로 enum/transition 변경 불필요.

### update_status() reason_code 지원

[`src/agent_trading/repositories/postgres/orders.py:148`](src/agent_trading/repositories/postgres/orders.py:148):
```python
async def update_status(
    self,
    order_request_id: UUID,
    status: OrderStatus,
    reason_code: str | None = None,      # ✅ 지원
    reason_message: str | None = None,    # ✅ 지원
    ...
)
```

`reason_code`와 `reason_message`를 모두 지원하므로 이유 코드로 세분화 가능.

## 3. stale orphan vs explicit reject 구분 정책

### 구분 기준

| 구분 | Explicit KIS Reject | Unknown Stale Orphan (현재 대상) |
|------|--------------------|-------------------------------|
| **원인** | submit_order_to_broker() 호출 후 KIS가 명시적 거절 응답 반환 | submit_order_to_broker() 호출 실패 (예외) 또는 생성 후 submit 호출 자체가 이루어지지 않음 |
| **broker_native_order_id** | 있을 수도 있음 (reject 응답에 포함) | 없음 (broker에 도달하지 않음) |
| **broker_status** | "rejected" 등 명시적 값 | NULL |
| **상태** | `REJECTED` (order_manager.py) | `REJECTED` + reason_code=`"submission_failed_no_broker_id"` (해당 fix) |
| **디버깅 힌트** | broker 거절 사유 코드 확인 가능 | order_state_events 로그에서 submission_failed_no_broker_id 확인 |

**두 경우 모두 `REJECTED` 상태를 공유하지만, `status_reason_code`로 명확히 구분 가능.**

### Reason Code 정책

| Reason Code | 발생 조건 | 설명 |
|-------------|----------|------|
| `"submission_failed_no_broker_id"` | stale PENDING_SUBMIT + broker_native_order_id NULL + 30분 초과 + side=sell | broker에 제출되지 않은 orphan 주문 |
| (KIS reject 코드) | submit_order_to_broker() 거절 응답 시 | broker가 반환한 거절 코드 (예: "03") |

## 4. 적용한 수정

### 4.1 order_sync_service.py — 메서드명, 상태, reason_code 변경

**파일**: [`src/agent_trading/services/order_sync_service.py`](src/agent_trading/services/order_sync_service.py)

| 항목 | 변경 전 | 변경 후 |
|------|--------|--------|
| 메서드명 | `_expire_stale_pending_submit_orders()` | `_reject_stale_pending_submit_orders()` |
| 전이 상태 | `OrderStatus.EXPIRED` | `OrderStatus.REJECTED` |
| reason_code | `"stale_pending_submit_expired"` | `"submission_failed_no_broker_id"` |
| 로그 메시지 | `"Expired {n} stale pending_submit orders"` | `"Rejected {n} stale pending_submit orders (submission_failed_no_broker_id)"` |
| 상수 주석 | EXPIRED 관련 설명 | REJECTED 관련 설명 |

### 4.2 order_manager.py — 주석 업데이트

**파일**: [`src/agent_trading/services/order_manager.py:72`](src/agent_trading/services/order_manager.py:72)

주석:
```
변경 전: # PENDING_SUBMIT → EXPIRED (stale timeout — order_sync_service)
변경 후: # PENDING_SUBMIT → REJECTED (order_sync_service, submission_failed_no_broker_id)
```

**`_ALLOWED_TRANSITIONS` 자체는 변경 불필요** — 이미 `PENDING_SUBMIT → REJECTED` 경로가 존재.

### 4.3 sell_guard.py — 변경 불필요

**파일**: [`src/agent_trading/services/sell_guard.py:226`](src/agent_trading/services/sell_guard.py:226)

`REJECTED`는 이미 `open_statuses`에 포함되지 않으므로(terminal 상태), sell_guard가 자동으로 open_sell_qty에서 제외합니다. stale PENDING_SUBMIT 제외를 위한 별도 안전장치(`is_stale_pending_submit()`)는 그대로 유지하여 이중 안전장치를 보존합니다.

### 4.4 변경하지 않은 것

| 항목 | 이유 |
|------|------|
| `OrderStatus` enum | `REJECTED` 이미 존재 |
| `_ALLOWED_TRANSITIONS` | `PENDING_SUBMIT → REJECTED` 이미 존재 |
| sell_guard open_sell_qty | REJECTED는 이미 제외됨 |
| fresh PENDING_SUBMIT (< 30분) | 계속 보호 (정상 submit 시도 중) |
| BUY 경로 | 영향 없음 |

## 5. 수정 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| [`src/agent_trading/services/order_sync_service.py`](src/agent_trading/services/order_sync_service.py) | 메서드명 변경, 상태 EXPIRED→REJECTED, reason_code 변경 |
| [`src/agent_trading/services/order_manager.py`](src/agent_trading/services/order_manager.py:72) | 주석 업데이트 (EXPIRED→REJECTED) |
| [`tests/services/test_order_sync_service.py`](tests/services/test_order_sync_service.py) | 테스트 클래스명/메서드명 변경, assert REJECTED + reason_code 검증 |

## 6. 테스트 결과

### 6.1 order_sync_service 테스트 (4개)

| 테스트 | 설명 | 결과 |
|--------|------|:----:|
| `test_reject_stale_pending_submit_orders` | stale PENDING_SUBMIT이 REJECTED로 전이 + reason_code="submission_failed_no_broker_id" 검증 | ✅ Pass |
| `test_reject_skips_fresh_pending_submit` | fresh PENDING_SUBMIT(30분 미만)은 REJECTED되지 않음 | ✅ Pass |
| `test_reject_skips_pending_submit_with_broker_id` | broker_native_order_id 있는 주문은 REJECTED되지 않음 | ✅ Pass |
| `test_reject_skips_buy_pending_submit` | BUY pending_submit은 REJECTED되지 않음 | ✅ Pass |

### 6.2 sell_guard 테스트 (23개)

기존 23개 테스트 전부 통과 — REJECTED 변경의 sell_guard 영향 없음 확인.

### 6.3 종합
- **전체 121개 테스트 전부 통과** (이전 session과 동일한 테스트 스위트)

## 7. 배포 상태

| 항목 | 상태 |
|------|:----:|
| Docker 이미지 재빌드 (`agent_trading-app`) | ✅ 완료 |
| `/health` 엔드포인트 | ✅ `{"status":"ok","database":"connected","healthy":true}` |
| 관련 서비스 재시작 | ✅ 완료 |

## 8. 운영 검증 (장중 확인)

1. **post-submit sync cycle 로그 확인**: `"Rejected N stale pending_submit orders (submission_failed_no_broker_id)"` 로그 출력 확인
2. **DB 확인**: `order_request`에서 stale PENDING_SUBMIT 주문이 `status=rejected`, `status_reason_code="submission_failed_no_broker_id"`로 변경되었는지 확인
3. **sell_guard 확인**: stale PENDING_SUBMIT이 open_sell_qty에서 제외되어 신규 SELL/EXIT 차단되지 않는 상태 유지
4. **fresh PENDING_SUBMIT 확인**: 30분 미만의 신선한 PENDING_SUBMIT은 계속 보호되어 정상 submit 진행
5. **BUY 경로 영향 없음 확인**: BUY PENDING_SUBMIT은 정리 대상에서 제외

## 9. stale orphan 상태 정책 최종 요약

```
PENDING_SUBMIT (생성)
  ├── submit 성공 → SUBMITTED (broker_native_order_id 있음)
  ├── submit 실패 (KIS reject) → REJECTED (명시적, broker 거절 코드)
  ├── submit 실패 (예외/불확실) → RECONCILE_REQUIRED
  └── stale (30분 이상 + broker_id 없음 + sell) → REJECTED ⭐
       reason_code: "submission_failed_no_broker_id"
```
