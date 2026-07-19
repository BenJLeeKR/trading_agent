# 2026-06-04 linked fill snapshot 부분체결 진행도 수렴 보강

## 배경

- linked `VTTC0081R` fill snapshot이 주문 상태를 `PARTIALLY_FILLED`로 확정한 뒤,
  다음 sync에서 체결량이 더 늘어나도 상태가 그대로 `PARTIALLY_FILLED`면
  기존 구현은 다음 두 가지를 놓치고 있었다.
  1. `status_reason_message`가 이전 체결량 그대로 남음
  2. snapshot refresh가 다시 호출되지 않음

- 예:
  - 이전: `filled=3, remaining=7`
  - 다음 sync: 실제 linked fill snapshot 합계가 `filled=5, remaining=5`
  - 상태는 여전히 `PARTIALLY_FILLED`이므로 `status_changed=False`
  - 결과적으로 진행도는 DB row와 refresh side effect에 반영되지 않았다.

## 수정 내용

### 1. truth probe fill snapshot reason metadata 갱신
- 파일: `src/agent_trading/services/order_sync_service.py`
- 조건:
  - `probe_reason == FILL_SNAPSHOT`
  - `probe_status`는 resolve 되었음
  - 상태는 그대로지만 `status_reason_code/message` 내용이 달라짐
- 동작:
  - 같은 status 값으로 `repos.orders.update_status(...)` 호출
  - 최신 `filled / requested / remaining / source / odno`가 다시 저장됨

### 2. 부분체결 진행도 증가 시 refresh 재호출
- 조건:
  - `probe_reason == FILL_SNAPSHOT`
  - 현재 status = `PARTIALLY_FILLED`
  - reason message가 달라져 실제 체결 진행도가 늘어난 것으로 판단
- 동작:
  - `snapshot_refresh_cb`를 다시 호출
  - 상태가 바뀌지 않아도 계좌 cash/position/orderable 수렴을 촉진

### 3. 성공적 fill snapshot truth를 conflict error로 보지 않음
- 기존:
  - `TruthProbeReason.FILL_SNAPSHOT`도 `truth_probe_conflict:fill_snapshot`로 반환될 수 있었음
- 변경:
  - `FILL_SNAPSHOT`는 성공적 truth source이므로 `SyncOrderResult.error = None`

## 테스트

- `tests/services/test_order_sync_service.py`
  - linked fill snapshot partial refresh 시 `error is None`
  - 이미 `PARTIALLY_FILLED`인 주문이 `3 → 5`로 진행될 때
    - `status_reason_message`가 `filled=5`, `remaining=5`로 갱신되는지
    - `snapshot_refresh_cb`가 다시 호출되는지

## 검증

- `pytest -q tests/services/test_order_sync_service.py -k 'fill_snapshot_partial or partial_progress or PartialFillRefresh or partially_filled_to_filled_terminal'`
  - `4 passed`
- `python3 -m py_compile src/agent_trading/services/order_sync_service.py`
  - 통과

## 기대 효과

1. partial 상태의 체결 진행도가 주문 row에 누적 반영된다.
2. partial 상태에서도 cash / position / orderable amount 수렴이 더 빨라진다.
3. fill snapshot 기반 truth가 더 이상 conflict처럼 보이지 않는다.
