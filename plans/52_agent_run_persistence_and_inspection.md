# Plan 52 — AgentRun 영속화 경로 구현 및 Inspection Read Path 정렬

## 목적

`AgentRunRecorder`의 in-memory 전용 stub을 repository-backed 구조로 전환하고,  
`GET /agent-runs` inspection API를 추가하여 AI Agent 실행 이력을 DB에 저장하고 조회할 수 있게 한다.

## 현재 상태

```mermaid
flowchart LR
    subgraph "현재"
        A[DecisionOrchestratorService] --> B[AgentRunRecorder in-memory list]
        B --> C[메모리 휘발 저장]
        C --> D[프로세스 재시작 시 소실]
    end
    
    subgraph "목표"
        E[DecisionOrchestratorService] --> F[AgentRunRecorder repository-backed]
        F --> G[AgentRunRepository protocol]
        G --> H[PostgresAgentRunRepository]
        G --> I[InMemoryAgentRunRepository]
        H --> J[trading.agent_runs 테이블]
        I --> K[메모리 대체]
        F --> L[GET /agent-runs API]
    end
```

### 이미 존재하는 것

| 항목 | 위치 | 상태 |
|------|------|------|
| `AgentRunEntity` | `entities.py:159-173` | ✅ 13개 필드, DB와 완벽 정렬 |
| `trading.agent_runs` 테이블 | `migrations/0001_initial_schema.sql` | ✅ 컬럼·제약조건·인덱스 완비 |
| `row_to_entity()` | `row_mapper.py:58-94` | ✅ Enum 필드 없음, 별도 변환 불필요 |
| `AgentRunRecorder.record()` (async) | `recorder.py:43-163` | ✅ 비즈니스 로직(agent_name 정합성, decision_context_id payload vs storage 분리) 존재 |
| `AgentRunRecorder.list_*()` (sync) | `recorder.py:165-177` | ⚠️ sync, Postgres 적응 위해 async 변환 필요 |
| `DecisionOrchestratorService.__init__` | `decision_orchestrator.py:280-297` | ✅ `agent_recorder` DI 지원 |
| `_run_agents()` → `record()` 호출 | `decision_orchestrator.py:552-724` | ✅ 수정 불필요 (record는 이미 async) |
| `_build_orchestrator()` | `runtime/bootstrap.py:197-234` | ⚠️ `agent_recorder` 미주입 → default `AgentRunRecorder()` 사용 |

### 만들어야 할 것

| 항목 | 설명 |
|------|------|
| `AgentRunRepository` protocol | `contracts.py`에 추가 - `add()`, `list_by_decision_context()`, `list_all()` |
| `InMemoryAgentRunRepository` | `memory.py`에 구현 |
| `PostgresAgentRunRepository` | `postgres/agent_runs.py` 신규 파일 |
| `RepositoryContainer.agent_runs` | `container.py`에 필드 추가 |
| `build_in_memory_repositories()` + `build_postgres_repositories()` | 각각 wiring 추가 |
| `AgentRunRecorder` 개선 | repository DI, query async화, clear() 유지 |
| `_build_orchestrator()` | `AgentRunRecorder(repo)` 주입 |
| `AgentRunResponse` schema | `api/schemas.py`에 Pydantic 모델 |
| `GET /agent-runs` route | `api/routes/agent_runs.py` 신규 파일 |
| `app.py` 등록 | protected router로 등록 |
| 테스트 | repository unit test + API integration test |

## 변경 불가 항목

다음은 이 Plan의 범위에서 **절대 수정하지 않는다**:

- `OrderManager` (`services/order_manager.py`)
- `ReconciliationService` (`services/reconciliation_service.py`)
- `BrokerAdapter` 및 `KoreaInvestmentAdapter`
- Hard Guardrail Engine
- `admin_ui/` 전체
- `_run_agents()` 내부의 EI→AR→FDC 요청 체인 구조 (request→request_with_ei→request_with_ei_and_ar)
- 기존 `agent_recorder.record()` 호출부 (`decision_orchestrator.py:605,637,659`)

