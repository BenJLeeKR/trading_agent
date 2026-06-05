# 2026-06-03 operations_day_runs summary_json health 구조화

## 목적

- `operations_day_runs`가 단순 phase/status row에 그치지 않고,
  scheduler가 최근에 실행한 핵심 task health를 바로 읽을 수 있도록 한다.
- 이후 대시보드나 운영 API가 별도 로그 파싱 없이
  `snapshot / fill sync / recovery` 상태를 즉시 표시할 수 있는 기반을 만든다.

## 변경 내용

파일:

- [`scripts/run_ops_scheduler.py`](../scripts/run_ops_scheduler.py)

추가/변경:

1. `_parse_fill_sync_summary()`
   - `fill-sync-cycle ...` 로그 라인에서
     - `accounts`
     - `succeeded`
     - `partial`
     - `failed`
     - `skipped`
     - `fills`
     - `skipped_fills`
     - `retries`
     - `retried_accounts`
     - `errors`
     를 추출

2. `_latest_command_result()`
   - 특정 task name 집합의 최신 `CommandResult` 선택

3. `_command_result_summary()`
   - `ok / returncode / timed_out / duration_seconds`
   형태로 JSON-safe summary 생성

4. `_build_operations_day_summary_json()`
   - `operations_day_runs.summary_json` payload를 구조화

구조 예시:

```json
{
  "command_results_count": 3,
  "ok_count": 2,
  "failed_count": 1,
  "timed_out_count": 1,
  "last_command_name": "eod_recovery_batch",
  "session_reason": "seeded",
  "snapshot_sync": {
    "name": "pre_snapshot_sync",
    "ok": true,
    "returncode": 0,
    "timed_out": false,
    "duration_seconds": 12.5,
    "metrics": {
      "total_accounts": 1,
      "succeeded": 1,
      "partial": 0,
      "failed": 0,
      "skipped": 0,
      "total_positions_synced": 5,
      "total_positions_skipped": 0,
      "total_cash_synced": 1,
      "errors": 0
    }
  },
  "fill_sync": {
    "name": "pre_fill_sync",
    "ok": true,
    "returncode": 0,
    "timed_out": false,
    "duration_seconds": 8.2,
    "metrics": {
      "total_accounts": 1,
      "succeeded": 1,
      "partial": 0,
      "failed": 0,
      "skipped": 0,
      "fills": 9,
      "skipped_fills": 0,
      "retries": 1,
      "retried_accounts": 1,
      "errors": 0
    }
  },
  "recovery_batch": {
    "name": "eod_recovery_batch",
    "ok": false,
    "returncode": 1,
    "timed_out": true,
    "duration_seconds": 30.0
  }
}
```

## heartbeat 경로 보강

기존 문제:

- `heartbeat` UPSERT/UPDATE는 `summary_json`을 갱신하지 않아
  DB row에 `"{}"`가 남을 수 있었다.

수정:

- `_heartbeat_task()`가 `operations_day_runs` 갱신 시
  `summary_json = _build_operations_day_summary_json(state)`를 같이 저장

의미:

- 실제 스케줄러가 task를 아직 수행하지 않았더라도
  최소한 구조화된 빈 summary shape가 유지된다.

## 테스트

파일:

- [`tests/scripts/test_run_ops_scheduler.py`](../tests/scripts/test_run_ops_scheduler.py)

추가 검증:

1. `TestParseFillSyncSummary`
   - `fill-sync-cycle` 라인 parsing 검증

2. `TestPersistOperationsDayRun`
   - `summary_json`에
     - `ok_count`
     - `failed_count`
     - `timed_out_count`
     - `snapshot_sync.metrics`
     - `fill_sync.metrics`
     - `recovery_batch`
     가 실제 포함되는지 확인

3. `TestHeartbeatTask`
   - `operations_day_runs` heartbeat update/upsert가
     `summary_json`까지 함께 쓰는지 검증

## 검증 결과

실행 명령:

```bash
pytest -q tests/scripts/test_run_ops_scheduler.py -k 'ParseFillSyncSummary or PersistOperationsDayRun or HeartbeatTask or PersistSessionState'
python3 -m py_compile scripts/run_ops_scheduler.py tests/scripts/test_run_ops_scheduler.py
```

결과:

- `10 passed`
- `py_compile` 통과

운영 확인:

```bash
docker compose restart ops-scheduler
docker compose exec -T app ... SELECT run_date, scheduler_status, summary_json ...
docker compose exec -T api ... GET /market-sessions/operations-day/latest
```

확인 결과:

- DB row `summary_json`이 `"{}"`가 아니라 구조화된 JSON으로 저장됨
- API 응답에서도 `summary_json`이 dict 형태로 노출됨

## 판정

- `operations_day_runs`는 이제
  - 저장
  - 최신 조회
  - task health 구조화
  까지 완료된 상태다.
- 다음 단계는 대시보드/상태 카드 연결이다.
