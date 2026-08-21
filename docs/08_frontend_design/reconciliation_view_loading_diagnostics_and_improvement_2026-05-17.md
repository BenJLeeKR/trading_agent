# 정합성 점검(ReconciliationView) 로딩 지연 진단 및 개선

> 작성일: 2026-05-17  
> 대상 파일: `admin_ui/src/components/ReconciliationView.tsx`, `admin_ui/src/__tests__/reconciliation.test.tsx`, `admin_ui/src/lib/reconcileRequired.ts`

---

## 1. 현재 로딩 구조 분석

### 1.1 useEffect 구성

```
[컴포넌트 마운트]
  │
  ├─ useEffect #1 (runs / locks) ── 72-94행
  │    ├── getReconciliationRuns()      ── 병렬 (Promise.all)
  │    └── getReconciliationLocks()     ── 병렬 (Promise.all)
  │    └── setLoading(false) (두 API 모두 완료 후)
  │    └── 실패 시 → setError() → 전체 화면 <ErrorBanner />
  │
  └─ useEffect #2 (reconcile_required) ── 97-144행
       ├── getOrders("reconcile_required")  ← Step 1: 직렬 선행 (106행)
       │    └── accountIds 추출 (111행)
       └── Promise.all(
             accountIds.map(id => getPositions(id))  ← Step 2: 병렬 후행 (114-119행)
           )
       └── setReconcileLoading(false) (모든 API 완료 후)
```

### 1.2 API 호출 수 (최악 시나리오)

| 단계 | 호출 | 수 | 비고 |
|------|------|------|------|
| useEffect #1 | runs + locks | 2 | 병렬, 1회 왕복 |
| useEffect #2 | orders + positions × N | 1 + N | 직렬 선행 후 병렬 |
| lazy (on click) | brokerOrders × M | M | 개별 lazy load |
| **합계** | | **3 + N + M** | N=계정 수, M=확장 행 수 |

### 1.3 상태 관리 분석 (변경 전)

| 상태 변수 | 타입 | 초기값 | 해제 시점 | 영향 범위 |
|-----------|------|--------|-----------|-----------|
| `loading` | boolean | true | useEffect #1 완료 | 화면 전체 LoadingSpinner |
| `error` | string\|null | null | useEffect #1 실패 | 화면 전체 ErrorBanner |
| `reconcileLoading` | boolean | false | useEffect #2 완료 | reconcile 섹션 spinner 아이콘 |
| `reconcileError` | string\|null | null | useEffect #2 실패 | reconcile 섹션 ErrorBanner |

### 1.4 렌더 흐름 (325-326행)

```tsx
// 325행: useEffect #1 완료 전까지 전체 화면이 LoadingSpinner
if (loading) return <LoadingSpinner />;

// 326행: useEffect #1 실패 시 전체 화면이 ErrorBanner
// → reconcile 섹션(useEffect #2)이 이미 성공했어도 가려짐
if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;
```

---

## 2. 병목 원인 (우선순위 순)

### 🥇 `getPositions(accountId)` × N (114-119행)

- 계정 수만큼 개별 HTTP 요청 발생
- N=5면 5회 왕복, N=10이면 10회
- 모든 응답이 도착해야 `reconcileLoading` 해제
- **백엔드에 `GET /positions` (account_ids bulk query)가 없음**

### 🥈 useEffect #1 실패 시 화면 전체 블랭크 (326행)

- `if (error) return <ErrorBanner />`가 runs/locks 영역뿐 아니라 reconcile 영역까지 가림
- reconcile_required 데이터가 이미 로드되었어도 표시 불가
- `onDismiss`로 error 해제 가능하지만, 사용자가 직접 dismiss 필요

### 🥉 로딩 상태가 하나로 묶여 있음 (325행)

- `loading` 하나로 runs/locks 영역과 reconcile 영역의 로딩을 동시에 제어
- runs/locks가 먼저 도착해도 reconcile_required가 로딩 중이면 전체가 스피너

### 🏅 `findMatchingPosition()`의 linear search (reconcileRequired.ts 45-46행)

