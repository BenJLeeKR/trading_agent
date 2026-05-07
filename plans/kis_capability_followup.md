# KIS Capability 정리 후속 작업 (2026-05-07)

## 배경

KIS 공식 최신 공지 (2026-04-20) 기준으로 실전 REST RPS 기본값을 15→18로 상향하고,
capability 구분표를 문서화하였다. 아래는 이번 작업에서 **코드 변경 없이 문서로만 남긴**
3가지 후속 작업 항목이다.

---

## 후속 #1: Auth/Approval key 1 rps strict cap ✅ 완료 (2026-05-07)

**문제**: KIS 공시상 Auth token (`/oauth2/tokenP`)과 Approval key (`/oauth2/Approval`)는
각각 1 rps로 제한된다. 현재 AUTH bucket (실전 0.12 rps, cap 6)은 간접적으로 보호하지만,
명시적인 1 rps strict cap이 없었다. EGW00133 (접근토큰 발급 잠시 후 다시 시도)이 실제
smoke 테스트에서 관찰되었다.

**구현 (Option A — Inline Lock + Monotonic Cooldown)**:
- `KISRestClient`에 `asyncio.Lock` 2개 (`_auth_lock`, `_approval_lock`) 추가
- monotonic clock 기반 1초 cooldown (`_last_auth_call_time`, `_last_approval_call_time`)
- lock 내부 double-check pattern으로 cache-hit 시 HTTP call 스킵
- 실패 시 timestamp 미갱신 → 즉시 재시도 가능
- Auth/Approval 독립 lock → 상호 간섭 없음

**관련 파일**:
- [`rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py) — authenticate()/get_approval_key() 수정
- [`test_kis_auth_strict_cap.py`](tests/brokers/test_kis_auth_strict_cap.py) — unit test 9개
- [`10_broker_rate_limit_and_capacity_policy.md`](plan_docs/detailed_design/10_broker_rate_limit_and_capacity_policy.md) §12 — enforcement ✅ 갱신
- [`kis_auth_strict_cap.md`](plans/kis_auth_strict_cap.md) — 설계 문서

**Priority**: Medium → 해결 완료

---

## 후속 #2: WebSocket 41 등록 제한 enforcement

**문제**: KIS 공시상 WebSocket 등록은 계좌당 41건으로 제한된다.
현재 [`SubscriptionBudget`](src/agent_trading/brokers/base.py:26)의
`max_subscriptions=100`은 KIS 41을 초과하므로, 실제 KIS WS 연결 시
41 초과 등록은 KIS 서버에서 거절될 수 있다.

**제안**:
- `SubscriptionBudget`에 `max_subscriptions`를 KIS env에 따라 동적 설정
  (paper/live 모두 41)
- 또는 `KISWebSocketClient`에 41-cap wrapper 추가
- subscribe() 실패 시 graceful fallback (eviction or reject)

**관련 파일**:
- [`base.py`](src/agent_trading/brokers/base.py) — `SubscriptionBudget` 기본값
- [`websocket_client.py`](src/agent_trading/brokers/koreainvestment/websocket_client.py) — subscribe() 로직
- [`rate_limit.py`](src/agent_trading/brokers/rate_limit.py) — `SubscriptionBudget` 복제본
- [`10_broker_rate_limit_and_capacity_policy.md`](plan_docs/detailed_design/10_broker_rate_limit_and_capacity_policy.md) §12

**Priority**: Medium (현재 테스트는 paper 1개 채널만 구독하므로 당장 문제되지 않으나,
실전 운용 시 multi-symbol 구독에서 41 초과 가능)

---

## 후속 #3: Strict Global REST Cap enforcement ✅ 완료 (2026-05-07)

**구현 내역**:
- `BucketType.REST_GLOBAL = "global"` 추가
- `RateLimitBudgetManager`에 `global_rest: OperationBucket | None` 필드 추가
- `consume_or_raise()` 2-tier enforcement: **Global REST → Per-operation** 순서로 consume
- `build_kis_budget_manager()`: global bucket capacity = total RPS, refill_rate = 1.0 × total RPS
  - Paper: capacity=1, refill_rate=1.0
  - Live: capacity=18, refill_rate=18.0 (env override 시 비례 확장)
- `snapshot()`에 global bucket state 자동 포함 → `/broker-capacity` inspection에서 확인 가능
- `RateLimitBudgetManager()` 직접 생성 시 (global_rest_capacity=0) global bucket 비활성화 (backward compatible)

**관련 파일**:
- [`rate_limit.py`](src/agent_trading/brokers/rate_limit.py) — `BucketType`, `RateLimitBudgetManager`, `build_kis_budget_manager()`
- [`plans/kis_rest_strict_global_cap.md`](plans/kis_rest_strict_global_cap.md) — 설계 문서
- 변경 불필요: `rest_client.py`, `bootstrap.py`, `broker_capacity.py`, `schemas.py`

**Priority**: ✅ 완료 — per-bucket scaling 위에 strict global gate 동작

---

## 변경 불가 확인

- ❌ Broker submit semantics 변경 금지
- ❌ Hard guardrail/reconciliation boundary 변경 금지
- ❌ Admin UI 변경 금지
- ❌ Rate limit engine 재설계 금지 (위 3건은 후속 작업으로 문서만 남김)
