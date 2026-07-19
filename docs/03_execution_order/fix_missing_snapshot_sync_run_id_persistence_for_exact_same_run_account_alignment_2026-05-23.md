# Snapshot Sync Run ID 미저장 버그 수정 보고서

**날짜:** 2026-05-23  
**작성자:** Roo (Debug/Code mode)  
**태그:** `bugfix`, `FK constraint`, `snapshot_sync_run_id`, `execution_order`

---

## 1. 문제 요약

`cash_balance_snapshots`와 `position_snapshots` 테이블에서 `snapshot_sync_run_id`가 `NULL`로 저장되는 버그.  
migration 0027 (`add_snapshot_sync_run_id.sql`)로 FK 컬럼이 추가되었으나, 실제 snapshot 저장 시 runtime에서 FK가 설정되지 않음.

### 영향

- 전체 `position_snapshots` 4,428건 중 `snapshot_sync_run_id IS NOT NULL` = **0건**
- 전체 `cash_balance_snapshots` 1,576건 중 `snapshot_sync_run_id IS NOT NULL` = **0건**
- `/account-snapshots/latest` API에서 `snapshot_sync_run_id` 기반 path(account alignment 판별)가 동작하지 않음

---

## 2. 근본 원인 — Foreign Key Constraint Violation

### 2.1 코드 경로 검증

모든 개별 코드 경로는 정상:

