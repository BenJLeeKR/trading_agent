# KIS 최신 공지 기준 Capability 정리 (2026-04-20)

## 목적

KIS 최신 공지(2026-04-20) 기준 REST/WebSocket 운영 한도를 문서, 설정 예시, 테스트 가이드에 반영한다. 기능 구현이 아니라 **capability 수치 정리**에 집중한다.

## 최신 공지 기준 수치

| 항목 | 최신 공지 | 현재 코드 |
|------|-----------|-----------|
| 실전 REST RPS | 18 | 15 (기본값) |
| 모의 REST RPS | 1 | 1 ✅ |
| `/oauth2/tokenP` | 1 rps | 0.1 rps (safety scaling) |
| Approval key 발급 | 1 rps | 미문서 |
| WS 세션 | 앱키당 1세션 | 구현됨 |
| WS 등록 | 합산 41건 | 기본 100 (base.py) |
| 동시호출 텀 | 100~150ms 권장 | smoke: 1.0s (보수적) |

---

## Step 1. `KIS_REAL_REST_RPS` 기본값 `15` → `18` 변경

**검토 결과: 변경한다.**

이유:
- 최신 공지 기준 18 RPS
- 현재 bucket 분배가 보수적이어서(합계 ≈ 13.1 rps @15 baseline → ≈ 15.7 rps @18 baseline) 실제 초과 위험 낮음
- env override 가능하므로 필요시 언제든 보수적 값 조정 가능
- 문서에 "최신 공지 2026-04-20 기준"을 명시

**변경 파일 (4개):**

| # | 파일 | 내용 |
|---|------|------|
| 1 | `src/agent_trading/config/settings.py:133` | 기본값 `"15"` → `"18"`, 주석에 최신 공지 날짜 명시 |
| 2 | `src/agent_trading/brokers/rate_limit.py:353` | 함수 파라미터 기본값 `15` → `18`, docstring 최신화 |
| 3 | `docker-compose.yml:61` | `:-15}` → `:-18}` |
| 4 | `.env.example:24` | 예시값 `15` → `18` |

**변경하지 않는 것:**
- `rate_limit.py:429` — `scale = total / 15.0`의 `15.0`은 **design baseline**으로 변경하지 않음 (weights가 15 RPS 기준으로 설계되었으므로)

---

## Step 2. Capability 항목 문서/설정 정리

### 2a. `plan_docs/detailed_design/10_broker_rate_limit_and_capacity_policy.md`

- 섹션 14.2 Bucket 분배표: Live baseline 15 → 18 업데이트
- 섹션 14.1 개요: "실전투자: 18 RPS (2026-04-20 최신 공지 기준)"로 명시
- 섹션 12 KIS 적용 원칙: auth 1 rps, approval key 1 rps, WS 41 capacity 추가
- 섹션 6 WebSocket Subscription Capacity: KIS WS 41 capacity 언급 추가

### 2b. `plan_docs/detailed_design/05_koreainvestment_adapter_spec.md`

- 섹션 6.8 KIS Rate Limit and Backoff Policy: 최신 수치 요약표 추가
- "현재 enforcement 상태"를 각 항목별로 표시

### 2c. Capability 구분표

아래 표를 **두 문서 모두**에 추가:

| Capability | KIS 공지 값 | 코드 enforcement | 문서 반영 |
|-----------|------------|----------------|----------|
| 실전 REST RPS | 18 | ✅ safety scaling (bucket 분리) | 이번에 반영 |
| 모의 REST RPS | 1 | ✅ safety scaling | ✅ |
| Auth token 1 rps | 1 rps | ❌ dedicated bucket 없음 (0.1 rps safety scaling만) | 이번에 반영 |
| Approval key 1 rps | 1 rps | ❌ dedicated bucket 없음 | 이번에 반영 |
| WS 1 session | 1 session | ✅ (KISWebSocketClient 설계상 1세션) | 이번에 반영 |
| WS 41 registrations | 41 | ❌ 기본값 100 (base.py) | 이번에 반영 |
| 동시호출 100~150ms | 권장 | ✅ smoke test 1.0s spacing (보수적) | 이번에 반영 |