```typescript
// 현재: O(n²) 가능성
positions.find((p) => p.symbol === order.symbol)
```

- 계정별 positions 배열에서 `Array.find()`로 symbol 검색
- 주문 수 × 포지션 수만큼 반복: M(orders) × P(positions) 비교

---

## 3. 사용자 체감 문제

1. **전체 spinner 1개로 모든 영역을 묶음** — runs/locks가 빨리 도착해도 reconcile 기다려야 화면 표시
2. **runs/locks 실패 시 reconcile까지 블랭크** — 부분 실패에도 전체 화면 사용 불가
3. **섹션별 로딩 피드백 부재** — reconcile 섹션에만 spinner 아이콘, runs/locks는 로딩 중 표시 없음

---

## 4. 적용할 개선 내용 (4가지)

### 개선 1: Loading 상태를 section-level로 분리

**현재 (325행)**:
```tsx
if (loading) return <LoadingSpinner />;
```

**변경**: `loading`을 `runsLocksLoading`으로 rename하고, reconcile 섹션과 분리하여 각각 독립적 로딩 표시

```tsx
// Before:
const [loading, setLoading] = useState(true);

// After:
const [runsLocksLoading, setRunsLocksLoading] = useState(true);
```

렌더 구조:
```tsx
// runs/locks 섹션
{runsLocksLoading ? (
  <LoadingSpinner text="정합성 데이터 로딩 중..." />
) : (
  <>
    {/* Active Locks Section */}
    {/* Reconciliation Runs Section */}
  </>
)}

// reconcile 섹션 (기존 reconcileLoading 사용)
{reconcileLoading ? (
  <LoadingSpinner text="조정 필요 주문 로딩 중..." />
) : (
  <>
    {/* Reconcile-required table */}
  </>
)}
```

**장점**:
- runs/locks가 먼저 도착하면 즉시 표시
- reconcile_required가 로딩 중이어도 runs/locks 영역은 조작 가능
- 사용자 체감 성능 향상

### 개선 2: Error 상태 3-way 완전 분리 — `runsError` / `locksError` / `reconcileError`

**현재**: `error` 하나로 runs/locks/reconcile 모든 섹션의 실패를 통합 관리하여 한 섹션 실패가 다른 섹션까지 가림

**변경**: runs, locks, reconcile 각각 독립적인 error 상태 변수 사용

```tsx
const [runsError, setRunsError] = useState<string | null>(null);
const [locksError, setLocksError] = useState<string | null>(null);
// reconcileError는 이미 존재 — 유지
```

**fetchData 로직 변경 (72-94행)**:
```typescript
// Before: Promise.all + 단일 catch
try {
  const [runsData, locksData] = await Promise.all([
    getReconciliationRuns(),
    getReconciliationLocks(),
  ]);
  setRuns(runsData);
  setLocks(locksData);
} catch (err) {
  setError(err instanceof Error ? err.message : "...");
} finally {
  setLoading(false);
}

// After: 개별 try/catch — 한쪽 실패가 다른쪽에 영향 없음
try {
  const runsData = await getReconciliationRuns();
  if (!cancelled) setRuns(runsData);
} catch (err) {
  if (!cancelled) {
    setRunsError(err instanceof Error ? err.message : "정합성 실행 데이터를 불러오지 못했습니다");
  }
}

try {
  const locksData = await getReconciliationLocks();
  if (!cancelled) setLocks(locksData);
} catch (err) {
  if (!cancelled) {
    setLocksError(err instanceof Error ? err.message : "잠금 데이터를 불러오지 못했습니다");
  }
}

if (!cancelled) setRunsLocksLoading(false);
```

**중요**: `getReconciliationRuns()`와 `getReconciliationLocks()`는 이제 `Promise.all`이 아닌 **직렬**로 실행됨. 이로 인한 지연은 없음 (2개 API, 각각 sub-second 응답). 병렬 처리 유지가 필요하다면 별도로 진행.

