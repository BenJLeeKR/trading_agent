# Reconciliation Run 실제 처리 추적 보고서

**작성일**: 2026-05-16 18:35 KST  
**분석 대상**: 
- `reconciliation_run_id = f7cf6333-303f-454b-8ebc-e140be9199dd`
- `order_request_id = 400353e9-9c09-49c9-b4cc-a03ac50474b1`

---

## 1. 대상 Run / 주문 식별자

| 항목 | 값 |
|------|-----|
| **reconciliation_run_id** | `f7cf6333-303f-454b-8ebc-e140be9199dd` |
| **order_request_id** | `400353e9-9c09-49c9-b4cc-a03ac50474b1` |
| **account_id** | `a44a02d1-7f32-5a62-99f7-235abeb58284` |
| **broker_native_order_id** | `0000035653` |
| **종목** | `001230` (동국제강) |

---

## 2. Run 상태 타임라인

| 시각 (KST) | 이벤트 | 출처 |
|-----------|--------|------|
| **2026-05-16 18:27:40** | Reconciliation Run 생성 (`status=started`, `trigger_type=requires_reconciliation`) | Backfill 스크립트 |
| **2026-05-16 18:27:40** | Blocking Lock 획득 (`expires_at=18:57:40`, 30분 TTL) | Backfill 스크립트 |
| **2026-05-16 18:27:40 ~ 현재** | **Run 미처리 상태 유지** (`started`, `completed_at=null`) | DB 관측 |

### Run 메타데이터

| 메타데이터 | 값 |
|-----------|-----|
| **status** | **`started`** (미완료) |
| **trigger_type** | `requires_reconciliation` |
| **started_at** | 2026-05-16 18:27:40 KST |
| **completed_at** | **`null`** |
| **updated_at** | 2026-05-16 18:27:40 KST (생성 이후 갱신 없음) |

---

## 3. 주문 상태 변화 여부

### 현재 주문 상태

| 항목 | 값 | 변화 여부 |
|------|-----|----------|
| **order_request_id** | `400353e9-...` | - |
| **status** | **`reconcile_required`** | ❌ **변화 없음** |
| **updated_at** | 2026-05-15 14:34:13 KST | ❌ **어제 이후 갱신 없음** |
| **version** | `5` | ❌ **증분 없음** |

### OrderStateEvents 최근 이력

| # | 이전 상태 | 새 상태 | 시각 (KST) | reason_code |
|---|---------|-------|-----------|-------------|
| 1 | `submitted` | **`reconcile_required`** | 2026-05-15 14:34:21 | `null` |
| 2 | `pending_submit` | `submitted` | 2026-05-15 14:31:24 | `0000035653` |
| 3 | `validated` | `pending_submit` | 2026-05-15 14:31:21 | `null` |
| 4 | `draft` | `validated` | 2026-05-15 14:31:21 | `null` |

> **Backfill 이후에도 주문 상태는 전혀 변하지 않았습니다.**

---

## 4. Broker Truth 조회 흔적

### BrokerOrder 상태

| 항목 | 값 |
|------|-----|
| **broker_order_id** | `da6abaa2-47c8-4d3e-81b8-c6d602288edb` |
| **broker_native_order_id** | `0000035653` **존재** |
| **broker_status** | **`reconcile_required`** |
| **last_synced_at** | 2026-05-16 15:18:06 KST (오늘) |

> `last_synced_at`이 오늘 15:18 KST로 갱신된 점이 중요합니다. 이는 `PostSubmitSyncRunner`가 이 주문을 계속 sync 대상으로 삼고 있음을 의미합니다. 그러나 post-submit sync는 `inquire-daily-ccld` API를 호출할 뿐, `ReconciliationService`를 통해 broker truth 조회를 수행하지 않습니다.

### Reconciliation 연결 흔적

