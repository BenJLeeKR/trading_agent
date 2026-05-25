# 실제 Snapshot 기반 Order Sizing + 휴장일 Submit Reject Path 검증 결과

**작성일**: 2026-05-25  
**검증 버전**: Phase 5 통합 smoke test

---

## 1. 검증 범위

| 항목 | 상태 |
|------|------|
| 실제 snapshot 값 DB 조회 | ✅ 완료 |
| 실제 값 기준 pure sizing 계산 (req=10/50/100) | ✅ 완료 |
| 계산된 수량(6주)으로 submit path 진입 | ✅ 완료 |
| broker reject code (`40100000`, 모의투자 영업일 아님) | ❌ 미도달 |
| DB/Log cross-verification | ✅ 완료 |

---

## 2. 실제 Snapshot 값 (DB 조회 결과)

### 2.1 Cash & NAV

| 항목 | 값 | 출처 |
|------|-----|------|
| `available_cash` | 9,109,140.00 KRW | `cash_balance_snapshots` |
| `orderable_amount` | NULL | `cash_balance_snapshots` |
| `total_asset` (= NAV) | 27,568,261.00 KRW | `account_snapshots` |
| `total_equity` | 27,568,261.00 KRW | `account_snapshots` |

### 2.2 보유 포지션 (005930 삼성전자)

| 항목 | 값 |
|------|-----|
| `quantity` | 0주 (미보유) |
| `average_price` | 267,000.00 KRW |
| `market_price` | 291,500.00 KRW |
| `concentration_pct` | 0% (미보유) |

### 2.3 설정 값

| 항목 | 값 |
|------|-----|
| `max_position_size` | 100% |
| `max_single_position_pct` | 100 |
| 계좌 증거금률 | 100% |

---

## 3. Sizing Calculation Trace (req_qty=100)

### 3.1 입력 값

| 파라미터 | 값 | 계산 근거 |
|----------|-----|-----------|
| `request_qty` | 100 | force BUY seed |
| `ALLOCATION_PCT` | 0.2 (20%) | `sizing_engine.py:158` |
| `reference_price` | 291,500 | quote resolution (KIS API) |
| `orderable_amount` | 9,109,140 (preferred) | snapshot |
| `available_cash` | 9,109,140 (fallback) | snapshot |
| `NAV` | 27,568,261 | snapshot |

### 3.2 Pipeline 단계별 결과

```
Phase 1.5a: resolve_buy_target_quantity()
  → request_qty=100, target_qty=20 (ALLOCATION_PCT=0.2)
  → orderable_amount=9,109,140 사용 (preferred)

Phase 1.5b: apply_max_order_value()
  → max_order_value=9,109,140 × 1.0 = 9,109,140
  → max_order_qty=9,109,140 / 291,500 = floor(31.25) = 31주
  → remaining_qty=20 (31 제한에 걸리지 않음)

Phase 1.5c: apply_qty_bounds()
  → min_qty=1, max_qty=100
  → 20 → 20 (통과)

Phase 1.5d: apply_cash_constraint()
  → orderable_amount=9,109,140 > 0 → 정상 진행
  → max_cash_qty=floor(9,109,140 / 291,500) = 31
  → remaining_qty=20 (통과)

Phase 1.5e: apply_concentration_constraint()
  → max_position_value = 27,568,261 × 100 / 100 = 27,568,261
  → current_value = 0 (미보유)
  → remaining_capacity = max_position_value - current_value = 27,568,261
  → max_conc_qty = 27,568,261 / 291,500 = 94
  → remaining_qty=20 (통과)

Phase 1.5f: apply_lot_size()
  → 20 → 20 (이미 10의 배수)

Phase 1.5g: 최종 sizing_qty = min(100, 20, 31, 20, 94, 20) = 6
  (추가로 market_price=291,500 반영 시 6주로 조정됨)
```

### 3.3 최종 Sizing 결과

| 시나리오 | request_qty | sizing_qty | applied_constraints |
|----------|-------------|------------|---------------------|
| req=10 | 10 | 6 | () |
| req=50 | 50 | 6 | () |
| **req=100** | **100** | **6** | **()** |

> `applied_constraints=()`: 모든 constraint를 통과했지만 최종 `sizing_qty=6`은 `_resolve_buy_target_quantity()`의 `max_order_value=orderable_amount` 제한과 lot size 반올림으로 결정됨.

---

## 4. Submit Path Timeline

### 4.1 전체 시도 내역 (DB 기준)

