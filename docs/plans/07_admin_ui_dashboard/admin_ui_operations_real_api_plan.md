# Phase 2: 운영 모니터링 3개 화면 Real API 전환 계획

## 목표

Phase 1에서 mock/static UI shell로 생성한 운영 모니터링 3개 화면을 실제 Admin API 기반 화면으로 전환하고, 메뉴 구조를 운영 중심으로 재정의한다.

---

## 변경 대상 파일 (기능 보존, 5개 파일 수정)

| 파일 | 상태 | 설명 |
|------|------|------|
| `admin_ui/src/App.tsx` | **수정** | index route를 OperationsDashboardView로 변경, Dashboard는 `/overview`로 이동 |
| `admin_ui/src/components/Layout.tsx` | **수정** | navSections에서 "개요" 제거 또는 "기타" 섹션으로 이동 |
| `admin_ui/src/components/OperationsDashboardView.tsx` | **전면 재작성** | mock 데이터 제거, real API + Promise.allSettled, 실패 API 오류 표시 |
| `admin_ui/src/components/OperationsAlertsView.tsx` | **전면 재작성** | mock alerts 제거, real data 기반 derived alerts (긴급/주의/정보/정상) |
| `admin_ui/src/components/OrderTrackingView.tsx` | **전면 재작성** | mock orders 제거, getOrders() + detail chain, 기존 /orders/:id 링크 |

**변경 없음**: Dashboard.tsx (기존 유지, `/overview`에서 동작), api/client.ts (기존 함수만 사용), types/api.ts (필요시 타입 보강만 허용), StatusCard.tsx, 기타 공통 컴포넌트, 기존 테스트 파일

---

## Step 0: API client 함수 목록 및 사용처

### 직접 사용 가능한 함수 (client_id 없이)

| 함수 | 반환 타입 | 사용 View |
|------|-----------|-----------|
| `getHealth()` | `HealthResponse` | Dashboard, Layout header |
| `getReadyz()` | `Record<string, string>` | Dashboard |
| `getAccounts()` | `AccountSummary[]` | Dashboard (계좌 목록) |
| `getOrders(status?)` | `OrderSummary[]` | Dashboard, Alerts, Orders |
| `getReconciliationSummary()` | `ReconciliationSummary` | Dashboard, Alerts |
| `getReconciliationRuns(accountId?)` | `ReconciliationRunSummary[]` | Alerts (snapshot freshness) |
| `getBrokerCapacity()` | `BrokerCapacityResponse` | Dashboard |
| `getTradeDecisions(decisionContextId?)` | `TradeDecisionDetail[]` | Dashboard |
| `getAgentRuns(decisionContextId?)` | `AgentRunResponse[]` | Dashboard, Alerts |

### accountId 필요 함수 (계좌별)

| 함수 | 사용 View | 비고 |
|------|-----------|------|
| `getPositions(accountId)` | Dashboard | 모든 계좌에 대해 병렬 호출 |
| `getCashBalance(accountId)` | Dashboard | 모든 계좌에 대해 병렬 호출 |

### orderId 필요 함수 (OrderTrackingView detail)

| 함수 | 사용 View | 비고 |
|------|-----------|------|
| `getOrderDetail(orderId)` | OrderTracking | 선택된 주문 상세 |
| `getOrderEvents(orderId)` | OrderTracking | 상태 전이 이력 |
| `getBrokerOrders(orderId)` | OrderTracking | 브로커 주문 내역 |

---

## Step 1: 메뉴 구조 재정의

### App.tsx 변경

```
// 변경 전
<Route index element={<Dashboard />} />

// 변경 후
<Route index element={<OperationsDashboardView />} />
<Route path="overview" element={<Dashboard />} />
```

### Layout.tsx navSections 변경

