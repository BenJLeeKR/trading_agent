# 주문 상세 API에 linked fill snapshot 요약 추가

## 목적

- `GET /orders/{id}` 응답만으로도 해당 주문에 연결된 `VTTC0081R` 체결 스냅샷 근거를 바로 읽을 수 있게 한다.
- operator가 주문 상태와 체결 증거를 대조할 때 `/fill-history`를 별도로 열지 않아도 핵심 체결 정보를 확인할 수 있게 한다.

## 적용 내용

### 1. `OrderDetail` 응답 모델 확장

- 파일: `src/agent_trading/api/schemas.py`
- 신규 필드:
  - `linked_fill_snapshot_summary: LinkedFillSnapshotSummary | None`

### 2. 신규 요약 모델 추가

- 파일: `src/agent_trading/api/schemas.py`
- 모델: `LinkedFillSnapshotSummary`
- 포함 필드:
  - `snapshot_count`
  - `broker_native_order_id`
  - `symbol`
  - `side`
  - `latest_fill_timestamp`
  - `latest_filled_quantity`
  - `max_filled_quantity`
  - `latest_fill_price`
  - `latest_ordered_quantity`
  - `latest_order_status_code`

### 3. 주문 상세 라우트 보강

- 파일: `src/agent_trading/api/routes/orders.py`
- `GET /orders/{id}`에서:
  1. 기존 주문 상세/제출시도 요약 조회
  2. `repos.broker_fill_snapshots.list_recent(order_request_id=uid)` 호출
  3. linked fill snapshot이 있으면 요약 생성 후 `detail.linked_fill_snapshot_summary`에 주입

### 4. 요약 규칙

- 최신 row 기준:
  - `broker_native_order_id`
  - `symbol`
  - `side`
  - `latest_fill_timestamp`
  - `latest_filled_quantity`
  - `latest_fill_price`
  - `latest_ordered_quantity`
  - `latest_order_status_code`
- 전체 row 기준:
  - `snapshot_count`
  - `max_filled_quantity`

## 테스트

- 파일: `tests/api/test_order_submission_attempts.py`
- 신규 테스트:
  - `test_order_detail_has_linked_fill_snapshot_summary`

검증 내용:
- 같은 `order_request_id`에 연결된 fill snapshot 2건을 넣고
- 주문 상세 응답에:
  - `snapshot_count == 2`
  - `broker_native_order_id == "0001234567"`
  - `latest_filled_quantity == 10.0`
  - `max_filled_quantity == 10.0`
  - `latest_fill_price == 70300.0`
  - `latest_ordered_quantity == 10.0`
  가 포함되는지 확인

## 실행 검증

- `pytest -q tests/api/test_order_submission_attempts.py tests/api/test_fill_history.py`
  - `26 passed`
- `python3 -m py_compile src/agent_trading/api/routes/orders.py src/agent_trading/api/schemas.py tests/api/test_order_submission_attempts.py`
  - 통과

## 기대 효과

1. 주문 상세만 봐도 linked fill snapshot 존재 여부를 즉시 파악 가능
2. `submitted/reconcile_required/filled` 상태를 체결 근거와 함께 해석 가능
3. 이후 `주문 상세 ↔ 체결내역 상세` 연동이나 `truth source` 표시 확장의 기반이 된다

## 다음 권장 작업

1. 주문 상세 API에 `truth_source` 요약(`fill_snapshot`, `broker_truth`, `position_fallback`) 추가
2. linked fill snapshot 요약을 기준으로 부분체결/완전체결 판정 근거를 주문 상세에 더 직접적으로 노출
3. `order_request_id → trade_decision_id` 기준 체결내역 drill-down API 정리
