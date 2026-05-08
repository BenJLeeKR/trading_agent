# Dashboard 422 수정 — reconciliation API `account_id` 필수 계약 대응

## 문제 원인

- **Backend contract**: `GET /reconciliation/runs?account_id=...` 와 `GET /reconciliation/locks?account_id=...` 는 `account_id`를 **필수 Query 파라미터**로 요구함
- **Dashboard 현재 상태**: `getReconciliationLocks()` 와 `getReconciliationRuns()` 를 **인자 없이** 호출
- **결과**: 422 Validation Error 발생

## 수정 계획

### 1. [`Dashboard.tsx`](admin_ui/src/components/Dashboard.tsx) — Step 4 수정

**변경 전 (line 170-174):**
```typescript
const [ordersData, locksData, reconData] = await Promise.all([
  getOrders(),
  getReconciliationLocks(),    // ❌ no account_id
  getReconciliationRuns(),     // ❌ no account_id
]);
```

**변경 후:**
```typescript
const repAccountId = allAccounts[0]?.account_id;
const [ordersData, locksData, reconData] = repAccountId
  ? await Promise.all([
      getOrders(),
      getReconciliationLocks(repAccountId),
      getReconciliationRuns(repAccountId),
    ])
  : [await getOrders(), [], []];
```

**선정 기준**: `allAccounts[0]` (첫 번째 계좌) — Dashboard가 이미 accounts를 fetch하므로 첫 번째 계좌를 대표로 사용. 계좌가 없으면 reconciliation 호출을 건너뛰고 빈 배열 사용.

### 2. [`dashboard.test.tsx`](admin_ui/src/__tests__/dashboard.test.tsx) — 테스트 변경 불필요

- `mockFetchOnce`는 URL을 구분하지 않고 FIFO 순서로 데이터를 반환하므로, `account_id` 전달 여부와 관계없이 동일한 mock 순서 유지
- 단, accounts가 없을 때 `getOrders()`는 계속 호출되므로 현재 mock 개수(11개) 유지

### 3. 영향 분석

| 시나리오 | 동작 |
|---|---|
| clients + accounts 정상 | `allAccounts[0].account_id` 로 reconciliation 호출 |
| clients 있음, accounts 없음 | `repAccountId = undefined` → reconciliation 스킵, orders만 fetch |
| clients 없음 | 기존 early return (변경 없음) |

## 작업 파일

| 파일 | 변경 | 설명 |
|---|---|---|
| [`Dashboard.tsx`](admin_ui/src/components/Dashboard.tsx) | 수정 | Step 4에서 대표 account_id 추출 후 reconciliation API에 전달 |
| [`dashboard.test.tsx`](admin_ui/src/__tests__/dashboard.test.tsx) | 변경 없음 | mock FIFO 방식이므로 mock 순서/개수 동일 |

## 검증

1. `npx vitest run` — 76/76 통과
2. `npm run build` — tsc + vite build 성공