**렌더 구조**:
```tsx
{/* runs error */}
{runsError && (
  <ErrorBanner message={runsError} onDismiss={() => setRunsError(null)} />
)}

{/* locks error */}
{locksError && (
  <ErrorBanner message={locksError} onDismiss={() => setLocksError(null)} />
)}

{/* reconcile error (기존 유지) */}
{reconcileError && (
  <ErrorBanner message={reconcileError} onDismiss={() => setReconcileError(null)} />
)}
```

**핵심 원칙**: 한 섹션 실패가 다른 섹션을 empty처럼 보이게 하지 않음. 예: runs 실패로 `runsError` 배너가 떠도, locks 데이터가 정상이면 locks 섹션은 정상 렌더링되어야 함.

### 개선 3: `deriveReconcileRequiredCases()` — 계정별 symbol→position Map 인덱스 최적화

**변경 전** ([`reconcileRequired.ts`](admin_ui/src/lib/reconcileRequired.ts:131)):
```typescript
export function deriveReconcileRequiredCases(
  orders: OrderSummary[],
  positionsByAccount: Map<string, PositionSnapshotView[]>,
): ReconcileRequiredCase[] {
  for (const order of orders) {
    const accountPositions = positionsByAccount.get(order.account_id) ?? [];
    // O(P) linear search per order → O(N × P) total
    const matchedPosition = findMatchingPosition(order, accountPositions);
    // ...
  }
}
```

**변경 후**: `Map<accountId, Map<symbol, PositionSnapshotView>>` pre-index 구축
```typescript
export function deriveReconcileRequiredCases(
  orders: OrderSummary[],
  positionsByAccount: Map<string, PositionSnapshotView[]>,
): ReconcileRequiredCase[] {
  // Step 1: Build account-level symbol→position index (O(P))
  const positionIndex = new Map<string, Map<string, PositionSnapshotView>>();
  for (const [accountId, positions] of positionsByAccount) {
    const symbolMap = new Map<string, PositionSnapshotView>();
    for (const pos of positions) {
      if (pos.symbol) symbolMap.set(pos.symbol, pos);
    }
    positionIndex.set(accountId, symbolMap);
  }

  // Step 2: Lookup per order using index (O(1) per order)
  const cases: ReconcileRequiredCase[] = [];
  for (const order of orders) {
    const acctIndex = positionIndex.get(order.account_id);
    const matchedPosition = order.symbol
      ? (acctIndex?.get(order.symbol) ?? null)
      : null;
    // ... (나머지 로직 동일)
  }
}
```

**복잡도**:
- **Before**: O(계정별 positions 배열 길이의 합 × orders 수) = O(P × N)
- **After**: O(positions 총합) + O(orders 수) = O(P + N)
- Map.get()은 O(1)이므로 orders 루프 내에서 추가 비용 없음

### 개선 4: Partial render 상태에서 summary semantics 보호

**문제**: reconcile 섹션이 loading 중이거나 일부만 로드되었을 때 summary 카드가 "0건"처럼 표시되면 사용자가 오해할 수 있음

**변경**:
- reconcile 섹션 내 summary 카드에 **로딩 중** 또는 **일부만 반영됨** 표시 추가
- `reconcileLoading === true`일 때 summary 카드 대신 "로딩 중..." 표시
- reconcileError가 있을 때 summary 카드에 "일부 데이터를 불러오지 못했습니다" 경고 표시

```tsx
{/* Summary card — semantics-safe */}
{!reconcileLoading && !reconcileError && reconcileCases.length > 0 && (
  <div className="grid grid-cols-2 gap-4">
    <SummaryCard label="조정 필요 주문" value={summaryCard.total} />
    <SummaryCard label="포지션 반영됨" value={summaryCard.reflected} />
  </div>
)}

{/* Loading indicator instead of misleading "0" */}
{reconcileLoading && (
  <div className="bg-white rounded-xl border border-[#e2e8f0] p-4 text-center">
    <p className="text-sm text-[#94a3b8]">조정 필요 주문 데이터를 불러오는 중...</p>
  </div>
)}

{/* Partial data warning */}
{!reconcileLoading && reconcileError && reconcileCases.length > 0 && (
  <WarningBanner
    variant="warning"
    title="데이터 일부 누락"
    message="일부 계정의 포지션 데이터를 불러오지 못했습니다. 표시된 정보는 불완전할 수 있습니다."
  />
)}
```

