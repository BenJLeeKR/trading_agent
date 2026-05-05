# Phase 2 — Component Composition Refinement

**목표**: Day 4의 "CSS overlay" 수준을 넘어, `design_template`의 **구조적 컴포넌트 패턴** (Layout Shell, Panel, DetailField, SectionDivider, FilterChip, FilterGroup)을 `admin_ui`에 적용하여 v0.dev 템플릿과의 visual parity를 높인다.

**제약 조건** (Phase 1과 동일):
- 백엔드/API/인증 변경 금지
- React Router 구조 변경 금지 (`/orders/:id` 라우트 유지)
- Next.js 마이그레이션 금지
- Write 액션 추가 금지
- 테스트 69개 전손 유지 (`decisions.test.tsx`의 `toHaveStyle("var(--pico-*)")` inline style 반드시 보존)
- `npm run test:run` 및 `npm run build` 통과 의무

---

## Gap Analysis: Current vs Template

### 1. Layout Shell — [`admin-shell.tsx`](design/design_template/src/components/admin/admin-shell.tsx) vs [`Layout.tsx`](admin_ui/src/components/Layout.tsx)

| 항목 | Current | Template | 변경 필요 |
|------|---------|----------|----------|
| Top header bar | 없음 | PageTitle + Search + User avatar + Clock | **P0 신규** |
| Sidebar brand | 텍스트만 | Icon "A" + 회사명 + "Operator Console READ ONLY" | **P0 개선** |
| Nav icons | 없음 | lucide icons (Gauge, ShoppingCart, 등) | **P0 추가** |
| Active indicator | 없음 | ChevronRight 아이콘 | **P0 추가** |
| Version footer | Token/Layout 표시 | "v2.4.1 — build 20230211" | P1 |

**변경 전략**:
- `Layout.tsx`에 top header bar `<header className="top-header">` 추가
- sidebar brand를 styled block으로 업그레이드
- nav 항목에 icon 추가 (lucide-react 사용하지 않고, 간단한 SVG 아이콘 또는 CSS-only 아이콘 사용)
- ChevronRight active indicator를 CSS로 추가
- Token/Layout 정보는 sidebar footer에 유지하되 버전 정보 추가

### 2. Panel Component — [`panel.tsx`](design/design_template/src/components/admin/panel.tsx)

**Template 제공 패턴**:
```tsx
<Panel title="Recent Orders" subtitle="Last 24h" headerRight={<RefreshButton />}>
  ...
</Panel>
```
```tsx
<DetailField label="Side" value="Buy" />
<DetailField label="Quantity" value="1,000" mono />
<SectionDivider label="Order Details" />
```

**변경 전략**: React 컴포넌트 생성 (`Panel`, `DetailField`, `SectionDivider`) + CSS 클래스 추가

**테스트 영향**: Text content 기반 테스트는 영향 없음. DOM 구조 변화가 `getByText()`에 영향 주지 않음.

### 3. Dashboard — [`overview-dashboard.tsx`](design/design_template/src/components/admin/overview-dashboard.tsx) vs [`Dashboard.tsx`](admin_ui/src/components/Dashboard.tsx)

| 항목 | Current | Template | 변경 필요 |
|------|---------|----------|----------|
| Summary cards | value + label 만 | sub-metrics (latency/uptime/replicas/storage) 포함 | **P0 개선** |
| Dashboard body | 순차적 3개 article | flex: left table + right 3 panels (Locks/Reconciliation/Degraded) | **P0 구조 변경** |
| WarningBanner | Health degraded만 | Critical overdue recon runs 포함 | **P0 추가** |

**변경 전략**:
- SummaryCard 컴포넌트에 `MetricRow` children 지원 (CSS 클래스 `.metric-row`)
- Dashboard body를 flex layout으로 변경: left (main content) + right (signals sidebar, 280px)
- WarningBanner를 API 데이터 기반으로 overdue runs 표시
- Database Status panel은 유지하되 Panel wrapper 적용

**테스트 영향**:
- `dashboard.test.tsx`의 "renders summary cards, database status, locks, and orders" — text content 기반으로 변경 없음
- "renders clickable summary cards with correct href" — `<a>` 링크 유지

### 4. DataTable — [`data-table.tsx`](design/design_template/src/components/admin/data-table.tsx) vs [`DataTable.tsx`](admin_ui/src/components/common/DataTable.tsx)