| 컴포넌트 | 파일 | 상태 |
|----------|------|------|
| Entity (`PositionSnapshotEntity`) | [`entities.py:117`](../src/agent_trading/domain/entities.py#117) | `snapshot_sync_run_id: UUID \| None = None` ✅ |
| Entity (`CashBalanceSnapshotEntity`) | [`entities.py:138`](../src/agent_trading/domain/entities.py#138) | `snapshot_sync_run_id: UUID \| None = None` ✅ |
| Repository INSERT SQL (position) | [`position_snapshots.py:33`](../src/agent_trading/repositories/postgres/position_snapshots.py#33) | `$13` 포함 ✅ |
| Repository INSERT SQL (cash) | [`cash_balance_snapshots.py:39`](../src/agent_trading/repositories/postgres/cash_balance_snapshots.py#39) | `$14` 포함 ✅ |
| Service - `sync_account_snapshots()` stamp | [`snapshot_sync.py:237`](../src/agent_trading/services/snapshot_sync.py#237) | `object.__setattr__()` 정상 동작 ✅ |
| Service - `sync_all_accounts()` 전달 | [`snapshot_sync.py:438`](../src/agent_trading/services/snapshot_sync.py#438) | 파라미터 전달 정상 ✅ |

### 2.2 실행 순서 버그 (Root Cause)

문제는 [`scripts/run_snapshot_sync_loop.py`](../scripts/run_snapshot_sync_loop.py)의 `_run_one_cycle()` 함수에서 **실행 순서**가 잘못된 것:

```
Before fix (버그 발생):
  1. run_id = uuid4()
  2. sync_all_accounts(... snapshot_sync_run_id=run_id)
     → snapshot INSERT 시도 (position_snapshots, cash_balance_snapshots)
     → snapshot_sync_run_id FK가 snapshot_sync_runs 테이블에 없음
     → ❌ FOREIGN KEY CONSTRAINT VIOLATION
     → INSERT 실패 → snapshot 저장 안 됨 (rollback or silent fail)
  3. repos.snapshot_sync_runs.add(run_entity)  ← 너무 늦음!
```

실제 DB 오류 메시지:
```
ERROR: Failed to persist position snapshot...
foreign key constraint "position_snapshots_snapshot_sync_run_id_fkey"
DETAIL: Key (snapshot_sync_run_id)=<uuid> is not present in table "snapshot_sync_runs"
```

---

## 3. 수정 내용

### 3.1 [`SnapshotSyncRunRepository` Protocol](../src/agent_trading/repositories/contracts.py) — `update_run()` 추가

```python
class SnapshotSyncRunRepository(Protocol):
    async def add(self, run: SnapshotSyncRunEntity) -> SnapshotSyncRunEntity: ...
    async def list_runs(self, ...) -> ...: ...
    async def get(self, run_id: UUID) -> SnapshotSyncRunEntity | None: ...
    async def update_run(self, run: SnapshotSyncRunEntity) -> SnapshotSyncRunEntity: ...  # ← NEW
    async def get_sync_health_summary(self, ...) -> ...: ...
```

### 3.2 [`PostgresSnapshotSyncRunRepository`](../src/agent_trading/repositories/postgres/snapshot_sync_runs.py) — `update_run()` 구현

```python
async def update_run(self, run: SnapshotSyncRunEntity) -> SnapshotSyncRunEntity:
    row = await self._tx.connection.fetchrow(
        """
        UPDATE trading.snapshot_sync_runs SET
            trigger_type=$2, scope=$3, ... status=$16, ...
        WHERE snapshot_sync_run_id=$1
        RETURNING *
        """,
        run.snapshot_sync_run_id, run.trigger_type, ...
    )
    return row_to_entity(row, SnapshotSyncRunEntity)
```

### 3.3 [`InMemorySnapshotSyncRunRepository`](../src/agent_trading/repositories/memory.py) — `update_run()` 구현

```python
async def update_run(self, run: SnapshotSyncRunEntity) -> SnapshotSyncRunEntity:
    self._items[run.snapshot_sync_run_id] = run
    return run
```

### 3.4 [`_run_one_cycle()`](../scripts/run_snapshot_sync_loop.py) — 실행 순서 변경

```
After fix (정상 동작):
  1. run_id = uuid4()
  2. repos.snapshot_sync_runs.add(running_entity)  ← "running" 상태로 먼저 INSERT
     → snapshot_sync_runs 테이블에 FK 대상 row 존재
  3. sync_all_accounts(... snapshot_sync_run_id=run_id)
     → snapshot INSERT 성공! FK 만족
  4. repos.snapshot_sync_runs.update_run(run_entity)  ← 실제 결과로 UPDATE
     → status: "completed" / "partial" / "failed"
```

핵심 변경 코드:

```python
# 3a. "running" 상태의 sync run을 먼저 생성 (FK 확보)
running_entity = SnapshotSyncRunEntity(
    snapshot_sync_run_id=run_id,
    trigger_type="scheduler",
    scope="all",
    status="running",                    # ← running 상태
    total_accounts=0,
    succeeded_accounts=0,
    ...
)
await repos.snapshot_sync_runs.add(running_entity)

# 3b. snapshot sync 실행 (FK constraint 만족)
batch = await sync_all_accounts(
    ...,
    snapshot_sync_run_id=run_id,
)

# 3c. sync run을 실제 결과로 UPDATE
run_entity = build_sync_run_entity(
    batch, ..., snapshot_sync_run_id=run_id,
)
await repos.snapshot_sync_runs.update_run(run_entity)
```

---

## 4. 검증 결과

### 4.1 수동 Sync 실행 (Docker container)

```
DEBUG_POS_FK: add() called snapshot_sync_run_id=4fc1225b-... (3 positions)
DEBUG_CASH_FK: add() called snapshot_sync_run_id=4fc1225b-... (1 cash)
Snapshot cycle complete — accounts=1 success=1 partial=0 fail=0
```

✅ **FK 위반 없음**, 3 position + 1 cash snapshot 저장 성공

### 4.2 DB 직접 조회 (MCP PostgreSQL query)

| 테이블 | `IS NOT NULL` | 전체 | 비율 |
|--------|--------------|------|------|
| `position_snapshots` | **3** | 4,431 | 수정 전 0% → 최신 3건 저장 ✅ |
| `cash_balance_snapshots` | **1** | 1,580 | 수정 전 0% → 최신 1건 저장 ✅ |
| `snapshot_sync_runs` | N/A | 1,990 | 정상 운영 중 |

### 4.3 Pytest 회귀 테스트

- **Snapshot/sync_run/account_snapshot 관련 테스트: 182/182 통과** ✅
- 전체 테스트: 417/418 통과 (1건 실패는 **기존 issue** — KIS dev token cache, 무관)

---

## 5. 변경된 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| [`scripts/run_snapshot_sync_loop.py`](../scripts/run_snapshot_sync_loop.py) | ✅ 수정 | 실행 순서 변경 + `SnapshotSyncRunEntity` import 추가 |
| [`src/agent_trading/repositories/contracts.py`](../src/agent_trading/repositories/contracts.py) | ✅ 수정 | `update_run()` Protocol 메서드 추가 |
| [`src/agent_trading/repositories/postgres/snapshot_sync_runs.py`](../src/agent_trading/repositories/postgres/snapshot_sync_runs.py) | ✅ 수정 | `update_run()` PostgreSQL 구현 |
| [`src/agent_trading/repositories/memory.py`](../src/agent_trading/repositories/memory.py) | ✅ 수정 | `update_run()` In-memory 구현 |

---

## 6. 재발 방지 대책

1. **실행 순서 검증**: FK 참조가 필요한 INSERT는 항상 참조 대상 row가 먼저 INSERT되었는지 확인
2. **Two-phase 패턴**: "running" 상태로 먼저 기록 → 완료 후 UPDATE 패턴을 다른 유사 케이스에도 적용 가능
3. **테스트 강화**: 향후 snapshot sync 관련 테스트에서 transaction 내 실행 순서 검증 케이스 추가 고려

---

## 7. Docker Container 영향

변경사항은 bind mount (`./src:/app/src`, `./scripts:/app/scripts`)를 통해 자동 반영:

- `agent_trading-ops-scheduler-1`: subprocess로 `run_snapshot_sync_loop.py` 호출 → 최신 코드 사용
- `agent_trading-snapshot-sync-1`: 직접 `run_snapshot_sync_loop.py` 실행 → 최신 코드 사용

별도의 container 재시작 없이 즉시 적용됨.
