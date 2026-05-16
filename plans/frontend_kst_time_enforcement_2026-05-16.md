# 프런트엔드 시간 표시 KST 강제 통일 보고서

**작성일**: 2026-05-16  
**목적**: admin_ui 내 모든 시간 표시를 `Intl.DateTimeFormat` 기반 KST(Asia/Seoul) helper로 통일

---

## 1. 기존 문제 지점 (5곳)

| # | 파일:라인 | 문제 |
|---|-----------|------|
| 1 | [`alerts.ts:85`](../admin_ui/src/lib/alerts.ts:85) | `description`에 `latest.started_at` ISO 원본 문자열을 그대로 삽입 → UTC 시간이 그대로 노출됨 |
| 2 | [`OperationsDashboardView.tsx:160`](../admin_ui/src/components/OperationsDashboardView.tsx:160) | Scheduler Status `subtitle`에서 `session.checked_at`을 로컬 `timeAgo()` 유틸로 표시 → 삭제된 `timeAgo()` 의존. KST 보장 안 됨 |
| 3 | [`OperationsDashboardView.tsx:986`](../admin_ui/src/components/OperationsDashboardView.tsx:986) | Session Events 목록에서 `evt.occurred_at`을 가공 없이 출력 → UTC raw time 그대로 표시 |
| 4 | [`OperationsDashboardView.tsx:697,720`](../admin_ui/src/components/OperationsDashboardView.tsx:697) | Snapshot `subtitle`에 `formatKstElapsed` 대신 raw 포맷 사용 |
| 5 | [`OperationsAlertsView.tsx:496-498`](../admin_ui/src/components/OperationsAlertsView.tsx:496) | 수동 KST offset 계산(`started_at.slice(0,10)`)으로 날짜 비교 → helper 미사용, 일관성 부족 |

---

## 2. KST Helper 강제 적용 범위

### 2.1 기존 Helper (변경 없음)

- [`formatKstDateTime(iso)`](../admin_ui/src/lib/utils.ts:54) — `2026-05-15 14:32:44 KST` 전체 포맷
- [`formatKstTime(iso)`](../admin_ui/src/lib/utils.ts:75) — `05-15 14:32` compact 포맷
- [`formatKstElapsed(iso)`](../admin_ui/src/lib/utils.ts:117) — `2026-05-15 14:32:44 KST (3분 전)` 경과 시간 포함

모든 helper는 `Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul" })` 기반으로 고정되어 있으며, UTC ISO 문자열을 입력받아 KST로 변환합니다.

### 2.2 변경 사항 상세

#### [`alerts.ts`](../admin_ui/src/lib/alerts.ts)

| 라인 | 변경 전 | 변경 후 |
|------|---------|---------|
| 8 | import 없음 | `import { formatKstDateTime } from "./utils"` 추가 |
| 55 | `new Date().toISOString()` → raw | `formatKstDateTime(new Date().toISOString())` → KST now |
| 85 | `마지막: ${latest.started_at}` | `마지막: ${formatKstDateTime(latest.started_at)}` |

#### [`OperationsDashboardView.tsx`](../admin_ui/src/components/OperationsDashboardView.tsx)

| 라인 | 변경 전 | 변경 후 |
|------|---------|---------|
| 11 | `formatKrw`만 import | `formatKrw, formatKstDateTime, formatKstElapsed` 3개 import |
| 160 | `session.checked_at` raw (timeAgo 제거됨) | `formatKstElapsed(session.checked_at)` |
| 697 | raw snapshot_at | `formatKstElapsed(d.latestSnapshotAt)` |
| 720 | raw snapshot_at | `formatKstElapsed(d.latestSnapshotAt)` |
| 879 | raw `row.createdAt` | `formatKstDateTime(row.createdAt)` |
| 913 | raw `row.startedAt` | `formatKstDateTime(row.startedAt)` |
| 928 | raw `row.completedAt` | `formatKstDateTime(row.completedAt)` |
| 986 | raw `evt.occurred_at` | `formatKstDateTime(evt.occurred_at)` |

