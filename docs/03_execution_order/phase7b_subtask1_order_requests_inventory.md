# Phase 7b Subtask 1 — order_requests 인벤토리 분석

> 기준 시점: 2026-05-30 00:00 KST (UTC 2026-05-29 15:00Z)  
> 분석 범위: `created_at >= '2026-05-26T15:00:00Z' AND created_at < '2026-05-29T15:00:00Z'`  
> (KST 2026-05-27 00:00 ~ 2026-05-30 00:00)

---

## 1. 전체 통계

| 지표 | 값 |
|------|-----|
| 전체 order_requests | 480건 (BUY 433, SELL 47) |
| broker_orders 존재 | 214건 (44.6%) |
| broker_orders 미존재 | 266건 (55.4%) — 전부 rejected |

### 상태별 분포

| 상태 | 건수 | broker_orders 있음 | broker_orders 없음 |
|------|------|-------------------|-------------------|
| `rejected` | 233 | 0 | 233 |
| `expired` | 209 | 176 | 33 |
| `filled` | 22 | 22 | 0 |
| `reconcile_required` | 16 | 16 | 0 |

### KST 일자별 분포

| KST 일자 | expired | filled | reconcile_required | rejected | 합계 |
|----------|---------|--------|-------------------|----------|------|
| 2026-05-27 | 19 | 4 | 2 | 131 | 156 |
| 2026-05-28 | 106 | 10 | 9 | 101 | 226 |
| 2026-05-29 | 84 | 8 | 5 | 1 | 98 |

---

## 2. `decision_type` × `status` 교차 분석

| decision_type | expired | filled | reconcile_required | rejected | 합계 |
|---------------|---------|--------|-------------------|----------|------|
| `approve` | 192 | 0 | 12 | 92 | 296 |
| `hold` | 9 | 0 | 2 | 131 | 142 |
| `reduce` | 8 | 21 | 2 | 2 | 33 |
| `exit` | 0 | 1 | 0 | 8 | 9 |

### 핵심 인사이트

1. **`hold` decision_type에서 142건의 order_request 생성됨** — `hold`는 주문을 생성하지 않아야 하는 결정인데, order_request가 생성되고 broker_orders 없이 `rejected`/`expired`로 처리됨. 이는 **Order Manager의 `decision_type` 필터링 누락**으로 추정.
2. **`approve` BUY 주문 192건이 `expired`** — 이 중 159건은 정상 expired (broker_orders 있음, sync cycle에서 `RECONCILE_REQUIRED` → `EXPIRED` 전이), 33건은 EOD orphan cleanup으로 expired.
3. **`reduce` SELL 주문 21건 `filled`** — 정상 체결. SELL 주문은 대부분 정상 처리됨.

---

## 3. Critical Problem #1: `order_requests.requested_quantity`가 전량 `1`로 고정

### 증상

```sql
-- BUY 주문 433건 전부 requested_quantity = 1
SELECT COUNT(*) FROM trading.order_requests o
JOIN trading.trade_decisions td ON o.trade_decision_id = td.trade_decision_id
WHERE o.created_at >= '2026-05-26T15:00:00Z'
  AND o.created_at < '2026-05-29T15:00:00Z'
  AND LOWER(o.side) = 'buy'
  AND o.requested_quantity = 1;
-- 결과: 433

SELECT COUNT(*) FROM ... WHERE LOWER(o.side) = 'buy' AND o.requested_quantity != 1;
-- 결과: 0
```

### 영향 범위

- **BUY 주문 433건 전부** `requested_quantity=1`로 왜곡됨
- 실제 `trade_decisions.quantity`는 Phase 7 backfill로 수정되었으나 (3~1630), `order_requests.requested_quantity`는 그대로 `1`
- SELL 주문 47건 중 19건도 불일치 (반대 방향: `requested_quantity=2~26` vs `td.quantity=1`)
- FILLED 주문 22건도 `requested_quantity`가 왜곡되어 있어, 실제 체결 수량과의 비교가 불가능

