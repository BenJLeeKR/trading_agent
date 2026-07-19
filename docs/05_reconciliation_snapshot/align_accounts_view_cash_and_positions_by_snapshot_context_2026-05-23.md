# Account 화면 Cash / Position Snapshot Context Alignment 개선 보고서

## 개요

**목표**: `AccountsView.tsx` 화면에서 cash balance와 position 데이터가 서로 다른 snapshot 시점에 조회되어 발생하는 시각적 불일치 문제를 해결한다.

**일자**: 2026-05-23

**관련 파일**:
- `src/agent_trading/api/schemas.py` — Pydantic 스키마 (AlignmentStatus / AccountSnapshotResponse)
- `src/agent_trading/api/routes/account_snapshots.py` — 신규 combined endpoint
- `src/agent_trading/api/app.py` — router 등록
- `admin_ui/src/types/api.ts` — TypeScript 타입 정의
- `admin_ui/src/api/client.ts` — API 클라이언트 함수
- `admin_ui/src/components/AccountsView.tsx` — UI alignment badge 표시

---

## 1. 문제 분석

### 1.1 기존 상황

기존 `AccountsView.tsx`는 `selectedAccount`가 변경될 때 [`Promise.all([getPositions(), getCashBalance()])`](admin_ui/src/components/AccountsView.tsx:106)로 **두 개의 독립적인 HTTP 요청**을 병렬 전송했다.

- `GET /positions?account_id=...` — position snapshot 목록
- `GET /cash-balances?account_id=...` — cash balance snapshot (단일)

두 요청은 서로 다른 시점에 처리되며, 백엔드에서 각각 최신 snapshot을 독립적으로 조회한다. 실제 운영 데이터를 확인한 결과:

| 항목 | Snapshot 시점 (UTC) |
|------|-------------------|
| Positions | `2026-05-23T11:20:02Z` |
| Cash Balance | `2026-05-23T12:45:41Z` |

**약 85분 차이** — 동일한 화면에서 전혀 다른 시점의 데이터가 표시됨.

### 1.2 근본 원인

1. **DB 스키마**: [`position_snapshots`](db/migrations/0025_add_fetch_status_to_snapshot_tables.sql) 및 [`cash_balance_snapshots`](db/migrations/0025_add_fetch_status_to_snapshot_tables.sql) 테이블에 `snapshot_sync_run_id` 컬럼이 **없음**. `snapshot_sync_runs` 테이블에만 PK로 존재.
2. **Domain Entity**: [`PositionSnapshotEntity`](src/agent_trading/domain/entities.py:118)와 [`CashBalanceSnapshotEntity`](src/agent_trading/domain/entities.py:136) 모두 `snapshot_sync_run_id` 필드 미포함.
3. **KIS Sync 로직**: [`sync_kis_account_snapshots()`](src/agent_trading/services/kis_snapshot_sync.py:189)는 VTTC8434R merged call로 cash+position을 동시에 가져오지만, **DB 저장 시점이 Phase 1/2로 분할**되어 cash와 position의 `snapshot_at`이 달라질 수 있음.
4. **조회 로직**: Position은 [`DISTINCT ON (instrument_id)`](src/agent_trading/repositories/postgres/position_snapshots.py:60)로 각 종목별 최신, Cash는 [`ORDER BY snapshot_at DESC LIMIT 1`](src/agent_trading/repositories/postgres/cash_balance_snapshots.py:70)로 단일 최신 — timestamp 불일치 발생.

### 1.3 검토된 접근법

| 접근법 | 설명 | 선택 |
|--------|------|------|
| **A** | DB migration으로 `snapshot_sync_run_id` 컬럼 추가 + 조인 쿼리 | ❌ 스키마 변경 부담 |
| **B** | Phase 1/2 통합으로 단일 트랜잭션 저장 | ❌ KIS API 변경 필요 |
| **C** | **Combined endpoint + timestamp 기반 alignment 판별** | ✅ |

---

## 2. 적용된 변경사항

### 2.1 Backend: 신규 Combined Endpoint

**Endpoint**: `GET /account-snapshots/latest?account_id=<uuid>`

