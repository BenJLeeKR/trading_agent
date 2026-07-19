# 분석 보고서: 10주 상한 근본 원인 및 동적 BUY 수량 설계

**작성일**: 2026-05-21  
**대상**: User Request 13c — Task A  
**분석자**: Roo (Architect)

---

## 1. 데이터 흐름 개요

```
run_paper_decision_loop.py:738          quantity=Decimal("10")   ← 하드코딩
run_orchestrator_once.py:359            quantity=Decimal("10")   ← 하드코딩
       │
       ▼
SubmitOrderRequest.quantity = Decimal("10")
       │
       ▼
decision_orchestrator.py assemble_and_submit()
  → assemble() → OrderIntent.request.quantity = Decimal("10")
  → _build_sizing_inputs() → SizingInputs(requested_quantity=req.quantity)
       │
       ▼
calculate_sizing(inputs)
  → _resolve_base_quantity(inputs)
    → side == BUY → _resolve_buy_target_quantity(inputs)
       │
       ▼
      _resolve_buy_target_quantity():
        target_qty = floor(orderable_amount * 0.2 / price)
        return min(target_qty, inputs.requested_quantity)  ← ★ CAP HERE ★
       │
       ▼
  → _apply_max_order_value()
  → _apply_qty_bounds()
  → _apply_cash_constraint()
  → _apply_concentration_constraint()
  → _apply_lot_size()
```

---

## Q1. BUY 수량이 아직 10주를 넘지 못하는 직접 원인은 무엇인가?

**정답: 3가지 원인이 중첩되어 있다.**

### 원인 ① — Entrypoint 하드코딩 (근본 원인)

| 파일 | 라인 | 코드 |
|------|------|------|
| [`run_paper_decision_loop.py`](../../scripts/run_paper_decision_loop.py:738) | 738 | `quantity=Decimal("10")` |
| [`run_orchestrator_once.py`](../../scripts/run_orchestrator_once.py:359) | 359 | `quantity=Decimal("10")` |

두 entrypoint 스크립트 모두 `SubmitOrderRequest.quantity`를 `Decimal("10")`으로 하드코딩하고 있다. 이 값이 `SizingInputs.requested_quantity`로 그대로 전달된다.

### 원인 ② — `_resolve_buy_target_quantity()`의 `min()` cap (직접 차단)

[`sizing_engine.py:227`](../../src/agent_trading/services/sizing_engine.py:227):
```python
return min(Decimal(str(target_qty)), inputs.requested_quantity)
```

`target_qty`가 아무리 커도 `requested_quantity`(즉 10)로 cap된다. 이것이 **가장 직접적인 차단 지점**이다.

### 원인 ③ — `_resolve_base_quantity()`의 BUY 분기

[`sizing_engine.py:287-288`](../../src/agent_trading/services/sizing_engine.py:287):
```python
if side == OrderSide.BUY:
    return _resolve_buy_target_quantity(inputs)
```

BUY 분기는 `_resolve_buy_target_quantity()`를 호출하고, 그 결과가 `min()`에 의해 10으로 cap된다.

### 판정

**직접 원인은 `_resolve_buy_target_quantity()`의 `return min(target_qty, requested_quantity)` (라인 227)이다.**  
하지만 이 cap이 존재하는 이유는 `requested_quantity=10`이라는 entrypoint의 하드코딩 때문이다.  
즉, **원인 ①(entrypoint 하드코딩)이 근본 원인이고, 원인 ②(min cap)가 직접 차단 지점**이다.

---

## Q2. 가장 적절한 수정 위치는 어디인가?

### 옵션 분석

| 옵션 | 수정 내용 | 장점 | 단점 |
|------|----------|------|------|
| **A** | `_resolve_buy_target_quantity()`에서 `requested_quantity` cap 제거 | 최소 변경, sizing engine만 수정 | entrypoint 하드코딩은 남음 |
| **B** | `_resolve_base_quantity()` BUY 분기 로직 변경 | 구조적 개선 | 영향도 큼 |
| **C** | A + B 동시 수정 | 완전한 해결 | 과잉 수정 |
| **D** | entrypoint의 `quantity=Decimal("10")` 자체 변경 | 근본 원인 해결 | entrypoint마다 수정 필요 |

