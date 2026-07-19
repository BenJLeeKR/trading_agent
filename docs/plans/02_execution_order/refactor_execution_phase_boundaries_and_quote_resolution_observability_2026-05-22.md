# 설계 문서: 주문 실행 리팩토링 2단계 — 실행 계획

> **일자**: 2026-05-22  
> **상태**: 설계 초안  
> **대상 브랜치**: `main`

---

## 1. 현재 `trade_decision only` 대표 경로 분류 (Q1 결과 요약)

`assemble_and_submit()`의 symbol loop에서 실제 broker submit까지 도달하지 못하고 중단되는 4개 경로.

```
symbol loop 시작
  │
  ├─ Phase 1.5 (sizing): effective_qty <= 0 → SKIPPED
  │   └─ PHASE_TRACE: sizing_skip → SubmitResult{status: "SKIPPED", error_phase: "sizing"}
  │
  ├─ Phase 1.5+ (sell_guard): guard blocked → SKIPPED
  │   └─ PHASE_TRACE: sell_guard_done (guard=block) → SubmitResult{status: "SKIPPED", error_phase: "sell_guard"}
  │
  ├─ Phase 2 (translation): HOLD/WATCH decision → SKIPPED
  │   └─ PHASE_TRACE: validate_skip_hold/watch → SubmitResult{status: "SKIPPED", error_phase: "translation"}
  │
  └─ Phase 3 (order_create): create_order() 실패 → ERROR
      └─ PHASE_TRACE: order_create_error → SubmitResult{status: "ERROR", error_phase: "order_create"}
```

**현재 문제점**:
- 각 경로의 중단 이유가 `SubmitResult.error_phase`에만 문자열로 저장됨
- `trade_decisions` 테이블에는 중단 이유가 전혀 기록되지 않아, 사후 분석이 어려움
- `PhaseTraceEntry` 구조체가 없어 phase trace가 로그에만 남고, 구조화된 데이터로 수집 불가

---

## 2. `quote_resolution` 구조 문제 (Q2 결과 요약)

### 현재 동작

```python
# decision_orchestrator.py ~L1030
quote = await self._broker_adapter.get_quote(symbol)
# 10초 timeout 존재, fallback: quote = {}
```

### 식별된 문제

| 문제 | 설명 | 영향 |
|------|------|------|
| **회로 차단기 없음** | 연속 quote 실패 시에도 계속 호출 | broker API rate limit 소진, 지연 증폭 |
| **캐싱 없음** | 동일 symbol을 같은 cycle 내 여러 번 호출 가능 | 중복 네트워크 비용 |
| **HP_SELL_QUOTE_BYPASS** | held_position sell에서 quote 호출 자체 회피 (이미 존재) | 변경 불필요 |

### quote_resolution blocking risk 완화 방안

```
호출 흐름:
  1. _quote_cache hit (TTL 5초) → 캐시된 quote 반환
  2. circuit breaker: _quote_skip_until[symbol] > now → quote = {} (fallback)
  3. 실제 get_quote() 호출
     - 성공 → _quote_cache 업데이트, _quote_failures[symbol] = 0
     - 실패 → _quote_failures[symbol] += 1
     - 3회 연속 실패 → _quote_skip_until[symbol] = now + 60s
```

---

## 3. 적용할 변경 사항 상세

### 3.1 EXE-001: Symbol-level Phase Trace 강화

#### 변경 대상 1: `PhaseTraceEntry` + `SubmitResult` 확장

**파일**: [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py)

```python
@dataclass(slots=True, frozen=True)
class PhaseTraceEntry:
    """단일 phase 실행 추적 엔트리.

    ``assemble_and_submit()``의 각 phase 진입/종료 시 생성되어
    ``SubmitResult.phase_trace``에 누적된다.
    """
    phase: str
    """phase 식별자 (예: \"sizing\", \"sell_guard\")."""
    elapsed_ms: int
    """phase 시작부터 현재까지의 경과 시간 (ms)."""
    status: str
    """\"start\" | \"ok\" | \"skipped\" | \"error\""""
```

**`SubmitResult` 확장**:

