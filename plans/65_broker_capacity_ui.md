# Broker Capacity UI 연동 계획

## 목표

이미 구현된 백엔드 `GET /broker-capacity` 엔드포인트를 Admin UI Dashboard에 연결하여, 운영자가 REST budget 및 WebSocket subscription 상태를 실시간으로 확인할 수 있도록 한다.

## 변경 제한 사항

- backend enforcement 로직 변경 금지
- broker submit semantics 변경 금지
- admin UI 전체 리디자인 금지
- write 기능 없음, 순수 read-only

---

## 현재 상태 분석

### 백엔드 응답 스키마 (`src/agent_trading/api/schemas.py`)

```python
class BucketSnapshot(BaseModel):
    remaining: float
    capacity: float
    refill_rate: float
    utilization: float

class WsSubscriptionSnapshot(BaseModel):
    max_subscriptions: int
    critical_limit: int
    optional_limit: int
    current_critical: int
    current_optional: int
    total_used: int
    remaining: int

class BrokerCapacityResponse(BaseModel):
    broker_name: str
    environment: str
    rest_budget: dict[str, BucketSnapshot]  # key: auth/order/inquiry/reconciliation/market_data
    can_accept_new_entries: bool
    websocket: WsSubscriptionSnapshot
    market_data_subscriptions: int
    order_event_accounts: list[str]
```

### 에러 처리 (백엔드)

- broker_adapter가 없으면 → **503** `"Broker adapter not configured"`
- budget_manager가 없으면 → rest_budget = `{}`, can_accept = `false`
- subscription_budget이 없으면 → ws_snapshot = all zeros

### 프론트엔드 현재 상태

- `admin_ui/src/types/api.ts` — `BrokerCapacityResponse`, `BucketSnapshot`, `WsSubscriptionSnapshot` 타입 **없음**
- `admin_ui/src/api/client.ts` — `getBrokerCapacity()` **없음**
- `admin_ui/src/components/Dashboard.tsx` — 6개 MetricCard + Account Quick List + Recent Orders + Active Locks 섹션으로 구성

---

## 구현 계획

### Step 1: 타입 정의 추가 (`admin_ui/src/types/api.ts`)

`BucketSnapshot`, `WsSubscriptionSnapshot`, `BrokerCapacityResponse` 인터페이스 추가

```typescript
export interface BucketSnapshot {
  remaining: number;
  capacity: number;
  refill_rate: number;
  utilization: number;
}

export interface WsSubscriptionSnapshot {
  max_subscriptions: number;
  critical_limit: number;
  optional_limit: number;
  current_critical: number;
  current_optional: number;
  total_used: number;
  remaining: number;
}

export interface BrokerCapacityResponse {
  broker_name: string;
  environment: string;
  rest_budget: Record<string, BucketSnapshot>;
  can_accept_new_entries: boolean;
  websocket: WsSubscriptionSnapshot;
  market_data_subscriptions: number;
  order_event_accounts: string[];
}
```

### Step 2: API client helper 추가 (`admin_ui/src/api/client.ts`)

```typescript
export async function getBrokerCapacity(): Promise<BrokerCapacityResponse> {
  return request<BrokerCapacityResponse>("/broker-capacity");
}
```

### Step 3: BrokerCapacityPanel 컴포넌트 생성 (`admin_ui/src/components/BrokerCapacityPanel.tsx`)

Dashboard 하단에 배치될 전용 패널 컴포넌트. 독립적인 fetch 생명주기를 가진다.

**상태 관리:**
- `capacity: BrokerCapacityResponse | null`
- `loading: boolean`
- `error: string | null`

**렌더링 구조 (Dashboard Active Locks 섹션과 동일한 패턴):**

```
┌─ Broker Capacity ──────────────────────────────────────┐
│ broker_name · environment    can_accept_new_entries: ✅ │
│                                                        │
│ ┌─ REST Budget ──────────────────────────────────────┐ │
│ │ auth:      remaining / capacity (utilization %)    │ │
│ │ order:     remaining / capacity (utilization %)    │ │
│ │ inquiry:   remaining / capacity (utilization %)    │ │
│ │ reconciliation: remaining / capacity (util %)      │ │
│ │ market_data: remaining / capacity (utilization %)  │ │
│ └────────────────────────────────────────────────────┘ │
│                                                        │
│ ┌─ WebSocket ────────────────────────────────────────┐ │
│ │ Subscriptions:  used / max  |  Remaining: N       │ │
│ │ Critical: current_critical / critical_limit        │ │
│ │ Optional: current_optional / optional_limit        │ │
│ │ Market data subs: N  |  Order event accts: N      │ │
│ └────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
```

**상태 처리:**
- **loading**: `LoadingSpinner` 표시
- **error** (503 포함): `ErrorBanner` 또는 inline 메시지 `"Broker capacity information is not available in this runtime."`
- **정상 데이터**: 위 테이블 형식으로 표시

**디자인 포인트:**
- 기존 Dashboard 섹션 (Active Locks, Recent Orders)와 동일한 `bg-white rounded-xl border border-[#e2e8f0]` 컨테이너 사용
- `can_accept_new_entries`는 `StatusBadge` (success/warning) 활용
- REST budget 항목은 remaining/capacity 막대바(progress bar) 형태로 시각화
- 활용률(utilization)이 80% 이상이면 warning 색상 적용

### Step 4: Dashboard.tsx에 BrokerCapacityPanel 통합

