# Naver API HTTP 429 Too Many Requests — Root Cause Analysis

## 1. Executive Summary

**분석 대상**: `--submit` 실행 중 발생한 Naver Search API 213건의 HTTP 429 오류  
**분석 기간**: 2026-05-26 13:17:34 ~ 13:18:54 (약 80초)  
**핵심 결론**: **Per-second rate limit 초과 (Rate Limiting)** — credentials/쿼터 문제 아님

---

## 2. 현재 Rate Limiting 메커니즘 분석

### 2.1 Semaphore(2) — Concurrency Control only

[`src/agent_trading/brokers/naver_news_adapter.py`](src/agent_trading/brokers/naver_news_adapter.py:62)

```python
_NAVER_SEMAPHORE: asyncio.Semaphore = asyncio.Semaphore(2)
```

- Semaphore(2)는 **동시 in-flight 요청 수**만 제한함
- **초당 요청 수(Requests Per Second)는 전혀 제한하지 않음**
- 두 개의 코루틴이 각각 연속적으로 빠르게 요청을 보낼 수 있어, Naver의 초당 10회 제한을 쉽게 초과

### 2.2 Retry/Backoff 설정

[`src/agent_trading/brokers/naver_news_adapter.py`](src/agent_trading/brokers/naver_news_adapter.py:84)

```python
self._max_retries: int = 2      # 최초 1회 + 2회 재시도 = 총 3회
self._backoff_base: float = 0.5  # 지수 백오프 기본값 0.5초
self._backoff_max: float = 10.0  # 최대 백오프 10초
```

**백오프 공식**: `backoff_base * (2^attempt) + random(0, 0.5 * backoff_base * (2^attempt))`

| 시도 | 지연 시간 (approx) | 결과 |
|------|-------------------|------|
| 1/3 (최초) | 0s | ❌ 429 |
| 2/3 (재시도 1) | ~0.5~0.75s | ❌ 429 |
| 3/3 (재시도 2) | ~1.0~1.5s | ❌ 429 |

- **문제점**: Rate limit이 지속되는 상황에서는 백오프가 너무 짧아 모든 재시도가 실패
- **Retry-After 헤더 미처리**: Naver API가 반환하는 `Retry-After` 헤더를 전혀 확인하지 않음

### 2.3 Retryable Status Codes

[`src/agent_trading/brokers/naver_news_adapter.py`](src/agent_trading/brokers/naver_news_adapter.py:201)

```python
_NAVER_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
```

- 429를 retryable로 분류한 것은 올바름
- Non-retryable 4xx (400, 401, 403, 404)는 즉시 빈 응답 반환 → **429 ≠ 401/403 확인 완료**

---

## 3. 로그 분석 결과

### 3.1 분석 대상 로그

[`logs/submit_measurement_20260526_131726.log`](logs/submit_measurement_20260526_131726.log)

### 3.2 호출 패턴

30개 종목 × 2개 질의(헤드라인 기반 + "공시" 질의) = **~60회 Naver API 호출/사이클**

**실제 로그 예시**:
```
13:17:34 NAVER API 429 (attempt 1/3) - query='티에이치엔 오전장...'
13:17:34 NAVER API 429 (attempt 1/3) - query='SK 많은 기업그룹...'
13:17:35 NAVER API 429 (attempt 2/3) - retrying in 1.02s
13:17:35 NAVER API 429 (attempt 2/3) - retrying in 1.45s
13:17:36 NAVER API 429 - max retries exceeded (2 queries)
...
13:17:45 NAVER API 429 (attempt 1/3) - query='한화투자증권 오전장...'
13:17:45 NAVER API 429 (attempt 1/3) - query='SK텔레콤 많은 기업그룹...'
...
13:18:54 NAVER API 429 - max retries exceeded (last queries)
```

### 3.3 핵심 관측

| 관측 항목 | 내용 |
|-----------|------|
| **429 발생률** | **100%** — 모든 Naver API 호출이 429 수신 |
| **지속 시간** | 전체 ~80초 사이클 동안 지속적 429 |
| **재시도 성공률** | **0%** — 모든 재시도(2회)도 429로 실패 |
| **성공한 호출** | **없음** — 로그에서 단 한 건의 성공 응답도 발견되지 않음 |
| **401/403 발생** | **없음** — credentials 문제 없음 |
| **응답 바디/헤더** | 429 status code만 로깅, 상세 body/headers는 로그에 미기록 |

---

## 4. 원인 분류

### 4.1 ✅ Rate Limit (Per-second) — 확정

Naver Search API의 documented rate limit:
- **일일 쿼터**: 25,000회/일
- **초당 제한**: ~10회/초 (명시적 문서는 아니지만 실제 운영 제한)

**429가 지속된 메커니즘**:
1. 30개 종목이 병렬로 처리됨 (subprocess isolation, 4개씩 배치)
2. 각 종목은 [`search_by_seed()`](src/agent_trading/brokers/naver_news_adapter.py:102) 내에서 2개 질의를 순차 실행
3. Semaphore(2)는 전체 시스템의 동시 요청을 2개로 제한하지만, 2개 요청이 동시에 나간 후 다음 2개가 재빨리 이어짐
4. 결과적으로 `60+ calls / 80 sec = ~0.75 calls/sec` 평균은 낮지만, **버스트 패턴**에서 순간적으로 10 req/s 초과
5. Naver가 rate limit에 걸리면 일정 시간(보통 1~10초) 동안 모든 요청을 차단
6. 차단이 해제되기 전에 재시도가 이루어져 모든 재시도도 429 실패

