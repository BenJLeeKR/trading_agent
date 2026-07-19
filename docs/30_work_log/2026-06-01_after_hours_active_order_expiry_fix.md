# after-hours 미해결 `submitted`/`acknowledged` 주문 정리 보강

## 배경

오늘 장 종료 후에도 다음 상태가 남아 있었다.

- `submitted`
- `reconcile_required`

확인 결과 이 주문들은 `submitted_at` 누락 문제가 아니라, 실제로 브로커 주문번호(`broker_native_order_id`)와 `broker_orders` 행이 존재하는 주문이었다.

즉, 기존 `EOD orphan cleanup` 대상이 아니었다.

## 핵심 원인

기존 after-hours 정리 로직은 두 갈래만 있었다.

1. `pending_submit` / 일부 `reconcile_required` orphan 정리
2. `reconcile_required` 경로에서만 stuck timeout / after-hours EXPIRED fallback

하지만 다음 케이스는 비어 있었다.

- `submitted`
- `acknowledged`

즉, 장 종료 후에도 브로커가 계속 `submitted`로만 응답하는 주문은
`reconcile_required` 경로로도 들어가지 않고,
orphan cleanup 조건도 만족하지 않아
영구적으로 남을 수 있었다.

## 추가로 확인된 구조적 포인트

- `ops-scheduler`의 after-hours 복구 배치는 사실상 `run_post_submit_sync_loop.py --after-hours --recovery` 1회 실행이다.
- 이 배치가 돌아도 `submitted` / `acknowledged` active order를 닫는 로직이 없었기 때문에 상태가 남았다.

## 수정 내용

### 1. `sync_order_post_submit()`에 after-hours active expiry 추가

`src/agent_trading/services/order_sync_service.py`

다음 조건을 모두 만족하면 after-hours에서 `EXPIRED`로 정리한다.

- `after_hours=True`
- `status_changed == False`
- fill 없음 (`fills_synced == 0`)
- 현재 상태가 `submitted` 또는 `acknowledged`
- 브로커 응답도 동일하게 `submitted` 또는 `acknowledged`
- 생성 후 grace period 초과

grace period:

- 일반 주문: 30분
- `broker_native_order_id`가 있고 `MARKET` 주문인 경우: 60분

### 2. 상태머신 허용 범위 보강

`src/agent_trading/services/order_manager.py`

다음 전이를 허용했다.

- `submitted -> expired`
- `acknowledged -> expired`

after-hours authoritative cleanup 경로에서 필요한 전이다.

### 3. `run_sync_cycle()` → `_sync_single_order()` → `sync_order_post_submit()`로 after-hours 컨텍스트 전달

기존에는 `sync_order_post_submit()`가 현재 호출이 after-hours인지 알 수 없었다.
이제 runner가 계산한 `after_hours` 값을 active order sync에도 전달한다.

## 테스트

추가/검증:

- `tests/services/test_order_sync_service.py`
  - 오래된 `submitted` 주문은 after-hours에서 `expired`
  - 최근 `submitted` 주문은 grace period 동안 유지
- 기존 after-hours orphan cleanup / stuck expiry 테스트 함께 재실행

실행 결과:

```bash
pytest -q tests/services/test_order_sync_service.py -k "AfterHoursSubmittedExpiry or after_hours_triggers_eod_orphan_cleanup or stuck_timeout_expires_after_hours_sell"
pytest -q tests/services/test_order_state_transition.py -k "submitted_to_acknowledged or acknowledged_to_filled or pending_submit_to_submitted"
```

- 모두 통과

## 운영 적용

코드 반영 후 `app`, `ops-scheduler`를 재기동하고,
필요 시 `run_post_submit_sync_loop.py --once --after-hours --recovery`를 수동 실행하여
당일 잔여 미해결 주문 정리를 다시 시도한다.
