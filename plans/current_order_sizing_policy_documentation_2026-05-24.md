# 현재 주문 사이징 정책 문서 (Order Sizing Policy)

> **목적**: 코드와 테스트에만 묻혀 있는 주문 사이징 정책을 명확히 문서화
> **범위**: `SizingEngine.calculate_sizing()` 및 `ExecutionService.run_execution_pipeline()` 내 Phase 1.5
> **기준일**: 2026-05-24
> **코드 변경 수반하지 않음** — 정책 문서화 전용

---

## 1. Canonical Sizing Policy 개요

| 항목 | 내용 |
|------|---------|
| **설계 원칙** | Pure function (I/O 없음), 모든 입력 Optional + graceful fallback, 적용된 제약 조건 추적 |
| **구현 위치** | `sizing_engine.py` — 모듈 수준 순수 함수 `calculate_sizing()` |
| **입력 구성** | `execution_service.py:372-485` — `DecisionOrchestratorService.build_sizing_inputs()`가 `OrderIntent`에서 `SizingInputs` 조립 |
| **파이프라인 위치** | Phase 1.5 — `assemble()` 완료 후, `create_order()` 전 |

### 1.1 처리 단계 (9단계)

`calculate_sizing()` (`sizing_engine.py:504-608`):

```
1. Decision type dispatch  →  _resolve_base_quantity()
2. Position-aware base qty →  _resolve_base_quantity() 내부 dispatch
3. Max order value         →  _apply_max_order_value()
4. Max/min order qty       →  _apply_qty_bounds()
5. Cash availability       →  _apply_cash_constraint()   [BUY only]
6. Position concentration  →  _apply_concentration_constraint()
7. Lot size rounding       →  _apply_lot_size()
8. Zero-quantity guard     →  skip_reason 설정
9. Max order value 계산    →  SizingResult.max_order_value
```

### 1.2 주요 Dataclass

#### SizingInputs (`sizing_engine.py:43-118`)

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `decision_type` | `str` | (필수) | `BUY`, `SELL`, `EXIT`, `REDUCE`, `APPROVE` |
| `side` | `OrderSide` | (필수) | `OrderSide.BUY` / `OrderSide.SELL` |
| `requested_quantity` | `Decimal` | (필수) | AI/호출자가 요청한 원본 수량 |
| `requested_price` | `Decimal\|None` | `None` | LIMIT 주문 가격 |
| `reference_price` | `Decimal\|None` | `None` | MARKET 주문용 참조 가격 (broker quote) |
| `sizing_hint` | `SizingHint` | `SizingHint()` | AI advisory sizing hint (FDC output) |
| `current_position_qty` | `Decimal\|None` | `None` | 현재 포지션 수량 |
| `current_position_avg_price` | `Decimal\|None` | `None` | 포지션 평균 진입가 |
| `available_cash` | `Decimal\|None` | `None` | 가용 현금 (`dnca_tot_amt`) |
| `orderable_amount` | `Decimal\|None` | `None` | 주문가능금액 (`ord_psbl_amt`) |
| `nav` | `Decimal\|None` | `None` | 순자산가치 |
| `max_single_position_pct` | `Decimal\|None` | `None` | 단일 포지션 최대 % |
| `min_cash_buffer_pct` | `Decimal\|None` | `None` | 최소 현금 버퍼 % |
| `max_order_value` | `Decimal\|None` | `None` | 최대 주문 금액 |
| `min_order_qty` | `Decimal\|None` | `None` | 최소 주문 수량 |
| `max_order_qty` | `Decimal\|None` | `None` | 최대 주문 수량 |
| `lot_size` | `Decimal\|None` | `None` | 호가 단위 (rounding) |

#### SizingResult (`sizing_engine.py:125-149`)

| 필드 | 타입 | 설명 |
|------|------|------|
| `quantity` | `Decimal` | 최종 계산 수량 (≥ 0). `0` = 거절 |
| `max_order_value` | `Decimal\|None` | `price × quantity` (price 없으면 `None`) |
| `applied_constraints` | `tuple[str,…]` | 적용된 제약 레이블 (예: `"cash_limit"`, `"position_concentration"`) |
| `skip_reason` | `str\|None` | `quantity == 0`일 때 거절 사유 |

