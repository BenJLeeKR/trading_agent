# 브로커 Rate Limit 및 Capacity 정책 v1

## 1. 목적

이 문서는 브로커 API 호출 제한을 단순 성능 이슈가 아니라 **주문 안전성 제약**으로 다룬다.

핵심 전제:

- 조회 예산이 고갈되면 주문 상태 확인과 reconciliation이 막힌다.
- 이 상태는 중복 주문, 상태 불명확, 포지션 불일치로 이어질 수 있다.
- 따라서 rate limit 관리 대상은 throughput이 아니라 **주문 경로 안정성**이다.

기본 대상은 한국투자증권 KIS REST/WebSocket이며, 다른 브로커에도 같은 정책 구조를 적용한다.

## 2. 정책 원칙

- 주문, 조회, reconciliation 호출은 동일한 예산으로 보지 않는다.
- 신규 진입보다 상태 확인과 정합성 복구 예산이 우선이다.
- rate limit 임박 시 더 많은 주문을 내는 것이 아니라 universe와 분석 대상을 축소한다.
- WebSocket은 REST 예산 절약 수단이지만, gap fill을 위한 REST 예산은 별도로 남겨둔다.

## 3. Operation Bucket 분리

최소한 아래 버킷으로 분리한다.

### 3.1 Auth Bucket

- access token 발급/갱신
- approval key 발급/갱신

### 3.2 Order Bucket

- 신규 주문
- 취소
- 정정

### 3.3 Inquiry Bucket

- 주문 상태 조회
- 미체결 조회
- 최근 주문 조회
- 잔고/포지션/현금 조회

### 3.4 Reconciliation Bucket

- submit timeout 후 상태 확인
- unknown state 복구
- WebSocket gap fill
- 강제 상태 동기화

### 3.5 Market Data Bucket

- quote
- orderbook
- bars
- instrument master refresh

## 4. Priority Ordering

rate limit이 빡빡할 때 우선순위는 아래와 같다.

1. auth recovery
2. reconciliation
3. open order / fill inquiry
4. risk-reducing exit order
5. 일반 주문 상태 조회
6. 신규 진입 주문
7. 비핵심 market data polling

의미:

- 신규 진입 예산보다 reconciliation 예산을 먼저 보호한다.
- 조회 예산이 부족하면 신규 진입을 줄이고 상태 복구 예산을 남긴다.

## 5. Rate Limit Budgeting

### 5.1 세션별 예산

각 세션은 아래 예산을 가진다.

- order budget
- inquiry budget
- reconciliation reserve
- market data reserve
- websocket subscription budget

### 5.2 Reconciliation Reserve

- reconciliation reserve는 일반 주문 조회에 소진하면 안 된다.
- unknown state가 하나라도 발생하면 reserve를 사용해 상태 확인을 우선 수행한다.

### 5.3 Universe Shrink Policy

rate limit 근접 시:

- 신규 분석 대상 종목 수 축소
- quote polling 주기 완화
- 비핵심 signal refresh 축소
- 신규 진입 주문 억제

즉, **계산을 줄여서 예산을 아끼는 것**이 먼저다.

## 6. WebSocket Subscription Capacity

- 종목 수가 늘어날수록 quote/orderbook/order-event subscription budget을 명시적으로 관리한다.
- critical subscription과 optional subscription을 구분한다.

권장 분류:

- critical
  - 보유 종목
  - 미체결 주문 종목
  - 즉시 진입 후보 상위 소수 종목

- optional
  - watchlist 하위 후보
  - 비보유 관찰 종목

budget 초과 시 optional부터 제거한다.

## 7. Cache TTL 정책

REST 호출 절감을 위해 cache를 사용하되, TTL은 데이터 성격별로 다르게 둔다.

예:

- instrument master: 길게
- trading session status: 짧게
- quote snapshot: 매우 짧게
- account snapshot: 주문 직전에는 캐시 대신 새 조회 또는 freshness 확인

원칙:

- stale cache로 신규 주문을 허용하지 않는다.
- cache miss보다 stale cache가 더 위험한 데이터는 강한 freshness 검증이 필요하다.

## 8. Throttling / Backoff / Circuit Breaker

### 8.1 Throttling

- 버킷별 토큰 버킷 또는 leaky bucket 사용
- auth / order / inquiry / reconciliation 버킷을 분리

### 8.2 Backoff

- 429 또는 broker-specific rate limit error는 operation별 다른 backoff를 적용
- reconciliation 호출은 완전 차단하지 말고 최소 reserve를 유지

### 8.3 Circuit Breaker

다음 조건에서 circuit open 가능:

- auth 반복 실패
- order bucket 지속 초과
- inquiry bucket 고갈
- broker maintenance 감지
- unknown state 급증

open 시 정책:

- 신규 진입 중단
- 위험 축소 주문만 제한적 허용
- reconciliation 우선

## 9. Unknown State와 Rate Limit의 결합 정책

이 문서의 핵심 정책:

```text
If inquiry budget is insufficient to confirm order state,
block new entries before placing additional orders.
```

상세 규칙:

- unknown state 발생 후 inquiry/reconciliation 예산이 부족하면 신규 진입 주문을 차단한다.
- 상태 확인이 안 된 주문과 같은 `account/strategy/symbol/side`에 대해서는 lock을 유지한다.
- broker 응답이 불명확한 상태에서 order bucket이 남아 있어도 재주문하지 않는다.

## 10. Monitoring Metrics

- bucket utilization by operation type
- reconciliation reserve remaining
- websocket subscription usage
- rate limit error count
- backoff count
- circuit open duration
- unknown state count
- inquiry skipped due to budget exhaustion
- new entries blocked due to rate-limit safety policy