## 상세 구현 계획

### Step 1: `contracts.py` — AgentRunRepository protocol 추가

**파일**: `src/agent_trading/repositories/contracts.py`

```python
class AgentRunRepository(Protocol):
    """Store for AI Agent execution run records."""

    async def add(self, run: AgentRunEntity) -> AgentRunEntity:
        """Persist a new agent run and return it with server defaults."""
        ...

    async def list_by_decision_context(
        self, decision_context_id: UUID
    ) -> Sequence[AgentRunEntity]:
        """Return all runs for a decision context, ordered by started_at DESC."""
        ...

    async def list_all(self, limit: int = 100) -> Sequence[AgentRunEntity]:
        """Return recent runs ordered by started_at DESC."""
        ...
```

**근거**: 기존 `TradeDecisionRepository` 패턴과 동일. `list_all()`에 `limit` 파라미터를 추가하여 API에서 페이징 기본값을 갖도록 함.

---

### Step 2: `memory.py` — InMemoryAgentRunRepository 구현

**파일**: `src/agent_trading/repositories/memory.py`

```python
class InMemoryAgentRunRepository:
    """In-memory implementation of ``AgentRunRepository``."""

    def __init__(self) -> None:
        self._runs: list[AgentRunEntity] = []

    async def add(self, run: AgentRunEntity) -> AgentRunEntity:
        self._runs.append(run)
        return run

    async def list_by_decision_context(
        self, decision_context_id: UUID
    ) -> Sequence[AgentRunEntity]:
        return tuple(
            r for r in self._runs
            if r.decision_context_id == decision_context_id
        )

    async def list_all(self, limit: int = 100) -> Sequence[AgentRunEntity]:
        return tuple(self._runs[-limit:])

    async def clear(self) -> None:
        self._runs.clear()
```

**근거**: 기존 `InMemoryTradeDecisionRepository` 패턴과 동일. `clear()` 메서드는 테스트에서 사용.

---

### Step 3: `postgres/agent_runs.py` — PostgresAgentRunRepository 신규 파일

**파일**: `src/agent_trading/repositories/postgres/agent_runs.py`

```python
from __future__ import annotations

from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import AgentRunEntity


class PostgresAgentRunRepository:
    """PostgreSQL implementation of ``AgentRunRepository``.

    Stores agent execution runs in the ``trading.agent_runs`` table.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, run: AgentRunEntity) -> AgentRunEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.agent_runs
                (agent_run_id, decision_context_id, agent_type,
                 model_id, prompt_id, temperature, seed,
                 raw_output_uri, structured_output_json,
                 status, started_at, completed_at, created_at)
            VALUES ($1, $2, $3,
                    $4, $5, $6, $7,
                    $8, $9::jsonb,
                    $10, $11, $12, $13)
            RETURNING *
            """,
            run.agent_run_id,
            run.decision_context_id,
            run.agent_type,
            run.model_id,
            run.prompt_id,
            run.temperature,
            run.seed,
            run.raw_output_uri,
            _json_dumps(run.structured_output_json),
            run.status,
            run.started_at,
            run.completed_at,
            run.created_at,
        )
        return row_to_entity(row, AgentRunEntity)

    async def list_by_decision_context(
        self, decision_context_id: UUID
    ) -> list[AgentRunEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.agent_runs "
            "WHERE decision_context_id = $1 "
            "ORDER BY started_at DESC",
            decision_context_id,
        )
        return [row_to_entity(r, AgentRunEntity) for r in rows]

    async def list_all(self, limit: int = 100) -> list[AgentRunEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.agent_runs ORDER BY started_at DESC LIMIT $1",
            limit,
        )
        return [row_to_entity(r, AgentRunEntity) for r in rows]
```