#### SizingHint (FDC Output, `schemas.py:491-509`)

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `size_mode` | `str` | `"no_change"` | `"fractional_reduce"`, `"no_change"`, `"increase"` |
| `size_adjustment_factor` | `float` | `0.0` | 조정 비율 (0.5 = 반으로 감소) |

---

## 2. Decision Type별 Sizing Semantics

### 2.1 BUY / APPROVE+BUY

| 속성 | 값 |
|------|-----|
| **Base quantity 결정** | `_resolve_buy_target_quantity()` — allocation 20% 기반 |
| **Cash constraint** | **적용** (`orderable_amount` → `available_cash` 우선순위) |
| **Position concentration** | 적용 |
| **Max order value** | 적용 |
| **AI sizing hint** | **사실상 bypass** — allocation 로직이 base quantity를 결정한 후 hint가 개입할 여지 없음 |

**Allocation 20% 규칙** (`sizing_engine.py:158-236`):

```python
_ALLOCATION_PCT = Decimal("0.2")  # 20%
```

- `effective_price` = `requested_price` → `reference_price` → 없으면 allocation skip
- `effective_cash` = `orderable_amount` → `available_cash` → 없으면 allocation skip
- `target_notional = effective_cash * 20%`
- `target_qty = int(target_notional / effective_price)` (ROUND_DOWN)
- `target_qty`는 `requested_quantity`를 **초과할 수 없음** (cap only, never increase)
- 최소 1주 보장 (`target_qty < 1 → 1`)

**의도**: 단일 BUY 주문이 가용 현금의 20%를 초과하지 않도록 제한.

### 2.2 SELL / APPROVE+SELL

| 속성 | 값 |
|------|-----|
| **Base quantity 결정** | `_base_qty_exit()` — **전량 청산** |
| **Cash constraint** | **미적용** (현금이 필요 없는 SELL) |
| **Position concentration** | 적용 |
| **Max order value** | 적용 |
| **SELL fallback** | sizing 결과가 0이어도 `intent.request.quantity`로 fallback (`execution_service.py:597-607`) |

> **중요**: SELL은 항상 `_base_qty_exit()`으로 dispatch됨. 부분 매도는 `REDUCE`를 통해서만 가능.

### 2.3 EXIT

| 속성 | 값 |
|------|-----|
| **Base quantity 결정** | `_base_qty_exit()` |
| **Cash constraint** | 미적용 |
| **Position concentration** | 적용 |
| **Max order value** | 적용 |

```python
def _base_qty_exit(inputs: SizingInputs) -> Decimal:
    if _is_position_known(inputs.current_position_qty):
        return inputs.current_position_qty  # 전량 청산
    return inputs.requested_quantity        # fallback: 요청 수량
```

### 2.4 REDUCE

| 속성 | 값 |
|------|-----|
| **Base quantity 결정** | `_base_qty_reduce()` — **부분 축소** |
| **Cash constraint** | 미적용 |
| **Position concentration** | 적용 |
| **Max order value** | 적용 |

```python
def _base_qty_reduce(inputs: SizingInputs) -> Decimal:
    if _is_position_known(inputs.current_position_qty):
        if hint has fractional_reduce/reduce factor:
            base_qty = position - (position * factor)  # AI 제안 축소
        else:
            base_qty = requested_quantity               # 요청 수량 그대로
        return min(base_qty, current_position_qty)       # 포지션 초과 불가
    return inputs.requested_quantity                     # fallback
```

### 2.5 HOLD / WATCH

| 속성 | 값 |
|------|-----|
| **Base quantity 결정** | **0** (`non_actionable_decision`) |
| **Cash constraint** | N/A |
| **Position concentration** | N/A |
| **Max order value** | N/A |

### 2.6 Decision Type Dispatch Matrix

