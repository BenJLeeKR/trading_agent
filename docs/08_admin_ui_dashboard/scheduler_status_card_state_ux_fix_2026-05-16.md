# Scheduler Status Card UX Fix Report

**Date:** 2026-05-16  
**Author:** Roo (Code mode)  
**Task:** Admin UI Scheduler Status UX 보정 — No Data / Stale / Error 상태 구분

---

## Problem

운영 대시보드의 `Scheduler Status` 카드가 `market_sessions` row 가 없을 때 **빨간 `오류` 배지**를 표시.  
이는 실제 API 실패(500)와 동일한 시각적 표현으로, 운영자가 **No Data / Stale / Real Error**를 구분할 수 없었음.

## Root Cause

1. **`OperationsDashboardView.tsx`** (line 711-718, previous):
   ```tsx
   status={d.session ? (d.sessionHealthy ? 'healthy' : 'warning') : 'error'}
   ```
   - `session == null` → `status="error"` (빨간색)
   - `session == null` → `value="No Data"` (영문, 혼동 유발)

2. **`StatusCard.tsx`** had no way to override the badge label — the label was hardcoded per variant via `statusLabels` map.

## Changes Made

### Files Modified

| File | Change |
|------|--------|
| [`admin_ui/src/components/common/StatusCard.tsx`](admin_ui/src/components/common/StatusCard.tsx) | Added optional `badgeLabel` prop to override default badge text |
| [`admin_ui/src/components/OperationsDashboardView.tsx`](admin_ui/src/components/OperationsDashboardView.tsx:108) | Added `getSchedulerStatus()` helper (exported), updated derived state and card rendering |
| [`admin_ui/src/__tests__/schedulerStatus.test.ts`](admin_ui/src/__tests__/schedulerStatus.test.ts) | **New file**: 17 unit tests for all scheduler status scenarios |

### Detail: `StatusCard.tsx`

Added optional `badgeLabel` prop:
```tsx
interface StatusCardProps {
  title: string;
  value: string | number;
  status: StatusVariant;
  subtitle?: string | React.ReactNode;
  badgeLabel?: string;  // NEW: overrides statusLabels[status]
}
```
Usage in render: `{badgeLabel ?? statusLabels[status]}`

### Detail: `OperationsDashboardView.tsx` — New `getSchedulerStatus()` Logic

**Priority order** (top = highest priority):

| Condition | badgeLabel | variant | subtitle |
|-----------|-----------|---------|----------|
| `hasFetchError` | `오류` | `error` (red) | Error message |
| `!session` (no data) | `미수집` | `neutral` (gray) | `No session data yet` |
| `source === 'gate_error_fallback' \|\| 'fallback'` | `대체` | `warning` (orange) | `Fallback: {phase}` |
| `!healthy \|\| staleSeconds > 600` | `지연` | `warning` (yellow) | `Last checked: {checked_at}` |
| Healthy | `정상` | `healthy` (green) | `Source: {source} \| Phase: {phase}` |

### Detail: Session Events Panel

**Before:** Panel hidden entirely when `sessionEvents` array is empty (`{d.sessionEvents.length > 0 && <Panel>...}`)  
**After:** Panel always rendered, showing `"No events yet"` neutral message when empty.

## Before vs After (Scheduler Status Card)

| State | Before | After |
|-------|--------|-------|
| **No Data** (session=null) | 🔴 `No Data` + red error badge | ⚪ `미수집` + gray neutral badge |
| **Healthy** | 🟢 `Healthy` + green healthy badge | 🟢 `정상` + green healthy badge |
| **Stale** | 🟡 `Stale` + yellow warning badge | 🟡 `지연` + yellow warning badge |
| **Fallback** | 🟡 `Stale` + yellow warning badge | 🟠 `대체` + orange warning badge |
| **Error** (fetch failed) | 🔴 `No Data` + red error badge | 🔴 `오류` + red error badge |

## Verification

### Build
```bash
cd admin_ui && npm run build
# ✓ built in 1.68s (tsc + vite)
```

### Tests
```bash
cd admin_ui && npm test -- --run
# Test Files: 13 passed (13)
#      Tests: 129 passed (129)
```

### New Test Coverage (`schedulerStatus.test.ts`)

| Scenario | Tests | Key Assertions |
|----------|-------|---------------|
| No Data (session=null) | 2 | `variant='neutral'`, `badgeLabel='미수집'`, NOT error |
| Healthy session | 2 | `variant='healthy'`, `badgeLabel='정상'`, subtitle contains source/phase |
| Stale (unhealthy) | 1 | `variant='warning'`, `badgeLabel='지연'` |
| Stale (stale_seconds > 600) | 1 | `variant='warning'`, NOT error |
| Mild staleness (< 10 min) | 1 | Treated as healthy |
| Fetch error | 3 | `variant='error'`, `badgeLabel='오류'`, shows error message |
| Fallback source | 3 | `variant='warning'`, `badgeLabel='대체'`, NOT error |
| Priority ordering | 2 | Fetch error > No Data > Fallback > Stale > Healthy |
| Edge cases | 1 | All possible source values don't throw |

## Compatibility Notes

- `.env` not modified
- Backend not modified (pure frontend change)
- `StatusCard` existing usages unaffected (optional `badgeLabel` prop, defaults to existing behavior)
- All existing 112 tests still pass
