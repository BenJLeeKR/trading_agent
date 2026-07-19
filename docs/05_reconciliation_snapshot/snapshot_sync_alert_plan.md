# Snapshot Sync 상태 경고 보강 계획 (보정사항 반영)

## 1. 현재 상태 분석

### 1.1 사용 가능한 백엔드 API (변경 불필요)

| API 엔드포인트 | 설명 | 프론트엔드 연동 상태 |
|---------------|------|-------------------|
| `GET /snapshot-sync-runs?limit=1` | 최근 sync run 목록 (status, partial_accounts, error_count 등) | ❌ 미연동 |
| `GET /snapshot-sync-runs/summary` | Sync health 요약 (last_status, consecutive_failures, is_stale) | ❌ 미연동 |
| `GET /health` | snapshot_sync_detail, snapshot_sync_stale, snapshot_sync_last_successful_run_at, snapshot_sync_consecutive_failures | ✅ 타입 누락 |

### 1.2 백엔드 계약 확인 완료

- `GET /snapshot-sync-runs` — `src/agent_trading/api/routes/snapshot_sync_runs.py:52`
  - prefix: `/snapshot-sync-runs`
  - params: `limit` (Query, default 50), `trigger_type` (optional), `status` (optional)
  - response: `list[SnapshotSyncRunSummary]`
  
- `GET /snapshot-sync-runs/summary` — `src/agent_trading/api/routes/snapshot_sync_runs.py:78`
  - prefix: `/snapshot-sync-runs/summary`
  - params: 없음
  - response: `SnapshotSyncRunHealthSummary`

### 1.3 `SnapshotSyncRunSummary` 스키마 (schemas.py 기준)

```python
class SnapshotSyncRunSummary(BaseModel):
    snapshot_sync_run_id: str
    trigger_type: str
    scope: str
    dry_run: bool
    total_accounts: int
    succeeded_accounts: int
    partial_accounts: int
    failed_accounts: int
    skipped_accounts: int
    positions_synced_total: int
    positions_skipped_total: int
    cash_synced_count: int
    error_count: int
    status: str           # "completed" | "partial" | "failed"
    started_at: datetime
    completed_at: datetime | None = None
    env_filter: str | None = None
    status_filter: str | None = None
    summary_json: dict[str, object] | None = None
```

### 1.4 `SnapshotSyncRunHealthSummary` 스키마 (schemas.py 기준)

```python
class SnapshotSyncRunHealthSummary(BaseModel):
    last_run_started_at: datetime | None = None
    last_run_completed_at: datetime | None = None
    last_status: str | None = None        # "completed" | "partial" | "failed" | None
    last_successful_run_at: datetime | None = None
    consecutive_failures: int = 0
    is_stale: bool = False
    stale_threshold_seconds: int = 900
```

---

## 2. 필요한 변경사항

### 2.1 [`types/api.ts`](admin_ui/src/types/api.ts) — 타입 추가

```typescript
// HealthResponse 확장 (백엔드 schemas.py 기준)
export interface HealthResponse {
  status: string;
  database: string;
  runtime_mode: string;
  snapshot_sync_detail: string | null;
  snapshot_sync_stale: boolean | null;
  snapshot_sync_last_successful_run_at: string | null;
  snapshot_sync_consecutive_failures: number | null;
}

// 신규 — GET /snapshot-sync-runs 응답
export interface SnapshotSyncRunSummary {
  snapshot_sync_run_id: string;
  trigger_type: string;
  scope: string;
  dry_run: boolean;
  total_accounts: number;
  succeeded_accounts: number;
  partial_accounts: number;
  failed_accounts: number;
  skipped_accounts: number;
  positions_synced_total: number;
  positions_skipped_total: number;
  cash_synced_count: number;
  error_count: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  env_filter: string | null;
  status_filter: string | null;
  summary_json: Record<string, unknown> | null;
}

// 신규 — GET /snapshot-sync-runs/summary 응답
export interface SnapshotSyncRunHealthSummary {
  last_run_started_at: string | null;
  last_run_completed_at: string | null;
  last_status: string | null;
  last_successful_run_at: string | null;
  consecutive_failures: number;
  is_stale: boolean;
  stale_threshold_seconds: number;
}
```