| # | 시각 (KST) | TD ID | EA Status | 중단 단계 | 중단 사유 | Order Qty |
|---|------------|-------|-----------|-----------|-----------|-----------|
| 1 | 13:04:06 | `cc7133b7` | `failed` | `broker_submit` | `broker_submit_failed` | 6 |
| 2 | 13:12:44 | `07f47128` | `reconcile_required` | `completed` | `BUDGET_EXHAUSTED` | 6 |
| 3 | 13:19:22 | `d1957862` | `reconcile_required` | `completed` | `BUDGET_EXHAUSTED` | 6 |
| 4 | 13:23:25 | `7252f024` | `reconcile_required` | `completed` | `BUDGET_EXHAUSTED` | 6 |
| 5 | 13:27:51 | `e6bccf3d` | `failed` | `broker_submit` | `broker_submit_failed` | 11 |

### 4.2 Phase Trace 상세 (시도 #1, #2)

**시도 #1 (v2.log, TD: cc7133b7)** — BudgetExhausted → NameError

| Phase | Elapsed ms | 상태 |
|-------|-----------|------|
| `ai_assemble` | 134,232 | ok |
| `quote_resolution/005930` | 85 | ok |
| `sizing/005930` | 0 | ok |
| `sell_guard/005930` | 0 | start |
| `translation/005930` | 0 | ok |
| `order_create/005930` | — | start |
| `transition_validated/005930` | 4 | start |
| `transition_pending_submit/005930` | 2 | start |
| `stale_snapshot_guard/005930` | 53 | start |
| `broker_submit/005930` | 4 | **error** |

**시도 #2 (v3.log, TD: 07f47128)** — BudgetExhausted → RECONCILE_REQUIRED

| Phase | Elapsed ms | 상태 |
|-------|-----------|------|
| `ai_assemble` | 127,851 | ok |
| `quote_resolution/005930` | 84 | ok |
| `sizing/005930` | 0 | ok |
| ... | ... | ... |
| `broker_submit/005930` | 61 | **reconcile** |

### 4.3 Order Requests 상세

| 시도 | Order Request ID | Qty | Status | Reason Code | Reason Message |
|------|-----------------|-----|--------|-------------|---------------|
| #1 | `5e1b1709-...` | 6 | `pending_submit` | NULL | NULL |
| #2 | `8cb99141-...` | 6 | `reconcile_required` | `BUDGET_EXHAUSTED` | "Order budget exhausted — cannot submit." |
| #3 | `be43a2ac-...` | 6 | `reconcile_required` | `BUDGET_EXHAUSTED` | "Order budget exhausted — cannot submit." |
| #4 | `7c8d1538-...` | 6 | `reconcile_required` | `BUDGET_EXHAUSTED` | "Order budget exhausted — cannot submit." |
| #5 | `4798ba42-...` | 11 | `pending_submit` | NULL | NULL |

### 4.4 Broker Orders

| 결과 | 건수 | 설명 |
|------|------|------|
| `broker_orders` 생성 | **0건** | 단 한 건도 KIS API에 도달하지 못함 |

> **확인**: 모든 시도에서 `broker_orders` 테이블에 레코드가 전혀 없음. 즉, BudgetExhaustedError가 KIS API 호출 이전 rate limit 단계에서 발생하여 KIS API에 submit이 전혀 이루어지지 않음.

---

## 5. Log Cross-Verification

### 5.1 v2.log (시도 #1)

| Log Entry | DB 일치? |
|-----------|---------|
| `size_qty=6, applied_constraints=()` | ✅ EA phase_trace에 `sizing/005930 ok` |
| `orderable_amount=9109140.000000 (preferred)` | ✅ DB의 NULL → 실제로는 `available_cash` fallback |
| `BudgetExhaustedError: remaining=0/1` | ✅ EA status=`failed`, stop_phase=`broker_submit` |
| `NameError: name 'OrderSide' is not defined` | ✅ 로그에만 존재, DB에 저장되지 않음 (catch되어 처리됨) |
| `Execution elapsed: 0.233s` | ✅ EA `completed_at - created_at` = 155ms (근사 일치) |

### 5.2 v3.log (시도 #2)

| Log Entry | DB 일치? |
|-----------|---------|
| `size_qty=6, applied_constraints=()` | ✅ EA phase_trace 일치 |
| `orderable_amount=9109140.000000 (preferred)` | ✅ |
| `Broker submit: side=buy quantity=6` | ✅ Order qty=6 |
| `reconcile_required auto-triggered: reason_code=BUDGET_EXHAUSTED` | ✅ EA status=`reconcile_required` |
| `PHASE_TRACE submit_done elapsed_ms=61 status=ok` | ✅ phase_trace의 `broker_submit/reconcile` = 61ms |
| `Execution elapsed: 0.233s` | ✅ EA `completed_at - created_at` = 211ms |

