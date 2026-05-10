# Phase 2 Inspection API Expansion Plan

## 1. 현재 상태 분석 (Gap Assessment)

### 1.1 사용자가 요청한 10개 Endpoint 중 이미 존재하는 것

| Endpoint | 파일 | 상태 |
|----------|------|------|
| `GET /orders/{id}/broker-orders` | [`orders.py`](src/agent_trading/api/routes/orders.py:134) | ✅ 이미 구현됨 |
| `GET /accounts/{id}` | [`accounts.py`](src/agent_trading/api/routes/accounts.py:57) | ✅ 이미 구현됨 |
| `GET /clients/{id}` | [`clients.py`](src/agent_trading/api/routes/clients.py:24) | ✅ 이미 구현됨 |
| `GET /instruments/{id}` | [`instruments.py`](src/agent_trading/api/routes/instruments.py:14) | ✅ 이미 구현됨 |
| `GET /positions?account_id=...` | [`positions.py`](src/agent_trading/api/routes/positions.py:19) | ✅ 이미 구현됨 |
| `GET /cash-balances?account_id=...` | [`positions.py`](src/agent_trading/api/routes/positions.py:42) | ✅ 이미 구현됨 |
| `GET /reconciliation/locks?account_id=...` | [`reconciliation.py`](src/agent_trading/api/routes/reconciliation.py:56) | ✅ 이미 구현됨 |
| `GET /agent-runs` | [`agent_runs.py`](src/agent_trading/api/routes/agent_runs.py:40) | ✅ 이미 구현됨 (단, detail by ID 없음) |

### 1.2 실제로 누락된 Endpoint

| Endpoint | 필요 작업 |
|----------|-----------|
| `GET /agent-runs/{agent_run_id}` | (1) [`AgentRunRepository`](src/agent_trading/repositories/contracts.py:571)에 `get()` 메서드 추가 (2) InMemory + Postgres 구현 (3) route handler 추가 |
| `GET /guardrail-evaluations` | (1) [`GuardrailEvaluationRepository`](src/agent_trading/repositories/contracts.py:442)에 `list_by_account()`, `get()` 추가 (2) 신규 route 파일 생성 (3) Pydantic schema 추가 |
| `GET /risk-limit-snapshots` | (1) 신규 route 파일 생성 (2) Pydantic schema 추가 (repository는 이미 adequate) |

### 1.3 Repository Contract Gap Matrix

| Repository | 현재 메서드 | 추가 필요한 메서드 |
|------------|------------|-------------------|
| [`AgentRunRepository`](src/agent_trading/repositories/contracts.py:571) | `add()`, `list_by_decision_context()`, `list_all()` | `get(agent_run_id: UUID) -> AgentRunEntity \| None` |
| [`GuardrailEvaluationRepository`](src/agent_trading/repositories/contracts.py:442) | `add()`, `get_by_decision_context()`, `get_by_order_request()` | `get(evaluation_id: UUID) -> GuardrailEvaluationEntity \| None`, `list_by_account(account_id: UUID) -> Sequence[...]` |
| [`RiskLimitSnapshotRepository`](src/agent_trading/repositories/contracts.py:459) | `add()`, `get_latest_by_account()`, `list_by_account()` | ✅ 충분 (변경 불필요) |

### 1.4 Pydantic Schema Gap

| 스키마 | 상태 |
|--------|------|
| [`GuardrailEvaluationView`](src/agent_trading/api/schemas.py) | ❌ 없음 — 신규 생성 필요 |
| [`RiskLimitSnapshotView`](src/agent_trading/api/schemas.py) | ❌ 없음 — 신규 생성 필요 |

---

## 2. 상세 구현 계획

### Step 1: [`contracts.py`](src/agent_trading/repositories/contracts.py) — Protocol 확장

**1a. `AgentRunRepository`에 `get()` 추가**
```python
class AgentRunRepository(Protocol):
    # ... existing methods ...
    
    async def get(self, agent_run_id: UUID) -> AgentRunEntity | None:
        """Get a single agent run by its UUID."""
        ...
```

