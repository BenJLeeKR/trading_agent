# 2026-06-01 브로커 제출 예외 즉시 상태 전이

## 배경

`IGW00007` 같은 브로커 제출 실패가 발생하면 기존 구현은 다음 순서로 동작했다.

1. `order_submission_attempts`에 실패 시도 저장
2. 예외 재전파
3. 주문은 `pending_submit` 상태에 그대로 남음
4. 약 30분 뒤 stale cleanup이 `submission_failed_no_broker_id`로 정리

이 구조는 운영 해석이 늦고, 실제 직접 원인보다 후행 cleanup reason이 먼저 보이는
문제를 만들었다.

## 문제

브로커가 이미 “명확히 실패”를 반환했는데도 주문 상태가 즉시 정리되지 않았다.

대표 사례:

- `001740` 자동 SELL
- 브로커 응답: `HTTP 500 / IGW00007 / MCA 전문바디 구성 오류`
- 실제 direct cause는 브로커 제출 실패였지만 주문 상태는 한동안 `pending_submit`

## 목표

브로커 예외를 구조적으로 분기해 다음처럼 즉시 전이한다.

- **명확한 실패** → `REJECTED`
- **모호한 실패 / 정합성 확인 필요** → `RECONCILE_REQUIRED`
- **일반 코드 버그 / 프로그래밍 예외** → 기존처럼 raise 유지

## 구현

### 수정 파일

- `src/agent_trading/services/order_manager.py`
- `tests/services/test_order_submit_to_broker.py`

### 변경 내용

`OrderManager.submit_order_to_broker()`에 `except BrokerError` 분기를 추가했다.

#### 1. 브로커 예외 공통 처리

- `order_submission_attempts` 저장 유지
- `BrokerError`는 더 이상 무조건 재전파하지 않음

#### 2. 즉시 `RECONCILE_REQUIRED`로 보내는 케이스

다음 조건이면 reconciliation trigger 후 즉시 전이:

- `exc.requires_reconciliation == True`
- 또는 `error_type`이 아래 중 하나
  - `API_ERROR`
  - `NETWORK`
  - `NETWORK_ERROR`
  - `TIMEOUT`
  - `TEMPORARY_BROKER`

#### 3. 즉시 `REJECTED`로 보내는 케이스

다음은 terminal rejection으로 즉시 전이:

- `ORDER_REJECTED`
- `INVALID_REQUEST`
- `AUTHORIZATION`
- `AUTHENTICATION`
- 그 외 `needs_reconciliation`에 해당하지 않는 `BrokerError`

즉, `IGW00007`처럼 현재는 브로커가 확정 실패를 준 케이스는 더 이상
30분 동안 `pending_submit`에 남지 않는다.

#### 4. 일반 예외는 그대로 유지

`ValueError`, 프로그래밍 오류 등 `BrokerError`가 아닌 예외는 기존처럼 raise 유지.
운영 문제와 코드 버그를 분리하기 위한 결정이다.

## 테스트

실행:

```bash
pytest -q tests/services/test_order_submit_to_broker.py \
  tests/services/test_decision_submit_pipeline.py -k \
  "submit_exception or requires_reconciliation or uncertain or rejected"
```

결과:

- `7 passed`

### 추가한 검증

1. `BrokerError(ORDER_REJECTED, raw_code=IGW00007)` → 즉시 `REJECTED`
2. `BrokerError(API_ERROR, requires_reconciliation=True)` → 즉시 `RECONCILE_REQUIRED`
3. 일반 `ValueError` → 예외 전파 유지

## 기대 효과

### 운영 가시성 개선

주문 상세 화면과 DB에서 브로커 제출 실패가 즉시 반영된다.
이제 `submission_failed_no_broker_id`는 “후속 cleanup reason”으로만 남고,
직접 원인이 상태/사유에 더 빠르게 드러난다.

### 정합성 개선

브로커가 이미 실패를 반환한 주문이 오랫동안 `pending_submit`에 남아
후속 로직을 혼란스럽게 만들 가능성이 줄어든다.

## 반영

- `app` 재시작
- `ops-scheduler` 재시작