### 권장: **옵션 A (최소 변경)**

**이유:**

1. `_resolve_buy_target_quantity()`는 이미 `orderable_amount * 20% / price`로 동적 수량을 계산하고 있다. 이 값이 **진정한 base quantity** 역할을 해야 한다.
2. `requested_quantity`는 entrypoint에서 하드코딩된 10에 불과하며, 아무런 의미 있는 정보를 담고 있지 않다.
3. `requested_quantity`를 **fallback 용도**로만 사용하면 entrypoint 하드코딩은 무해해진다.
4. risk constraint 체인(`_apply_cash_constraint`, `_apply_concentration_constraint`, `_apply_max_order_value`)이 실제 상한 역할을 하므로, `min()` cap은 중복된 제약이다.

**옵션 A의 구체적인 변경:**

```python
# 변경 전 (라인 227)
return min(Decimal(str(target_qty)), inputs.requested_quantity)

# 변경 후
return Decimal(str(target_qty))
```

---

## Q3. BUY 시작 수량은 어떤 값으로 잡는 것이 가장 안전한가?

### 현재 계산식

```python
target_notional = effective_cash * 0.2    # 9,000,000 * 0.2 = 1,800,000
target_qty = int(target_notional / effective_price)
```

### 안전성 평가

| 요소 | 설명 | 안전성 |
|------|------|--------|
| `_ALLOCATION_PCT = 0.2` | 현금의 20%만 단일 BUY에 사용 | ✅ 적절 |
| `orderable_amount` 우선 사용 | KIS API의 실제 주문가능금액 | ✅ 정확 |
| `available_cash` fallback | dnca_tot_amt fallback | ✅ 안전 |
| `min_cash_buffer_pct` | cash constraint에서 추가 버퍼 | ✅ 이중 안전 |

### 권장: `target_qty` 자체를 base로 사용

`target_qty = floor(orderable_amount * 0.2 / price)`를 그대로 base quantity로 사용하는 것이 안전하다. 그 이유는:

1. **20% allocation**은 이미 보수적인 값이다.
2. 이후 `_apply_cash_constraint()`가 cash 기반으로 다시 cap한다.
3. `_apply_concentration_constraint()`가 포트폴리오 비중으로 다시 cap한다.
4. `_apply_max_order_value()`가 최대 주문금액으로 다시 cap한다.
5. `_apply_qty_bounds()`가 `max_order_qty`로 다시 cap한다.

즉, **risk constraint 체인이 4중 안전장치** 역할을 하므로, `target_qty` 자체를 base로 사용해도 과매수 위험이 없다.

### `requested_quantity` fallback 유지

`effective_price`나 `effective_cash`를 구할 수 없는 경우에만 `requested_quantity`를 fallback으로 사용하는 현재 로직은 유지해야 한다:

```python
if effective_price is None or effective_price <= 0:
    return inputs.requested_quantity  # fallback
if effective_cash is None or effective_cash <= 0:
    return inputs.requested_quantity  # fallback
```

---

## Q4. max_order_qty / max_order_value / concentration limit과 어떻게 조합해야 안전한가?

### Constraint 체인 적용 순서 (`calculate_sizing()`)

```
Step 3: _apply_max_order_value()     → price * qty ≤ max_order_value
Step 4: _apply_qty_bounds()          → min_order_qty ≤ qty ≤ max_order_qty
Step 5: _apply_cash_constraint()     → price * qty ≤ cash * (1 - buffer)
Step 6: _apply_concentration_constraint() → total_position ≤ NAV * max_pct
Step 7: _apply_lot_size()            → round down to lot_size
```

### 각 constraint의 역할

| Constraint | 입력값 | 역할 | BUY 상한 가능? |
|-----------|--------|------|---------------|
| `_apply_max_order_value` | `max_order_value` (config) | 주문금액 절대 상한 | ✅ 가능 (설정 시) |
| `_apply_qty_bounds` | `max_order_qty` (config) | 수량 절대 상한 | ✅ 가능 (설정 시) |
| `_apply_cash_constraint` | `orderable_amount`, `min_cash_buffer_pct` | 현금 기반 cap | ✅ **항상 적용** |
| `_apply_concentration_constraint` | `nav`, `max_single_position_pct`, 현재 포지션 | 포트폴리오 비중 cap | ✅ **항상 적용** |

