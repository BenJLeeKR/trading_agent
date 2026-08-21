# Plan: 운영 대시보드 Section B — 스냅샷 동기화 → 정합성 점검 변경

## 목적
운영 대시보드의 Section B (두 번째 최근 요약 섹션)를 `최근 스냅샷 동기화` → `최근 정합성 점검`으로 변경한다. 데이터 소스도 `snapshotSyncRuns` → `reconRuns`로 전환한다.

## 작업 범위
- 프런트엔드만 수정 (`admin_ui/src/components/OperationsDashboardView.tsx`)
- API 계약 변경 없음
- mock 데이터 추가 없음

## 현재 상태 분석

### 이미 존재하는 데이터
- `data.reconRuns: ReconciliationRunSummary[]` — 이미 `getReconciliationRuns(accounts[0].account_id)`로 fetch 중 (lines 258-266)
- `ReconciliationRunSummary` 타입 필드: `run_id`, `account_id`, `started_at`, `completed_at`, `status`, `order_mismatches`, `position_mismatches`

### 유지해야 하는 것
- `getSnapshotSyncRuns(10)` 호출 — `StatusCard` (snapshot sync 상태)와 `deriveAlerts` alert rule에서 여전히 필요
- `data.snapshotSyncRuns` — 위 카드/경고에서 사용

### 변경해야 하는 것

#### 1. 인터페이스 이름 변경 (lines 57-64)
```typescript
// 변경 전
interface CompactSyncItem { ... totalAccounts: number; errorCount: number; }

// 변경 후
interface CompactReconciliationItem {
  id: string;
  startedAt: string;
  status: string;
  statusVariant: "success" | "warning" | "error" | "neutral";
  mismatchCount: number;   // order_mismatches + position_mismatches
  completedAt: string | null;
}
```

#### 2. useMemo 변경 (lines 507-542)
```typescript
// 변경 전
const compactSyncRuns: CompactSyncItem[] = useMemo(() => {
  if (!data) return [];
  return [...data.snapshotSyncRuns]
    .sort(...)
    .slice(0, 5)
    .map(r => ({ ... totalAccounts, errorCount }));

// 변경 후
const compactReconciliationRuns: CompactReconciliationItem[] = useMemo(() => {
  if (!data) return [];
  return [...data.reconRuns]
    .sort((a, b) => new Date(b.started_at ?? 0).getTime() - new Date(a.started_at ?? 0).getTime())
    .slice(0, 5)
    .map(r => ({
      id: r.run_id,
      startedAt: r.started_at ?? "-",
      status: statusLabel,  // completed→정상, partial→주의, failed→긴급, default→r.status
      statusVariant,
      mismatchCount: (r.order_mismatches ?? 0) + (r.position_mismatches ?? 0),
      completedAt: r.completed_at,
    }));
```

#### 3. JSX Section B 변경 (lines 781-812)

**제목**: `최근 스냅샷 동기화` → `최근 정합성 점검`
**링크**: 그대로 `/reconciliation`, 텍스트 `정합성 점검 보기` (변경 없음)
**컬럼**:
| 변경 전 | 변경 후 |
|---------|---------|
| 시작시각 | 시작시각 |
| 상태 | 상태 |
| 전체계좌 | 불일치건수 (order_mismatches + position_mismatches) |
| 오류 | 완료시각 |

**emptyMessage**: `동기화 이력 없음` → `정합성 점검 이력 없음`

**타입 참조**: `CompactSyncItem` → `CompactReconciliationItem`

#### 4. DashboardData에서 snapshotSyncRuns 제거 여부
- **유지** — StatusCard(마지막 스냅샷 동기화)와 alert rule에서 사용 중
- `data.snapshotSyncRuns`는 그대로 두고, Section B만 reconRuns로 전환

### 상태 뱃지 매핑 (ReconciliationRun status → 한글 레이블 + variant)

| status | 레이블 | variant |
|--------|--------|---------|
| completed | 정상 | success |
| partial | 주의 | warning |
| failed | 긴급 | error |
| 기타 | r.status | neutral |

### account_id 없을 때 처리
- 이미 `accounts.length > 0` 가드가 존재 (line 260)
- 계좌 없으면 `reconRuns`는 빈 배열 → empty state 표시
- 422 발생하지 않음

---

## 실행 단계 (Code 모드)

1. `CompactSyncItem` → `CompactReconciliationItem` 인터페이스 교체 (lines 57-64)
2. `compactSyncRuns` useMemo → `compactReconciliationRuns` useMemo로 교체 (lines 507-542)
   - 데이터 소스: `data.snapshotSyncRuns` → `data.reconRuns`
   - 필드: `totalAccounts`/`errorCount` → `mismatchCount`/`completedAt`
3. JSX Section B 교체 (lines 781-812)
   - 제목, 컬럼, 데이터, 타입 참조, emptyMessage 변경
4. Build 검증: `cd admin_ui && npm run build`
5. Test 검증: `cd admin_ui && npm run test:run`
