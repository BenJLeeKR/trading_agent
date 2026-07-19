# KIS Quote Fetch Rate Limit (`EGW00201`) 병목 분석

> 분석일: 2026-05-26  
> 분석 범위: `--submit` 모드 full pipeline  
> 대상 symbol: 최대 30개 (Semaphore 5 동시 실행)

---

## 1. 현재 Quote Fetch 호출 경로

### 1.1 호출 흐름 다이어그램

```mermaid
sequenceDiagram
    participant Loop as run_decision_loop.py
    participant Orchestrator as DecisionOrchestratorService
    participant Exec as ExecutionService
    participant Adapter as KISAdapter
    participant REST as KISRestClient
    participant KIS as KIS API

    Note over Loop,KIS: === Cycle Start (symbol 1..N, Semaphore=5) ===

    Loop->>Adapter: _resolve_symbol_price()<br/>broker.get_quote(symbol, market)
    Note over Loop: price=None 고정<br/>(_resolve_order_type_and_price)<br/>→ quote result 미사용
    Adapter->>REST: get_quote(symbol)
    REST->>KIS: GET /inquire-price<br/>bucket=MARKET_DATA
    KIS-->>REST: quote response
    REST-->>Adapter: raw output
    Adapter-->>Loop: Quote(last=xxx)

    Loop->>Orchestrator: assemble_and_submit(request, broker)
    Orchestrator->>Exec: run_execution_pipeline()

    Note over Exec: request.price is None (MARKET)<br/>→ _resolve_quote() 호출

    Exec->>Adapter: _resolve_quote()<br/>broker.get_quote(symbol, market)
    Note over Exec: _quote_cache TTL=5s<br/>BUT 첫 번째 호출과<br/>시간차 > 5s → cache miss
    Adapter->>REST: get_quote(symbol)
    REST->>KIS: GET /inquire-price<br/>bucket=MARKET_DATA
    KIS-->>REST: quote response
    REST-->>Adapter: raw output
    Adapter-->>Exec: Quote, reference_price

    Note over Loop,Exec: ★ 동일 symbol에 대해<br/>2회 중복 호출 발생
```

### 1.2 상세 호출 지점

| 경로 | 위치 | 호출 함수 | 호출 조건 |
|------|------|-----------|----------|
| **Path A** | [`run_decision_loop.py:738`](../scripts/run_decision_loop.py:738) | `_resolve_symbol_price()` → `broker.get_quote()` | 항상 (dry-run/submit 공통) |
| **Path B** | [`execution_service.py:566`](../src/agent_trading/services/execution_service.py:566) | `_resolve_quote()` → `broker.get_quote()` | `request.price is None` (MARKET 주문) |

### 1.3 quote cache 상태

[`execution_service.py:116`](../src/agent_trading/services/execution_service.py:116) — `_quote_cache` 존재:

```python
self._quote_cache: dict[str, tuple[Quote, datetime]] = {}
_QUOTE_CACHE_TTL = 5  # seconds
```

**문제점:**
- cache는 `ExecutionService` 인스턴스에 local
- Path A (`_resolve_symbol_price`)는 `ExecutionService`를 거치지 않음 → cache miss
- Path B (`_resolve_quote`)는 cache를 참조하지만, Path A와의 시간 간격이 AI agent 실행 시간(35s+)보다 길어 TTL(5s) 내에 도달 불가
- **Cache hit ratio = 0%** (cycle 내 첫 번째 quote fetch가 cache에 저장되더라도 같은 cycle에서 재사용되지 않음)

---

## 2. 단계별/심볼별 Quote 호출 횟수 매트릭스

### 2.1 Symbol 1개 기준

| 단계 | 경로 | 비고 | API 호출 |
|------|------|------|----------|
| Pre-decision | `_resolve_symbol_price()` | 결과 미사용 (price=None) | 1회 |
| AI assemble | `DecisionOrchestratorService.assemble()` | quote fetch 없음 | 0회 |
| Execution pipeline | `_resolve_quote()` → sizing | reference_price 획득 | 1회 |
| Translate/Submit | `build_submit_order_request_from_decision()` | quote fetch 없음 | 0회 |
| **Symbol 합계** | | | **2회** |

### 2.2 30개 Symbol 기준

| 항목 | 값 |
|------|-----|
| Symbol당 quote 호출 | 2회 |
| **총 quote 호출** (30 symbols) | **60회** |
| 동시 실행 (Semaphore) | 5 |
| Quote당 예상 시간 | ~1s (network) ~ 10s (timeout) |
| Quote 병목 예상 wall clock | 60 ÷ 5 × 1s ≈ **12s** (정상) / 최대 60s (timeout) |
| KIS MARKET_DATA bucket capacity | 100 (refill 10/s) → 충분 |
| **중복 호출로 인한 낭비** | **30회 (50%)** |

