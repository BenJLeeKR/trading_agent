# RECONCILE_REQUIRED Backfill Trigger 구현 보고서

**작성일**: 2026-05-16 18:00 KST  
**작업 범위**: 기존 stuck `RECONCILE_REQUIRED` 주문에 reconciliation run backfill

---

## 1. 대상 범위

### 대상 조건
| 조건 | 값 |
|------|-----|
| **상태** | `status = 'reconcile_required'` (`OrderStatus.RECONCILE_REQUIRED`) |
| **Active run** | 없음 (계정별 `get_active_run()` = None) |
| **Broker 주문** | 존재 여부와 무관 (broker_native_order_id 있으면 추가 로깅) |
| **필터 옵션** | `--order-id`, `--account-id`, `--limit` |

### DB 조회 쿼리 (Postgres)
```sql
SELECT * FROM trading.order_requests
WHERE status = 'reconcile_required'
ORDER BY created_at
LIMIT $1;
```

### 실제 대상 주문 (2026-05-16 기준)

| 항목 | 값 |
|------|-----|
| **order_request_id** | `400353e9-9c09-49c9-b4cc-a03ac50474b1` |
| **account_id** | `a44a02d1-7f32-5a62-99f7-235abeb58284` |
| **instrument_id** | `e3b0c442-...` (종목코드: 001230 동국홀딩스) |
| **broker_native_order_id** | `0000035653` |
| **side** | `buy` |
| **stuck 기간** | 2026-05-15 14:34 ~ 현재 |

---

## 2. Backfill 방식

### 스크립트 구조

[`scripts/backfill_reconcile_required_orders.py`](scripts/backfill_reconcile_required_orders.py)

```
main()
  └── parse_args()
  └── asyncio.run(_run(args))
        └── DatabaseConfig() → create_pool()
        └── transaction() → build_postgres_repositories(tx)
        └── ReconciliationService(repos)
        └── repos.orders.list(OrderQuery(status=RECONCILE_REQUIRED))
        └── 각 order에 대해:
              ├── broker_orders 조회 (broker_native_order_id 로깅용)
              ├── get_active_run() 확인 → 있으면 REUSE
              ├── dry-run → SKIP
              └── trigger() 호출 → TRIGGERED / FAILED
        └── Summary 출력
        └── tx.commit() (triggered > 0)
        └── close_pool()
```

### CLI 인터페이스

```bash
# Dry-run (변경 없음)
python3 scripts/backfill_reconcile_required_orders.py --dry-run

# 전체 실행
python3 scripts/backfill_reconcile_required_orders.py

# 특정 주문만 실행
python3 scripts/backfill_reconcile_required_orders.py --order-id 400353e9-...

# 특정 계정만 실행
python3 scripts/backfill_reconcile_required_orders.py --account-id <uuid>

# 최대 10건만 처리
python3 scripts/backfill_reconcile_required_orders.py --limit 10

# 상세 로그
python3 scripts/backfill_reconcile_required_orders.py --verbose
```

### 기술적 상세

| 항목 | 값 | 근거 |
|------|-----|------|
| **trigger_type** | `"requires_reconciliation"` | DB migration 0008의 CHECK constraint에 등록된 값 |
| **symbol 파라미터** | `InstrumentRepository.get(instrument_id)` → `symbol` | `OrderRequestEntity`는 `instrument_id`(UUID)만 보유 |
| **side 파라미터** | `order.side.value` | `OrderSide` enum → 문자열 변환 |
| **DB 연결** | `DatabaseConfig()` → `create_pool()` → `transaction()` → `close_pool()` | 기존 `sync_snapshots.py` 패턴 |
| **Docker 실행** | `docker compose exec -T api python3 scripts/backfill_reconcile_required_orders.py` | `./scripts` 볼륨 마운트로 rebuild 불필요 |

---

## 3. Idempotency 전략

### 1차 방어: `ReconciliationService.trigger()` 내부
- [`trigger()`](src/agent_trading/services/reconciliation_service.py:73) 시작 부분에서 `get_active_run(account_id)` 호출
- Active run(`status='started'`) 존재 → **기존 run 반환, 새 run 생성 안 함**
- 이는 Phase 18에서 이미 구현됨

