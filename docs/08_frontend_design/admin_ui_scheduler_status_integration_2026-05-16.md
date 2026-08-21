# Admin UI Scheduler/Session 상태 통합 — 구현 보고서

**날짜**: 2026-05-16  
**프로젝트**: Admin UI Scheduler Status Integration  
**이전 작업**: Scheduler Naming Canonicalization (`near_real` → `ops_scheduler`)  

---

## 1. 목적

기존 운영 대시보드(`OperationsDashboardView`)에 scheduler/session 상태 정보를 통합 노출하여 운영자가 별도 페이지 이동 없이 한눈에 시스템 상태를 파악할 수 있도록 합니다.

## 2. 사전 조사 결과 (Ask Mode)

| 항목 | 조사 결과 |
|------|----------|
| `MarketSessionEntity` | `checked_at`(TIMESTAMPTZ)이 heartbeat 역할 (별도 `last_heartbeat_at` 없음) |
| session API 파일 | 없음 → `routes/sessions.py` 신규 생성 결정 |
| Dashboard 패턴 | 6개 `StatusCard` + 3개 `DataTable`, `Promise.all` fetch, Tailwind CSS |
| 공통 컴포넌트 | `StatusCard`(healthy/warning/error/neutral), `StatusBadge`(success/warning/error/info/neutral), `Panel`, `WarningBanner` |
| `api.ts` | session 관련 TS 타입 없음 → 신규 추가 필요 |

## 3. 구현 범위

### 3.1 백엔드 API (Python/FastAPI)

| 파일 | 변경 | 설명 |
|------|------|------|
| `src/agent_trading/api/routes/sessions.py` | **신규** | `GET /market-sessions/latest` — 최신 session 상태 + `healthy`(checked_at < 120s) 필드, `GET /market-sessions/events/recent?limit=5` — 최근 session events |
| `src/agent_trading/api/schemas.py` | **수정** | `MarketSessionSummary`, `SessionEventSummary`, `SchedulerStatusResponse` Pydantic 모델 추가 |
| `src/agent_trading/api/routes/__init__.py` | **수정** | `from . import sessions` 추가 |
| `src/agent_trading/api/app.py` | **수정** | `sessions.router` 등록 (Phase 5c) |
| `src/agent_trading/api/deps.py` | **수정** | `get_db` async 의존성 추가 (postgres 모드 `asyncpg.Pool`) |

### 3.2 프런트엔드 (TypeScript/React)

| 파일 | 변경 | 설명 |
|------|------|------|
| `admin_ui/src/types/api.ts` | **수정** | `MarketSessionSummary`, `SessionEventSummary`, `SchedulerStatusResponse`, `SessionEventsResponse` 인터페이스 추가 |
| `admin_ui/src/components/OperationsDashboardView.tsx` | **수정** | Scheduler Status `StatusCard`, Fallback `WarningBanner`, Session Events `Panel` 통합 |

### 3.3 테스트

| 파일 | 결과 |
|------|------|
| `tests/api/test_sessions.py` | **5/5 통과** |

테스트 케이스:
1. `test_get_latest_session_no_data` — DB에 session 없을 때 `no_data` 응답
2. `test_get_latest_session_healthy` — 최근 heartbeat session → `healthy=true`
3. `test_get_latest_session_stale` — 120초 초과 heartbeat → `healthy=false`
4. `test_get_recent_events` — session events 조회
5. `test_get_recent_events_empty` — events 없을 때 빈 배열 응답

### 3.4 Docker 빌드

| 항목 | 결과 |
|------|------|
| `npm run build` | **성공** — 1,756개 모듈 트랜스파일, 414KB JS + 25KB CSS 번들 |

## 4. 대시보드 추가 요소

### 4.1 Scheduler Status StatusCard
- **위치**: 운영 대시보드 상단 StatusCard 그리드 (Ready 카드 다음)
- **value**: `Healthy` / `Stale` / `No Data`
- **status**: `healthy`(초록) / `warning`(노랑) / `error`(빨강)
- **subtitle**: `{market_phase} | {Trading/Non-Trading} | {source}`
- **heartbeat threshold**: `checked_at` 기준 120초

### 4.2 Fallback WarningBanner
- **조건**: `session.source === 'fallback'` (또는 `weekday_heuristic`)
- **메시지**: "Session provider가 fallback 모드로 동작 중입니다. KIS live-info 연결을 확인하세요."
- **variant**: `warning`

### 4.3 Session Events Panel
- **위치**: 기존 DataTable 섹션 하단
- **내용**: 최근 5건의 session 이벤트를 compact 테이블로 표시
- **컬럼**: Time(KST), Phase 변경 (StatusBadge), Source
- **Phase 색상**: OPEN=success, AFTER_HOURS=info, HALT=error, 나머지=warning

## 5. 데이터 흐름

```
OpsScheduler (10s heartbeat)
  → market_sessions.checked_at 업데이트
    → GET /market-sessions/latest
      → SchedulerStatusResponse (healthy 필드 계산)
        → Admin UI Dashboard
          → StatusCard 표시

SessionEvent 발생
  → session_events 테이블 INSERT
    → GET /market-sessions/events/recent?limit=5
      → SessionEventsResponse
        → Admin UI Dashboard
          → Session Events Panel 표시
```

## 6. 완료 조건 체크리스트

| # | 항목 | 상태 |
|---|------|------|
| 1 | 사전 조사 완료 | ✅ |
| 2 | 백엔드 routes/sessions.py 생성 및 등록 | ✅ |
| 3 | schemas.py Pydantic 모델 추가 | ✅ |
| 4 | api.ts TypeScript 인터페이스 추가 | ✅ |
| 5 | OperationsDashboardView.tsx Scheduler Status 패널 통합 | ✅ |
| 6 | Session event compact list 추가 | ✅ |
| 7 | Fallback 경고 표시 | ✅ |
| 8 | API 테스트 5/5 통과 | ✅ |
| 9 | Docker admin-ui 빌드 성공 | ✅ |

## 7. 미해결/차기 작업

| 우선순위 | 작업 | 설명 |
|---------|------|------|
| P3 | `KIS_LIVE_INFO_ENABLED=true` 전환 | `.env` 설정 변경 필요, 장 종료 후 E2E 검증 필요 |
| P4 | `source_type` DB persistence gap | 2,153건 NULL — source_type 미기재, 영향도 낮음 |
