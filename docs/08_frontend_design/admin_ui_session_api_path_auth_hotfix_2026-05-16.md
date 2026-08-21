# Admin UI Session API 경로/인증 정합성 Hotfix 보고서

**작성일**: 2026-05-16  
**관련 Phase**: Phase 12  
**목적**: Operations DashboardView의 Session API 호출 경로 오류(`/api/` prefix) 수정 및 공통 API client 통합

---

## 1. Root Cause

[`OperationsDashboardView.tsx`](admin_ui/src/components/OperationsDashboardView.tsx:278)에서 Session 데이터를 가져오기 위해 `fetch('/api/market-sessions/latest')` 형태로 호출하면서 경로 앞에 `/api/` prefix가 붙어 **404 Not Found**가 발생했다.

다른 모든 API helper는 [`client.ts`](admin_ui/src/api/client.ts:45)의 내부 `request()` 함수를 통해 `/api/` 없이 올바른 경로를 사용하고 있었으나, Session API만 유일하게 raw `fetch()` 호출을 사용하면서 경로 정합성이 깨졌다.

```
❌ /api/market-sessions/latest   → 404 (wrong path)
✅ /market-sessions/latest       → 200 (correct path, requires Authorization)
```

---

## 2. 변경 내용

### 2.1 공통 API client 헬퍼 추가

[`admin_ui/src/api/client.ts`](admin_ui/src/api/client.ts:274)에 Session API 전용 헬퍼 2개를 추가했다.

| 헬퍼 | 라인 | 엔드포인트 |
|------|------|-----------|
| [`getLatestMarketSession()`](admin_ui/src/api/client.ts:276) | 276-278 | `GET /market-sessions/latest` |
| [`getRecentSessionEvents(limit)`](admin_ui/src/api/client.ts:280) | 280-282 | `GET /market-sessions/events/recent?limit=N` |

두 헬퍼 모두 기존 `request<T>()` 함수를 통해 Bearer 토큰을 자동으로 첨부하므로 인증 문제도 함께 해결된다.

```typescript
// admin_ui/src/api/client.ts:276
export async function getLatestMarketSession(): Promise<SchedulerStatusResponse> {
  return request<SchedulerStatusResponse>("/market-sessions/latest");
}

// admin_ui/src/api/client.ts:280
export async function getRecentSessionEvents(limit: number = 5): Promise<SessionEventsResponse> {
  return request<SessionEventsResponse>(`/market-sessions/events/recent?limit=${limit}`);
}
```

### 2.2 OperationsDashboardView 수정

[`OperationsDashboardView.tsx`](admin_ui/src/components/OperationsDashboardView.tsx)에서 raw `fetch()` 호출을 제거하고 공통 헬퍼로 대체했다.

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| Import | 없음 | [`getLatestMarketSession, getRecentSessionEvents`](admin_ui/src/components/OperationsDashboardView.tsx:23) from `../api/client` |
| Session fetch | `fetch('/api/market-sessions/latest')` | [`getLatestMarketSession()`](admin_ui/src/components/OperationsDashboardView.tsx:278) |
| Events fetch | `fetch('/api/market-sessions/events/recent?limit=5')` | [`getRecentSessionEvents(5)`](admin_ui/src/components/OperationsDashboardView.tsx:282) |

### 2.3 경로 정합화 상세

- **문제 경로**: `/api/market-sessions/latest` → `/api/` prefix가 backend FastAPI route와 불일치
- **수정 경로**: `/market-sessions/latest` — 다른 모든 API helper(`/clients`, `/orders`, `/health` 등)와 동일한 규칙 사용
- **인증**: `request<T>()` 함수가 자동으로 Bearer token을 `Authorization` 헤더에 첨부하므로 401 오류도 함께 해소

---

## 3. 테스트 결과

### 3.1 신규 테스트 스위트

[`schedulerStatus.test.ts`](admin_ui/src/__tests__/schedulerStatus.test.ts)에 9개 신규 테스트를 추가하여 총 25개 테스트로 확장되었다.

| 시나리오 | 테스트 영역 | 테스트 수 |
|----------|-----------|----------|
| **Scenario 1-6** | [`getSchedulerStatus()`](admin_ui/src/components/OperationsDashboardView.tsx:126) 로직 — No Data / Healthy / Stale / Error / Fallback / Mixed | 기존 16개 |
| **Scenario 7** | [`getLatestMarketSession()`](admin_ui/src/api/client.ts:276) helper | **신규 4개** |
| **Scenario 8** | [`getRecentSessionEvents()`](admin_ui/src/api/client.ts:280) helper | **신규 5개** |