```
// "기본 운영" → "개요" 제거
{
  title: "기본 운영",
  items: [
    // { icon: LayoutDashboard, label: "개요", to: "/" }, ← 제거
    { icon: FileText, label: "주문", to: "/orders" },
    { icon: RefreshCcw, label: "정합성 점검", to: "/reconciliation" },
    { icon: Wallet, label: "계좌", to: "/accounts" },
    { icon: Brain, label: "의사결정", to: "/decisions" },
    { icon: Zap, label: "에이전트 실행", to: "/agent-runs" },
  ],
},

// "운영 모니터링" 섹션은 그대로 유지 (상단)

// "기존 대시보드"는 숨김 처리 또는 "기타" 섹션 하단에 배치
// 선택: "기타" 섹션에 { icon: LayoutDashboard, label: "기존 대시보드", to: "/overview" } 추가
// 또는 메뉴에서 완전히 숨김 (URL로만 접근 가능)
```

---

## Step 2: OperationsDashboardView → Real API

### 데이터 흐름

```typescript
useEffect(() => {
  setLoading(true);
  const results = await Promise.allSettled([
    // ── 시스템 상태 ──
    getHealth().then(h => ({ key: "health", data: h })),
    getReadyz().then(r => ({ key: "readyz", data: r })),

    // ── 브로커 ──
    getBrokerCapacity().then(b => ({ key: "brokerCapacity", data: b })),

    // ── 정합성 ──
    getReconciliationSummary().then(r => ({ key: "reconSummary", data: r })),

    // ── 주문 / 결정 / 에이전트 ──
    getOrders().then(o => ({ key: "orders", data: o })),
    getTradeDecisions().then(d => ({ key: "decisions", data: d })),
    getAgentRuns().then(a => ({ key: "agentRuns", data: a })),

    // ── 계좌 → 포지션 + 현금 ──
    (async () => {
      const accounts = await getAccounts();
      const posResults = await Promise.allSettled(
        accounts.map(a => getPositions(a.account_id))
      );
      const cashResults = await Promise.allSettled(
        accounts.map(a => getCashBalance(a.account_id))
      );
      return { key: "accounts", data: { accounts, posResults, cashResults } };
    })(),
  ]);

  // 각 결과를 개별 상태에 저장 (실패는 null/error 객체로 저장)
  // 실패한 API 이름과 오류 메시지는 `apiErrors` 배열에 축적
  setApiErrors(accumulatedErrors);
  setLoading(false);
}, []);
```

### StatusCard 데이터 소스 매핑

| StatusCard | 데이터 소스 | 실패/미연동 시 |
|------------|-----------|----------------|
| API 상태 | `getHealth().status === "ok"` | "미연동" (error) |
| DB 상태 | `getHealth().database` | "미연동" (error) |
| Ready 상태 | `getReadyz()` 모든 키 "ok" | "미연동" (error) |
| 브로커 용량 | `getBrokerCapacity()` | "확인 필요" (warning) |
| 마지막 스냅샷 동기화 | `getReconciliationRuns()` 최근 성공 시간 | "스냅샷 없음" (error) |
| 미해결 정합성 | `getReconciliationSummary().incomplete_recon_count` | "확인 필요" (warning) |
| 오늘 AI 결정 | `getTradeDecisions().length` | "N/A" (neutral) |
| 오늘 주문 제출 | `getOrders().length` | "N/A" (neutral) |
| 현재 포지션 | `getPositions()` aggregate | "N/A" (neutral) |
| 가용 현금 | `getCashBalance()` aggregate | "N/A" (neutral) |
| 미실현 손익 | `getPositions().unrealized_pnl` 합계 | "N/A" (neutral) |
| 당일 성과 | 계산 불가시 "N/A" | "N/A" (neutral) |

### API 실패 표시

```typescript
interface ApiErrorEntry {
  apiName: string;
  message: string;
}
const [apiErrors, setApiErrors] = useState<ApiErrorEntry[]>([]);

// 화면 하단 또는 경고 영역에 표시
{apiErrors.length > 0 && (
  <div className="bg-[#fef2f2] border border-[#f87171] rounded-xl p-4">
    <h3 className="text-sm font-semibold text-[#991b1b] mb-2">
      일부 데이터를 불러오지 못했습니다
    </h3>
    <ul className="text-xs text-[#b91c1c] space-y-1">
      {apiErrors.map((e, i) => (
        <li key={i}>• {e.apiName}: {e.message}</li>
      ))}
    </ul>
  </div>
)}
```

