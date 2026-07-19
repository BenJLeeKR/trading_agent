# OrderTrackingView / OrderDetail — 상태 전이 타임라인 응답 매핑 Hotfix

**작성일**: 2026-05-17  
**상태**: 설계 (Architect 모드)  
**구현 모드**: Code

---

## 1. Root Cause

`GET /orders/{id}/events` 백엔드 API 응답 필드명과 프런트엔드 [`OrderEvent`](admin_ui/src/types/api.ts:56) 타입 및 [`eventColumns`](admin_ui/src/components/OrderTrackingView.tsx:105) 컬럼 매핑이 **6/6 전부 불일치**하여, 타임라인 테이블이 빈 셀(`undefined`)로 렌더링된다.

### 백엔드 실제 응답 shape

[`src/agent_trading/api/schemas.py:152`](src/agent_trading/api/schemas.py:152) — `OrderEvent` Pydantic 모델:

```python
class OrderEvent(BaseModel):
    order_state_event_id: str
    previous_status: str | None = None
    new_status: str
    event_source: str
    event_timestamp: datetime
    reason_code: str | None = None
    correlation_id: str | None = None
    created_at: datetime | None = None
```

[`src/agent_trading/api/routes/orders.py:168`](src/agent_trading/api/routes/orders.py:168) — 실제 응답 빌드 로직도 동일.

### 현재 프런트엔드 타입 (잘못됨)

[`admin_ui/src/types/api.ts:56`](admin_ui/src/types/api.ts:56):

```typescript
export interface OrderEvent {
  event_id: string;
  order_request_id: string;
  from_status: string;
  to_status: string;
  reason: string;
  timestamp: string;
}
```

---

## 2. 불일치 매핑표 (변경 전 → 변경 후)

| # | 프런트 (현재) | 백엔드 (실제) | 액션 | Nullable? | 비고 |
|---|---------------|---------------|------|-----------|------|
| 1 | `event_id` | `order_state_event_id` | **Rename** | No | PK 매핑 |
| 2 | `order_request_id` | 없음 | **Remove** | — | 백엔드 미반환 |
| 3 | `from_status` | `previous_status` | **Rename** | Yes | 첫 이벤트는 null 가능 |
| 4 | `to_status` | `new_status` | **Rename** | No | 항상 존재 |
| 5 | `reason` | `reason_code` | **Rename** | Yes | null 허용 |
| 6 | `timestamp` | `event_timestamp` | **Rename** | No | ISO 8601 datetime |
| 7 | 없음 | `event_source` | **Add** | No | 항상 문자열 |
| 8 | 없음 | `correlation_id` | **Add (선택)** | Yes | ui 미노출 |
| 9 | 없음 | `created_at` | **Add (선택)** | Yes | ui 미노출 |

---

## 3. 파일별 변경 상세

### 3.1 [`admin_ui/src/types/api.ts`](admin_ui/src/types/api.ts) — `OrderEvent` 타입 재정의

**변경 전** (L56-63):

```typescript
export interface OrderEvent {
  event_id: string;
  order_request_id: string;
  from_status: string;
  to_status: string;
  reason: string;
  timestamp: string;
}
```

**변경 후**:

```typescript
export interface OrderEvent {
  order_state_event_id: string;
  previous_status: string | null;
  new_status: string;
  event_source: string;
  event_timestamp: string;
  reason_code: string | null;
  correlation_id?: string | null;
  created_at?: string | null;
}
```

변경 로직:
- `event_id` → `order_state_event_id` (string, non-null)
- `order_request_id` 제거
- `from_status` → `previous_status` (string | null)
- `to_status` → `new_status` (string)
- `reason` → `reason_code` (string | null)
- `timestamp` → `event_timestamp` (string)
- `event_source` 추가 (string, non-null)
- `correlation_id`, `created_at`는 선택적 옵셔널로 추가 (UI 미사용)

---

### 3.2 [`admin_ui/src/components/OrderTrackingView.tsx`](admin_ui/src/components/OrderTrackingView.tsx)

#### 3.2.1 `eventColumns` — 컬럼 키 변경 (L105-110)

