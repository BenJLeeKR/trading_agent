# Plan 56 — Admin UI Typography / Spacing / Polish

> **승인 조건 (구현 시 주의)**
> 1. Typography scale은 page title / panel title / body / meta / label / mono 정도로 실용적으로 유지
> 2. Spacing scale은 panel padding, filter gap, detail row gap, table cell padding까지 실제 치환 범위를 명확히 할 것
> 3. Compact table mode는 숫자 정렬, hover/selected state, row clickability를 함께 확인
> 4. Inline style 제거는 중복 가능한 것부터 우선, 테스트 계약인 inline style(예: DecisionsView confidence color)은 억지로 제거하지 말 것

## 목적

현재 Admin UI의 구조적 구성(Phase 1/2)은 완료되었으나, `design/design_template/` 대비 **micro-level polish gap**이 남아 있음. 
이번 작업은 구조 변경 없이 **Typography / Spacing / Density / Polish** 계층을 system-level로 정리하여 제품화된 enterprise admin console 수준으로 완성도를 높이는 것이 목표.

---

## 1. Typography System 정리

### 현재 문제점
- 고정된 font-size scale 없음 (임의 값 0.6rem ~ 1.5rem 분포)
- line-height가 대부분 미지정 (Pico 기본값에 의존)
- body에 명시적 font-family 없음
- mono text가 산발적으로만 적용됨
- page title(1.4rem)과 panel title(0.85rem) 사이 계층은 있으나 polish 부족
- table body text(0.85rem)가 panel title(0.85rem)과 동일한 크기

### 수정 사항

#### 1a. CSS Custom Properties에 font scale 추가 (`admin-theme.css`)

```css
:root {
  /* Font scale */
  --text-xs: 0.65rem;    /* meta, timestamp, badges */
  --text-sm: 0.7rem;     /* compact table, signal, filter btn */
  --text-base: 0.8rem;   /* detail value, body text */
  --text-md: 0.85rem;    /* table body, panel title */
  --text-lg: 0.95rem;    /* section header */
  --text-xl: 1.1rem;     /* sidebar brand */
  --text-2xl: 1.4rem;    /* page title */
  
  /* Line heights */
  --leading-tight: 1.25;
  --leading-normal: 1.4;
  --leading-relaxed: 1.6;
  
  /* Font weights */
  --weight-normal: 400;
  --weight-medium: 500;
  --weight-semibold: 600;
  --weight-bold: 700;
  
  /* Font families */
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace;
}
```

#### 1b. body에 font-family 적용

```css
body {
  font-family: var(--font-sans);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
```

#### 1c. 기존 CSS 클래스에 font scale/weight/leading 적용 (일괄 교체)

| 현재 값 | 변경 값 |
|---------|---------|
| `.page-header h2` font-size: 1.4rem | `var(--text-2xl)` |
| `.page-header p` font-size: 0.85rem | `var(--text-sm)` |
| `.panel-title` font-size: 0.85rem | `var(--text-md)` |
| `.panel-subtitle` font-size: 0.7rem | `var(--text-xs)` |
| `.detail-field-label` font-size: 0.65rem | `var(--text-xs)` |
| `.detail-field-value` font-size: 0.8rem | `var(--text-base)` |
| `.section-divider-label` font-size: 0.65rem | `var(--text-xs)` |
| `.badge` font-size: 0.75rem | `var(--text-xs)` |
| `.filter-group-btn` font-size: 0.7rem | `var(--text-sm)` |
| `table-wrapper thead th` font-size: 0.8rem | `var(--text-sm)` |
| `table-wrapper tbody td` font-size: 0.85rem | `var(--text-md)` |
| `.sidebar-nav-link` font-size: 0.9rem | `var(--text-md)` |
| `.sidebar-brand-title` font-size: 0.85rem | `var(--text-md)` |
| `.top-header-title` font-size: 0.9rem | `var(--text-md)` |
| `.metric-row` font-size: 0.65rem | `var(--text-xs)` |
| `.signal-table` font-size: 0.7rem | `var(--text-sm)` |
| `.signal-table th` font-size: 0.6rem | `var(--text-xs)` |
| `.warning-banner` font-size: 0.875rem | `var(--text-base)` |
| `.event-timeline-event` font-size: 0.7rem | `var(--text-sm)` |
| `.event-timeline-time` font-size: 0.65rem | `var(--text-xs)` |