### 원인

[`backfill_buy_trade_decision_quantity.py`](scripts/backfill_buy_trade_decision_quantity.py:338)의 [`apply_backfill()`](scripts/backfill_buy_trade_decision_quantity.py:338) 함수는 **`trading.trade_decisions` 테이블만 UPDATE**하고, `trading.order_requests` 테이블은 전혀 건드리지 않음:

```sql
UPDATE trading.trade_decisions td
SET quantity = sub.new_qty
FROM (VALUES ...) AS sub(trade_decision_id, new_qty)
WHERE td.trade_decision_id = sub.trade_decision_id::uuid
  AND td.quantity = 1
```

`order_requests`의 `requested_quantity`는 [`PostgresOrderRepository.add()`](src/agent_trading/repositories/postgres/orders.py:31)에서 INSERT 시점에 `order.requested_quantity` 값으로 설정됨. 이 값은 Order Manager가 `trade_decisions.quantity`를 읽어서 전달해야 하지만, 당시에는 `trade_decisions.quantity=1`이었으므로 그대로 `1`이 저장됨.

### 저위험 해결 방안

**Phase 7b backfill 스크립트 신규 작성** — `order_requests.requested_quantity`를 `trade_decisions.quantity`와 동기화:

```sql
-- 의사 코드
UPDATE trading.order_requests o
SET requested_quantity = td.quantity
FROM trading.trade_decisions td
WHERE o.trade_decision_id = td.trade_decision_id
  AND o.requested_quantity != td.quantity
  AND LOWER(o.side) = 'buy'
  AND o.created_at >= '2026-05-26T15:00:00Z'
```

**안전장치**:
- `requested_quantity`는 [`update_status()`](src/agent_trading/repositories/postgres/orders.py:148)에서 수정되지 않는 필드이므로, 별도 UPDATE 구문 필요
- `order_state_events` 히스토리와의 정합성은 별도 검토 필요
- SELL 주문의 역방향 불일치(19건)는 별도 분석 후 처리

---

## 4. Problem #2: `reconcile_required` 잔존 16건

### 상세 현황

| # | 생성시각(KST) | side | decision_type | requested_qty | td.quantity | broker_native_order_id | last_synced_at |
|---|-------------|------|---------------|--------------|-------------|----------------------|---------------|
| 1 | 5/27 06:05 | BUY | hold | 1 | 1 | 0000034878 | 5/29 06:36 |
| 2 | 5/27 06:14 | BUY | hold | 1 | 1 | 0000035601 | 5/29 06:36 |
| 3 | 5/27 23:50 | BUY | approve | 1 | 10 | 0000000673 | 5/29 06:36 |
| 4 | 5/27 23:58 | BUY | approve | 1 | 10 | 0000000749 | 5/29 06:36 |
| 5 | 5/28 03:29 | SELL | reduce | 3 | 1 | 0000023345 | 5/29 06:36 |
| 6 | 5/28 06:06 | BUY | approve | 1 | 11 | 0000034364 | 5/29 06:36 |
| 7 | 5/28 06:07 | BUY | approve | 1 | 56 | 0000034386 | 5/29 06:36 |
| 8 | 5/28 06:07 | BUY | approve | 1 | 37 | 0000034390 | 5/29 06:36 |
| 9 | 5/28 06:21 | BUY | approve | 1 | 3 | 0000035513 | 5/29 06:36 |
| 10 | 5/28 06:21 | BUY | approve | 1 | 76 | 0000035534 | 5/29 06:36 |
| 11 | 5/28 06:21 | BUY | approve | 1 | 36 | 0000035537 | 5/29 06:36 |
| 12 | 5/29 06:05 | BUY | approve | 1 | 12 | 0000031736 | 5/29 07:00 |
| 13 | 5/29 06:05 | BUY | approve | 1 | 85 | 0000031759 | 5/29 07:00 |
| 14 | 5/29 06:05 | BUY | approve | 1 | 84 | 0000031790 | 5/29 07:00 |
| 15 | 5/29 06:19 | SELL | reduce | 1 | 1 | 0000032810 | 5/29 07:00 |
| 16 | 5/29 06:19 | BUY | approve | 1 | 11 | 0000032815 | 5/29 07:00 |