| 테이블 | 결과 | 의미 |
|--------|------|------|
| `reconciliation_order_links` | **0건** | mismatch 분석 **미수행** |
| `reconciliation_position_links` | **0건** | position 분석 **미수행** |
| `order_blocking_locks` | **1건** | lock 존재 (expires 18:57:40 KST) |
| `fill_events` | **0건** | 체결 이력 없음 |

---

## 5. Root Cause 분류

## **분류 C: Run만 생성되고 소비되지 않음** ✅

### 분류 기준

| 분류 | 설명 | 해당 여부 |
|------|------|----------|
| **A. 정상 처리 완료** | run 실행, 주문 상태 변경 | ❌ (run=started, order=reconcile_required) |
| **B. 실행됐지만 broker truth 부족** | run은 돌았지만 paper broker가 truth 미제공 | ❌ (run 메서드가 전혀 호출 안 됨) |
| **C. Run만 생성되고 소비 안 됨** | reconciliation worker/loop 미존재 | **✅ 해당** |
| **D. 내부 오류** | 예외/DB 문제 | ❌ (lock은 정상 생성) |

### 핵심 증거: Reconciliation Run 소비자가 존재하지 않음

코드 분석 결과, `ReconciliationService`의 다음 메서드들이 **어디에서도 호출되지 않습니다**:

| 메서드 | 파일:라인 | 호출 여부 |
|--------|----------|----------|
| `trigger()` | `reconciliation_service.py:46` | ✅ 호출됨 (backfill) |
| `resolve_unknown_state()` | `reconciliation_service.py:328` | ❌ **미호출** |
| `resolve_and_mark()` | `reconciliation_service.py:373` | ❌ **미호출** |
| `mark_resolved()` | `reconciliation_service.py:296` | ❌ **미호출** |
| `attach_order_mismatch()` | `reconciliation_service.py:266` | ❌ **미호출** |
| `get_active_run()` | `reconciliation_service.py:117` | ✅ 호출됨 (backfill) |

### 조회된 프로세스들의 Reconciliation 처리 현황

| 프로세스 | Reconciliation 처리 | 설명 |
|---------|-------------------|------|
| `PostSubmitSyncRunner` (`order_sync_service.py`) | ❌ | `RECONCILE_REQUIRED` 주문 sync는 하지만 reconciliation run 무시 |
| `run_post_submit_sync_loop.py` | ❌ | ReconciliationService 미사용 |
| `run_near_real_ops_scheduler.py` | ❌ | post-submit sync만 호출 |
| `OrderManager._transition_to_core()` | ✅ (생성만) | `trigger()`로 run 생성까지만, 소비는 없음 |

---

## 6. 운영 해석

### 6.1 현재 상태 다이어그램

```
Backfill (18:27:40 KST)
  ↓
trigger(account_id)
  ↓
├── ReconciliationRun (f7cf6333, status=started)  ← 🟡 생성만 됨
├── BlockingLock (expires 18:57:40 KST)           ← 🟡 30분 후 만료
├── reconciliation_order_links: 0건               ← 🔴 미수행
├── reconciliation_position_links: 0건             ← 🔴 미수행
└── fill_events: 0건                               ← 🔴 체결 없음

Order (400353e9, status=reconcile_required)
  └── PostSubmitSyncRunner: sync 지속 (last_synced=15:18 KST)
       └── 하지만 reconciliation run 무시
```

### 6.2 구조적 문제

1. **Reconciliation Run 생성은 되지만 소비자가 없음**: `trigger()`로 run을 만들어도, 이 run을 찾아서 `resolve_and_mark()`를 호출하는 프로세스가 전혀 없음
2. **Post-submit sync와 reconciliation이 분리되어 있음**: `PostSubmitSyncRunner`는 주문 상태 sync만 수행하고, reconciliation run의 존재를 인지하지 못함
3. **Blocking lock은 자동 만료됨**: 30분 후 lock이 사라지면 계정에 새 주문 제출이 가능해지지만, 기존 `reconcile_required` 주문은 해결되지 않은 채 영원히 남음

### 6.3 Paper 환경 한계와의 관계