---

## 3. 중복 호출 식별 결과

### 3.1 동일 symbol/cycle 내 중복

**식별된 중복:** `_resolve_symbol_price()` → `_resolve_quote()` (2회)

[`run_decision_loop.py:738`](../scripts/run_decision_loop.py:738)에서 호출된 `_resolve_symbol_price()`의 결과는 [`_resolve_order_type_and_price()`](../scripts/run_decision_loop.py:177)가 항상 `(OrderType.MARKET, None)`을 반환하므로 **실제 주문 가격에 반영되지 않음**.

```python
# scripts/run_decision_loop.py:744-749
order_type, price = _resolve_order_type_and_price(
    side="buy",
    decision_type=None,
    default_price=resolved_price,  # ← 이 값이 무시됨
)
return OrderType.MARKET, None  # ← 항상 price=None
```

이후 [`execution_service.py:565`](../src/agent_trading/services/execution_service.py:565):
```python
elif intent.request.price is None:  # ← True
    _resolved_quote, reference_price = await self._resolve_quote(...)
```

→ **동일 symbol에 대해 2번째 quote fetch 발생**

### 3.2 중복이 아닌 것

- `assemble()` 단계: quote fetch 없음 (DB/Repository 조회만)
- HP_SELL bypass: `is_hp_sell=True` 시 `_resolve_quote()` 내부에서 broker 호출 스킵
- sizing engine (`calculate_sizing`): 순수 함수, quote fetch 없음

### 3.3 Held Position Sell 예외

HP_SELL (REDUCE/EXIT)의 경우:
1. `_resolve_quote()`에서 `is_hp_sell=True` → `return {}, None` (broker 호출 생략)
2. `run_execution_pipeline()` Phase 1.5에서도 HP_SELL bypass

→ **HP_SELL은 quote fetch 0회** (Path A의 `_resolve_symbol_price()`는 여전히 호출됨)

---

## 4. Rate Limit 악화 요인

### 4.1 RateLimitBudget 설정

[`rate_limit.py:197-211`](../src/agent_trading/brokers/rate_limit.py:197):

| Bucket | Capacity | Refill Rate | Quote 사용 여부 |
|--------|----------|-------------|----------------|
| MARKET_DATA | 100 | 10.0/s | ✅ quote fetch가 사용 |
| ORDER | 30 | 2.0/s | ❌ |
| INQUIRY | 60 | 5.0/s | ❌ |
| RECONCILIATION | 20 | 1.0/s | ❌ |
| GLOBAL_REST | 0 (disabled) | - | ❌ |

MARKET_DATA bucket은 100 tokens / 10s refill → 30 symbols × 2 = 60 tokens는 capacity 내.
**Token-bucket 자체는 병목 원인이 아님.**

### 4.2 retry/backoff 구조

[`rest_client.py:378-391`](../src/agent_trading/brokers/koreainvestment/rest_client.py:378):

| 컴포넌트 | 설정값 |
|----------|--------|
| `ExponentialBackoff` | base=1.0s, max=60.0s, jitter=0.1 |
| `CircuitBreaker` | failure_threshold=5, recovery_timeout=30s |
| `_request()` timeout | httpx default (설정 없음) |

**`_request()`에는 retry loop가 없음** — 1회 실패 시 즉시 `BrokerError` raise.
재시도는 `_resolve_quote()`의 `except Exception` 블록에서만 처리 (fallback empty quote 반환).

### 4.3 동시성 구조

[`run_decision_loop.py:1197`](../scripts/run_decision_loop.py:1197):
```python
_SEMAPHORE_MAX = 5
sem = asyncio.Semaphore(_SEMAPHORE_MAX)
```

30개 symbol이 Semaphore(5)로 동시 실행.
각 symbol은 `_resolve_symbol_price()` → (AI agents ~35s) → `_resolve_quote()` 순서로 진행.

**동시 quote fetch peak = 5** (Semaphore 제한). KIS 입장에서는 초당 5회 quote 요청.
KIS 실시간 시세 API의 실질적인 rate limit이 초당 1~2회 정도라면 5회 동시 요청에서 `EGW00201` 발생 가능.

### 4.4 EGW00201 오류 처리

[`rest_client.py:207`](../src/agent_trading/brokers/koreainvestment/rest_client.py:207):
```python
"EGW00201",  # 입력값형식오류
```