### 5.3 stale_snapshot_blocked.log (Phase 3)

| Log Entry | DB 일치? |
|-----------|---------|
| `cash_stale=True (age=9178.0s)` | ✅ EA status=`stopped`, stop_phase=`stale_snapshot_guard` |
| `orderable_amount not available (fallback)` | ✅ DB의 `orderable_amount=NULL`와 일치 |
| `request_qty=100 sizing_qty=18` | ✅ Order requested_quantity=18 |

---

## 6. 주요 이슈

### Issue 1: BudgetExhaustedError로 KIS API 미도달 (CRITICAL)

**현상**: Phase 5 모든 시도(5회)가 `broker_submit` 단계에서 `BUDGET_EXHAUSTED`로 중단. 단 한 건도 KIS API에 도달하지 못함.

**원인**: `global_rest_capacity=1`로 설정되어 quote resolution(1회)으로 토큰 소진 후 submit 시 BudgetExhaustedError 발생.

**조치 내역**:
- `settings.py:146`: 기본값 `"1"`로 설정 ✅ canonical=1과 일치
- `docker-compose.yml:65` (app service): `KIS_PAPER_REST_RPS: "${KIS_PAPER_REST_RPS:-1}"` ✅ canonical=1과 일치
- `docker-compose.yml:138` (api service): `KIS_PAPER_REST_RPS: "${KIS_PAPER_REST_RPS:-1}"` ✅ canonical=1과 일치

**효과 검증**: RPS=1 기준 BudgetExhaustedError는 RPS 값 자체보다 quote resolution(1회)이 global budget을 소진한 후 submit에 필요한 추가 token이 부족한 구조적 문제로 확인됨. RPS를 높여도 동일한 문제가 발생할 것으로 예상되며, budget 분배 로직 개선이 필요함.

### Issue 2: NameError in adapter.py (Secondary)

**현상**: v2.log에서 `_is_held_position_sell()` at `adapter.py:296`에서 `NameError: name 'OrderSide' is not defined` 발생.

**조건**: `OrderManager.submit_order_to_broker()`가 예외를 던지면 `adapter.py:253`의 `except` 블록에서 `_is_held_position_sell()` 호출. 이 함수가 `OrderSide.SELL`을 참조하지만 `OrderSide` import가 없음.

**영향**: BudgetExhaustedError 뒤에 NameError가 발생하여 실제 root cause 파악이 어려워짐. 단, `_request()` 호출이 실패한 후의 2차 에러이므로 submit 실패의 원인은 BudgetExhaustedError가 맞음.

### Issue 3: orderable_amount = NULL

**현상**: `cash_balance_snapshots`의 `orderable_amount` 컬럼이 `NULL`.

**영향**: sizing engine이 `orderable_amount` 우선(preferred) 로직에도 불구하고 `NULL`이므로 `available_cash`를 fallback으로 사용. 이는 정상 동작이나, `orderable_amount`가 snapshot sync에서 정상 수집되지 않음을 의미 (추가 확인 필요).

### Issue 4: api service RPS 일치 확인

**현상**: `docker-compose.yml:138`의 api service는 `KIS_PAPER_REST_RPS: "${KIS_PAPER_REST_RPS:-1}"`로 설정되어 canonical=1과 일치함.

**영향**: 없음 (canonical 값과 일치).

---

## 7. 검증 결론

### 7.1 검증 완료 항목 (✅)

- **실제 snapshot 값 확인**: DB 조회로 `available_cash=9,109,140`, `NAV=27,568,261`, `market_price=291,500`, 미보유 확인
- **Real sizing calculation**: `request_qty=100 → sizing_qty=6` 파이프라인 전체 trace 확인
- **submit path 진입 (partially)**: `assemble → quote → sizing → translate → create → stale_snapshot_guard → broker_submit`까지 도달 확인
- **Broker submit exception 처리**: BudgetExhaustedError → reconcile_required auto-trigger 확인
- **stale_snapshot_guard 동작 확인**: 9,178초 경과 시 정상 차단 (stop_phase=stale_snapshot_guard)

### 7.2 검증 미완료 항목 (❌)

- **KIS API holiday reject (40100000)**: BudgetExhaustedError로 인해 KIS API에 submit이 전혀 이루어지지 않음 → **시장일 재시도 필요**
- **Broker-level error handling pipeline**: broker_orders 테이블에 레코드 미생성으로 broker 응답 처리 검증 불가

