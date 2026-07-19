# Market Sessions Reason Metadata Structuring

## 목적
- `market_sessions.reason_code`만으로는 휴장/특수세션 판정의 근거가 부족한 부분을 보완한다.
- `076`, `163`, fallback, combined 판정 경로에서 사용한 핵심 근거를 구조화해 저장한다.
- 운영 API에서 같은 날짜의 판정 결과를 볼 때, free-form `reason` 문자열 해석 없이 바로 근거를 읽을 수 있게 만든다.

## 변경 내용

### 1. DB 스키마 확장
- `trading.market_sessions.reason_metadata JSONB` 추가
- 마이그레이션:
  - `db/migrations/0034_add_market_sessions_reason_metadata.sql`

### 2. 세션 판정 구조화
- `SessionInfo.reason_metadata` 추가
- 다음 provider들이 구조화 근거를 채워서 반환
  - `KisHolidayProvider`
  - `FallbackSessionProvider`
  - `CombinedSessionProvider`

예시:
- `kis_holiday_api`
  - `provider`, `opnd_yn`, `bzdy_yn`, `tr_day_yn`
- `fallback`
  - `provider`, `weekday`, `weekday_label`, `is_weekend`
- `combined`
  - `provider`, `holiday_is_trading_day`, `holiday_reason_code`
  - `phase`, `mkop_cls_code`, `antc_mkop_cls_code`, `ws_connected`
- `combined_error`
  - `provider`, `step`, `error`

### 3. 저장 경로 확장
- `scripts/run_ops_scheduler.py`
  - `_persist_session_state()`가 `reason_metadata`까지 `market_sessions`에 저장
- repository 계층도 동일 반영
  - `src/agent_trading/repositories/postgres/market_sessions.py`
  - `src/agent_trading/repositories/memory.py`

### 4. API 노출
- `MarketSessionSummary.reason_metadata` 추가
- 아래 API가 `reason_metadata`를 함께 반환
  - `GET /market-sessions/latest`
  - `GET /market-sessions/by-date/{run_date}`
  - `GET /market-sessions/history`

## 검증
- `pytest -q tests/api/test_sessions.py tests/scripts/test_run_ops_scheduler.py -k 'session or PersistSessionState or HeartbeatTask'`
  - `44 passed`
- `python3 -m py_compile ...` 통과
- `make docker-migrate`
  - `0034_add_market_sessions_reason_metadata.sql` 적용 확인

## 기대 효과
- 임시공휴일, safe-mode, 076-only fallback, 163 open/close 판정을 문자열 파싱 없이 직접 추적 가능
- 이후 session history/운영 대시보드/장중 readiness의 설명력이 올라감
- 조기종료/특수세션 대응 규칙을 더 추가할 때도 JSON 필드에 근거를 축적할 수 있음