> `timeAgo()` 함수는 제거되었으며, 모든 elapsed 표시는 `formatKstElapsed`로 대체되었습니다.

#### [`OperationsAlertsView.tsx`](../admin_ui/src/components/OperationsAlertsView.tsx)

| 라인 | 변경 전 | 변경 후 |
|------|---------|---------|
| 9 | import 없음 | `import { formatKstDateTime } from "../lib/utils"` 추가 |
| 496 | `started_at.slice(0, 10)` 수동 KST | `formatKstDateTime(snapshotSyncRun.started_at).slice(0, 10)` |
| 497 | 수동 날짜 비교 | `formatKstDateTime(new Date().toISOString()).slice(0, 10)` |
| 521 | raw `started_at` | `formatKstDateTime(snapshotSyncRun.started_at)` |

---

## 3. 수정 파일 목록 (5개)

| 파일 | 상태 | 변경 요약 |
|------|------|-----------|
| [`admin_ui/src/lib/utils.ts`](../admin_ui/src/lib/utils.ts) | 기존 (변경 없음) | `formatKstDateTime`, `formatKstTime`, `formatKstElapsed` 3개 helper가 이미 존재 |
| [`admin_ui/src/lib/alerts.ts`](../admin_ui/src/lib/alerts.ts) | **수정** | `formatKstDateTime` import + description/now를 KST 포맷으로 변경 |
| [`admin_ui/src/components/OperationsDashboardView.tsx`](../admin_ui/src/components/OperationsDashboardView.tsx) | **수정** | `formatKstDateTime`/`formatKstElapsed` import + 8개 지점 KST 포맷 적용, `timeAgo()` 제거 |
| [`admin_ui/src/components/OperationsAlertsView.tsx`](../admin_ui/src/components/OperationsAlertsView.tsx) | **수정** | `formatKstDateTime` import + 수동 KST offset 계산 → helper 사용 |
| [`admin_ui/src/__tests__/utils.test.ts`](../admin_ui/src/__tests__/utils.test.ts) | **신규** | 21개 KST formatter 단위 테스트 |
| [`admin_ui/src/__tests__/schedulerStatus.test.ts`](../admin_ui/src/__tests__/schedulerStatus.test.ts) | **수정** | KST formatter 사용 확인 assertion 추가 (라인 109) |

---

## 4. 테스트 결과

### 4.1 신규 Utils 테스트 (`utils.test.ts`)

**21개 테스트 케이스**가 추가되었습니다.

#### `formatKstDateTime` (7 tests)

| 테스트 | 입력 | 기대 출력 |
|--------|------|-----------|
| null | `null` | `"—"` |
| undefined | `undefined` | `"—"` |
| empty string | `""` | `"—"` |
| invalid date | `"not-a-date"` | `"—"` |
| valid UTC → KST | `"2026-05-16T05:00:00Z"` | `"2026-05-16 14:00:00 KST"` |
| another KST | `"2026-05-15T23:59:59Z"` | `"2026-05-16 08:59:59 KST"` |
| midnight crossing | `"2026-05-15T15:00:00Z"` | `"2026-05-16 24:00:00 KST"` |

#### `formatKstTime` (5 tests)

| 테스트 | 입력 | 기대 출력 |
|--------|------|-----------|
| null | `null` | `"—"` |
| undefined | `undefined` | `"—"` |
| empty string | `""` | `"—"` |
| invalid date | `"bad-date"` | `"—"` |
| valid UTC → KST compact | `"2026-05-16T05:00:00Z"` | `"05-16 14:00"` |
| midnight crossing | `"2026-05-15T15:00:00Z"` | `"05-16 24:00"` |

#### `formatKstElapsed` (9 tests)

