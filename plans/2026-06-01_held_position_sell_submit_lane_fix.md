# held_position SELL 제출 lane 복구

## 배경

2026-06-01 14:14 KST에 `001740` 종목은 AI 의사결정에서 `REDUCE/SELL` 근거가 생성되었지만, 실제 주문은 생성되지 않고 `결정만 생성됨(DRY_RUN)`으로 끝났다.

로그와 DB를 확인한 결과, 이 건은 SELL guard나 보유수량 부족으로 막힌 것이 아니라 같은 decision cycle 안에서 일반 submit 슬롯이 먼저 예약되면서 `held_position` 종목도 함께 dry-run으로 내려간 케이스였다.

## 직접 원인

`scripts/run_decision_loop.py`의 cycle 내부 병렬 처리 로직은 다음처럼 동작하고 있었다.

1. 어떤 종목이든 `submit=True`면 먼저 `submit_budget_consumed`를 확인
2. 앞선 종목이 일반 BUY submit 슬롯을 예약하면 `submit_budget_consumed=True`
3. 뒤늦게 평가된 `source_type=held_position` 종목도 동일한 플래그에 막혀 `submit=False`, `dry_run=True`

즉, "held-position SELL은 위험 축소 목적이므로 일반 BUY보다 덜 막아야 한다"는 정책이 scheduler 레벨에서는 있었지만, 실제 per-symbol 실행 레벨에서는 일반 submit 슬롯과 분리되어 있지 않았다.

## 수정 내용

### 1. per-symbol submit 판정 helper 추가

`_compute_symbol_submit_mode()`를 추가해 종목별 `submit/dry_run` 판정을 한곳으로 모았다.

- `core` 종목:
  - 기존대로 `submit_budget_consumed`를 따른다.
- `held_position` 종목:
  - 일반 submit 슬롯과 분리한다.
  - 대신 cycle cap(`HELD_POSITION_SELL_MAX_PER_CYCLE=2`)과 same-symbol dedupe만 적용한다.

### 2. 일반 submit 슬롯 예약 범위 축소

기존에는 `symbol_submit=True`인 모든 종목이 실행 전에 `submit_budget_consumed=True`를 예약했다.

수정 후에는:

- `core` 종목만 실행 전에 일반 submit 슬롯을 예약
- `held_position` 종목은 별도 lane으로 submit path에 진입

실제 결과가 `REDUCE/EXIT + SELL`로 확인되면 기존처럼 cycle cap 카운터와 symbol dedupe 집계는 유지한다.

## 기대 효과

- 같은 cycle에서 앞선 BUY 후보가 submit 슬롯을 잡아도, 뒤의 `held_position` SELL 후보는 여전히 실제 submit 경로로 갈 수 있다.
- `001740` 같은 위험 축소 SELL이 "결정만 생성됨"으로 내려앉는 현상을 줄인다.
- 기존 BUY 중복 방지(`submit_budget_consumed` 선예약)는 그대로 유지된다.

## 검증

실행한 검증:

1. `python3 -m py_compile scripts/run_decision_loop.py tests/scripts/test_run_decision_loop.py`
2. `pytest -q tests/scripts/test_run_decision_loop.py -k "HeldPositionSellBudget or test_submit or test_dry_run"`

결과:

- `11 passed`

추가한 회귀 검증:

- 일반 submit 슬롯이 이미 소비된 상태에서도 `held_position`은 submit 가능해야 함
- held-position cycle cap 초과 시 dry-run으로 내려가야 함
- 같은 symbol 중복 held-position submit은 막아야 함
- `core` 종목은 여전히 일반 submit 슬롯을 따라야 함

## 후속 확인 포인트

운영에서는 `ops-scheduler` 재시작 후 다음 held-position SELL 후보가 `submit=False dry_run=True`가 아니라 실제 submit path로 진입하는지 로그에서 재확인한다.