**핵심 설계**:
- `structured_output_json` → `$n::jsonb` 캐스팅 (asyncpg JSONB codec 없을 때 대비)
- `RETURNING *` → `row_to_entity()`로 Entity 변환 (DB 기본값 반영)
- `ORDER BY started_at DESC` → 최신 실행이 먼저 오도록
- `LIMIT $1` → `list_all()`에 limit 기본값 100

---

### Step 4: `container.py` — RepositoryContainer에 agent_runs 필드 추가

**파일**: `src/agent_trading/repositories/container.py`

```python
from agent_trading.repositories.contracts import (
    ...
    AgentRunRepository,    # 추가
)

@dataclass(slots=True, frozen=True)
class RepositoryContainer:
    ...
    agent_runs: AgentRunRepository  # 추가
    ...
```

⚠️ **주의**: `frozen=True` dataclass이므로 필드 순서는 알파벳 순서 유지.  
`agent_runs`는 `accounts`와 `audit_logs` 사이에 위치.

---

### Step 5: Bootstrap wiring

**파일 수정 1**: `repositories/bootstrap.py`

```python
from agent_trading.repositories.memory import (
    ...
    InMemoryAgentRunRepository,   # 추가
)

def build_in_memory_repositories() -> RepositoryContainer:
    return RepositoryContainer(
        ...
        agent_runs=InMemoryAgentRunRepository(),  # 추가
        ...
    )
```

**파일 수정 2**: `repositories/postgres/bootstrap.py`

```python
from agent_trading.repositories.postgres.agent_runs import (
    PostgresAgentRunRepository,  # 추가
)

def build_postgres_repositories(tx: TransactionManager) -> RepositoryContainer:
    return RepositoryContainer(
        ...
        agent_runs=PostgresAgentRunRepository(tx),  # 추가
        ...
    )
```

---

### Step 6: `AgentRunRecorder` repository-backed 전환

**파일**: `services/ai_agents/recorder.py`

**변경 사항**:

1. **생성자 변경**: `AgentRunRepository`를 받도록
   - `def __init__(self, repo: AgentRunRepository, max_runs: int = 0) -> None:`
   - `self._repo = repo` 저장
   - 기존 `self._runs: list[AgentRunEntity]`는 유지 (clear()용 + fallback)

2. **`record()` 수정**: 
   - 기존 비즈니스 로직(agent_name 정합성, decision_context_id payload/storage 분리) **전부 유지**
   - `self._runs.append(run)` → `self._repo.add(run)`으로 영속화

3. **`list_by_decision_context()` → async 변환**:
   ```python
   async def list_by_decision_context(
       self, decision_context_id: UUID
   ) -> Sequence[AgentRunEntity]:
       return await self._repo.list_by_decision_context(decision_context_id)
   ```

4. **`list_all()` → async 변환**:
   ```python
   async def list_all(self, limit: int = 100) -> Sequence[AgentRunEntity]:
       return await self._repo.list_all(limit=limit)
   ```

5. **`clear()` 유지**: 테스트 호환성을 위해 유지, repository clear도 호출

**변경 예시**:

```python
from collections.abc import Sequence
from uuid import UUID

from agent_trading.repositories.contracts import AgentRunRepository

class AgentRunRecorder:
    def __init__(
        self,
        repo: AgentRunRepository,
        max_runs: int = 0,
    ) -> None:
        self._repo = repo
        self._max_runs = max_runs
        self._runs: list[AgentRunEntity] = []  # fallback buffer

    async def record(self, ...) -> AgentRunEntity:
        # ... 기존 비즈니스 로직 유지 ...
        run = AgentRunEntity(...)
        
        self._runs.append(run)
        persisted = await self._repo.add(run)  # 영속화
        
        if self._max_runs > 0 and len(self._runs) > self._max_runs:
            self._runs = self._runs[-self._max_runs :]
        
        return persisted

    async def list_by_decision_context(
        self, decision_context_id: UUID
    ) -> Sequence[AgentRunEntity]:
        return await self._repo.list_by_decision_context(decision_context_id)

    async def list_all(self, limit: int = 100) -> Sequence[AgentRunEntity]:
        return await self._repo.list_all(limit=limit)

    def clear(self) -> None:
        self._runs.clear()
```