이 에러는 `_KNOWN_FAILURE_CODES`에 포함되어 `_raise_on_error()`에서 `BrokerErrorType.ORDER_REJECTED`로 변환.
`_resolve_quote()`에서는 `except Exception`으로 캐치되어:
- circuit breaker 실패 카운트 증가
- fallback empty Quote 반환

---

## 5. 개선 방안 설계

### Phase 1: 중복 Quote Fetch 제거 (즉시 적용 가능)

#### 1-A: `_resolve_symbol_price()` 제거 또는 조건부 실행

**현황:** [`run_decision_loop.py:737-742`](../scripts/run_decision_loop.py:737):
```python
broker = runtime.get("primary_broker_adapter")
resolved_price = await _resolve_symbol_price(symbol, market, broker)
```

**제안:** `_resolve_symbol_price()` 호출을 생략. price는 항상 `None`으로 설정 (MARKET 주문이므로).

```python
# 변경 후
resolved_price = None  # _resolve_symbol_price() 호출 제거
```

**영향:**
- quote fetch 30회 절감 (30 symbols 기준)
- `_resolve_symbol_price()` 로그 observability 상실 → 필요시 별도 메트릭 수집

#### 1-B: `_resolve_symbol_price()` 결과를 `request.price`에 전달

**대안:** `_resolve_symbol_price()`의 결과를 `SubmitOrderRequest.price`에 설정하여
`_resolve_quote()`의 조건(`price is None`)을 우회.

```python
# run_decision_loop.py:744-749 수정
order_type, price = _resolve_order_type_and_price(
    side="buy",
    decision_type=None,
    default_price=resolved_price,  # price에 resolved_price 전달
)
```

단, `_resolve_order_type_and_price()`의 반환 로직을 변경해야 함:
```python
def _resolve_order_type_and_price(*, side, decision_type=None, default_price=None):
    return OrderType.MARKET, default_price  # default_price를 price로 사용
```

**영향:**
- quote fetch 30회 절감 (동일)
- `reference_price`가 `SizingInputs.requested_price`로 전달되어 sizing 정확도 향상
- 단, MARKET 주문에 `price`가 설정되면 KIS API에서 LIMIT 주문으로 오해할 수 있으므로
  `order_type == MARKET` 조건으로 price 무시 필요

#### 1-C: Cycle-local Quote Cache 공유

**제안:** `_resolve_symbol_price()`의 결과를 in-memory dict에 저장하고,
`_resolve_quote()`가 동일 symbol에 대해 재사용하도록 `ExecutionService`에 전달.

```python
# run_decision_loop.py
cycle_quote_cache: dict[str, Quote] = {}

# _resolve_symbol_price() 호출 시 cache에 저장
quote = await broker.get_quote(symbol, market)
cycle_quote_cache[symbol] = quote

# assemble_and_submit()에 cache 전달
await orchestrator.assemble_and_submit(
    request,
    order_manager=order_manager,
    broker=broker,
    quote_cache=cycle_quote_cache,  # ★ 추가
)
```

**`execution_service.py` 수정:**
```python
async def run_execution_pipeline(self, ..., quote_cache=None):
    ...
    if symbol in (quote_cache or {}):
        quote = quote_cache[symbol]
        reference_price = quote.last or quote.ask or quote.bid
    else:
        _resolved_quote, reference_price = await self._resolve_quote(...)
```

### Phase 2: Quote Cache TTL 최적화

#### 2-A: `_QUOTE_CACHE_TTL` 증가

현재 5초 → cycle 시간(~300s) 내에서는 무의미.
Cycle 간 reuse를 위해 **`_QUOTE_CACHE_TTL = 300`** (1 cycle 주기)로 증가.

```python
_QUOTE_CACHE_TTL = 300  # 300초 = 1 cycle
```

단, cycle 간 quote staleness 위험存在. 
정확한 sizing보다 rate limit 회피가 우선이라면 trade-off 수용 가능.

#### 2-B: HP_SELL의 `_resolve_symbol_price()` 스킵

HP_SELL symbol의 경우 `_resolve_symbol_price()`도 스킵:

```python
# run_decision_loop.py
if source_type != "held_position":
    resolved_price = await _resolve_symbol_price(symbol, market, broker)
else:
    resolved_price = None
```

### Phase 3: Rate Limit 튜닝

#### 3-A: MARKET_DATA bucket capacity 증가

```python
# rate_limit.py build_kis_budget_manager()
market_data_capacity=200,   # 100 → 200
market_data_refill_rate=20, # 10 → 20
```

#### 3-B: Quote fetch에 retry 추가

`_resolve_quote()`의 except 블록에 지수 백오프 retry 추가:

```python
# execution_service.py _resolve_quote()
for attempt in range(3):
    try:
        quote = await asyncio.wait_for(
            broker.get_quote(symbol, market), timeout=10.0
        )
        break
    except Exception:
        if attempt < 2:
            await asyncio.sleep(2 ** attempt)  # 1s, 2s backoff
            continue
        raise
```

---

## 6. 예상 Wall Clock 영향

### 6.1 Quote Fetch 횟수 감소율

| 시나리오 | 현재 | Phase 1-A 적용 | Phase 1-B+C | 감소율 |
|----------|------|----------------|-------------|--------|
| 30 symbols submit | 60회 | 30회 | 30회 | **50%** |
| HP_SELL 포함 30 symbols | 30~60회 | 0~30회 | 0~30회 | 50~100% |
| Dry-run (30 symbols) | 30회 | 0회 | 0회 | **100%** |

### 6.2 Wall Clock 단축 예상

| 구간 | 현재 (추정) | 개선 후 (추정) |
|------|-------------|----------------|
| Quote fetch (정상, ~1s/call) | 60 ÷ 5 × 1s = 12s | 30 ÷ 5 × 1s = 6s |
| Quote fetch (EGW00201 포함, ~3s/call) | 60 ÷ 5 × 3s = 36s | 30 ÷ 5 × 3s = 18s |
| AI agents (고정) | ~35s | ~35s |
| **총 wall clock** (정상) | **~50s** | **~44s** (~12% 단축) |
| **총 wall clock** (EGW00201) | **~75s** | **~57s** (~24% 단축) |

### 6.3 EGW00201 발생 확률 감소 효과

현재 30 symbols × 2회 = 60회 quote 호출 중 KIS rate limit에 걸릴 확률이 P라면,
Phase 1 적용 후 30회로 줄어들면 **rate limit hit 확률도 50% 감소**.

---

## 7. 실행 계획 요약

### Step 1: Phase 1-A (즉시, 저위험)
- [`run_decision_loop.py:737-742`](../scripts/run_decision_loop.py:737) — `_resolve_symbol_price()` 호출 제거
- `resolved_price = None`으로 변경
- `_resolve_order_type_and_price()`와 `SubmitOrderRequest.price`는 변경 없음

### Step 2: Phase 1-B (중간 위험)
- `_resolve_order_type_and_price()`가 `default_price`를 반환하도록 수정
- `request.price`에 resolved price 설정 → `_resolve_quote()` 조건 우회
- 단, MARKET 주문에서 price 필드 처리 확인 필요

### Step 3: Phase 3-B (선택)
- `_resolve_quote()`에 2회 retry + 지수 백오프 추가
- circuit breaker 연동 유지

### Step 4: Phase 2 (선택, 장기)
- `_QUOTE_CACHE_TTL` 증가 검토
- Cycle-local cache 공유 메커니즘 설계

---

## 부록: 참조 코드

| 파일 | 라인 | 내용 |
|------|------|------|
| [`run_decision_loop.py`](../scripts/run_decision_loop.py:107) | 107-174 | `_resolve_symbol_price()` — Path A |
| [`run_decision_loop.py`](../scripts/run_decision_loop.py:177) | 177-191 | `_resolve_order_type_and_price()` — 항상 `(MARKET, None)` |
| [`run_decision_loop.py`](../scripts/run_decision_loop.py:738) | 738 | `_resolve_symbol_price()` 호출 지점 |
| [`run_decision_loop.py`](../scripts/run_decision_loop.py:744) | 744 | `_resolve_order_type_and_price()` 호출 |
| [`execution_service.py`](../src/agent_trading/services/execution_service.py:76) | 76 | `_QUOTE_CACHE_TTL = 5` |
| [`execution_service.py`](../src/agent_trading/services/execution_service.py:116) | 116 | `_quote_cache` 선언 |
| [`execution_service.py`](../src/agent_trading/services/execution_service.py:174) | 174-290 | `_resolve_quote()` — Path B |
| [`execution_service.py`](../src/agent_trading/services/execution_service.py:558) | 558-576 | HP_SELL bypass + `_resolve_quote()` 호출 조건 |
| [`rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py:207) | 207 | EGW00201 in `_KNOWN_FAILURE_CODES` |
| [`rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py:769) | 769-863 | `_request()` — budget check + circuit breaker |
| [`rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py:1533) | 1533-1554 | `get_quote()` — 실제 API 호출 |
| [`rate_limit.py`](../src/agent_trading/brokers/rate_limit.py:197) | 197-211 | `MARKET_DATA` bucket 설정 (capacity=100, refill=10/s) |
| [`rate_limit.py`](../src/agent_trading/brokers/rate_limit.py:302) | 302-379 | `consume_or_raise()` — 2-tier budget check |