---

## 5. 변경 대상 파일 및 상세 변경 사항

### 5.1 `admin_ui/src/components/ReconciliationView.tsx`

#### 상태 변수 변경

| 변경 전 | 변경 후 | 비고 |
|---------|---------|------|
| `loading` | `runsLocksLoading` | runs/locks 전용 loading |
| `error` | **`runsError`** + **`locksError`** | 3-way error 완전 분리 |
| `reconcileLoading` | 유지 | reconcile 전용 loading |
| `reconcileError` | 유지 | reconcile 전용 error (기존) |

#### useEffect #1 변경 (72-94행)

- `Promise.all` → 개별 try/catch로 분리 (직렬 실행, 지연 없음)
- `setRunsError()` / `setLocksError()` 각각 설정
- `setError()` 삭제 — 더 이상 사용하지 않음

#### 렌더 구조 변경 (325-326행 → 새로운 구조)

```tsx
// Before (기존):
if (loading) return <LoadingSpinner />;
if (error) return <ErrorBanner message={error} onDismiss={() => setError(null)} />;

return (
  <div className="p-6 space-y-6">{/* ... */}</div>
);

// After (제안):
return (
  <div className="p-6 space-y-6">
    {/* Page Header (항상 표시) */}

    {/* ── runs/locks 영역 ── */}
    {runsLocksLoading ? (
      <LoadingSpinner text="정합성 데이터 로딩 중..." />
    ) : (
      <>
        {runsError && <ErrorBanner message={runsError} onDismiss={() => setRunsError(null)} />}
        {locksError && <ErrorBanner message={locksError} onDismiss={() => setLocksError(null)} />}
        {activeLocks.length > 0 && <WarningBanner ... />}
        {/* Active Locks Section */}
        {/* Reconciliation Runs Section */}
      </>
    )}

    {/* ── reconcile 섹션 ── */}
    {reconcileLoading ? (
      <LoadingSpinner text="조정 필요 주문 로딩 중..." />
    ) : (
      <>
        {reconcileError && <ErrorBanner ... />}
        {/* Summary card (semantics-safe) */}
        {/* Reconcile-required table */}
      </>
    )}
  </div>
);
```

#### BrokerInfoPanel (변경 없음)
- lazy load 패턴 그대로 유지 — 회귀 방지

### 5.2 `admin_ui/src/lib/reconcileRequired.ts`

- [`deriveReconcileRequiredCases()`](admin_ui/src/lib/reconcileRequired.ts:131) 내부에 `Map<accountId, Map<symbol, PositionSnapshotView>>` pre-index 구축
- [`findMatchingPosition()`](admin_ui/src/lib/reconcileRequired.ts:38) 함수 시그니처 변경 가능 — (order, positionIndex) 형태로 변경
- 기존 `findMatchingPosition()`은 더 이상 사용되지 않을 수 있음

### 5.3 `admin_ui/src/__tests__/reconciliation.test.tsx`

#### 신규 테스트 케이스

1. **runs/locks loading이 reconcile loading과 독립적인지**
   - `getReconciliationRuns` / `getReconciliationLocks`를 지연
   - reconcile_required orders가 먼저 도착해도 runs/locks 영역만 LoadingSpinner
   - reconcile 섹션은 정상 렌더링

2. **runs API 실패 시 reconcile 섹션 정상 렌더링** (회귀 방지)
   - `getReconciliationRuns` reject, `getReconciliationLocks` resolve
   - runs 영역에 `runsError` ErrorBanner
   - reconcile 섹션 정상 표시

3. **locks API 실패 시 runs 섹션 정상 렌더링**
   - `getReconciliationLocks` reject, `getReconciliationRuns` resolve
   - locks 영역에 `locksError` ErrorBanner
   - runs 섹션 정상 표시

