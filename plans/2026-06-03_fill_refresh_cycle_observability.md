# 2026-06-03 fill-triggered snapshot refresh cycle observability

## 목적

- `2026-06-03_remaining_work_priority_map.md`의
  `fill 발생 후 snapshot refresh 자동화` 항목 중
  **실측 계측**을 보강한다.
- 이제는 refresh가 동작하는지 여부만이 아니라,
  한 sync cycle 안에서
  - 몇 건이 실제 refresh로 실행됐는지
  - 몇 건이 dedupe 되었는지
  - 완료 / degraded / failed 가 각각 몇 건인지
  - 소요시간이 어느 정도였는지
  를 로그 기준으로 바로 읽을 수 있어야 한다.

## 구현 내용

### 1. `SnapshotRefreshStats` 추가

- 파일: `scripts/run_post_submit_sync_loop.py`
- per-cycle 집계 필드:
  - `scheduled_count`
  - `deduped_count`
  - `completed_count`
  - `degraded_count`
  - `failed_count`
  - `total_elapsed_ms`
  - `max_elapsed_ms`

### 2. refresh callback 내부 계측

- `_build_refresh_callback()`가 closure 내부 stats를 유지
- callback 객체에 `._stats`로 노출
- 실제 refresh 수행 시:
  - elapsed ms 측정
  - complete / degraded / failed 분기별 카운트 누적
  - dedupe 발생 시 `deduped_count` 누적

### 3. cycle summary 로그 확장

- `_log_cycle_summary()`가 기존 `sync-cycle` 로그 뒤에
  추가로 `sync-cycle-refresh` 로그를 남긴다.

예시:

```text
sync-cycle-refresh scheduled=2 deduped=1 completed=1 degraded=1 failed=0 avg_elapsed_ms=175 max_elapsed_ms=250
```

## 검증

- `tests/scripts/test_run_post_submit_sync_loop.py`
  - refresh callback stats 집계
  - degraded 로그에 `elapsed_ms` 포함
  - `sync-cycle-refresh` 요약 로그 출력
- `tests/services/test_snapshot_sync.py`
  - 기존 orderable/risk_limit observability 회귀 유지

## 기대 효과

- 다음 거래일 장중 검증 시,
  fill 이후 snapshot refresh가
  실제로 몇 번 실행됐고 얼마나 느렸는지
  DB 없이도 로그만으로 빠르게 확인할 수 있다.
- 이후 필요하면 이 계측을 `fill-sync-runs`나 별도 run table로
  승격하는 기반으로 사용할 수 있다.