**후방 호환성**: `_run_agents()`에서 `record()` 호출은 이미 `await` 사용 중이므로 수정 불필요.  
단, `DecisionOrchestratorService.__init__`의 `agent_recorder or AgentRunRecorder()` 기본값이 깨짐 → Step 7에서 처리.

---

### Step 7: Runtime bootstrap wiring

**파일**: `runtime/bootstrap.py`

**`_build_orchestrator()` 변경**:

```python
from agent_trading.services.ai_agents.recorder import AgentRunRecorder

def _build_orchestrator(
    repos: RepositoryContainer,
    settings: AppSettings,
    event_interpretation_agent: EventInterpretationAgent | None = None,
    ai_risk_agent: AIRiskAgent | None = None,
    final_decision_agent: FinalDecisionComposerAgent | None = None,
) -> DecisionOrchestratorService:
    # ... 기존 agent 빌드 로직 ...
    agent_recorder = AgentRunRecorder(repo=repos.agent_runs)
    return DecisionOrchestratorService(
        repos=repos,
        event_interpretation_agent=event_interpretation_agent,
        ai_risk_agent=ai_risk_agent,
        final_decision_agent=final_decision_agent,
        agent_recorder=agent_recorder,
    )
```

이렇게 하면 `build_default_runtime()`과 `build_postgres_runtime()` 모두  
자동으로 repository-backed recorder를 갖게 됨.

---

### Step 8: API Schema — AgentRunResponse 추가

**파일**: `src/agent_trading/api/schemas.py`

```python
class AgentRunResponse(BaseModel):
    """``GET /agent-runs`` — AI agent execution run record."""

    agent_run_id: str
    decision_context_id: str
    agent_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    model_id: str | None = None
    prompt_id: str | None = None
    temperature: float | None = None
    seed: int | None = None
    raw_output_uri: str | None = None
    structured_output_json: dict[str, object] | None = None
    created_at: datetime | None = None
```

**설계**: `TradeDecisionDetail` 패턴과 동일. UUID→str 변환은 Pydantic v2 자동 처리.  
`Decimal`인 `temperature`는 `float | None`으로 노출.

---

### Step 9: API Route — GET /agent-runs

**파일**: `src/agent_trading/api/routes/agent_runs.py` (신규)

```python
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import AgentRunResponse
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["agent-runs"])


@router.get("/agent-runs", response_model=list[AgentRunResponse])
async def list_agent_runs(
    decision_context_id: str | None = Query(
        None, description="Optional decision context ID filter"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Max results"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[AgentRunResponse]:
    """List AI agent execution runs, optionally filtered by decision context."""
    if decision_context_id is not None:
        try:
            ctx_id = UUID(decision_context_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid UUID: {decision_context_id}"
            ) from exc
        runs = await repos.agent_runs.list_by_decision_context(ctx_id)
    else:
        runs = await repos.agent_runs.list_all(limit=limit)

    return [
        AgentRunResponse(
            agent_run_id=str(r.agent_run_id),
            decision_context_id=str(r.decision_context_id),
            agent_type=r.agent_type,
            status=r.status,
            started_at=r.started_at,
            completed_at=r.completed_at,
            model_id=str(r.model_id) if r.model_id else None,
            prompt_id=str(r.prompt_id) if r.prompt_id else None,
            temperature=float(r.temperature) if r.temperature else None,
            seed=r.seed,
            raw_output_uri=r.raw_output_uri,
            structured_output_json=r.structured_output_json,
            created_at=r.created_at,
        )
        for r in runs
    ]
```

**설계**: `trade_decisions.py` 패턴과 동일.  
`?decision_context_id=` 필터 → 단일 context의 모든 run 조회.  
`?limit=` 파라미터로 최대 결과 제한 (기본 100).

