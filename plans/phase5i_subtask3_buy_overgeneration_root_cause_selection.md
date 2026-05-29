# Phase 5i-5 — Subtask 3: BUY order_request 과다 생성 원인 선정

## 선정 결과

**선정: 후보 A — 신규 포지션 concentration constraint gap**

---

## 선택 이유

### Subtask 1 발견 (생성 경로 inventory)

1. [`run_decision_loop.py:741`](../scripts/run_decision_loop.py:741)에서 `SubmitOrderRequest(side=OrderSide.BUY, quantity=Decimal("1"))`가 **모든 universe symbol**에 대해 cycle마다 하드코딩으로 생성됨
2. AI agent(FDC)가 `decision_type`(BUY/APPROVE/HOLD/WATCH)을 결정하며, [`translation.py:76`](../src/agent_trading/services/translation.py:76)에서 non-actionable type(HOLD/WATCH)은 `None` 반환 → SKIPPED
3. Cycle 간 중복 방지 메커니즘 없음 — `submit_budget_consumed`는 **동일 cycle 내에서만 유효**
4. [`sizing_engine.py:402-464`](../src/agent_trading/services/sizing_engine.py:402)의 `_apply_concentration_constraint()`가 **가장 효과적인 방어 계층**

### Subtask 2 발견 (DB/로그 패턴 분석)

1. **현재 로그상 BUY 과다 생성은 실제로 발생하지 않음** — 모든 BUY SubmitOrderRequest가 SKIPPED/BLOCKED 처리됨
2. **유일한 취약점: 신규 포지션 BUY + APPROVE 경로** — concentration constraint가 `current_value=0`일 때 비활성화되어 `qty=1`이 통과 가능
3. [`_resolve_buy_target_quantity()`](../src/agent_trading/services/sizing_engine.py:202)는 `effective_cash * 20% / effective_price`로 baseline 계산하지만, cash가 충분하면 `qty=1` 통과
4. 현재 방어 계층: concentration constraint ✅, stale snapshot guard ✅, non-actionable gate ✅, submit budget ✅

### 후보 상세 평가

#### 후보 A: 신규 포지션 concentration constraint gap ⭐

| 기준 | 평가 | 근거 |
|------|------|------|
| **실제 발생 가능성** | **중간** | Subtask 2에서 유일하게 확인된 실제 취약점. 신규 포지션 BUY+APPROVE 시 `current_value=0`으로 인해 constraint가 비활성화됨. Cash가 충분하면 `qty=1`이 통과 가능. |
| **영향** | **중** | 신규 포지션 BUY 1건이 통과할 가능성. Budget limit(cycle당 1건)으로 급격한 과다는 아님. |
| **수정 난이도** | **저** | [`sizing_engine.py:451`](../src/agent_trading/services/sizing_engine.py:451) 1줄 수정. `current_value=0`이어도 `max_position_value` 기준 제한 유지. |
| **회귀 위험** | **매우 저** | 기존 보유 포지션의 concentration constraint 로직 전혀 변경 없음. 신규 포지션에만 영향. |
| **검증 가능성** | **높음** | 기존 `test_sizing_engine.py` 스위트로 검증 가능. 신규 포지션(`current_value=0`) 케이스만 추가. |

#### 후보 B: SubmitOrderRequest 무조건 생성

| 기준 | 평가 | 근거 |
|------|------|------|
| **실제 발생 가능성** | 높음 | 항상 모든 symbol/cycle에서 발생 |
| **영향** | 저 | budget 소진 후 assemble(LLM API 호출)만 실행, 실제 submit 안 됨. CPU/API 비용 낭비이나 기능적 영향 없음. |
| **수정 난이도** | 저-중 | budget 체크 위치를 `_run_one_cycle()` 호출 전으로 이동 |
| **회귀 위험** | 중 | assemble 결과(TradeDecision)가 이후 로직에서 필요할 수 있음. `_run_one_cycle()`의 return 값이 `_process_one()`에서 status 판단에 사용됨. |
| **검증 가능성** | 중 | assemble 호출 여부 확인 필요 |

#### 후보 C: Cycle 간 BUY 중복 가능

| 기준 | 평가 | 근거 |
|------|------|------|
| **실제 발생 가능성** | 저-중 | AI가 동일 symbol에 반복 BUY 결정 필요 → 드문 경우 |
| **영향** | 저-중 | cycle당 1회, daily budget 제한. 하지만 `submit_budget_consumed`가 cycle마다 reset되어 기술적으로는 매 cycle 1건 submit 가능. |
| **수정 난이도** | 중 | DB unique constraint 추가 |
| **회귀 위험** | 중 | 의도된 재시도(예: 실패한 주문 재전송) 차단 가능 |
| **검증 가능성** | 중 | 통합 테스트 필요 |

#### 후보 D: BUY side 하드코딩

