# 2026-06-04 장중 decision loop summary 즉시 저장 보강

## 배경

- `[PRIORITY_MAP] remaining_work_priority_map.md`의 `3. 다음 거래일 장중 실운영 검증` 항목에는
  다음 잔여 작업이 남아 있었다.
  - 장중 첫 `decision_submit_gate` 이후 `decision_loop` summary 자동 적재 재확인
- 기존 구현은 `_run_intraday_due_tasks()`의 맨 마지막에서만
  `operations_day_runs`를 저장했다.
- 따라서 같은 cycle 안에서
  - `decision_submit_gate`
  - `post_submit_sync`
  - `fill_sync`
  순으로 실행될 때, decision loop 결과가 DB에 반영되기까지 후속 task 완료를 기다려야 했다.
- 이 구조는 장중 첫 submit cycle 직후 상태를 운영자가 보려는 경우,
  summary 노출이 지연되거나 중간 실패 시 누락처럼 보일 여지가 있었다.

## 목표

- `decision_submit_gate` 또는 `decision_dry_run`이 끝난 직후,
  그 결과를 `operations_day_runs.summary_json.decision_loop`에 바로 반영되게 한다.
- 후속 `post_submit_sync` / `fill_sync`가 같은 cycle에서 계속 돌더라도,
  decision loop summary의 최초 적재는 지연되지 않게 한다.

## 적용 내용

### 1. decision loop 완료 직후 즉시 persist

파일:
- `scripts/run_ops_scheduler.py`

변경:
- `_run_intraday_due_tasks()` 내부에서
  `decision_submit_gate` / `decision_dry_run` 실행 완료 후
  `await _persist_operations_day_run(state, dsn)`를 즉시 호출하도록 추가

의도:
- 장중 첫 submit gate 결과가 후속 task보다 먼저 `operations_day_runs`에 남는다.

### 2. 회귀 테스트 추가

파일:
- `tests/scripts/test_run_ops_scheduler.py`

추가 테스트:
- `test_persists_immediately_after_decision_loop_before_followups`

검증 포인트:
- 첫 persist 시점의 `command_results`가 `["decision_submit_gate"]`인지
- 최종 persist 시점에는
  `["decision_submit_gate", "post_submit_sync", "fill_sync"]`
  순으로 누적되는지

즉, decision loop 결과가 후속 task보다 먼저 저장되는지 확인한다.

## 검증 결과

실행:

```bash
pytest -q tests/scripts/test_run_ops_scheduler.py -k 'PersistOperationsDayRun or IntradayDecisionLoopPersistence or HeartbeatTask or PersistSessionState'
python3 -m py_compile scripts/run_ops_scheduler.py tests/scripts/test_run_ops_scheduler.py
```

결과:
- `10 passed`
- `py_compile` 통과

## 영향

- `operations_day_runs.summary_json.decision_loop`가 장중 첫 submit cycle 직후 더 빨리 관측된다.
- `evaluate_intraday_operational_validation.py`와 같은 운영 검증 CLI가
  같은 cycle 내 후속 task 완료를 기다리지 않고도 decision loop 최신 상태를 읽을 수 있다.
- `3. 다음 거래일 장중 실운영 검증` 항목의 남은 자동 적재 보강 작업을 닫는 근거가 된다.