| `decision_type` | `side` | Base Quantity 함수 | Cash Constraint | 비고 |
|---|---|---|---|---|
| `BUY` | `BUY` | `_resolve_buy_target_quantity()` | 적용 | Allocation 20% |
| `APPROVE` | `BUY` | `_resolve_buy_target_quantity()` | 적용 | BUY와 동일 |
| `SELL` | `SELL` | `_base_qty_exit()` | 미적용 | 전량 청산 |
| `APPROVE` | `SELL` | `_base_qty_exit()` | 미적용 | SELL과 동일 |
| `EXIT` | any | `_base_qty_exit()` | 미적용 | 전량 청산 |
| `REDUCE` | any | `_base_qty_reduce()` | 미적용 | 부분 축소 |
| `HOLD` | any | **0** | N/A | Non-actionable |
| `WATCH` | any | **0** | N/A | Non-actionable |

---

## 3. BUY 수량 감소 규칙 (상세)

BUY 주문의 수량은 다음 6개 제약 조건에 따라 **순차적으로 감소**합니다.

### 3.1 Allocation 20% Cap (1차, BUY only)

**코드**: `_resolve_buy_target_quantity()` (`sizing_engine.py:158-236`)

- `effective_cash * 0.2 / effective_price`가 `requested_quantity`보다 작으면 cap
- `effective_cash` = `orderable_amount` → `available_cash` → None → skip
- `effective_price` = `requested_price` → `reference_price` → None → skip
- `applied_constraints` 레이블: `"allocation_limit"`

### 3.2 Cash Constraint (2차, BUY only)

**코드**: `_apply_cash_constraint()` (`sizing_engine.py:319-380`)

- `effective_cash / effective_price` (ROUND_DOWN)
- `orderable_amount ≤ 0` → **BUY 완전 차단** (`"orderable_amount_zero"`)
- `min_cash_buffer_pct`가 설정되면: `effective_cash * (1 - buffer_pct/100)`
- MARKET 주문: **safety factor 0.95** 적용 (슬리피지 버퍼)
- `applied_constraints` 레이블: `"cash_limit"` 또는 `"orderable_amount_zero"`

### 3.3 Position Concentration Constraint (3차, 모든 사이드)

**코드**: `_apply_concentration_constraint()` (`sizing_engine.py:383-445`)

```
max_position_value = nav * max_single_position_pct / 100
remaining_capacity = max_position_value - current_value
max_additional_qty = remaining_capacity / effective_price  (ROUND_DOWN)
```

- `nav`가 없으면 `cash_balance_snapshot.total_asset`으로 fallback
- `remaining_capacity ≤ 0` → **0 반환** (`"position_concentration"`)
- `applied_constraints` 레이블: `"position_concentration"`

### 3.4 Max Order Value (4차, 모든 사이드)

**코드**: `_apply_max_order_value()` (`sizing_engine.py:466-489`)

- `price × qty > max_order_value` → `qty = max_order_value / price` (ROUND_DOWN)
- `applied_constraints` 레이블: `"max_order_value"`
- `effective_price`가 없으면 skip

### 3.5 Max/Min Order Qty (5차, 모든 사이드)

**코드**: `_apply_qty_bounds()` (`sizing_engine.py:448-463`)

- `qty > max_order_qty` → `max_order_qty`로 cap (`"max_qty_cap"`)
- `qty < min_order_qty` → **0** (`"below_min_qty"`)

### 3.6 Lot Size Rounding (6차, 모든 사이드)

**코드**: `_apply_lot_size()` (`sizing_engine.py:424-441`)

- `lot_size`가 설정되면 가장 가까운 배수로 내림
- `applied_constraints` 레이블: `"lot_size_rounded"`

### 3.7 AI Sizing Hint

**코드**: `_apply_ai_size_hint()` (`sizing_engine.py:184-199`)

| `size_mode` | 동작 |
|---|---|
| `"increase"` | `base_qty * (1 + factor)` |
| `"fractional_reduce"` / `"reduce"` | `base_qty - (base_qty * factor)` |
| `"no_change"` | 그대로 |

**중요**: BUY 사이드에서는 `_resolve_buy_target_quantity()`가 allocation 로직으로 base quantity를 결정하므로, AI sizing hint는 **사실상 적용되지 않음** (bypass). AI hint는 SELL/REDUCE/EXIT 경로에서만 실제로 적용됨.

---

## 4. Cash Source 우선순위

**코드**: `_build_sizing_inputs()` (`execution_service.py:372-485`) 및 `_apply_cash_constraint()` (`sizing_engine.py:319-380`)

