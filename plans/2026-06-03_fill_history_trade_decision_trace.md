# 체결내역 API에 trade_decision 추적 경로 추가

## 목적

- `fill-history`가 단순히 `order_request_id`까지만 보여주는 수준을 넘어서,
  체결내역 → 주문 → 의사결정까지 한 번에 추적 가능하도록 한다.
- `Fill History Phase 3`의 첫 항목인 `order_request_id → trade_decision_id` 조회 경로 확장을 수행한다.

## 적용 내용

### 1. 응답 모델 확장

- 파일: `src/agent_trading/api/schemas.py`
- `FillHistoryItem.trade_decision_id: str | None` 추가

### 2. `/fill-history` 쿼리 파라미터 확장

- 파일: `src/agent_trading/api/routes/fill_history.py`
- 신규 파라미터:
  - `trade_decision_id`

### 3. trade_decision 기반 조회 경로 추가

- `trade_decision_id`가 주어지면:
  1. `repos.orders.list(OrderQuery(trade_decision_id=...))`로 matching order를 찾고
  2. 각 `order_request_id` 기준으로 fill snapshot을 조회한 뒤
  3. 정렬/limit 적용 후 응답한다.

### 4. 응답에 trade_decision_id 주입

- 각 fill snapshot row의 `order_request_id`가 있으면
  - `repos.orders.get(order_request_id)`로 주문을 조회하고
  - `trade_decision_id`를 `FillHistoryItem`에 포함한다.

## 테스트

- 파일: `tests/api/test_fill_history.py`
- 보강 내용:
  1. fill snapshot에 대응하는 `OrderRequestEntity` 2건 seed
  2. 응답 row에 `trade_decision_id`가 채워지는지 검증
  3. `trade_decision_id` 필터가 실제로 한 건만 반환하는지 검증

실행 결과:

- `pytest -q tests/api/test_fill_history.py tests/api/test_order_submission_attempts.py`
  - `26 passed`
- `python3 -m py_compile src/agent_trading/api/routes/fill_history.py src/agent_trading/api/schemas.py tests/api/test_fill_history.py`
  - 통과

## 기대 효과

1. 체결내역 API만으로 `fill → order_request → trade_decision` 추적 가능
2. `BUY 차단`, `주문 상세`, `체결내역`, `제출 이력`을 같은 lineage로 묶기 쉬워짐
3. 이후 `trade_decision_id` 기준 체결 drill-down이나 operator 분석 경로의 백엔드 기반이 됨

## 다음 권장 작업

1. 주문 상세 API에 `truth_source` 요약 추가 (`fill_snapshot`, `broker_truth`, `position_fallback`)
2. `order_sync_service`의 부분체결 판정을 `fill snapshot` 우선으로 더 확대
3. fill 발생 후 position/cash refresh 자동화