분류 **B(실행됐지만 broker truth 부족)** 가 아닌 이유:
- reconciliation run의 `resolve_and_mark()`가 **호출 자체가 되지 않았음**
- Paper 환경에서 `inquire-daily-ccld`가 빈 결과를 반환하는 문제는 post-submit sync 레벨에서 발생
- reconciliation 레벨까지 도달하지도 못함

---

## 7. 다음 액션 제안

### 7.1 즉시 조치 (P0)

| 우선순위 | 액션 | 설명 |
|---------|------|------|
| **P0** | **Reconciliation Worker 구현** | `PostSubmitSyncRunner.run_sync_cycle()` 종료 직전에 `get_active_run()` → `resolve_and_mark()` 호출 로직 추가. 또는 별도 reconciliation loop 생성. |
| **P0** | **현재 stuck run 수동 해소** | Blocking lock 만료 전(`18:57:40 KST`)에 broker truth 수동 확인 후 `mark_resolved()` 호출 또는 주문 상태 수동 변경 필요 |

### 7.2 단기 개선 (P1)

| 우선순위 | 액션 | 설명 |
|---------|------|------|
| **P1** | **Reconciliation run 자동 만료 정책** | 일정 시간(예: 1시간) 이상 `started` 상태인 run을 자동 `escalated` 처리 |
| **P1** | **Observability: 모니터링 쿼리 추가** | `SELECT * FROM reconciliation_runs WHERE status='started' AND started_at < NOW() - INTERVAL '30 minutes'` |
| **P1** | **Backfill 스크립트에 --resolve 옵션 추가** | run 생성뿐 아니라 즉시 `resolve_and_mark()` 호출까지 수행하는 옵션 |

### 7.3 중기 설계 (P2)

| 우선순위 | 액션 | 설명 |
|---------|------|------|
| **P2** | **Post-submit sync와 reconciliation 통합** | sync 과정에서 reconciliation run이 존재하면 자동으로 resolve 시도 |
| **P2** | **Paper 전용 reconciliation 전략** | Paper 환경에서 reconcile 실패 시 자동 `escalated` 처리 및 운영자 알림 |

### 7.4 즉시 수동 해소 가이드

Blocking lock 만료 전에 다음 수동 조치를 권장:

```bash
# 1. Broker truth 확인 (KIS API 조회)
# docker compose exec -T api python3 -c "
# from src.agent_trading.services.reconciliation_service import ReconciliationService
# ...

# 2. broker_native_order_id=0000035653로 KIS API 직접 조회
# curl -X GET 'https://openapivts.koreainvestment.com:29443/uapi/domestic-stock/v1/trading/inquire-daily-ccld' \
#   -H 'authorization: Bearer <token>' \
#   -d '...'

# 3. 체결됨 → fill_events 기록 + transition_to_authoritative(FILLED)
# 4. 체결 안 됨 → transition_to_authoritative(CANCELLED) 또는 수동 CANCEL submit
```

---

## 부록: 참조

- **Phase 17 분석**: [`plans/reconcile_required_single_order_trace_2026-05-16.md`](plans/reconcile_required_single_order_trace_2026-05-16.md)
- **Phase 18 Auto-trigger**: [`plans/reconcile_required_auto_trigger_implementation_2026-05-16.md`](plans/reconcile_required_auto_trigger_implementation_2026-05-16.md)
- **Phase 19 Backfill**: [`plans/reconcile_required_backfill_trigger_2026-05-16.md`](plans/reconcile_required_backfill_trigger_2026-05-16.md)
- **ReconciliationService**: [`src/agent_trading/services/reconciliation_service.py`](src/agent_trading/services/reconciliation_service.py)
- **OrderSyncService**: [`src/agent_trading/services/order_sync_service.py`](src/agent_trading/services/order_sync_service.py)
- **PostSubmitSyncLoop**: [`scripts/run_post_submit_sync_loop.py`](scripts/run_post_submit_sync_loop.py)