---

## Step 3. 테스트/가이드 정리

### `tests/smoke/test_kis_paper_smoke.py`

- 모듈 docstring: KIS Paper sandbox 제약 요약에 최신 수치 반영
- `_space_api_calls` docstring: "Paper REST 1 rps, 권장 동시호출 간격 100~150ms, smoke는 1.0s로 보수적 운영"
- rate limit skip 메시지: "EGW00133: 1 token/min" 설명에 최신 공지 `/oauth2/tokenP`는 1 rps임을 부기
- KIS Paper sandbox는 1 token/min 제한이 있을 수 있으나, 실제 `/oauth2/tokenP` limit은 1 rps임을 구분

---

## Step 4. WS 41 capacity 문서 반영

### `src/agent_trading/brokers/rate_limit.py` — SubscriptionBudget docstring

- KIS 최신 공지 기준 WS 41 capacity 언급 추가
- 현재 `SubscriptionBudget` 기본값(`max_subscriptions=100`)이 41과 차이가 있음을 주석으로 명시
- 단, 이번 턴에서 기본값 자체는 변경하지 않음 (strict enforcement 영역)

### `src/agent_trading/brokers/base.py` — SubscriptionBudget docstring

- KIS WS 41 capacity 언급 추가
- "현재 기본값 100은 KIS 공지 41보다 여유가 있으나, 향후 strict enforcement 시 41로 조정 필요" 주석 추가

---

## Step 5. 후속 작업 메모

아래 항목은 이번 턴에서 **구현하지 않고 문서로만 남긴다**:

1. **Auth/Approval 1 rps dedicated bucket**
   - 현재 auth bucket은 safety scaling만 (0.1 rps live, 0.017 rps paper)
   - 향후 `/oauth2/tokenP`와 `/oauth2/approval` 전용 1 rps bucket 분리 필요
   - enforcement 시 auth 실패 시 circuit open 연동

2. **WS 41 exact cap enforcement**
   - 현재 `SubscriptionBudget.max_subscriptions=100` (base.py)
   - KIS WS 실제 제한 41에 맞추려면 `max_subscriptions=41`로 조정
   - 단, 변경 시 critical/optional 분배 재검토 필요 (critical=20, optional=21 등)
   - 보유 종목 20개 이하 운영 시 critical 20은 유지 가능

3. **Global REST cap strict enforcement**
   - 현재는 per-bucket safety scaling만 (sum ≈ 13~15.7 rps)
   - 실제 global REST cap enforcement는 TokenBucket 계층 추가 필요 (doc 14.6 구조)
   - 18 RPS 초과 시 throttling이 아니라 circuit breaker 연동 우선 검토

---

## 변경 파일 목록

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `src/agent_trading/config/settings.py` | 코드 | KIS_REAL_REST_RPS 기본값 15→18 |
| `src/agent_trading/brokers/rate_limit.py` | 코드+문서 | 기본값 15→18, docstring 최신화, WS 41 주석 |
| `src/agent_trading/brokers/base.py` | 문서 | SubscriptionBudget docstring에 WS 41 언급 |
| `docker-compose.yml` | 설정 | KIS_REAL_REST_RPS 기본값 15→18 |
| `.env.example` | 설정 | 주석 예시값 15→18 |
| `plan_docs/detailed_design/10_broker_rate_limit_and_capacity_policy.md` | 문서 | 수치 업데이트, capability 구분표 추가 |
| `plan_docs/detailed_design/05_koreainvestment_adapter_spec.md` | 문서 | rate limit 섹션 업데이트 |
| `tests/smoke/test_kis_paper_smoke.py` | 문서 | docstring/주석 최신화 |