```python
@dataclass(slots=True, frozen=True)
class SubmitResult:
    status: str
    intent: OrderIntent | None = None
    order: OrderRequestEntity | None = None
    error_phase: str | None = None
    error_message: str | None = None
    trade_decision_id: UUID | None = None
    decision_context_id: UUID | None = None
    # ── 신규: EXE-001 ────────────────────────────────────────────
    phase_trace: tuple[PhaseTraceEntry, ...] = ()
```

#### 구현 상세

1. `assemble_and_submit()` 내부에 `_phase_trace: list[PhaseTraceEntry]` 리스트 추가
2. `_phase_start = time_module.monotonic()` 클래스 변수로 시작 시간 기록 (메서드 시작 지점)
3. 각 PHASE_TRACE 지점에서 `PhaseTraceEntry` 추가 및 `_phase_trace` 누적
4. symbol loop 종료 시 `SubmitResult(phase_trace=tuple(_phase_trace))` 전달

**현재 PHASE_TRACE 21개 지점 매핑**:

| # | 라인 (추정) | 현재 로그 | PhaseTraceEntry |
|---|-------------|-----------|-----------------|
| 1 | ~947 | assemble_start | phase="assemble_start", status="start" |
| 2 | ~971 | quote_resolution/{symbol} | phase="quote_resolution", status="start" |
| 3 | ~983 | quote_resolution done | phase="quote_resolution", status="ok" |
| 4 | ~989 | quote_fallback | phase="quote_resolution", status="error" |
| 5 | ~1072 | sizing/{symbol} | phase="sizing", status="start" |
| 6 | ~1116 | sizing done | phase="sizing", status="ok" |
| 7 | ~1127 | sizing skip | phase="sizing", status="skipped" |
| 8 | ~1195 | sell_guard/{symbol} | phase="sell_guard", status="start" |
| 9 | ~1203 | sell_guard skip | phase="sell_guard", status="skipped" |
| 10 | ~1274 | translation skip | phase="translation", status="skipped" |
| 11 | ~1286 | translation done | phase="translation", status="ok" |
| 12 | ~1309 | order_create error | phase="order_create", status="error" |
| 13 | ~1336 | transition→VALIDATED | phase="transition_validated", status="ok" |
| 14 | ~1364 | transition→PENDING_SUBMIT | phase="transition_pending_submit", status="ok" |
| 15 | ~1471 | stale_snapshot_guard | phase="stale_snapshot_guard", status="start" |
| 16 | ~1546 | stale_snapshot_guard skip | phase="stale_snapshot_guard", status="skipped" |
| 17 | ~1556 | broker_submit | phase="broker_submit", status="start" |
| 18 | ~1571 | broker_submit ok | phase="broker_submit", status="ok" |
| 19 | ~1589 | broker_submit reject | phase="broker_submit", status="error" |
| 20 | ~1628 | broker_submit reconcile | phase="broker_submit", status="reconcile" |
| 21 | ~마지막 | assemble_and_submit done | phase="assemble_done", status="ok" |

#### 변경 대상 2: [`scripts/run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) 직렬화

`_serialize_cycle_result()`에 `phase_trace` 직렬화 로직 추가:

```python
if result.phase_trace:
    data["phase_trace"] = [
        {
            "phase": pt.phase,
            "elapsed_ms": pt.elapsed_ms,
            "status": pt.status,
        }
        for pt in result.phase_trace
    ]
```

---

### 3.2 EXE-002: quote_resolution Blocking Risk 완화

**변경 대상**: [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py)

#### 회로 차단기 (Circuit Breaker)

```python
class DecisionOrchestratorService:
    # ── EXE-002: quote circuit breaker ────────────────────────────
    _quote_failures: ClassVar[dict[str, int]] = {}
    """symbol → 연속 quote 실패 횟수."""
    _quote_skip_until: ClassVar[dict[str, datetime]] = {}
    """symbol → quote 스킵 deadline (KST)."""
    _quote_cache: ClassVar[dict[str, tuple[dict, datetime]]] = {}
    """symbol → (quote_result, cached_at). TTL 5초."""
    _QUOTE_CACHE_TTL_SECONDS: ClassVar[int] = 5
    _QUOTE_CB_THRESHOLD: ClassVar[int] = 3
    _QUOTE_CB_COOLDOWN_SECONDS: ClassVar[int] = 60
```

