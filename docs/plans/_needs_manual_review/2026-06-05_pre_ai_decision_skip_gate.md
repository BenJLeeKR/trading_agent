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

## 2026-06-18 후속 확장 원칙

현재 문서는 `cash/orderable_amount/held_position` 중심의 1차 pre-AI gate만 다룬다.
후속 2차 확장은 아래 순서와 범위를 따른다.

### 1. 우선 확장할 항목

- `deterministic_trigger.eligibility_reasons` 기반 조기 종료
  - 대상:
    - `eligibility_low_average_volume`
    - `eligibility_low_turnover`
    - `eligibility_allocation_blocked`
    - `eligibility_risk_off_block`
    - `eligibility_participation_rate_blocked`
- `recent_events == 0`일 때 EI 생략
- `primary_candidate == NO_ACTION` 이고 `recent_events == 0`인 경우
  신규 진입 후보에 한해 AR/FDC까지 생략
- AR이 `reject` 또는 고위험 점수를 반환한 경우
  FDC 조건부 생략

### 2. 적용 범위 제한

- 위 확장은 우선 `core` 등 신규 BUY 검토 경로에만 적용한다.
- `held_position` 경로에는 그대로 적용하지 않는다.
- `reconciliation_overlay`, 상태 복구, snapshot 정합성 확인 경로에도 그대로 적용하지 않는다.

이유는 다음과 같다.

- 보유종목 경로는 `REDUCE/EXIT` 기회를 놓치지 않는 것이 토큰 절감보다 우선이다.
- 정합성 복구 경로는 신규 진입보다 우선이며,
  unknown state에서는 더더욱 AI 호출 최적화보다 상태 확인이 우선이다.

### 3. 측정 원칙

- 후속 구현 전후로 아래를 구조화해 측정한다.
  - EI skip count
  - AR skip count
  - FDC skip count
  - skip reason 분포
  - source_type별 skip 비율
- 토큰 절감 수치는 계측 결과를 기준으로만 판단한다.
  정성 추정치만으로 목표치를 먼저 고정하지 않는다.

### 4. 현재 구현 반영 상태

- `TradeDecisionEntity.decision_json.ai_call_path`에
  `ei_skipped`, `ar_skipped`, `fdc_skipped`, `skip_reason_codes`를 저장한다.
- `run_decision_loop` cycle result에도 같은 필드를 직렬화한다.
- `run_decision_loop` summary metrics에도 아래 집계를 포함한다.
  - `tracked_count`
  - `ei_skipped_count`
  - `ar_skipped_count`
  - `fdc_skipped_count`
  - `skip_reason_counts`
- 따라서 장중 운영에서는 DB 조회와 loop summary 양쪽에서
  short-circuit 적용률을 동시에 실측할 수 있다.
