# Plan 57: Admin UI 디자인 템플릿 최대 이식

## 목적

`design/design_template/`의 Admin UI 디자인 구성/레이아웃/컴포지션을
`admin_ui/`에 가능한 한 최대로 이식한다. 템플릿은 **라이트 테마**(shadcn/ui + Tailwind),
우리 앱은 **다크 테마**(OKLCH + Pico CSS)이므로 **색상은 유지하고 레이아웃과 컴포지션만 이식**.

## 핵심 원칙

- **기능/데이터 흐름/라우트/Auth 유지** (수정 금지)
- **색상 시스템 유지** (OKLCH 다크 팔레트, 템플릿 라이트 색상 사용 금지)
- **템플릿의 레이아웃 구조/컴포넌트 구성/정보 밀도**를 최대한 정확히 재현
- 새로운 Lucide 아이콘 추가 시 `npm install lucide-react` 필요
- 모든 변경 후 `npm run test:run` + `npm run build` 통과 필수

## 공통 CSS 클래스 추가 (템플릿 기반)

템플릿의 반복 패턴에서 추출한 새로운 CSS 클래스들을 `admin-theme.css`에 추가:

### 레이아웃 split 클래스
```css
/* 좌/우 split 레이아웃 (Orders, Decisions, Reconciliation, Accounts 공통) */
.split-layout {
  display: flex;
  gap: var(--space-4);
  flex: 1;
  min-height: 0;
}

.split-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
}

.split-sidebar {
  width: 280px;  /* Orders/Decisions */
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  overflow-y: auto;
}

.split-sidebar--narrow {
  width: 272px;  /* Reconciliation */
}

.split-sidebar--card-list {
  width: 248px;  /* Accounts */
}
```

### Card-style panel (템플릿 white rounded-xl border 대체)
```css
.card-panel {
  background-color: var(--panel-bg);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.card-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
}

.card-panel-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-primary);
}

.card-panel-count {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
```

### StatCard (템플릿의 icon+label+value+change 패턴)
템플릿의 StatCard 구조를 우리 SummaryCard에 적용:
- icon + iconBg + iconColor
- label (text-xs, secondary)
- value (text-xl, bold)
- change + change indicator (TrendingUp/Down)
- alert badge (optional)

기존 `.summary-card` 클래스에 새 변형 추가:
```css
.summary-card--icon { /* icon+label+value+change variant */ }
```

### Account card list (AccountsView 좌측 리스트)
```css
.account-card { /* 248px card list item */ }
.account-card--active { /* selected state */ }
.account-card-name { }
.account-card-id { }
.account-card-status { }
.account-card-value { }
```

### Alert panel item
```css
.alert-item { /* System Health / Active Alerts items */ }
```

### Timeline (Order 상태 이벤트) — 이미 존재, 스타일 조정만
기존 `.event-timeline-*` 클래스 유지, 템플릿 스타일 참고하여 색상/간격 조정

### Pill filter button group (템플릿의 segmented filter 패턴)
```css
.pill-group { }
.pill-btn { }
.pill-btn--active { }
```

## Step-by-step 구현 계획

---

### Step 1: Layout 공통 구조 업그레이드

**대상**: `Layout.tsx`, `admin-theme.css` (Section 4, 21, 22, 23)

**변경 사항**:

1. **Sidebar collapse 기능 추가**:
   - `Layout.tsx`에 `collapsed` state + toggle 버튼 추가
   - 축소 시 64px, 확장 시 220px (`.sidebar` width 동적 변경)
   - 템플릿처럼 토글 버튼을 우측 경계에 배치 (absolute positioning)
   - Nav section labels ("Main Menu") 추가 (템플릿 `NavSection` 컴포넌트 참고)
   - 하단에 avatar/user 영역 추가 (초기에는 "Admin" 정적 텍스트로)

2. **Top Header 업그레이드**:
   - 현재: page title + token display + logout
   - 변경: greeting ("Good Morning") + (선택) date badge + notification bell (정적) + avatar
   - Page title은 template처럼 header 좌측에 유지
   - 기존 token display + logout 유지 (우측 영역)
   - 필요시 `ClockIcon` 대신 `Calendar` 아이콘으로 date 표시

3. **CSS 변경**:
   - `.sidebar` transition 추가 (width changes)
   - 새 `.sidebar-toggle` 클래스
   - `.sidebar-user-area` 클래스 (avatar + name/role)
   - `.sidebar-nav-section` 클래스 (section label)
   - `.top-header` 스타일 조정 (template의 header 구조 반영)

**영향 범위**: `Layout.tsx` (큰 변경), `admin-theme.css` (Section 4, 21, 22, 23)

---

