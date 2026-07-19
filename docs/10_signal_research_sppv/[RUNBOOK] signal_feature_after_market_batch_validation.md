# signal feature 장후 배치 운영 검증 절차

## 목적

- 장후 `signal feature` 배치가
  `freeze -> fetch -> persist -> tail-retry` 흐름으로 정상 종료했는지
  운영 기준으로 빠르게 판정한다.
- authoritative source를
  `file artifact`가 아니라
  `freeze/run-state/snapshot DB row` 기준으로 검증한다.
- `operations_day_runs.summary_json`,
  `signal_feature_batch_runs`,
  `signal_feature_snapshots`
  세 저장소가 서로 일관되는지 대조한다.
- `scheduler 성공`과 `실제 snapshot 적재 성공`을 구분한다.

## 적용 범위

- 대상 배치 시각: `20:10 KST`
- snapshot anchor 시각: 해당 영업일 `20:00 KST`
- 기준 거래일: `run_date`

## 정상 판정 기준

아래 조건을 모두 만족하면 정상으로 본다.

1. `operations_day_runs.summary_json.signal_feature_input.ok = true`
2. `operations_day_runs.summary_json.signal_feature_batch.ok = true`
3. `signal_feature_input.metrics.target_count`
   와 `signal_feature_batch_runs.target_count`가 일치한다.
4. `signal_feature_input.metrics.fetch_success_count`
   와 `signal_feature_batch_runs.fetch_success_count`가 일치한다.
5. `signal_feature_batch_runs.persist_success_count`
   와 해당 거래일 `signal_feature_snapshots` row 수가 일치한다.
6. `signal_feature_batch_runs.final_missing_count = 0`
7. 해당 거래일 row의 `snapshot_at`이 모두 `20:00 KST`다.

## 1차 확인: operations_day_runs 요약

### 확인 SQL

```sql
SELECT
    run_date,
    summary_json->'signal_feature_input' AS signal_feature_input,
    summary_json->'signal_feature_batch' AS signal_feature_batch
FROM trading.operations_day_runs
WHERE run_date = DATE '2026-06-23';
```

### 확인 포인트

- `signal_feature_input.metrics.target_count`
- `signal_feature_input.metrics.fetch_success_count`
- `signal_feature_input.metrics.fetch_error_count`
- `signal_feature_input.metrics.universe_freeze_run_id`
- `signal_feature_batch.ok`
- `signal_feature_batch.returncode`
- `signal_feature_batch.timed_out`

### 해석

- `signal_feature_input`가 비어 있으면
  input 생성 단계가 실행되지 않았거나 요약 적재가 누락된 것이다.
- `signal_feature_batch`가 비어 있으면
  persist 단계가 실행되지 않았거나 로그 파싱이 실패한 것이다.
- `fetch_error_count > 0`이면
  tail-retry 또는 수동 재실행 검토가 필요하다.

## 2차 확인: batch run 메타데이터

### 확인 SQL

```sql
SELECT
    business_date,
    universe_freeze_run_id,
    trigger_type,
    target_count,
    fetch_success_count,
    fetch_error_count,
    persist_success_count,
    persist_error_count,
    skipped_count,
    final_missing_count,
    status
FROM trading.signal_feature_batch_runs
WHERE business_date = DATE '2026-06-23'
ORDER BY started_at DESC;
```

### 확인 포인트

- `universe_freeze_run_id` 존재 여부
- `target_count`
- `fetch_success_count`
- `persist_success_count`
- `final_missing_count`
- `status`

### 해석

- `status=completed` 이고 `final_missing_count=0`이면
  실행 단위 기준 정상이다.
- `status=completed_with_errors` 이면
  종목 단위 누락이 남아 있다.
- `universe_freeze_run_id`가 비어 있으면
  freeze 재사용/audit 경로가 끊긴 것이다.

## 3차 확인: 종목 단위 실패 잔존 여부

### 확인 SQL

```sql
SELECT
    status,
    count(*) AS row_count
FROM trading.signal_feature_batch_run_items
WHERE signal_feature_batch_run_id = '<배치 run id>'
GROUP BY status
ORDER BY status;
```

### 실패 종목 샘플 확인 SQL

