# 2026-06-03 operations_day_runs 조회 API 1차 구현

## 목적

- 이미 저장되기 시작한 `trading.operations_day_runs`를 운영/대시보드가 읽을 수 있도록
  최소 조회 API를 먼저 제공한다.
- 이번 단계에서는 **latest 단일 row 조회**만 제공하고,
  이후 대시보드 연결과 summary 확장은 후속 단계로 둔다.

## 추가한 API

- `GET /market-sessions/operations-day/latest`

응답 성격:

- 가장 최근 `operations_day_runs` row 반환
- `last_heartbeat_at`이 있으면 이를 기준으로 freshness 계산
- heartbeat가 없으면 `updated_at` / `created_at` fallback
- 응답 shape는 기존 `GET /market-sessions/latest`와 유사하게
  - `status`
  - `data`
  - `healthy`
  - `stale_seconds`
  를 유지한다.

## 코드 변경

### 1. 스키마 추가

파일:

- [`src/agent_trading/api/schemas.py`](../src/agent_trading/api/schemas.py)

추가:

- `OperationsDayRunSummary`
- `OperationsDayStatusResponse`

핵심 필드:

- `run_date`
- `scheduler_status`
- `is_trading_day`
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

### 2. 라우트 추가

파일:

- [`src/agent_trading/api/routes/sessions.py`](../src/agent_trading/api/routes/sessions.py)

추가:

- `get_latest_operations_day_run()`

SQL:

- `trading.operations_day_runs`
- 정렬: `COALESCE(last_heartbeat_at, updated_at, created_at) DESC`
- `LIMIT 1`

freshness 규칙:

- 기준 시각이 없으면 stale
- 기준 시각이 있고 `STALE_THRESHOLD_SECONDS(120)` 미만이면 healthy

## 테스트

파일:

- [`tests/api/test_sessions.py`](../tests/api/test_sessions.py)

추가 케이스:

1. row 없음 → `status=no_data`
2. 최근 heartbeat 있음 → `healthy=True`
3. heartbeat 없음 + 오래된 updated_at → `healthy=False`

## 검증 결과

실행 명령:

```bash
pytest -q tests/api/test_sessions.py
python3 -m py_compile src/agent_trading/api/routes/sessions.py src/agent_trading/api/schemas.py tests/api/test_sessions.py
```

결과:

- `9 passed`
- `py_compile` 통과

## 운영 반영 메모

`api` 컨테이너는 소스가 bind-mount되지 않으므로,
이 라우트를 실제 서버에서 보려면 재빌드/재기동이 필요하다.

## 남은 작업

1. `operations_day_runs` API를 운영 대시보드/상태 카드에 연결
2. 필요시 `recent list` / `run_date filter` 조회 추가

## 후속 보강

- `summary_json` health 구조화는 별도 문서로 정리:
  - [`plans/2026-06-03_operations_day_runs_summary_json_health.md`](./2026-06-03_operations_day_runs_summary_json_health.md)

## 판정

- `operations_day_runs`는 이제 **저장 + 최신 조회**까지 연결됐다.
- 다음 단계는 운영 화면 연결이다.
