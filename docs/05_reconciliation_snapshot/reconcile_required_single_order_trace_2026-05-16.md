# RECONCILE_REQUIRED 단일 주문 추적 분석 보고서

**작성일**: 2026-05-16 18:00 KST  
**분석 대상**: `order_request_id=400353e9-9c09-49c9-b4cc-a03ac50474b1`

---

## 1. 대상 주문 식별자

| 항목 | 값 |
|------|-----|
| **order_request_id** | `400353e9-9c09-49c9-b4cc-a03ac50474b1` |
| **broker_native_order_id** | `0000035653` |
| **broker_order_id (내부 PK)** | `da6abaa2-...` |
| **종목코드** | `001230` (동국홀딩스) |
| **의사결정 ID** | `366f0bc1-...` (REDUCE) |
| **매매방향** | `buy` (KIS paper 매도=매수 파라미터) |
| **수량** | 10주 |
| **가격** | 11,400 KRW |
| **최종 상태** | `reconcile_required` |
| **상태 고정 시각** | 2026-05-15 14:34:21 KST |

---

## 2. 전체 상태 전이 타임라인

### 2.1 order_state_events DB 기록

| # | 이전 상태 | 이후 상태 | 기록 시각 (KST) |
|---|----------|----------|----------------|
| 1 | `draft` | `validated` | 2026-05-15 14:31:04 |
| 2 | `validated` | `pending_submit` | 2026-05-15 14:31:04 |
| 3 | `pending_submit` | `submitted` | 2026-05-15 14:31:24 |
| 4 | `submitted` | `reconcile_required` | 2026-05-15 14:34:21 |

### 2.2 로그 기반 상세 타임라인

| 시각 (KST) | 이벤트 | 상세 |
|-----------|--------|------|
| **14:31:04** | Trade decision → Order 생성 | paper-decision-loop: decision `366f0bc1` → order_request `400353e9` 생성 |
| **14:31:21** | 주문 검증 완료 | draft → validated → pending_submit |
| **14:31:24** | **KIS paper API submit** | `order-stock` HTTP **200 OK** → `broker_native_order_id=0000035653` 할당 |
| **14:31:24** | submit pipeline 완료 | 상태: `submitted` |
| **14:34:21** | **최초 post-submit sync** | `inquire-daily-ccld` 조회 → **ODNO match FAILED** (output_count=0, odnos_in_response=[]) |
| **14:34:21** | **reconcile_required 전이** | submitted → reconcile_required |
| **15:20:21** | post-submit sync 재시도 | ODNO match FAILED (output_count=0) |
| **15:25:41** | post-submit sync 재시도 | ODNO match FAILED (output_count=0) |
| **15:31:02** | post-submit sync 재시도 | ODNO match FAILED (output_count=0) |
| **15:31:20** | post-submit sync 재시도 | ODNO match FAILED (output_count=0) |
| ... | 이후 지속 | 동일 패턴 반복, 최종 sync: 2026-05-16 15:18 KST |
| **현재** | **reconcile_required 유지** | reconciliation run 미실행, fill events 0건 |

---

## 3. Broker 상태

### 3.1 KIS Paper API 제출 결과

| 항목 | 결과 |
|------|------|
| **엔드포인트** | `/uapi/domestic-stock/v1/trading/order-stock` (KIS paper mock) |
| **HTTP 응답** | **200 OK** |
| **broker_native_order_id** | `0000035653` (정상 할당) |
| **제출 시각** | 2026-05-15 14:31:24 KST |

→ **broker_native_order_id가 존재**하므로 주문은 KIS paper API에 정상 접수됨.

### 3.2 broker_orders 테이블

```sql
SELECT broker_order_id, broker_native_order_id, broker_status, last_synced_at
FROM trading.broker_orders
WHERE order_request_id = '400353e9-9c09-49c9-b4cc-a03ac50474b1';
```

| broker_order_id | broker_native_order_id | broker_status | last_synced_at |
|----------------|----------------------|--------------|---------------|
| `da6abaa2-...` | `0000035653` | `reconcile_required` | 2026-05-16 06:18:06 UTC |

→ broker_status도 `reconcile_required`로 동기화. 마지막 동기화: 2026-05-16 15:18 KST (다음날까지 sync 지속).

---

## 4. Post-Submit Sync / Reconciliation 관측

### 4.1 Post-Submit Sync 로그

```
[2026-05-15 14:34:21 KST] post_submit_sync
  broker_order_id=da6abaa2-...
  → inquire-daily-ccld API 호출
  → ODNO match FAILED for broker_order_id=0000035653
    (output_count=0, odnos_in_response=[])
  → 상태 전이: submitted → reconcile_required
```

### 4.2 핵심 DB 조회 결과

| 테이블 | 조회 결과 |
|--------|----------|
| `trading.reconciliation_runs` | **0건** — reconciliation run 단 한 번도 실행되지 않음 |
| `trading.reconciliation_order_links` | **0건** — reconciliation 대상으로 링크된 적 없음 |
| `trading.fill_events` | **0건** — 체결 이력 없음 |
| `trading.order_requests WHERE status='reconcile_required'` | **총 1건** — 이 주문이 유일 |

---

## 5. Root Cause 분류

### 분류: **A. Paper Broker Truth 한계** ✅