| 항목 | Current | Template | 변경 필요 |
|------|---------|----------|----------|
| Selected row | `outline: 1px solid var(--accent-color)` | `border-l-2 border-l-primary` | **P0 변경** |
| Compact mode | 없음 | `compact` prop으로 cell padding 조절 | **P0 추가** |
| Header style | `text-transform uppercase` | `text-[10px] uppercase tracking-wider text-muted-foreground/70` | P1 (CSS로 처리 가능) |
| Hover style | `oklch(0.20 0.01 240)` | `bg-surface-2/60` | P1 (CSS만 변경) |

**변경 전략**:
- DataTable.tsx에 `compact` prop 추가 → CSS class `table-compact`로 패딩 조절
- CSS에서 `[aria-selected="true"]` 선택자에 `border-left: 2px solid var(--accent-color)` 추가 (outline 유지도 가능하나 template 스타일로 통일)

**테스트 영향**: `components.test.tsx`의 DataTable 테스트는 text content 기반으로 영향 없음.

### 5. Filter Bar — Chip-based Multi-Select

| 화면 | Current Filter | Template Filter | 변경 필요 |
|------|---------------|-----------------|----------|
| OrdersView | `<select>` for Status, Side, `<input>` for symbol | FilterChip toggle buttons (multi-select Set) | **P0 변경** |
| DecisionsView | `<select>` for Side, Type, Confidence, `<input>` for symbol | FilterGroup buttons (single-select) | **P0 변경** |

**변경 전략**:
- FilterChip 컴포넌트 생성 (또는 CSS class 기반 패턴)
- FilterGroup 컴포넌트 생성 (single-select button group)
- OrdersView: symbol filter 제외하고 status/side를 chip 기반 multi-select로 변경
- DecisionsView: side/type/confidence를 FilterGroup으로 변경
- Search input은 유지 (symbol/ticker 검색)

**테스트 영향**:
- `orders.test.tsx` — filter 테스트는 `<select>` 변경 이벤트 대신 `<button>` 클릭으로 변경 필요
  - `"filters orders by status"` → `findAllByRole("button")`로 변경
  - `"filters orders by side"` → 동일
- `decisions.test.tsx` — filter 테스트도 유사 변경
  - **테스트 코드 수정 필요** — 단, 동작 변경은 최소화 (필터 로직은 동일)

### 6. Detail Panel Composition

| 화면 | Current | Template | 변경 필요 |
|------|---------|----------|----------|
| OrderDetail | raw `<article>` with `<header><strong>` | Panel + DetailField + SectionDivider + timeline events | **P0 개선** |
| Reconciliation detail | 없음 (tab 기반) | ReconRunDetail/LockDetail with Panel + DetailField | **P0 추가** |
| Accounts detail | raw `<article>` with inline fields | Panel + DetailField + PnlCard grid | **P0 개선** |
| Decisions detail | raw `<article>` with detail-context-section | DecisionDetailPanel with Panel + ConfidenceBar + DetailField | **P0 개선** |

**변경 전략**: 모든 detail/article을 Panel wrapper로 감싸고, DetailField/SectionDivider 패턴 적용.

### 7. SummaryCard Sub-Metrics

**변경 전략**:
- SummaryCard에 `children` prop 추가 (MetricRow 렌더링용)
- CSS 클래스 `.summary-card-metrics` 와 `.metric-row` 추가
- Dashboard의 card 데이터에 sub-metrics 추가 (latency, uptime 등 — 실제 API 데이터 없으면 mock)

---

## 상세 구현 단계

### Step 1: CSS 확장 (`admin-theme.css`에 추가)

**추가할 CSS 클래스**:

```css
/* 18. Top Header Bar */
.top-header { ... }
.top-header-title { ... }
.top-header-right { ... }
.top-header-search { ... }
.top-header-user { ... }
.top-header-clock { ... }

/* 19. Sidebar Icons & Active Indicator */
.sidebar-brand-icon { ... }
.sidebar-nav-icon { ... }
.sidebar-nav-chevron { ... }

/* 20. Panel Component */
.panel { ... }
.panel-header { ... }
.panel-title { ... }
.panel-subtitle { ... }
.panel-header-right { ... }
.panel-body { ... }
.panel-body--no-padding { ... }

/* 21. DetailField */
.detail-field { ... }
.detail-field-label { ... }
.detail-field-value { ... }
.detail-field-value--mono { ... }

/* 22. SectionDivider */
.section-divider { ... }
.section-divider-label { ... }
.section-divider-line { ... }

/* 23. Filter Chip & Filter Group */
.filter-chips { ... }
.filter-chip { ... }
.filter-chip--active { ... }
.filter-group { ... }
.filter-group-label { ... }
.filter-group-btn { ... }
.filter-group-btn--active { ... }

/* 24. DataTable Compact & Selected Row Accent */
.table-compact td,
.table-compact th { ... }
.table-wrapper tbody tr[aria-selected="true"] { border-left: 2px solid var(--accent-color); }

/* 25. Summary Card Sub-Metrics */
.summary-card-metrics { ... }
.metric-row { ... }
.metric-row-label { ... }
.metric-row-value { ... }
.metric-row-separator { ... }

/* 26. Dashboard Signals Sidebar */
.signals-sidebar { ... }
.signals-sidebar-panel { ... }

/* 27. Detail Side Panel (inline detail) */
.detail-side-panel { ... }

/* 28. Health Label / Status Indicator */
.health-label { ... }
.health-label--ok { ... }
.health-label--degraded { ... }
.health-label--error { ... }
```