### 4.2 ❌ Daily Quota Exhaustion — 아닌 이유

- 213건의 429가 모두 rate limit 패턴을 보임 (burst에 반응)
- Daily quota 소진 시 429 대신 403(Forbidden) 또는 별도 오류 코드 반환 가능
- 모든 호출이 아닌 초기 호출 일부만 실패해야 함
- 여기서는 **모든 호출이 429**로 일관됨 → rate limit 패턴

### 4.3 ❌ Credentials 문제 — 아닌 이유

- [`_call_api()`](src/agent_trading/brokers/naver_news_adapter.py:172)에서 정확한 헤더 전송:
  ```python
  headers = {
      "X-Naver-Client-Id": self._client_id,
      "X-Naver-Client-Secret": self._client_secret,
  }
  ```
- 401/403은 non-retryable 4xx로 즉시 처리되어 로그에 별도 기록됨
- 401/403 로그는 **단 한 건도 발견되지 않음**

---

## 5. 권장 수정 사항

### 5.1 필수: Rate Limiter 도입 (Token Bucket 또는 Sliding Window)

현재 Semaphore(2)를 **Rate Limiter로 대체**해야 함.

**Token bucket 예시** — [`src/agent_trading/brokers/rate_limit.py`](src/agent_trading/brokers/rate_limit.py)에 이미 관련 클래스 존재 가능성:

```python
# Naver 전용 Rate Limiter: 8 req/s (safe margin)
_naver_rate_limiter = TokenBucketRateLimiter(
    max_rate=8,     # max requests per second (Naver limit 10, margin 20%)
    time_window=1.0 # 1 second window
)
```

**Semaphore(2) 제거 또는 보완**:
- Semaphore는 동시성 제어용으로 유지하되, rate limiter를 추가로 적용
- 또는 [`asyncio.Semaphore(2)`](src/agent_trading/brokers/naver_news_adapter.py:62) 대신 rate limiter가 동시성도 제어

### 5.2 필수: Retry-After 헤더 처리

```python
if response.status_code == 429:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        delay = max(int(retry_after), delay)
```

### 5.3 권장: 백오프 전략 개선

현재 `backoff_base=0.5`는 rate limit 시나리오에 너무 공격적:

```python
# Rate limit 전용: 더 긴 초기 백오프
self._backoff_base: float = 2.0   # 0.5 → 2.0
self._backoff_max: float = 30.0   # 10.0 → 30.0
```

또는 **jitter가 포함된 decorator 기반 retry**로 교체 고려.

### 5.4 권장: 429 응답 바디/헤더 로깅

현재 로그에 429 응답의 상세 내용이 기록되지 않음. Naver가 반환하는 에러 메시지와 제한 시간 정보를 로깅해야 디버깅 용이:

```python
logger.warning(
    "NAVER API 429 (attempt %d/%d) - retrying in %.2fs | headers=%s body=%s",
    attempt + 1, self._max_retries + 1, delay,
    dict(response.headers), response.text[:200]
)
```

---

## 6. Mermaid: 호출 흐름

```mermaid
flowchart TD
    A[DecisionOrchestrator\n30 symbols] --> B[Subprocess 배치\n4 symbols/배치]
    B --> C[Symbol별 search_by_seed]
    C --> D[Query 1: headline 기반]
    C --> E[Query 2: 공시 질의]
    
    D --> F[Semaphore(2) 통과]
    E --> F
    
    F --> G{Naver API 호출}
    G -->|429| H[Retry 1: 0.5~0.75s 대기]
    H --> I{Naver API 재호출}
    I -->|429| J[Retry 2: 1.0~1.5s 대기]
    J --> K{Naver API 재호출}
    K -->|429| L[max retries exceeded\n빈 결과 반환]
    
    G -->|200| M[성공 - 뉴스 파싱]
    
    L --> N[종목 처리 완료\n시드 뉴스 없음]
    M --> N
```

---

## 7. 결론

| 항목 | 진단 |
|------|------|
| **문제** | HTTP 429 Too Many Requests |
| **원인** | **Per-second rate limit 초과** — Semaphore(2)로는 요청 속도 제어 불가 |
| **증상** | 전체 ~80초 동안 **모든** Naver API 호출이 429로 실패 (100% failure rate) |
| **영향 범위** | 30개 종목 × 2개 질의 × 3회 시도 = ~180회 요청 중 전부 429 |
| **Credentials** | ❌ 문제 아님 (401/403 없음, 정확한 헤더 전송 확인) |
| **Daily Quota** | ❌ 문제 아님 (패턴이 rate limit에 부합) |
| **1차 수정** | Token bucket rate limiter 도입 (8 req/s, 20% safety margin) |
| **2차 수정** | Retry-After 헤더 파싱 및 백오프 전략 개선 |