```
orderable_amount (KIS ord_psbl_amt)  ← broker의 실제 주문가능금액 (우선)
  └→ available_cash (KIS dnca_tot_amt)  ← paper API fallback
      └→ None → cash constraint skip
```

**`orderable_amount`가 0 또는 음수면** → BUY 차단 (`skip_reason="orderable_amount_zero"`)

**MARKET 주문 safety factor**: `effective_cash *= 0.95` (슬리피지 대비 5% 버퍼)

---

## 5. SELL Fallback

**코드**: `execution_service.py:597-607`

```
Phase 1.5:
  sizing_result = calculate_sizing(inputs)
  
  if side == SELL and sizing_result.quantity == 0:
      sizing_result = replace(sizing_result, quantity=request.quantity)
      # SELL이 sizing에 의해 0이 되는 것을 방지
```

**의도**: SELL(매도)는 현금이 필요 없으므로 cash constraint 등으로 0이 되어서는 안 됨. sizing이 `0`을 반환해도 원본 `request.quantity`로 fallback.

---

## 6. 정보 부족 시 Fallback 정책

### 6.1 `reference_price`가 없을 때

`reference_price`가 없으면 `effective_price = None`이 되어 **cash/concentration/max-order-value 제약이 모두 skip**됨. 이는 MARKET 주문에서 가격 정보가 없을 때 과도한 제약을 피하기 위한 설계.

| 제약 | `reference_price` 없음 |
|------|----------------------|
| Allocation 20% | **Skip** — `requested_quantity` 그대로 반환 |
| Cash constraint | **Skip** |
| Concentration | **Skip** |
| Max order value | **Skip** |
| Lot size | **적용** |
| Max/min order qty | **적용** |

### 6.2 `available_cash`/`orderable_amount`가 None일 때

- `orderable_amount = None` → `available_cash`로 fallback
- `available_cash = None` → cash constraint skip
- BUY allocation도 동일한 fallback → 정보 없으면 allocation skip

### 6.3 포지션 정보가 없을 때

| `decision_type` | 동작 |
|---|---|
| `EXIT` | `requested_quantity` fallback |
| `REDUCE` | `requested_quantity` fallback |
| `SELL` | `requested_quantity` fallback (exit으로 dispatch) |
| `BUY` | allocation 기반 (포지션 무관) |

### 6.4 NAV가 없을 때

**코드**: `execution_service.py:405-412`

1. `risk_limit_snapshot.nav` (1순위)
2. `cash_balance_snapshot.total_asset` (2순위, fallback)
3. 둘 다 없으면 → concentration constraint skip

---

## 7. Config 설정과 우선순위

**코드**: `execution_service.py:418-480`

| Config Key | Nested 경로 | Legacy Flat Key (fallback) |
|---|---|---|
| `max_single_position_pct` | `risk.max_single_position_pct` | `max_position_size` |
| `min_cash_buffer_pct` | `risk.min_cash_buffer_pct` | `min_cash_buffer_pct` |
| `max_order_value` | `execution.max_order_value` | `max_order_value` |
| `min_order_qty` | `execution.min_order_qty` | — |
| `max_order_qty` | `execution.max_order_qty` | — |

**Config Key Resolution 로직**: nested key가 없으면 legacy flat key로 fallback.

---

## 8. 테스트가 고정하는 정책

### 8.1 `test_sizing_engine.py` (30개 테스트)

