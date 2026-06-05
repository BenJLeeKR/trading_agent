# 2026-06-02 scheduler gate dry-run reason 영속화

## 배경
지금까지 `오늘 BUY 차단` 집계는 일부 구간에서 로그/추론에 의존했다. 특히 core/market_overlay BUY가 scheduler gate에서 dry-run으로 내려간 경우, DB에는 명시적 stop reason이 남지 않아 `no attempt` 패턴으로 간접 분류해야 했다.

## 목표
- `run_decision_loop`가 scheduler gate 때문에 dry-run된 BUY에 대해 명시적인 `stop_reason`을 `execution_attempts`에 저장
- 이후 `GET /orders/buy-block-summary`는 해당 stop reason을 우선 사용
- 미래 데이터에서는 로그 추론 없이 DB만으로 차단 사유 집계 가능

## 추가된 dry-run reason
- `general_submit_disabled_core`
- `general_submit_disabled_market_overlay`
- `submit_budget_consumed_core`
- `submit_budget_consumed_market_overlay`
- 보조적으로 held-position SELL lane용
  - `held_position_sell_cycle_cap`
  - `held_position_sell_symbol_duplicate`

## 구현
- `scripts/run_decision_loop.py`
  - `_infer_symbol_dry_run_reason()` 추가
  - dry-run branch에서 `trade_decision_id`가 있으면 `ExecutionAttemptEntity`를 생성
    - `status='non_trade'`
    - `stop_phase='scheduler_gate'`
    - `stop_reason=<dry_run_reason>`
  - dry-run JSON 결과에도 `dry_run_reason` 포함
- `src/agent_trading/api/routes/orders.py`
  - `buy-block-summary` 집계가 위 stop reason을 우선 사용하도록 보강
  - 기존 no-attempt fallback은 과거 데이터 호환용으로 유지

## 검증
- `pytest -q tests/scripts/test_run_decision_loop.py -k 'infer_core_dry_run_reason or infer_market_overlay_dry_run_reason or core_symbol_blocked_when_general_submit_disabled'` → 3 passed
- `pytest -q tests/api/test_inspection.py -k 'buy_block_summary or daily_summary'` → 2 passed
- `python3 -m py_compile scripts/run_decision_loop.py src/agent_trading/api/routes/orders.py` 통과

## 기대 효과
- 내일부터는 core/overlay BUY dry-run 차단이 DB에 명확한 원인 코드로 남음
- `buy-block-summary`가 추론 대신 사실 기반 stop reason을 사용
- 이후 대시보드 drill-down/리포트화가 쉬워짐
