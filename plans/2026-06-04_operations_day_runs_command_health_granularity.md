# 2026-06-04 operations_day_runs command health 세분화

## 목적

- `operations_day_runs.summary_json`가 마지막 command 몇 개의 요약만 담는 수준을 넘어서,
  command family별 누적 상태를 함께 저장하도록 보강한다.
- 날짜별 history를 조회할 때 다음을 한 row에서 읽을 수 있게 한다.
  - snapshot sync가 몇 번 돌았는지
  - fill sync 실패/timeout이 있었는지
  - decision loop가 최근 어떤 상태였는지
  - recovery batch timeout이 있었는지

## 구현 내용

### 1. command family aggregate 추가

- 파일: `scripts/run_ops_scheduler.py`
- 추가 helper:
  - `_command_family_stats()`

각 family에 대해 아래 필드를 계산한다.

- `count`
- `ok_count`
- `failed_count`
- `timed_out_count`
- `last_name`
- `last_ok`
- `last_returncode`
- `last_timed_out`
- `last_duration_seconds`
- `last_metrics` (snapshot/fill 계열만)

### 2. summary_json 구조 확장

`_build_operations_day_summary_json()`에 `command_health` 추가:

- `snapshot_sync`
- `fill_sync`
- `event_ingestion`
- `post_submit_sync`
- `decision_loop`
- `recovery_batch`

기존 top-level 요약 필드:

- `snapshot_sync`
- `fill_sync`
- `decision_loop`
- `recovery_batch`

는 그대로 유지해서 하위 호환성을 지킨다.

## 테스트

- 파일: `tests/scripts/test_run_ops_scheduler.py`
- 보강 검증:
  - `command_health.snapshot_sync.count == 1`
  - `command_health.snapshot_sync.last_metrics.total_positions_synced == 5`
  - `command_health.fill_sync.last_metrics.fills == 9`
  - `command_health.decision_loop.last_ok is True`
  - `command_health.recovery_batch.timed_out_count == 1`

## 검증 결과

- `pytest -q tests/scripts/test_run_ops_scheduler.py -k 'PersistOperationsDayRun or HeartbeatTask or PersistSessionState'`
  - `9 passed`
- `python3 -m py_compile scripts/run_ops_scheduler.py tests/scripts/test_run_ops_scheduler.py`
  - 통과
- `docker compose up -d --build ops-scheduler`
  - 반영 완료

## 운영 메모

- 재기동 직후에는 아직 command 실행 이력이 없으므로
  `operations_day_runs.summary_json["command_health"]`가 빈 dict일 수 있다.
- pre-market / intraday cycle이 실제로 돌면 family별 집계가 채워진다.

## 의미

이제 `operations_day_runs` history는 단순 상태 문자열이 아니라,
해당 날짜에 command family별로 실제 어떤 health를 보였는지까지 저장한다.

다음 단계의 readiness / intraday validation 해석도 이 집계를 더 직접 활용할 수 있다.