**1b. `GuardrailEvaluationRepository`에 `get()` + `list_by_account()` 추가**
```python
class GuardrailEvaluationRepository(Protocol):
    # ... existing methods ...
    
    async def get(
        self, guardrail_evaluation_id: UUID
    ) -> GuardrailEvaluationEntity | None:
        """Get a single guardrail evaluation by its UUID."""
        ...
    
    async def list_by_account(
        self, account_id: UUID, limit: int = 20
    ) -> Sequence[GuardrailEvaluationEntity]:
        """List guardrail evaluations for an account (via decision_context join)."""
        ...
```

### Step 2: [`memory.py`](src/agent_trading/repositories/memory.py) — InMemory 구현

**2a. `InMemoryAgentRunRepository.get()`**
- `self._runs`가 list이므로 UUID로 linear scan 또는 dict 변환
- 간단하게 dict lookup을 위해 `self._items: dict[UUID, AgentRunEntity]`로 변경하거나 그대로 list scan
- **권장**: 기존 `self._runs: list` 유지하고 linear scan (데이터가 적으므로)

**2b. `InMemoryGuardrailEvaluationRepository.get()` + `list_by_account()`**
- `get()`: self._items dict lookup
- `list_by_account()`: decision_context_id를 통해 account_id를 알 수 없으므로, 이 메서드는 외부에서 account_id→decision_context_id 매핑을 받거나 간단히 빈 결과 반환
- **권장**: InMemory에서는 항상 빈 list 반환하고, Postgres만 실제 구현 (inspection 용도이므로)

### Step 3: Postgres 구현체 확장

**3a. [`postgres/agent_runs.py`](src/agent_trading/repositories/postgres/agent_runs.py) — `get()` 추가**
```sql
SELECT * FROM trading.agent_runs WHERE agent_run_id = $1
```

**3b. [`postgres/guardrail_evaluations.py`](src/agent_trading/repositories/postgres/guardrail_evaluations.py) — `get()` + `list_by_account()` 추가**
```sql
-- get()
SELECT * FROM trading.guardrail_evaluations WHERE guardrail_evaluation_id = $1

-- list_by_account()
SELECT ge.* FROM trading.guardrail_evaluations ge
JOIN trading.decision_contexts dc ON ge.decision_context_id = dc.decision_context_id
WHERE dc.account_id = $1
ORDER BY ge.evaluated_at DESC
LIMIT $2
```

### Step 4: [`schemas.py`](src/agent_trading/api/schemas.py) — Pydantic Response Model 추가

**4a. `GuardrailEvaluationView`**
```python
class GuardrailEvaluationView(BaseModel):
    """Read-only guardrail evaluation result."""
    model_config = ConfigDict(from_attributes=True)
    
    guardrail_evaluation_id: str
    rule_set_version: str
    overall_passed: bool
    evaluated_at: datetime
    decision_context_id: str | None = None
    trade_decision_id: str | None = None
    order_request_id: str | None = None
    rule_results: dict[str, object] = {}
    blocking_rule_codes: list[str] | None = None
    warning_rule_codes: list[str] | None = None
    created_at: datetime | None = None
```

**4b. `RiskLimitSnapshotView`**
```python
class RiskLimitSnapshotView(BaseModel):
    """Read-only risk limit snapshot."""
    model_config = ConfigDict(from_attributes=True)
    
    risk_limit_snapshot_id: str
    account_id: str
    snapshot_at: datetime
    nav: Decimal | None = None
    cash_available: Decimal | None = None
    gross_exposure_pct: Decimal | None = None
    net_exposure_pct: Decimal | None = None
    daily_realized_pnl: Decimal | None = None
    daily_unrealized_pnl: Decimal | None = None
    daily_loss_used_pct: Decimal | None = None
    max_daily_loss_limit_pct: Decimal | None = None
    symbol_exposure_json: dict[str, object] = {}
    sector_exposure_json: dict[str, object] = {}
    open_order_exposure_json: dict[str, object] = {}
    drawdown_state: str | None = None
    kill_switch_active: bool = False
    blocked_reason_codes: list[str] | None = None
    created_at: datetime | None = None
```