#### quote resolution 로직 수정

현재 ~L1030의 `get_quote()` 호출 전후에 circuit breaker + cache 로직 추가:

```python
async def _resolve_quote(self, symbol: str, intent: OrderIntent) -> dict:
    """EXE-002: circuit breaker + cache가 적용된 quote resolution."""
    now = datetime.now(timezone.utc)

    # 1. Cache hit check
    if symbol in self._quote_cache:
        cached_quote, cached_at = self._quote_cache[symbol]
        if (datetime.now(timezone.utc) - cached_at).total_seconds() < self._QUOTE_CACHE_TTL_SECONDS:
            return cached_quote

    # 2. Circuit breaker check
    skip_until = self._quote_skip_until.get(symbol)
    if skip_until and now < skip_until:
        logger.warning("Quote CB active for %s, skip until %s", symbol, skip_until)
        return {}

    # 3. Actual quote call
    try:
        quote = await self._broker_adapter.get_quote(symbol)
        # Cache on success
        self._quote_cache[symbol] = (quote, datetime.now(timezone.utc))
        self._quote_failures[symbol] = 0
        return quote
    except Exception:
        self._quote_failures[symbol] = self._quote_failures.get(symbol, 0) + 1
        if self._quote_failures[symbol] >= self._QUOTE_CB_THRESHOLD:
            skip_deadline = datetime.now(timezone.utc) + timedelta(seconds=self._QUOTE_CB_COOLDOWN_SECONDS)
            self._quote_skip_until[symbol] = skip_deadline
            logger.error(
                "Quote CB TRIPPED for symbol=%s after %d consecutive failures, "
                "skip until %s",
                symbol, self._quote_failures[symbol], skip_deadline,
            )
        return {}
```

**참고**: HP_SELL_QUOTE_BYPASS 패턴은 이미 존재하므로 별도 변경 불필요.

---

### 3.3 EXE-005A: `trade_decision only` reason 명시화

#### 3.3.1 DB 마이그레이션

**파일**: [`db/migrations/0021_add_pipeline_stop_fields.sql`](db/migrations/0021_add_pipeline_stop_fields.sql)

```sql
-- Migration 0021: Add pipeline_stop fields to trade_decisions
--
-- Purpose
-- -------
-- ``assemble_and_submit()`` 내에서 symbol별 pipeline이 중단된 위치와
-- 이유를 기록하여, 사후 분석과 모니터링을 가능하게 한다.
-- 모든 컬럼은 NULLABLE로 추가되어 기존 레코드와 하위 호환성을 유지한다.
--
-- See Also
-- --------
-- EXE-005A: src/agent_trading/services/decision_orchestrator.py

BEGIN;

ALTER TABLE trading.trade_decisions
    ADD COLUMN pipeline_stop_phase VARCHAR(64),
    ADD COLUMN pipeline_stop_reason TEXT,
    ADD COLUMN pipeline_stopped_at TIMESTAMPTZ;

COMMENT ON COLUMN trading.trade_decisions.pipeline_stop_phase IS
    '파이프라인이 중단된 phase (PipelinePhase enum 값). NULL이면 broker submit까지 완료.';
COMMENT ON COLUMN trading.trade_decisions.pipeline_stop_reason IS
    '파이프라인 중단 사유 (PipelineStopReason enum 값).';
COMMENT ON COLUMN trading.trade_decisions.pipeline_stopped_at IS
    '파이프라인이 중단된 시각 (KST).';

COMMIT;
```

#### 3.3.2 Enum 정의

**파일**: [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) (또는 별도 enum 파일)