```typescript
// 변경 전
const eventColumns: Column<OrderEvent>[] = [
  { key: "from_status", header: "이전 상태", width: "100px", render: (row) => statusLabel(row.from_status) },
  { key: "to_status",   header: "이후 상태", width: "100px", render: (row) => statusLabel(row.to_status) },
  { key: "timestamp",   header: "시간",      width: "150px", render: (row) => formatKstDateTime(row.timestamp) },
  { key: "reason",      header: "사유" },
];

// 변경 후
const eventColumns: Column<OrderEvent>[] = [
  { key: "previous_status", header: "이전 상태", width: "100px", render: (row) => statusLabel(row.previous_status ?? "") },
  { key: "new_status",      header: "이후 상태", width: "100px", render: (row) => statusLabel(row.new_status) },
  { key: "event_timestamp", header: "시간",      width: "150px", render: (row) => formatKstDateTime(row.event_timestamp) },
  { key: "reason_code",     header: "사유" },
  // event_source는 tooltip 또는 보조 컬럼으로 선택적 노출
  { key: "event_source",    header: "소스",      width: "90px" },
];
```

**설계 결정**: `event_source` 컬럼을 추가하되, 사용자 피드백에 따라 제거 가능. 기본적으로는 노출하여 디버깅 편의성 확보.

#### 3.2.2 `idKey` 변경 (L367)

```typescript
// 변경 전
<DataTable columns={eventColumns} data={orderEvents} idKey="event_id" compact />

// 변경 후
<DataTable columns={eventColumns} data={orderEvents} idKey="order_state_event_id" compact />
```

#### 3.2.3 `statusLabel()` 보강 (L32-44)

**현재 8/12 커버 → 모든 12개 OrderStatus 커버**

```typescript
function statusLabel(status: string): string {
  const map: Record<string, string> = {
    draft: "초안",
    validated: "검증됨",
    pending_submit: "제출 대기",
    submitted: "제출됨",
    acknowledged: "접수됨",
    partially_filled: "부분체결",
    filled: "체결",
    cancelled: "취소됨",
    cancel_pending: "취소 대기",
    rejected: "거부됨",
    expired: "만료",
    pending: "대기",
    reconcile_required: "조정필요",
  };
  return map[status] ?? status;
}
```

**누락 추가**: `draft`, `validated`, `pending_submit`, `cancel_pending`, `expired`

---

### 3.3 [`admin_ui/src/components/OrderDetail.tsx`](admin_ui/src/components/OrderDetail.tsx)

#### 3.3.1 `eventColumns` — 컬럼 키 변경 (L48-69)

```typescript
// 변경 전
const eventColumns: Column<OrderEvent>[] = [
  { key: "timestamp",    header: "시각" },
  { key: "from_status",  header: "이전", render: (r) => <StatusBadge ...>{getEnumLabel(fieldMap, "order_status", r.from_status)}</StatusBadge> },
  { key: "to_status",    header: "이후", render: (r) => <StatusBadge ...>{getEnumLabel(fieldMap, "order_status", r.to_status)}</StatusBadge> },
  { key: "reason",       header: "사유" },
];

// 변경 후
const eventColumns: Column<OrderEvent>[] = [
  { key: "event_timestamp", header: "시각" },
  { key: "previous_status", header: "이전", render: (r) => <StatusBadge ...>{getEnumLabel(fieldMap, "order_status", r.previous_status ?? "")}</StatusBadge> },
  { key: "new_status",      header: "이후", render: (r) => <StatusBadge ...>{getEnumLabel(fieldMap, "order_status", r.new_status)}</StatusBadge> },
  { key: "reason_code",     header: "사유" },
];
```

#### 3.3.2 `idKey` 변경 (L214)

```typescript
// 변경 전
<DataTable columns={eventColumns} data={events} idKey="event_id" ... />

// 변경 후
<DataTable columns={eventColumns} data={events} idKey="order_state_event_id" ... />
```

---

### 3.4 [`admin_ui/src/__tests__/test-utils/fixtures.ts`](admin_ui/src/__tests__/test-utils/fixtures.ts)

#### 3.4.1 `mockOrderEvents` — 실제 응답 shape에 맞게 업데이트 (L187-204)

```typescript
// 변경 전
export const mockOrderEvents: OrderEvent[] = [
  {
    event_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00e1",
    order_request_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee0001",
    from_status: "pending_submit",
    to_status: "submitted",
    reason: "Order submitted to broker",
    timestamp: "2026-05-05T00:00:01Z",
  },
  ...
];

// 변경 후
export const mockOrderEvents: OrderEvent[] = [
  {
    order_state_event_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00e1",
    previous_status: null,           // 첫 이벤트는 이전 상태 없음
    new_status: "submitted",
    event_source: "INTERNAL",
    event_timestamp: "2026-05-05T00:00:01Z",
    reason_code: null,
  },
  {
    order_state_event_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeee00e2",
    previous_status: "submitted",
    new_status: "filled",
    event_source: "BROKER",
    event_timestamp: "2026-05-05T00:00:05Z",
    reason_code: "FILL_CONFIRMED",
  },
];
```

