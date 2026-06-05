# 2026-06-04 부분체결 시 snapshot refresh 트리거 보강

## 배경

- `fill-triggered snapshot refresh` 자동화는 이미 구현되어 있었지만,
  실제 코드상 refresh callback은 `OrderStatus.FILLED`로 바뀐 경우에만 호출되고 있었다.
- 그러나 `PARTIALLY_FILLED`도 이미
  - 포지션 변화
  - 현금 변화
  - orderable amount 변화
  를 만들 수 있으므로, 다음 sizing/guard 수렴을 위해 즉시 refresh가 필요하다.
- 특히 linked `VTTC0081R` fill snapshot이 부분체결을 먼저 알려주는 경로에서는
  상태는 `PARTIALLY_FILLED`로 바뀌지만 refresh는 누락되고 있었다.

## 수정 내용

### 1. truth probe 조기 반환 경로 보강
- 파일: `src/agent_trading/services/order_sync_service.py`
- 기존:
  - truth probe가 `FILLED`를 반환한 경우에만 `snapshot_refresh_cb` 호출
- 변경:
  - truth probe가 `PARTIALLY_FILLED` 또는 `FILLED`를 반환하면 refresh 호출

### 2. 일반 broker status 경로 보강
- 파일: `src/agent_trading/services/order_sync_service.py`
- 기존:
  - 일반 `get_order_status()` 경로도 `FILLED`만 refresh
- 변경:
  - 상태가 새로 `PARTIALLY_FILLED` 또는 `FILLED`가 되면 refresh 호출

## 테스트

- `tests/services/test_order_sync_service.py`
  - 일반 broker partial fill 시 refresh 호출
  - linked fill snapshot partial fill 시 refresh 호출

## 검증

- `pytest -q tests/services/test_order_sync_service.py -k 'PartialFillRefresh or fill_snapshot_partial or partially_filled_to_filled_terminal or filled_without_new_fills_no_refresh'`
  - `4 passed`
- `python3 -m py_compile src/agent_trading/services/order_sync_service.py`
  - 통과

## 기대 효과

1. 부분체결 직후 포지션/현금/orderable amount가 더 빨리 수렴한다.
2. linked fill snapshot 기반 자동 판정이 실제 계좌 snapshot 수렴까지 이어진다.
3. 다음 주문 sizing이 오래된 cash/position을 보는 시간을 줄일 수 있다.
