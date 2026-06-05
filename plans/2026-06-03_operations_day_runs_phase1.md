# 2026-06-03 operations_day_runs 1차 구현

## 목적

- `ops-scheduler`의 운영일 상태를 메모리/로그 추정이 아니라 DB row로 남긴다.
- 이후 운영 API와 대시보드가 `market_sessions`만 보지 않고,
  실제 스케줄러 진행 상태를 함께 읽을 수 있는 기반을 만든다.

## 이번 작업 범위

### 1. DB 스키마 추가

신규 마이그레이션:

- [`db/migrations/0032_add_operations_day_runs.sql`](../db/migrations/0032_add_operations_day_runs.sql)

추가 테이블:

- `trading.operations_day_runs`

주요 컬럼:

- `run_date`
- `scheduler_status`
- `is_trading_day`
- `session_source`
- `market_phase`
- `pre_market_done`
- `end_of_day_done`
- `after_hours_mode`
- `recovery_batch_done`
- `submit_count`
- `held_position_sell_submit_count`
- `cycles`
- `last_phase_change_at`
- `last_heartbeat_at`
- `summary_json`

## 코드 변경

### 1. 스케줄러 상태 파생 함수

파일:

- [`scripts/run_ops_scheduler.py`](../scripts/run_ops_scheduler.py)

추가:

- `_derive_operations_day_status()`

상태 매핑:

- `after_hours_mode=True` → `after_hours`
- `end_of_day_done=True` → `end_of_day_complete`
- `pre_market_done=True` → `intraday`
- 그 외 → `pre_market`

### 2. session state 저장 시 operations_day_runs 동시 저장

변경:

- `_persist_session_state()` 종료 시 `_persist_operations_day_run()` 호출

의미:

- `market_sessions` UPSERT와 같은 타이밍에 운영일 요약 row도 같이 갱신된다.

### 3. phase 전이/주기 task 후 운영일 row 갱신

추가 반영 함수:

- `_run_pre_market(..., dsn=...)`
- `_run_intraday_due_tasks(..., dsn=...)`
- `_run_end_of_day(..., dsn=...)`
- `_run_after_hours_snapshot_cycle(..., dsn=...)`

의미:

- pre-market 완료
- intraday 주기 실행
- end-of-day 전이
- after-hours cycle

각 시점에 `operations_day_runs`가 최신 state로 업데이트된다.

### 4. heartbeat 이중 기록

변경:

- `_heartbeat_task()`가 이제
  - `trading.market_sessions`
  - `trading.operations_day_runs`
  둘 다 heartbeat를 갱신한다.

세부 동작:

- `session_db_id`가 있으면 `UPDATE`
- 없으면 `run_date` 기준 `UPSERT`

## 테스트

파일:

- [`tests/scripts/test_run_ops_scheduler.py`](../tests/scripts/test_run_ops_scheduler.py)

추가/보강:

1. `TestPersistOperationsDayRun`
   - `dsn=None` no-op
   - `operations_day_runs` UPSERT SQL 검증
2. `TestHeartbeatTask`
   - `market_sessions` + `operations_day_runs` 동시 heartbeat 검증
   - session 미존재 시 두 테이블 모두 UPSERT 검증
3. 기존 session-state 관련 테스트와 함께 회귀 확인

## 검증 결과

실행 명령:

```bash
pytest -q tests/scripts/test_run_ops_scheduler.py -k 'PersistOperationsDayRun or HeartbeatTask or PersistSessionState'
python3 -m py_compile scripts/run_ops_scheduler.py tests/scripts/test_run_ops_scheduler.py
```

결과:

- `9 passed`
- `py_compile` 통과

## 현재 상태

이번 1차 구현으로 완료된 것:

- 운영일 상태 저장용 테이블 정의
- scheduler state → DB row 반영
- heartbeat 연동
- phase/task 진행 상태 기본 저장

아직 남은 것:

1. 운영 대시보드/상태 카드 연결
2. `summary_json`에 recovery/fill-sync/snapshot health를 더 구조적으로 넣는 2차 확장
3. 필요시 `recent list` / `run_date filter` 조회 추가

## 판정

- `operations_day_runs`는 이제 **백엔드 저장 기반의 1차 토대**가 준비된 상태다.
- 다음 단계는 **운영 화면 연결**이다.