```sql
SELECT
    symbol,
    market_code,
    status,
    error_code,
    error_message
FROM trading.signal_feature_batch_run_items
WHERE signal_feature_batch_run_id = '<배치 run id>'
  AND status IN ('error', 'fetch_error', 'skipped_instrument_not_found')
ORDER BY symbol
LIMIT 50;
```

### 해석

- `persisted`만 존재하면 정상이다.
- `fetch_error`가 남아 있으면
  live 시세/일봉 fetch 실패가 tail-retry 후에도 해소되지 않은 상태다.
- `error`가 남아 있으면
  fetch 이후 계산 또는 저장 단계 실패다.
- `skipped_instrument_not_found`가 있으면
  universe와 instrument master 정합성부터 다시 봐야 한다.

## 4차 확인: snapshot 적재 건수 대조

### 확인 SQL

```sql
SELECT
    count(*) AS snapshot_count
FROM trading.signal_feature_snapshots
WHERE snapshot_at = TIMESTAMPTZ '2026-06-23 20:00:00+09';
```

### 세부 확인 SQL

```sql
SELECT
    min(snapshot_at AT TIME ZONE 'Asia/Seoul') AS min_kst,
    max(snapshot_at AT TIME ZONE 'Asia/Seoul') AS max_kst,
    count(*) AS row_count
FROM trading.signal_feature_snapshots
WHERE snapshot_at = TIMESTAMPTZ '2026-06-23 20:00:00+09';
```

### 해석

- `snapshot_count = persist_success_count` 이어야 한다.
- `min_kst = max_kst = 2026-06-23 20:00:00` 이어야 한다.
- 다른 시각이 섞이면 anchor 저장 로직 회귀다.

## 5차 확인: 중복 적재 여부

### 확인 SQL

```sql
SELECT count(*) AS dup_groups
FROM (
    SELECT 1
    FROM trading.signal_feature_snapshots
    GROUP BY instrument_id, timeframe, snapshot_at, feature_set_version
    HAVING count(*) > 1
) t;
```

### 해석

- `dup_groups = 0` 이어야 한다.
- 0이 아니면 natural key upsert 또는 과거 백필 경로를 점검해야 한다.

## 권장 판정 순서

1. `operations_day_runs.summary_json` 확인
2. `signal_feature_batch_runs` 확인
3. 실패 시 `signal_feature_batch_run_items` 확인
4. 최종적으로 `signal_feature_snapshots` 건수와 anchor 시각 확인

## authoritative source 판정 원칙

- 대상 종목 집합:
  `universe_freeze_runs` / `universe_freeze_run_items`
- 배치 실행 성공/실패 메타데이터:
  `signal_feature_batch_runs` / `signal_feature_batch_run_items`
- 최종 feature payload:
  `signal_feature_snapshots`
- 입력 JSON:
  transport / tail-retry / 장애 분석용 artifact

따라서 운영 검증 시
`input 파일이 남아 있느냐`보다
`DB freeze/run-state/snapshot이 서로 일관되느냐`를 우선 본다.

## 2026-06-23 실측 예시

- `signal_feature_input.target_count = 99`
- `signal_feature_input.fetch_success_count = 99`
- `signal_feature_input.fetch_error_count = 0`
- `signal_feature_batch_runs.persist_success_count = 99`
- `signal_feature_batch_runs.final_missing_count = 0`
- `signal_feature_snapshots@2026-06-23 20:00:00+09 = 99건`

즉, 이 날짜는 장후 배치가 정상 종료한 케이스로 볼 수 있다.

## 장애 판정 기준

- `target_count != fetch_success_count + fetch_error_count`
  - input 요약 또는 retry 누적 집계 이상
- `persist_success_count < fetch_success_count`
  - 계산/저장 단계 누락 존재
- `final_missing_count > 0`
  - 수동 재실행 검토 필요
- `snapshot_count != persist_success_count`
  - batch run 기록과 실제 snapshot 저장 불일치
- `dup_groups > 0`
  - idempotent re-run 경로 회귀

## 후속 조치 기준

- `fetch_error` 위주면
  live 시세/일봉 API rate limit / 5xx / timeout 로그 확인
- `error` 위주면
  저장 precision, schema drift, repository exception 확인
- `skipped_instrument_not_found`가 있으면
  instrument master 배치 및 canonical mapping 점검
