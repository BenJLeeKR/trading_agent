# Plan 58: Admin UI Design Detail Alignment (최종)

## 핵심 원칙
- **목표**: 템플릿과의 시각적 정합성 최대 달성
- **방법**: CSS 값 조정이 우선, class rename은 수단일 뿐
- **제외**: 템플릿에 없는 SummaryCard 상단 컬러 border 제거
- **불가**: auth/API/tabs/loading state 등 기능 구조 차이는 유지

---

## 1. CSS-only (admin-theme.css) — 34개 조정

### A. Design Token (:root)
| 항목 | 현재 | 템플릿 |
|------|------|--------|
| `--text-xs` | 0.65rem | **0.75rem** (12px) |
| `--text-sm` | 0.7rem | **0.875rem** (14px) |
| `--text-base` | 0.8rem | **1rem** (16px) |
| `--text-md` | 0.85rem | **0.875rem** (정렬, template에 없음) |
| `--text-lg` | 0.9rem | **1.125rem** (18px) |
| `--text-xl` | 1.1rem | **1.25rem** (20px) |
| `--text-2xl` | 1.4rem | **1.5rem** (24px) |

### B. Table (lines 774-791)
- thead th: padding `0.5rem 0.75rem` → **0.625rem 1rem**
- thead th: font-weight 600 → **500**
- thead th: text-transform uppercase → **none**
- thead th: letter-spacing wide → **normal**
- tbody td: padding `0.5rem 0.75rem` → **0.625rem 1rem**
- compact mode: `0.3rem 0.55rem` → **0.25rem 0.5rem**
- selected row: `border-left: 2px solid` → **none**

### C. pill-btn (lines 1247-1269) ← 템플릿 버튼 기준으로 정렬
- radius: `var(--radius-sm)=6px` → **var(--radius-md)=8px**
- inactive color: `var(--text-muted)=#9ca3af` → **#6b7280**
- padding: `0.25rem 0.55rem` → **0.25rem 0.625rem** (px-2.5 py-1)
- border: `none` → 유지
- active bg: `#1d2939` → 이미 일치 ✓
- active text: `#fff` → 이미 일치 ✓

### D. filter-group-btn (lines 1219-1245) ← CSS 값만 pill-btn과 일치하도록 조정 (class 통일이 목적이 아니라 시각 일치가 목적)
- OrdersView/ReconciliationView는 `filter-group-btn`을 사용 중
- 시각 결과를 템플릿과 일치시키려면 border 제거, radius/color/padding/font-size 변경 필요
- `pill-btn`과 동일한 값으로 맞춤: border none, radius 8px, color #6b7280, padding 0.25rem 0.625rem
- **결과적으로 두 class가 동일해지므로 `pill-btn`으로 rename하는 게 유지보수에 유리**

### E. 모든 카드 radius → var(--radius-lg)=12px
- `.summary-card` line 484: `var(--radius-md)` → `var(--radius-lg)`
- `.card-panel` line 1278: `var(--radius-md)` → `var(--radius-lg)`
- `.account-card` line 1347: `var(--radius-md)` → `var(--radius-lg)`
- `.alerts-panel` line 1575: `var(--radius-md)` → `var(--radius-lg)`

### F. 계정 카드 폰트
- font-size 0.6rem(9.6px) → **0.625rem(10px)** — template `text-[10px]`와 일치
- `.account-card-id` line 1370
- `.account-card-status` line 1380
- `.account-card-label` line 1394
- `.account-card-broker` line 1406

### G. detail-row padding (line 1671)
- `0.35rem 0` → **0.375rem 0** (template py-1.5)

### H. filter-bar container (lines 633-639)
- bg: 없음 → **#fff**
- border: 없음 → **1px solid #e8eaed**
- border-radius: 없음 → **12px**
- padding: 없음 → **0.75rem**

### I. Layout (lines 1445-1498)
- `.top-header`: padding `0 1.25rem` → **0.75rem 1.5rem**, height `3rem` → **auto**
- `.top-header-greeting`: font-size `var(--text-md)` → **var(--text-lg)** (template h1=18px)
- `.top-header-date-badge`: radius `var(--radius-sm)` → **var(--radius-md)=8px**
- `.top-header-notif-btn`: radius `var(--radius-sm)` → **var(--radius-md)=8px**