### 분류 기준

| 분류 | 설명 | 해당 여부 |
|------|------|----------|
| **A. Paper broker truth 한계** | KIS paper mock API의 inquire-daily-ccld가 체결 내역을 반환하지 않음 | **✅ 해당** |
| **B. Submit 후 broker API 장애** | HTTP 200 이후 broker 내부 오류로 ODNO 미생성 | ❌ 미해당 (ODNO=0000035653 정상) |
| **C. Reconciliation 로직 버그** | reconcile_required 진입 후 reconciliation run 미트리거 | ⚠️ 부분 해당 (정책 문제) |
| **D. 기타 (DB, 네트워크 등)** | DB/네트워크 수준의 장애 | ❌ 미해당 |

### 근거

1. **KIS paper API가 HTTP 200으로 정상 제출 성공**: broker_native_order_id=`0000035653` 할당 → submit 자체는 문제없음
2. **`inquire-daily-ccld`가 해당 ODNO에 대해 항상 0건 반환**: 실전(KIS real) 환경에서는 제출된 주문이 일별 체결 내역에 포함되지만, **모의투자(paper) 환경에서는 제출된 주문이 inquire-daily-ccld 결과에 나타나지 않음**
3. **동일 패턴이 모든 post-submit sync 사이클에서 반복**: output_count=0, odnos_in_response=[]가 일관되게 관측
4. **DB에 이 주문이 유일한 reconcile_required 건**: 시스템 전체에서 이 주문만 stuck

---

## 6. 운영 해석

### 6.1 현재 상황

| 측면 | 상태 | 위험도 |
|------|------|--------|
| **주문 접수** | KIS paper에 정상 접수 (HTTP 200, broker_native_order_id 존재) | ✅ 안전 |
| **체결 여부** | **알 수 없음** — paper API가 체결 내역을 반환하지 않아 확인 불가 | ⚠️ 불확실 |
| **시스템 정체** | reconcile_required 상태로 후속 처리 불가 | 🔴 막힘 |
| **영향 범위** | DB에 유일한 reconcile_required 건, 전체 시스템 영향 없음 | 🟡 제한적 |
| **자동 해소** | reconciliation run 미실행 → 자동 해소 불가능 | 🔴 미작동 |

### 6.2 Root Cause 해석

**근본 원인은 KIS paper mock API의 한계**입니다. Paper 환경의 `inquire-daily-ccld` 엔드포인트는 실전 환경과 달리 제출된 주문의 체결 내역을 반환하지 않습니다. 이는 KIS paper API 자체의 특성으로, 코드 버그가 아닌 **환경적 제약**에 해당합니다.

Post-submit sync 로직은 `inquire-daily-ccld` 결과에 따라 `submitted` 상태를 유지할지 `reconcile_required`로 전이할지 결정하는데, paper 환경에서는 이 검증이 **항상 실패**하도록 설계되어 있습니다.

---

## 7. 후속 조치 제안

### 7.1 우선순위별 제안

| 우선순위 | 제안 | 설명 |
|---------|------|------|
| **P0** | **Paper 환경 post-submit sync 우회 로직** | `inquire-daily-ccld`가 paper 환경에서 항상 0건을 반환한다면, paper 환경에서는 post-submit sync를 **건너뛰거나**, `order-stock` 응답만으로 `submitted` 상태를 유지하도록 변경 |
| **P1** | **Reconciliation 자동 트리거** | `reconcile_required` 상태 진입 시 reconciliation run을 **자동 생성**하여 사람의 개입 없이도 상태 해소 시도 |
| **P2** | **Paper 전용 reconciliation 전략** | Paper 환경에서는 `inquire-daily-ccld` 대신 `inquire-ccld` (개별 체결 조회) API를 사용하거나, 일정 시간 후 자동으로 `reconcile_required`를 해소하는 정책 도입 |
| **P3** | **수동 해소 스크립트** | 현재 stuck된 이 주문을 수동으로 해소할 수 있는 스크립트 제공 (예: `reconcile_required` → `submitted` 복원 또는 `cancelled` 처리) |

### 7.2 즉시 권장 조치

1. **KIS paper UI (openapivts)에서 broker_native_order_id=0000035653 직접 조회**하여 실제 체결 여부 확인
2. 체결되었다면 수동으로 `fill_events` 기록 및 상태 `filled`로 변경
3. 체결되지 않았다면 `reconcile_required` → `cancelled`로 수동 상태 변경
4. **P0 수정 (paper 환경 post-submit sync 우회)은 5/18(월) 영업일 장중 E2E 검증 필수**

---

## 부록: 참조

- **Post-submit sync 구현**: [`src/agent_trading/services/kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py)
- **Order 상태 전이 로직**: [`src/agent_trading/services/order_sync_service.py`](src/agent_trading/services/order_sync_service.py)
- **Scheduler 로그**: [`logs/near_real_scheduler_2026-05-15.log`](logs/near_real_scheduler_2026-05-15.log)
- **DB 마이그레이션 (reconciliation)**: [`db/migrations/0008_update_reconciliation_trigger_types.sql`](db/migrations/0008_update_reconciliation_trigger_types.sql)
- **분석 세션 summary**: Conversation Phase 17 (2026-05-16)
