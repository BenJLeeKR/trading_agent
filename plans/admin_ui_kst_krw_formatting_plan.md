# Admin UI KST/KRW Formatting Implementation Plan

## Current State Summary

### Time Formatting (Browser Local, Non-KST) — 23 instances across 10 components

| # | Component | File | Current Pattern | Issue |
|---|-----------|------|-----------------|-------|
| 1 | AgentRunsTable.tsx:18 | `formatTime()` | `toLocaleTimeString("en-US")` | Browser local |
| 2 | AgentRunDetailPanel.tsx:9 | `formatTime()` | `toLocaleString("en-US")` | Browser local |
| 3 | AccountsView.tsx:49 | `formatSnapshotTime()` | `d.getHours()`, `getTimezoneOffset()` | Browser local + local TZ |
| 4 | OrderTrackingView.tsx:59 | `formatTime()` | `toLocaleString("ko-KR")` | Browser local |
| 5 | Dashboard.tsx | inline | `toLocaleTimeString("ko-KR")`, `toLocaleDateString()` | Browser local |
| 6 | BrokerCapacityPanel.tsx:172 | inline | `toLocaleTimeString("ko-KR")` | Browser local |
| 7 | ReconciliationView.tsx:214,219,513,516 | inline | `toLocaleDateString()`, `toLocaleTimeString()` | Browser local |
| 8 | ReconciliationView.tsx:592,597,691 | inline | `toLocaleString()` | Browser local |
| 9 | DecisionsView.tsx:138,265,351 | inline | `toLocaleString()` | Browser local |
| 10 | OperationsAlertsView.tsx:528 | inline | `toLocaleString("ko-KR")` | Browser local |
| 11 | AgentRunsPanel.tsx:150 | inline | `toLocaleString()` | Browser local |

### Currency Formatting — 6 instances across 5 components

| # | Component | Current Pattern | Issue |
|---|-----------|-----------------|-------|
| 1 | Dashboard.tsx:27 | `formatCurrency()` → `원` suffix ✅ | OK, but local function |
| 2 | AccountsView.tsx:21 | `formatCurrency()` → `원` for KRW ✅ | OK, but local function |
| 3 | OperationsDashboardView.tsx:88 | `formatCurrency()` → `원` suffix ✅ | OK, but local function |
| 4 | OrderTrackingView.tsx:76 | `formatPrice()` → `$` prefix ❌ | **확인 필요** — 값은 KRW일 가능성高, formatter만 $인 케이스 |
| 5 | ReconciliationView.tsx:257,418 | `toLocaleString()` plain number ❌ | No suffix |

### Key Findings

### Key Implementation Decisions (피드백 반영)

1. **`formatKrw()` null/undefined/NaN 방어** — 세 가지 case 모두 `"—"` 반환 (`"—"`는 em-dash, 숫자 부재 시 명시적 UI 표시)
2. **`formatKstElapsed()` vs `formatKstDateTime()` 역할 분리**:
   - `formatKstDateTime()` — 절대 시각만: `2026-05-15 14:32:44 KST`
   - `formatKstElapsed()` — 상대 시각 중심: `2026-05-15 14:32:44 KST (3분 전)`
   - AccountsView에서 두 용도를 혼용하지 않음
3. **`OrderTrackingView.formatPrice($)` — 값 검증 후 처리**:
   - 해당 price field가 KRW인지 USD인지 확인
   - KRW면 `formatKrw()`로 교체
   - 다른 통화 가능성 있으면 TODO 주석 남기고 일단 KRW 기준 통일


1. **No shared formatters exist** — [`admin_ui/src/lib/utils.ts`](admin_ui/src/lib/utils.ts) only has `cn()` function
2. **All 23 time displays use browser local time** — `toLocaleString()`, `toLocaleTimeString()`, `getHours()` are all browser-local
3. **`formatSnapshotTime()` in AccountsView.tsx** is the most complex — builds datetime + UTC offset + elapsed text, all browser-local
4. **`formatPrice()` in OrderTrackingView.tsx** uses `$` prefix — clearly a leftover, Korean stocks are KRW
5. **`원` suffix pattern is already correct** in 3 components (Dashboard, AccountsView, OperationsDashboardView) — these local functions can be the basis for shared `formatKrw()`
6. **DB stores UTC** — no data transformation needed, only display conversion

---

## Implementation Plan

### Step 1: Add Shared Formatters to `admin_ui/src/lib/utils.ts`

Three new functions:

#### `formatKstDateTime(iso: string | null, options?: { showSeconds?: boolean }): string`
- Fixed KST via `Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", ... })`
- Full datetime: `2026-05-15 14:32:44`
- Null-safe → returns `"—"`
- Always append ` KST` suffix

#### `formatKstTime(iso: string | null): string`
- Short time via `Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", ... })`
- Format: `05-15 14:32` (month-day hour:min)
- Used for compact table displays
- Null-safe → returns `"—"`

#### `formatKrw(val: number | null | undefined): string`
- KRW currency via `Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 })`
- Format: `145,400원`
- Negative: `-5,000원`
- Zero: `0원`
- Null/NaN → returns `"—"`
- **No decimal places** for KRW

#### `formatKstElapsed(iso: string | null): string`
- AccountsView `formatSnapshotTime()` replacement component
- Returns: `2026-05-15 14:32:44 KST (방금 전)`
- Elapsed time logic preserved from original `formatSnapshotTime()`

---

### Step 2–12: Component Modifications (Execution Order)