---

### 3.5 [`admin_ui/src/__tests__/orderDetail.test.tsx`](admin_ui/src/__tests__/orderDetail.test.tsx)

영향받는 테스트 케이스 — L130-131:
```typescript
// 현재: 백엔드가 반환하지 않는 문자열을 찾고 있음 → 테스트 실패
expect(screen.getByText("Order submitted to broker")).toBeInTheDocument();
expect(screen.getByText("Fill confirmed by broker")).toBeInTheDocument();
```

이 두 줄은 `r.reason` (구 `reason` 필드) 값을 찾고 있었으나, 백엔드는 `reason_code`만 반환.
변경 후 `mockOrderEvents`의 `reason_code`가 `null` / `"FILL_CONFIRMED"` 이므로, 어설션 대상 변경 필요.

```typescript
// 변경 후
// reason_code가 null인 경우 테이블에 빈 문자열("-" 등)로 표시됨
// DataTable의 기본 렌더링은 null/undefined를 빈 문자열로 처리
// 따라서 "Order submitted to broker" 텍스트는 더 이상 존재하지 않음
expect(screen.getByText("FILL_CONFIRMED")).toBeInTheDocument();
```

---

### 3.6 신규 테스트 파일: [`admin_ui/src/__tests__/orderTrackingView.test.tsx`](admin_ui/src/__tests__/orderTrackingView.test.tsx)

`OrderTrackingView` 컴포넌트에 대한 신규 테스트 파일 작성.  
(현재 `OrderTrackingView` 테스트가 전혀 존재하지 않음)

테스트 케이스:

| # | 테스트명 | 검증 내용 |
|---|----------|-----------|
| 1 | `renders order list in DataTable` | 주문 목록 정상 렌더링 |
| 2 | `renders event timeline with correct field mappings` | `previous_status` / `new_status` / `event_timestamp` / `reason_code` 컬럼 표시 |
| 3 | `event_timestamp displays KST formatted datetime` | `formatKstDateTime` 적용 확인 |
| 4 | `handles reason_code=null gracefully` | null 사유코드에서도 테이블 정상 렌더 |
| 5 | `idKey="order_state_event_id" does not cause row key errors` | row key 회귀 없음 |
| 6 | `statusLabel covers all 12 order statuses` | 누락된 상태 5개에 대한 레이블 표시 확인 |
| 7 | `column headers match new field names` | 컬럼 헤더 "이전 상태", "이후 상태", "시간", "사유", "소스" 확인 |

---

## 4. `statusLabel()` 보강 내역

| 상태 값 | 한글 레이블 | 기존 포함? |
|---------|------------|-----------|
| `draft` | 초안 | ❌ 누락 → 추가 |
| `validated` | 검증됨 | ❌ 누락 → 추가 |
| `pending_submit` | 제출 대기 | ❌ 누락 → 추가 |
| `submitted` | 제출됨 | ✅ |
| `acknowledged` | 접수됨 | ✅ |
| `partially_filled` | 부분체결 | ✅ |
| `filled` | 체결 | ✅ |
| `cancel_pending` | 취소 대기 | ❌ 누락 → 추가 |
| `cancelled` | 취소됨 | ✅ |
| `rejected` | 거부됨 | ✅ |
| `expired` | 만료 | ❌ 누락 → 추가 |
| `pending` | 대기 | ✅ |
| `reconcile_required` | 조정필요 | ✅ |

---

## 5. 테스트 계획

### 5.1 기존 테스트 수정

| 파일 | 수정 내용 |
|------|----------|
| [`admin_ui/src/__tests__/orderDetail.test.tsx`](admin_ui/src/__tests__/orderDetail.test.tsx) | L130-131: `reason` 필드값 어설션 → `reason_code` 기반으로 변경 |
| [`admin_ui/src/__tests__/orderDetail.test.tsx`](admin_ui/src/__tests__/orderDetail.test.tsx) | 컬럼 헤더는 "시각", "이전", "이후", "사유" 로 유지되어 변경 불필요 |

### 5.2 신규 테스트 (`orderTrackingView.test.tsx`)

위 3.6 항목 참조.

### 5.3 빌드 검증

```bash
cd admin_ui && npm run build
```

TypeScript 컴파일 에러 없이 통과해야 함.  
변경된 타입 정의로 인해 기존 `OrderEvent` 참조 코드에서 타입 에러가 발생하지 않는지 확인.

---

## 6. 리스크 분석