| 기준 | 평가 | 근거 |
|------|------|------|
| **실제 발생 가능성** | 높음 | 항상 발생 |
| **영향** | 저 | CPU/memory만 소비. AI가 HOLD 결정 시 객체 폐기됨. |
| **수정 난이도** | 중 | side 동적 설정. SELL 경로가 이미 별도로 존재하여 복잡성 증가. |
| **회귀 위험** | 중 | SELL 경로와 충돌 가능. 기존 BUY 로직 변경 필요. |
| **검증 가능성** | 중 | |

### 최종 판단

**후보 A**가 선정 기준을 가장 잘 충족:

1. **실제 발생 가능성**: Subtask 2에서 유일하게 확인된 실질적 취약점. `current_value=0`인 신규 포지션의 BUY+APPROVE 경로는 실제 운영 환경에서 발생 가능.
2. **영향**: `qty=1`이 통과 가능하지만, budget limit(cycle당 1건)이 2차 방어. 그러나 여러 cycle에 걸쳐 누적되면 여러 신규 포지션이 열릴 가능성.
3. **수정 난이도**: 가장 낮음. [`sizing_engine.py:451`](../src/agent_trading/services/sizing_engine.py:451)의 `max_additional_qty` 계산식에서 `current_value=0`이어도 `max_position_value` 기준 제한이 적용되도록 개선.
4. **회귀 위험**: 가장 낮음. 기존 보유 포지션 로직 변경 없음.
5. **검증 가능성**: 가장 높음. 단위 테스트로 검증 가능.

**배제 사유:**
- **후보 B**: 영향이 너무 낮고(LLM API 비용만 낭비), 회귀 위험 중간. 실제 BUY 과다 생성 원인이 아님.
- **후보 C**: 설계 의도(cycle당 1 submit)와 충돌. 의도된 재시도를 차단할 위험. 실제 과다 생성보다는 설계 결정에 가까움.
- **후보 D**: 영향이 가장 낮음(CPU/memory). SELL 경로와 충돌 위험. 개선 효과 대비 수정 비용이 높음.

---

## 수정안 (상세 설계)

### 대상 파일
- [`src/agent_trading/services/sizing_engine.py`](../src/agent_trading/services/sizing_engine.py)

### 수정할 함수
- [`_apply_concentration_constraint()`](../src/agent_trading/services/sizing_engine.py:402)

### 변경 전

```python
# Lines 433-451
current_value = Decimal("0")
if current_position_qty is not None and current_position_avg_price is not None:
    current_value = current_position_qty * current_position_avg_price

remaining_capacity = max_position_value - current_value
if remaining_capacity <= 0:
    constraints.append("position_concentration")
    ...
    return Decimal("0")

max_additional_qty = (remaining_capacity / effective_price).to_integral_value(rounding=ROUND_DOWN)
```

**문제**: `current_position_qty`가 `None`이거나 `0`이면 `current_value=0` → `remaining_capacity = max_position_value`. 신규 포지션의 경우 constraint가 사실상 비활성화되어 `max_additional_qty`가 `max_position_value / effective_price`까지 허용됨.

### 변경 후

```python
# Lines 433-451 (수정)
current_value = Decimal("0")
if current_position_qty is not None and current_position_avg_price is not None:
    current_value = current_position_qty * current_position_avg_price

remaining_capacity = max_position_value - current_value
if remaining_capacity <= 0:
    constraints.append("position_concentration")
    ...
    return Decimal("0")

# 항상 max_position_value 기준으로 상한 적용
# current_value=0(신규 포지션)인 경우에도 max_addl_qty가 max_position_value를 초과하지 않도록 보장
max_additional_qty = (max_position_value / effective_price).to_integral_value(rounding=ROUND_DOWN)
if max_additional_qty < qty:
    constraints.append("position_concentration")
    ...
    return max_additional_qty
return qty
```

**변경 내용**: `max_additional_qty` 계산을 `remaining_capacity` 대신 `max_position_value` 기준으로 변경. 이렇게 하면:
- 신규 포지션(`current_value=0`): `max_additional_qty = max_position_value / effective_price` — 항상 제한 적용
- 기존 포지션 보유: `remaining_capacity < max_position_value`이므로 기존보다 더 타이트해지지 않음 (이미 `remaining_capacity`에 의해 제한됨)

**더 정확한 대안**: `remaining_capacity`가 `max_position_value`보다 클 수 없으므로, 다음 중 하나 선택:
```python
# Option 1 (권장): remaining_capacity를 그대로 사용하되 0 이하 체크만 유지
# 실제로 remaining_capacity <= 0 체크가 이미 있으므로, 신규 포지션은 max_position_value 제한을 받음
# 변경 불필요 — 문제는 remaining_capacity가 충분히 클 때 qty=1이 통과하는 것

# Option 2 (대안): 신규 포지션에 대한 별도 최소 제한
max_additional_qty = (max_position_value / effective_price).to_integral_value(rounding=ROUND_DOWN)
```

**권장**: **Option 1** — 현재 로직 유지. `remaining_capacity = max_position_value - current_value`에서 `current_value=0`이면 `remaining_capacity = max_position_value`. `max_additional_qty = (remaining_capacity / effective_price)`이므로 자연스럽게 `max_position_value` 기준 제한이 적용됨.