### J. alerts-panel padding (line 1577)
- `var(--space-4)` → **var(--space-3)** (template p-3 = 0.75rem)

### K. SummaryCard 상단 컬러 border 제거 (lines 558-566)
- `.summary-card--ok`, `.summary-card--warn`, `.summary-card--error` border-top 제거
- 템플릿에 없는 디자인 요소이므로 삭제

### L. 신규 CSS class 추가
```css
.panel-body { padding: 0.75rem 1rem; }
.sidebar-logout-btn { ... }  /* Layout.tsx inline 스타일 대체 */
.status-footer--success { ... }  /* ReconciliationView green footer */
.status-footer--warning { ... }  /* ReconciliationView amber footer */
.summary-card-grid { grid-template-columns: repeat(3, 1fr); }  /* AccountsView inline grid 이동 */
```

---

## 2. Component (TSX) 변경 — 5개 파일

### OrdersView.tsx
- lines 160, 175: `filter-group-btn` → `pill-btn` (시각 일치를 위해)
- lines 286, 319: `style={{ padding: "0.75rem 1rem" }}` → `<div className="panel-body">`

### ReconciliationView.tsx
- line 202: `filter-group-btn` → `pill-btn` (시각 일치를 위해)
- line 251: `style={{ padding: "0.75rem 1rem" }}` → `<div className="panel-body">`
- lines 292-337: 인라인 status footer → CSS class + 동적 class만 유지

### AccountsView.tsx
- line 271: `account-card--selected` → `account-card--active` (CSS selector와 일치)
- line 318: `style={{ gridTemplateColumns: ... }}` 제거, CSS class로 대체

### DecisionsView.tsx
- lines 298,311,317,330,365,377: `style={{ padding: "0.75rem 1rem" }}` → `<div className="panel-body">`
- lines 352,358,364,377: inline padding → `.panel-body`

### Layout.tsx
- lines 140-153: logout button inline style → `.sidebar-logout-btn` class

---

## 3. 수정 후 보고 템플릿

모든 수정 완료 후 다음 항목별로 템플릿 값과 현재 값 차이를 보고합니다:

| 카테고리 | 항목 | 템플릿 값 | 수정 후 값 | 일치 여부 |
|---------|------|-----------|-----------|----------|
| Typography | --text-xs | 0.75rem | ? | ? |
| Typography | --text-sm | 0.875rem | ? | ? |
| Typography | --text-base | 1rem | ? | ? |
| Typography | --text-lg | 1.125rem | ? | ? |
| Typography | --text-xl | 1.25rem | ? | ? |
| Typography | --text-2xl | 1.5rem | ? | ? |
| Card | border-radius | 12px | ? | ? |
| Card | padding | 1rem | ? | ? |
| Button | border-radius | 8px | ? | ? |
| Button | inactive color | #6b7280 | ? | ? |
| Button | active bg | #1d2939 | ? | ? |
| Table | th padding | 0.625rem 1rem | ? | ? |
| Table | th font | 12px/500 | ? | ? |
| Table | td padding | 0.625rem 1rem | ? | ? |
| Filter bar | bg | #fff | ? | ? |
| Filter bar | border-radius | 12px | ? | ? |
| Filter bar | padding | 0.75rem | ? | ? |
| Detail panel | detail-row padding | 0.375rem 0 | ? | ? |
| Detail panel | detail-row border | #f9fafb | ? | ? |
| Layout | top-header padding | 0.75rem 1.5rem | ? | ? |
| Layout | greeting font-size | 1.125rem | ? | ? |

---

## 4. 실행 순서 (요약)

1. **Phase A**: `:root` typography token 6개
2. **Phase B**: Table + pill-btn + filter-bar + card radius + account fonts + detail-row + compact + panel-body class + summary-card border-top 제거 + alerts padding
3. **Phase C**: Layout (top-header, greeting, date-badge, notif-btn)
4. **Phase D**: TSX 5개 파일 (class align + inline→class)
5. **Phase E**: 검증 (test + build) + 보고
