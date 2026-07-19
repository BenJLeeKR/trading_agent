# KIS VTTC8908R Timeout 완화 계획

## 발견 요약 (코드 대조 검증 완료)

### 1. httpx Timeout 설정 — 확인됨
- **파일**: [`rest_client.py:431`](../src/agent_trading/brokers/koreainvestment/rest_client.py#L431)
- **현재값**: `httpx.Timeout(8.0, connect=5.0, read=5.0)`
- **검증 결과**: 정확함. `read=5.0`은 KIS API 응답 시간에 비해 짧은 편.

### 2. `_request()` Retry 부재 — 확인됨
- **파일**: [`rest_client.py:828-863`](../src/agent_trading/brokers/koreainvestment/rest_client.py#L828)
- **현재 동작**:
  - `httpx.TimeoutException` → `BrokerError(retryable=True)` raise + `circuit_breaker.record_failure()`
  - `httpx.RequestError` → `BrokerError(retryable=True)` raise + `circuit_breaker.record_failure()`
  - **retry 로직 없음** — `retryable=True` flag만 있고 실제 재시도는 caller에게 위임
- **검증 결과**: 정확함. `_request()` 내에 retry 없음.

### 3. Circuit Breaker 설정 — 확인됨
- **파일**: [`rest_client.py:385-388`](../src/agent_trading/brokers/koreainvestment/rest_client.py#L385)
- **설정값**: `failure_threshold=5, recovery_timeout=30.0`
- **상태 전이**: `CLOSED → OPEN (5 failures) → after 30s → HALF_OPEN → 1 probe success → CLOSED`
- **검증 결과**: 정확함. 5회 연속 실패 시 30초간 모든 INQUIRY 차단.

### 4. `get_orderable_cash()` 메서드 — 확인됨
- **파일**: [`rest_client.py:1427-1531`](../src/agent_trading/brokers/koreainvestment/rest_client.py#L1427)
- **동작**:
  - Budget pre-check: budget 부족 시 `fallback_cash` 반환 (API 호출 생략)
  - `_request()` 호출 후 `output.ord_psbl_cash` 추출
  - `Exception` catch → `None` 반환 (상세 로그만 출력)
- **검증 결과**: 정확함. `_request()` 예외를 caller에게 전파하지 않고 `None`으로 변환.

### 5. `kis_snapshot_sync.py` 저장 로직 — 확인됨
- **파일**: [`kis_snapshot_sync.py:441-530`](../src/agent_trading/services/kis_snapshot_sync.py#L441)
- **Fallback 체인 (검증 완료)**:
  ```
  VTTC8908R 성공 → orderable_amount = ord_psbl_cash (line 478-483)
  VTTC8908R 실패(Exception) → available_cash로 fallback (line 466-476)
  VTTC8908R 실패(BudgetExhaustedError) → available_cash로 fallback (line 456-465)
  VTTC8908R 성공 but ord_psbl_cash=None → VTTC8434R output2.ord_psbl_amt (line 485-493)
  VTTC8434R ord_psbl_amt도 없음 → available_cash (line 497-503)
  raw_cash 없음 → orderable_amount = None (line 512-515)
  after-hours → skip (line 504-511)
  ```
- **검증 결과**: 정확함. 3중 fallback 정상 동작 중.

### 6. `sizing_engine.py` Cash Fallback — 확인됨
- **파일**: [`sizing_engine.py:210-380`](../src/agent_trading/services/sizing_engine.py#L210)
- **두 가지 fallback 경로**:
  1. `_resolve_buy_target_quantity()` (line 218-219): `effective_cash = inputs.orderable_amount or inputs.available_cash` — Python `or`로 0/None fallback
  2. `_apply_cash_constraint()` (line 348-366): `orderable_amount > available_cash` 명시적 우선순위
- **검증 결과**: 정확함. `orderable_amount` 우선, 없으면 `available_cash` fallback.

### 7. `execution_service.py` Cash Source 로깅 — 확인됨
- **파일**: [`execution_service.py:466-477`](../src/agent_trading/services/execution_service.py#L466)
- **현재**: `orderable_amount` 존재 여부에 따라 로그 출력하지만 **source 태깅 없음** (어떤 API에서 왔는지 추적 불가)

---

## Root Cause 분석

### 직접 원인: VTTC8908R Timeout
- `read=5.0` timeout은 KIS 현물/모의 환경 API 응답 시간을 고려할 때 지나치게 보수적
- KIS API는 특히 장중 트래픽이 몰릴 때 5초 이상 응답 지연 발생 가능
- Timeout 발생 시 `_request()`가 즉시 `BrokerError(retryable=True)`를 raise하지만:
  - `get_orderable_cash()`에서 `except Exception` catch → `None` 반환
  - `None`은 바로 fallback 체인으로 빠짐
  - circuit breaker가 OPEN되어 이후 모든 INQUIRY 차단 가능

### 간접 원인: Retry 부재
- 일시적인 timeout에도 재시도 없이 즉시 fallback
- 1~2회의 빠른 재시도로 해결될 수 있는 일시적 장애를 영구적 실패로 처리
- circuit breaker 불필요한 OPEN 유발

### 근본 원인: OAuth2 Token 403 (EGW00133)
- 별도 문제로, snapshot-sync 로그에서 38회 발견
- `raw_cash` 자체를 못 가져와서 `orderable_amount`가 NULL이 되는 간접적 원인
- **본 수정안의 범위 외** (token 갱신 문제는 별도 분석 필요)

---

## 제안된 수정 (Proposal A/B/C/D)

### Proposal A: httpx read timeout 증가
| 항목 | 내용 |
|------|------|
| **변경 파일** | [`rest_client.py:431`](../src/agent_trading/brokers/koreainvestment/rest_client.py#L431) |
| **변경 내용** | `read=5.0` → `read=15.0` (3배 증가) |
| **변경 전** | `httpx.Timeout(8.0, connect=5.0, read=5.0)` |
| **변경 후** | `httpx.Timeout(18.0, connect=5.0, read=15.0)` (total도 8→18로 조정) |
| **근거** | KIS API 응답 시간이 5초를 초과하는 경우 발생. 15초는 enterprise API에서 합리적인 timeout. |
| **영향 범위** | 모든 KIS API 호출 (inquire_price, inquire_balance, inquire_psbl_order, order 등) |
| **리스크** | timeout이 길어져도 circuit breaker가 연쇄 실패 차단. 15초는 과도하지 않음. |
| **난이도** | ⭐ — 1줄 변경 |

#### 상세 변경 코드 (`rest_client.py:431`)
```python
# 변경 전
timeout=httpx.Timeout(8.0, connect=5.0, read=5.0),

# 변경 후
timeout=httpx.Timeout(18.0, connect=5.0, read=15.0),
```

#### 상세 근거
- KIS API 공식 문서상 응답 시간 SLA는 3초 이내지만, 장중 피크 시간대에는 5~10초까지 지연 관찰됨
- `total=18.0`은 read timeout 15초 + connect 3초 버퍼로, read timeout 15초의 20% 여유
- `inquire_price` read timeout은 별도 문제 (13개 symbol에서 발생) — 별도 분석 필요할 수 있음

---

### Proposal B: `_request()`에 지수 백오프 retry 추가
| 항목 | 내용 |
|------|------|
| **변경 파일** | [`rest_client.py:828-863`](../src/agent_trading/brokers/koreainvestment/rest_client.py#L828) |
| **변경 내용** | `httpx.TimeoutException` 및 `httpx.RequestError` 발생 시 최대 2회 retry 추가 |
| **재시도 정책** | 지수 백오프: 1.0s (1회), 2.0s (2회) — jitter 0.1s |
| **조건** | `retryable=True`인 경우에만 retry (timeout, network error) |
| **영향 범위** | 모든 KIS API 호출, `_request()` 공통 |
| **리스크** | retry로 인한 wall clock 증가 (최대 3.3초). circuit breaker와 rate limit 상호작용. |
| **난이도** | ⭐⭐ — 기존 예외 처리 로직 수정 |

#### 상세 변경 코드 (`rest_client.py:828-863`)

```python
# 변경 전 (현재: retry 없음)
try:
    if method.upper() == "GET":
        resp = await client.get(url, headers=headers, params=params)
    else:
        resp = await client.post(url, headers=headers, json=body, params=params)
except httpx.TimeoutException:
    self._circuit_breaker.record_failure()
    raise BrokerError(
        broker_name=BrokerName.KOREA_INVESTMENT,
        error_type=BrokerErrorType.TIMEOUT,
        retryable=True,
        raw_message=f"KIS {endpoint_key}: timeout",
    )
except httpx.RequestError as e:
    self._circuit_breaker.record_failure()
    raise BrokerError(
        broker_name=BrokerName.KOREA_INVESTMENT,
        error_type=BrokerErrorType.NETWORK_ERROR,
        retryable=True,
        raw_message=f"KIS {endpoint_key}: network error: {e}",
    )
```

```python
# 변경 후: 지수 백오프 retry 추가
MAX_RETRIES = 2
RETRY_DELAYS = [1.0, 2.0]  # seconds

for attempt in range(MAX_RETRIES + 1):
    try:
        if method.upper() == "GET":
            resp = await client.get(url, headers=headers, params=params)
        else:
            resp = await client.post(url, headers=headers, json=body, params=params)
        break  # 성공 시 루프 탈출
    except httpx.TimeoutException:
        if attempt < MAX_RETRIES:
            delay = RETRY_DELAYS[attempt]
            jitter = random.uniform(0, 0.1)
            logger.warning(
                "[KIS] %s timeout on attempt %d/%d, retrying in %.1fs",
                endpoint_key, attempt + 1, MAX_RETRIES + 1, delay + jitter,
            )
            await asyncio.sleep(delay + jitter)
            continue
        self._circuit_breaker.record_failure()
        raise BrokerError(
            broker_name=BrokerName.KOREA_INVESTMENT,
            error_type=BrokerErrorType.TIMEOUT,
            retryable=True,
            raw_message=f"KIS {endpoint_key}: timeout after {MAX_RETRIES + 1} attempts",
        )
    except httpx.RequestError as e:
        if attempt < MAX_RETRIES:
            delay = RETRY_DELAYS[attempt]
            jitter = random.uniform(0, 0.1)
            logger.warning(
                "[KIS] %s network error on attempt %d/%d, retrying in %.1fs: %s",
                endpoint_key, attempt + 1, MAX_RETRIES + 1, delay + jitter, e,
            )
            await asyncio.sleep(delay + jitter)
            continue
        self._circuit_breaker.record_failure()
        raise BrokerError(
            broker_name=BrokerName.KOREA_INVESTMENT,
            error_type=BrokerErrorType.NETWORK_ERROR,
            retryable=True,
            raw_message=f"KIS {endpoint_key}: network error after {MAX_RETRIES + 1} attempts: {e}",
        )
```

#### Retry가 circuit breaker와 상호작용하는 방식
```
정상 → 성공 → circuit_breaker.record_success() (failure_count = 0 리셋)
timeout 1회차 → retry (delay 1s)
timeout 2회차 → retry (delay 2s)
timeout 3회차 (max) → circuit_breaker.record_failure() → BrokerError raise
```
- retry는 circuit breaker 실패 카운트 전에 일어나므로, 일시적 timeout 1~2회는 CB에 영향 없음
- 3회 연속 timeout에서만 CB 실패 카운트 증가 → 불필요한 CB OPEN 방지

---

### Proposal C: `snapshot_sync.py`에 `orderable_amount` 캐싱
| 항목 | 내용 |
|------|------|
| **변경 파일** | [`kis_snapshot_sync.py:441-530`](../src/agent_trading/services/kis_snapshot_sync.py#L441) |
| **변경 내용** | 성공한 `orderable_amount`를 인메모리 캐싱하여 다음 cycle에서 재사용 |
| **TTL** | 180초 (3분) — KIS 잔고 조회 주기(약 60초)의 3배 |
| **조건** | VTTC8908R 성공 시 캐시 갱신. VTTC8908R 실패 시 캐시 사용 (stale 허용). |
| **영향 범위** | `kis_snapshot_sync.py`의 `sync_single_account()` 함수 내 |
| **리스크** | stale value 사용 가능성. 캐시 무효화 시점이 중요. |
| **난이도** | ⭐⭐ — 함수형 코드에 캐시 추가 |

#### 상세 변경 설계

```python
# 새 파일 또는 kis_snapshot_sync.py 상단에 추가
from time import monotonic

# 모듈 레벨 캐시 (인스턴스가 아닌 모듈 단위 공유)
_orderable_amount_cache: dict[str, tuple[Decimal | None, float]] = {}
"""account_id → (orderable_amount, timestamp)"""

_CACHE_TTL = 180.0  # 3분


def _get_cached_orderable_amount(account_id: str) -> Decimal | None:
    """Return cached orderable_amount if within TTL, else None."""
    entry = _orderable_amount_cache.get(account_id)
    if entry is not None:
        value, timestamp = entry
        if monotonic() - timestamp < _CACHE_TTL:
            return value
    return None


def _set_cached_orderable_amount(account_id: str, value: Decimal | None) -> None:
    _orderable_amount_cache[account_id] = (value, monotonic())
```

**적용 위치** (`sync_single_account()` 내, line 446 전후):
```python
# 캐시 조회 (VTTC8908R 호출 전)
if raw_cash and not after_hours:
    cached_amt = _get_cached_orderable_amount(account_id)
    if cached_amt is not None:
        logger.info(
            "orderable_amount=%s (source: cache, TTL=%ss, account=%s)",
            cached_amt, _CACHE_TTL, account_id,
        )
        orderable_amount = cached_amt
    else:
        # 기존 VTTC8908R 호출 로직...
        # 성공 시: _set_cached_orderable_amount(account_id, orderable_cash)
```

---

### Proposal D: `sizing_engine.py`/`execution_service.py`에 `orderable_amount` Source Tagging 강화
| 항목 | 내용 |
|------|------|
| **변경 파일** | [`execution_service.py:466-477`](../src/agent_trading/services/execution_service.py#L466), [`sizing_engine.py:348-366`](../src/agent_trading/services/sizing_engine.py#L348) |
| **변경 내용** | `orderable_amount`의 출처(API source)를 로그 및 constraints에 태깅 |
| **영향 범위** | 운영 모니터링 및 디버깅 용이성 |
| **난이도** | ⭐ — 로깅 메시지 개선 |

#### 상세 변경

**`execution_service.py:466-477`** — cash source 로깅 강화:
```python
# 변경 전
if orderable_amount is not None:
    logger.info(
        "Cash source: orderable_amount=%s (preferred) | "
        "available_cash=%s (fallback)",
        orderable_amount, available_cash,
    )
else:
    logger.info(
        "Cash source: available_cash=%s (fallback, orderable_amount not available)",
        available_cash,
    )

# 변경 후 — source 정보 추가
if orderable_amount is not None:
    logger.info(
        "Cash source: orderable_amount=%s (from snapshot DB) | "
        "available_cash=%s | orderable_amount 질의 출처: VTTC8908R > "
        "VTTC8434R.ord_psbl_amt > available_cash fallback",
        orderable_amount, available_cash,
    )
else:
    logger.info(
        "Cash source: available_cash=%s (fallback, orderable_amount=null in snapshot DB) | "
        "원인 가능성: VTTC8908R timeout / VTTC8434R raw_cash 부재 / after-hours skip",
        available_cash,
    )
```

**`sizing_engine.py:348-366`** — constraint source tagging:
```python
# 변경 전
if orderable_amount is not None:
    if orderable_amount <= 0:
        constraints.append("orderable_amount_zero")
        ...
    effective_cash = orderable_amount
elif available_cash is not None:
    ...
    effective_cash = available_cash

# 변경 후 — constraint source tagging
if orderable_amount is not None:
    if orderable_amount <= 0:
        constraints.append("orderable_amount_zero")
        ...
    constraints.append("cash_source=orderable_amount")
    effective_cash = orderable_amount
elif available_cash is not None:
    constraints.append("cash_source=available_cash_fallback")
    ...
    effective_cash = available_cash
else:
    constraints.append("cash_source=none")
```

---

## 구현 우선순위

| 우선순위 | Proposal | 리스크 | 영향 | 난이도 | 근거 |
|---------|----------|--------|------|--------|------|
| **P0** | **A: timeout 증가** | 낮음 | 높음 | ⭐ | 단 1줄 변경으로 모든 KIS API에 영향. KIS 응답 지연에 즉시 대응. |
| **P1** | **B: retry 추가** | 중간 | 중간 | ⭐⭐ | 일시적 timeout 자동 복구. CB 불필요 OPEN 방지. 단 wall clock 증가. |
| **P2** | **C: 캐싱** | 중간 | 중간 | ⭐⭐ | API 호출 수 감소. stale value 리스크 존재. |
| **P3** | **D: 로깅 강화** | 낮음 | 낮음 | ⭐ | 운영 모니터링 개선. 코드 영향 없음. |

### 권장 조합: A + B + D (C는 선택)
- **A (timeout 증가)**: 반드시 먼저 적용. 가장 단순하고 효과적.
- **B (retry 추가)**: A 이후 적용. 일시적 장애에 대한 복원력 향상.
- **D (로깅 강화)**: A+B 적용 후 source 추적 용이성 확보.
- **C (캐싱)**: A+B로도 문제가 지속될 경우 고려. stale value 리스크가 있어 신중히 결정.

---

## 테스트 계획

### 단위 테스트

#### Proposal A (timeout 증가)
| 테스트 | 내용 |
|--------|------|
| `test_timeout_values` | httpx.Timeout 객체가 올바른 read/connect/total 값을 가지는지 확인 |
| `test_existing_timeout_unchanged` | 다른 timeout 설정값(connect=5.0)이 영향을 받지 않는지 확인 |

#### Proposal B (retry 추가)
| 테스트 | 내용 |
|--------|------|
| `test_retry_on_timeout_success_after_retry` | 1회차 timeout → retry → 성공 케이스 |
| `test_retry_on_timeout_all_fail` | 3회 모두 timeout → 최종 BrokerError raise |
| `test_retry_on_network_error` | NetworkError → retry → 성공/실패 |
| `test_retry_not_on_other_errors` | 4xx/5xx 응답은 retry하지 않음 |
| `test_retry_max_attempts` | 최대 retry 횟수(2회) 초과 시도하지 않음 |
| `test_circuit_breaker_not_incremented_on_retry_success` | retry 성공 시 CB failure_count 증가하지 않음 |
| `test_circuit_breaker_incremented_after_max_retries` | 최종 실패 시 CB failure_count 증가 |
| `test_retry_delays` | 지수 백오프 1.0s, 2.0s 적용 확인 |

#### Proposal C (캐싱)
| 테스트 | 내용 |
|--------|------|
| `test_cache_hit_within_ttl` | TTL 내 캐시 히트 시 API 호출 없이 캐시 값 사용 |
| `test_cache_miss_expired_ttl` | TTL 만료 시 API 호출 |
| `test_cache_miss_no_entry` | 캐시 미존재 시 API 호출 |
| `test_cache_update_on_success` | API 성공 시 캐시 갱신 |

#### Proposal D (로깅)
| 테스트 | 내용 |
|--------|------|
| `test_constraints_include_cash_source` | constraints 리스트에 `cash_source=*` 포함 확인 |

### 통합 테스트
| 테스트 | 내용 |
|--------|------|
| `test_snapshot_sync_vttc8908r_timeout_retry` | 모의 timeout 환경에서 retry → fallback → 저장 검증 |
| `test_sizing_cash_source_tagging` | `CashBalanceSnapshotEntity`의 `orderable_amount`가 sizing engine에 올바르게 전달되는지 확인 |

### 운영 검증 (모니터링)
| 항목 | 방법 |
|------|------|
| VTTC8908R timeout 건수 감소 | `logs/near_real_scheduler_*` 로그 `[VTTC8908R]` 검색 |
| circuit breaker OPEN 빈도 감소 | `circuit breaker open` 로그 검색 |
| `orderable_amount` 정상화율 | DB 쿼리: `SELECT COUNT(*) FROM cash_balance_snapshots WHERE orderable_amount IS NULL AND created_at > NOW() - interval '24h'` |
| retry 성공률 | `retrying in` 로그 검색 → 성공/실패 비율 확인 |

---

## Mermaid: VTTC8908R 요청 흐름 (수정 후)

```mermaid
flowchart TD
    A[snapshot_sync: sync_single_account] --> B{raw_cash && !after_hours?}
    B -->|No| C[orderable_amount = None / skip]
    B -->|Yes| D{Proposal C: cache hit?}
    D -->|Yes| E[Use cached orderable_amount]
    D -->|No| F[_request: VTTC8908R 호출<br/>read=15s timeout]
    F --> G{Proposal B: timeout?}
    G -->|No (성공)| H[ord_psbl_cash 추출]
    G -->|Yes| I[retry 1: delay 1s]
    I --> J{성공?}
    J -->|Yes| H
    J -->|No| K[retry 2: delay 2s]
    K --> L{성공?}
    L -->|Yes| H
    L -->|No| M[BrokerError retryable=True<br/>circuit_breaker.record_failure]
    H --> N{ord_psbl_cash<br/>존재?}
    N -->|Yes| O[orderable_amount = ord_psbl_cash<br/>Proposal C: update cache]
    N -->|No| P[Fallback: VTTC8434R.ord_psbl_amt]
    P --> Q{존재?}
    Q -->|Yes| R[orderable_amount = ord_psbl_amt]
    Q -->|No| S[Final fallback: available_cash]
    M --> P
    O --> T[CashBalanceSnapshotEntity 저장]
    R --> T
    S --> T
    T --> U[sizing_engine 사용 시<br/>Proposal D: source tagging]
```

---

## 의사결정 매트릭스

| 기준 | A (timeout↑) | B (retry) | C (캐싱) | D (로깅) |
|------|:------------:|:---------:|:---------:|:--------:|
| 코드 변경량 | 1 line | ~40 lines | ~30 lines | ~15 lines |
| 회귀 리스크 | 극히 낮음 | 중간 (retry 타이밍) | 중간 (stale data) | 없음 |
| timeout 직접 대응 | ✅ | ✅ (retry 성공 시) | ❌ | ❌ |
| CB 불필요 OPEN 방지 | 부분적 | ✅ | ❌ | ❌ |
| API 호출 수 감소 | ❌ | ❌ (증가) | ✅ | ❌ |
| 모니터링 개선 | ❌ | ❌ | ❌ | ✅ |
| 적용 즉시 효과 | ✅ | ✅ | ❌ | ❌ |

---

## 결론

**권장 구현 순서**: Proposal A → Proposal B → Proposal D (선택사항: Proposal C)

1. **Proposal A**는 가장 낮은 리스크로 즉각적인 timeout 완화 효과를 제공합니다.
2. **Proposal B**는 일시적 장애에 대한 시스템 복원력을 크게 향상시킵니다.
3. **Proposal D**는 운영 가시성을 확보하여 문제 발생 시 원인 파악을 용이하게 합니다.
4. **Proposal C**는 A+B 적용 후에도 VTTC8908R 호출이 여전히 문제가 될 경우에만 고려합니다.
