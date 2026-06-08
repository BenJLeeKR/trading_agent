# 2026-06-05 Pre-AI Decision Skip Gate

## 목적

의사결정 루프의 맨 앞단에서 명백히 비실행 대상인 종목을 걸러서, 불필요한 AI 호출과 토큰 사용량을 줄인다.

## 적용 정책

### 1. held_position 경로

- 해석: `held_position` 경로는 위험 축소를 위한 매도 판단 후보로 본다.
- 조건:
  - 해당 계좌의 최신 포지션 스냅샷에서
  - 현재 심볼의 보유 수량이 없거나 `<= 0`
- 동작:
  - AI 호출 전에 즉시 `SKIPPED`
  - `error_phase=pre_ai_gate`
  - `error_message=no_held_position`

### 2. 일반 BUY 경로

- 해석: `core`, `market_overlay`, `event_overlay`, `manual` 등 `held_position`이 아닌 경로는 BUY 판단 후보로 본다.
- 조건:
  - 최신 `cash_balance_snapshot.orderable_amount < 0`
  - 또는 `orderable_amount <= 500000`
  - 또는 `remaining_general_buy_budget <= 0` 이고 현재 심볼의 실보유 수량도 없음
- 동작:
  - AI 호출 전에 즉시 `SKIPPED`
  - `error_phase=pre_ai_gate`
  - `error_message=negative_orderable_amount | low_orderable_amount | general_buy_budget_exhausted`

## 3. 일반 lane SELL 오판 토큰 낭비 방지

- 현재 구조상 `core` 경로에서도 AI가 `SELL/REDUCE` 판단을 낼 수 있다.
- 하지만 pre-AI 단계에서는 아직 최종 방향(`BUY/SELL`)을 모른다.
- 따라서 다음 보수 정책을 추가했다.
  - `held_position`이 아닌 경로에서
  - 현재 심볼의 실보유 수량이 없고
  - 일반 BUY 예산도 이미 소진된 경우
- 해당 심볼은 더 이상 실행 가능한 `BUY`도, 실보유 기반 `SELL`도 만들기 어렵다고 보고
  AI 호출 전에 `general_buy_budget_exhausted`로 바로 `SKIPPED` 처리한다.

## 기준금액(500,000원) 선택 이유

- 기존 sizing 엔진의 신규 진입 최소 진입금액(`min_entry_threshold`)과 맞췄다.
- 즉, 어차피 sizing 단계에서 신규 진입이 차단될 만큼 주문가능금액이 작은 경우라면, AI 호출 자체를 생략하는 편이 더 효율적이다.

## 구현 위치

- `scripts/run_decision_loop.py`
  - `PRE_AI_BUY_MIN_ORDERABLE_AMOUNT`
  - `_evaluate_pre_ai_skip_reason()`
  - `_run_one_cycle()` 진입 직후 pre-AI gate 적용

## 검증

- `tests/scripts/test_run_decision_loop.py`
  - 주문가능금액 `499,999` → `low_orderable_amount`로 `SKIPPED`
  - held_position 수량 `0` → `no_held_position`로 `SKIPPED`
  - 보유수량 `0` + `remaining_general_buy_budget=0` → `general_buy_budget_exhausted`로 `SKIPPED`
  - 보유수량 `> 0` + `remaining_general_buy_budget=0` → 즉시 skip하지 않음 (SELL 후보 가능성 유지)

## 기대 효과

- 명백한 비실행 대상에 대해 EI/AR/FDC 호출을 생략
- 장중 토큰 사용량 감소
- 의미 없는 `HOLD/WATCH` 생성 감소