신규 테스트 세부 내역:

- **Scenario 7** (`getLatestMarketSession()`):
  1. 정상 응답 — `/market-sessions/latest` 호출 및 `SchedulerStatusResponse` 반환 확인 ([라인 320](admin_ui/src/__tests__/schedulerStatus.test.ts:320))
  2. 500 에러 — `ApiResponseError` throw 확인 ([라인 331](admin_ui/src/__tests__/schedulerStatus.test.ts:331))
  3. 401 에러 — `UnauthorizedError` throw 확인 ([라인 339](admin_ui/src/__tests__/schedulerStatus.test.ts:339))
  4. Network 에러 — `Network error` throw 확인 ([라인 347](admin_ui/src/__tests__/schedulerStatus.test.ts:347))

- **Scenario 8** (`getRecentSessionEvents()`):
  1. 정상 응답 — `/market-sessions/events/recent?limit=5` 호출 확인 ([라인 364](admin_ui/src/__tests__/schedulerStatus.test.ts:364))
  2. 기본 limit=5 — 인자 없이 호출 시 기본값 적용 확인 ([라인 375](admin_ui/src/__tests__/schedulerStatus.test.ts:375))
  3. 500 에러 — `ApiResponseError` throw 확인 ([라인 384](admin_ui/src/__tests__/schedulerStatus.test.ts:384))
  4. Network 에러 — `Network error` throw 확인 ([라인 392](admin_ui/src/__tests__/schedulerStatus.test.ts:392))
  5. 사용자 지정 limit — `limit=10` 전달 시 정상 동작 확인 ([라인 400](admin_ui/src/__tests__/schedulerStatus.test.ts:400))

### 3.2 전체 테스트 결과

```
npm test → 13개 파일, 138개 테스트 전부 통과 ✅
```

---

## 4. Build 결과

```
npm run build → 성공 ✅
```

TypeScript 컴파일, Vite 번들링 모두 이상 없음.

---

## 5. 실제 API 확인 결과

| curl 명령 | 예상 | 실제 | 비고 |
|-----------|------|------|------|
| `curl localhost:8000/api/market-sessions/latest` | 404 | 404 ✅ | 잘못된 경로, 수정 전과 동일 |
| `curl localhost:8000/market-sessions/latest` | 200 | 200 ✅ | 올바른 경로, Authorization 필요 |
| `curl localhost:8000/market-sessions/events/recent?limit=5` | 200 | 200 ✅ | 정상 응답 |

- `/api/` prefix 경로는 backend FastAPI에 등록되어 있지 않으므로 404가 정상이다.
- 올바른 경로 `/market-sessions/latest`는 200 정상 응답을 반환한다 (Authorization 헤더 필요 — 프런트에서 `request()`가 자동 처리).
- `/market-sessions/events/recent?limit=5`도 200 정상 응답을 반환한다.

---

## 6. 변경 파일 요약

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| [`admin_ui/src/api/client.ts`](admin_ui/src/api/client.ts:274) | 추가 | `getLatestMarketSession()`, `getRecentSessionEvents()` 헬퍼 2개 추가 |
| [`admin_ui/src/components/OperationsDashboardView.tsx`](admin_ui/src/components/OperationsDashboardView.tsx:23) | 수정 | raw `fetch()` → 공통 helper 호출로 변경, import 추가 |
| [`admin_ui/src/__tests__/schedulerStatus.test.ts`](admin_ui/src/__tests__/schedulerStatus.test.ts:1) | 추가 | 9개 신규 테스트 포함 총 25개 테스트 |

---

## 7. 남은 Follow-up

- **Scheduler Status 카드 실제 렌더 확인** (선택): 영업일 장중에 Operations Dashboard를 열어 Scheduler Status 카드가 정상적으로 표시되는지 육안 확인 필요. 현재는 session data가 없는 비영업일/야간이므로 `미수집` (neutral) 상태가 정상.
- **모니터링**: 장중 Scheduler Status가 `정상` (healthy/green)으로 표시되는지 확인.

---

## 참고 링크

- [Session API 500 Hotfix 보고서](plans/session_api_500_hotfix_2026-05-16.md) — Phase 11 backend session API 수정 내역
- [`OperationsDashboardView.tsx` Scheduler Card logic](admin_ui/src/components/OperationsDashboardView.tsx:126) — `getSchedulerStatus()` 함수
- [`client.ts` request() wrapper](admin_ui/src/api/client.ts:45) — 공통 fetch wrapper