#### 1d. letter-spacing 상수화

```css
--tracking-tight: -0.01em;
--tracking-normal: 0;
--tracking-wide: 0.03em;
--tracking-wider: 0.04em;
--tracking-widest: 0.06em;
```

적용 대상:
- uppercase label: `var(--tracking-wider)` (기존 0.04em)
- table header: `var(--tracking-wide)` (기존 0.03em)
- badge: `var(--tracking-wide)`
- section-divider-label: `var(--tracking-wider)`

---

## 2. Spacing System 정리

### 현재 문제점
- 4px/8px 기반 scale 없음
- 임의 값: 0.15rem, 0.25rem, 0.3rem, 0.4rem, 0.5rem, 0.6rem, 0.65rem, 0.75rem, 1rem, 1.25rem, 1.5rem
- panel-header(0.65rem)와 panel-body(0.75rem)의 padding 불일치
- 화면별 filter-bar/panel/section gap이 제각각

### 수정 사항

#### 2a. Spacing scale 추가

```css
:root {
  --space-0: 0;
  --space-1: 0.25rem;   /* 4px */
  --space-2: 0.5rem;    /* 8px */
  --space-3: 0.75rem;   /* 12px */
  --space-4: 1rem;      /* 16px */
  --space-5: 1.25rem;   /* 20px */
  --space-6: 1.5rem;    /* 24px */
  --space-8: 2rem;      /* 32px */
}
```

#### 2b. CSS 클래스에 spacing scale 적용

| 컴포넌트 | 현재 값 | 변경 값 |
|----------|---------|---------|
| `.panel-header` padding | 0.65rem 1rem | `var(--space-3) var(--space-4)` |
| `.panel-body` padding | 0.75rem 1rem | `var(--space-3) var(--space-4)` |
| `.surface-panel-header` padding | 0.75rem 1rem | `var(--space-3) var(--space-4)` |
| `.surface-panel-body` padding | 0.75rem 1rem | `var(--space-3) var(--space-4)` |
| `.filter-bar` gap | 0.75rem | `var(--space-3)` |
| `.filter-group` gap | 0.3rem | `var(--space-1)` |
| `.detail-grid` gap | 0.5rem | `var(--space-2)` |
| `.summary-cards-grid` gap | 1rem | `var(--space-4)` |
| `.dashboard-body` gap | 1rem | `var(--space-4)` |
| `.signals-sidebar` gap | 0.75rem | `var(--space-3)` |
| `.main-content` padding | 1.5rem | `var(--space-6)` |
| `.page-header` margin-bottom | 1.5rem | `var(--space-6)` |
| `.page-footer` margin-top | 1.5rem | `var(--space-6)` |
| `.section-divider` margin | 0.6rem 0 | `var(--space-2) 0` |
| `.sidebar-brand` padding | 0.85rem 1rem 0.75rem | `var(--space-3) var(--space-4)` |
| `.sidebar-nav-link` padding | 0.4rem 0.75rem | `var(--space-2) var(--space-3)` |
| `.sidebar-footer` padding | 0.75rem 1rem | `var(--space-3) var(--space-4)` |
| `.top-header` padding | 0 1.25rem | `0 var(--space-5)` |
| `.top-header` height | 3rem | `3rem` (유지) |
| `.warning-banner` padding | 0.6rem 0.85rem | `var(--space-2) var(--space-3)` |
| `.warning-banner` margin-bottom | 0.75rem | `var(--space-3)` |
| `.summary-card` padding | 1rem | `var(--space-4)` |

---

## 3. Table Density / Rhythm 정리