### 실제 상한 역할 분석

**`_apply_cash_constraint()`** 가 실제 BUY 상한의 핵심 역할을 한다:

```python
# orderable_amount = 9,000,000, min_cash_buffer_pct = 10% 가정
effective_cash = 9,000,000 * (1 - 0.1) = 8,100,000
max_qty_by_cash = 8,100,000 / effective_price
```

예를 들어 삼성전자 80,000원:
- `max_qty_by_cash = 8,100,000 / 80,000 = 101`주
- `target_qty = 1,800,000 / 80,000 = 22`주
- cash constraint는 101주를 허용하므로, `target_qty=22`가 그대로 통과

**`_apply_concentration_constraint()`** 가 두 번째 안전장치:

```python
# NAV=50,000,000, max_single_position_pct=20%, 현재 포지션=0
max_position_value = 50,000,000 * 0.2 = 10,000,000
remaining_capacity = 10,000,000 - 0 = 10,000,000
max_additional_qty = 10,000,000 / 80,000 = 125주
```

### 결론

**risk constraint 체인(cash → concentration → max_order_value → max_order_qty)이 실제 BUY 상한 역할을 충분히 수행할 수 있다.** `_resolve_buy_target_quantity()`의 `min()` cap은 이 체인과 중복되므로 제거해도 안전하다.

---

## Q5. 가장 작은 수정으로 완전 동적 BUY 수량을 만들려면 무엇을 바꿔야 하는가?

### 최소 변경: 1개 파일, 1개 라인

| 파일 | 라인 | 변경 전 | 변경 후 |
|------|------|---------|---------|
| [`sizing_engine.py`](../../src/agent_trading/services/sizing_engine.py:227) | 227 | `return min(Decimal(str(target_qty)), inputs.requested_quantity)` | `return Decimal(str(target_qty))` |

### 변경의 영향도

| 영향 항목 | 설명 |
|-----------|------|
| **BUY 수량** | 동적 계산된 `target_qty`가 그대로 사용됨. 저가주에서 수량 증가 |
| **SELL/REDUCE/EXIT** | 영향 없음 (`_resolve_buy_target_quantity()`는 BUY 전용) |
| **HOLD/WATCH** | 영향 없음 (`_SKIP_DECISION_TYPES`에서 0 반환) |
| **risk constraint** | 영향 없음 — cash/concentration/max_order_value는 그대로 적용 |
| **entrypoint 하드코딩** | `quantity=Decimal("10")`은 남지만, BUY 분기에서 무시됨 |
| **fallback 시나리오** | price/cash 정보 없으면 여전히 `requested_quantity` fallback 사용 |

### 추가 고려사항 (선택적)

1. **entrypoint 하드코딩 제거** (2개 파일, 2라인): `quantity=Decimal("10")` → 의미 있는 기본값으로 변경. 하지만 옵션 A만으로도 동적 수량이 가능하므로 필수는 아님.
2. **`_resolve_base_quantity()` BUY 분기 단순화**: `_resolve_buy_target_quantity()` 호출 대신 직접 계산. 구조적 개선이지만 기능적 변경은 아님.

---

## 시나리오 계산 (orderable_amount=9,000,000 기준)

### 계산식

```python
_ALLOCATION_PCT = 0.2
target_notional = 9,000,000 * 0.2 = 1,800,000
target_qty = int(1,800,000 / price)
```

### 결과 표

| 종목 | 가격 | target_qty 20% | 현재 capped | cap 제거 시 | cash constraint | concentration |
|------|------|----------------|-------------|------------|-----------------|---------------|
| SK하이닉스 | 200,000 | 9주 | 9주 | **9주** | 40주 ✅ | 50주 ✅ |
| 두산 | 150,000 | 12주 | 10주 | **12주** | 54주 ✅ | 66주 ✅ |
| 삼성전자 | 80,000 | 22주 | 10주 | **22주** | 101주 ✅ | 125주 ✅ |
| 저가주 A | 30,000 | 60주 | 10주 | **60주** | 270주 ✅ | 333주 ✅ |
| 초저가주 B | 5,000 | 360주 | 10주 | **360주** | 1,620주 ✅ | 2,000주 ✅ |

