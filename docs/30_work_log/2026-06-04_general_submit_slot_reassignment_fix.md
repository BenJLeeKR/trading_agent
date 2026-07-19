# 2026-06-04 일반 BUY submit slot 재할당 버그 수정

## 배경

2026-06-04 장중에 `BUY approve` 의사결정은 다수 생성됐지만 실제 `BUY order_request`는 0건이었다.  
DB와 로그를 확인한 결과, `core`/`market_overlay` BUY가 대부분 아래 사유로 종료됐다.

- `scheduler_gate / submit_budget_consumed_core`
- `scheduler_gate / submit_budget_consumed_market_overlay`

하지만 같은 날 `operations_day_runs.submit_count=0`이었고, 실제 생성된 주문도 `SELL`만 존재했다.  
즉 `일일 submit cap`이 정말 소진된 것이 아니라, decision loop 내부의 일반 submit slot 관리가 잘못된 상태였다.

## 원인

`scripts/run_decision_loop.py`에서 일반 submit 후보는 `_run_one_cycle()` 실행 **전**에 `submit_budget_consumed=True`로 선점하고 있었다.

이 구조에서는:

1. 같은 cycle의 첫 일반 BUY 후보가 submit slot을 먼저 잡는다.
2. 그 후보가 `missing_reference_price_for_market_buy`, `sizing_rejected` 등 **pre-submit 단계에서 실패**해도
3. 같은 cycle의 나머지 BUY 후보들은 모두 `submit_budget_consumed_*` 사유로 dry-run 처리된다.

즉 `실제 주문 제출이 한 번도 발생하지 않았는데도` 일반 BUY lane이 이미 소진된 것처럼 동작했다.

## 수정 내용

### 1. 일반 BUY submit lane 직렬화

`scripts/run_decision_loop.py`

- 일반/core/market_overlay submit 후보는 `_general_submit_lock` 안에서 평가하고 실행한다.
- 첫 후보가 **실제 submit**(`SUBMITTED`, `RECONCILE_REQUIRED`)에 도달했을 때만 `submit_budget_consumed=True`로 확정한다.
- 첫 후보가 pre-submit 단계에서 실패하면 lock 해제 후 같은 cycle의 다음 일반 BUY 후보가 submit 기회를 이어받는다.

### 2. 실행 helper 정리

중복 try/except를 줄이기 위해 `_execute_symbol_cycle()` nested helper를 추가했다.

## 기대 효과

- `첫 BUY 후보 실패 -> 같은 cycle 다음 BUY submit` 경로가 복구된다.
- `submit_budget_consumed_core/market_overlay`가 실제 submit 이후에만 발생한다.
- `operations_day_runs.submit_count=0`인데 BUY가 모두 dry-run 되는 현상을 제거한다.

## 검증

### 정적 검증

```bash
python3 -m py_compile scripts/run_decision_loop.py tests/scripts/test_run_decision_loop.py
```

### 회귀 테스트

```bash
pytest -q tests/scripts/test_run_decision_loop.py -k 'GeneralSubmitLane or HeldPositionSellBudget'
```

결과:

- `8 passed`

### 추가된 핵심 테스트

`tests/scripts/test_run_decision_loop.py`

- `test_run_loop_allows_next_general_submit_after_pre_submit_failure`
  - 첫 일반 BUY 후보가 `SIZING_REJECTED`로 실패
  - 다음 일반 BUY 후보가 실제 `submit=True`로 실행
  - 그 다음 후보만 `submit_budget_consumed_core`로 dry-run 되는지 검증

## 배포 메모

- 이 수정은 `ops-scheduler` 컨테이너에 반영되어야 실제 장중 decision loop에 적용된다.
- 다음 거래 cycle에서 `submit_budget_consumed_core/market_overlay` 로그 패턴이 줄고, 최소 일부 BUY가 실제 submit 경로로 진입하는지 확인이 필요하다.