### Step 5: [`agent_runs.py`](src/agent_trading/api/routes/agent_runs.py) — Detail Endpoint 추가

```python
@router.get("/agent-runs/{agent_run_id}", response_model=AgentRunResponse)
async def get_agent_run(
    agent_run_id: UUID = Path(...),
    repos: RepositoryContainer = Depends(get_repos),
) -> AgentRunResponse:
    """Get a single agent run by its UUID."""
    run = await repos.agent_runs.get(agent_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return _to_response(run)
```

### Step 6: [`guardrail_evaluations.py`](src/agent_trading/api/routes/guardrail_evaluations.py) — 신규 Route 파일

새 파일 생성. 패턴은 [`positions.py`](src/agent_trading/api/routes/positions.py)와 동일:

```python
"""Guardrail evaluation inspection endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import UUID

router = APIRouter(tags=["guardrail-evaluations"])

@router.get("/guardrail-evaluations", response_model=list[GuardrailEvaluationView])
async def list_guardrail_evaluations(
    account_id: UUID | None = Query(None),
    decision_context_id: UUID | None = Query(None),
    order_request_id: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    repos = Depends(get_repos),
):
    """List guardrail evaluations, optionally filtered."""
    if account_id:
        results = await repos.guardrail_evaluations.list_by_account(account_id, limit)
    elif decision_context_id:
        results = await repos.guardrail_evaluations.get_by_decision_context(decision_context_id)
    elif order_request_id:
        results = await repos.guardrail_evaluations.get_by_order_request(order_request_id)
    else:
        return []
    return [_to_guardrail_view(r) for r in results]

@router.get("/guardrail-evaluations/{evaluation_id}", response_model=GuardrailEvaluationView)
async def get_guardrail_evaluation(
    evaluation_id: UUID = Path(...),
    repos = Depends(get_repos),
):
    """Get a single guardrail evaluation by its UUID."""
    evaluation = await repos.guardrail_evaluations.get(evaluation_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Guardrail evaluation not found")
    return _to_guardrail_view(evaluation)
```

### Step 7: [`risk_limit_snapshots.py`](src/agent_trading/api/routes/risk_limit_snapshots.py) — 신규 Route 파일

```python
"""Risk limit snapshot inspection endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import UUID

router = APIRouter(tags=["risk-limit-snapshots"])

@router.get("/risk-limit-snapshots", response_model=list[RiskLimitSnapshotView])
async def list_risk_limit_snapshots(
    account_id: UUID = Query(...),
    limit: int = Query(20, ge=1, le=200),
    repos = Depends(get_repos),
):
    """List risk limit snapshots for an account, newest first."""
    snapshots = await repos.risk_limit_snapshots.list_by_account(account_id, limit)
    return [_to_risk_snapshot_view(s) for s in snapshots]

@router.get("/risk-limit-snapshots/latest", response_model=RiskLimitSnapshotView | None)
async def get_latest_risk_limit_snapshot(
    account_id: UUID = Query(...),
    repos = Depends(get_repos),
):
    """Get the latest risk limit snapshot for an account."""
    snapshot = await repos.risk_limit_snapshots.get_latest_by_account(account_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No risk limit snapshot found for this account")
    return _to_risk_snapshot_view(snapshot)
```

### Step 8: [`app.py`](src/agent_trading/api/app.py) — Router 등록

```python
# Phase 2 routers (Milestone 6 — decision inspection & reconciliation)
from agent_trading.api.routes import (
    decisions, accounts, instruments, positions,
    clients, agent_runs, broker_capacity, snapshot_sync_runs,
    performance, guardrail_evaluations, risk_limit_snapshots,
)
# ... in Phase 2 block:
app.include_router(guardrail_evaluations.router)
app.include_router(risk_limit_snapshots.router)
```