## 11. Trigger -> Action 예시

### 11.1 Inquiry Budget Low

- trigger: inquiry bucket usage above threshold
- action:
  - candidate universe 축소
  - quote polling 완화
  - 신규 진입 보수화

### 11.2 Reconciliation Reserve Depleted

- trigger: reserve below minimum threshold
- action:
  - 신규 진입 즉시 중단
  - open order / fill / balance 확인만 수행

### 11.3 WebSocket Subscription Saturation

- trigger: subscription budget 초과 임박
- action:
  - optional watchlist 구독 해제
  - critical symbols only 유지

## 12. KIS 적용 원칙

- KIS의 실제 limit 값은 문서화된 capability/config에서 관리한다.
- 코드에 하드코딩하지 않는다.
- REST quote/order/inquiry/auth를 같은 버킷으로 취급하지 않는다.
- approval key / access token concurrency는 single-flight로 관리한다.

## 13. v1 권장 구현 범위

- REST operation bucket 분리
- reconciliation reserve 도입
- unknown state 시 신규 진입 차단
- websocket subscription budget
- basic backoff
- circuit breaker

v1에서는 정확한 broker 수치보다 **예산 분리 구조와 fail-safe 정책**을 먼저 구현한다.

## 14. KIS 환경별 REST RPS → Token Bucket Safety Scaling

### 14.1 개요

KIS API 문서는 환경별 aggregate REST RPS를 제공한다:

- 실전투자 (`live`/`real`): **15 RPS**
- 모의투자 (`paper`): **1 RPS**

이 수치는 5개 독립 token bucket (AUTH, ORDER, INQUIRY, MARKET_DATA, RECONCILIATION)의
**safety scaling baseline**으로 사용된다. 각 bucket은 독립적으로 동작하므로 aggregate
total이 strict하게 보장되지 않는다 — 의도적인 설계로, bucket 간 경합이 발생해도
한 bucket의 고갈이 다른 bucket에 영향을 주지 않도록 한다.

> **현재 구현은 per-bucket safety scaling이다. exact global REST cap이 아니다.**
> strict global cap이 필요하면 14.6 참고.

### 14.2 Bucket 분배표 (v1 Safety Scaling)

| Bucket | Weight | Paper (1 RPS) | Live (15 RPS) |
|--------|--------|---------------|---------------|
| AUTH | 0.017 | 0.017 rps / cap 1 | 0.10 rps / cap 5 |
| ORDER | 0.10 | 0.10 rps / cap 1 | 2.00 rps / cap 5 |
| INQUIRY | 0.50 | 0.50 rps / cap 1 | 5.00 rps / cap 10 |
| MARKET_DATA | 0.50 | 0.50 rps / cap 1 | 5.00 rps / cap 20 |
| RECONCILIATION | 0.10 | 0.10 rps / cap 1 | 1.00 rps / cap 5 |
| **Sum** | **1.217** | **~1.2 rps** | **~13.1 rps** |

Capacity (burst)는 환경별 baseline capacity를 직접 사용한다:
- Paper: 모든 bucket `capacity = max(1, int(total_rps * 1))` → 모두 1
- Live: `capacity = max(1, int(baseline_cap * scale))` where `scale = total_rps / 15.0`
  - baseline capacities: auth=5, order=5, inquiry=10, market_data=20, reconciliation=5

### 14.3 환경 정규화

- `KIS_ENV=paper` → paper bucket rates
- `KIS_ENV=real` → `live`로 정규화 → live bucket rates
- `KIS_ENV=live` → live bucket rates

### 14.4 Env Override

두 env var로 전체 RPS 기준점을 override할 수 있다:

- `KIS_REAL_REST_RPS` (기본값 15) — live 환경의 aggregate RPS baseline
- `KIS_PAPER_REST_RPS` (기본값 1) — paper 환경의 aggregate RPS baseline

override 시 각 bucket의 refill rate는 `baseline_rate * (override_rps / default_rps)`로
비례 scaling된다. 예: `KIS_REAL_REST_RPS=30` → 모든 live bucket rate가 2배가 된다.

### 14.5 구현 위치

- Resolver 함수: `src/agent_trading/config/settings.py` (`_resolve_kis_real_rest_rps`, `_resolve_kis_paper_rest_rps`)
- Factory 함수: `src/agent_trading/brokers/rate_limit.py` (`build_kis_budget_manager()`)
- Runtime wiring: `src/agent_trading/runtime/bootstrap.py` (`_build_kis_adapter()`)

### 14.6 향후 확장: Strict Global REST Cap

현재 v1은 per-bucket safety scaling만 적용한다. 만약 strict global REST cap이
필요하다면 아래 구조로 확장해야 한다:

```
Global Token Bucket (total_rps)
    ├── AUTH bucket (sub-rate-limited)
    ├── ORDER bucket (sub-rate-limited)
    ├── INQUIRY bucket (sub-rate-limited)
    ├── MARKET_DATA bucket (sub-rate-limited)
    └── RECONCILIATION bucket (sub-rate-limited)
```

- **Global bucket**: 전체 REST RPS를 enforce하는 상위 bucket
- **Per-bucket sub-limits**: 각 operation type별 max rate (현재 v1 bucket과 동일)
- 모든 API call은 **global bucket → per-bucket** 순으로 2단 consume
- 장점: aggregate total이 strict하게 보장됨
- 단점: bucket 간 경합 발생 가능 (한 bucket이 global token을 모두 소진하면 다른 bucket도 차단)

이 확장은 현재 v1 범위를 벗어나므로, 필요시 별도 plan으로 추진한다.
