# `submitted_at` 누락 보정 및 제출 상태 정상화

## 배경

오늘 장중 주문을 점검한 결과, 다음과 같은 비정상 패턴이 확인됐다.

- `order_requests.status = 'submitted'` 인데 `submitted_at IS NULL`
- `order_requests.status = 'reconcile_required'` 인데 실제 브로커 제출 시도 이력이 존재

이 상태는 운영 해석과 after-hours 복구 판단을 혼동시키며, 특히 "실제로 브로커에 전달된 주문"과 "아직 제출되지 않은 주문"을 필드 하나로 구분할 수 없게 만든다.

## 원인

원인은 `OrderManager.transition_to()` 경로에서 `SUBMITTED` 또는 제출 이후의 `RECONCILE_REQUIRED` / `REJECTED` 전이 시 `submitted_at`을 저장하지 않는 버그였다.

구체적으로:

1. `src/agent_trading/services/order_manager.py`
   - `_replace_status()`가 `status`, `reason`, `updated_at`만 바꾸고 `submitted_at`은 건드리지 않음
2. `src/agent_trading/repositories/postgres/orders.py`
   - `update_status()` SQL이 `submitted_at` 컬럼을 전혀 업데이트하지 않음
3. 결과적으로 브로커 제출이 성공/불확실/거절로 끝나도 `submitted_at`은 `NULL`로 남음

## 수정 내용

### 1. 제출 경로에서 `submitted_at` 명시 저장

`OrderManager.transition_to()` / `_transition_to_core()`에 `mark_submitted_at` 플래그를 추가했다.

- 브로커 제출이 실제로 발생한 경로에서만 `mark_submitted_at=True`
  - 정상 제출 → `SUBMITTED`
  - 불확실/조정필요 → `RECONCILE_REQUIRED`
  - 브로커 명시 거절 → `REJECTED`
  - 브로커 `BrokerError` 기반 즉시 `REJECTED` / `RECONCILE_REQUIRED`
- `BLOCKED` 같은 "브로커 제출 전 차단" 경로는 그대로 `submitted_at`을 남기지 않음

### 2. 저장소 레벨 보강

Postgres / InMemory `update_status()`에 `submitted_at` 인자를 추가했다.

- 서비스 레이어가 제출 시각을 명시하면 그대로 저장
- 기존 호환 경로로 `status='submitted'`만 들어오는 경우에는 fallback으로 현재 시각을 채움

### 3. 오늘 이미 잘못 저장된 행 보정

`order_submission_attempts.submitted_at`을 근거로 오늘 누락된 행을 보정했다.

보정 대상:

- `submitted`
- `reconcile_required`
- `rejected`

단, 실제 제출 시도 이력이 있는 주문만 업데이트했다.

## 검증

### 테스트

다음 테스트를 실행해 통과했다.

```bash
pytest -q tests/services/test_order_state_transition.py tests/services/test_order_submit_to_broker.py -k "submitted or reconciliation or rejected"
```

결과:

- `15 passed`

### DB 확인

오늘 주문 중 `submitted` / `reconcile_required` 상태에서 `submitted_at IS NULL` 건수:

- 수정 전: 19건 (`submitted=15`, `reconcile_required=4`)
- 수정 후: `0건`

샘플 검증:

- `22dadd3b-24f5-4200-9246-ef810df3af84` → `submitted_at` 정상 채움
- `7d391c54-124e-41f8-864e-945f6f362a5f` → `reconcile_required` 이지만 `submitted_at` 정상 채움

## 잔여 메모

- 과거 `rejected` 주문 중 `submitted_at NULL` 행이 일부 남아 있을 수 있다.
  - 이 중에는 실제 브로커 제출 전 차단(`BLOCKED`)이나 stale cleanup 성격의 행도 섞여 있을 수 있으므로, 이번 작업은 "실제 제출 이력이 있는 행"만 우선 보정했다.
- 다음 확인 포인트는 16:00 after-hours 복구 배치가 `submitted_at`에 의존하지 않더라도, 운영 해석상 제출 이력과 상태가 일관되게 보이는지다.