### 원인

모든 `reconcile_required` 주문의 `last_synced_at`이 **2026-05-29 06:36~07:00 KST**에 멈춤. 이는 sync cycle이 더 이상 이 주문들을 처리하지 않고 있음을 의미.

[`_sync_reconcile_required_orders()`](src/agent_trading/services/order_sync_service.py:798)는 [`transition_to_authoritative()`](src/agent_trading/services/order_sync_service.py:888)를 호출하여 broker truth를 조회하지만, `resolve_unknown_state()`가 계속 `RECONCILE_REQUIRED`를 반환하거나 예외가 발생하면 해결되지 않음.

특히 **after-hours(15:30 KST~)가 아닌 장중**에는 `EXPIRED` fallback이 억제되므로, broker가 상태를 확정해주지 않는 한 `RECONCILE_REQUIRED`에 영원히 머무를 수 있음.

### 저위험 해결 방안

1. **기존 [`backfill_reconcile_required_orders.py`](scripts/backfill_reconcile_required_orders.py) 실행** — `ReconciliationRun`을 생성하여 강제 해결 시도
2. **수동 broker truth 조회** — 각 `broker_native_order_id`로 KIS API 직접 조회 후, 결과에 따라 수동 상태 전이
3. **after-hours에 EXPIRED fallback 유도** — sync cycle이 after-hours에 실행되면 `transition_to_authoritative()`가 `EXPIRED`로 fallback

---

## 5. Problem #3: `hold` decision_type에서 order_request 생성

### 증상

`decision_type='hold'`인 주문 142건이 `order_requests`에 존재:
- 131건 `rejected` (BUDGET_EXHAUSTED)
- 9건 `expired`
- 2건 `reconcile_required`

`hold`는 "보류" 결정으로, **주문을 생성해서는 안 됨**. 그러나 Order Manager가 `hold` 결정을 필터링하지 않고 order_request를 생성한 것으로 보임.

### 영향 범위

- 142건의 불필요한 order_request 레코드
- 131건은 `BUDGET_EXHAUSTED`로 rejected 처리되어 broker budget 소진 가속화
- 9건은 expired 처리되었으나 sync cycle 리소스 낭비
- 2건은 `reconcile_required`로 잔존하여 추가 관리 필요

### 원인

Order Manager의 [`submit_order()`](src/agent_trading/services/order_sync_service.py:265) 진입점에서 `decision_type`을 검사하지 않음. `hold` 결정도 `approve`와 동일하게 order_request 생성 및 broker 제출을 시도함.

### 저위험 해결 방안

1. **Order Manager에 `hold` 필터링 로직 추가** — `decision_type == 'hold'`이면 order_request 생성 자체를 skip하고 로깅만 수행
2. **기존 hold order_request 정리** — 이미 생성된 142건은 `status_reason_code`를 `'cancelled_by_hold_decision'` 등으로 업데이트하거나, 그대로 두고 신규 생성만 방지

---

## 6. Problem #4: SELL 주문 `requested_quantity` 역방향 왜곡

### 증상

SELL 주문 19건에서 `requested_quantity > td.quantity`:
- `requested_quantity=2~26` vs `td.quantity=1`
- `decision_type`: hold(5), exit(7), reduce(6), approve(0)

이는 BUY와 반대 방향의 왜곡으로, SELL 주문의 `requested_quantity`가 실제보다 큼.

### 원인

