# 인계 문서: 차기 Roo Code 세션 핸드오버

> **작성일**: 2026-05-21 (UTC+9:00, Asia/Seoul)
> **대상**: 차기 Roo Code 세션 작업자
> **목적**: 이번 세션(2026-05-21)의 모든 작업 상황과 의사결정 맥락을 인계하여 끊김 없는 작업 연속성 확보

---

## 1. Current Status (현재 상태)

이번 세션에서는 **User Request 13, 13b, 13c** 라는 3개의 연쇄 작업을 완료하고, **AR 2-layer defense 생산 검증**을 수행했습니다. 모든 코드 변경은 테스트와 Docker 빌드 검증까지 완료된 상태입니다.

---

### A. User Request 13 — Reference price 기반 MARKET 주문 sizing + 10주 하드코딩 제거 ✅ 완료

#### 문제 상황
[`run_paper_decision_loop.py:738`](scripts/run_paper_decision_loop.py:738)에서 `quantity=Decimal("10")`이 하드코딩되어 있었고, MARKET 주문 시 `price=None`이 전달되면서 sizing constraint(`_apply_cash_constraint`, `_apply_concentration_constraint`, `_apply_max_order_value`)가 모두 `requested_price`가 `None`이므로 skip 처리되었습니다. 결과적으로 항상 10주가 제출되는 버그였습니다.

#### 해결 방법
- [`SizingInputs`](src/agent_trading/services/sizing_engine.py)에 `reference_price` 필드 추가
- 3개 constraint 함수(`_apply_cash_constraint`, `_apply_concentration_constraint`, `_apply_max_order_value`)가 `requested_price`가 `None`일 때 `reference_price`로 fallback하도록 수정
- MARKET 주문 전용 `safety_factor=0.95` 적용 (매수 시 현금 여유분 확보)

