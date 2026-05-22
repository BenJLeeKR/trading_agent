# Stale PENDING_SUBMIT 매도 주문이 신규 청산(EXIT/SELL)을 차단하는 문제 Fix

## 1. 문제 요약
- 2026-05-22 09:12 KST, 삼성화재(`000810`) 청산 판단(`exit/sell`) 생성됨
- `order_request`로 이어지지 않음 (SKIPPED)
- 원인: 2026-05-20 생성된 `pending_submit` 매도 주문(10주)이 `sell_guard`의 `available_sell_qty` 계산에서 차단
- `available_sell_qty = position_qty(10) - open_sell_qty(10) = 0`

## 2. Root Cause

### 2.1 직접 원인: submit_order_to_broker() 실패 후 PENDING_SUBMIT 잔류
- [`order_manager.py`](src/agent_trading/services/order_manager.py)의 `submit_order_to_broker()`에서 예외 발생 시, 주문이 `PENDING_SUBMIT` 상태로 잔류
- broker에 도달하지 않았으므로 `broker_native_order_id = NULL`
- 상태 전이 테이블(`_ALLOWED_TRANSITIONS`)에 `PENDING_SUBMIT → EXPIRED` 경로가 없어 자동 정리 불가

### 2.2 구조적 원인 1: post-submit sync가 PENDING_SUBMIT을 skip
- [`order_sync_service.py`](src/agent_trading/services/order_sync_service.py:32)의 `_SYNCABLE_STATUSES`에 `PENDING_SUBMIT` 미포함
- `sync_order_post_submit()`이 PENDING_SUBMIT을 "non-syncable status"로 판단하고 skip
- broker 미도달 orphan 주문은 영원히 sync되지 않음

### 2.3 구조적 원인 2: sell_guard가 stale PENDING_SUBMIT까지 open_sell_qty에 포함
- [`sell_guard.py:226`](src/agent_trading/services/sell_guard.py:226)의 `_get_open_sell_qty()`가 `PENDING_SUBMIT`을 open sell로 집계
- broker에 도달하지 않은 orphan 주문까지 영구적으로 `available_sell_qty`를 감소시킴

### 2.4 현황 규모
- 총 **27건**의 orphan `pending_submit` sell 주문 존재 (5/14 ~ 5/21)
- 모두 `broker_native_order_id IS NULL`
- 각 10주씩 총 **270주** 허상 open sell 수량

## 3. Stale Orphan 판정 기준

다음 조건을 **모두** 만족하는 PENDING_SUBMIT 주문을 stale orphan으로 판정:

| 조건 | 설명 |
|------|------|
| `status = PENDING_SUBMIT` | 아직 broker에 제출 시도 중인 상태 |
| `broker_native_order_id IS NULL` | broker에 도달한 적 없음 (API 호출 실패) |
| `created_at < (now - 30분)` | 30분 이상 상태 변화 없음 |
| `side = sell` | 매도 주문만 대상 (현재 문제는 SELL) |

## 4. 적용한 수정

### 4.1 Layer 1 — post-submit sync stale 정리 경로 추가 (근본 해결)

**파일**: [`order_sync_service.py`](src/agent_trading/services/order_sync_service.py)

**변경사항**:
1. 상수 `_PENDING_SUBMIT_STALE_SECONDS: int = 1800` (30분) 추가
2. `PostSubmitSyncRunner` 클래스에 `_expire_stale_pending_submit_orders()` 메서드 추가
   - stale PENDING_SUBMIT 조회 → `EXPIRED`로 전이
   - `order_state_event` 생성 (`reason: stale_pending_submit_expired`)
3. `run_sync_cycle()` 시작 부분에서 호출 — 정리 후 sync 수행

**효과**: post-submit sync cycle이 실행될 때마다 30분 이상 stuck된 PENDING_SUBMIT 주문을 EXPIRED로 정리. EXPIRED는 sell_guard에서 open_sell_qty에 포함되지 않음.

### 4.2 Layer 2 — sell_guard stale PENDING_SUBMIT 제외 (이중 안전장치)

**파일**: [`sell_guard.py:226`](src/agent_trading/services/sell_guard.py:226)

**변경사항**:
- `_get_open_sell_qty()`에서 PENDING_SUBMIT 주문 처리 시:
  - stale 조건 확인 (broker_native_order_id NULL + created_at 30분 초과)
  - stale PENDING_SUBMIT은 open_sell_qty 집계에서 제외
  - fresh PENDING_SUBMIT은 계속 집계
  - broker_native_order_id가 있는 PENDING_SUBMIT은 항상 포함

**효과**: sync가 아직 정리하지 못한 stale 주문이라도 sell_guard가 신규 매도를 차단하지 않음.

### 4.3 상태 전이 허용 — order_manager.py

**파일**: [`order_manager.py`](src/agent_trading/services/order_manager.py:65)

**변경사항**:
- `_ALLOWED_TRANSITIONS`에 `PENDING_SUBMIT → EXPIRED` 경로 추가

**효과**: `order_repo.update_status()`가 유효성 검사를 통과하여 EXPIRED 전이가 가능해짐.