SELL 주문은 Phase 7 backfill 대상이 아니었음 (BUY만 대상). SELL의 `trade_decisions.quantity`는 `1`로 남아있지만, `order_requests.requested_quantity`는 원래 의도된 값(2~26)을 유지하고 있음.

즉, **SELL은 `trade_decisions.quantity`가 왜곡**된 것이고, **BUY는 `order_requests.requested_quantity`가 왜곡**된 것.

### 저위험 해결 방안

1. **SELL `trade_decisions.quantity` backfill** — SELL 주문의 실제 의도된 수량을 position 데이터나 fill 데이터에서 재구성
2. **또는 `requested_quantity`를 기준으로 `trade_decisions.quantity` 동기화** — SELL은 `requested_quantity`가 더 신뢰할 수 있으므로 역방향 동기화

---

## 7. 종합: 가장 Critical한 문제

### 1순위: `order_requests.requested_quantity` 전량 왜곡 (BUY 433건)

**왜 가장 critical한가?**

1. **영향 범위가 가장 큼** — 분석 기간 내 BUY 주문 100% 영향
2. **데이터 무결성 훼손** — `order_requests`는 주문의 영구 기록인데, `requested_quantity`가 실제 의도와 다름
3. **FILLED 주문도 영향** — 22건의 filled 주문도 `requested_quantity=1`로 기록되어, 실제 체결 수량과의 비교가 불가능
4. **향후 로직에 악영향** — position 계산, budget 계산, 성과 분석 등이 왜곡된 데이터를 기준으로 수행될 위험
5. **Phase 7 backfill의 미완성** — backfill이 `trade_decisions`만 수정하고 `order_requests`를 누락한 것이 근본 원인

### 권장 조치 순서

1. **Phase 7b: `order_requests.requested_quantity` backfill** (BUY 433건)
   - `trade_decisions.quantity` → `order_requests.requested_quantity` 동기화
   - SELL 19건은 별도 분석 후 처리 (역방향 왜곡)

2. **Order Manager에 `hold` 필터링 추가**
   - `decision_type == 'hold'`면 order_request 생성 skip
   - 신규 hold 주문 생성을 원천 차단

3. **Reconcile_required 16건 해결**
   - [`backfill_reconcile_required_orders.py`](scripts/backfill_reconcile_required_orders.py) 실행
   - 또는 after-hours sync cycle에서 자연 해소 유도

---

## 8. 부록: 상태 전이 맵

```
PENDING_SUBMIT ──(제출 성공)──→ SUBMITTED ──→ ACKNOWLEDGED ──→ PARTIALLY_FILLED ──→ FILLED
       │                              │                                              │
       │(제출 실패)                    │(broker 취소)                                  │
       ├──→ REJECTED                  ├──→ CANCELLED                                  │
       │                              │                                              │
       │(EOD orphan)                  │(미확정)                                        │
       └──→ EXPIRED                   └──→ RECONCILE_REQUIRED ──(broker truth)──→ FILLED/CANCELLED/EXPIRED
                                              │
                                              │(after-hours fallback)
                                              └──→ EXPIRED
```

### Sync cycle 흐름 ([`run_sync_cycle()`](src/agent_trading/services/order_sync_service.py:2453))

1. Stale PENDING_SUBMIT 정리 (30분 초과 → `REJECTED`)
2. Active status 주문 조회 및 sync
3. RECONCILE_REQUIRED 해결 시도 ([`_sync_reconcile_required_orders()`](src/agent_trading/services/order_sync_service.py:798))
4. After-hours에만 EOD orphan cleanup 실행 ([`expire_eod_orphan_orders()`](src/agent_trading/services/order_sync_service.py:2100))

### EOD orphan 조건 ([`_is_eod_orphan()`](src/agent_trading/services/order_sync_service.py:2247))

1. `created_at` > 1시간 전
2. `submitted_at IS NULL`
3. `broker_orders` 없음
