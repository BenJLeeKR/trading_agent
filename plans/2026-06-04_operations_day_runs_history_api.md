# 2026-06-04 operations_day_runs history API 추가

## 배경

`operations_day_runs`는

- latest 저장
- latest 조회 API
- `summary_json` health 구조화
- 운영 대시보드 `Scheduler Status` 카드 연결

까지는 완료되어 있었다.

하지만 운영자가 특정 날짜의 scheduler 운영 상태를 다시 확인하거나,
여러 날짜의 운영 흐름을 비교하려면 여전히 DB를 직접 조회해야 했다.

`plans/2026-06-03_remaining_work_priority_map.md` 기준으로도
`operations_day_runs`의 남은 세부 작업은 `recent list / run_date filter 조회 추가`였다.

## 목표

`market_sessions` 계열 API 안에서 `operations_day_runs`도 다음 두 경로로 조회 가능하게 한다.

1. 특정 날짜 단건 조회
2. 날짜 범위 history 조회

## 구현 내용

### 1. 응답 스키마 추가

파일: [`src/agent_trading/api/schemas.py`](../src/agent_trading/api/schemas.py)

추가 모델:

- `OperationsDayDetailResponse`
- `OperationsDayHistoryResponse`

기존 `OperationsDayRunSummary`를 재사용해 latest / by-date / history가 같은 shape로 보이게 했다.

### 2. API route 추가

파일: [`src/agent_trading/api/routes/sessions.py`](../src/agent_trading/api/routes/sessions.py)

추가 endpoint:

- `GET /market-sessions/operations-day/by-date/{run_date}`
- `GET /market-sessions/operations-day/history?date_from=&date_to=&limit=`

동작:

- `by-date`
  - 해당 `run_date` row가 있으면 `status="ok"`
  - 없으면 `status="no_data"`
- `history`
  - `run_date DESC`
  - `date_from`, `date_to`, `limit` 지원

`summary_json`은 기존 `_coerce_summary_json()`을 재사용하여 dict로 정규화한다.

## 테스트

파일: [`tests/api/test_sessions.py`](../tests/api/test_sessions.py)

추가 검증:

1. `operations-day/by-date` row 존재
2. `operations-day/by-date` no_data
3. `operations-day/history` 날짜 필터/limit 전달

실행:

```bash
pytest -q tests/api/test_sessions.py
python3 -m py_compile \
  src/agent_trading/api/routes/sessions.py \
  src/agent_trading/api/schemas.py \
  tests/api/test_sessions.py
```

결과:

- `16 passed`
- `py_compile` 통과

## 배포/실서버 확인

실행:

```bash
docker compose up -d --build api
docker compose ps api
```

결과:

- `api` 컨테이너 `healthy`

실 endpoint 확인은 현재 셸에 `INSPECTION_API_TOKEN`이 없어 `401 Missing Authorization header`까지만 확인했다.

즉:

- 라우트 로딩/서버 기동은 정상
- 인증이 필요한 실제 inspection endpoint 특성상, 토큰 없는 로컬 호출은 401이 정상

## 효과

이제 `operations_day_runs`도 다음 흐름이 가능해졌다.

1. latest 상태 조회
2. 특정 날짜 재검증
3. 날짜 범위 이력 비교

따라서 이후에는:

- 비거래일/거래일 phase 전이 비교
- 특정 날짜의 submit_count / cycles / summary_json 비교
- readiness / 장중 검증 결과와의 대조

를 더 쉽게 진행할 수 있다.