```python
class PipelinePhase(str, Enum):
    """assemble_and_submit() symbol pipeline의 phase 식별자.
    
    값은 문자열 리터럴과의 하위 호환성을 위해 str을 상속한다.
    """
    AI_ASSEMBLE = "ai_assemble"
    QUOTE_RESOLUTION = "quote_resolution"
    SIZING = "sizing"
    SELL_GUARD = "sell_guard"
    TRANSLATION = "translation"
    ORDER_CREATE = "order_create"
    TRANSITION_VALIDATED = "transition_validated"
    TRANSITION_PENDING_SUBMIT = "transition_pending_submit"
    STALE_SNAPSHOT_GUARD = "stale_snapshot_guard"
    BROKER_SUBMIT = "broker_submit"
    POST_SUBMIT_SYNC = "post_submit_sync"


class PipelineStopReason(str, Enum):
    """symbol pipeline 중단 사유.
    
    값은 문자열 리터럴과의 하위 호환성을 위해 str을 상속한다.
    """
    SIZING_REJECTED = "sizing_rejected"
    SELL_GUARD_BLOCKED = "sell_guard_blocked"
    DECISION_HOLD = "decision_hold"
    DECISION_WATCH = "decision_watch"
    ORDER_CREATE_FAILED = "order_create_failed"
    TRANSITION_FAILED = "transition_failed"
    STALE_SNAPSHOT = "stale_snapshot"
    BROKER_SUBMIT_FAILED = "broker_submit_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMEOUT = "timeout"
```

#### 3.3.3 TradeDecisionEntity 확장

**파일**: [`src/agent_trading/domain/entities.py`](src/agent_trading/domain/entities.py)

```python
@dataclass(slots=True, frozen=True)
class TradeDecisionEntity:
    # ... 기존 필드 (변경 없음) ...

    # -- EXE-005A: Pipeline stop fields --
    pipeline_stop_phase: str | None = None
    """파이프라인이 중단된 phase (PipelinePhase enum 값). None이면 broker submit까지 완료."""
    pipeline_stop_reason: str | None = None
    """파이프라인 중단 사유 (PipelineStopReason enum 값)."""
    pipeline_stopped_at: datetime | None = None
    """파이프라인이 중단된 시각 (KST)."""
```

> **참고**: `TradeDecisionEntity`가 `slots=True, frozen=True`이므로, 기존 인스턴스 생성 코드는 변경 없이도 새로운 필드가 `None` 기본값으로 설정된다.

#### 3.3.4 TradeDecisionRepository 확장

**파일**: [`src/agent_trading/repositories/contracts.py`](src/agent_trading/repositories/contracts.py)

```python
class TradeDecisionRepository(Protocol):
    # ... 기존 메서드 (변경 없음) ...

    async def update_pipeline_stop(
        self,
        trade_decision_id: UUID,
        *,
        pipeline_stop_phase: str,
        pipeline_stop_reason: str,
        pipeline_stopped_at: datetime,
    ) -> None:
        """EXE-005A: trade_decision의 pipeline stop 필드를 업데이트.

        ``assemble_and_submit()``의 각 return 지점에서 호출되어,
        broker submit까지 완료되지 못한 symbol의 중단 위치와 사유를 기록한다.
        """
        ...
```

**파일**: [`src/agent_trading/repositories/postgres/trade_decisions.py`](src/agent_trading/repositories/postgres/trade_decisions.py)

```python
async def update_pipeline_stop(
    self,
    trade_decision_id: UUID,
    *,
    pipeline_stop_phase: str,
    pipeline_stop_reason: str,
    pipeline_stopped_at: datetime,
) -> None:
    await self._tx.connection.execute(
        """
        UPDATE trading.trade_decisions
        SET pipeline_stop_phase = $2,
            pipeline_stop_reason = $3,
            pipeline_stopped_at = $4
        WHERE trade_decision_id = $1
        """,
        trade_decision_id,
        pipeline_stop_phase,
        pipeline_stop_reason,
        pipeline_stopped_at,
    )
```

**파일**: [`src/agent_trading/repositories/memory.py`](src/agent_trading/repositories/memory.py)

```python
async def update_pipeline_stop(
    self,
    trade_decision_id: UUID,
    *,
    pipeline_stop_phase: str,
    pipeline_stop_reason: str,
    pipeline_stopped_at: datetime,
) -> None:
    entity = self._items.get(trade_decision_id)
    if entity is None:
        return
    # TradeDecisionEntity는 frozen이므로 replace로 새 인스턴스 생성
    from dataclasses import replace
    self._items[trade_decision_id] = replace(
        entity,
        pipeline_stop_phase=pipeline_stop_phase,
        pipeline_stop_reason=pipeline_stop_reason,
        pipeline_stopped_at=pipeline_stopped_at,
    )
```

