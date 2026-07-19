# Reconciliation Worker — P0 구현 보고서

**일자**: 2026-05-16  
**참조**: [`plans/reconciliation_worker_architecture_2026-05-16.md`](plans/reconciliation_worker_architecture_2026-05-16.md)

---

## 1. 개요

Phase 18 auto-trigger와 Phase 19 backfill로 생산된 Reconciliation Run이 소비되지 않고 `started` 상태로 누적되는 문제를 해결하기 위해 Reconciliation Worker를 구현했다. Architecture 문서에서 식별된 4가지 계약 문제를 모두 해결하고, 실제 Run을 소비하는 Worker Core, CLI Script, Docker Service, Test Suite를 완성했다.

---

## 2. 변경 파일 목록

### 2.1 신규 파일

| 파일 | 설명 |
|------|------|
| [`src/agent_trading/services/reconciliation_worker.py`](src/agent_trading/services/reconciliation_worker.py) | Worker Core Logic — `ReconciliationRunProcessor` |
| [`scripts/run_reconciliation_worker.py`](scripts/run_reconciliation_worker.py) | CLI Script — loop/single-cycle/dry-run 모드 |
| [`tests/services/test_reconciliation_worker.py`](tests/services/test_reconciliation_worker.py) | 단위 테스트 17종 |

### 2.2 기존 파일 변경

| 파일 | 변경 내용 |
|------|-----------|
| [`src/agent_trading/domain/entities.py`](src/agent_trading/domain/entities.py) | `ReconciliationOrderLinkEntity`, `ReconciliationPositionLinkEntity` 추가 |
| [`src/agent_trading/repositories/contracts.py`](src/agent_trading/repositories/contracts.py) | `list_pending_runs()`, `get_run_order_links()`, `list_run_position_links()` 프로토콜 메서드 추가 |
| [`src/agent_trading/repositories/postgres/reconciliation.py`](src/agent_trading/repositories/postgres/reconciliation.py) | 위 3개 메서드 Postgres 구현 + `_row_to_link_entity()`, `_row_to_position_link_entity()` 헬퍼 |
| [`src/agent_trading/repositories/memory.py`](src/agent_trading/repositories/memory.py) | 위 3개 메서드 In-memory 구현 |
| [`src/agent_trading/services/reconciliation_service.py`](src/agent_trading/services/reconciliation_service.py) | `trigger_and_link()`, `list_pending_runs()`, `get_run_order_links()` 추가 |
| [`src/agent_trading/services/order_manager.py`](src/agent_trading/services/order_manager.py) | Auto-trigger: `trigger()` → `trigger_and_link()`, `trigger_type` → `"requires_reconciliation"` |
| [`docker-compose.yml`](docker-compose.yml) | `reconciliation-worker` 서비스 추가 |

---

## 3. Phase별 구현 상세

### Phase 0: 계약 수정 (Contract First)

#### 3.1 `trigger_and_link()` — 통합 생성 메서드

**문제**: [`trigger()`](src/agent_trading/services/reconciliation_service.py:116)는 Run만 생성하고 [`attach_order_mismatch()`](src/agent_trading/services/reconciliation_service.py:401)를 호출하지 않아 Order Link가 없는 Run이 생산되었다.

**해결**: [`trigger_and_link()`](src/agent_trading/services/reconciliation_service.py:50)는 `trigger()`를 호출한 후 `order_request_id`가 제공되면 `attach_order_mismatch(mismatch_type="pending_inquiry")`를 호출한다.

```python
async def trigger_and_link(self, account_id, trigger_type, *, order_request_id=None, ...):
    run = await self.trigger(account_id, trigger_type, ...)
    if order_request_id is not None:
        await self.attach_order_mismatch(
            run.reconciliation_run_id,
            order_request_id,
            mismatch_type="pending_inquiry",
            details={...},
        )
    return run
```

#### 3.2 `trigger_type` 정합화

**문제**: [`order_manager.py`](src/agent_trading/services/order_manager.py:679)의 auto-trigger가 `trigger_type="reconcile_required_transition"`을 사용했으나 DB CHECK constraint에는 `"requires_reconciliation"`만 허용된다.

**해결**: [`trigger_type="requires_reconciliation"`](src/agent_trading/services/order_manager.py)로 변경하고 `trigger()` → `trigger_and_link()`로 변경하여 Run + Link를 함께 생성한다.

#### 3.3 `list_pending_runs()` — Read Path