#### 변경 파일
| 파일 | 변경 내용 |
|------|-----------|
| [`src/agent_trading/services/sizing_engine.py`](src/agent_trading/services/sizing_engine.py) | `SizingInputs.reference_price` 필드, constraint fallback 로직 |
| [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | `_build_sizing_inputs()` reference_price 파라미터, quote resolution |
| [`tests/services/test_sizing_engine.py`](tests/services/test_sizing_engine.py) | 12개 신규 테스트 |

#### 테스트 결과
- **63/63 통과** (기존 51 + 신규 12)
- 설계 문서: [`plans/remove_fixed_10_share_order_quantity_and_enable_reference_price_based_market_order_sizing_2026-05-21.md`](plans/remove_fixed_10_share_order_quantity_and_enable_reference_price_based_market_order_sizing_2026-05-21.md)
- 분석 문서: [`plans/analyze_fixed_10_share_market_order_sizing_root_cause_2026-05-21.md`](plans/analyze_fixed_10_share_market_order_sizing_root_cause_2026-05-21.md)

---

### B. AR 2-layer defense 생산 검증 ✅ (Pending — 차기 장중 재확인 필요)

#### 목적
AI Risk의 Layer 2 guard가 실제 생산 환경에서 정상 동작하는지 검증:
- `reject` → `review` 전환
- `available_cash` → `orderable_amount` 우선 정책

#### 결과
코드는 이미 배포 완료되었습니다(Docker 재빌드 + ops-scheduler 재시작). 그러나 쿼리 시점에 신규 코드로 실행된 AR run이 0건이어서 **Layer 2 guard의 실제 동작을 확인할 수 없었습니다**.

#### ⚠️ Key Judgment: **부분 개선 (Pending)** — 차기 장중(2026-05-22) 재확인 필요
- 검증 보고서: [`plans/reverify_ai_risk_effective_buying_cash_and_reject_to_review_guard_2026-05-21.md`](plans/reverify_ai_risk_effective_buying_cash_and_reject_to_review_guard_2026-05-21.md)

---

### C. User Request 13b — 고가주 sub-10 BUY baseline + `_resolve_buy_target_quantity()` ✅ 완료

#### 문제 상황
[`_resolve_base_quantity()`](src/agent_trading/services/sizing_engine.py)가 `inputs.requested_quantity`를 그대로 반환하는 구조였습니다. 고가주(예: SK하이닉스 200,000원)에서 10주를 BUY하면 200만원이 소모되어 과도한 주문이 발생했습니다.

#### 해결 방법
- [`_resolve_buy_target_quantity()`](src/agent_trading/services/sizing_engine.py) 신규 메서드 도입
- 모듈 레벨 상수 `_ALLOCATION_PCT = 0.2` (20%) 정의
- 계산 공식: `target_qty = floor(orderable_amount * 20% / price)`
- 최소 1주 보장, `requested_quantity`로 capped

#### 변경 파일
| 파일 | 변경 내용 |
|------|-----------|
| [`src/agent_trading/services/sizing_engine.py`](src/agent_trading/services/sizing_engine.py) | `_resolve_buy_target_quantity()` ~35라인 추가 |

#### 테스트 결과
- **71/71 통과** (신규 8개)
- 설계 문서: [`plans/remove_fixed_10_share_buy_baseline_and_enable_sub_10_quantities_for_high_price_stocks_2026-05-21.md`](plans/remove_fixed_10_share_buy_baseline_and_enable_sub_10_quantities_for_high_price_stocks_2026-05-21.md)
- 분석 문서: [`plans/analyze_buy_baseline_10_share_hardcoding_and_sub_10_quantities_2026-05-21.md`](plans/analyze_buy_baseline_10_share_hardcoding_and_sub_10_quantities_2026-05-21.md)

---

### D. User Request 13c — `requested_quantity=10` 상한 제거 + 완전 동적 BUY 수량 ✅ 완료

#### 문제 상황
[`_resolve_buy_target_quantity()`](src/agent_trading/services/sizing_engine.py:227)의 `return min(target_qty, requested_quantity)`에서 `requested_quantity=10`이 상한으로 작동했습니다. 이로 인해 중저가주(삼성전자 80,000원)도 10주 이상 주문이 불가능한 문제가 있었습니다.

#### 해결 방법
- **Phase 1**: [`sizing_engine.py:227`](src/agent_trading/services/sizing_engine.py:227)에서 `min()` cap 제거 → `return Decimal(str(target_qty))`
- **Phase 2**: Entrypoint 기본값 `Decimal("10")` → `Decimal("1")` 변경

#### 변경 파일
| 파일 | 변경 내용 |
|------|-----------|
| [`src/agent_trading/services/sizing_engine.py:227`](src/agent_trading/services/sizing_engine.py:227) | `min()` cap 제거 |
| [`scripts/run_paper_decision_loop.py:738`](scripts/run_paper_decision_loop.py:738) | `Decimal("10")` → `Decimal("1")` |
| [`scripts/run_orchestrator_once.py:359`](scripts/run_orchestrator_once.py:359) | `Decimal("10")` → `Decimal("1")` |
| [`tests/services/test_sizing_engine.py`](tests/services/test_sizing_engine.py) | 3개 기대값 업데이트 + 1개 신규 테스트 |

#### 테스트 결과
- **73/73 통과**
- **Docker 검증**: `docker compose build` 성공, 5개 대표 가격 시나리오 검증 완료
- 설계 문서: [`plans/remove_requested_quantity_10_cap_and_enable_fully_dynamic_buy_quantities_2026-05-21.md`](plans/remove_requested_quantity_10_cap_and_enable_fully_dynamic_buy_quantities_2026-05-21.md)
- 분석 문서: [`plans/analyze_remove_requested_quantity_10_cap_2026-05-21.md`](plans/analyze_remove_requested_quantity_10_cap_2026-05-21.md)

---

### 현재 BUY 수량 계산 공식 (최종 상태)

```
BUY quantity = floor(orderable_amount * 20% / effective_price)
              (최소 1주, requested_quantity 상한 없음)

effective_price = requested_price or reference_price (MARKET)
effective_cash  = orderable_amount or available_cash

이후 4중 risk constraint 체인:
1. _apply_cash_constraint()      — cash / (price * safety_factor)
2. _apply_concentration_constraint() — portfolio % cap
3. _apply_max_order_value()      — max_order_value / price
4. _apply_max_order_qty()        — configurable max qty
```

#### 대표 가격 시나리오 (orderable_amount = 9,000,000원 기준)

| 종목 | 가격 | 최종 BUY 수량 |
|------|------|---------------|
| SK하이닉스 | 200,000원 | 9주 |
| 두산 | 150,000원 | 12주 |
| 삼성전자 | 80,000원 | 22주 |
| 저가주 | 30,000원 | 60주 |
| 초저가주 | 5,000원 | 360주 |

---

## 2. Work In Progress (진행 중인 작업)

### ⚠️ AR Layer 2 guard — 차기 장중 운영 검증 필요 (2026-05-22)

**상태**: 코드 배포 완료 (`docker compose build` + ops-scheduler 재시작 완료). 그러나 아직 신규 AR run이 실행되지 않아 Layer 2 guard가 실제로 동작하는지 미확인 상태입니다.

#### 차기 세션에서 확인해야 할 사항

1. **ops-scheduler 로그 확인**
   - 로그에서 `"Layer2 Guard applied"` 메시지 검색
   - Layer 2 guard가 정상적으로 호출되는지 확인

2. **DB 데이터 검증**
   - `orderable_amount > 0`인 AI Risk run의 `risk_opinion`이 `review`로 저장되는지 확인
   - AR Layer 1 (`reject` → `review` 전환)이 의도대로 동작하는지 검증

3. **FDC downstream 동작 확인**
   - `review` opinion에 대한 FDC의 실제 판단 로그 확인
   - FDC가 `review`를 어떻게 처리하는지(end-to-end) 추적

#### 참고 문서
- [`plans/reverify_ai_risk_effective_buying_cash_and_reject_to_review_guard_2026-05-21.md`](plans/reverify_ai_risk_effective_buying_cash_and_reject_to_review_guard_2026-05-21.md)

---

### 🔴 알려진 이슈 (추가 작업 불필요 — 참고용)

이번 세션에서 수정된 모든 코드는 테스트 73/73 통과, Docker 검증 완료 상태입니다. **미해결 이슈는 없습니다.**

---

## 3. Implicit Context (숨은 맥락 및 의사결정)

이 섹션은 코드만으로는 파악하기 어려운 아키텍처 결정사항과 정책을 기록합니다.

---

### A. `SizingInputs.reference_price` — MARKET 주문용 sizing 기준 가격

#### Quote Resolution (decision_orchestrator.py Phase 1.5)

[`assemble_and_submit()`](src/agent_trading/services/decision_orchestrator.py)의 Phase 1.5에서 quote 기반으로 `reference_price`를 결정합니다.

**Quote 우선순위**:
| 방향 | 우선순위 |
|------|----------|
| **BUY** | `last > ask > bid` |
| **SELL** | `last > bid > ask` |

#### `safety_factor=0.95` 적용 조건
- `requested_price is None AND reference_price is not None`일 때만 적용
- 즉, **MARKET 주문 전용**
- LIMIT 주문은 `requested_price`를 사용하며 `reference_price`를 무시

---

### B. `_ALLOCATION_PCT = 0.2` (20%) — 단일 BUY 현금 할당 비율

- 정의 위치: 모듈 레벨 상수 [`src/agent_trading/services/sizing_engine.py`](src/agent_trading/services/sizing_engine.py)
- 의미: `orderable_amount`의 20%를 단일 BUY 주문에 할당
- 사용처: [`_resolve_buy_target_quantity()`](src/agent_trading/services/sizing_engine.py)
- 설계 의도: **보수적 접근**. 이후 4중 risk constraint 체인이 추가로 제한을 가하므로, baseline 자체를 과도하게 설정할 필요 없음

---

### C. Entrypoint `requested_quantity` 기본값

| 파일 | 현재값 | 이전값 | 비고 |
|------|--------|--------|------|
| [`scripts/run_paper_decision_loop.py:738`](scripts/run_paper_decision_loop.py:738) | `Decimal("1")` | `Decimal("10")` | 변경 완료 |
| [`scripts/run_orchestrator_once.py:359`](scripts/run_orchestrator_once.py:359) | `Decimal("1")` | `Decimal("10")` | 변경 완료 |
| [`decision_orchestrator.py:1598`](src/agent_trading/services/decision_orchestrator.py:1598) | `intent.request.quantity or Decimal("10")` | 동일 | **변경 안함** |

#### 중요: `requested_quantity`의 의미 변화
- **이전**: BUY 수량의 절대적 상한
- **현재**: 
  - BUY 경로: `or Decimal("10")`는 `intent.request.quantity`가 `None`일 때만 fallback. 현재 entrypoint에서 `Decimal("1")`이 전달되므로 이 fallback은 발동하지 않음
  - price와 reference_price가 모두 `None`이면 fallback으로 사용됨
  - SELL 경로: 여전히 이 값을 base로 사용

#### TODO (선택사항)
[`decision_orchestrator.py:1598`](src/agent_trading/services/decision_orchestrator.py:1598)의 `or Decimal("10")`을 `or Decimal("1")`로 변경할 수 있으나, 현재 `Decimal("1")`이 entrypoint에서 항상 전달되므로 **기능적 영향은 없어 불필요한 변경**으로 판단됨.

---

### D. SELL 경로는 변경 없음

모든 User Request(13, 13b, 13c)에서 **SELL sizing은 기존 position-aware 로직을 유지**했습니다.

- [`_resolve_base_quantity()`](src/agent_trading/services/sizing_engine.py)에서 `OrderSide.SELL`이면 `inputs.requested_quantity` 반환
- position holding 수량 기반으로 sizing 수행
- BUY 경로만 `_resolve_buy_target_quantity()`를 통해 새 로직 적용

---

### E. [`_build_sizing_inputs()`](src/agent_trading/services/decision_orchestrator.py) — `requested_quantity` 전달 구조

```python
requested_quantity=intent.request.quantity or Decimal("10")
```

- `intent.request.quantity`는 entrypoint에서 전달된 값 (현재 `Decimal("1")`)
- `or Decimal("10")` 구문은 `None`일 때만 fallback (Python falsy 체크)
- `Decimal("1")`은 truthy이므로 이 fallback이 발동하지 않음
- **일관성 개선 제안**: 추후 리팩터링 시 `or Decimal("1")`로 변경 검토

---

### F. Cash 우선순위 정책 (AR Layer 1과 일관)

```
effective_cash = orderable_amount or available_cash
```

- `orderable_amount`가 **있으면** 우선 사용 (AR Layer 1 정책 반영)
- `orderable_amount`가 **None이면** `available_cash`로 fallback
- AI Risk의 `orderable_amount` 필드 도입 결정과 일관된 정책

---

### G. Docker 운영 참고사항

| 항목 | 내용 |
|------|------|
| **이미지 빌드** | `docker compose build` (4개 이미지: app, api, reconciliation-worker, ops-scheduler) |
| **ops-scheduler 재시작** | `docker compose restart ops-scheduler` |
| **Health check** | `curl -sf http://localhost:8000/health` |
| **Python 명령어** | 반드시 `python3` 사용 (shebang 포함) |
| **Shell** | 반드시 `/bin/bash` 기준 |
| **주의** | `.env` 파일 수정 금지 |

---

## 4. Plans 디렉토리 문서 목록 (이번 세션 생성)

| 파일 | 설명 |
|------|------|
| [`plans/analyze_fixed_10_share_market_order_sizing_root_cause_2026-05-21.md`](plans/analyze_fixed_10_share_market_order_sizing_root_cause_2026-05-21.md) | **User Request 13**: MARKET order 10주 고정 근본 원인 분석 |
| [`plans/remove_fixed_10_share_order_quantity_and_enable_reference_price_based_market_order_sizing_2026-05-21.md`](plans/remove_fixed_10_share_order_quantity_and_enable_reference_price_based_market_order_sizing_2026-05-21.md) | **User Request 13**: reference_price 기반 sizing 설계 |
| [`plans/reverify_ai_risk_effective_buying_cash_and_reject_to_review_guard_2026-05-21.md`](plans/reverify_ai_risk_effective_buying_cash_and_reject_to_review_guard_2026-05-21.md) | **AR 2-layer guard**: 생산 검증 보고서 |
| [`plans/analyze_buy_baseline_10_share_hardcoding_and_sub_10_quantities_2026-05-21.md`](plans/analyze_buy_baseline_10_share_hardcoding_and_sub_10_quantities_2026-05-21.md) | **User Request 13b**: BUY baseline 10주 고정 분석 |
| [`plans/remove_fixed_10_share_buy_baseline_and_enable_sub_10_quantities_for_high_price_stocks_2026-05-21.md`](plans/remove_fixed_10_share_buy_baseline_and_enable_sub_10_quantities_for_high_price_stocks_2026-05-21.md) | **User Request 13b**: `_resolve_buy_target_quantity()` 설계 |
| [`plans/analyze_remove_requested_quantity_10_cap_2026-05-21.md`](plans/analyze_remove_requested_quantity_10_cap_2026-05-21.md) | **User Request 13c**: 10주 상한 근본 원인 분석 |
| [`plans/remove_requested_quantity_10_cap_and_enable_fully_dynamic_buy_quantities_2026-05-21.md`](plans/remove_requested_quantity_10_cap_and_enable_fully_dynamic_buy_quantities_2026-05-21.md) | **User Request 13c**: cap 제거 + 동적 수량 설계 |

---

## 5. 요약 체크리스트 — 차기 세션 시작 시

- [ ] **AR Layer 2 guard 생산 검증** (2026-05-22 장중)
  - [ ] ops-scheduler 로그에서 `"Layer2 Guard applied"` 확인
  - [ ] DB `risk_opinion = 'review'` 저장 확인
  - [ ] FDC downstream 동작 확인
- [ ] (선택) [`decision_orchestrator.py:1598`](src/agent_trading/services/decision_orchestrator.py:1598) `or Decimal("10")` → `or Decimal("1")` 리팩터링 검토
- [ ] (선택) 신규 User Request 접수 시 위 `Current Status` 및 `Implicit Context` 참조

---

*인계 완료. 이 문서는 [`plans/HANDOVER_TO_NEW_SESSION.md`](plans/HANDOVER_TO_NEW_SESSION.md)에 저장되어 있습니다.*