### Step 2: 공통 컴포넌트 생성

#### `admin_ui/src/components/common/Panel.tsx`
```tsx
interface PanelProps {
  title?: string;
  subtitle?: string;
  headerRight?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  noPadding?: boolean;
}
export function Panel({ ... }: PanelProps) {
  return (
    <div className={cn("panel", className)}>
      {(title || headerRight) && (
        <div className="panel-header">
          <div>
            {title && <h3 className="panel-title">{title}</h3>}
            {subtitle && <p className="panel-subtitle">{subtitle}</p>}
          </div>
          {headerRight && <div className="panel-header-right">{headerRight}</div>}
        </div>
      )}
      <div className={cn("panel-body", noPadding && "panel-body--no-padding", bodyClassName)}>
        {children}
      </div>
    </div>
  );
}
```

#### `admin_ui/src/components/common/DetailField.tsx`
```tsx
interface DetailFieldProps {
  label: string;
  value: ReactNode;
  mono?: boolean;
}
export function DetailField({ label, value, mono }: DetailFieldProps) {
  return (
    <div className="detail-field">
      <span className="detail-field-label">{label}</span>
      <span className={cn("detail-field-value", mono && "detail-field-value--mono")}>
        {value}
      </span>
    </div>
  );
}
```

#### `admin_ui/src/components/common/SectionDivider.tsx`
```tsx
interface SectionDividerProps {
  label: string;
}
export function SectionDivider({ label }: SectionDividerProps) {
  return (
    <div className="section-divider">
      <span className="section-divider-label">{label}</span>
      <div className="section-divider-line" />
    </div>
  );
}
```

### Step 3: Layout.tsx 업그레이드

**변경 사항**:
1. Sidebar brand를 Icon + 회사명 + "Operator Console · READ ONLY" styled block으로 업그레이드
2. Nav 항목에 SVG 아이콘 추가 (lucide 의존성 없이 간단한 path 아이콘)
3. Nav active 항목에 ChevronRight indicator 추가
4. Top header bar 추가 (PageTitle은 현재 `useLocation()`으로 pathname 기반 렌더링)
5. Search bar (비활성화된 placeholder, 클릭 시 아무 동작 안함 — no backend search)
6. User avatar (고정 "U" 아바타)
7. Clock (고정 시간 — 실제 동적 시계는 불필요)

**구체적 DOM 구조**:
```tsx
<div className="app-shell">
  <aside className="sidebar">
    {/* Brand */}
    <div className="sidebar-brand">
      <div className="sidebar-brand-icon">
        <span>A</span>
      </div>
      <div className="sidebar-brand-text">
        <p className="sidebar-brand-title">AITrading Co.</p>
        <p className="sidebar-brand-subtitle">
          Operator Console <span className="sidebar-brand-badge">· READ ONLY</span>
        </p>
      </div>
    </div>
    {/* Nav */}
    <nav>
      <ul className="sidebar-nav">
        {NAV_ITEMS.map(...)}
      </ul>
    </nav>
    {/* Footer */}
    <div className="sidebar-footer">
      <p>Token: {truncatedToken}</p>
      <p className="sidebar-footer-version">v2.4.1 — build 20260505</p>
    </div>
  </aside>
  <div className="main-area">
    <header className="top-header">
      <div className="top-header-title">{pageTitle}</div>
      <div className="top-header-right">
        <div className="top-header-search">Search...</div>
        <div className="top-header-user">U</div>
        <div className="top-header-clock">14:23:45 KST</div>
      </div>
    </header>
    <main className="main-content">{children}</main>
  </div>
</div>
```

**테스트 영향**:
- `layout.test.tsx` "renders all 5 navigation links and brand" — brand text content는 "AITrading Co." + "READ ONLY"로 변경. `getByText()`로 찾는 값들 확인 필요.
- Token 디스플레이는 sidebar footer에 유지되므로 "displays truncated token" 테스트는 통과.
- Logout 버튼 위치 변경 없음 (여전히 sidebar footer).

