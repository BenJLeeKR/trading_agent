# 분석: MARKET 주문 10주 고정 문제 — Root Cause 및 수정 방안

> **작성일**: 2026-05-21  
> **분석 범위**: paper 주문 제출 경로 전체 (`run_paper_decision_loop.py` → `decision_orchestrator.py` → `sizing_engine.py`)  
> **핵심 문제**: `quantity=Decimal("10")` 하드코딩으로 인해 MARKET 주문에서 sizing engine의 cash constraint가 적용되지 않음

---

## 1. 전체 호출 흐름도

### 1.1 운영 경로 (near_real_ops_scheduler → run_paper_decision_loop)

```
run_near_real_ops_scheduler.py
  └─ _run_intraday_due_tasks()
       └─ _decision_command(dry_run=False)
            → python3 -m scripts.run_paper_decision_loop --count 1 --submit
              [line 645-659: _decision_command()]
```

**운영 스케줄러는 [`run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py)를 subprocess로 호출** (`run_orchestrator_once.py`는 사용하지 않음).

### 1.2 `run_paper_decision_loop.py` 내부 흐름

```
_run_one_cycle() [line 672]
  │
  ├─ 1. Seed FK chain
  ├─ 2. Pre-check snapshot health
  ├─ 2.5 _resolve_symbol_price() [line 107]
  │      → broker.get_quote(symbol, market).last (live quote)
  │      → KIS_SMOKE_PRICE env var fallback
  │      → Decimal("50000") default
  │      ※ 반환값은 로깅용으로만 사용됨 (price=None 정책)
  │
  ├─ 3. _resolve_order_type_and_price() [line 177]
  │      → 항상 (OrderType.MARKET, None) 반환 (전면 MARKET 정책)
  │
  ├─ 3. SubmitOrderRequest 생성 [line 729-741]
  │      quantity=Decimal("10")  ← ★ 하드코딩
  │      price=None              ← MARKET 주문
  │      order_type=OrderType.MARKET
  │
  ├─ [dry_run=True]
  │    orchestrator.assemble(request)
  │    orchestrator._build_sizing_inputs(intent)
  │    calculate_sizing(sizing_inputs)
  │    → 여기서 sizing이 돌지만, requested_price=None이므로
  │      cash constraint는 항상 skip됨 → quantity=10 유지
  │
  └─ [submit=True]
       orchestrator.assemble_and_submit(request, ...) [line 880]
         ├─ Phase 1: assemble() → OrderIntent
         ├─ Phase 1.5: sizing engine [line 965-1024]
         │    _build_sizing_inputs(intent) → SizingInputs
         │      requested_price = req.price = None (from SubmitOrderRequest)
         │    calculate_sizing(sizing_inputs)
         │      → cash constraint skip (price is None)
         │      → quantity=10 유지
         │
         ├─ Phase 1.5+: Duplicate Sell Guard (SELL only)
         ├─ Phase 2: build_submit_order_request_from_decision(intent)
         │    → intent.request.quantity 그대로 사용 (sizing 결과 반영)
         ├─ Phase 3: OrderManager.create_order()
         ├─ Phase 4a: DRAFT → VALIDATED
         ├─ Phase 4b: VALIDATED → PENDING_SUBMIT
         └─ Phase 5: submit_order_to_broker()
```

### 1.3 `run_orchestrator_once.py` (독립 실행, 운영 미사용)

```
run_orchestrator_once.py [line 350-361]
  SubmitOrderRequest(
    quantity=Decimal("10"),   ← 동일 하드코딩
    price=None,               ← MARKET
    order_type=OrderType.MARKET,
  )
  → orchestrator.assemble(request)
  → orchestrator._build_sizing_inputs(intent)
  → calculate_sizing(sizing_inputs)
  → 동일한 문제: cash constraint skip
```

---

## 2. Quantity 결정 지점별 현재 값과 출처

| 지점 | 파일:라인 | 현재 값 | 출처 |
|------|-----------|---------|------|
| `SubmitOrderRequest.quantity` | [`run_paper_decision_loop.py:738`](scripts/run_paper_decision_loop.py:738) | `Decimal("10")` | **하드코딩** |
| `SubmitOrderRequest.price` | [`run_paper_decision_loop.py:739`](scripts/run_paper_decision_loop.py:739) | `None` | `_resolve_order_type_and_price()` → MARKET 정책 |
| `SizingInputs.requested_price` | [`decision_orchestrator.py:1552`](src/agent_trading/services/decision_orchestrator.py:1552) | `req.price` (= `None`) | `SubmitOrderRequest.price`에서 전달 |
| `SizingInputs.requested_quantity` | [`decision_orchestrator.py:1551`](src/agent_trading/services/decision_orchestrator.py:1551) | `req.quantity` (= `10`) | `SubmitOrderRequest.quantity`에서 전달 |
| `calculate_sizing()` → cash constraint | [`sizing_engine.py:289`](src/agent_trading/services/sizing_engine.py:289) | **skip** (`price is None`) | `requested_price=None`이므로 조건 통과 |
| `calculate_sizing()` → concentration | [`sizing_engine.py:336-343`](src/agent_trading/services/sizing_engine.py:336) | **skip** (`price is None`) | 동일한 이유 |
| `calculate_sizing()` → max_order_value | [`sizing_engine.py:411`](src/agent_trading/services/sizing_engine.py:411) | **skip** (`price is None`) | 동일한 이유 |
| 최종 submit quantity | `assemble_and_submit()` Phase 1.5 이후 | `10` | sizing이 price=None으로 모든 constraint skip |

**결론**: `requested_price=None`으로 인해 sizing engine의 **모든 price-dependent constraint** (cash, concentration, max_order_value)가 skip되고, `_resolve_base_quantity()`가 `requested_quantity=10`을 그대로 반환하여 항상 10주가 유지된다.

---

## 3. Sizing Engine Cash Constraint Skip 조건 분석

### 3.1 `_apply_cash_constraint()` [`sizing_engine.py:270-319`](src/agent_trading/services/sizing_engine.py:270)

```python
def _apply_cash_constraint(qty, price, available_cash, min_cash_buffer_pct, constraints, orderable_amount=None):
    if price is None or price <= 0:   # ← line 289
        return qty                     # ← skip: 아무 제약도 적용하지 않음
```

- **조건**: `price is None or price <= 0` → cash constraint 전체 skip
- **영향**: `orderable_amount`(KIS `ord_psbl_amt`)나 `available_cash`(KIS `dnca_tot_amt`)가 있어도 전혀 사용되지 않음
- **의도**: MARKET 주문(`price=None`)에서는 예수금 대비 매수 가능 수량을 계산할 수 없으므로 cash constraint를 적용하지 않음
- **문제**: `_resolve_symbol_price()`로 quote를 조회하고 있지만, 이 값이 sizing engine까지 전달되지 않음

### 3.2 `_apply_concentration_constraint()` [`sizing_engine.py:322-356`](src/agent_trading/services/sizing_engine.py:322)

```python
if nav is None or nav <= 0 or max_single_position_pct is None or max_single_position_pct <= 0 or price is None or price <= 0:
    return qty   # ← 동일한 skip 조건
```

### 3.3 `_apply_max_order_value()` [`sizing_engine.py:400-418`](src/agent_trading/services/sizing_engine.py:400)

```python
if max_order_value is None or max_order_value <= 0 or price is None or price <= 0:
    return qty   # ← 동일한 skip 조건
```

### 3.4 영향 요약

| Constraint | Skip 조건 | MARKET 주문 영향 |
|-----------|-----------|-----------------|
| Cash (`_apply_cash_constraint`) | `price is None` | **SKIP** → 10주 그대로 |
| Concentration (`_apply_concentration_constraint`) | `price is None` | **SKIP** → 10주 그대로 |
| Max order value (`_apply_max_order_value`) | `price is None` | **SKIP** → 10주 그대로 |
| Max/Min qty (`_apply_qty_bounds`) | price 불필요 | **적용됨** (max_order_qty/min_order_qty) |
| Lot size (`_apply_lot_size`) | price 불필요 | **적용됨** |

---

## 4. Reference Price 도입 가능 지점

### 4.1 `Quote` 데이터 클래스 [`domain/models.py:58-66`](src/agent_trading/domain/models.py:58)

```python
@dataclass(slots=True, frozen=True)
class Quote:
    symbol: str
    market: str
    bid: Decimal | None    # 매수호가
    ask: Decimal | None    # 매도호가
    last: Decimal | None   # 체결가
    as_of: datetime
```

- `last`, `ask`, `bid` 모두 사용 가능
- `_resolve_symbol_price()`는 현재 `quote.last`만 사용 [`run_paper_decision_loop.py:126`](scripts/run_paper_decision_loop.py:126)

### 4.2 `_resolve_symbol_price()` [`run_paper_decision_loop.py:107-174`](scripts/run_paper_decision_loop.py:107)

```python
async def _resolve_symbol_price(symbol, market, broker):
    # Priority 1: broker.get_quote().last
    quote = await broker.get_quote(symbol, market)
    if quote.last is not None and quote.last > 0:
        return quote.last
    # Priority 2: KIS_SMOKE_PRICE env var
    # Priority 3: Decimal("50000") default
```

- 현재는 **로깅/observability 용도**로만 사용됨 (line 713-721 주석 참조)
- 반환값이 `SubmitOrderRequest.price`에 전달되지 않음 (`_resolve_order_type_and_price()`가 항상 `None` 반환)

### 4.3 Reference Price 전달 경로 (현재)

```
_resolve_symbol_price()  →  SubmitOrderRequest(price=None, ...)
                                    ↓
                           _build_sizing_inputs(intent)
                                    ↓
                           SizingInputs(requested_price=None)
                                    ↓
                           calculate_sizing() → cash constraint SKIP
```

**핵심**: `requested_price`는 `SubmitOrderRequest.price`에서 직접 가져오므로, MARKET 주문에서는 항상 `None`이다.  
**해결 방안**: `SizingInputs`에 `reference_price` 필드를 추가하거나, `_build_sizing_inputs()`에서 quote를 별도로 조회하여 전달.

---

## 5. BUY/SELL 분기별 현재 동작과 문제

### 5.1 BUY 분기

| 단계 | 현재 동작 | 문제 |
|------|----------|------|
| `_resolve_base_quantity()` | `requested_quantity=10` 반환 | 하드코딩된 10주 |
| `_apply_cash_constraint()` | `price=None` → skip | **cash constraint 미적용** |
| `_apply_concentration_constraint()` | `price=None` → skip | concentration 미적용 |
| `_apply_max_order_value()` | `price=None` → skip | max order value 미적용 |
| 최종 | **10주 유지** | 예수금 대비 과도한 주문 가능 |

**BUY 수량 계산 의도**: `orderable_amount / reference_price`로 최대 매수 가능 수량을 계산하고, 여기에 `min_cash_buffer_pct`를 적용해야 함.

### 5.2 SELL 분기

| 단계 | 현재 동작 | 문제 |
|------|----------|------|
| `_resolve_base_quantity()` | `_base_qty_exit()` → `current_position_qty` or `requested_quantity=10` | position이 없으면 10주 |
| `_apply_cash_constraint()` | BUY만 적용 → SELL은 skip | 정상 (SELL은 cash 불필요) |
| `assemble_and_submit()` Phase 1.5 | sizing=0이면 `intent.request.quantity`로 fallback [`decision_orchestrator.py:988-998`](src/agent_trading/services/decision_orchestrator.py:988) | SELL fallback 로직 존재 |
| Duplicate Sell Guard | `_sell_guard_resolver.resolve()` | 별도 guard 존재 |

**SELL 수량 계산 의도**: `current_position_qty`를 기준으로 REDUCE/EXIT 수량 결정. position이 없으면 `requested_quantity` fallback.  
**SELL은 cash constraint가 필요 없으므로 price=None 문제의 직접적 영향은 없음.** 단, concentration constraint는 SELL에도 적용될 수 있으나 현재는 price=None으로 skip됨.

---

## 6. 최소 변경 범위 제안

### 6.1 Option A: `SizingInputs`에 `reference_price` 필드 추가 (권장)

**변경 대상**:

| # | 파일 | 변경 내용 | 영향 |
|---|------|----------|------|
| 1 | [`sizing_engine.py`](src/agent_trading/services/sizing_engine.py) | `SizingInputs`에 `reference_price: Decimal \| None = None` 필드 추가 | 하위 호환성 유지 (기본값 None) |
| 2 | [`sizing_engine.py`](src/agent_trading/services/sizing_engine.py) | `_apply_cash_constraint()`에서 `price` 대신 `reference_price` fallback 로직 추가 | `price is None`이어도 `reference_price`가 있으면 cash constraint 적용 |
| 3 | [`sizing_engine.py`](src/agent_trading/services/sizing_engine.py) | `_apply_concentration_constraint()`, `_apply_max_order_value()`에도 동일 fallback 적용 | 일관성 |
| 4 | [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | `_build_sizing_inputs()`에서 `reference_price`를 `_resolve_symbol_price()` 결과로 채움 | 실제 quote 기반 reference price 전달 |
| 5 | [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | `assemble()` 또는 `_build_sizing_inputs()`에서 broker quote 조회 로직 추가 | quote 조회 통합 |

**장점**:
- `SubmitOrderRequest.price`와 `SizingInputs.requested_price`를 변경하지 않음 (하위 호환성)
- MARKET 주문의 price=None 정책 유지
- sizing engine만 수정하면 됨

**단점**:
- `_build_sizing_inputs()`에서 quote 조회를 위해 broker adapter 필요 (현재는 `DecisionOrchestratorService`에 broker 참조 없음)

### 6.2 Option B: `_build_sizing_inputs()`에서 `requested_price`를 quote로 override

**변경 대상**:

| 파일 | 변경 내용 |
|------|----------|
| [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | `_build_sizing_inputs()`에서 `requested_price`가 `None`이고 quote를 조회할 수 있으면 quote.last로 override |

**문제점**:
- `_build_sizing_inputs()`는 현재 broker adapter에 접근할 수 없음 (동기 메서드)
- `assemble_and_submit()`의 Phase 1.5에서 비동기 quote 조회 후 `SizingInputs` 재구성 필요

### 6.3 Option C: `run_paper_decision_loop.py`에서 `SubmitOrderRequest.price`에 quote 전달

**변경 대상**:

| 파일 | 변경 내용 |
|------|----------|
| [`run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) | `_resolve_order_type_and_price()`가 MARKET이어도 `resolved_price`를 `price`에 설정 (sizing용 reference) |
| [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | `assemble_and_submit()` Phase 2에서 `build_submit_order_request_from_decision()` 호출 시 price=None으로 재설정 (broker 제출용) |

**장점**: 변경 범위가 가장 작음  
**단점**: `SubmitOrderRequest.price`에 의미가 섞임 (sizing용 reference vs broker 제출용 price)

### 6.4 권장: Option A + 최소 변경

가장 안전하고 확장성 있는 방법은 **Option A**다. 구체적인 수정 사항:

1. **`SizingInputs`에 `reference_price` 필드 추가**
   - `requested_price`와 별도로, cash constraint 계산에만 사용
   - 기본값 `None`으로 기존 호출자 영향 없음

2. **`_apply_cash_constraint()` 수정**
   ```python
   def _apply_cash_constraint(qty, price, available_cash, min_cash_buffer_pct, 
                               constraints, orderable_amount=None, reference_price=None):
       effective_price = price if (price is not None and price > 0) else reference_price
       if effective_price is None or effective_price <= 0:
           return qty
       # ... 나머지 로직 동일
   ```

3. **`calculate_sizing()` 수정**
   ```python
   # Step 5: cash availability (BUY only)
   if inputs.side == OrderSide.BUY:
       qty = _apply_cash_constraint(
           qty,
           inputs.requested_price,
           inputs.available_cash,
           inputs.min_cash_buffer_pct,
           constraints,
           orderable_amount=inputs.orderable_amount,
           reference_price=inputs.reference_price,  # 추가
       )
   ```

4. **`_build_sizing_inputs()`에서 reference_price 설정**
   - `_resolve_symbol_price()`의 로직을 `DecisionOrchestratorService` 내에서 사용하거나
   - `assemble_and_submit()`의 Phase 1.5 직전에 quote 조회 후 전달

---

## 7. 운영 경로 확인

### 7.1 `near_real_ops_scheduler.py`가 실행하는 커맨드

```python
# _decision_command() [scripts/run_near_real_ops_scheduler.py:645-659]
def _decision_command(*, dry_run: bool) -> list[str]:
    argv = [
        PYTHON_BIN,           # "python3"
        "-m",
        "scripts.run_paper_decision_loop",
        "--count",
        "1",
        "--output",
        "json",
    ]
    if dry_run:
        argv.append("--dry-run")
    else:
        argv.append("--submit")
    return argv
```

- **실제 운영 커맨드**: `python3 -m scripts.run_paper_decision_loop --count 1 --submit`
- **dry-run 커맨드**: `python3 -m scripts.run_paper_decision_loop --count 1 --dry-run`
- **`run_orchestrator_once.py`는 운영에서 사용되지 않음** (독립 실행/디버깅용)

### 7.2 submit budget 로직

```python
# _run_intraday_due_tasks() [scripts/run_near_real_ops_scheduler.py:889-943]
dry_run = not general_budget_ok and not hp_sell_budget_ok
# budget 소진 시 dry-run 모드로 전환
```

- `DEFAULT_MAX_SUBMIT_PER_DAY = 1` (하루 최대 1회 submit)
- `HELD_POSITION_SELL_MAX_PER_DAY = 5` (held position sell은 별도 budget)
- budget 소진 시 `--dry-run` 모드로 전환되어 sizing만 수행

---

## 8. Q&A 요약

### Q1: 10주 하드코딩은 어떤 경로에서 실제 운영 submit에 사용되는가?

**운영 경로**: [`near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py) → [`run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) `--count 1 --submit`  
→ `_run_one_cycle()` → `SubmitOrderRequest(quantity=Decimal("10"))`  
→ `orchestrator.assemble_and_submit()` → Phase 1.5 sizing (skip) → broker submit

`run_orchestrator_once.py`는 운영에서 사용되지 않으며, 독립 실행/디버깅 용도다.

### Q2: 시장가 주문에서 sizing에 사용할 reference price는 어디서 가져오는 게 가장 안전한가?

**가장 안전한 출처**: `broker.get_quote(symbol, market).last` (현재가)

- [`_resolve_symbol_price()`](scripts/run_paper_decision_loop.py:107)가 이미 이 로직을 구현하고 있음
- `quote.last` → `quote.ask` (BUY의 경우 ask가 더 보수적) → `KIS_SMOKE_PRICE` → `Decimal("50000")` fallback
- `_resolve_symbol_price()`의 반환값을 sizing engine까지 전달하는 파이프라인이 필요

### Q3: 제출 price는 None이어도 sizing용 requested_price만 별도로 전달 가능한가?

**가능하다.** `SizingInputs`에 `reference_price` 필드를 추가하면 `SubmitOrderRequest.price=None`과 독립적으로 운용할 수 있다.

현재 `SizingInputs.requested_price`는 `SubmitOrderRequest.price`에서 직접 매핑되므로 분리가 필요하다.

### Q4: BUY는 orderable_amount / reference_price 기준으로 수량 계산이 가능한가?

**가능하다.** [`_apply_cash_constraint()`](src/agent_trading/services/sizing_engine.py:270)는 이미 `orderable_amount / price` 로직을 가지고 있다:

```python
max_qty_by_cash = (effective_cash / price).to_integral_value(rounding=ROUND_DOWN)
```

`price` 자리에 `reference_price`를 사용하면 MARKET 주문에서도 cash constraint가 정상 작동한다.

### Q5: SELL은 어떤 기준으로 수량을 계산/유지하는 것이 맞는가?

**SELL 수량 결정 기준**:
1. `EXIT`: `current_position_qty` (전량 매도)
2. `REDUCE`: `current_position_qty × (1 - reduction_factor)` 또는 `requested_quantity` (position cap 적용)
3. `SELL` (without REDUCE/EXIT): `_base_qty_exit()` → 전량 매도로 처리

SELL은 cash constraint가 필요 없으므로 price=None 문제의 직접적 영향은 없다. 단, concentration constraint는 SELL에도 적용될 수 있다.

### Q6: 가장 작은 수정으로 "10주 고정"을 제거하려면 어디를 고쳐야 하는가?

**최소 변경 범위** (Option A 기준):

| # | 파일 | 수정 사항 |
|---|------|----------|
| 1 | [`sizing_engine.py`](src/agent_trading/services/sizing_engine.py) | `SizingInputs`에 `reference_price` 필드 추가 |
| 2 | [`sizing_engine.py`](src/agent_trading/services/sizing_engine.py) | `_apply_cash_constraint()`에 `reference_price` 파라미터 추가 및 fallback 로직 |
| 3 | [`sizing_engine.py`](src/agent_trading/services/sizing_engine.py) | `_apply_concentration_constraint()`에 동일 fallback |
| 4 | [`sizing_engine.py`](src/agent_trading/services/sizing_engine.py) | `_apply_max_order_value()`에 동일 fallback |
| 5 | [`sizing_engine.py`](src/agent_trading/services/sizing_engine.py) | `calculate_sizing()`에서 `reference_price` 전달 |
| 6 | [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | `_build_sizing_inputs()`에서 `reference_price` 설정 (quote 조회 결과) |
| 7 | [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | `assemble_and_submit()` Phase 1.5에서 quote 조회 후 `_build_sizing_inputs()`에 전달 |

**영향 받는 파일**: `sizing_engine.py`, `decision_orchestrator.py` (2개)

### Q7: 실제 운영 스케줄러의 현재 커맨드 확인

**운영 스케줄러**: [`run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py)  
**실행 커맨드**: `python3 -m scripts.run_paper_decision_loop --count 1 --submit`  
**활성화된 경로**: [`run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) (paper loop)  
**미사용**: [`run_orchestrator_once.py`](scripts/run_orchestrator_once.py) (독립 실행/디버깅용)

---

## 9. 결론

**Root Cause**: `SubmitOrderRequest(quantity=Decimal("10"), price=None)` 하드코딩으로 인해:
1. `requested_quantity=10`이 고정값으로 전달됨
2. `requested_price=None`으로 인해 sizing engine의 모든 price-dependent constraint(cash, concentration, max_order_value)가 skip됨
3. 결과적으로 항상 10주가 그대로 submit됨

**해결 방안**: `SizingInputs`에 `reference_price` 필드를 추가하여, MARKET 주문에서도 quote 기반 cash constraint가 적용되도록 수정. `SubmitOrderRequest.price=None` 정책은 유지하면서 sizing engine만 보강.

**우선순위**: P0 — 현재 운영 환경에서 예수금 대비 과도한 주문이 발생할 수 있는 버그.
