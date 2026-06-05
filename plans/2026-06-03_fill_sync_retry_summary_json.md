# Fill Sync Retry 관측값 summary_json 저장

## 목표

`VTTC0081R` 체결내역 sync에서 retry가 실제로 발생했는지 운영 API에서 바로 확인할 수 있도록, run summary에 retry 집계값을 저장한다.

## 변경 내용

### 1. account/batch result에 retry 집계 필드 추가

- 파일: `src/agent_trading/services/fill_history_sync.py`
- `AccountFillSyncResult`
  - `retried_days`
  - `retry_count`
- `FillBatchSyncResult`
  - `retried_accounts`
  - `retried_days`
  - `total_retries`

### 2. per-day → account → batch 합산

- `sync_fill_history_for_account()`
  - VTTC0081R retry 발생 시 `retried_days=1`, `retry_count=1`
- `sync_all_fill_history()`
  - 각 day 결과의 retry 값을 account-level result에 누적
  - account-level retry가 있으면 batch-level 집계도 증가

### 3. FillSyncRun.summary_json 자동 채움

- `build_fill_sync_run_entity()`
  - 별도 `summary_json`이 없으면 자동으로 아래 구조 저장

```json
{
  "retried_accounts": 1,
  "retried_days": 1,
  "total_retries": 1
}
```

### 4. 실행 로그 보강

- 파일: `scripts/run_fill_sync_loop.py`
- cycle summary log에 아래 필드 추가
  - `retries`
  - `retried_accounts`

## 테스트

- `tests/services/test_fill_history_sync.py`
  - inquiry budget exhaustion 후 retry 성공 검증
  - `build_fill_sync_run_entity()`의 `summary_json` 자동 채움 검증

실행 결과:

- `pytest -q tests/services/test_fill_history_sync.py`
- 결과: `3 passed`

## 실제 실행 검증

수동 실행:

```bash
docker compose exec -T app python3 scripts/run_fill_sync_loop.py --once --after-hours
```

실제 로그:

- `VTTC0081R budget retry: order_day=2026-06-02 bucket=inquiry attempt=2/2`
- `fill-sync-cycle ... retries=1 retried_accounts=1 errors=0`

API 확인:

```bash
curl -H 'Authorization: Bearer dev-token-123' 'http://localhost:8000/fill-sync-runs?limit=1'
```

최신 run의 `summary_json`:

```json
{
  "retried_accounts": 1,
  "retried_days": 1,
  "total_retries": 1
}
```

## 기대 효과

1. fill sync가 조용히 retry 복구된 건인지 즉시 식별 가능
2. `failed -> completed`로만 보이던 배치의 내부 품질을 더 잘 파악 가능
3. 이후 운영 화면에서 retry badge/통계 추가 시 별도 백엔드 작업 없이 바로 활용 가능

## 다음 권장 작업

1. `/fill-sync-runs/summary`에 최근 retry 정보 추가
2. 체결내역 화면에서 마지막 sync의 retry 여부를 뱃지로 표시
3. retry가 특정 일자에 반복될 때 alert threshold 추가