### Step 2: Dashboard — Overview 컴포지션

**대상**: `Dashboard.tsx`, `admin-theme.css`

**변경 사항**:

1. **StatCards 업그레이드** (참고: `components/admin/overview/StatCards.tsx`):
   - 현재: 텍스트-only summary card grid
   - 변경: 각 카드에 아이콘 + 라벨 + 값 + 변화율(TrendingUp/Down) 추가
   - 4개 카드: Total Orders, Pending Reconciliation, Active Accounts, Open Decisions
   - `lucide-react` 아이콘 사용: `ClipboardList`, `GitCompareArrows`, `Wallet`, `Brain`
   - 기존 `healthLabel` + `MetricRow` 유지 (카드 내부에 표시)
   - 카드에 `border-top-color` 변형 유지 (variant: ok/warn/error)

2. **우측 Signals Sidebar → AlertsPanel로 대체** (참고: `AlertsPanel.tsx`):
   - 현재: signals-sidebar (agents signals + health status + active locks table)
   - 변경: AlertsPanel (System Health + Active Alerts)
   - System Health: 4개 항목 (Order Router, Broker Feed, Recon Engine, Decision Engine) — 각각 operational/degraded 표시
   - Active Alerts: 최근 경고 3개 (lock, recon required, degraded health)
   - **유지할 것**: Database Status panel, Active Locks section, Incomplete Reconciliation section
   - 이들은 `.dashboard-main` 좌측 영역에 유지

3. **레이아웃 조정**:
   - `.dashboard-body` flex container 유지
   - `.dashboard-main`: 기존 panels 유지 (flex column, gap)
   - `.signals-sidebar` → `.alerts-sidebar`로 교체 (기존 signals 내용을 AlertsPanel로 대체)

**영향 범위**: `Dashboard.tsx` (StatCards 리팩터 + AlertsPanel 추가), `admin-theme.css` (.alerts-sidebar 추가)

**테스트 영향**: `dashboard.test.tsx` — StatCards label/text 변경, signals-sidebar 제거로 일부 테스트 수정 필요
- "renders summary cards" 테스트: 카드 라벨/값 문자열 변경 반영
- "shows warning banner" 테스트: 유지
- "shows health warning" 테스트: 유지

---

### Step 3: OrdersView — 좌/우 split + 인라인 detail panel

**대상**: `OrdersView.tsx`, `OrderDetail.tsx` (부분), `admin-theme.css`

**변경 사항** (참고: `components/admin/pages/OrdersPage.tsx`):

1. **Filter bar 업그레이드**:
   - 현재: select dropdowns (status, side) + search input
   - 변경: search input (flex-1, placeholder "Search by symbol, order ID, account…") + status pill buttons (all/filled/pending/partial/cancelled) + side pill buttons (all/BUY/SELL)
   - template의 filter bar 구조: rounded-lg border, flex-wrap, pill buttons with active state

2. **Table 영역**:
   - 현재: `<Panel>` wrapping `<DataTable>`
   - 변경: card-panel 스타일, table header에 "{N} orders" + "Today, ..." subtitle
   - 테이블 컬럼 순서 템플릿에 맞게 조정 (Order ID / Symbol / Side / Qty / Filled / Price / Avg Fill / Status / Broker / Account / Time)

3. **우측 detail panel (280px)**:
   - 현재: row click → OrderDetail 라우트로 navigate
   - 변경: row click → 우측에 280px inline detail panel 열림
   - panel 구성:
     a. **Order Detail**: header (title + X close button) + status banner (colored bg + dot) + detail fields (DetailRow 스타일)
     b. **State Events**: timeline (order created → sent to broker → acknowledged → fill received / cancelled)
     c. **Broker Mapping**: broker name + ext order ID + routing + commission
   - **OrderDetail 라우트 유지**: 우측 패널에서 "View full detail" 링크로 이동 가능
   - detail panel은 `selectedOrder` state로 제어

4. **상태 이벤트 타임라인**:
   - 기존 `.event-timeline-*` CSS 클래스 활용 (Section 29)
   - 템플릿의 timeline보다 더 간결하게 유지 (현재 구현 그대로 사용 가능)
   - Order의 `stateEvents` 데이터에서 이벤트 추출

**영향 범위**: `OrdersView.tsx` (큰 리팩터), `OrderDetail.tsx` (변경 없음), `admin-theme.css` (새 클래스 추가)

**테스트 영향**: `orders.test.tsx` — 
- "navigates to order detail on row click" 테스트: navigate → inline panel open으로 변경되어 실패
- 이 테스트는 수정 필요: panel 렌더링 확인으로 대체
- filter/search 테스트: 유지 (데이터 흐름 변경 없음)

---

