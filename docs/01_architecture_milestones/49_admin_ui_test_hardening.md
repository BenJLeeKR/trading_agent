# Plan 49 — Admin UI Smoke / Component Test Hardening

## Revision History

| Date | Version | 변경 내용 |
|------|---------|-----------|
| 2026-05-05 | v1.0 | 최초 작성 |
| 2026-05-05 | v1.1 | P0 시나리오 1개 추가 (기존 token → protected 진입). OrderDetail을 P1 후보로 문서에 명시. URL+method 분기 명확화 |

## 목차

1. [Why Now](#1-why-now)
2. [테스트 스택](#2-테스트-스택)
3. [Mock 전략](#3-mock-전략)
4. [테스트 구조](#4-테스트-구조)
5. [변경 파일 목록](#5-변경-파일-목록)
6. [실행 순서](#6-실행-순서)
7. [검증 포인트](#7-검증-포인트)
8. [Risk Assessment](#8-risk-assessment)

---

## 1. Why Now

Admin UI Phase 1이 구현되었으나, **자동화된 프론트엔드 테스트가 전혀 없는 상태**다.

- **백엔드**는 68개의 pytest가 회귀 방지 역할을 함
- **프론트엔드**는 빌드 시 TypeScript 컴파일만 검증, 런타임 동작은 미검증
- Phase 2에서 write UI, 설정 관리 등이 추가되기 전에 최소한의 smoke/component 테스트를 먼저 확보해야 회귀 비용이 낮음

**목표**: "Admin UI가 앞으로 커져도 최소 동작이 깨지지 않게 만드는 것"

이번 범위:
- **Component/smoke 수준** — full browser E2E 아님
- **Backend 미변경** — frontend 회귀 방지망 구축에 집중
- **Playwright/Cypress 도입 안 함**

---

## 2. 테스트 스택

### 선택: **Vitest + React Testing Library + jsdom**

| 도구 | 버전 | 목적 |
|------|------|------|
| [`vitest`](https://vitest.dev/) | ^3.1 | Vite 네이티브 통합 테스트 러너. Vite config 재사용, 빠른 HMR, watch mode |
| [`@testing-library/react`](https://testing-library.com/docs/react-testing-library/intro) | ^16.3 | React 컴포넌트 렌더링/쿼리. DOM 기반, 구현 세부사항보다 사용자 동작 검증 |
| [`@testing-library/jest-dom`](https://github.com/testing-library/jest-dom) | ^6.6 | DOM 상태 단언 커스텀 matcher (`toBeInTheDocument`, `toHaveTextContent` 등) |
| [`@testing-library/user-event`](https://testing-library.com/docs/user-event/intro) | ^14.6 | 실제 사용자 상호작용 시뮬레이션 (`fireEvent`보다 `userEvent` 권장) |
| [`jsdom`](https://github.com/jsdom/jsdom) | ^26.0 | 브라우저 없는 DOM 환경. Vitest `environment: "jsdom"`으로 사용 |

**선택 이유**:
- Vite와 자연스럽게 통합 (`vite.config.ts`에 `test` 블록만 추가)
- 설정 최소화 — 별도 tsconfig 불필요
- Component + interaction test에 적합
- 이미 설치된 React 19와 호환

### NPM scripts 추가

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest",
    "test:run": "vitest run"
  }
}
```

- `npm test` — watch mode (개발 중 실행)
- `npm run test:run` — CI/1회 실행

### Vite config test 블록

```ts
/// <reference types="vitest/config" />
// ...
test: {
  globals: true,
  environment: "jsdom",
  setupFiles: "./src/__tests__/setup.ts",
  css: true,
  include: ["src/__tests__/**/*.test.{ts,tsx}"],
}
```

### Setup 파일 (`setup.ts`)

```ts
import "@testing-library/jest-dom/vitest";

// Pico CSS는 빌드 시 번들링되므로 테스트에서는 import 생략 가능
// (css: true 옵션이 이미 vite.config에 있으면 처리됨)

// sessionStorage mock (jsdom 기본 지원, 추가 설정 불필요)

beforeEach(() => {
  sessionStorage.clear();
});
```

---

## 3. Mock 전략

### 선택: **`global.fetch` mock**

`LoginForm.tsx`는 `fetch("/orders", ...)`를 직접 호출하고,
page 컴포넌트들은 `api/client.ts`의 `request()` → `fetch()`를 경유한다.
두 코드 경로 모두 `fetch`를 사용하므로 하나의 mock으로 모든 API 호출을 제어할 수 있다.

#### 구조

```
테스트 → (렌더) → 컴포넌트 → api/client.ts → fetch()
                                                   ↑
                                              vi.fn() mock
```

#### API 응답 Fixture 예시

```ts
// test-utils/fixtures.ts
export const mockOrders = [
  {
    order_request_id: "uuid-1",
    symbol: "AAPL",
    side: "buy",
    order_type: "limit",
    qty: "100",
    status: "filled",
    created_at: "2026-05-05T00:00:00Z",
    client_id: "client-1",
    strategy_code: "strat-a",
  },
];

export const mockHealthOk = {
  status: "ok",
  database: "connected",
  mode: "in_memory",
};
```

#### Mock Helper

```ts
// test-utils/mockFetch.ts
import { vi } from "vitest";

export function mockFetchOnce(data: unknown) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => data,
  } as Response);
}

export function mockFetchError(status: number, detail: string) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
    ok: false,
    status,
    statusText: detail,
    json: async () => ({ detail }),
  } as Response);
}

export function mockFetchNetworkError() {
  return vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("Network error"));
}
```

#### `vi.mock()` 대신 `vi.spyOn()`을 사용하는 이유

| 방식 | 장점 | 단점 |
|------|------|------|
| `vi.mock("./api/client", ...)` | 모듈 전체를 제어 | 실제 모듈이 가려져서 디버깅 어려움 |
| **`vi.spyOn(globalThis, "fetch")`** | **fetch 레벨에서 제어, 실제 import 경로 유지** | 각 테스트마다 setup/teardown 필요 |
| `wrapper injection` | 가장 순수, 의존성 명시 | 컴포넌트 리팩터링 필요 (이번 범위 밖) |

→ **`vi.spyOn(globalThis, "fetch")`** 채택. LoginForm의 raw fetch와 client.ts의 request() fetch를 동시에 커버.

#### URL + Method 분기 명확화 규칙

테스트 코드에서 각 fetch 호출이 어떤 endpoint/method를 호출하는지 명확히 드러나야 한다:

```ts
// ✅ 권장: URL 분기 시 path/method로 의도 명시
// GET /orders → orders 목록
// GET /health → health check
// POST /orders (없음 — read-only)

// Bad: URL 체크 없이 mockResolvedValueOnce 순서만으로 암시적 분기
// Good: expect.stringContaining("/orders") 등으로 URL 검증 추가
mockFetchOnce(mockOrders);                    // GET /orders
mockFetchOnce(mockHealthOk);                  // GET /health
mockFetchOnce(mockReconciliationRuns);         // GET /reconciliation/runs
mockFetchOnce(mockLocks);                      // GET /reconciliation/locks
```

Dashboard처럼 4개 병렬 API를 호출하는 경우, fixture 데이터에 각자 구분되는 값(ex: 다른 order_request_id)을 넣어 어떤 fetch가 어떤 응답인지 테스트 코드에서 명확히 알 수 있게 한다.

#### 401 시나리오 테스트

```ts
// 401 응답 → client.ts request()에서 UnauthorizedError throw
// → clearStoredToken() + _onUnauthorized() 호출
// → AuthContext의 logout 실행 → isAuthenticated = false
```

---

## 4. 테스트 구조

### 파일 배치

```
admin_ui/src/
├── __tests__/
│   ├── setup.ts                    # jest-dom matcher 등록, sessionStorage 초기화
│   ├── test-utils/
│   │   ├── fixtures.ts             # API 응답 fixture 데이터
│   │   ├── mockFetch.ts            # fetch mock helper 함수
│   │   └── render.tsx              # Wrapper provider를 포함한 custom render
│   ├── auth.test.tsx               # P0: LoginForm + AuthContext + 401 handler
│   ├── dashboard.test.tsx          # P0: Dashboard smoke
│   ├── orders.test.tsx             # P0: OrdersView smoke
│   └── components.test.tsx         # P1: DataTable, StatusBadge, ErrorBanner, LoadingSpinner
```

### P0 — 이번 턴 반드시

#### `auth.test.tsx` — Auth Flow 통합 테스트

| # | 시나리오 | 검증 포인트 |
|---|----------|-------------|
| 1 | LoginForm 렌더링 | 제목 "🛡️ Admin UI" 표시, password input 존재, submit 버튼 존재 |
| 2 | 빈 token 입력 시 에러 | submit 시 "Token cannot be empty." 표시 |
| 3 | 유효한 token 입력 | fetch("/orders", { Authorization }) 호출, 200 응답 → sessionStorage에 token 저장, isAuthenticated = true |
| 4 | 잘못된 token 입력 | fetch가 401 반환 → "Invalid token. The server rejected the authorization." 표시 |
| 5 | 네트워크 오류 | fetch rejected → "Cannot connect to server. Is the API running?" 표시 |
| 6 | 기존 sessionStorage token → protected 진입 | sessionStorage에 token 저장 후 AuthProvider mount → isAuthenticated = true, ProtectedRoute가 children 통과 |
| 7 | LoginForm → login → ProtectedRoute | token 저장 후 ProtectedRoute가 children 렌더링 (login 화면으로 redirect되지 않음) |
| 8 | Logout | logout() 호출 → sessionStorage token 제거, token state null |

#### `dashboard.test.tsx` — Dashboard Smoke

| # | 시나리오 | 검증 포인트 |
|---|----------|-------------|
| 1 | 로딩 상태 | 초기 렌더링 시 LoadingSpinner 표시 |
| 2 | 정상 데이터 로드 | 4개 API 응답 → "Dashboard" 제목, 4개 SummaryCard, DB 상태, locks/orders 테이블 |
| 3 | 에러 상태 | API 실패 시 ErrorBanner 표시 |
| 4 | Refresh 버튼 | 클릭 시 fetch 재호출 |

#### `orders.test.tsx` — OrdersView Smoke

| # | 시나리오 | 검증 포인트 |
|---|----------|-------------|
| 1 | 로딩 상태 | LoadingSpinner |
| 2 | 주문 목록 렌더링 | DataTable에 symbol, side, status 등 표시 |
| 3 | 빈 목록 | "No orders found." 표시 |
| 4 | Row click → navigate | onRowClick이 navigate("/orders/{id}") 호출 |

### P1 — 가능하면 포함

#### `components.test.tsx` — 공통 컴포넌트 Smoke

| # | 시나리오 | 검증 포인트 |
|---|----------|-------------|
| 1 | DataTable 렌더링 | column label, data row, keyField 기준 key |
| 2 | DataTable 빈 상태 | emptyMessage 표시 |
| 3 | DataTable 로딩 상태 | "Loading..." text |
| 4 | DataTable row click | onRowClick 호출 확인 |
| 5 | StatusBadge variant | status별 컬러가 올바른지 CSS backgroundColor 확인 (pending=blue, filled=green 등) |
| 6 | ErrorBanner 렌더링/닫기 | message 표시, Dismiss 버튼 클릭 시 onDismiss 호출 |
| 7 | LoadingSpinner | "Loading..." text |

### P1 — OrderDetail (차순위 후보)

OrderDetail은 URL param(`:orderId`) 의존성 + 3개 병렬 API 호출로 테스트 복잡도가 높지만, Phase 2에서 write UI가 추가되면 **가장 깨지기 쉬운 화면** 중 하나다. P1 후보로 유지:

| 시나리오 | 검증 포인트 |
|----------|-------------|
| 로딩 상태 | LoadingSpinner |
| 정상 데이터 | 3개 API 응답 → OrderDetail, OrderEvent 목록, BrokerOrder 목록 렌더링 |
| 에러 상태 | API 실패 → ErrorBanner |
| 잘못된 ID | 404 응답 → "Order not found." |

### P2 — 이번 턴 제외

- ReconciliationView, AccountsView, DecisionsView — 구조가 유사하므로 OrdersView/Dashboard가 커버하면 회귀 위험 낮음
- Layout + Navigation — ProtectedRoute가 auth guard를 검증하므로 중복
- Full browser E2E (Playwright/Cypress)

---

## 5. 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| [`admin_ui/package.json`](admin_ui/package.json) | 수정 | `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`, `jsdom` 의존성 추가, `test`/`test:run` 스크립트 추가 |
| [`admin_ui/vite.config.ts`](admin_ui/vite.config.ts) | 수정 | `test` 블록 추가 (`globals`, `environment: "jsdom"`, `setupFiles`, `css`) |
| [`admin_ui/src/__tests__/setup.ts`](admin_ui/src/__tests__/setup.ts) | 생성 | `@testing-library/jest-dom/vitest` import, `beforeEach` global setup |
| [`admin_ui/src/__tests__/test-utils/fixtures.ts`](admin_ui/src/__tests__/test-utils/fixtures.ts) | 생성 | API 응답 fixture 데이터 |
| [`admin_ui/src/__tests__/test-utils/mockFetch.ts`](admin_ui/src/__tests__/test-utils/mockFetch.ts) | 생성 | `mockFetchOnce`, `mockFetchError`, `mockFetchNetworkError` helper |
| [`admin_ui/src/__tests__/test-utils/render.tsx`](admin_ui/src/__tests__/test-utils/render.tsx) | 생성 | `HashRouter` + `AuthProvider` custom render wrapper |
| [`admin_ui/src/__tests__/auth.test.tsx`](admin_ui/src/__tests__/auth.test.tsx) | 생성 | Auth flow 통합 테스트 (7개 시나리오) |
| [`admin_ui/src/__tests__/dashboard.test.tsx`](admin_ui/src/__tests__/dashboard.test.tsx) | 생성 | Dashboard smoke (4개 시나리오) |
| [`admin_ui/src/__tests__/orders.test.tsx`](admin_ui/src/__tests__/orders.test.tsx) | 생성 | OrdersView smoke (4개 시나리오) |
| [`admin_ui/src/__tests__/components.test.tsx`](admin_ui/src/__tests__/components.test.tsx) | 생성 | 공통 컴포넌트 smoke (7개 시나리오) |
| [`plans/49_admin_ui_test_hardening.md`](plans/49_admin_ui_test_hardening.md) | 생성 | 본 문서 |
| [`plans/README.md`](plans/README.md) | 수정 | Plan 49 목록 추가 |
| [`plans/[BACKLOG] backlog.md`](plans/[BACKLOG]%20backlog.md) | 수정 | 필요 시 backlog 항목 갱신 |

---

## 6. 실행 순서

### Step 1: 테스트 인프라 설치 및 설정

의존성 설치:
```bash
cd admin_ui
npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom
```

### Step 2: `vite.config.ts`에 test 블록 추가

```ts
/// <reference types="vitest/config" />
export default defineConfig({
  // ... 기존 설정
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/__tests__/setup.ts",
    css: true,
    include: ["src/__tests__/**/*.test.{ts,tsx}"],
  },
});
```

### Step 3: Setup 파일 + Test Utilities 생성

- `setup.ts` — jest-dom matcher, sessionStorage 초기화
- `test-utils/fixtures.ts` — API fixture 데이터
- `test-utils/mockFetch.ts` — fetch mock helper
- `test-utils/render.tsx` — custom render with HashRouter + AuthProvider

### Step 4: Auth 테스트 (`auth.test.tsx`)

7개 시나리오:
1. LoginForm 기본 렌더링
2. 빈 token 에러
3. 유효 token → login 성공
4. 잘못된 token → 에러 메시지
5. 네트워크 오류 → 연결 에러
6. Login → Protected route guard
7. Logout → token 제거

### Step 5: Dashboard smoke (`dashboard.test.tsx`)

4개 시나리오:
1. 로딩 상태
2. 정상 데이터
3. 에러 상태
4. Refresh 버튼

### Step 6: OrdersView smoke (`orders.test.tsx`)

4개 시나리오:
1. 로딩 상태
2. 주문 목록 렌더링
3. 빈 목록
4. Row click → navigate

### Step 7: 공통 컴포넌트 smoke (`components.test.tsx`)

7개 시나리오:
1. DataTable 렌더링
2. DataTable empty
3. DataTable loading
4. DataTable row click
5. StatusBadge variant
6. ErrorBanner render/close
7. LoadingSpinner

### Step 8: 테스트 실행 확인

```bash
cd admin_ui && npm run test:run
```

### Step 9: 문서 업데이트

- `plans/README.md` — Plan 49 추가
- `plans/[BACKLOG] backlog.md` — 필요 시 업데이트

---

## 7. 검증 포인트

| # | 검증 항목 | 기준 |
|---|-----------|------|
| 1 | `npm run test:run` 전체 통과 | 0 failure |
| 2 | LoginForm token 입력/저장/실패 동작 | sessionStorage, UI 상태 변화 |
| 3 | ProtectedRoute guard 동작 | 미인증 시 `/login` redirect |
| 4 | 401 → auto logout | client.ts의 401 처리 → AuthContext → isAuthenticated = false |
| 5 | Dashboard 최소 렌더링 | Loading → Data → Error 3가지 상태 |
| 6 | OrdersView 최소 렌더링 | DataTable, row click navigate |
| 7 | 공통 컴포넌트 개별 동작 | DataTable/StatusBadge/ErrorBanner/LoadingSpinner |
| 8 | 기존 `npm run build` 여전히 통과 | TypeScript + Vite build regression 없음 |

---

## 8. Risk Assessment

| 위험 | 영향 | 확률 | 완화 |
|------|------|------|------|
| `jsdom`과 Pico CSS CSS 변수(`var(--pico-*)`) 호환성 | CSS 변수가 jsdom에서 undefined → 테스트에서 스타일 단언 실패 | 낮음 | `css: true` 옵션으로 Vite CSS 처리. 스타일 단언보다 text content/존재 여부 위주로 검증 |
| `HashRouter` + `MemoryRouter` 충돌 | 테스트에서 MemoryRouter를 쓰면 HashRouter 동작과 다를 수 있음 | 중간 | Custom render에서 MemoryRouter 사용. Hash vs Memory 차이는 routing 동작이 아니라 guard 동작 검증에 집중 |
| React 19 + Testing Library 호환성 | 아직 release된 지 얼마 안 된 React 19와의 호환성 이슈 | 낮음 | `@testing-library/react` v16은 React 19 공식 지원. 설치 시 버전 확인 |
| `vi.spyOn(globalThis, "fetch")` cleanup 누락 | 테스트 간 fetch mock leak | 낮음 | `afterEach`에서 `vi.restoreAllMocks()` 호출로 초기화 보장 |
| Over-testing (너무 많은 테스트 유지보수 부담) | 파일이 많아지면 유지보수 비용 증가 | 중간 | P0만 필수, P1은 가능한 선에서. 페이지가 추가될 때마다 smoke test를 함께 추가하는 문화 정착 필요 |

---

## Appendix: 테스트 비용 효율 분석

| 화면 | API 호출 수 | 상태 수 | 테스트 우선순위 | 이유 |
|------|------------|---------|----------------|------|
| LoginForm | 1 (fetch) | 4 (init/loading/error/success) | **P0** | 가장 핵심, 3-way 분기 |
| AuthContext | 0 (provider) | 2 (auth/unauth) | **P0** | 전체 routing 기반 |
| ProtectedRoute | 0 | 2 (guard pass/redirect) | **P0** | auth 없으면 전체 앱 무용 |
| Dashboard | 4 (parallel) | 3 (loading/data/error) | **P0** | 랜딩 페이지 |
| OrdersView | 1 | 3 (loading/data/empty/error) | **P0** | 두 번째로 중요한 화면 |
| OrderDetail | 3 (parallel) | 3 (loading/data/error) | P2 | URL param 의존, 복잡도 ↑ |
| ReconciliationView | 2 | 4 (loading/runs/locks/error) | P1 | Dashboard가 일부 커버 |
| AccountsView | 1+2n | 4 (loading/list/detail/error) | P1 | Dashboard가 일부 커버 |
| DecisionsView | 1 | 3 (loading/data/error) | P1 | 단순 DataTable 단일 |
| DataTable | 0 | 3 (loading/data/empty) | **P1** | 공통, OrdersView에서 간접 검증 |
| StatusBadge | 0 | 1+ (variant) | **P1** | 단순, 시각적 확인은 수동 |
| ErrorBanner | 0 | 2 (show/dismiss) | P1 | 단순 |
