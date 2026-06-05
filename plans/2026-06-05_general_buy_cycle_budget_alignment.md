# 일반 BUY cycle budget 정렬

## 배경

`ops-scheduler`는 일일 일반 BUY 상한을 `max_general_buy_submit_per_day`로 계산하고 있었지만,
실제 `run_decision_loop` subprocess는 cycle 내부에서 일반 BUY submit을 최대 1건만 허용하고 있었다.

그 결과:

- 하루 일반 BUY cap이 6건이어도
- 같은 `decision_submit_gate` cycle 안에서는 첫 성공 주문 이후
- 나머지 core / market_overlay BUY 후보가 `submit_budget_consumed_*`로 dry-run 처리됐다.

이는 현재 운영 정책인 "일반 BUY 일일 cap"과 구현이 어긋나는 상태였다.

## 수정 내용

### 1. `run_decision_loop`에 cycle budget 인자 추가

- 신규 CLI 인자: `--max-general-submits-this-cycle`
- 기본값은 `1`로 유지해서 단독 실행 기본 동작은 보수적으로 유지
- 일반 lane submit 가능 여부를 boolean이 아니라
  `submit_budget_consumed_count < max_general_submits_this_cycle`
  로 판단하도록 변경

### 2. cycle 내 일반 BUY submit 카운트 추적

- `submit_budget_consumed` boolean을 `submit_budget_consumed_count` 정수로 변경
- `SUBMITTED` / `RECONCILE_REQUIRED` 시 일반 lane 카운트를 증가
- held_position 위험 축소 SELL lane은 기존처럼 별도 처리

### 3. `ops-scheduler`가 남은 일일 BUY budget을 subprocess에 전달

- `_decision_command()`가 `--max-general-submits-this-cycle`를 항상 전달
- `_run_intraday_due_tasks()`에서
  `remaining_general_submit_budget = max(0, max_general_buy_submit_per_day - effective_submit_count)`
  계산 후 전달

즉 이제 같은 cycle 안에서도 남은 일일 BUY budget만큼 일반 BUY submit을 시도할 수 있다.

## 기대 효과

- 첫 BUY 성공 후 같은 cycle의 나머지 BUY가 무조건 dry-run 되지 않음
- `max_general_buy_submit_per_day=6` 설정 의미가 실제 cycle 실행에도 반영됨
- `submit_budget_consumed_core/market_overlay`가 "cycle 내부 1건 제한"이 아니라
  "실제 남은 일일 BUY budget 소진"을 더 정확히 의미하게 됨

## 검증

- `tests/scripts/test_run_decision_loop.py`
  - pre-submit 실패 후 다음 BUY가 slot 승계
  - cycle budget이 3이면 일반 BUY 3건까지 submit 허용
- `tests/scripts/test_run_ops_scheduler.py`
  - `_decision_command()`가 cycle budget 인자를 전달
  - scheduler가 남은 일일 BUY budget(예: 6-2=4)을 전달

결과:

- `38 passed`
- `python3 -m py_compile ...` 통과