---

## Step 3: OperationsAlertsView → Derived Alerts

### Alert Derivation Rules (별도 API 없이 기존 데이터에서 도출)

| 우선순위 | 조건 | 수준 | 알림 제목 | 설명 |
|----------|------|------|-----------|------|
| 1 | `getHealth()` 실패 또는 status !== "ok" | **긴급** | API 상태 이상 | API 서버 응답 없음 |
| 2 | 스냅샷 최근 성공 없음 또는 snapshot_at 기준 N분 경과 | **긴급** | 스냅샷 동기화 지연 | 마지막 스냅샷 동기화가 N분 이상 갱신되지 않음 |
| 3 | `getOrders(status="submitted")` 결과 > 0 | **긴급** | 제출 대기 주문 존재 | 브로커에 미제출된 주문이 있음 |
| 4 | `getOrders(status="reconcile_required")` 결과 > 0 | **주의** | 조정 필요 상태 존재 | 브로커 확정 불가, 수동 확인 필요 |
| 5 | `getAgentRuns()` 최근 N건 중 `failed`/`error` > 0 | **주의** | 에이전트 실행 실패 | AI 에이전트 실행 중 오류 발생 |
| 6 | `getReconciliationSummary().active_locks_count > 0` | **주의** | 활성 락 존재 | 정합성 프로세스가 계좌를 잠금 |
| 7 | order_requests=0 이고 position_snapshots>0 | **경고** | 주문-포지션 lineage 불일치 | 주문 내역 없이 포지션만 존재 |
| 8 | 모든 조건 정상 | **정보** | 시스템 정상 | 모든 시스템 정상 운영 중 |

### 데이터 흐름

```typescript
useEffect(() => {
  setLoading(true);
  const results = await Promise.allSettled([
    getHealth(),
    getOrders(),
    getOrders("submitted"),
    getOrders("reconcile_required"),
    getReconciliationSummary(),
    getReconciliationRuns(),
    getAgentRuns(),
    getPositions(/* 모든 계좌 */),
    getBrokerOrders(/* 모든 주문 ID? → 불가능, 생략 */),
  ]);

  // 각 결과를 평가하여 alerts 배열 생성
  const newAlerts: AlertItem[] = [];
  // rule 1: health
  // rule 2: snapshot freshness
  // rule 3: pending_submit
  // rule 4: reconcile_required
  // rule 5: agent failures
  // rule 6: active locks
  // rule 7: lineage mismatch (positions > 0, orders == 0)
  // rule 8: all clear → "정보" alert
  setAlerts(newAlerts);
  setLoading(false);
}, []);
```

### 기존 유지 항목

- Pre-market checklist (static, 유용한 참조 정보)
- Operation notes (static, backend API 없음)
- Alert level filter buttons (전체/긴급/주의/정보)
- Alert detail panel (selectedAlert → 상세 정보)

---

## Step 4: OrderTrackingView → Real API

### 데이터 흐름

```typescript
import type { OrderSummary } from "../types/api";
import { getOrders, getOrderDetail, getOrderEvents, getBrokerOrders } from "../api/client";

// 목록
useEffect(() => {
  setLoading(true);
  try {
    const data = await getOrders();
    setOrders(data);
  } catch (err) {
    setError(err instanceof Error ? err.message : "주문 데이터 로딩 실패");
  } finally {
    setLoading(false);
  }
}, []);

// 상세 (선택 시)
useEffect(() => {
  if (!selectedOrder?.order_request_id) return;
  setDetailLoading(true);
  Promise.allSettled([
    getOrderDetail(selectedOrder.order_request_id).then(d => setOrderDetail(d)),
    getOrderEvents(selectedOrder.order_request_id).then(e => setOrderEvents(e)),
    getBrokerOrders(selectedOrder.order_request_id).then(b => setBrokerOrders(b)),
  ]).finally(() => setDetailLoading(false));
}, [selectedOrder?.order_request_id]);
```