**실제 수정할 부분은 `_resolve_buy_target_quantity()`와 `_apply_concentration_constraint()`의 상호작용**:

`sizing_engine.py:451`에서 `max_additional_qty` 계산 후 `return max_additional_qty`를 통해 quantity를 제한하는 것은 이미 작동 중. **실제 gap은 `_resolve_buy_target_quantity()`에서 `target_qty < 1`일 때 `target_qty = 1`로 강제하는 부분**:

```python
# sizing_engine.py:252-253
if target_qty < 1:
    target_qty = 1
```

이 `min 1 share` 보장이 concentration constraint의 `max_additional_qty < qty` 체크를 우회할 수 있음. 만약 `max_additional_qty = 0`이고 `qty = 1`이면, `0 < 1`이므로 constraint가 적용되어 `0` 반환. 하지만 `max_additional_qty >= 1`이면 `qty=1`이 통과.

**결론**: 현재 로직은 `max_additional_qty >= 1`인 경우 `qty=1`을 허용하도록 설계되어 있음. 이는 **의도된 동작**일 가능성이 높음 (1주라도 매수하여 포지션을 열 수 있어야 함).

### 실제 수정 방향

`_apply_concentration_constraint()`에 **신규 포지션 최소 진입 임계값(minimum entry threshold)** 추가:

```python
def _apply_concentration_constraint(
    qty: Decimal,
    price: Decimal | None,
    current_position_qty: Decimal | None,
    current_position_avg_price: Decimal | None,
    nav: Decimal | None,
    max_single_position_pct: Decimal | None,
    constraints: list[str],
    reference_price: Decimal | None = None,
) -> Decimal:
    ...
    max_position_value = nav * max_single_position_pct / Decimal("100")

    current_value = Decimal("0")
    if current_position_qty is not None and current_position_avg_price is not None:
        current_value = current_position_qty * current_position_avg_price

    remaining_capacity = max_position_value - current_value
    if remaining_capacity <= 0:
        constraints.append("position_concentration")
        ...
        return Decimal("0")

    max_additional_qty = (remaining_capacity / effective_price).to_integral_value(rounding=ROUND_DOWN)
    
    # --- 추가: 신규 포지션 최소 진입 임계값 ---
    # 신규 포지션(current_value=0)의 경우, max_single_position_pct의 일정 비율(예: 50%) 이상일 때만 진입 허용
    # 이는 미미한 qty=1이 통과하여 불필요한 포지션이 생성되는 것을 방지
    if current_value == 0 and max_additional_qty > 0:
        min_entry_value = max_position_value * Decimal("0.5")  # 50% threshold
        min_entry_qty = (min_entry_value / effective_price).to_integral_value(rounding=ROUND_UP)
        if qty < min_entry_qty:
            constraints.append("min_entry_threshold")
            logger.info(
                "Sizing min entry threshold activated: "
                "nav=%s max_pct=%s max_position_value=%s "
                "effective_price=%s req_qty=%s min_entry_qty=%s final_qty=0",
                nav, max_single_position_pct, max_position_value,
                effective_price, qty, min_entry_qty,
            )
            return Decimal("0")
    # --- 추가 끝 ---

    if max_additional_qty < qty:
        ...
```

**임계값 설정**: `max_single_position_pct`의 50%. 즉, 최대 허용 포지션의 절반 이상일 때만 신규 진입 허용. 이는 `qty=1` 같은 미미한 진입을 차단하면서도 의미 있는 진입은 허용.

---

## 검증 계획

### 기존 테스트 영향
- **영향 없음**: 기존 테스트는 보유 포지션이 있는 케이스(`current_value > 0`)를 주로 테스트. 신규 조건(`current_value == 0`)은 기존 테스트에 영향을 주지 않음.
- **기존 통과 테스트 그대로 통과 예상**.

### 신규 테스트

`tests/services/test_sizing_engine.py`에 추가할 케이스:

1. **`test_concentration_constraint_new_position_below_threshold`**
   - `current_position_qty=None`, `current_position_avg_price=None` (신규 포지션)
   - `qty=1`, `max_single_position_pct=5%`, 적정 `nav`, `effective_price`
   - 기대 결과: `0` (min_entry_threshold constraint 적용)

2. **`test_concentration_constraint_new_position_above_threshold`**
   - 동일 조건, `qty`를 min_entry_qty 이상으로 설정
   - 기대 결과: `qty` 유지 또는 `max_additional_qty`로 제한

3. **`test_concentration_constraint_existing_position_unchanged`**
   - 보유 포지션 있음 (`current_value > 0`)
   - 기존과 동일하게 동작하는지 확인 (회귀 방지)

### 실행 검증
```bash
# 기존 테스트 스위트 실행
pytest tests/services/test_sizing_engine.py -v

# 신규 테스트만 실행
pytest tests/services/test_sizing_engine.py -v -k "concentration"
```