**Response Model** — [`AccountSnapshotResponse`](src/agent_trading/api/schemas.py:639):

```python
class AlignmentStatus(str, Enum):
    ALIGNED = "aligned"      # cash와 position의 snapshot_at 차이 ≤ 5초
    PARTIAL = "partial"      # cash/position 중 하나만 존재하거나 timestamp 차이 > 5초
    UNKNOWN = "unknown"      # 두 데이터 모두 없음

class AccountSnapshotResponse(BaseModel):
    account_id: UUID
    positions: list[PositionSnapshotView]
    cash_balance: CashBalanceSnapshotView | None
    alignment_status: AlignmentStatus
    positions_snapshot_at: datetime | None
    cash_snapshot_at: datetime | None
```

**Route 구현** — [`account_snapshots.py`](src/agent_trading/api/routes/account_snapshots.py):

```python
@router.get("/account-snapshots/latest", response_model=AccountSnapshotResponse)
async def get_latest_account_snapshots(...):
    positions = await repos.position_snapshots.list_latest_by_account(aid)
    # instrument enrichment (symbol, instrument_name)
    cash = await repos.cash_balance_snapshots.get_latest_by_account(aid)
    alignment = _compute_alignment_status(pos_snapshot_at, cash_snapshot_at)
    return AccountSnapshotResponse(...)
```

**Alignment 판별 로직** — [`_compute_alignment_status()`](src/agent_trading/api/routes/account_snapshots.py:33):

```python
def _compute_alignment_status(
    positions_snapshot_at: datetime | None,
    cash_snapshot_at: datetime | None,
    tolerance: timedelta = timedelta(seconds=5),
) -> AlignmentStatus:
    if positions_snapshot_at and cash_snapshot_at:
        diff = abs(positions_snapshot_at - cash_snapshot_at)
        if diff <= tolerance:
            return AlignmentStatus.ALIGNED
        return AlignmentStatus.PARTIAL
    return AlignmentStatus.PARTIAL if (
        positions_snapshot_at or cash_snapshot_at
    ) else AlignmentStatus.UNKNOWN
```

**Router 등록** — [`app.py`](src/agent_trading/api/app.py):

```python
from agent_trading.api.routes.account_snapshots import router as account_snapshots_router
protected_routers.append(account_snapshots_router)
```

### 2.2 Frontend: 타입 정의 및 클라이언트

**TypeScript 타입** — [`api.ts`](admin_ui/src/types/api.ts:165):

```typescript
export type AlignmentStatus = "aligned" | "partial" | "unknown";

export interface AccountSnapshotResponse {
  account_id: string;
  positions: PositionSnapshotView[];
  cash_balance: CashBalanceSnapshotView | null;
  alignment_status: AlignmentStatus;
  positions_snapshot_at: string | null;
  cash_snapshot_at: string | null;
}
```

**API 클라이언트** — [`client.ts`](admin_ui/src/api/client.ts:197):

```typescript
export async function getAccountSnapshots(accountId: string): Promise<AccountSnapshotResponse> {
  return request<AccountSnapshotResponse>(`/account-snapshots/latest?account_id=${encodeURIComponent(accountId)}`);
}
```

### 2.3 Frontend: UI 개선

**AccountsView.tsx** — 주요 변경사항:

1. **Import 변경**: `getPositions, getCashBalance` → `getAccountSnapshots`, `AlignmentStatus`
2. **State 추가**: `const [snapshotAlignment, setSnapshotAlignment] = useState<AlignmentStatus | null>(null)`
3. **Fetch 로직 단일화**: `Promise.all` → 단일 `getAccountSnapshots()` 호출
4. **Alignment Badge** — snapshot 섹션 라벨 우측에 표시:

| 상태 | 배지 색상 | 텍스트 |
|------|----------|--------|
| `aligned` | 초록 (`#16a34a`) | "동일 snapshot 기준" |
| `partial` | 노랑 (`#b45309`) | "시점 어긋남" |
| `unknown` | 회색 (`#64748b`) | "snapshot 정보 없음" |

---

## 3. 테스트 결과