### 4.4 변경하지 않은 것
- `_SYNCABLE_STATUSES`는 변경하지 않음 (PENDING_SUBMIT이 syncable이 되는 건 의미상 부적합)
- BUY 경로는 수정하지 않음 (영향 없음)
- 신선한 PENDING_SUBMIT(30분 미만)은 sell_guard에서 정상 집계 (제출 직후 보호)
- SUBMITTED/ACKNOWLEDGED/RECONCILE_REQUIRED는 sell_guard에서 변경 없음

## 5. 수정 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| [`src/agent_trading/services/order_sync_service.py`](src/agent_trading/services/order_sync_service.py) | stale PENDING_SUBMIT → EXPIRED 정리 로직 추가 |
| [`src/agent_trading/services/sell_guard.py`](src/agent_trading/services/sell_guard.py) | stale PENDING_SUBMIT open_sell_qty 제외 |
| [`src/agent_trading/services/order_manager.py`](src/agent_trading/services/order_manager.py) | PENDING_SUBMIT → EXPIRED 전이 허용 |

## 6. 테스트 결과

### 6.1 sell_guard 테스트 (총 23개, 신규 4)

| 테스트 | 설명 | 결과 |
|--------|------|------|
| 기존 19개 | sell_guard 회귀 테스트 | ✅ Pass |
| `test_stale_pending_submit_excluded_from_open_sell_qty` | stale PENDING_SUBMIT이 open_sell_qty에서 제외되는지 | ✅ Pass |
| `test_fresh_pending_submit_included_in_open_sell_qty` | fresh PENDING_SUBMIT(30분 미만)은 계속 집계되는지 | ✅ Pass |
| `test_stale_pending_submit_with_broker_id_included` | broker_native_order_id가 있는 PENDING_SUBMIT은 stale이어도 포함되는지 | ✅ Pass |
| `test_pending_submit_buy_unaffected` | BUY PENDING_SUBMIT은 변경 없는지 | ✅ Pass |

### 6.2 order_sync_service 테스트 (총 98개, 신규 4)

| 테스트 | 설명 | 결과 |
|--------|------|------|
| 기존 94개 | order_sync 서비스 회귀 테스트 | ✅ Pass |
| `test_expire_stale_pending_submit_orders` | stale PENDING_SUBMIT이 EXPIRED로 전이되는지 | ✅ Pass |
| `test_expire_skips_fresh_pending_submit` | fresh PENDING_SUBMIT은 expire되지 않는지 | ✅ Pass |
| `test_expire_skips_pending_submit_with_broker_id` | broker_native_order_id 있는 주문은 expire되지 않는지 | ✅ Pass |
| `test_expire_skips_buy_pending_submit` | BUY pending_submit은 expire되지 않는지 | ✅ Pass |

### 6.3 종합
- **총 121개 테스트 전부 통과**

## 7. 000810 사례 전후 비교

### Before (2026-05-22 09:12 KST)
```
position_qty = 10
open_sell_qty = 10 (stale pending_submit 10주 포함)
available_sell_qty = 10 - 10 = 0
→ 신규 EXIT/SELL 차단 (SKIPPED)
```

### After (fix 적용 후)
```
position_qty = 10
open_sell_qty = 0 (stale pending_submit 제외됨)
available_sell_qty = 10 - 0 = 10
→ 신규 EXIT/SELL 정상 허용
```

### 추가: 기존 stale 주문 정리
- post-submit sync cycle 실행 시 stale PENDING_SUBMIT 27건이 EXPIRED로 전이됨
- `_expire_stale_pending_submit_orders()`는 sync cycle 시작 시 자동 실행

## 8. 배포 상태

| 항목 | 상태 |
|------|------|
| Docker 이미지 재빌드 | ✅ 완료 (`agent_trading-app`) |
| `/health` 엔드포인트 | ✅ `{"status":"ok","database":"connected"}` |
| 관련 서비스 재시작 | ✅ 완료 |

## 9. 운영 검증 (장중 확인 필요)

1. **post-submit sync cycle 로그 확인**: stale PENDING_SUBMIT이 EXPIRED로 전이되는 로그 확인
2. **DB 확인**: `order_request`에서 `status=expired`로 변경된 행 확인
3. **000810 신규 청산 가능**: position=10, stale pending_submit 제외되었으므로 신규 SELL/EXIT 주문 생성 가능
4. **sell_guard 로그 확인**: stale pending_submit이 open_sell_qty에서 제외되는 로그 확인
5. **BUY 경로 영향 없음 확인**

## 10. 추가 발견: 000810 trade_decision 불일치 (별도 이슈)

조사 중 발견된 추가 문제 — **이번 fix 범위 외**:
- 000810의 stale pending_submit과 연결된 `trade_decision_id = bdc1708a-...`는 `decision_type=hold, side=buy, risk_check_passed=false`
- HOLD+BUY + risk_rejected 판단인데 SELL 주문이 생성됨
- 이는 `assemble_and_submit()`에서 HOLD 결정에도 주문이 생성되는 버그 가능성
- 차기 세션에서 별도 조사 필요