---

### Step 10: `app.py` — agent_runs_router 등록

**파일**: `src/agent_trading/api/app.py`

```python
# Phase 1 routers
from agent_trading.api.routes.agent_runs import router as agent_runs_router  # 추가

protected_routers = [
    ...
    agent_runs_router,  # 추가
]
```

---

### Step 11: 테스트

#### 11.1 Postgres Repository Test

**파일**: `tests/repositories/test_postgres_agent_runs.py` (신규)

`test_postgres_trade_decisions.py` 패턴 참조:
- `seeded_agent_run` fixture (decision_context_id 참조)
- `test_add_agent_run` — full entity INSERT 및 RETURNING 검증
- `test_list_by_decision_context` — context별 조회
- `test_list_all` — 전체 조회 + limit
- `test_list_by_decision_context_empty` — 존재하지 않는 context → 빈 리스트

#### 11.2 API Inspection Test

**파일**: `tests/api/test_inspection.py`에 `TestAgentRuns` 클래스 추가

`TestOrders` 패턴 참조:
- `test_list_agent_runs_empty` — empty_client → 200 + []
- `test_list_agent_runs` — client → seeded runs 반환
- `test_list_agent_runs_by_decision_context` — `?decision_context_id=` 필터
- `test_list_agent_runs_invalid_uuid` → 400

#### 11.3 API conftest 수정

**파일**: `tests/api/conftest.py`
- `agent_run_id` fixture 추가
- `seeded_repos`에 `AgentRunEntity` 시드 추가 (decision_context_id 참조)

---

### Step 12: 최종 검증

1. **`pytest tests/`** 실행 — 기존 테스트가 깨지지 않는지 확인
2. **`pytest tests/repositories/test_postgres_agent_runs.py`** — 신규 Postgres repository 테스트
3. **`pytest tests/api/test_inspection.py::TestAgentRuns`** — API inspection 테스트
4. **수동 검증**: `GET /agent-runs` 호출하여 JSON 응답 구조 확인

## 변경 파일 요약

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| `repositories/contracts.py` | 수정 | `AgentRunRepository` protocol 추가 |
| `repositories/memory.py` | 수정 | `InMemoryAgentRunRepository` 클래스 추가 |
| `repositories/postgres/agent_runs.py` | **신규** | `PostgresAgentRunRepository` |
| `repositories/container.py` | 수정 | `agent_runs: AgentRunRepository` 필드 추가 |
| `repositories/bootstrap.py` | 수정 | `InMemoryAgentRunRepository()` wiring |
| `repositories/postgres/bootstrap.py` | 수정 | `PostgresAgentRunRepository(tx)` wiring |
| `services/ai_agents/recorder.py` | 수정 | repository-backed, query async화 |
| `runtime/bootstrap.py` | 수정 | `AgentRunRecorder(repo=repos.agent_runs)` 주입 |
| `api/schemas.py` | 수정 | `AgentRunResponse` Pydantic 모델 추가 |
| `api/routes/agent_runs.py` | **신규** | `GET /agent-runs` endpoint |
| `api/app.py` | 수정 | agent_runs_router 등록 |
| `tests/repositories/test_postgres_agent_runs.py` | **신규** | Postgres repository test |
| `tests/api/conftest.py` | 수정 | `AgentRunEntity` 시드 추가 |
| `tests/api/test_inspection.py` | 수정 | `TestAgentRuns` 클래스 추가 |

## 제외된 변경

- **`decision_orchestrator.py`의 `_run_agents()`** — 내부 `record()` 호출은 이미 async이며, 수정 불필요
- **`DecisionOrchestratorService.__init__`** — `agent_recorder` DI signature는 유지, 기본값만 삭제
- **기존 `AgentRunRecorder`의 `record()` 비즈니스 로직** — agent_name 정합성 체크, decision_context_id payload/storage 분리 → 그대로 유지
