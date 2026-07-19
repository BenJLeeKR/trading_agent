# pre_snapshot_sync 요약 파싱 경고 제거

## 배경

`ops-scheduler`는 `pre_snapshot_sync` 실행 후 snapshot 요약을 파싱해서:

- `cash_synced`
- `positions_synced`
- `CASH_SYNC_ZERO`

같은 신호를 phase 로그에 반영하려고 한다.

그런데 실제로는 snapshot sync가 성공해도 아래 경고가 계속 남았다.

- `pre-market snapshot sync: could not parse sync summary from stdout`

## 원인

`run_ops_scheduler.py`의 `_parse_snapshot_sync_summary()`는
`CommandResult.stdout`만 파싱하고 있었다.

하지만 `run_snapshot_sync_loop.py`는 `logging.basicConfig()` 기반이라
구조화된 `sync-cycle ...` 라인이 **stderr**로 기록된다.

즉:

- snapshot sync 자체는 정상 동작
- 구조화 요약도 존재
- 다만 파서가 잘못된 스트림만 보고 있었음

## 수정 내용

`_parse_snapshot_sync_summary()`가:

- `stdout`
- `stderr`

둘을 합친 출력에서 `sync-cycle` 라인을 찾도록 변경했다.

이 방식의 장점:

- `run_snapshot_sync_loop.py` 출력 형식을 건드리지 않음
- 기존 로깅 구조 유지
- scheduler 파서만 현실에 맞게 수정

## 테스트

`tests/scripts/test_run_ops_scheduler.py`

- stderr에만 `sync-cycle ... cash=1 ...` 라인이 있는 `CommandResult`
- `_parse_snapshot_sync_summary()`가 정상 파싱하는지 검증

실행 결과:

- `pytest -q tests/scripts/test_run_ops_scheduler.py -k "snapshot_sync_summary or snapshot_command"`
- 결과: `1 passed`

추가로:

- `python3 -m py_compile scripts/run_ops_scheduler.py tests/scripts/test_run_ops_scheduler.py`
- 통과

## 기대 효과

이제 `pre_snapshot_sync`가 정상 완료되면:

- `ops-scheduler`가 snapshot summary를 실제로 읽을 수 있음
- 불필요한 `could not parse sync summary` 경고 제거
- cash/position 신호가 startup phase 로그에 더 정확히 반영됨