### 2차 방어: Backfill 스크립트 자체
- `trigger()` 호출 **전**에 `recon_service.get_active_run(order.account_id)`로 사전 체크
- Active run 존재 → REUSE 카운트, `continue` (trigger() 호출 자체를 건너뜀)
- `--dry-run` → trigger() 호출 안 함

### 중복 시나리오별 동작

| 시나리오 | 1차 방어 | 2차 방어 | 결과 |
|---------|---------|---------|------|
| 동일 스크립트 2회 실행 | trigger()가 active run 반환 | 스크립트가 REUSE로 skip | ✅ 중복 없음 |
| 새 run 생성 직후 2회차 | trigger()가 active run 반환 | 동일 | ✅ 중복 없음 |
| run resolved 후 2회차 | trigger()가 새 run 생성 | 스크립트가 trigger() 호출 | ✅ 정상 (새 run) |
| dry-run 후 실제 실행 | trigger()가 새 run 생성 | 스크립트가 trigger() 호출 | ✅ 정상 |

---

## 4. 변경 파일 목록

| 파일 | 설명 |
|------|------|
| [`scripts/backfill_reconcile_required_orders.py`](scripts/backfill_reconcile_required_orders.py) | **신규** — Backfill 실행 스크립트 (argparse, dry-run, idempotency, instrument symbol 조회) |
| [`tests/scripts/test_backfill_reconcile_required.py`](tests/scripts/test_backfill_reconcile_required.py) | **신규** — 14개 단위 테스트 (7개 CLI 파싱 + 7개 async 로직) |
| [`plans/reconcile_required_backfill_trigger_2026-05-16.md`](plans/) | 본 보고서 |

---

## 5. 테스트 결과

### 테스트 커버리지 (14개)

| # | 테스트 | 검증 내용 |
|---|--------|----------|
| 1 | `test_parse_args_dry_run` | `--dry-run` 파싱 |
| 2 | `test_parse_args_limit` | `--limit 10` 파싱 |
| 3 | `test_parse_args_order_id` | `--order-id <uuid>` 파싱 |
| 4 | `test_parse_args_account_id` | `--account-id <uuid>` 파싱 |
| 5 | `test_parse_args_verbose` | `--verbose` 파싱 |
| 6 | `test_parse_args_defaults` | 기본값 파싱 |
| 7 | `test_parse_args_all_flags` | 모든 플래그 조합 파싱 |
| 8 | `test_backfill_trigger_creates_run` | stuck 주문 → trigger → reconciliation run 생성 |
| 9 | `test_backfill_idempotent_skips_active_run` | active run 존재 → REUSE |
| 10 | `test_backfill_dry_run_skips_trigger` | dry-run → trigger() 미호출 |
| 11 | `test_backfill_dry_run_still_checks_active` | dry-run에서 active run 체크는 정상 |
| 12 | `test_backfill_no_stuck_orders` | stuck 주문 없음 → scanned=0 |
| 13 | `test_backfill_multiple_orders` | 다수 주문 → 각각 trigger |
| 14 | `test_backfill_trigger_failure_isolated` | 실패해도 다른 주문에 영향 없음 |

### 실행 결과
```
python3 -m pytest tests/scripts/test_backfill_reconcile_required.py -v
==== 14 passed in 0.03s ====
```

---

## 6. Dry-Run 결과

### 명령어
```bash
docker compose exec -T api \
  python3 scripts/backfill_reconcile_required_orders.py --dry-run --verbose
```

### 출력
```
Found 1 stuck RECONCILE_REQUIRED order(s)
[1/1] DRY-RUN order=400353e9-... account=a44a02d1-...
       broker_native_ids=['0000035653'] (would trigger)

=== Backfill Summary ===
  scanned:   1
  triggered: 0
  reused:    0
  skipped:   1 (dry-run)
  failed:    0
  total:     1
```

### 확인 사항
- **대상 주문**: `400353e9-...` 1건 정확히 식별 ✅
- **broker_native_order_id**: `0000035653` 존재 확인 ✅
- **active run**: 없음 (dry-run이므로 trigger 미호출) ✅

---

## 7. 실제 실행 결과

### 1차 실행 — 신규 트리거
```bash
docker compose exec -T api \
  python3 scripts/backfill_reconcile_required_orders.py --verbose
```

```
Found 1 stuck RECONCILE_REQUIRED order(s)
[1/1] TRIGGERED order=400353e9-... account=a44a02d1-...
       broker_native_ids=['0000035653'] run=f7cf6333-...

=== Backfill Summary ===
  scanned:   1
  triggered: 1   ← 새로운 reconciliation run 생성
  reused:    0
  skipped:    0
  failed:     0
  total:      1
```

