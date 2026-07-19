# 주문 실행 시퀀스 상세 설계 v1

## 1. 목적

주문 생성, 검증, 전송, 체결 반영, 정합성 복구의 표준 흐름을 정의한다.

## 2. 기본 시퀀스

```text
Decision Orchestrator
  -> AI Risk Agent
  -> AI Compliance Agent
  -> Hard Guardrail Engine
  -> Portfolio Engine
  -> Order Manager
  -> Broker Router
  -> KoreaInvestmentAdapter
  -> Broker API
  -> Fill / Order Update
  -> Reconciliation Service
```

## 3. 주문 생성 단계

### 3.1 입력

- strategy_id
- account_id
- decision_context_id
- symbol
- side
- order_type
- requested_price
- requested_qty
- rationale summary

### 3.2 사전 검증

1. 전략 활성 상태 확인
2. 거래 세션 상태 확인
3. 계좌 kill switch 상태 확인
4. 중복 signal 여부 확인
5. 최신 포지션 스냅샷 존재 여부 확인

## 4. 상태 전이

주문 엔티티는 아래 상태 머신을 따른다.

```text
DRAFT
-> VALIDATED
-> PENDING_SUBMIT
-> SUBMITTED
-> ACKNOWLEDGED
-> PARTIALLY_FILLED
-> FILLED
-> CANCEL_PENDING
-> CANCELLED
-> REJECTED
-> EXPIRED
-> RECONCILE_REQUIRED
```

규칙:

- `SUBMITTED`는 내부에서 브로커 전송 성공까지 의미한다.
- 브로커 응답 불명확 시 `RECONCILE_REQUIRED`로 전이한다.
- 최종 상태는 `FILLED`, `CANCELLED`, `REJECTED`, `EXPIRED`다.

## 4.1 Decision State와 Order State의 분리

decision lifecycle은 trade idea와 position lifecycle을, order lifecycle은 개별 주문 요청을 표현한다.

```text
WATCHLIST
-> CANDIDATE
-> APPROVED_SIGNAL
-> ORDER_READY
-> ORDER_BLOCKED
-> ORDER_CREATED
-> POSITION_OPEN
-> EXIT_PENDING
-> CLOSED
-> POST_TRADE_REVIEW
```

규칙:

- decision state는 trade idea 또는 position lifecycle을 표현한다.
- order state는 개별 `order_request`의 lifecycle을 표현한다.
- 하나의 decision은 여러 `order_request`를 가질 수 있다.
- 부분체결, scale-in, scale-out, cancel-replace는 같은 `decision_id` 아래 여러 `order_request`로 표현한다.
- decision state가 불명확하면 신규 `order_request`를 만들지 않는다.

## 5. 멱등성 설계

### 5.1 client order id

형식 예시:

```text
{env}-{account_id}-{trading_day}-{strategy_id}-{sequence}
```

조건:

- 계좌 단위 유일성 보장
- 재시도 시 같은 의도면 같은 id 사용
- 브로커 주문번호와 별도 매핑 유지

### 5.2 idempotency key

해시 입력:

- account_id
- symbol
- side
- order_type
- normalized_price
- normalized_qty
- decision_context_id

사용 위치:

- Order Manager insert
- Broker submit 직전 lock
- 재시도 판단 시 중복 차단

## 6. 브로커 제출 단계

### 6.1 submit 전 체크

- capability에서 주문 유형 지원 여부
- 가격단위/tick size 정규화
- 수량 단위 정규화
- 세션 시간 유효성
- 잔고 및 주문 가능 금액 조회 정책 확인

### 6.2 submit 결과 처리

- 성공 응답: 브로커 원주문번호 저장 후 `ACKNOWLEDGED`
- 명시적 거부: 오류 코드 정규화 후 `REJECTED`
- 네트워크 실패: 즉시 재주문 금지, 주문 조회 후 상태 확정
- rate limit: backoff 후 조회 우선

## 7. 체결 반영

체결 이벤트 입력원:

- WebSocket 실시간 체결
- REST 주문 조회 폴링
- 일괄 정산 파일 또는 체결 조회

체결 반영 규칙:

- fill 이벤트는 append-only 저장
- cumulative filled qty는 이벤트 합으로 계산
- 평균 체결가는 브로커 값과 내부 재계산을 둘 다 저장

## 8. 정합성 복구

### 8.1 재조회 트리거

- submit 응답 timeout
- WebSocket 단절
- 부분 체결 후 장시간 상태 정체
- 내부 포지션과 브로커 잔고 불일치

### 8.2 복구 절차

1. broker order inquiry 호출
2. broker fill inquiry 호출
3. account balance/position 조회
4. 내부 상태 재계산
5. 차이점 감사 로그 기록
6. 필요 시 신규 주문 중단

## 8.3 Unknown State Handling

```text
When order state is unknown, do not submit a new order for the same account/symbol/strategy/side until reconciliation is completed.
```

- submit timeout 후에는 즉시 재시도하지 않는다.
- `broker_order_id`가 없더라도 `client_order_id` 또는 시간/종목/수량/가격 기반으로 조회 가능한 범위까지 조회한다.
- 조회 불가 시 해당 `symbol/strategy`를 `RECONCILE_REQUIRED`로 잠근다.
- lock 해제는 reconciliation 성공 또는 운영자 승인으로만 가능하다.
- unknown state에서 risk-reducing exit가 필요한 경우 별도 emergency policy를 따른다.

## 8.4 Partial Fill Policy

- `PARTIALLY_FILLED` 상태의 잔량은 무기한 유지하지 않는다.
- partially filled 수량도 즉시 exposure와 risk 계산에 포함한다.
- 잔량 유지 가능 시간과 가격 이탈 기준은 execution config에서 관리한다.
- 부분체결이 발생한 즉시 stop/exit plan을 활성화한다.
- 동일 signal의 재진입 주문은 잔량 처리 완료 전 금지한다.

## 9. 취소/정정

- 취소와 정정도 별도 order request로 취급한다.
- 원주문과 변경주문을 연결하는 relation 저장이 필요하다.
- 원주문 상태가 불명확하면 취소보다 먼저 조회한다.

## 9.1 Cancel/Replace Safety

- 정정은 신규 주문이 아니라 원주문과 연결된 replacement request로 기록한다.
- 정정 실패 시 원주문 상태를 반드시 재조회한다.
- cancel request timeout 시 취소 완료로 간주하지 않는다.
- `CANCEL_PENDING` 상태에서는 동일 잔량에 대해 신규 주문을 내지 않는다.
- cancel/replace는 idempotency key를 별도로 가진다.

## 9.2 Order Event Ordering

- WebSocket fill 이벤트가 REST order acknowledgment보다 먼저 도착할 수 있다.
- 이벤트 timestamp와 ingest timestamp를 둘 다 저장한다.
- 상태 전이는 monotonic하게 적용하되, 늦게 도착한 이벤트도 append-only log에는 저장한다.
- terminal state 이후 도착한 이벤트는 reconciliation 대상으로 표시한다.
- broker native sequence가 있으면 우선 사용하고, 없으면 adapter별 ordering policy를 둔다.

## 10. 장애 처리 원칙

- 불확실한 상태에서 자동 재주문 금지
- 부분 체결 상태에서는 포지션 위험 기준으로 취소/유지 판단
- 브로커 장애 시 신규 진입 중단, 청산은 정책 기반 예외 허용

## 11. 모니터링 메트릭

- submit success rate
- broker reject rate
- average ack latency
- fill latency
- reconciliation mismatch count
- duplicate order prevention count
- order stuck in intermediate status