### 현재 문제점
- compact mode의 cell padding이 `!important` 사용 (CSS 특이성 충돌)
- selected row가 left-border accent와 background-color를 중복 사용
- numeric alignment 미지정

### 수정 사항

#### 3a. Compact mode 정리

```css
.table-compact th,
.table-compact td {
  padding: var(--space-1) var(--space-2);
}

.table-compact tbody td {
  padding-top: var(--space-1);
  padding-bottom: var(--space-1);
}
```

- `!important` 제거 (CSS 특이성 충돌 해소)
- `min-height: 28px` 제거 (padding으로 충분)

#### 3b. Table cell alignment

```css
.table-wrapper tbody td {
  vertical-align: middle;
}

/* Numeric alignment helper */
.table-wrapper td.numeric,
.table-wrapper th.numeric {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
```

- `td`에 `vertical-align: middle` 유지
- numeric column을 위한 CSS 클래스 추가 (컴포넌트 수정 없이 CSS만)

#### 3c. Selected row 정리

```css
.table-wrapper tbody tr[aria-selected="true"] {
  background-color: oklch(0.22 0.03 240 / 0.6);
  border-left: 2px solid var(--accent-color);
  outline: none;
}
```

- 중복된 `.table-wrapper tbody tr[aria-selected="true"]` 규칙 병합 (현재 두 번 정의됨, line 458-462와 1068-1072)

---

## 4. Badge / Icon / Banner Polish

### 4a. Badge 크기/스타일 정리

```css
.badge {
  display: inline-flex;
  align-items: center;
  padding: 0.1rem 0.45rem;
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  border-radius: 0.25rem;
  line-height: var(--leading-tight);
}
```

- `inline-block` → `inline-flex` (내부 텍스트 수직 중앙 정렬)
- padding 미세 조정
- `line-height: var(--leading-tight)` 명시

### 4b. Sidebar nav icon 정렬

```css
.sidebar-nav-icon {
  width: 0.95rem;    /* 유지 */
  height: 0.95rem;
  flex-shrink: 0;
  /* 기존 stroke 속성 유지 */
}
```

- icon 크기 유지 (이미 적절)
- 불필요한 중복 CSS 규칙 제거 (현재 `.sidebar-nav-icon`이 두 번 정의됨, line 1013-1022)

### 4c. Top header 아이콘/텍스트 alignment

```css
.top-header {
  height: 3rem;      /* 유지 */
  /* 아이콘과 텍스트가 자연스럽게 중앙 정렬되도록 */
}
```

- 현재 이미 `align-items: center` 적용됨 — 확인 후 불필요한 수정 없음

### 4d. Warning banner hierarchy 개선

```css
.warning-banner-strong {
  font-weight: var(--weight-bold);
  font-size: var(--text-sm);
}

.warning-banner-content {
  font-size: var(--text-base);
}
```

---

## 5. Surface Depth / Contrast Polish

### 현재 문제점
- Panel background가 surface-1과 같은 값 (oklch(0.16 0.009 240))
- Selected row가 surface-2와 너무 유사할 수 있음
- Shadow가 매우 제한적 (shadow-sm, shadow-md만 존재)

### 수정 사항

#### 5a. Panel depth 미세 조정

```css
:root {
  --panel-bg: oklch(0.16 0.009 240);      /* 유지 (현행) */
  --panel-border: oklch(0.24 0.009 240);   /* 유지 */
}
```

- 현재 panel depth는 적절 — 불필요한 변경 없음
- 중복 CSS 규칙 제거 (`.panel`과 `.surface-panel`이 유사한 스타일)

#### 5b. Selected/hover row contrast 확인

```css
.table-wrapper tbody tr:hover {
  background-color: oklch(0.20 0.01 240);
}

.table-wrapper tbody tr[aria-selected="true"] {
  background-color: oklch(0.22 0.03 240 / 0.6);
  border-left: 2px solid var(--accent-color);
}
```

- hover(0.20)와 selected(0.22, 60% 투명) 간 충분한 contrast 확인 필요
- 필요시 selected 배경을 oklch(0.22 0.04 240 / 0.7)로 미세 조정