4. **모든 API 성공 시 기존 동작과 동일** (회귀 방지)
   - 기존 테스트 모두 통과 확인

5. **Partial render 상태에서 summary semantics**
   - reconcileLoading=true → summary 대신 "로딩 중..." 표시
   - reconcileError=true + 데이터 있음 → warning 배너 표시
   - reconcileError=true + 데이터 없음 → empty 상태

6. **broker lazy load 회귀 없음**
   - 기존 broker info expand 테스트 유지

7. **`deriveReconcileRequiredCases` Map lookup 정확성**
   - 여러 계정, 여러 symbol의 positions이 올바르게 매칭되는지
   - symbol이 겹치는 경우 올바른 계정의 position 사용

---

## 6. 테스트 계획

### 6.1 단위 테스트 (vitest)

```bash
cd admin_ui && npm test -- --run
```

### 6.2 통합 확인

```bash
cd admin_ui && npm run build
```

### 6.3 수동 확인 항목

- Docker 재빌드 후 reconcile view 접속
- 브라우저 DevTools Network 탭에서 API 호출 수 확인
- runs/locks/reconcile 각 섹션 독립적 표시 확인
- 각 API 강제 실패 시 ErrorBanner 섹션별 분리 확인
- Summary 카드가 loading/error 상태에서 오해 없이 표시되는지 확인

---

## 7. 실행 순서

```
Step 1: ReconciliationView.tsx 수정
  ├── 상태 변수: runsLocksLoading, runsError, locksError (기존 reconcileError 유지)
  ├── useEffect #1: 개별 try/catch로 분리 (직렬 실행)
  └── 렌더 구조: section-level loading/error + summary semantics

Step 2: reconcileRequired.ts 최적화
  └── deriveReconcileRequiredCases: Map<accountId, Map<symbol, Position>> pre-index

Step 3: reconciliation.test.tsx 업데이트
  ├── section-level loading 독립성 테스트
  ├── partial error render 테스트 (3-way error)
  ├── summary semantics 테스트
  └── broker lazy load 회귀 테스트 유지

Step 4: npm test + npm run build
  └── 모든 테스트 통과 및 빌드 성공 확인

Step 5: Docker 재빌드 + API 확인
  └── 운영 환경 정상 동작 확인
```

---

## 8. 설계 원칙

1. **단순성 유지**: 기존 아키텍처를 크게 바꾸지 않고 incremental 개선
2. **점진적 개선**: 한 번에 모든 것을 바꾸지 않고, 병목 순위대로 처리
3. **회귀 방지**: broker lazy load (handleToggleBrokerInfo) 패턴을 건드리지 않음
4. **확장성**: 추후 bulk position API 도입 시 구조 개편이 필요 없도록 useEffect #2는 그대로 유지
5. **semantics 보호**: partial render 상태에서 summary 숫자가 오해를 부르지 않도록 처리

---

## 9. Mermaid: 변경 후 로딩 흐름

```mermaid
sequenceDiagram
    participant User
    participant Component as ReconciliationView
    participant API1 as GET /runs
    participant API2 as GET /locks
    participant API3 as GET /orders
    participant API4 as GET /positions

    Component->>API1: getReconciliationRuns
    Component->>API2: getReconciliationLocks
    Component->>API3: getOrders reconcile_required

    Note over API1,API2: 개별 try/catch - runsError/locksError 독립적 처리
    Note over API3,API4: 기존 직렬→병렬 패턴 유지

    API1-->>Component: runs data (or runsError)
    API2-->>Component: locks data (or locksError)
    Note over Component: setRunsLocksLoading = false
    Note over Component: runs/locks 영역 렌더링 시작 (부분 실패 허용)

    API3-->>Component: orders
    Component->>API4: getPositions x N (parallel)
    API4-->>Component: positions map
    Note over Component: setReconcileLoading = false
    Note over Component: reconcile 영역 렌더링 (summary semantics 보호)
```