### Step 4: DataTable.tsx 업그레이드

**변경 사항**:
1. `compact` prop 추가 (boolean)
2. CSS class `table-compact` 조건부 적용
3. CSS 변경: `[aria-selected="true"]`에 `border-left: 2px solid var(--accent-color)` 적용

```tsx
export function DataTable<T>({
  data,
  columns,
  getRowKey,
  onRowClick,
  isLoading,
  emptyMessage = "No data",
  selectedKey,
  compact = false,
}: DataTableProps<T>) {
  return (
    <div className={cn("table-wrapper", compact && "table-compact")}>
      ...
    </div>
  );
}
```

### Step 5: Dashboard.tsx 업그레이드

**변경 사항**:
1. SummaryCard에 sub-metrics 추가 (latency, uptime, replicas, storage 등 — 실제 API 데이터 없으면 표시 안함)
2. Dashboard body를 flex layout으로 변경:
   - Left (flex-1): Database Status Panel + (기존 Locks table + Orders table — Panel wrapper 적용)
   - Right (280px, signals-sidebar): Active Locks Warnings + Incomplete Reconciliation Signals + Degraded Agents (API 데이터 기반, 없으면 렌더링 안함)
3. WarningBanner: Health degraded 외에 critical overdue recon runs 추가

**CSS 구조**:
```css
.dashboard-body {
  display: flex;
  gap: 1rem;
}
.dashboard-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.signals-sidebar {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
```

### Step 6: OrdersView.tsx 업그레이드

**변경 사항**:
1. Filter bar: status/side를 FilterChip multi-select로 변경
2. DataTable에 Panel wrapper 적용
3. DataTable에 compact 모드 적용

**FilterChip 패턴**:
```tsx
function FilterChip({ label, active, onClick }) {
  return (
    <button
      className={cn("filter-chip", active && "filter-chip--active")}
      onClick={onClick}
    >
      {active ? "✓" : "○"} {label}
    </button>
  );
}
```

**테스트 영향**: `<select>` → `<button>` 변경으로 filter 테스트 수정 필요.

### Step 7: OrderDetail.tsx 업그레이드

**변경 사항**:
1. `<article>` → `<Panel>` 컴포넌트로 변경
2. Detail header를 SectionDivider + DetailField 패턴으로 변경
3. State events + Broker orders DataTable에 Panel wrapper 적용
4. Decision links footer 유지 (section-divider로 구분)

**테스트 영향**: DOM 구조 변경이 text content 기반 테스트에 영향 없음.

### Step 8: ReconciliationView.tsx 업그레이드

**변경 사항**:
1. Runs DataTable에 Panel wrapper 적용
2. Locks DataTable에 Panel wrapper 적용
3. Detail 영역 (선택된 run/lock)에 Panel + DetailField + SectionDivider 패턴 적용
4. WarningBanner에 icon 추가

### Step 9: AccountsView.tsx 업그레이드

**변경 사항**:
1. Account DataTable에 Panel wrapper 적용
2. Detail 영역에 Panel wrapper 적용 (cash balance + positions)
3. Detail 내부에 DetailField 패턴 적용
4. Positions DataTable에 compact mode 적용

### Step 10: DecisionsView.tsx 업그레이드

**변경 사항**:
1. DataTable에 Panel wrapper 적용
2. Filter bar: side/type을 FilterGroup button group으로 변경
3. Detail panel에 Panel wrapper + DetailField + SectionDivider 적용
4. **CRITICAL**: confidence 컬럼의 inline style `style={{ color: ... }}` **반드시 보존** (decisions.test.tsx 테스트 통과 조건)
5. Context error banner + context detail section 유지

**테스트 영향**:
- `decisions.test.tsx` "applies correct color based on confidence value" — inline `style={{ color: "var(--pico-ins-color)" }}` 보존 필요
- Filter 변경: `<select>` → `<button>`으로 filter 테스트 수정 필요

### Step 11: 테스트 실행

```bash
cd admin_ui && npm run test:run
```

**예상 변경 필요한 테스트 코드**:
1. `orders.test.tsx` — filter `<select>` → `<button>` 변경으로 `fireEvent.change(select)` → `fireEvent.click(button)` 변경
2. `decisions.test.tsx` — filter `<select>` → `<button>` 변경
3. `layout.test.tsx` — brand text content 변경 확인
4. 기타 테스트: text content 기반이므로 변경 불필요

### Step 12: 빌드

```bash
cd admin_ui && npm run build
```

---

## 테스트 보존 전략

### 유지해야 할 inline style (decisions.test.tsx)