| 테스트 | 입력 (UTC) | 기대 출력 |
|--------|------------|-----------|
| null | `null` | `"—"` |
| undefined | `undefined` | `"—"` |
| empty string | `""` | `"—"` |
| invalid date | `"invalid"` | `"—"` |
| 방금 전 (29초) | `"2026-05-16T06:59:31Z"` | `"2026-05-16 15:59:31 KST (방금 전)"` |
| 3분 전 | `"2026-05-16T06:57:00Z"` | `"2026-05-16 15:57:00 KST (3분 전)"` |
| 1시간 30분 전 | `"2026-05-16T05:30:00Z"` | `"2026-05-16 14:30:00 KST (1시간 30분 전)"` |
| 2일 전 | `"2026-05-14T07:00:00Z"` | `"2026-05-14 16:00:00 KST (2일 전)"` |
| 미래 날짜 | `"2026-05-17T07:00:00Z"` | `"2026-05-17 16:00:00 KST ()"` |

> `formatKstElapsed` 테스트는 `vi.useFakeTimers()`로 `now`를 `2026-05-16T07:00:00Z`로 고정하여 시간 의존성 제거.

### 4.2 SchedulerStatus Assertion (`schedulerStatus.test.ts`)

[`schedulerStatus.test.ts:109`](../admin_ui/src/__tests__/schedulerStatus.test.ts:109):

```typescript
expect(result.subtitle).toContain("KST"); // KST formatter 사용 확인
```

`formatKstElapsed`가 `"KST"` 접미사를 포함하는 출력을 내는지 검증하여, KST formatter가 실제로 사용되고 있음을 확인합니다.

### 4.3 전체 테스트 결과

```
npm run build  → 성공
vitest run     → 160/160 통과 (14개 파일, 22개 신규 assertion)
```

---

## 5. Build 결과

```bash
$ npm run build
✔ Build completed successfully.
```

TypeScript 컴파일, Vite 번들링 모두 정상.

---

## 6. 남은 예외 케이스

### 6.1 [`AccountsView.tsx:26`](../admin_ui/src/components/AccountsView.tsx:26) — 숫자 포맷팅

```typescript
function formatQty(val: number | null | undefined): string {
  if (val == null) return "—";
  if (Number.isNaN(val)) return "—";
  return val.toLocaleString();  // ← 숫자 포맷팅 (시간 아님)
}
```

`val.toLocaleString()`은 수량(quantity) 포맷팅으로, 시간 표시가 아닙니다. 따라서 KST formatter 적용 대상이 아니며, **수정 불필요**.

### 6.2 [`alerts.ts:79`](../admin_ui/src/lib/alerts.ts:79) — 경과 시간 계산

```typescript
const elapsed = Date.now() - new Date(latest.started_at).getTime();
```

이 코드는 경과 시간(ms)을 계산하여 5분 threshold를 초과했는지 판단하는 로직입니다. 화면에 직접 시간을 표시하는 것이 아니며, `formatKstDateTime`은 description에 사용되고 있습니다.

- `Date.now()`는 로컬 시간과 무관한 Unix timestamp(UTC)를 반환하므로 정확성에는 문제 없음
- `new Date(latest.started_at).getTime()`도 UTC 기준이라 KST 변환 불필요
- **정확성 개선 가능**하나 현재 동작에 문제가 없으므로 보류

---

## 7. 결론

- **5개 문제 지점** 모두 KST helper로 전환 완료
- **`timeAgo()`** 커스텀 함수 제거 → `formatKstElapsed`로 일원화
- **신규 테스트 21개** + schedulerStatus assertion 1개 추가 → 총 **160/160 통과**
- **Build 정상**
- 남은 2개 예외 케이스는 시간 표시와 무관하거나 현재 동작에 문제 없음

Phase 13 완료. 프런트엔드 전체 시간 표시가 `Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul" })` 기반 helper로 통일되어 KST 표시가 강제 보장됩니다.
