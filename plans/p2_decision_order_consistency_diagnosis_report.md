# Phase 2 잔존 Decision/Order 정합성 문제 진단 보고서

> **작성일**: 2026-05-20  
> **진단 대상**: `trade_decisions` vs `order_requests` 정합성  
> **분석 방법**: DB sampling, 코드 경로 추적, Agent output 대조

---

## 목차

1. [문제 1: 비정상 TD (`decision_type='sell'` + `side='buy'`)](#1-비정상-td-decision_typesell--sidebuy)
2. [문제 2: 음수 lag (`order_created_at < td_created_at`)](#2-음수-lag-order_created_at--td_created_at)
3. [추가 발견: FDC output vs 실제 TD 불일치](#3-추가-발견-fdc-output-vs-실제-td-불일치)
4. [종합 수정 방안](#4-종합-수정-방안)

---

## 1. 비정상 TD (`decision_type='sell'` + `side='buy'`)

### 1.1 현상

DB에서 다음 TD가 발견됨:

| 컬럼 | 값 |
|------|------|
| `trade_decision_id` | `35c6c00c-5e8c-48d8-8573-b578119b993c` |
| `decision_context_id` | `5793812c-ab07-4c70-bf5c-0bc061d0f8cd` |
| `decision_type` | `sell` ← `DecisionType` enum에 없는 값 |
| `side` | `buy` |
| `symbol` | `TEST` |
| `agent_run_id` | `NULL` |
| `strategy_id` | `NULL` |
| `decision_json` | `'{}'` |
| `created_at` | `2026-05-20 10:06:53` |

### 1.2 원인

**이 TD는 정상 코드 경로(`_ensure_trade_decision()`)를 통해 생성되지 않았음.**

근거:
1. [`DecisionType` enum](src/agent_trading/domain/enums.py:106)은 `APPROVE, REJECT, HOLD, WATCH, EXIT, REDUCE`만 정의 — `sell`은 **유효하지 않은 enum 값**
2. [`_resolve_decision_type()`](src/agent_trading/services/decision_orchestrator.py:2696)은 `DecisionType("sell")`에서 `ValueError` → `DecisionType.HOLD` 반환. DB에 `'sell'`이 저장될 수 없음
3. [`PostgresTradeDecisionRepository.add()`](src/agent_trading/repositories/postgres/trade_decisions.py:82)는 `decision.decision_type.value`를 INSERT — 문자열 `"sell"`에 `.value` 호출 시 `AttributeError`
4. `symbol='TEST'`, `agent_run_id=NULL`, `strategy_id=NULL`, `decision_json='{}'` — 일반 실행 경로에서는 불가능한 조합
5. 동일 컨텍스트(`5793812c`)의 correlation_id = `test-readable-api-1258ee0e` — [통합 테스트](tests/integration/test_orchestrator_entrypoint.py:395) 패턴과 일치하지만, **테스트 코드는 `SYMBOL="005930"`** 사용, `TEST` 사용하지 않음

**추정 경로**: DB에 직접 SQL INSERT로 주입되었거나, 별도 수동 테스트 과정에서 생성된 데이터로 판단됨. 연결된 `order_request`도 없음 (`order_created_at IS NULL`).

### 1.3 영향

- **없음**. 이 TD는 어떤 order와도 연결되어 있지 않으며, 실제 운영 로직에 영향을 주지 않는 테스트 잔여물.

---

## 2. 음수 lag (`order_created_at < td_created_at`)

### 2.1 현황

- **총 145개** order가 `order.created_at < td.created_at` 상태
- lag 범위: **-6.9초 ~ -258.5초** (약 4분)
- 모든 `paper-loop-*` correlation_id에서 동일 패턴 관찰

### 2.2 근본 원인: `created_at` 결정 메커니즘 불일치

두 테이블이 `created_at`을 결정하는 방식이 **서로 다름**:

#### [`trade_decisions`](src/agent_trading/services/decision_orchestrator.py:2298-2315)

```
now = datetime.now(timezone.utc)   # ← Python wall clock (실제 시각)
...
created_at=now,                     # INSERT SQL에 명시적 포함
```

- `_ensure_trade_decision()` 내에서 Python의 `datetime.now(timezone.utc)`로 결정
- INSERT SQL에도 [`created_at` 컬럼이 $41 파라미터로 명시](src/agent_trading/repositories/postgres/trade_decisions.py:55,124)

#### [`order_requests`](src/agent_trading/repositories/postgres/orders.py:35-42)

```sql
INSERT INTO trading.order_requests
    (order_request_id, account_id, instrument_id,
     client_order_id, idempotency_key, correlation_id,
     side, order_type, time_in_force,
     requested_price, requested_quantity,
     status, status_reason_code, status_reason_message,
     trade_decision_id, decision_context_id, submitted_at)
    -- ↑ created_at이 INSERT 컬럼 목록에 없음!
VALUES ($1, $2, $3, ...)
RETURNING *
```

- **`created_at`이 INSERT SQL 컬럼 목록에 없음**
- DB 컬럼 기본값 `now()`가 사용됨
- PostgreSQL에서 `now()`는 **트랜잭션 시작 시각** (statement_timestamp()와 다름)

### 2.3 발생 메커니즘

```
Transaction Start (T1 = 05:07:16)  ← DB now()는 이 시각 고정
    │
    ├── agents 실행 (LLM API 호출, ~2분 소요)
    │   │
    │   └── _ensure_trade_decision()
    │       now = datetime.now(timezone.utc)  ← T2 = 05:09:22
    │       TD.created_at = T2
    │       INSERT INTO trade_decisions ... created_at = T2
    │
    └── order_manager.create_order()
        INSERT INTO order_requests ... created_at = DB now() = T1 (트랜잭션 시작 시각)
        → order.created_at = T1 = 05:07:16

Result: order.created_at (T1) < td.created_at (T2) → 음수 lag = -126초
```

**실제 사례** ([`32611e41` 컨텍스트](src/agent_trading/services/decision_orchestrator.py:520)):

| 항목 | 값 |
|------|------|
| Transaction start | `2026-05-20 05:07:16` (order.created_at) |
| FDC agent completed | `2026-05-20 05:09:22` |
| TD created_at | `2026-05-20 05:09:22` (Python wall clock) |
| `client_order_id` suffix | `0509229675` (= 05:09:22, Python timestamp) |
| Lag | **-126.5초** |

`client_order_id` 접미사(`0509229675`)가 order의 DB `created_at`(05:07:16)이 아닌 Python 시각(05:09:22)을 사용하는 점도 동일한 불일치를 입증.

### 2.4 차수별 lag 패턴

| 날짜 | Lag 범위 | 평균 lag |
|------|---------|---------|
| 2026-05-14 | -7s ~ -11s | ~ -9s |
| 2026-05-15 | -7s ~ -11s | ~ -9s |
| 2026-05-18 | -37s ~ -43s | ~ -39s |
| 2026-05-19 | -6s ~ -12s | ~ -9s |
| 2026-05-20 | -50s ~ -258s | ~ -126s |

**5/18, 5/20에 lag가 큰 이유**: LLM API latency 변동으로 agent 실행 시간이 길어져 transaction duration이 증가했기 때문.

---

## 3. 추가 발견: FDC output vs 실제 TD 불일치

### 3.1 정상 케이스 (held_position_sell_override)

FDC가 `HOLD`를 출력해도 [`_check_held_position_sell_override()`](src/agent_trading/services/decision_orchestrator.py:460)가 `reduce`/`exit`로 변경하는 사례:

| correlation_id | FDC 출력 | 최종 TD | 비고 |
|---------------|---------|---------|------|
| `paper-loop-000150-1-27437` | `REDUCE/SELL` | `reduce/sell` | FDC 자체 판단 → 정상 |
| `paper-loop-000210-1-27437` | `HOLD/""` | `reduce/sell` | override 작동 |
| `paper-loop-000270-1-27437` | `HOLD/""` | `reduce/sell` | override 작동 |
| `paper-loop-000660-1-27437` | `HOLD/""` | `exit/sell` | override 작동 |
| `paper-loop-000810-1-27437` | `HOLD/""` | `exit/sell` | override 작동 |

✅ **정상 동작** — held_position logic이 FDC의 HOLD 결정을 실제 보유 포지션 정보로 override

### 3.2 단순 전달 케이스

| correlation_id | FDC 출력 | 최종 TD |
|---------------|---------|---------|
| `test-readable-api-*` | `HOLD/BUY` | `hold/buy` |
| `paper-loop-000720-1-27719` | `HOLD/""` | `hold/buy` |
| `paper-loop-020150-1-27321` | `HOLD/""` | `hold/buy` |

✅ **정상 동작** — FDC 출력이 그대로 TD에 반영

---

## 4. 종합 수정 방안

### 4.1 [필수] `order_requests.created_at` 동기화 (음수 lag 해결)

**원인**: Order INSERT에 `created_at` 누락 → DB `now()` 기본값 → 트랜잭션 시작 시각 사용  
**수정 대상**: [`PostgresOrderRepository.add()`](src/agent_trading/repositories/postgres/orders.py:31-62)

#### 방안 A (권장): INSERT에 `created_at` 명시

[`order_manager.create_order()`](src/agent_trading/services/order_manager.py:306)에서 이미 `now = datetime.now(timezone.utc)`를 계산하고 있음. 이 값을 `created_at`으로 INSERT에 포함:

```python
# order_manager.py:306-320
now = datetime.now(timezone.utc)
order = OrderRequestEntity(
    ...
    created_at=now,    # ← 이미 entity에 설정됨
)
```

**변경**: `orders.py`의 INSERT SQL에 `created_at` 컬럼 추가:

```sql
INSERT INTO trading.order_requests
    (order_request_id, account_id, instrument_id,
     client_order_id, idempotency_key, correlation_id,
     side, order_type, time_in_force,
     requested_price, requested_quantity,
     status, status_reason_code, status_reason_message,
     trade_decision_id, decision_context_id, submitted_at,
     created_at)                              -- ← 추가
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
        $12, $13, $14, $15, $16, $17, $18)   -- ← $18 추가
```

```python
# 파라미터에도 order.created_at 추가
order.order_request_id,
...
order.submitted_at,
order.created_at,   # ← 추가
```

**효과**: TD와 order가 동일한 `now` 인스턴스를 사용 → `td.created_at ≈ order.created_at` (수 밀리초 차이)

#### 방안 B: TD도 DB `now()` 사용

`_ensure_trade_decision()`에서 `created_at=now` 대신 `created_at=None`으로 설정하고, DB 기본값 `now()` 사용. 단, 이 경우 `TradeDecisionRepository.add()` INSERT에서 `created_at`을 제외해야 함.

**비권장**: Python에서 생성 시각을 제어할 수 없게 됨. `get_by_context()` 정렬 등에 영향.

### 4.2 [선택] `decision_type` 컬럼 CHECK 제약 조건 검토

**현재**: `decision_type` 컬럼에 enum 기반 CHECK 제약이 없음 (`VARCHAR`), `_resolve_decision_type()`이 Fallback `HOLD` 처리  
**리스크**: 유효하지 않은 값(`sell`, `buy` 등)이 DB에 직접 INSERT될 수 있음

**수정 대상**: DB migration

```sql
ALTER TABLE trading.trade_decisions
    ADD CONSTRAINT chk_decision_type_valid
    CHECK (decision_type IN ('approve', 'reject', 'hold', 'watch', 'exit', 'reduce'));
```

단, 이 변경은 현재 존재하는 `'sell'`, `'buy'` 값을 먼저 정리해야 함.

### 4.3 [선택] `get_by_context()` 대신 `decision_id` 직접 사용 검증

현재 [`assemble_and_submit()`](src/agent_trading/services/decision_orchestrator.py:956-963)에서 `get_by_context()`로 최신 TD를 조회하는 로직은 **진단 목적**으로만 사용됨. 실제 order 생성은 `intent.request.decision_id`를 사용하므로 TD 연결 자체는 정확함.

다만, 동일 컨텍스트에 여러 TD가 쌓일 경우 `get_by_context()`가 의도치 않은 TD를 반환할 가능성 존재. (현재 `ORDER BY created_at DESC, trade_decision_id DESC`로 최신 1건만 반환)

---

## 요약

| 문제 | 심각도 | 원인 | 수정 |
|------|--------|------|------|
| `decision_type='sell'` TD | 낮음 (테스트 잔여물) | 직접 SQL INSERT | CHECK 제약 추가 (선택) |
| `order.created_at < td.created_at` | **중간** (145건) | Order INSERT에 `created_at` 누락 → DB `now()`=트랜잭션 시각 vs TD는 Python wall clock | **INSERT에 `created_at` 명시 (필수)** |
| FDC output 불일치 | 없음 (정상 동작) | `held_position_sell_override` 정상 작동 | 불필요 |

---

## 최종 진단: 질문별 답변

### Q1. 비정상 TD (`sell`+`buy`)의 구체적인 생성 코드 경로는?

**A1**. 정상 코드 경로(`_ensure_trade_decision()` → `PostgresTradeDecisionRepository.add()`)를 통하지 않음. `DecisionType` enum에 없는 `'sell'` 값이 DB에 저장된 점, `symbol='TEST'`, `agent_run_id=NULL`, `strategy_id=NULL`, `decision_json='{}'`인 점이 결정적 증거. **DB에 직접 SQL INSERT된 것으로 판단**되며, `correlation_id = test-readable-api-1258ee0e`와 연관됨. 연결된 order_request가 없어 실제 영향은 없음.

### Q2. 6개 negative lag의 정확한 발생 기전과 전수 패턴은?

**A2**. **145건 전수 확인** (6건이 아님). 발생 기전:
1. `order_requests.created_at` = DB `now()` = **트랜잭션 시작 시각** (INSERT SQL에서 created_at 생략)
2. `trade_decisions.created_at` = Python `datetime.now(timezone.utc)` = **LLM API 호출 완료 후 실제 시각**
3. LLM API latency(1~3분) 동안 transaction이 열려 있으므로 `order.created_at < td.created_at` 발생
4. lag 범위: **-6.9초 ~ -258.5초**, LLM 응답 시간에 비례

### Q3. `assemble_and_submit()`에서 `get_by_context()`로 가져온 TD와 실제 order가 연결된 TD가 다른 경우가 있는가?

**A3**. **발견되지 않음.** `get_by_context()`는 `assemble_and_submit()`에서 **진단 목적**으로만 사용됨(줄 956-963). 실제 order-TD 연결은 `_ensure_trade_decision()`이 반환한 `trade_decision_id`가 `intent.request.decision_id` → `SubmitOrderRequest.decision_id` → `order.trade_decision_id`로 전달되어 정확히 연결됨. 다만 동일 컨텍스트에 여러 TD가 존재하는 경우, `get_by_context()`가 예상과 다른 TD를 반환할 수 있으나 order 연결에는 영향 없음.

### Q4. "현재 사이클의 TD를 보장"하는 최소 변경은?

**A4**. **Order INSERT에 `created_at` 명시 추가.** [`PostgresOrderRepository.add()`](src/agent_trading/repositories/postgres/orders.py:35-42)의 INSERT SQL에 `created_at` 컬럼을 추가하고, [`OrderManager.create_order()`](src/agent_trading/services/order_manager.py:306)에서 이미 계산한 `now`를 값으로 전달. 이렇게 하면 TD와 order가 동일한 `datetime.now(timezone.utc)` 값을 사용하게 되어 `td.created_at ≈ order.created_at`이 보장됨. 변경 범위는 `orders.py` 한 파일, 2-3줄 수정.