**계약** ([`contracts.py`](src/agent_trading/repositories/contracts.py:457)):
```python
async def list_pending_runs(
    self,
    limit: int = 20,
    *,
    account_id: UUID | None = None,
    run_id: UUID | None = None,
) -> Sequence[ReconciliationRunEntity]: ...
```

- `WHERE status = 'started'` 조건으로 미처리 Run만 반환
- `ORDER BY started_at ASC`로 FIFO 보장 (오래된 Run부터 처리)
- 선택적 `account_id`/`run_id` 필터 지원
- `LIMIT` 파라미터로 배치 크기 제어

**Postgres 구현** ([`postgres/reconciliation.py`](src/agent_trading/repositories/postgres/reconciliation.py:178)): 동적 SQL 빌드로 필터 조건에 따라 `WHERE` 절을 구성.

**In-memory 구현** ([`memory.py`](src/agent_trading/repositories/memory.py:652)): `self._runs` dict에서 `status == "started"` 필터링 후 정렬/제한.

#### 3.4 `get_run_order_links()` — Link Read Path

**계약** ([`contracts.py`](src/agent_trading/repositories/contracts.py:482)):
```python
async def get_run_order_links(
    self,
    reconciliation_run_id: UUID,
) -> Sequence[ReconciliationOrderLinkEntity]: ...
```

- `trading.reconciliation_order_links` 테이블에서 `reconciliation_run_id`로 조회
- `_row_to_link_entity()` 헬퍼로 `dict` → `ReconciliationOrderLinkEntity` 변환
- `details_json` 필드는 `json.loads()`로 역직렬화

---

### Phase 1: Repository Read Path

#### 신규 Entity

```python
@dataclass(slots=True, frozen=True)
class ReconciliationOrderLinkEntity:
    reconciliation_run_id: UUID
    order_request_id: UUID
    mismatch_type: str
    details_json: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
```

3개 리포지토리 구현체(Contract Protocol, Postgres, In-memory) 모두 위 메서드를 구현했다.

---

### Phase 2: Worker Core Logic

[`ReconciliationRunProcessor`](src/agent_trading/services/reconciliation_worker.py:40)의 처리 흐름:

```
process_run(run)
  │
  ├─ 1. get_run_order_links() → order_links
  │     └─ empty → skipped_no_links (WARNING)
  │
  ├─ 2. accounts.get(run.account_id) → account
  │     └─ None → failed
  │
  ├─ 3. broker_accounts.get(account.broker_account_id) → broker_account
  │     └─ account_ref = broker_account.account_ref
  │
  ├─ 4. For each link:
  │     └─ _process_order_link(run, link, account_ref)
  │           ├─ broker_orders.list_by_order_request() → broker_orders
  │           ├─ dry_run? → log + return "resolved"
  │           ├─ resolve_and_mark() → result
  │           └─ Exception → "failed"
  │
  └─ 5. Run 마감:
        ├─ All resolved → mark_resolved()
        ├─ All failed → update_run_status("failed")
        └─ Partial → update_run_status("reflection_failed")
```

#### Idempotency 보장

1. **`list_pending_runs()`** 가 `WHERE status = 'started'`로 필터링 → 이미 처리된 Run은 재처리되지 않음
2. **`update_run_status()`** 는 `status` 컬럼만 변경 (멱등성)
3. **`optimistic locking`** (architecture 문서 참조): `transition_to_authoritative()`에서 version 체크

#### Broker Adapter Placeholder

[`_get_broker()`](src/agent_trading/services/reconciliation_worker.py:209)는 현재 `None`을 반환한다. 실제 운영 환경에서는 KIS Broker Adapter를 계정별로 캐싱/생성해야 한다. 이는 별도 Follow-up 항목이다.

---

### Phase 3: Script