**참고**: `update_pipeline_stop()`은 `TradeDecisionRepository` Protocol에 추가되므로, `bootstrap.py`에서 레지스트리 갱신이 필요할 수 있음. 프로토콜 기반이므로 정적 검사만 통과하면 작동.

#### 3.3.5 `assemble_and_submit()` return 지점에 pipeline_stop 업데이트

| return 위치 | 조건 | pipeline_stop_phase | pipeline_stop_reason |
|-------------|------|---------------------|----------------------|
| Phase 1.5 sizing skip | `effective_qty <= 0` | `"sizing"` | `"sizing_rejected"` |
| Phase 1.5+ sell_guard skip | sell guard blocked | `"sell_guard"` | `"sell_guard_blocked"` |
| Phase 2 translation HOLD | decision_type == HOLD | `"translation"` | `"decision_hold"` |
| Phase 2 translation WATCH | decision_type == WATCH | `"translation"` | `"decision_watch"` |
| Phase 3 order_create error | create_order() 실패 | `"order_create"` | `"order_create_failed"` |

각 지점에서 `SubmitResult` 생성 전에 `update_pipeline_stop()` 호출:

```python
# 예시: Phase 1.5 sizing skip
if trade_decision_id is not None:
    await self._repos.trade_decisions.update_pipeline_stop(
        trade_decision_id,
        pipeline_stop_phase=PipelinePhase.SIZING.value,
        pipeline_stop_reason=PipelineStopReason.SIZING_REJECTED.value,
        pipeline_stopped_at=datetime.now(timezone.utc),
    )
return SubmitResult(
    status="SKIPPED",
    error_phase="sizing",
    trade_decision_id=trade_decision_id,
    decision_context_id=intent.decision_context_id,
    phase_trace=tuple(_phase_trace),
)
```

---

## 4. 변경 영향 범위 (파일별 변경 사항)

### 변경 파일 요약