```tsx
// decisions.test.tsx:70 — confidence 색상 테스트
expect(confCells[0]).toHaveStyle("color: var(--pico-ins-color)");
expect(confCells[1]).toHaveStyle("color: var(--pico-warning)");
expect(confCells[2]).toHaveStyle("color: var(--pico-del-color)");
```

DecisionsView.tsx의 confidence 컬럼 렌더러에서 `style={{ color: ... }}`는 **절대 변경 금지**. CSS class로 옮기면 `toHaveStyle` 테스트가 깨짐.

```tsx
// DecisionsView.tsx — 반드시 유지
{
  key: "confidence",
  header: "Confidence",
  render: (r) => (
    <span
      style={{ color: confidenceColor(r.confidence) }}
    >
      {(r.confidence * 100).toFixed(0)}%
    </span>
  ),
}
```

### Filter 테스트 변경 가이드

**Before** (select 기반):
```tsx
const select = container.querySelector("select");
fireEvent.change(select, { target: { value: "Buy" } });
```

**After** (button 기반):
```tsx
const buttons = screen.getAllByRole("button");
const buyButton = buttons.find((b) => b.textContent?.includes("Buy"));
fireEvent.click(buyButton);
```

---

## 컴포넌트 의존성

```
Layout.tsx
  └─ Panel (CSS only for brand/nav sections)

Dashboard.tsx
  ├─ SummaryCard (sub-metrics via children)
  ├─ Panel wrapper for each section
  ├─ WarningBanner (icon upgrade)
  └─ DataTable (compact mode)

OrdersView.tsx
  ├─ FilterChip (new component or inline)
  ├─ Panel wrapper
  └─ DataTable (compact mode)

OrderDetail.tsx
  ├─ Panel wrapper
  ├─ DetailField
  ├─ SectionDivider
  └─ DataTable (compact mode)

ReconciliationView.tsx
  ├─ Panel wrapper
  ├─ DetailField
  ├─ SectionDivider
  └─ WarningBanner (icon upgrade)

AccountsView.tsx
  ├─ Panel wrapper
  ├─ DetailField
  └─ DataTable (compact mode)

DecisionsView.tsx
  ├─ FilterGroup (new pattern)
  ├─ Panel wrapper
  ├─ DetailField
  ├─ SectionDivider
  └─ DataTable (compact mode)
```

---

## 파일 변경 요약

| 파일 | 변경 유형 | 영향 |
|------|----------|------|
| `admin_ui/src/styles/admin-theme.css` | 대규모 추가 (+200 lines) | CSS 확장 |
| `admin_ui/src/components/common/Panel.tsx` | **신규 생성** | 공통 컴포넌트 |
| `admin_ui/src/components/common/DetailField.tsx` | **신규 생성** | 공통 컴포넌트 |
| `admin_ui/src/components/common/SectionDivider.tsx` | **신규 생성** | 공통 컴포넌트 |
| `admin_ui/src/components/Layout.tsx` | 대규모 수정 | Top header + icons + ChevronRight |
| `admin_ui/src/components/common/DataTable.tsx` | 중간 수정 | compact prop 추가 |
| `admin_ui/src/components/Dashboard.tsx` | 대규모 수정 | Sub-metrics + signals sidebar + Panel |
| `admin_ui/src/components/OrdersView.tsx` | 중간 수정 | FilterChip + Panel + compact |
| `admin_ui/src/components/OrderDetail.tsx` | 중간 수정 | Panel + DetailField + SectionDivider |
| `admin_ui/src/components/ReconciliationView.tsx` | 중간 수정 | Panel + DetailField in details |
| `admin_ui/src/components/AccountsView.tsx` | 중간 수정 | Panel + DetailField |
| `admin_ui/src/components/DecisionsView.tsx` | 중간 수정 | FilterGroup + Panel + DetailField |
| `admin_ui/src/__tests__/orders.test.tsx` | 소규모 수정 | Filter select→button |
| `admin_ui/src/__tests__/decisions.test.tsx` | 소규모 수정 | Filter select→button |

---

## 완료 기준

1. **69/69 테스트 통과** (`npm run test:run`)
2. **빌드 성공** (`npm run build`)
3. Top header bar가 Layout에 표시됨
4. Sidebar nav에 아이콘과 active ChevronRight 표시됨
5. Dashboard에 sub-metrics + signals sidebar 표시됨
6. 모든 화면에서 Panel wrapper 적용됨
7. DetailField/SectionDivider 패턴이 detail 영역에 적용됨
8. DataTable에 compact mode + left-border selected accent 적용됨
9. Filter bar가 chip/button 기반으로 업그레이드됨
10. DecisionsView confidence inline style 보존됨