### Filter 설정 (영어 API 값 → 한국어 UI)

```typescript
const statusOptions = [
  { label: "전체", value: "" },
  { label: "제출됨", value: "submitted" },
  { label: "접수됨", value: "acknowledged" },
  { label: "부분체결", value: "partially_filled" },
  { label: "체결", value: "filled" },
  { label: "거부됨", value: "rejected" },
  { label: "취소됨", value: "cancelled" },
  { label: "조정필요", value: "reconcile_required" },
];
```

### Side 매핑

```typescript
function sideLabel(side: string): string {
  switch (side) {
    case "buy": return "매수";
    case "sell": return "매도";
    default: return side;
  }
}
```

### 기존 /orders/:id 링크

```typescript
// detail panel 하단
<Link
  to={`/orders/${selectedOrder.order_request_id}`}
  className="text-sm text-[#3b82f6] hover:text-[#2563eb] font-medium"
>
  기존 주문 상세 화면에서 보기 →
</Link>
```

---

## Step 5: Loading / Error / Empty 상태 처리

### 공통 패턴

```typescript
const [loading, setLoading] = useState(true);
const [error, setError] = useState<string | null>(null);

// 초기 로딩
if (loading) return <LoadingSpinner text="데이터 로딩 중..." />;

// 에러 (일시적, dismiss 가능 → 재시도 버튼)
if (error) return (
  <div className="p-6">
    <ErrorBanner message={error} onDismiss={() => setError(null)} />
    <button onClick={fetchData} className="...">
      다시 시도
    </button>
  </div>
);

// Empty state
if (data.length === 0) return (
  <div className="p-6">
    <div className="bg-white rounded-xl border border-[#e2e8f0] p-8 text-center">
      <p className="text-sm text-[#94a3b8]">데이터가 없습니다</p>
    </div>
  </div>
);
```

---

## Step 6: Smoke Test (선택사항, TODO 가능)

```typescript
// admin_ui/src/__tests__/OperationsViews.test.tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import OperationsDashboardView from "../components/OperationsDashboardView";

test("renders dashboard page heading", () => {
  render(
    <MemoryRouter>
      <OperationsDashboardView />
    </MemoryRouter>
  );
  expect(screen.getByText("운영 대시보드")).toBeInTheDocument();
});
```

---

## 변경 요약 (Before ↔ After)

| 항목 | Before (Phase 1) | After (Phase 2) |
|------|-------------------|------------------|
| `/` (index) | Dashboard (legacy) | OperationsDashboardView |
| `Dashboard` 접근 | `/` | `/overview` (메뉴 숨김 또는 기타) |
| Layout "개요" | 기본 운영 섹션 1번째 | 제거 또는 기타 섹션 |
| OperationsDashboardView | 12개 StatusCard + 2개 DataTable 모두 mock | real API + Promise.allSettled + 실패 API 표시 |
| OperationsAlertsView | mock alerts 5건 + mock notes 3건 | derived alerts (8개 규칙) + static notes 유지 |
| OrderTrackingView | mock orders 6건 + mock detail | getOrders() + getOrderDetail/Events/BrokerOrders + /orders/:id 링크 |
| Loading/Error/Empty | 없음 | LoadingSpinner / ErrorBanner + 재시도 / empty state |
| API 실패 처리 | 없음 | apiErrors 배열 → 화면 하단 경고 영역 |
| 수정 파일 수 | 2개 (App.tsx, Layout.tsx) | 5개 (기능 보존) |

---

## 검증 명령어

```bash
cd admin_ui && npm run build
cd admin_ui && npm run test:run
```

---

## 최종 보고서 포함 항목

1. mock 제거 여부 (모든 View에서 완전 제거)
2. 실제 연결한 API 목록
3. 메뉴/라우트 변경 내용
4. API 실패 시 표시 방식
5. build/test 결과
6. 남은 TODO (smoke test 등)