| # | 파일 | 변경 유형 | 설명 |
|---|------|-----------|------|
| 1 | [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | 수정 | `PhaseTraceEntry` dataclass 추가, `SubmitResult.phase_trace` 필드 추가, `PipelinePhase`/`PipelineStopReason` enum 추가, `_quote_circuit_breaker`/`_quote_cache` 로직 추가, 각 return 지점 `update_pipeline_stop()` 호출 |
| 2 | [`src/agent_trading/domain/entities.py`](src/agent_trading/domain/entities.py) | 수정 | `TradeDecisionEntity`에 `pipeline_stop_phase`, `pipeline_stop_reason`, `pipeline_stopped_at` 필드 추가 |
| 3 | [`src/agent_trading/repositories/contracts.py`](src/agent_trading/repositories/contracts.py) | 수정 | `TradeDecisionRepository` Protocol에 `update_pipeline_stop()` 메서드 추가 |
| 4 | [`src/agent_trading/repositories/postgres/trade_decisions.py`](src/agent_trading/repositories/postgres/trade_decisions.py) | 수정 | `update_pipeline_stop()` 구현 추가 |
| 5 | [`src/agent_trading/repositories/memory.py`](src/agent_trading/repositories/memory.py) | 수정 | `InMemoryTradeDecisionRepository.update_pipeline_stop()` 구현 추가 |
| 6 | [`scripts/run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) | 수정 | `_serialize_cycle_result()`에 `phase_trace` 직렬화 추가 |
| 7 | [`db/migrations/0021_add_pipeline_stop_fields.sql`](db/migrations/0021_add_pipeline_stop_fields.sql) | 신규 | `trade_decisions` 테이블에 pipeline_stop 컬럼 3개 추가 |

### 변경 영향 없는 항목

- `.env` — 수정 금지 (제약 조건)
- `src/agent_trading/repositories/bootstrap.py` — Protocol 기반이므로 변경 불필요 (단, `update_pipeline_stop` 메서드가 `bootstrap.py`의 레지스트리 확인을 통과해야 함)
- `src/agent_trading/repositories/container.py` — 변경 불필요
- `src/agent_trading/repositories/postgres_uow.py` — 변경 불필요
- `src/agent_trading/db/row_mapper.py` — `TradeDecisionEntity`에 새 필드가 추가되지만, `row_to_entity()`는 dataclass 필드 이름과 SQL 컬럼명을 자동 매핑하므로 변경 불필요 (단, SQL 컬럼명과 dataclass 필드명이 일치해야 함)

---

## 5. 테스트 계획

### 5.1 단위 테스트

| 테스트 | 대상 | 설명 |
|--------|------|------|
| `test_phase_trace_entry_creation` | `PhaseTraceEntry` | dataclass 생성 및 필드 검증 |
| `test_submit_result_phase_trace` | `SubmitResult` | `phase_trace` 필드 기본값 및 커스텀값 검증 |
| `test_pipeline_stop_fields_on_entity` | `TradeDecisionEntity` | 새 pipeline_stop 필드 기본값 None 검증 |
| `test_quote_cache_hit` | `_resolve_quote` | TTL 내 동일 symbol 재호출 시 캐시 반환 |
| `test_quote_circuit_breaker_trip` | `_resolve_quote` | 3회 연속 실패 후 60초 스킵 |
| `test_quote_circuit_breaker_recovery` | `_resolve_quote` | cooldown 후 정상 호출 재개 |
| `test_update_pipeline_stop_memory` | `InMemoryTradeDecisionRepository` | `update_pipeline_stop()` 호출 후 entity 업데이트 확인 |
| `test_serialize_phase_trace` | `_serialize_cycle_result` | phase_trace 직렬화 포맷 검증 |

### 5.2 통합 테스트

| 테스트 | 설명 |
|--------|------|
| `test_assemble_and_submit_phase_trace` | 실제 `assemble_and_submit()` 호출 후 `SubmitResult.phase_trace`에 최소 2개 이상의 entry 존재 확인 |
| `test_assemble_and_submit_pipeline_stop_sizing` | sizing skip 시 `update_pipeline_stop()` 호출 및 DB 기록 확인 |
| `test_assemble_and_submit_pipeline_stop_translation` | HOLD 결정 시 pipeline_stop 기록 확인 |
| `test_quote_resolution_with_cb` | quote 연속 실패 상황에서 circuit breaker 동작 확인 |

### 5.3 회귀 테스트

- 기존 테스트 모두 통과 확인 (`pytest tests/ -v`)
- `TradeDecisionEntity` 생성 코드 변경 없음 (기본값 None) → 하위 호환성 보장
- `SubmitResult` 생성 코드 변경: `phase_trace` 누적 로직 추가만, 기존 필드 변경 없음

---

## 6. 적용 순서 (점진적 적용)

```
Step 1: EXE-001 — PhaseTraceEntry + SubmitResult 확장
  ├── PhaseTraceEntry dataclass 추가
  ├── SubmitResult.phase_trace 필드 추가
  ├── assemble_and_submit() 내 _phase_trace 누적 로직
  ├── run_paper_decision_loop.py 직렬화
  └── 단위 테스트

Step 2: EXE-002 — quote circuit breaker + cache
  ├── _quote_failures / _quote_skip_until / _quote_cache 추가
  ├── _resolve_quote() 메서드 추출
  ├── 기존 get_quote() 호출을 _resolve_quote()로 대체
  └── 단위 테스트

Step 3: EXE-005A — DB migration + enum + entity 확장
  ├── db/migrations/0021_...sql 생성
  ├── PipelinePhase / PipelineStopReason enum 추가
  ├── TradeDecisionEntity pipeline_stop 필드 추가
  ├── TradeDecisionRepository.update_pipeline_stop() 추가
  ├── Postgres / Memory 구현
  ├── assemble_and_submit() 각 return 지점에 update_pipeline_stop() 호출
  └── 단위 + 통합 테스트
```

---

## 7. Mermaid: 변경된 데이터 흐름

```mermaid
flowchart TD
    subgraph assemble_and_submit
        A[assemble_and_submit start] --> B[PhaseTraceEntry: start]
        B --> C[symbol loop]
        C --> D{effective_qty <= 0?}
        D -->|Yes| E[PhaseTraceEntry: sizing skipped]
        E --> F[update_pipeline_stop: sizing_rejected]
        F --> G[SubmitResult: SKIPPED]
        D -->|No| H{sell_guard blocked?}
        H -->|Yes| I[PhaseTraceEntry: sell_guard skipped]
        I --> J[update_pipeline_stop: sell_guard_blocked]
        J --> G
        H -->|No| K{decision HOLD/WATCH?}
        K -->|Yes| L[PhaseTraceEntry: translation skipped]
        L --> M[update_pipeline_stop: decision_hold/watch]
        M --> G
        K -->|No| N{create_order ok?}
        N -->|No| O[PhaseTraceEntry: order_create error]
        O --> P[update_pipeline_stop: order_create_failed]
        P --> Q[SubmitResult: ERROR]
        N -->|Yes| R[broker submit flow]
        R --> S[PhaseTraceEntry: submit ok/error]
        S --> T[SubmitResult: SUBMITTED/REJECTED]
    end

    subgraph quote_resolution
        U[get_quote call] --> V{_quote_cache hit?}
        V -->|Yes| W[return cached quote]
        V -->|No| X{circuit breaker active?}
        X -->|Yes| Y[return {} fallback]
        X -->|No| Z[actual get_quote]
        Z -->|Success| AA[update cache, reset failures]
        Z -->|Failure| AB[increment failures]
        AB --> AC{failures >= 3?}
        AC -->|Yes| AD[set skip_until=now+60s]
        AC -->|No| AE[return {} fallback]
    end

    subgraph trade_decisions table
        TD[(trade_decisions)]
        TD --> AF[pipeline_stop_phase]
        TD --> AG[pipeline_stop_reason]
        TD --> AH[pipeline_stopped_at]
    end

    F --> TD
    J --> TD
    M --> TD
    P --> TD
```

---

## 8. 다음 리팩토링 단계 제안 (EXE-005B: execution_attempt)

### 배경
현재 `execution_attempt`는 구현되지 않았으며, Q5 분석 결과 이번 단계에서는 observability enhancement에 집중하기로 결정.

### 제안: EXE-005B execution_attempt

```python
@dataclass(slots=True, frozen=True)
class ExecutionAttempt:
    execution_attempt_id: UUID
    trade_decision_id: UUID
    cycle: int
    attempt_number: int
    started_at: datetime
    completed_at: datetime | None
    result_status: str  # SUBMITTED | SKIPPED | FAILED | ERROR
    pipeline_stop_phase: str | None
    pipeline_stop_reason: str | None
    phase_trace_json: dict | None
```

**도입 시기**: EXE-001/002/005A 안정화 후 다음 리팩토링 단계에서 진행.

---

## 9. 리스크 및 고려사항

| 리스크 | 완화 방안 |
|--------|-----------|
| `TradeDecisionEntity`가 `frozen=True`이므로 `update_pipeline_stop()`에서 `replace()` 필요 | In-memory 구현에서 `dataclasses.replace()` 사용; Postgres는 직접 UPDATE |
| `ClassVar` dict는 프로세스 메모리에 존재 → 프로세스 재시작 시 소멸 | Quote CB/Cache는 일시적 성능 최적화 도구이므로, 재시작 시 초기화되어도 무방 |
| `update_pipeline_stop()`이 Protocol에 추가되면 모든 구현체가 구현해야 함 | Memory + Postgres 두 구현체만 존재; 둘 다 구현 완료 |
| `pipeline_stop_*` 컬럼이 NULLABLE이므로 기존 쿼리 호환 | 새로운 필드는 기본값 None, 모든 기존 SELECT는 그대로 작동 |
| HP_SELL_QUOTE_BYPASS와 quote CB 간 충돌 | HP_SELL_QUOTE_BYPASS는 quote 호출 자체를 회피하므로 CB에 도달하지 않음; 충돌 없음 |
| `row_to_entity()`가 새 컬럼을 자동 매핑하지 못할 가능성 | SQL 컬럼명과 dataclass 필드명이 일치해야 함 (`pipeline_stop_phase` → `pipeline_stop_phase`) |