**fetchAll과 독립적으로** BrokerCapacityPanel이 자체 fetch 하도록 설계 (Dashboard의 fetchAll에 묶지 않음)

- Dashboard의 main render 영역, Active Locks 섹션 **다음**에 BrokerCapacityPanel 배치
- Dashboard의 기존 loading/error/empty 상태와 무관하게 동작
- BrokerCapacityPanel 내부에서 자체 loading/error 처리

```tsx
// Dashboard.tsx main render (line ~544, before closing </div>)
<BrokerCapacityPanel />
```

### Step 5: Fixture 데이터 추가 (`admin_ui/src/__tests__/test-utils/fixtures.ts`)

```typescript
export const mockBrokerCapacity: BrokerCapacityResponse = {
  broker_name: "koreainvestment",
  environment: "paper",
  rest_budget: {
    auth: { remaining: 1, capacity: 1, refill_rate: 0.1, utilization: 0 },
    order: { remaining: 5, capacity: 8, refill_rate: 0.5, utilization: 0.375 },
    inquiry: { remaining: 15, capacity: 20, refill_rate: 2.0, utilization: 0.25 },
    reconciliation: { remaining: 3, capacity: 5, refill_rate: 0.5, utilization: 0.4 },
    market_data: { remaining: 10, capacity: 10, refill_rate: 1.0, utilization: 0 },
  },
  can_accept_new_entries: true,
  websocket: {
    max_subscriptions: 50,
    critical_limit: 40,
    optional_limit: 10,
    current_critical: 5,
    current_optional: 2,
    total_used: 7,
    remaining: 43,
  },
  market_data_subscriptions: 3,
  order_event_accounts: ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00a1"],
};
```

### Step 6: 테스트 파일 생성 (`admin_ui/src/__tests__/BrokerCapacityPanel.test.tsx`)

**테스트 케이스:**

1. **정상 렌더링** — broker-capacity fetch 성공 시 broker_name, environment, REST budget, WS usage 표시 확인
2. **503 에러** — `"capacity inspection unavailable in this runtime"` 또는 `"not available"` 메시지 확인
3. **네트워크 에러** — ErrorBanner 또는 에러 메시지 표시 확인
4. **can_accept_new_entries=false** — warning 표시 확인 (StatusBadge variant)

**Dashboard 테스트 영향 없음**: BrokerCapacityPanel은 Dashboard의 fetchAll과 독립적이므로 기존 dashboard.test.tsx 수정 불필요

### Step 7: 빌드 검증

```bash
cd admin_ui && npx vitest run && npm run build
```

---

## 추가/수정 파일 목록

| 파일 | 작업 | 설명 |
|------|------|------|
| `admin_ui/src/types/api.ts` | 수정 | `BucketSnapshot`, `WsSubscriptionSnapshot`, `BrokerCapacityResponse` 타입 추가 |
| `admin_ui/src/api/client.ts` | 수정 | `getBrokerCapacity()` 함수 추가 |
| `admin_ui/src/components/BrokerCapacityPanel.tsx` | **생성** | Broker Capacity 전용 패널 컴포넌트 |
| `admin_ui/src/components/Dashboard.tsx` | 수정 | Active Locks 섹션 아래에 `<BrokerCapacityPanel />` 추가 |
| `admin_ui/src/__tests__/test-utils/fixtures.ts` | 수정 | `mockBrokerCapacity` fixture 추가 |
| `admin_ui/src/__tests__/BrokerCapacityPanel.test.tsx` | **생성** | BrokerCapacityPanel 단위 테스트 |

---

## 시각적 설계

```
┌──────────────────────────────────────────────────────────────┐
│  Overview                                                    │
│  Account and position summary                                │
├──────────────────────────────────────────────────────────────┤
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐     │
│ │Total │ │Avail │ │Posit │ │Recent│ │Active│ │Incom │     │
│ │Accnts│ │Cash  │ │ions  │ │Orders│ │Locks │ │Recon │     │
│ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘     │
│                                                              │
│ Accounts table...                                            │
│ Recent Orders section...                                     │
│ Active Locks section...                                      │
│                                                              │
│ ┌─ Broker Capacity ────────────────────────────────────────┐ │
│ │ KoreaInvestment · paper  |  Accepting new entries: ✅    │ │
│ │                                                          │ │
│ │ REST Budget                                              │ │
│ │ auth          ██████████░░░░  1/1  (0%)                  │ │
│ │ order         ████████░░░░░░  5/8  (37%)                 │ │
│ │ inquiry       ██████████░░░░  15/20 (25%)                │ │
│ │ reconciliation██████░░░░░░░░  3/5  (40%)                 │ │
│ │ market_data   ██████████████  10/10 (0%)                 │ │
│ │                                                          │ │
│ │ WebSocket                                                │ │
│ │ Subscriptions: 7 / 50  |  Remaining: 43                 │ │
│ │ Critical: 5 / 40  |  Optional: 2 / 10                   │ │
│ │ Market data subs: 3  |  Order event accounts: 1         │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 운영자 판단 포인트

1. **can_accept_new_entries**: false면 broker에 새 주문을 제출할 수 없는 상태 → 즉시 조치 필요
2. **REST budget exhaustion**: 특정 operation의 remaining이 0에 가까우면 rate limit budget이 소진된 상태
3. **WS subscription exhaustion**: remaining이 0에 가까우면 더 이상 실시간 데이터 구독 불가
4. **utilization 80%+**: warning 색상으로 표시하여 선제적 대응 유도