| 테스트 클래스 | 고정하는 정책 |
|---|---|
| `TestNewEntry` | BUY/APPROVE pass-through: 제약 없으면 `requested_quantity` 유지 |
| `TestCashConstraint` | BUY cash cap: `orderable_amount` 우선, `≤ 0` → 차단 |
| `TestReduce` | REDUCE position-aware: 포지션 있으면 cap, 없으면 fallback |
| `TestExit` | EXIT 전량: 포지션 있으면 position qty, 없으면 fallback |
| `TestMaxOrderQty` | `max_order_qty` cap |
| `TestMinOrderQty` | `min_order_qty` 이하 → skip |
| `TestConcentration` | concentration cap with `max_single_position_pct` |
| `TestLotSize` | `lot_size` 내림 rounding |
| `TestAiSizingHintIncrease` | AI hint `increase`: BUY는 allocation이 우선 → bypass |
| `TestAiSizingHintReduce` | AI hint `fractional_reduce`: BUY는 allocation bypass |
| `TestAllNoneFallback` | 모든 None 입력 → pass-through (skip_reason 없음) |
| `TestApproveSell` | APPROVE+SELL → exit 처리 |
| `TestNonActionable` | HOLD/WATCH → 0 + `non_actionable_decision` |
| `TestMaxOrderValue` | `max_order_value` cap |
| `TestCashBuffer` | `min_cash_buffer_pct`가 effective cash 감소 |
| `TestMaxOrderValueResult` | `SizingResult.max_order_value` 계산 |
| `TestCombinedConstraints` | 다중 제약 순차 적용 및 `applied_constraints` 누적 |
| `TestOrchestratorSizingPath` | orchestrator 경로 시뮬레이션 (build_sizing_inputs → calculate_sizing) |
| `TestNavFallbackFromCashBalance` | NAV fallback: `total_asset` 사용 |
| `TestMarketBuyReferencePriceCashConstraint` | MARKET BUY + `reference_price` cash constraint |
| `TestLimitBuyIgnoresReferencePrice` | LIMIT BUY는 `requested_price` 우선 |
| `TestMarketSellNoCashConstraint` | SELL MARKET은 cash constraint 미적용 |
| `TestSafetyFactorMarketOnly` | Safety factor 0.95는 MARKET에만 적용 |
| `TestMarketBuyConcentrationWithReferencePrice` | MARKET BUY concentration |
| `TestMarketBuyMaxOrderValueWithReferencePrice` | MARKET BUY max order value |
| `TestMaxOrderValueWithReferencePrice` | `SizingResult.max_order_value` with `reference_price` |
| `TestMarketBuyCashBufferAndSafetyFactor` | `min_cash_buffer_pct` + safety factor compounding |
| `TestBuyBaselineWithAllocationPct` | BUY allocation 20% baseline: 고가/저가주, 최소 1주, zero cash 차단 |

### 8.2 `test_decision_submit_pipeline.py` — sizing 통합 검증

| 테스트 | 고정하는 정책 |
|---|---|
| `test_sizing_applied_to_submitted_order` | sizing 결과가 실제 제출 주문에 반영됨 → `result.submit_response.requested_quantity`가 cap된 값 |
| `test_sizing_zero_quantity_skips` | sizing 0 → SKIPPED, `error_phase="sizing"`, broker 미호출 |

### 8.3 `test_decision_replay.py` — 결정론적 검증

| 테스트 | 고정하는 정책 |
|---|---|
| `test_replay_sizing_identity` | 동일 `SizingInputs` → 동일 `SizingResult` (결정론적) |
| `test_replay_sizing_cash_constraint` | cash constraint 적용 시에도 결정론적 |
| `test_replay_sizing_zero_quantity` | zero quantity 결과도 결정론적 |
| `test_replay_assemble_with_sizing` | orchestrator 경로 → 동일 `SizingInputs`로 2회 `calculate_sizing()` → 동일 결과 |
| `REPLAY_SCENARIOS` parametrized | 각 시나리오별 `expected_quantity` (sizing 결과 포함) |
| `REPLAY_SCENARIOS` 2회차 | fresh repos로 2회 실행 → 동일 status |

---

## 9. 파이프라인 통합 흐름 (ExecutionService Phase 1.5)

**코드**: `execution_service.py:541-671`

```
Phase 1.5 시작
  │
  ├─ 1) reference_price resolve
  │     └─ MARKET 주문만 broker quote 조회
  │     └─ HP_SELL (REDUCE/EXIT SELL) → quote bypass, smoke price fallback
  │
  ├─ 2) _build_sizing_inputs(intent, reference_price)
  │     └─ OrderIntent + quote → SizingInputs
  │
  ├─ 3) calculate_sizing(sizing_inputs)
  │     └─ 9단계 순차 적용
  │
  ├─ 4) SELL fallback
  │     └─ sizing_result=0 && side==SELL → request.quantity fallback
  │
  ├─ 5) effective_qty ≤ 0 → SKIPPED 반환
  │     └─ error_phase="sizing"
  │     └─ SubmitResult(is_skipped=True, error_message=skip_reason)
  │
  └─ 6) quantity != original → intent.request 수량 override
        └─ SubmitResult(sizing_result=..., is_submitted=True)
```