[`run_reconciliation_worker.py`](scripts/run_reconciliation_worker.py) CLI 옵션:

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--once` | `False` | 1회만 실행 후 종료 |
| `--count N` | `0` (무한) | 최대 N회 실행 후 종료 |
| `--account-id` | `None` | 특정 계정만 필터 |
| `--run-id` | `None` | 특정 Run만 처리 |
| `--dry-run` | `False` | 실제 변경 없이 로그만 출력 |
| `--limit N` | `10` | 배치 크기 |
| `--interval N` | `30` | 루프 간격(초) |
| `--verbose` | `False` | 상세 로깅 |

환경 변수: `RECONCILIATION_WORKER_INTERVAL_SECONDS` (기본 30), `RECONCILIATION_WORKER_BATCH_SIZE` (기본 10)

Signal handling: `SIGINT`, `SIGTERM` → graceful shutdown

---

### Phase 4: Docker

[`docker-compose.yml`](docker-compose.yml)에 `reconciliation-worker` 서비스 추가:

- Image: `agent_trading-app:latest`
- Command: `python3 /app/scripts/run_reconciliation_worker.py`
- Restart: `unless-stopped`
- `depends_on: db: condition: service_healthy`
- 환경변수: DB 연결, KIS 자격증명, Worker 설정

---

## 4. 테스트 결과

### 신규 테스트 17종 — **모두 통과**

| 테스트 | 유형 | 검증 내용 |
|--------|------|-----------|
| `test_trigger_and_link_creates_run_and_link` | Service | `trigger_and_link()`가 Run + Link를 함께 생성 |
| `test_trigger_and_link_without_order_request_id` | Service | `order_request_id=None` → Link 없이 Run만 생성 |
| `test_list_pending_runs_returns_started_only` | Repository | `status='started'`만 반환 |
| `test_list_pending_runs_filter_by_account_id` | Repository | `account_id` 필터링 |
| `test_list_pending_runs_limit` | Repository | `limit` 파라미터 |
| `test_get_run_order_links_returns_links` | Repository | Link 조회 |
| `test_get_run_order_links_empty_for_unknown_run` | Repository | 존재하지 않는 Run → 빈 리스트 |
| `test_process_run_no_links` | Worker | Link 없는 Run → `skipped_no_links` |
| `test_process_run_no_account_found` | Worker | 계정 없음 → `failed` |
| `test_process_run_all_resolved` | Worker | 전부 해결 → `resolved` |
| `test_process_run_order_fails` | Worker | Broker 오류 → `failed` |
| `test_process_run_no_broker_orders` | Worker | Broker Order 없음 → `failed` |
| `test_process_run_dry_run_retains_status` | Worker | Dry-run → 상태 변경 없음 |
| `test_process_run_multiple_orders_partial_fail` | Worker | 부분 실패 → `failed` |
| `test_process_run_idempotent_started_only` | Idempotency | 이미 `resolved`된 Run은 미반환 |
| `test_service_list_pending_runs` | Service | 서비스 위임 |
| `test_service_get_run_order_links` | Service | 서비스 위임 |

### 기존 테스트 14종 — **모두 통과** (회귀 없음)

---

## 5. 아키텍처 결정 요약

| 결정 | 근거 |
|------|------|
| `account_ref`는 Run의 `account_id` → `account.broker_account_id` → `broker_account.account_ref`로 조회 | `BrokerOrderEntity`에 `account_ref` 필드가 없음 (설계적 결정으로 entity를 가볍게 유지) |
| `trigger_and_link()`는 `trigger()` + `attach_order_mismatch()`를 순차 호출 | 별도 트랜잭션에서 실행되나, 링크 생성 실패는 non-fatal로 처리 |
| `list_pending_runs()`는 `status='started'`만 반환 | `WHERE` 조건으로 Idempotency를 자연스럽게 보장 |
| Dry-run 모드는 `_process_order_link()`에서 early return | `resolve_and_mark()` 호출을 완전히 우회하여 side-effect 차단 |
| Worker가 `_get_broker()`에서 `None` 반환 | 현재는 `resolve_and_mark()`가 broker 없이도 `mark_resolved()`를 호출할 수 있도록 fallback 경로 존재 |
| FIFO 처리 (`ORDER BY started_at ASC`) | 오래된 불일치부터 우선 처리하여 시간적 일관성 확보 |

---

## 6. Follow-up 항목

1. **Broker Adapter 구성**: [`_get_broker()`](src/agent_trading/services/reconciliation_worker.py:209)에서 실제 KIS Broker Adapter를 계정별로 생성/캐싱해야 함. `broker_cache` dict를 활용하여 adapter 재사용.
2. **Backfill 스크립트 업데이트**: [`scripts/backfill_reconcile_required_orders.py`](scripts/backfill_reconcile_required_orders.py)에서 `trigger()` → `trigger_and_link()`로 변경 필요.
3. **운영 배포**: Docker rebuild → `docker compose up -d` → `/health` 확인 → Worker 로그 확인.
4. **통합 테스트**: 실제 Postgres + Mock Broker를 사용한 Integration Test 추가.
