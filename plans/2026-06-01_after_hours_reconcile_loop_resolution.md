# 2026-06-01 after-hours `submitted`/`reconcile_required` 미해결 주문 해소

## 문제 요약

- 오늘 16시 이후에도 `submitted`, `reconcile_required` 주문이 남아 있었다.
- 앞선 수정으로 `submitted_at` 누락은 보정했지만, 상태 자체는 미해결로 유지됐다.
- 실제 원인은 두 단계였다.
  1. `reconcile_required -> submitted` 전이가 상태 머신에서 막혀 있었다.
  2. after-hours 만료 로직이 `submitted -> reconcile_required`로 한 번 흔들린 주문을 다시 `EXPIRED`로 정리하지 못했다.

## 확인된 현상

### 1. 로그와 실제 DB 상태 불일치

- `transition_to_authoritative()`가 브로커 truth로 `submitted`를 받아도
  `reconcile_required -> submitted` 전이가 불가능해서 DB 상태는 유지됐다.
- 그런데 함수는 `status_result`를 그대로 반환했고,
  `_sync_reconcile_required_orders()`는 이를 성공으로 집계했다.
- 결과적으로 로그에는 `resolved ... new_status=submitted`가 찍히지만
  실제 DB에는 `reconcile_required`가 남아 있었다.

### 2. after-hours active expire 루프

- 오래된 active 주문이 active sync에서 `submitted -> reconcile_required`로 바뀐 뒤,
  cycle 마지막 reconcile 단계에서 다시 `submitted`로 돌아왔다.
- 기존 after-hours expire 조건은
  `status_changed == False`일 때만 동작했기 때문에
  이 “한 번 흔들린” 주문들을 만료시키지 못했다.

## 적용한 수정

### 1. 상태 전이 허용

- 파일: `src/agent_trading/services/order_manager.py`
- `OrderStatus.RECONCILE_REQUIRED`의 허용 전이에 `OrderStatus.SUBMITTED` 추가

의도:
- 브로커 truth가 “아직 active submitted 상태”라고 말하면
  로컬 주문도 다시 active 상태로 되돌릴 수 있어야 한다.

### 2. 거짓 성공 집계 차단

- 파일: `src/agent_trading/services/order_sync_service.py`
- `transition_to_authoritative()`에서
  브로커 truth가 non-`RECONCILE_REQUIRED`를 반환해도
  실제 상태 전이가 일어나지 않으면 `None`을 반환하도록 수정

의도:
- 상태가 바뀌지 않았는데 reconcile 해소 성공으로 로그/집계되는 문제 방지

### 3. after-hours 만료 조건 확장

- 파일: `src/agent_trading/services/order_sync_service.py`
- after-hours active expire 조건을 다음으로 확장
  - 이전 상태가 `submitted` 또는 `acknowledged`
  - 현재 broker truth가 `submitted`, `acknowledged`, `reconcile_required`
  - 현재 order 상태가 `submitted`, `acknowledged`, `reconcile_required`
  - fill 없음
  - grace period 초과

의도:
- active sync 중간에 `reconcile_required`로 흔들린 주문도
  after-hours에서는 같은 cycle 안에 `EXPIRED`로 정리되게 함

## 테스트

### 추가/수정한 테스트

- `tests/services/test_order_state_transition.py`
  - `test_reconcile_required_to_submitted`
- `tests/services/test_order_sync_service.py`
  - `test_reconcile_required_moves_back_to_submitted_when_broker_truth_submitted`
  - `test_submitted_old_reconcile_required_still_expires_after_hours`

### 실행 결과

- `pytest -q tests/services/test_order_state_transition.py -k "reconcile_required_to_submitted or reconcile_required_to_acknowledged or reconcile_required_to_expired"`
  - `3 passed`
- `pytest -q tests/services/test_order_sync_service.py -k "AfterHoursSubmittedExpiry or reconcile_required_moves_back_to_submitted_when_broker_truth_submitted"`
  - `4 passed`

## 수동 복구 실행

컨테이너 반영 후 아래 recovery batch를 직접 실행했다.

```bash
docker exec agent_trading-app-1 python3 scripts/run_post_submit_sync_loop.py --once --after-hours --recovery
```

### 실행 결과

1. 첫 recovery cycle
   - 기존 `submitted` 15건 중 다수가 `expired` 또는 `filled`로 정리
   - `reconcile_required` 4건은 `submitted`로 복귀

2. 두 번째/세 번째 recovery cycle
   - `submitted -> reconcile_required -> submitted` 루프 재현
   - 조건 확장 후 같은 cycle 안에서 `EXPIRED` 정리 성공

## 최종 결과

오늘 주문 상태 집계:

- `expired`: 16
- `filled`: 3
- `rejected`: 26
- `submitted`: 0
- `reconcile_required`: 0

즉, 오늘 남아 있던 `submitted` / `reconcile_required` 미해결 주문은 모두 해소되었다.