### 2.2 [`api/client.ts`](admin_ui/src/api/client.ts) — API 함수 추가

```typescript
export async function getSnapshotSyncRuns(
  limit?: number,
  status?: string
): Promise<import("../types/api").SnapshotSyncRunSummary[]> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  if (status) params.set("status", status);
  const qs = params.toString();
  return request<import("../types/api").SnapshotSyncRunSummary[]>(
    `/snapshot-sync-runs${qs ? `?${qs}` : ""}`
  );
}

export async function getSnapshotSyncSummary(): Promise<
  import("../types/api").SnapshotSyncRunHealthSummary
> {
  return request<import("../types/api").SnapshotSyncRunHealthSummary>(
    "/snapshot-sync-runs/summary"
  );
}
```

### 2.3 [`OperationsAlertsView.tsx`](admin_ui/src/components/OperationsAlertsView.tsx) — 경고 규칙 추가

**fetchAlerts 수정**: 기존 API 호출에 `getSnapshotSyncRuns(1)` 추가

**deriveAlerts에 추가할 규칙** (보정사항 반영):

| ID | 조건 | 수준 | 제목 | 설명 |
|:--:|------|:----:|------|------|
| SNAP-SYNC-001 | `run.status === 'partial'` (error_count=0 포함) | **주의** | 스냅샷 부분 성공 | 일부 스냅샷 미갱신 가능 (partial N건, 실패 M건) |
| SNAP-SYNC-002 | `run.status === 'failed'` | 긴급 | 스냅샷 동기화 실패 | 최근 스냅샷 동기화 실패 |
| SNAP-SYNC-003a | API 오류 (fetch 실패) | 긴급 | 스냅샷 동기화 상태 조회 실패 | API 연결 실패 |
| SNAP-SYNC-003b | run 없음 (null) | 긴급 | 스냅샷 동기화 이력 없음 | 실행 이력 없음 |
| SNAP-TIME-001 | position/cash 모두 snapshot_at 있고, 차이 10분↑ | 경고 | 현금/포지션 스냅샷 시각 불일치 | 두 snapshot 시각 차이 N분 |

### 2.4 [`OperationsDashboardView.tsx`](admin_ui/src/components/OperationsDashboardView.tsx) — Snapshot sync StatusCard 개선

- **우선**: `snapshot_sync_runs` 최신 status를 StatusCard value에 반영
  - completed + not stale → 정상
  - partial → 주의 (일부 미갱신)
  - failed → 즉시 확인
  - no run → 스냅샷 없음
- **보조**: position/cash snapshot_at을 subtitle에 표시

---

## 3. 검증

```bash
cd /workspace/agent_trading/admin_ui && npm run build
cd /workspace/agent_trading/admin_ui && npm run test:run
```

---

## 4. 제약 조건 준수 확인

| 제약 | 준수 |
|------|:----:|
| 백엔드 API 변경 금지 | ✅ `GET /snapshot-sync-runs`만 사용 (기존 엔드포인트) |
| 타입 필드명은 백엔드 schemas.py 기준 | ✅ 확인 완료 |
| API 오류와 run 없음 구분 | ✅ 별도 alert ID |
| partial은 긴급이 아닌 주의 | ✅ level='주의' |
| error_count=0이어도 status=partial이면 경고 | ✅ 조건에 error_count 미포함 |
| position/cash 시각 차이는 둘 다 있을 때만 계산 | ✅ 조건 추가 |
| Dashboard는 sync run status 우선, snapshot_at은 보조 | ✅ 구현 |

---

## 5. 대시보드 StatusCard 변경 설계

| sync run status | 카드 Value | 카드 status | Subtitle |
|:---------------:|:----------:|:-----------:|----------|
| completed, not stale | 정상 | healthy | position/cash snapshot_at 시각 |
| completed, stale | 지연 확인 | warning | 마지막 갱신: N분 전 |
| partial | 주의 | warning | 일부 스냅샷 미갱신 (partial N건) |
| failed | 즉시 확인 | error | 마지막 동기화 실패 |
| no run / null | 스냅샷 없음 | error | 실행 이력 없음 |
