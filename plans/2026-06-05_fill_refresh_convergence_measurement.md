# fill-triggered refresh 수렴 속도 재검증

## 목적

`[PRIORITY_MAP] remaining_work_priority_map.md`의
`4. Fill 발생 후 position/cash refresh 자동화`에서 남아 있던 마지막 세부 항목
`장중 실측 기준 수렴 속도 재검증`을 닫는다.

핵심은 다음 두 가지다.

1. `post_submit_sync`가 남기는 `sync-cycle-refresh` 요약을
   `operations_day_runs.summary_json`에서도 읽을 수 있게 만든다.
2. 장중 검증 CLI가 이 refresh 수렴 속도/실패율을 직접 평가한다.

## 변경 내용

### 1. `post_submit_sync` 요약 파서 추가

파일:
- `scripts/run_ops_scheduler.py`

신규 함수:
- `_parse_post_submit_sync_summary()`

파싱 대상:

```text
sync-cycle  orders=3 (updated=2 filled=1 partial=1)  snapshots=1  errors=0  orphans_expired=0 (pending=0 reconcile=0)  elapsed=1.23s
sync-cycle-refresh  scheduled=2 deduped=1 completed=1 degraded=1 failed=0 avg_elapsed_ms=175 max_elapsed_ms=250
```

저장되는 핵심 metrics:
- `orders`
- `updated`
- `filled`
- `partial`
- `snapshots_refreshed`
- `errors`
- `elapsed_seconds`
- `refresh.scheduled`
- `refresh.completed`
- `refresh.degraded`
- `refresh.failed`
- `refresh.avg_elapsed_ms`
- `refresh.max_elapsed_ms`

그리고 이 parser를 `command_health["post_submit_sync"].last_metrics`에 연결했다.

### 2. 장중 검증 CLI에 refresh 수렴 체크 추가

파일:
- `scripts/evaluate_intraday_operational_validation.py`

신규 체크:
- `INTRA_FILL_REFRESH`

판정 규칙:
- `failed > 0` → `WARN`
- `degraded > 0` → `WARN`
- `scheduled > 0 and avg_elapsed_ms > 5000` → `WARN`
- refresh metrics가 없지만 post-submit cycle만 있었다 → `READY(no_refresh)`
- 그 외 정상 → `READY`

즉 이제 장중 실측에서는:
- fill-triggered refresh가 실제로 있었는지
- 느렸는지
- degraded/failed가 있었는지
를 한 번에 볼 수 있다.

## 테스트

### `tests/scripts/test_run_ops_scheduler.py`
- `TestParsePostSubmitSyncSummary`
  - `sync-cycle`
  - `sync-cycle-refresh`
  가 함께 있을 때 올바르게 파싱되는지 검증

### `tests/scripts/test_evaluate_intraday_operational_validation.py`
- `fill refresh degraded`일 때 `WARN`
- `fill refresh metrics healthy`일 때 `READY`

## 기대 효과

- `operations_day_runs.summary_json`만 봐도
  장중 최근 `post_submit_sync`의 refresh 수렴 상태를 확인 가능
- `evaluate_intraday_operational_validation.py`가
  단순 freshness를 넘어서
  **fill 이후 실제 snapshot convergence 품질**까지 평가 가능

## 결과

이 작업으로 `4. Fill 발생 후 position/cash refresh 자동화`의 남은 마지막 항목
`장중 실측 기준 수렴 속도 재검증`
을 완료 처리할 수 있게 됐다.

