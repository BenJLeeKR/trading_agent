# KoreaInvestmentAdapter 상세 설계 v1

## 1. 목적

한국투자증권 KIS Developers Open API를 기본 브로커 구현체로 정의한다.

## 2. 책임 범위

- REST 인증 토큰 발급/갱신/폐기
- WebSocket approval key 발급 및 재연결
- 국내주식 기준 시세 조회, 잔고 조회, 주문, 주문 조회, 체결 반영
- KIS 고유 요청 헤더, TR ID, hashkey 처리
- KIS 응답을 공통 domain model로 정규화

## 3. 내부 모듈

### 3.1 auth_manager

- appkey/appsecret 관리
- access token 캐시
- token expiry 전 선갱신
- 갱신 실패 시 circuit open 및 알림

### 3.2 approval_key_manager

- WebSocket 접속키 발급
- 실시간 채널 재연결 시 키 재사용/재발급 정책

### 3.3 rest_client

- base URL 환경 분리
- 공통 header 설정
- rate limit aware retry
- request/response 감사 로그 훅

### 3.4 websocket_client

- 실시간 시세 및 주문/체결 이벤트 구독
- heartbeat 관리
- 연결 단절 시 backoff 재접속

### 3.5 normalizer

- 주문/체결/잔고/시세 응답 공통 모델 변환
- raw code와 normalized status 동시 보존

## 4. 환경 분리

### 4.1 live

- 실계좌 credential
- 실계좌 base URL
- 실계좌 계좌번호
- 보수적 주문 정책

### 4.2 paper

- 모의투자 credential
- 모의투자 base URL
- 별도 계좌 매핑
- 일부 capability 차이 허용

규칙:

- live와 paper는 같은 account entity를 공유하지 않는다.
- credential 저장 위치도 분리한다.

## 5. 인증 생명주기

### 5.1 access token

1. 어댑터 시작 시 토큰 캐시 조회
2. 없거나 만료 임박 시 새 토큰 발급
3. 응답에서 expiry를 파싱해 안전 마진을 두고 갱신
4. 401/인증 오류 발생 시 단일 flight로 재발급

### 5.2 approval key

1. WebSocket 구독 시작 전 발급
2. 연결 종료 또는 인증 실패 시 재발급 여부 판단
3. approval key 만료와 access token 만료는 별도 관리

## 6. 주문 처리 규칙

### 6.1 submit_order

- 필요한 KIS 헤더와 body는 adapter 내부에서 조합
- hashkey 필요 시 본문 기반으로 생성
- client order id와 broker native order id를 별도 저장

### 6.2 실패 처리

- HTTP 성공이어도 비즈니스 응답 오류는 `OrderRejectedError` 가능
- timeout 발생 시 즉시 재주문하지 않고 주문조회로 상태 확인
- KIS 응답 코드 원문은 감사 로그에 보관

### 6.3 부분 체결

- 실시간 체결 이벤트 우선 반영
- 장 종료 전까지 잔량 상태를 주기 조회

## 6.4 KIS Operation Mapping Table

| Operation | Adapter Method | Required Capability | Auth | Hash Required | Reconciliation Impact |
|---|---|---|---|---|---|
| domestic stock order submit | `submit_order` | `kr_stock_order` | access token | broker-doc-dependent | high |
| domestic stock order status inquiry | `get_order_status` | `kr_stock_order_query` | access token | broker-doc-dependent | high |
| domestic stock balance inquiry | `get_positions` / `get_cash_balance` | `kr_stock_balance_query` | access token | broker-doc-dependent | high |
| realtime quote subscribe | `subscribe_market_data` | `websocket_quote` | approval key | no | medium |
| realtime fill subscribe | `subscribe_order_events` | `websocket_order_event` | approval key | no | high |

## 6.5 KIS-Specific Ambiguous State Policy

- HTTP timeout
- 응답 수신 전 연결 종료
- KIS 비즈니스 오류 코드가 성공/실패를 명확히 의미하지 않는 경우
- WebSocket 주문 이벤트 지연
- REST 주문조회에서 주문이 즉시 조회되지 않는 경우

정책:

```text
submit_order 재호출 금지
-> get_recent_orders 또는 get_order_status 우선
-> open order / fill / balance 조회
-> internal order state를 RECONCILE_REQUIRED로 전환
-> reconciliation 완료 전 동일 account/symbol/strategy/side 신규 주문 금지
```

## 6.6 Token and Approval Key Concurrency

- 토큰 재발급은 single-flight로 처리한다.
- 동시에 여러 worker가 토큰을 갱신하지 못하도록 distributed lock을 사용한다.
- 토큰 갱신 실패 시 즉시 주문 중단 circuit을 연다.
- approval key 재발급 중에는 WebSocket 재구독 순서를 보장한다.
- 인증 실패가 반복되면 credential misconfiguration으로 분류하고 운영자 알림을 보낸다.

## 6.7 WebSocket Recovery and Gap Fill

- WebSocket disconnect 시 마지막 수신 timestamp와 sequence를 저장한다.
- 재연결 후 누락 구간을 REST 조회로 보강한다.
- sequence가 제공되지 않는 경우 timestamp 기반 gap detection을 수행한다.
- gap fill 완료 전 해당 종목의 fast execution signal은 stale로 표시한다.
- 주문/체결 이벤트 채널의 gap은 market data gap보다 더 높은 severity로 처리한다.