### Step 4: ReconciliationView — 좌/우 split

**대상**: `ReconciliationView.tsx`, `admin-theme.css`

**변경 사항** (참고: `components/admin/pages/ReconciliationPage.tsx`):

1. **탭 기반 → 좌/우 split 레이아웃으로 변경**:
   - 현재: tab-bar (Runs / Locks) — 한 번에 하나만 표시
   - 변경: warning banner (상단) + 좌측(runs table + unmatched table) + 우측(locks panel + run detail panel)
   - 모든 정보를 동시에 표시

2. **Warning banner** (상단, 조건부):
   - active locks 있을 때만 표시
   - 템플릿 스타일: red tint background, Lock icon, bold title + description + "Review Locks" button
   - 우리의 기존 warning-banner--error 활용, 내용만 템플릿에 맞게 조정

3. **좌측 메인 영역**:
   - **Runs table**: card-panel 스타일, header에 "Reconciliation Runs" + "Last 48 hours" subtitle
   - Status filter를 select → pill buttons로 변경 (all/completed/failed/running/pending)
   - "Re-run" button 추가 (UI only, non-functional)
   - **Unmatched Positions table** (하단): card-panel 스타일
     - header에 AlertTriangle icon + title + count badge
     - rows: Run ID / Symbol / Type / Expected / Actual / Diff (diff != 0 rows에 yellow bg)

4. **우측 사이드바 (272px)**:
   - **Account Locks** 패널: card-panel, lock cards with severity badge + reason + time + "Release Lock" button
   - **Run Detail** 패널 (run 선택 시): card-panel, detail fields + matched/unmatched status footer

**영향 범위**: `ReconciliationView.tsx` (큰 리팩터, 레이아웃 완전 변경), `admin-theme.css` (새 클래스)

**테스트 영향**: `reconciliation.test.tsx` — 
- "switches to locks tab" 테스트: tab 제거로 실패 → split layout 확인으로 대체
- "shows enhanced warning banner" 테스트: 유지 가능 (banner는 계속 존재)
- filter/table 테스트: 유지 (데이터 흐름 변경 없음)

---

### Step 5: AccountsView — 좌측 카드 리스트 + 우측 detail

**대상**: `AccountsView.tsx`, `admin-theme.css`

**변경 사항** (참고: `components/admin/pages/AccountsPage.tsx`):

1. **좌측 account 카드 리스트 (248px)**:
   - 현재: DataTable (계정 목록 테이블)
   - 변경: 세로 카드 리스트 (scrollable, width 248px)
   - 각 카드: account name (semibold) + account ID (mono, small) + status badge + total value + day P&L + broker
   - 선택 시 active state (파란 tint 배경 + 파란 테두리)
   - 상단: "ACCOUNTS (N)" section label

2. **우측 세부 영역**:
   - **Account status warning** (조건부, locked 계정일 때만):
     - red tint bg + Lock icon + warning message
   - **Summary cards (3개)**: Total Value / Cash Balance / Day P&L
     - 템플릿 스타일: icon + value + sub label + trending indicator
   - **Positions table**: card-panel
     - header: Wallet icon + "Positions — {account name}" + count
     - columns: Symbol / Qty / Avg Cost / Current Price / Market Value / P&L / P&L %
     - P&L % 컬럼: TrendingUp/Down icon + pill badge

3. **기존 기능 유지**:
   - search filter 유지 (계정명/코드 검색)
   - type filter 유지 (active/locked/inactive)
   - position/cash 데이터 로딩 유지

**영향 범위**: `AccountsView.tsx` (큰 리팩터, 테이블→카드 리스트로 변경), `admin-theme.css` (account-card, summary-card 새 변형)

**테스트 영향**: `accounts.test.tsx` — 
- "renders accounts table" 테스트: table 대신 card list로 변경 → 실패
- "loads positions" 테스트: detail panel 확인 방식으로 변경
- "shows account code and type in detail header" 테스트: 유지 가능
- filter/search 테스트: 유지

---

### Step 6: DecisionsView — detail panel 고도화

**대상**: `DecisionsView.tsx`, `admin-theme.css`

**변경 사항** (참고: `components/admin/pages/DecisionsPage.tsx`):

1. **Filter bar 업그레이드**:
   - 현재: select (side) + search + confidence range inputs
   - 변경: pill buttons for Outcome (all/executed/rejected/pending/overridden) + Action (all/BUY/SELL/HOLD)
   - search + confidence filter는 하단 또는 별도 영역으로 이동
   - filter bar를 card-panel 스타일로 (rounded-xl border, p-3)

