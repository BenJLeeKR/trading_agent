# 수정 계획 (v2 — 범위 축소)

## 작업 1: 운영 대시보드 System Status Summary 제거

**파일:** [`OperationsDashboardView.tsx`](admin_ui/src/components/OperationsDashboardView.tsx:536)

**변경사항:**
- Lines 536-556: `{/* System Status Summary (항상 표시) */}` div 블록 전체 제거 (API/DB/Ready badge 3개)

**변경하지 않는 것:**
- Cash 계산/라벨 (`totalAvailableCash`, `cashUsedFallback`, "가용 현금" 등) — **변경 금지**
- 기존 StatusCard 그리드 — **변경 금지**
- `SHOW_ADVANCED_OPERATION_CARDS` — **변경 금지**
- `Layout.tsx` — **변경 금지**

## 작업 2: 계좌 화면 현금 프레임 라벨 변경

**파일:** [`AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx:591)

**변경사항:**
- Line 591: `주문가능금액:` → `예수금:`

**변경하지 않는 것:**
- `available_cash`, `settled_cash`, `unsettled_cash` 필드 매핑 — **변경 금지**
- 상단 요약 카드 "현금 잔고" 값/라벨 — **변경 금지**
- `총 자산` 계산 — **변경 금지**
- OperationsDashboardView cash 계산/라벨 — **변경 금지**
