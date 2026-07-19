# 공통 BrokerAdapter 인터페이스 설계 v1

## 1. 목적

브로커별 API 차이를 코어 도메인에서 분리하기 위한 공통 계약을 정의한다.

## 2. 설계 원칙

- 코어는 브로커별 endpoint, header, TR ID를 알지 못한다.
- 브로커 전용 제약은 adapter 내부에 캡슐화한다.
- adapter는 공통 domain model만 반환한다.
- 지원하지 않는 기능은 명시적 unsupported error를 반환한다.

## 3. 인터페이스 초안

```python
from typing import Protocol, Sequence


class BrokerAdapter(Protocol):
    broker_name: str

    async def get_capabilities(self) -> "BrokerCapability":
        ...

    async def health_check(self) -> "BrokerHealth":
        ...

    async def authenticate(self) -> "BrokerSession":
        ...

    async def get_quote(self, symbol: str, market: str) -> "Quote":
        ...

    async def get_orderbook(self, symbol: str, market: str) -> "OrderBook":
        ...

    async def get_positions(self, account_ref: str) -> Sequence["Position"]:
        ...

    async def get_cash_balance(self, account_ref: str) -> "CashBalance":
        ...

    async def get_trading_session(self, market: str) -> "TradingSessionStatus":
        ...

    async def get_order_constraints(self, symbol: str, market: str) -> "OrderConstraint":
        ...

    async def submit_order(self, request: "SubmitOrderRequest") -> "SubmitOrderResult":
        ...

    async def cancel_order(self, request: "CancelOrderRequest") -> "CancelOrderResult":
        ...

    async def amend_order(self, request: "AmendOrderRequest") -> "AmendOrderResult":
        ...

    async def get_order_status(
        self, account_ref: str, client_order_id: str | None, broker_order_id: str | None
    ) -> "OrderStatusResult":
        ...

    async def get_fills(
        self, account_ref: str, broker_order_id: str, from_ts: str | None = None
    ) -> Sequence["FillEvent"]:
        ...

    async def list_open_orders(self, account_ref: str) -> Sequence["OrderStatusResult"]:
        ...

    async def get_recent_orders(
        self, account_ref: str, from_ts: str | None = None
    ) -> Sequence["OrderStatusResult"]:
        ...

    async def get_account_snapshot(self, account_ref: str) -> "AccountSnapshot":
        ...

    async def subscribe_market_data(self, subscriptions: Sequence["MarketDataSubscription"]) -> None:
        ...

    async def subscribe_order_events(self, account_ref: str) -> None:
        ...
```

## 4. 공통 모델

### 4.1 BrokerCapability

- 지원 자산군
- 지원 주문 유형
- 정정/취소 가능 여부
- 모의투자 지원 여부
- REST/WebSocket 지원 여부
- rate limit profile
- tick size rule kind
- market session calendar source
- supports_client_order_id
- supports_idempotency_key
- supports_market_order
- supports_limit_order
- supports_cancel_replace
- supports_partial_fill_event
- supports_order_event_stream
- supports_realtime_quote
- supports_realtime_orderbook
- max_orders_per_second
- max_orders_per_day
- max_symbol_subscriptions
- price_tick_rule_source
- lot_size_rule_source
- order_status_consistency_level

### 4.2 SubmitOrderRequest

- `account_ref`
- `client_order_id`
- `idempotency_key`
- `decision_id`
- `decision_context_id`
- `order_intent_id`
- `symbol`
- `market`
- `side`
- `order_type`
- `price`
- `qty`
- `time_in_force`
- `strategy_id`
- `correlation_id`
- `price_band_lower`
- `price_band_upper`
- `max_slippage_bps`
- `allow_partial_fill`
- `client_timestamp`
- `metadata`

### 4.3 SubmitOrderResult

- `accepted`
- `client_order_id`
- `idempotency_key`
- `broker_order_id`
- `broker_status`
- `normalized_status`
- `ack_timestamp`
- `exchange_timestamp` nullable
- `raw_code`
- `raw_message`
- `raw_payload_uri`
- `uncertain`
- `requires_reconciliation`

## 5. 오류 계약

adapter는 아래 공통 오류 유형 중 하나로 정규화해야 한다.

- `AuthenticationError`
- `AuthorizationError`
- `RateLimitError`
- `NetworkError`
- `InvalidRequestError`
- `UnsupportedCapabilityError`
- `OrderRejectedError`
- `TemporaryBrokerError`
- `DataUnavailableError`
- `AmbiguousOrderStateError`
- `StaleMarketDataError`
- `BrokerMaintenanceError`
- `CircuitOpenError`
- `ClockSkewError`

각 오류는 최소한 아래 필드를 포함한다.

- `broker_name`
- `error_type`
- `retryable`
- `raw_code`
- `raw_message`
- `correlation_id`
- `retry_after_seconds` nullable
- `requires_reconciliation` boolean
- `safe_to_retry` boolean
- `blocks_new_orders` boolean

## 6. capability resolution 규칙

- 코어는 주문 전 `BrokerCapability`를 캐시 조회한다.
- capability는 정적 값과 동적 값을 분리한다.
- 정적 값 예: 지원 상품, 주문 타입
- 동적 값 예: 현재 rate limit budget, 세션 가용성

## 7. 상태 정규화 규칙

브로커 상태는 내부 공통 상태로 매핑한다.

- new -> `ACKNOWLEDGED`
- partial -> `PARTIALLY_FILLED`
- filled -> `FILLED`
- canceled -> `CANCELLED`
- rejected -> `REJECTED`
- unknown -> `RECONCILE_REQUIRED`

## 8. 이벤트 수집 방식

- WebSocket 이벤트가 우선
- 누락 대비 REST 조회 폴백 필수
- 실시간 이벤트와 조회 응답은 동일한 정규화 함수 사용

## 9. 테스트 요구사항

- sandbox 또는 mock transport 기반 contract test
- 오류 코드 매핑 테스트
- 부분 체결/중복 응답/지연 응답 테스트
- 모의투자와 실전 URL 분리 테스트
- timeout 후 `submit_order`가 uncertain result를 반환하는지
- same idempotency_key 재요청 시 중복 주문을 만들지 않는지
- partial fill 이벤트가 중복 수신되어도 fill_event가 중복 저장되지 않는지
- WebSocket 이벤트 누락 후 REST fallback으로 상태 복구되는지
- broker_status unknown이 `RECONCILE_REQUIRED`로 매핑되는지
- clock skew가 감지되는지
- capability가 지원하지 않는 주문 타입을 명시적으로 거부하는지