| 리스크 | 영향 | 완화 방안 |
|--------|------|-----------|
| `reason_code`가 null인 경우 테이블 셀이 비어 보임 | UX 저하 가능성 낮음 | `render` 함수에서 `reason_code ?? "-"` 처리 |
| `previous_status`가 null인 첫 이벤트에서 `statusLabel("")` 호출 | "이전 상태" 셀에 빈 값 표시 | `statusLabel(row.previous_status ?? "")` → 빈 문자열은 그대로 반환됨 |
| `event_source` 컬럼 추가로 컬럼 너비 증가 | 레이아웃 변경 | `width: "90px"`로 최소화, 추후 제거 가능 |
| 기존 `orderDetail.test.tsx`의 이벤트 데이터 어설션 실패 | CI 실패 | 테스트 픽스처 및 어설션 함께 수정 |
| `npm run build` 타입 에러 | 빌드 차단 | `OrderEvent` 타입 변경 시 모든 참조처 일괄 수정해야 함 |

### 타입 안전성

`OrderEvent`의 필드명 변경으로 인해 TypeScript 컴파일러가 다음 위치에서 **전부** 타입 에러를 발생시킴:

1. [`OrderTrackingView.tsx:106-109`](admin_ui/src/components/OrderTrackingView.tsx:106) — `eventColumns`의 `key`와 `render`에서 사용하는 필드
2. [`OrderTrackingView.tsx:367`](admin_ui/src/components/OrderTrackingView.tsx:367) — `idKey="event_id"`
3. [`OrderDetail.tsx:49-68`](admin_ui/src/components/OrderDetail.tsx:49) — `eventColumns`
4. [`OrderDetail.tsx:214`](admin_ui/src/components/OrderDetail.tsx:214) — `idKey="event_id"`
5. [`fixtures.ts:187-204`](admin_ui/src/__tests__/test-utils/fixtures.ts:187) — `mockOrderEvents`

→ 따라서 **컴파일러 에러가 모든 변경 지점을 정확히 가리키므로** 누락 없이 전부 수정 가능.

---

## 7. 실행 순서 (Code 모드 지침)

아래 순서대로 변경을 수행할 것:

### Step 1 — `api.ts` 타입 재정의
- [`admin_ui/src/types/api.ts`](admin_ui/src/types/api.ts): `OrderEvent` 인터페이스 재작성 (3.1 참조)

### Step 2 — `fixtures.ts` 픽스처 업데이트
- [`admin_ui/src/__tests__/test-utils/fixtures.ts`](admin_ui/src/__tests__/test-utils/fixtures.ts): `mockOrderEvents` 재작성 (3.4 참조)

### Step 3 — `OrderTrackingView.tsx` 수정
- [`admin_ui/src/components/OrderTrackingView.tsx`](admin_ui/src/components/OrderTrackingView.tsx): 
  1. `eventColumns` 컬럼 키 변경 (3.2.1)
  2. `idKey="order_state_event_id"` 변경 (3.2.2)
  3. `statusLabel()` 보강 (3.2.3)

### Step 4 — `OrderDetail.tsx` 수정
- [`admin_ui/src/components/OrderDetail.tsx`](admin_ui/src/components/OrderDetail.tsx):
  1. `eventColumns` 컬럼 키 변경 (3.3.1)
  2. `idKey="order_state_event_id"` 변경 (3.3.2)

### Step 5 — 기존 테스트 수정
- [`admin_ui/src/__tests__/orderDetail.test.tsx`](admin_ui/src/__tests__/orderDetail.test.tsx): 이벤트 데이터 어설션 수정

### Step 6 — 신규 테스트 작성
- [`admin_ui/src/__tests__/orderTrackingView.test.tsx`](admin_ui/src/__tests__/orderTrackingView.test.tsx): 신규 작성

### Step 7 — 빌드 검증
```bash
cd admin_ui && npm run build
```

---

## 8. 변경 요약 매트릭스

| 파일 | 변경 유형 | 영향 라인 |
|------|----------|-----------|
| `types/api.ts` | 타입 재정의 | L56-63 (7줄) |
| `components/OrderTrackingView.tsx` | 컬럼 키 + idKey + statusLabel | L32-44, L105-110, L367 |
| `components/OrderDetail.tsx` | 컬럼 키 + idKey | L48-69, L214 |
| `__tests__/test-utils/fixtures.ts` | 픽스처 재작성 | L187-204 |
| `__tests__/orderDetail.test.tsx` | 어설션 수정 | L130-131 |
| `__tests__/orderTrackingView.test.tsx` | **신규 파일** | ~120줄 |