| Step | File | Change | Risk |
|------|------|--------|------|
| 2 | [`AgentRunsTable.tsx`](admin_ui/src/components/AgentRunsTable.tsx:18) | Remove `formatTime()`, import `formatKstTime` | Low |
| 3 | [`AgentRunDetailPanel.tsx`](admin_ui/src/components/AgentRunDetailPanel.tsx:9) | Remove `formatTime()`, import `formatKstDateTime` | Low |
| 4 | [`AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx:21,49) | Replace `formatCurrency()` + `formatSnapshotTime()` with shared formatters; keep local `formatQty()` | Medium |
| 5 | [`OrderTrackingView.tsx`](admin_ui/src/components/OrderTrackingView.tsx:59,76) | Replace `formatTime()` + `formatPrice($)` with `formatKstDateTime` + `formatKrw` | Medium |
| 6 | [`Dashboard.tsx`](admin_ui/src/components/Dashboard.tsx) | Replace `formatCurrency()` + inline time with shared formatters | Low |
| 7 | [`BrokerCapacityPanel.tsx`](admin_ui/src/components/BrokerCapacityPanel.tsx:172) | Replace `toLocaleTimeString("ko-KR")` with `formatKstTime` | Low |
| 8 | [`ReconciliationView.tsx`](admin_ui/src/components/ReconciliationView.tsx) | Replace 8 instances of time/currency formatting | Medium |
| 9 | [`DecisionsView.tsx`](admin_ui/src/components/DecisionsView.tsx:138,265,351) | Replace 3 `toLocaleString()` with `formatKstDateTime` | Low |
| 10 | [`OperationsAlertsView.tsx`](admin_ui/src/components/OperationsAlertsView.tsx:528) | Replace `toLocaleString("ko-KR")` with `formatKstDateTime` | Low |
| 11 | [`AgentRunsPanel.tsx`](admin_ui/src/components/AgentRunsPanel.tsx:150) | Replace `toLocaleString()` with `formatKstDateTime` | Low |
| 12 | [`OperationsDashboardView.tsx`](admin_ui/src/components/OperationsDashboardView.tsx:88) | Replace local `formatCurrency()` with shared `formatKrw` | Low |

---

### Architecture Decision: KST Timezone Strategy

Use **`Intl.DateTimeFormat`** with `{ timeZone: "Asia/Seoul" }` for all time formatting:

```typescript
const KST_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
```

**Why not `date-fns-tz` or `luxon`?**
- Avoid adding new dependencies for a simple formatting task
- `Intl.DateTimeFormat` is natively available in all modern browsers and Node.js
- The project (React + Vite) supports it out of the box

**Why not `toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })`?**
- Actually, this IS the recommended approach. `Intl.DateTimeFormat` is the object form of the same API.
- Implementation choice: use `Intl.DateTimeFormat` for reusable instances (performance) or inline `toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })`.

**Decision:** Pre-create `Intl.DateTimeFormat` instances at module level for performance (avoid recreating on every render).

---

### Key Implementation Details

#### `formatSnapshotTime()` Replacement Strategy

The current [`formatSnapshotTime()`](admin_ui/src/components/AccountsView.tsx:49) is complex:
- Builds datetime from browser-local `getFullYear()`, `getHours()`, etc.
- Calculates UTC offset from browser `getTimezoneOffset()` (variable!)
- Shows elapsed time: "방금 전", "5분 전", "2시간 30분 전", "3일 전"

**Replacement:** Create `formatKstElapsed()` in utils.ts:
- Use `Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul" })` for datetime part
- Hardcode `KST` instead of dynamic UTC offset
- Keep elapsed time logic (it's a relative calculation, independent of timezone)
- Return format: `2026-05-15 14:32:44 KST (방금 전)`

#### `formatPrice()` `$` → `원` Fix (값 검증 후 진행)

[`OrderTrackingView.tsx:76`](admin_ui/src/components/OrderTrackingView.tsx:76) uses `$` prefix:
```typescript
return `$${num.toFixed(2)}`;
```

**선행 확인:** 이 price field가 정말 KRW price인지 확인 필요.
- `OrderSummary` / `BrokerOrderView` 타입에서 해당 필드 정의 확인
- 한국 주식만 거래하는 현재 운영 범위에서는 KRW가 맞을 것
- 만약 다른 통화 가능성이 있다면 `TODO` 주석 남기고 KRW 기준 통일

**수정:** `formatKrw()`로 교체:
- `formatKrw(145400)` → `145,400원`
- No decimal places for KRW

#### ReconciliationView Price Display

Two instances use [`toLocaleString()`](admin_ui/src/components/ReconciliationView.tsx:257) for prices:
```typescript
r.order.requested_price?.toLocaleString() ?? "—"
```
Replace with `formatKrw()`.

---

### Risks and Considerations

1. **`OrderTrackingView.tsx` price context:** The `formatPrice()` function receives price values without currency context. If some prices are USD (e.g., US stocks), we need to handle both currencies. Based on project scope (Korean stocks), assume all KRW.

2. **AccountsView `formatCurrency()` supports multiple currencies:** Current implementation checks `currency === "KRW"` vs others. Keep this logic in the shared `formatKrw()` or create a general `formatCurrency(val, currency)` in utils.ts.

3. **Elapsed time in `formatSnapshotTime()` is relative to "now":** The elapsed calculation (`방금 전`, `5분 전`) will continue to use `new Date()` (current time). This is acceptable — elapsed time is inherently relative. The datetime part will use fixed KST.

4. **Backward compatibility:** These are purely display changes. No backend API changes, no DB changes, no data model changes. All ISO strings remain UTC.

---

### Verification

After all changes:
```bash
cd /workspace/agent_trading/admin_ui
npm run build
```

Check for:
- No TypeScript compilation errors
- No linting errors
- All time displays show `KST` suffix (not browser offset)
- All currency displays show `원` suffix (not `$` or plain numbers)
