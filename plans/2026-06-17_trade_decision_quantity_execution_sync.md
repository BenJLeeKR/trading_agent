# 2026-06-17 trade_decision 수량을 execution sizing 결과와 동기화

## 문제

- 현재 `trade_decisions.quantity`는 `assemble()` 시점의 request 수량을 그대로 저장한다.
- intraday loop 경로에서는 이 값이 placeholder `1`인 경우가 많아,
  실제 주문 수량 분석에서 `trade_decisions.quantity`가 지속적으로 오염된다.
- 반면 실제 제출 수량은 `order_requests.requested_quantity`에 있으므로,
  decision 단위 분석과 execution 단위 분석이 서로 다른 수량을 보게 된다.

## 목표

- `trade_decisions.quantity`를 `의사결정 placeholder`가 아니라
  `execution 단계에서 확정된 deterministic sizing 결과`로 정렬한다.
- 동시에 placeholder 원본은 잃지 않도록 `decision_json.execution_sizing`에 provenance를 남긴다.

## 설계 원칙

1. `TradeDecision`는 여전히 decision layer 산출물이다.
2. 다만 `quantity` 계열 필드는 operator 분석과 replay 기준에서
   execution sizing 결과가 더 중요하므로 execution 단계에서 보정한다.
3. `OrderManager / ReconciliationService / BrokerAdapter` 경계는 건드리지 않는다.
4. broker submit 이후 실제 체결 수량과는 별개다.
   - 이번 작업은 `filled_quantity`가 아니라 `deterministic sized quantity`를 저장하는 것이다.

## 반영 규칙

- Phase 1.5 sizing 이후:
  - `trade_decisions.quantity = effective_qty`
  - `trade_decisions.target_quantity = effective_qty`
  - `trade_decisions.max_order_value = price * effective_qty` (price가 있을 때)
  - `trade_decisions.target_notional = price * effective_qty` (price가 있을 때)
- zero quantity skip인 경우:
  - `quantity = 0`
  - `target_quantity = 0`
  - `max_order_value = null`
  - `target_notional = null`
- provenance:
  - `decision_json.execution_sizing.requested_quantity_before_sizing`
  - `decision_json.execution_sizing.resolved_quantity`
  - `decision_json.execution_sizing.applied_constraints`
  - `decision_json.execution_sizing.skip_reason`

## 기대 효과

- `trade_decisions` 단독 조회만으로도 실제 submit 직전 수량을 해석할 수 있다.
- `trade_decisions.quantity=1` placeholder 왜곡이 제거된다.
- 이후 동일 종목 반복 `REDUCE` 분석 시
  `trade_decisions.quantity`와 `order_requests.requested_quantity`의 의미 차이가 줄어든다.

## 후속 과제

- 같은 종목 반복 `REDUCE` 판단 자체를 줄이는 cooldown / anchor / no-change suppression 정책
- 과거 placeholder 오염 데이터 backfill 필요 여부 검토