> **참고**: cash constraint 계산 시 `min_cash_buffer_pct=10%` 가정 → `effective_cash = 9,000,000 * 0.9 = 8,100,000`
> **참고**: concentration constraint 계산 시 `NAV=50,000,000`, `max_single_position_pct=20%`, 현재 포지션=0 가정
> ✅ = constraint가 `target_qty`보다 높아 추가 제한 없음

### 분석

1. **SK하이닉스 (200,000원)**: `target_qty=9`로 이미 10 이하. cap 제거 영향 없음.
2. **두산 (150,000원)**: `target_qty=12`로 10 → 12로 소폭 증가.
3. **삼성전자 (80,000원)**: `target_qty=22`로 10 → 22로 2.2배 증가.
4. **저가주 A (30,000원)**: `target_qty=60`로 10 → 60으로 6배 증가.
5. **초저가주 B (5,000원)**: `target_qty=360`로 10 → 360으로 36배 증가. **가장 큰 변화**.

### 위험 평가

- 모든 시나리오에서 `cash constraint`와 `concentration constraint`가 `target_qty`보다 훨씬 높은 상한을 제공하므로, **cap 제거 후에도 risk constraint에 의해 추가 제한되지 않음**.
- `target_qty` 자체가 `orderable_amount * 20%`로 계산되므로, 현금의 20%를 초과하는 주문은 발생하지 않음.
- **초저가주(5,000원)의 360주**는 `1,800,000원`어치로, 현금 9,000,000의 20% 이내이므로 안전.

---

## 요약

| 질문 | 답변 |
|------|------|
| **Q1. 직접 원인** | `_resolve_buy_target_quantity()`의 `return min(target_qty, requested_quantity)` (라인 227). 근본 원인은 entrypoint의 `quantity=Decimal("10")` 하드코딩. |
| **Q2. 가장 적절한 수정 위치** | **옵션 A**: `_resolve_buy_target_quantity()`에서 `requested_quantity` cap만 제거. 1개 파일, 1개 라인 수정. |
| **Q3. 안전한 BUY 시작 수량** | `target_qty = floor(orderable_amount * 0.2 / price)` 자체를 base로 사용. 20% allocation은 보수적이며, 이후 4중 risk constraint 체인이 안전장치 역할. |
| **Q4. constraint 조합** | cash constraint → concentration constraint → max_order_value → max_order_qty가 4중 안전장치. `min()` cap은 이들과 중복되므로 제거 안전. |
| **Q5. 최소 수정** | `sizing_engine.py:227` 1개 라인만 변경. entrypoint 하드코딩은 남아도 BUY 분기에서 무시됨. |

### 권장 액션 Plan

**Phase 1 (필수 — Code 모드)**:
1. [`sizing_engine.py:227`](../../src/agent_trading/services/sizing_engine.py:227) — `min()` cap 제거: `return Decimal(str(target_qty))`
2. 관련 unit test 업데이트 (`tests/services/test_sizing_engine.py`)

**Phase 2 (권장 — 선택적)**:
3. [`run_paper_decision_loop.py:738`](../../scripts/run_paper_decision_loop.py:738) — `quantity=Decimal("10")`을 `Decimal("1")`로 변경 (의미 없는 하드코딩 완화)
4. [`run_orchestrator_once.py:359`](../../scripts/run_orchestrator_once.py:359) — 동일 변경

**Phase 3 (선택 — 구조 개선)**:
5. `_resolve_base_quantity()` BUY 분기 리팩토링 — 로직 단순화

### 결정이 필요한 사항

1. Phase 1만 진행할지, Phase 2까지 포함할지?
2. Phase 1 구현 시 기존 test case에서 `min()` cap을 가정한 케이스가 있는지 확인 필요