---

## 6. Inline Style → CSS Class 마이그레이션

### 원칙
- 가능한 모든 inline style을 CSS 클래스로 이동
- 테스트에서 `toHaveStyle`을 검증하는 경우는 보존 (DecisionsView confidence color 등)
- 컴포넌트 로직에 의존하는 동적 스타일은 예외 허용

### 대상 목록

#### Dashboard.tsx
| 위치 | Inline Style | 대체 클래스 |
|------|-------------|-------------|
| L77 | `h3 style={{ color }}` | 이미 `summary-card--ok/warn/error`로 variant 적용됨 → 컬러는 CSS 변수로 처리 |
| L240-258 | `span` health dot (inline-block, 10x10, borderRadius 등) | `.health-dot` 클래스 생성 |
| L282 | `div style={{ marginTop: "0.5rem", paddingTop: "0.5rem" }}` | `.table-footer` 클래스로 (또는 기존 `.page-footer` 활용) |
| L294, L324 | `p style={{ padding: "0.75rem" }}` | `.panel-empty` 클래스 생성 |
| L309 | `tr style={{ cursor: "pointer" }}` | 이미 `.cursor-pointer` 클래스 존재 → 사용 |
| L341-343 | `button` refresh | `.btn-refresh` 또는 기존 `.outline` 유지 |

#### OrdersView.tsx
| 위치 | Inline Style | 대체 클래스 |
|------|-------------|-------------|
| L97-108 | `span` side color | `.side-buy` / `.side-sell` 클래스 생성 |
| L131 | `input style={{ flex: 1, minWidth: "180px" }}` | `.filter-input` 클래스 생성 |
| L159-161 | `span` counter | `.panel-counter` 클래스 생성 |

#### OrderDetail.tsx
| 위치 | Inline Style | 대체 클래스 |
|------|-------------|-------------|
| L75 | `p style={{ marginBottom: "0.75rem" }}` | `.back-link` 클래스 생성 |
| L84-86 | `code` order ID | `.order-id` 클래스 생성 |
| L116 | `div style={{ marginTop: "0.5rem" }}` | `.error-block` 클래스 생성 |
| L124 | `div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}` | `.decision-links` 클래스 생성 |

#### ReconciliationView.tsx
| 위치 | Inline Style | 대체 클래스 |
|------|-------------|-------------|
| L177, L200 | `div style={{ marginTop: "0.75rem" }}` | `.tab-content` 클래스 생성 |
| L221-223 | `span style={{ fontWeight: "normal" }}` | `.warning-banner-body` 클래스 생성 |

#### AccountsView.tsx
| 위치 | Inline Style | 대체 클래스 |
|------|-------------|-------------|
| L137-149 | `span` position side color | `.side-long` / `.side-short` 클래스 생성 |
| L181 | `input style={{ width: "220px" }}` | `.filter-input`(기존) 또는 유지 |
| L231-233 | `p style={{ margin: 0 }}` | `.text-muted`만으로 충분 |
| L237 | `div style={{ marginTop: "0.75rem" }}` | `.positions-table` 클래스 생성 |

#### DecisionsView.tsx
| 위치 | Inline Style | 대체 클래스 |
|------|-------------|-------------|
| L119-132 | `span` side color | `.side-buy` / `.side-sell` (OrdersView와 공유) |
| L139-148 | `span` confidence color | ⚠️ 테스트(`toHaveStyle`)와 연결 — 보존 |
| L155 | `code` context ID | `.context-id` 클래스 |
| L187 | `input style={{ width: "160px" }}` | `.filter-input--sm` 클래스 |
| L200-213 | `label` confidence filters | `.confidence-filter` 클래스 |
| L233-236 | `span` counter | `.panel-counter` (OrdersView와 공유) |
| L258 | `button` close | `.close-btn` 클래스 |
| L212, L225 | `input style={{ width: "100px", marginTop: "0.2rem" }}` | `.confidence-input` 클래스 |

---

## 7. CSS 중복 규칙 정리

