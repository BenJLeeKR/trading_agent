# 2026-06-02 일반 BUY budget에서 held_position SELL 제외

## 배경
2026-06-02 장중에 BUY 주문이 0건이었던 원인을 추적한 결과, `ops-scheduler`의 일반 submit budget 집계가 `held_position REDUCE/EXIT SELL` 주문까지 함께 세고 있었다. 현재 설계는 held-position 위험축소 SELL을 일반 BUY/core submit budget과 분리하는 것인데, DB 집계가 이를 반영하지 못해 SELL이 누적될수록 일반 BUY lane이 하루 종일 `--no-allow-general-submit`로 고정되는 문제가 있었다.

## 원인
- `scripts/run_ops_scheduler.py`의 `_get_db_submit_count()`가 `trading.order_requests`만 보고 예산 소모 건수를 계산했다.
- 이 쿼리는 `held_position` / `reduce|exit` / `sell` 주문을 제외하지 않았다.
- 따라서 별도 lane으로 취급해야 하는 SELL 주문이 일반 submit budget을 모두 소진시켰다.

## 수정
- `_get_db_submit_count()`를 `trade_decisions`와 조인하도록 변경했다.
- 아래 3중 조건을 동시에 만족하는 주문은 일반 submit budget에서 제외한다.
  - `td.source_type = 'held_position'`
  - `td.decision_type IN ('reduce', 'exit')`
  - `td.side = 'sell'`

## 검증
- `tests/scripts/test_run_ops_scheduler.py`
  - `_get_db_submit_count()`가 제외 조건을 포함한 SQL을 사용하는지 회귀 테스트 추가
- 실행 결과
  - `pytest -q tests/scripts/test_run_ops_scheduler.py -k 'DbSubmitBudget or decision_submit_command_disable_general_submit'`
  - `6 passed`
  - `python3 -m py_compile scripts/run_ops_scheduler.py tests/scripts/test_run_ops_scheduler.py` 통과

## 기대 효과
- held-position SELL이 많아도 일반 BUY/core submit lane이 불필요하게 잠기지 않는다.
- `--no-allow-general-submit`는 실제 일반 submit budget 소진 상황에서만 활성화된다.