## 6.8 KIS Rate Limit and Backoff Policy

Rate limit 정책은 ``plan_docs/detailed_design/10_broker_rate_limit_and_capacity_policy.md``에
상세히 정의되어 있으며, 아래는 KIS 공식 발표 (2026-04-20) 기준 capability와
현재 코드 enforcement 상태를 요약한 표이다.

| Capability | KIS 공시 값 (2026-04-20) | Code Enforcement | 문서 상태 |
|---|---|---|---|
| **실전 REST RPS** | 계좌당 초당 18건 (이전 15 → 18 상향) | Token-bucket safety scaling: [`build_kis_budget_manager()`](src/agent_trading/brokers/rate_limit.py:351)에서 `real_rest_rps=18` 기본값; 5-bucket 분배 | [`10_broker_rate_limit_and_capacity_policy.md`](plan_docs/detailed_design/10_broker_rate_limit_and_capacity_policy.md) §12, §14 |
| **모의 REST RPS** | 계좌당 초당 1건 | `paper_rest_rps=1` 기본값; paper env → 3-bucket 단순 분배 | 동문 §12, §14.3 |
| **Auth token** (`/oauth2/tokenP`) | 1 rps | AUTH bucket (실전: 0.12 rps, cap 6)에서 간접 보호; 별도 1 rps strict cap 없음 | 동문 §12 — **※ 후속작업 #1** |
| **Approval key** (`/oauth2/Approval`) | 1 rps | AUTH bucket 공유; 별도 1 rps strict cap 없음 | 동문 §12 — **※ 후속작업 #1** |
| **WebSocket 등록** | 계좌당 41건 | [`SubscriptionBudget`](src/agent_trading/brokers/base.py:26) `max_subscriptions=100` (KIS 41 초과); 별도 41 제한 없음 | 동문 §12 — **※ 후속작업 #2** |
| **동시호출 권장 간격** | 100~150ms | Token-bucket refill rate로 간접 반영; 별도 hard interval 없음 | 동문 §12 |
| **Global REST Cap** (계좌+key 기준) | 초당 18건 (실전) | Safety scaling만 존재; strict global REST cap 미구현 | 동문 §14.6 — **※ 후속작업 #3** |

- rate limit은 quote, order, inquiry, auth operation 별로 분리해서 추적한다.
- 주문 관련 rate limit에 접근하면 신규 진입 주문을 제한한다.
- 상태 조회 rate limit은 reconciliation에 영향을 주므로 별도 예산을 남겨둔다.
- backoff는 operation별로 다르게 적용한다.
- rate limit 초과는 단순 retry가 아니라 circuit breaker와 연동한다.
- KIS capability 구분표의 상세 bucket 분배는 ``10_broker_rate_limit_and_capacity_policy.md`` §14.2 참조.

## 6.9 Decimal and Rounding Policy

- 모든 가격, 수량, 금액은 float가 아니라 Decimal을 사용한다.
- KIS 문자열 숫자는 normalizer에서 Decimal로 변환한다.
- tick size 반올림은 주문 side별로 다르게 처리한다.
- BUY limit price는 의도보다 공격적으로 올라가지 않도록 정책화한다.
- SELL limit price는 의도보다 불리하게 내려가지 않도록 정책화한다.
- 세금/수수료는 별도 필드로 분리한다.
- adapter는 반올림 전 값과 반올림 후 값을 모두 audit log에 남긴다.

## 7. 시세 및 계좌 데이터 처리

- 종목 마스터는 별도 동기화 잡으로 관리
- quote와 orderbook는 실시간 우선, snapshot 보조
- 계좌 잔고와 포지션은 주문 전후 및 주기적으로 조회

## 8. 정규화 예시

### 8.1 주문 상태

- KIS 접수 -> `ACKNOWLEDGED`
- 일부 체결 -> `PARTIALLY_FILLED`
- 전부 체결 -> `FILLED`
- 거부 -> `REJECTED`
- 조회 불가/모호 -> `RECONCILE_REQUIRED`

### 8.2 금액/수량

- 문자열 숫자 응답은 Decimal로 변환
- 통화/세금/수수료는 별도 필드로 분리

## 9. 관측성

필수 메트릭:

- token refresh success/failure
- websocket reconnect count
- order submit latency
- order reject by code
- quote delay
- REST 4xx/5xx count

필수 로그:

- request id
- TR ID
- account ref masked
- endpoint name
- normalized result

## 10. 보안

- appkey/appsecret은 평문 파일 저장 금지
- 민감정보는 마스킹 후 로그
- raw payload 저장 시 계좌번호와 토큰 마스킹

## 11. 구현 시 재확인 항목

구현 직전에 최신 공식 문서에서 반드시 재확인할 항목:

- 실전/모의 base URL
- 토큰 발급 endpoint
- approval key 발급 절차
- 주문/정정/취소 TR ID
- 국내주식 주문 가능 시간 및 제약
- rate limit 정책
- hashkey 적용 범위