2. **Table 영역**:
   - card-panel 스타일, header: Brain icon + "Decision Log" + count
   - 컬럼: Decision ID / Symbol / Action / Confidence / Strategy / Account / Outcome / Time
   - **ConfidenceBar 컴포넌트 추가**:
     - progress bar (bg: gray, fill: green/yellow/red based on value)
     - percentage text 우측
     - 현재 confidence color inline style과 충돌 없도록 구현 (test contract 유지)

3. **우측 detail panel (288px)**:
   - 현재: detail panel (1개 패널, decision fields + lazy context + signals)
   - 변경: 3개 섹션으로 분리
     a. **Decision Detail**: header (title + X close) + action/outcome banner + detail fields (ID/Strategy/Account/Date/Time) + ConfidenceBar + Reason
     b. **Input Signals**: header + signal rows (name + value + direction icon)
     c. **Market Context**: header + context rows (market regime / volatility / volume / spread)
   - 각 섹션을 별도 card-panel로 분리 (template 구조)

4. **기존 기능 유지**:
   - lazy-load context on row click
   - error banner on context API failure
   - confidence color by value (test contract)

**영향 범위**: `DecisionsView.tsx` (detail panel 리팩터), `admin-theme.css` (.confidence-bar, .signal-row 등)

**테스트 영향**: `decisions.test.tsx` — 
- "shows decision fields and lazy-loads context on row click" 테스트: detail panel 구조 변경으로 확인 로직 수정 필요
- "applies correct color based on confidence value" 테스트: 유지 (confidence color logic 유지)
- filter/search 테스트: 유지

---

### Step 7: CSS 추가/정리

**대상**: `admin-theme.css`

위 각 Step에서 필요한 CSS 클래스 외에도 공통으로 추가할 것:

1. **`.split-layout` / `.split-main` / `.split-sidebar`** (모든 split 화면 공통)
2. **`.card-panel` / `.card-panel-header` / `.card-panel-title`** (패널 스타일)
3. **`.pill-group` / `.pill-btn` / `.pill-btn--active`** (필터 버튼)
4. **`.account-card` 계열** (Accounts 카드 리스트)
5. **`.stat-card-icon`** (StatCard icon wrapper)
6. **`.alerts-sidebar`** (Dashboard signals→alerts 대체)
7. **`.confidence-bar` / `.confidence-bar-fill`** (Decisions confidence bar)
8. **`.signal-row`** (signal direction display)
9. **`.detail-row`** (order/detail key-value row, template DetailRow 패턴)
10. **`.status-banner`** (colored bg + dot status indicator)

---

### Step 8: 테스트 조정

각 Step에서 깨지는 테스트를 순차적으로 수정:
- `orders.test.tsx`: row click navigate → inline panel 확인
- `reconciliation.test.tsx`: tab 제거 → split layout 확인
- `accounts.test.tsx`: table → card list 확인
- `decisions.test.tsx`: detail panel 구조 변경 반영
- `dashboard.test.tsx`: StatCards label 변경 반영

**전략**:
- 가능한 한 테스트의 **assertion 대상만 변경**하고 테스트 구조는 유지
- 예: `screen.getByText('Orders')` → `screen.getByText('Total Orders')`
- 예: `expect(navigate).toHaveBeenCalled()` → `expect(screen.getByText('Order Detail')).toBeInTheDocument()`

---

### Step 9: 빌드 + 전체 테스트

- `rm -rf node_modules dist` (clean state)
- `npm install` (lucide-react 추가되었는지 확인)
- `npm run build`
- `npm run test:run`

---

## 변경 금지 목록

- Backend API 호출 방식
- Auth (sessionStorage token)
- Route 구조 (`/dashboard`, `/orders`, `/orders/:id`, `/reconciliation`, `/accounts`, `/decisions`)
- `/admin` static serving
- Pico CSS 의존성 (제거하지 않음)
- 기존 데이터 fetch 로직 (useEffect + API calls)
- TypeScript 타입 정의 (`api.ts`)

## 보존해야 할 테스트 계약

1. DecisionsView confidence color: `toHaveStyle` assertion (inline style 유지)
2. Dashboard health indicators: ok/degraded 상태 표시
3. AccountsView cash balance null: "No cash balance snapshot" 메시지
4. ReconciliationView warning banner: active locks 조건부 표시
5. OrdersView filter by status/side/search: 데이터 필터링

## 추가 설치

```bash
cd admin_ui && npm install lucide-react
```

템플릿은 `lucide-react`를 아이콘 라이브러리로 사용. 현재 admin_ui는 인라인 SVG를 사용 중.
lucide-react로 마이그레이션하면 일관된 아이콘 스타일 확보 가능.
단, **점진적 교체**: 새로 추가하는 아이콘만 lucide 사용, 기존 SVG 아이콘은 유지.