### Step 9: [`test_inspection.py`](tests/api/test_inspection.py) — In-Memory 테스트 추가

기존 [`test_inspection.py`](tests/api/test_inspection.py) 패턴에 맞춰 3개의 Test Class 추가:

- `TestAgentRunsDetail` — `GET /agent-runs/{id}` (found + not_found + invalid_uuid)
- `TestGuardrailEvaluations` — `GET /guardrail-evaluations` (by account, by decision_context, by id, not_found)
- `TestRiskLimitSnapshots` — `GET /risk-limit-snapshots` (list + latest + not_found)

각 테스트는 기존 `client` fixture(seeded data)와 `empty_client` fixture 사용.

Seed data에 `GuardrailEvaluationEntity`와 `RiskLimitSnapshotEntity`를 [`conftest.py`](tests/api/conftest.py)에 추가해야 함.

### Step 10: [`test_postgres_inspection.py`](tests/api/test_postgres_inspection.py) — Postgres Smoke Test

기존 `TestPostgresInspectionAPI` 클래스에 2-3개 smoke test 추가:
- `test_guardrail_evaluations_empty` — 빈 결과 확인
- `test_risk_limit_snapshots_requires_account` — account_id 없이 422 확인

### Step 11: [`BACKLOG.md`](plans/BACKLOG.md) 업데이트

Backlog items #5 (Phase 2 API endpoints), #6 (Postgres-backed API mode), #7 (reconciliation locks) 상태를 "completed ✅"로 갱신하고 승격 기록 추가.

---

## 3. 변경 불가 항목 (No-Go)

- ❌ Admin UI redesign
- ❌ Broker submit semantics 변경
- ❌ Hard guardrail / reconciliation boundary 변경
- ❌ 기존 API semantics 변경 (기존 endpoint는 그대로 유지)
- ❌ Write API 추가 (read-only inspection 유지)
- ❌ GuardrailEvaluationRepository의 기존 메서드 시그니처 변경

---

## 4. 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `src/agent_trading/repositories/contracts.py` | 수정 | AgentRunRepository.get(), GuardrailEvaluationRepository.get()/list_by_account() 추가 |
| `src/agent_trading/repositories/memory.py` | 수정 | InMemoryAgentRunRepository.get(), InMemoryGuardrailEvaluationRepository.get()/list_by_account() 추가 |
| `src/agent_trading/repositories/postgres/agent_runs.py` | 수정 | get() 메서드 추가 |
| `src/agent_trading/repositories/postgres/guardrail_evaluations.py` | 수정 | get() + list_by_account() 메서드 추가 |
| `src/agent_trading/api/schemas.py` | 수정 | GuardrailEvaluationView, RiskLimitSnapshotView 추가 |
| `src/agent_trading/api/routes/agent_runs.py` | 수정 | GET /agent-runs/{id} route 추가 |
| `src/agent_trading/api/routes/guardrail_evaluations.py` | **신규** | GET /guardrail-evaluations, GET /guardrail-evaluations/{id} |
| `src/agent_trading/api/routes/risk_limit_snapshots.py` | **신규** | GET /risk-limit-snapshots, GET /risk-limit-snapshots/latest |
| `src/agent_trading/api/app.py` | 수정 | guardrail_evaluations, risk_limit_snapshots router 등록 |
| `tests/api/conftest.py` | 수정 | GuardrailEvaluationEntity, RiskLimitSnapshotEntity seed data 추가 |
| `tests/api/test_inspection.py` | 수정 | 3개 Test Class 추가 |
| `tests/api/test_postgres_inspection.py` | 수정 | Smoke test 2-3개 추가 |
| `plans/BACKLOG.md` | 수정 | #5, #6, #7 상태 갱신 |