---

## 10. 향후 재검토 포인트

| # | 이슈 | 설명 | 우선순위 |
|---|------|------|----------|
| 1 | **BUY에서 AI sizing hint가 사실상 무시됨** | `_resolve_buy_target_quantity()`가 allocation 기반으로 base qty를 결정한 후 AI hint가 적용될 기회가 없음. 의도된 동작인지 확인 필요 | 중간 |
| 2 | **`reference_price` 없을 때 제약 모두 skip** | MARKET 주문에서 `reference_price`가 없으면 cash/concentration/max-order-value 제약이 모두 skip되어 `requested_quantity`가 그대로 통과됨. 과도하게 관대할 수 있음 | 낮음 |
| 3 | **SELL fallback이 다른 제약을 우회하는지** | sizing 0 → `request.quantity` fallback이 concentration/max-order-value 등 다른 제약을 우회하는 것은 아닌지 확인 필요 | 낮음 |
| 4 | **`_is_new_entry()` vs `_resolve_base_quantity()` 중복** | `_is_new_entry()`는 `calculate_sizing()` 내에서 직접 사용되지 않음. `_resolve_base_quantity()`가 모든 dispatch를 처리 | 낮음 |
| 5 | **`SELL`이 항상 `_base_qty_exit()`으로 dispatch** | 부분 매도가 필요하면 `REDUCE`를 사용해야 함. 이 규칙이 AI 프롬프트에 명확히 문서화되어 있는지 확인 필요 | 중간 |
| 6 | **Allocation 20%가 `requested_quantity` 초과 불가** | Cap-only 설계는 보수적이지만, AI가 의도적으로 많은 수량을 요청했을 때 무시될 수 있음. 의도 확인 필요 | 낮음 |
| 7 | **Safety factor 0.95의 보수성** | MARKET 주문에서 5% 추가 버퍼가 적절한지. 변동성 큰 종목에서는 부족할 수 있음 | 낮음 |

---

## 부록 A: 참조 파일 목록

| 파일 | 설명 |
|------|------|
| `src/agent_trading/services/sizing_engine.py` | 핵심 사이징 로직 — `calculate_sizing()` 순수 함수 |
| `src/agent_trading/services/execution_service.py` | Phase 1.5 통합 — `_build_sizing_inputs()`, SELL fallback |
| `src/agent_trading/services/ai_agents/schemas.py` | `SizingHint` dataclass (FDC output) |
| `tests/services/test_sizing_engine.py` | 사이징 단위 테스트 (30개) |
| `tests/services/test_decision_submit_pipeline.py` | 파이프라인 통합 테스트 (sizing 반영 검증) |
| `tests/services/test_decision_replay.py` | 결정론적 replay 검증 (sizing 포함) |

## 부록 B: Constraint Label 목록

`SizingResult.applied_constraints`에 포함될 수 있는 레이블:

| 레이블 | 설명 | 적용 조건 |
|--------|------|-----------|
| `"allocation_limit"` | BUY allocation 20% cap | BUY, cash/price known |
| `"cash_limit"` | 현금 부족으로 cap | BUY only |
| `"orderable_amount_zero"` | `orderable_amount ≤ 0` | BUY only → skip |
| `"position_concentration"` | 단일 포지션 % 초과 | 모든 사이드 |
| `"max_order_value"` | 최대 주문 금액 초과 | 모든 사이드 |
| `"max_qty_cap"` | `max_order_qty` 초과 | 모든 사이드 |
| `"below_min_qty"` | `min_order_qty` 미만 → skip | 모든 사이드 |
| `"lot_size_rounded"` | 호가 단위 rounding | 모든 사이드 |
| `"non_actionable_decision"` | HOLD/WATCH | HOLD/WATCH → skip |
| `"zero_after_constraints"` | 모든 제약 적용 후 0 | 모든 사이드 → skip |
| `"ai_hint_increase"` | AI hint increase 적용 | SELL/REDUCE/EXIT |
| `"ai_hint_reduce"` | AI hint reduce 적용 | SELL/REDUCE/EXIT |