### 3.1 Backend 테스트 (pytest)

```
tests/api/test_account_snapshots.py .                                   [  5%]
...
==== 18 passed in 4.23s ====
```

기존 17개 + 신규 1개 테스트 모두 통과.

### 3.2 Frontend 빌드

```bash
# TypeScript 검사
$ npx tsc --noEmit
# (일부 pre-existing fixture.ts 오류 — 본 PR과 무관)

# Vite build
$ npx vite build
✓ 1756 modules transformed.
✓ built in 6.27s
```

### 3.3 Docker 통합 검증

```bash
$ docker compose build api
$ docker compose up -d api
$ curl -s "http://localhost:8000/account-snapshots/latest?account_id=a44a02d1-..."
```

**응답**:
```json
{
  "account_id": "a44a02d1-...",
  "positions": [/* 12 positions */],
  "cash_balance": { /* full cash balance data */ },
  "alignment_status": "partial",
  "positions_snapshot_at": "2026-05-23T11:20:02.795423Z",
  "cash_snapshot_at": "2026-05-23T12:45:41.617495Z"
}
```

- **Status**: `200 OK`
- **Alignment**: `partial` (85분 차이 — 실제 데이터 기준 정확히 감지)
- **Positions**: 12개
- **Cash Balance**: 정상 포함됨

---

## 4. 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| [`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py) | 수정 | `AlignmentStatus` enum, `AccountSnapshotResponse` 모델 추가 |
| [`src/agent_trading/api/routes/account_snapshots.py`](src/agent_trading/api/routes/account_snapshots.py) | **신규** | Combined endpoint + alignment 판별 로직 |
| [`src/agent_trading/api/app.py`](src/agent_trading/api/app.py) | 수정 | `account_snapshots_router` 등록 |
| [`admin_ui/src/types/api.ts`](admin_ui/src/types/api.ts) | 수정 | `AlignmentStatus`, `AccountSnapshotResponse` 타입 추가 |
| [`admin_ui/src/api/client.ts`](admin_ui/src/api/client.ts) | 수정 | `getAccountSnapshots()` 함수 추가 |
| [`admin_ui/src/components/AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx) | 수정 | 단일 API 호출 + alignment badge 표시 |

---

## 5. 한계점 및 향후 과제

### 5.1 Current Limitations

1. **Timestamp 기반 추정**: 실제 sync run ID로 조인하는 것이 아니므로, 동일 KIS 호출에서 가져온 데이터라도 우연히 timestamp 차이가 5초를 넘으면 `partial`로 표시될 수 있음.
2. **Phase 분할 문제 미해결**: KIS snapshot sync의 Phase 1/2 구조 자체는 변경되지 않았으므로, cash와 position의 저장 시점 차이는 여전히 발생 가능.
3. **5초 tolerance의 trade-off**: 너무 짧으면 false partial, 너무 길면 실제 불일치를 놓침.

### 5.2 향후 개선 방향

1. **DB 마이그레이션**: `position_snapshots`와 `cash_balance_snapshots` 테이블에 `snapshot_sync_run_id` FOREIGN KEY 컬럼 추가.
   - 정확한 sync run 단위 조인 가능
   - 리포팅/감사 쿼리에서 유용
2. **Domain Entity 확장**: `PositionSnapshotEntity` / `CashBalanceSnapshotEntity`에 `snapshot_sync_run_id` 필드 추가.
3. **KIS Sync 저장 로직 개선**: Phase 1/2를 하나의 트랜잭션으로 묶어 `snapshot_at` 통일.
4. **UI 확장**: alignment badge에 hover tooltip으로 실제 timestamp 표시.
5. **알림 기능**: `partial` 상태가 지속될 경우 운영자에게 알림.

---

## 6. 결론

DB 스키마 변경 없이 **combined endpoint + timestamp alignment detection** 접근법으로 Account 화면의 cash/position 불일치 문제를 해결했다. 실제 운영 데이터에서 85분 차이를 정확히 감지하여 `partial` 상태로 표시함을 확인했다. 향후 DB migration을 통해 더 정확한 sync-run 기반 조인으로 개선할 수 있다.