현재 `admin-theme.css`에서 발견된 중복:

| 규칙 | 중복 위치 | 처리 |
|------|----------|------|
| `.sidebar-brand` | line 143-146 + line 952-959 | 병합 (최신 버전 유지) |
| `.sidebar-brand-title` | line 148-152 + line 983-992 | 병합 |
| `.sidebar-brand-badge` | line 154-163 + line 1001-1004 | 병합 |
| `.sidebar-nav-link` | line 176-184 + line 1007-1011 | 병합 |
| `.sidebar-nav-icon` | line 1013-1022만 (중복 없음) | 유지 |
| `.warning-banner` | line 377-386 + line 1344-1354 | 병합 |
| `.warning-banner-content` | line 1337-1342만 | 유지 |
| `.warning-banner-icon` | line 1326-1335만 | 유지 |
| `.table-wrapper tbody tr[aria-selected="true"]` | line 458-462 + line 1068-1072 | 병합 |
| `.detail-field` | line 364-366 + line 731-735 | 병합 |
| `.text-muted` | line 577-579 | 유지 (중복 없음) |
| `.surface-panel` + `.panel` | section 7 + section 18 | `surface-panel`은 `.panel`로 대체 가능 — 제거 검토 |
| `.detail-grid` | line 358-362 | 유일 — 유지 |
| `.data-grid-2` / `.data-grid-auto` | line 557-567 | 사용처 확인 — 미사용시 제거 |

---

## 8. 실행 순서

### Step 1: CSS 토큰 확장 (admin-theme.css)
- font scale, line-height, font-family, font-weight 토큰 추가
- spacing scale 토큰 추가
- tracking 상수 추가
- 기존 CSS 클래스의 값을 새로운 토큰으로 일괄 교체

### Step 2: CSS 중복 규칙 병합 및 정리
- 중복 셀렉터 병합
- surface-panel → panel 통합 검토
- !important 제거

### Step 3: Inline Style → CSS Class 마이그레이션
- 각 컴포넌트별로 inline style을 CSS 클래스로 이동
- 테스트 영향 범위 확인 (toHaveStyle 검증 보존)

### Step 4: Table/Badge/Icon/Banner Polish
- compact mode 정리
- badge inline-flex 전환
- selected row 단일 규칙으로 정리

### Step 5: Surface Depth 미세 조정
- 필요시 contrast 조정
- 중복/과잉 스타일 제거

### Step 6: 테스트 실행 및 검증
- `npm run test:run` (69개 전손 통과 확인)
- `npm run build` (tsc + vite 성공 확인)

---

## 변경 금지 항목 (Plan 56 범위 외)

- ❌ backend/API/auth 변경
- ❌ 새 기능 추가
- ❌ filter semantics 변경
- ❌ route 구조 변경
- ❌ chart 추가
- ❌ full redesign
- ❌ 테스트 assertion 변경 (toHaveStyle 검증 보존)
- ❌ `design/design_template/` 파일 직접 수정

---

## 검증 기준

1. `cd admin_ui && npm run test:run` — 69개 테스트 전손 통과
2. `cd admin_ui && npm run build` — tsc + vite 성공
3. 수동 확인: 모든 페이지에서 typography/rhythm 일관성
4. Inline style 사용이 크게 줄어들었는가
5. CSS 토큰 체계가 문서화 가능한 규칙으로 정리되었는가

---

## 잔여 Visual Debt (Plan 56 이후)

1. **Pico CSS 의존성**: Pico 기본 버튼/폼 스타일이 일부 영역에 영향을 줌. 향후 Pico 탈피 또는 정리 필요
2. **Sans-serif 폰트 실제 로드**: 현재 system-ui 기본값 사용 중. Inter 같은 폰트를 실제 로드하면 더 정교한 느낌 가능
3. **색상 토큰 정리**: `--pico-ins-color`, `--pico-del-color`, `--pico-warning` 같은 Pico 참조가 DecisionsView/AccountsView에 남아있음. Phase 3에서 `--status-*`로 마이그레이션 필요