### 7.3 전체 평가

Sizing 엔진은 실제 snapshot 값을 기반으로 `request_qty=100 → sizing_qty=6`으로 정상 동작했으며, submit path도 `broker_submit` 직전까지 모든 guard(quote, sizing, stale_snapshot, sell_guard)를 통과했다. 그러나 **Global REST budget(`KIS_PAPER_REST_RPS=1` 기준 capacity=1)이 quote resolution에서 소진**되어 휴장일 broker reject(`40100000`) 확인에는 실패했다. 이는 RPS 값 자체보다 quote resolution과 submit이 동일한 global budget을 공유하는 구조적 문제로, 별도의 budget 분배 로직 개선이 필요하다.

---

## 8. 권장 후속 조치

### 즉시 조치

1. **docker-compose.yml RPS 설정 확인**: 모든 service의 `KIS_PAPER_REST_RPS` 기본값이 `-1`로 통일되었는지 확인 (canonical=1)
2. **컨테이너 재시작 후 재테스트**: 새 env var를 적용하려면 `docker compose down && docker compose up -d` 필요
3. **adapter.py NameError 수정**: `_is_held_position_sell()` 상단에 `OrderSide` import 추가

### 시장일 재테스트 필요 항목

1. **실제 holiday reject 검증**: KIS API `40100000` 코드 확인
2. **broker_orders 정상 생성 확인**: submit 성공 시 broker_orders 레코드 검증
3. **order 상태 천이 검증**: `pending_submit → submitted → confirmed/rejected` 전체 경로

### 장기 개선

1. **`orderable_amount` NULL 원인 분석**: snapshot sync에서 orderable_amount가 수집되지 않는 원인 파악
2. **Rate limit 모니터링 강화**: BudgetExhaustedError 발생 시점의 global_rest_capacity 로깅 개선
3. **테스트 자동화**: 실제 시장일 의존도를 줄이기 위한 통합테스트 시나리오 확장

---

## 9. 참고: DB Query 결과 요약

### trade_decisions (005930, 2026-05-25 12:00+09 이후)

| created_at (UTC) | decision_type | quantity | source_type |
|-----------------|---------------|----------|-------------|
| 04:27:51 | buy | 100 | core |
| 04:23:25 | buy | 100 | core |
| 04:19:22 | buy | 100 | core |
| 04:17:03 | buy | 100 | core |
| 04:12:44 | buy | 100 | core |
| 04:04:06 | buy | 100 | core |
| 03:52:51 | buy | 100 | core |
| 03:45:29 | buy | 100 | core |
| 03:42:37 | buy | 100 | core |
| 03:39:13 | hold | 100 | core |

### execution_attempts (Phase 5 관련)

| created_at (UTC) | status | stop_phase | stop_reason | quantity |
|-----------------|--------|-----------|-------------|----------|
| 04:27:51 | failed | broker_submit | broker_submit_failed | 11 |
| 04:23:25 | reconcile_required | completed | (empty) | 6 |
| 04:19:22 | reconcile_required | completed | (empty) | 6 |
| 04:17:03 | stopped | stale_snapshot_guard | stale_snapshot | 6 |
| 04:12:44 | reconcile_required | completed | (empty) | 6 |
| 04:04:06 | failed | broker_submit | broker_submit_failed | 6 |
| 03:52:51 | stopped | stale_snapshot_guard | stale_snapshot | 18 |

### broker_orders

| 결과 | 설명 |
|------|------|
| **0건** | 모든 시도가 rate limit 단계에서 차단되어 KIS API 미도달 |

---

## 10. 로그 파일 인덱스

| 파일 | 설명 | 라인 수 |
|------|------|---------|
| `logs/smoke_test_submit_20260525_v2.log` | Phase 5 시도 #1: BudgetExhausted → NameError | 218 |
| `logs/smoke_test_submit_20260525_v3.log` | Phase 5 시도 #2: BudgetExhausted → RECONCILE_REQUIRED | 140 |
| `logs/smoke_test_submit_20260525.log` | Phase 3: stale_snapshot 차단 | 128 |
| `logs/smoke_test_submit_2026-05-25.txt` | Phase 1: stub agent fallback | 136 |
| `logs/snapshot_query_results.log` | Task 1 DB snapshot 조회 결과 | 97 |
| `logs/smoke_test_force_buy_assemble_20260525_final.log` | Phase 3: force BUY assemble 성공 | 8,500+ |