### 생성된 Reconciliation Run

| 항목 | 값 |
|------|-----|
| **reconciliation_run_id** | `f7cf6333-303f-454b-8ebc-e140be9199dd` |
| **account_id** | `a44a02d1-7f32-5a62-99f7-235abeb58284` |
| **trigger_type** | `requires_reconciliation` |
| **status** | `started` |
| **symbol** | 종목코드 001230 |

### 2차 실행 — Idempotency 검증
```bash
docker compose exec -T api \
  python3 scripts/backfill_reconcile_required_orders.py --verbose
```

```
Found 1 stuck RECONCILE_REQUIRED order(s)
[1/1] REUSE order=400353e9-... account=a44a02d1-...
       broker_native_ids=['0000035653'] active_run=f7cf6333-...

=== Backfill Summary ===
  scanned:   1
  triggered: 0   ← 중복 생성 없음
  reused:    1   ← 기존 run 재사용
  skipped:    0
  failed:     0
  total:      1
```

### `/health` 확인
```json
{
  "status": "ok",
  "database": "connected",
  "scheduler": { "healthy": true, ... }
}
```

---

## 8. 아키텍처 다이어그램

```
[변경 전]

DB: trading.order_requests
  └── status = 'reconcile_required' (1건)
  └── ReconciliationRun: 0건 ← 문제!

[변경 후]

scripts/backfill_reconcile_required_orders.py
  │
  ├── 1. DB 조회: status = 'reconcile_required'
  │     └── 1건 발견 (400353e9-...)
  │
  ├── 2. get_active_run(account_id)
  │     └── None → trigger 필요
  │
  └── 3. ReconciliationService.trigger()
        └── account_id=a44a02d1
        └── trigger_type="requires_reconciliation"
        └── symbol="001230"
        └── side="buy"
        │
        ├── ReconciliationRun 생성 (f7cf6333-...)
        ├── status = 'started'
        └── BlockingLock 획득 (ON CONFLICT DO NOTHING)
              └── account_id + symbol + side 기준

2회차 실행:
  └── get_active_run(account_id)
        └── f7cf6333-... (status='started') → REUSE
```

---

## 9. 남은 Follow-up

| 우선순위 | 항목 | 설명 |
|---------|------|------|
| **P0** | **Reconciliation 실행 모니터링** | 생성된 run(`f7cf6333-...`)이 실제로 reconciliation 프로세스에 의해 처리되는지 확인 필요. run이 `started` 상태에서 계속 머물지 않고 `resolved` 또는 `escalated`로 진행되어야 함 |
| **P1** | **Schedule/CRON 등록** | backfill 스크립트를 정기적으로 실행하여 신규 stuck 주문이 발생해도 자동 backfill 되도록 개선 가능 |
| **P2** | **Admin UI reconciliation run 조회** | 생성된 run이 Admin UI의 Reconciliation 화면에서 조회/추적 가능한지 확인 |
| **P3** | **Paper 전용 auto-resolve** | Paper 환경에서 reconciliation이 항상 실패하면 자동 해소 정책 도입 |

---

## 부록: 참조

- **Backfill 스크립트**: [`scripts/backfill_reconcile_required_orders.py`](scripts/backfill_reconcile_required_orders.py)
- **테스트 파일**: [`tests/scripts/test_backfill_reconcile_required.py`](tests/scripts/test_backfill_reconcile_required.py)
- **Phase 17 분석 보고서**: [`plans/reconcile_required_single_order_trace_2026-05-16.md`](plans/reconcile_required_single_order_trace_2026-05-16.md)
- **Phase 18 Auto-trigger 구현**: [`plans/reconcile_required_auto_trigger_implementation_2026-05-16.md`](plans/reconcile_required_auto_trigger_implementation_2026-05-16.md)
- **ReconciliationService**: [`src/agent_trading/services/reconciliation_service.py`](src/agent_trading/services/reconciliation_service.py)
- **OrderManager**: [`src/agent_trading/services/order_manager.py`](src/agent_trading/services/order_manager.py)
- **Docker Compose 볼륨 마운트**: [`docker-compose.yml`](docker-compose.yml) — `./scripts:/app/scripts`
