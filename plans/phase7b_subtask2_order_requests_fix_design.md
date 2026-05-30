# Phase 7b Subtask 2 — order_requests 정합성 보정 설계

> 기준 시점: 2026-05-30 09:15 KST (UTC 2026-05-30 00:15Z)
> 설계 범위: KST 2026-05-27~29 기간 `order_requests` 4개 문제 보정

---

## 목차

1. [보정 대상 상세 정의](#1-보정-대상-상세-정의)
2. [Backup 및 안전장치](#2-backup-및-안전장치)
3. [2순위 문제: reconcile_required 16건 처리](#3-2순위-문제-reconcile_required-16건-처리)
4. [3순위 문제: hold decision_type 주문 생성 방지](#4-3순위-문제-hold-decision_type-주문-생성-방지)
5. [보정 순서](#5-보정-순서)
6. [리스크 및 완화 방안](#6-리스크-및-완화-방안)
7. [부록: 상세 데이터 분석](#7-부록-상세-데이터-분석)

---

## 1. 보정 대상 상세 정의

### 1.1 Primary Target: `order_requests.requested_quantity` 동기화

#### 조건 검증

| 검증 항목 | 결과 | 비고 |
|-----------|------|------|
| 모든 order_requests가 trade_decision_id 참조? | ✅ **YES** (480/480건, 0건 NULL) | `trade_decision_id` NOT NULL 컬럼 |
| trade_decision_id가 NULL인 경우? | ✅ 해당 사항 없음 | 모든 레코드가 참조 존재 |
| BUY 불일치 규모 | 296건 mismatch (100%) | `requested_quantity=1` vs `td.quantity=3~1630` |
| SELL 불일치 규모 | 19건 mismatch (역방향) | `requested_quantity=2~26` vs `td.quantity=1` |

#### 보정 SQL (BUY + SELL 공통)

```sql
UPDATE trading.order_requests o
SET requested_quantity = td.quantity,
    updated_at = NOW()
FROM trading.trade_decisions td
WHERE o.trade_decision_id = td.trade_decision_id
  AND o.requested_quantity != td.quantity
  AND o.created_at >= '2026-05-26T15:00:00Z'
  AND o.created_at <  '2026-05-29T15:00:00Z';
```

**변경 예상 건수**: 315건 (BUY 296 + SELL 19)

**참고**: `order_requests.requested_quantity`는 [`PostgresOrderRepository.update_status()`](src/agent_trading/repositories/postgres/orders.py:148)에서 수정되지 않는 필드이므로, 별도 UPDATE 구문이 필요함. `update_status()`는 `status`, `status_reason_code`, `status_reason_message`, `updated_at`, `version`만 변경함.

#### Idempotency

동일 조건으로 재실행해도 `o.requested_quantity != td.quantity` 조건에 의해 이미 보정된 레코드는 skip됨. 멱등성 보장.

### 1.2 SELL 역방향 왜곡 분석

#### 현황

| 구분 | 건수 | requested_quantity | trade_decisions.quantity |
|------|------|-------------------|------------------------|
| hold | 5건 | 2 | 1 |
| exit | 7건 | 2 (6건), 26 (1건) | 1 |
| reduce | 6건 | 2~4 | 1 |
| approve | 0건 | - | - |

#### 판단: **SELL은 `requested_quantity`가 Truth Source**

**근거**:

1. **Phase 7 backfill은 BUY만 대상**이었음 — SELL `td.quantity`는 전혀 건드리지 않음 (`backfill_buy_trade_decision_quantity.py`는 `side = 'buy'` 조건으로 필터링)
2. **SELL `requested_quantity`는 broker에 실제 제출된 수량** — FILLED 주문(3건)이 `requested_quantity=2~4`로 broker에서 체결됨
3. **`td.quantity=1`은 초기 cap 값** — Phase 7 이전 버그로 모든 trade_decision이 `quantity=1`로 고정되었던 흔적
4. `reduce` FILLED 3건: `requested_quantity=2~4`가 실제 broker 체결 수량 — `td.quantity=1`보다 `requested_quantity`가 신뢰할 수 있음

#### 결론: SELL `requested_quantity`는 보정 대상에서 제외

SELL 주문에 대해서는 **`requested_quantity`를 현재 값 그대로 유지**하고, 향후 별도 subtask에서 `trade_decisions.quantity`를 `requested_quantity`와 동기화하는 방안을 검토.

> **Phase 7b Subtask 2 범위 외** — SELL `trade_decisions.quantity` 보정은 별도 분석 필요

---

## 2. Backup 및 안전장치

### 2.1 Backup 테이블

```sql
DROP TABLE IF EXISTS trading.order_requests_bak_phase7b;
CREATE TABLE trading.order_requests_bak_phase7b AS
SELECT * FROM trading.order_requests
WHERE created_at >= '2026-05-26T15:00:00Z'
  AND created_at < '2026-05-29T15:00:00Z';
CREATE INDEX idx_orbak_phase7b_order_request_id
  ON trading.order_requests_bak_phase7b (order_request_id);
```

**예상 레코드 수**: 480건

### 2.2 Dry-run 모드

스크립트에 `--dry-run` 플래그 구현:
- Backup 테이블 생성 (실제 운영 데이터 보호)
- 변경 대상 row 목록 출력
- `requested_quantity` 변경 전후 비교 출력
- 실제 UPDATE 미실행

### 2.3 Safety Threshold

```python
SAFETY_THRESHOLD = 500  # 예상 변경 건수(315)의 약 1.5배
```

- 변경 예상 건수가 threshold 초과 시 ABORT
- `--safety-threshold N` 오버라이드 옵션 제공
- 0으로 설정 시 threshold 검사 비활성화

### 2.4 Transaction Safety

```python
async with transaction() as tx:
    # 1. Backup 생성 (같은 트랜잭션 내)
    # 2. UPDATE 실행
    # 3. 변경 건수 검증
    # 4. Dry-run이 아니면 commit
    if not args.dry_run:
        await tx.commit()
```

- 단일 트랜잭션 내에서 원자적 실행
- 실패 시 전체 롤백
- `--dry-run` 모드에서는 commit 생략

### 2.5 사후 검증 쿼리

보정 후 다음 쿼리로 정합성 검증:

```sql
-- 1. 모든 불일치가 해소되었는가?
SELECT COUNT(*) FROM trading.order_requests o
JOIN trading.trade_decisions td ON o.trade_decision_id = td.trade_decision_id
WHERE o.created_at >= '2026-05-26T15:00:00Z'
  AND o.created_at < '2026-05-29T15:00:00Z'
  AND o.requested_quantity != td.quantity;
-- 결과: 0이어야 함

-- 2. Backup과 비교
SELECT COUNT(*) FROM trading.order_requests_bak_phase7b;
-- 결과: 480 (보존 확인)

-- 3. 특이값 확인
SELECT requested_quantity, COUNT(*)
FROM trading.order_requests
WHERE created_at >= '2026-05-26T15:00:00Z'
  AND created_at < '2026-05-29T15:00:00Z'
GROUP BY requested_quantity
ORDER BY requested_quantity;
-- "1"만 있으면 잘못된 것
```

---

## 3. 2순위 문제: reconcile_required 16건 처리

### 3.1 현황 분석

| 메트릭 | 값 |
|--------|-----|
| 전체 건수 | 16건 |
| 최장 stuck 시간 | ~66시간 (5/27 06:05 KST 생성) |
| 최단 stuck 시간 | ~18시간 (5/29 06:19 KST 생성) |
| 마지막 last_synced_at | 5/29 06:36~07:00 KST |
| 이후 sync cycle 미처리 기간 | ~26시간 |

**`last_synced_at`이 5/29 06:36~07:00 KST에서 멈춘 원인 분석**:

1. `_sync_reconcile_required_orders()`가 `limit=50`으로 호출되므로 모든 16건을 조회할 수 있음
2. `transition_to_authoritative()`에서 `resolve_unknown_state()`가 계속 `RECONCILE_REQUIRED` 반환
3. 5/29 06:36 KST는 장중(intraday)이므로 EXPIRED fallback이 **억제됨** (`is_after_hours=False`)
4. 5/29 15:30 KST 이후 after-hours가 되었지만, sync cycle이 실행되지 않았거나 실행되어도 stuck 조건이 충족되지 않았을 가능성

### 3.2 해결 방안: 기존 스크립트 활용

[`scripts/backfill_reconcile_required_orders.py`](scripts/backfill_reconcile_required_orders.py) 실행으로 해결 가능:

```bash
# Dry-run: 대상 주문 확인
python3 scripts/backfill_reconcile_required_orders.py --dry-run

# 실제 실행 (모든 reconcile_required 주문 처리)
python3 scripts/backfill_reconcile_required_orders.py

# 특정 계정만 처리
python3 scripts/backfill_reconcile_required_orders.py --account-id <uuid>
```

**스크립트 동작**:
1. `OrderQuery(status=RECONCILE_REQUIRED)`로 대상 주문 조회
2. `ReconciliationService.trigger_and_link()` 호출 → reconciliation run 생성
3. Reconciliation run이 broker truth 조회 후 상태 전이 시도
4. Idempotent: active reconciliation run이 이미 존재하면 재사용

### 3.3 after-hours EXPIRED fallback 조건 분석

16건 중 `reconcile_required` 상태로 남아있는 이유:

| 조건 | 만족 여부 | 설명 |
|------|----------|------|
| `is_after_hours=True` | ✅ (5/29 15:30 KST 이후) | after-hours 조건 충족 |
| `stuck_duration > 7200s` | ✅ (최소 18시간) | 2시간 threshold 초과 |
| `created_at > grace_period` | ✅ (최소 18시간 > 30분) | young order 보호 통과 |
| `_is_genuine_manual_reconciliation()` | ❌ (False여야 EXPIRED fallback 가능) | broker_order_id 존재 + 24시간 미만 |

**가장 가능성 높은 원인**: sync cycle이 5/29 07:00 KST 이후로 이 주문들을 더 이상 처리하지 않음 (시스템 재시작, 스케줄러 중단 등). 현재 시점에서 after-hours 조건이 확실히 충족되므로, backfill 스크립트 또는 sync cycle 재실행으로 해결 가능.

### 3.4 대체 방안

스크립트 실패 시 수동 처리:

```sql
-- 강제 EXPIRED 전이 (최후의 수단)
UPDATE trading.order_requests
SET status = 'expired',
    status_reason_code = 'eod_orphan_cleanup_failed_reconciliation',
    updated_at = NOW(),
    version = version + 1
WHERE order_request_id = ANY(<16건 UUID 목록>);
```

---

## 4. 3순위 문제: hold decision_type 주문 생성 방지

### 4.1 현재 상태 분석

| 항목 | 값 |
|------|-----|
| hold order_requests 건수 | 142건 |
| 생성일 | 전부 2026-05-27 KST (단일 일자) |
| 상태 분포 | rejected 131, expired 9, reconcile_required 2 |

### 4.2 이미 존재하는 HOLD 필터링 로직

[`translation.py`](src/agent_trading/services/translation.py:76) `build_submit_order_request_from_decision()`:

```python
actionable_types = {"APPROVE", "BUY", "SELL", "EXIT", "REDUCE", "WATCH"}
if decision_type not in actionable_types:
    return None  # HOLD 포함 non-actionable 타입 필터링
```

[`execution_service.py`](src/agent_trading/services/execution_service.py:790) Phase 2:

```python
submit_request = build_submit_order_request_from_decision(intent)
if submit_request is None:
    # HOLD/WATCH skip — order_request 생성 없이 SKIPPED 반환
    return SubmitResult.build(status="SKIPPED", is_skipped=True)
```

**핵심 발견**: 현재 코드에는 **HOLD 필터링이 이미 존재**함. 142건의 hold order_requests는 이 필터링 로직이 도입되기 전(2026-05-27 이전)에 생성된 것.

### 4.3 추가 Defensive Filtering 설계

현재 `execution_service.py` Phase 2에서 이미 필터링되지만, **defense-in-depth** 원칙에 따라 2계층 방어 추가:

#### Layer 1 (이미 존재): `translation.py` — 결정적 변환 단계

변경 불필요. `HOLD`가 `actionable_types`에 없으므로 `None` 반환.

#### Layer 2 (신규): `OrderManager.create_order()` — 생성 직전 검증

[`order_manager.py`](src/agent_trading/services/order_manager.py:224) `create_order()` 메서드에 decision_type 검증 추가:

```python
async def create_order(self, request: SubmitOrderRequest, ...) -> OrderRequestEntity:
    # ... existing budget check, field validation ...
    
    # NEW: decision_type 검증 (defense-in-depth)
    # execution_service.py Phase 2에서 이미 필터링되지만,
    # 다른 코드 경로로 우회하는 경우를 대비한 2차 방어
    if hasattr(request, 'decision_type') and request.decision_type in ('HOLD', 'WATCH'):
        raise ValueError(
            f"Cannot create order for non-actionable decision_type={request.decision_type}"
        )
```

**참고**: `SubmitOrderRequest` 모델에 `decision_type` 필드가 없으면, `order_intent_id` → `OrderIntent` → `ai_backend_inputs.decision_type` 역추적 필요. 또는 더 간단하게 `trade_decision_id` → `trade_decisions.decision_type` 조회.

#### Layer 3 (신규): `submit_order_to_broker()` — 제출 직전 검증

[`order_manager.py`](src/agent_trading/services/order_manager.py:364) `submit_order_to_broker()` 메서드에도 동일한 검증 추가:

```python
async def submit_order_to_broker(self, order, broker, request, ...):
    # NEW: decision_type 검증
    # PENDING_SUBMIT 상태에서도 hold 주문이 broker에 도달하는 것을 방지
    if hasattr(request, 'decision_type') and request.decision_type in ('HOLD', 'WATCH'):
        raise ValueError(
            f"Cannot submit order for non-actionable decision_type={request.decision_type}"
        )
```

### 4.4 기존 hold order_requests 정리

142건 기존 hold 주문은 다음 중 하나로 처리:

**Option A (권장): 상태 업데이트만 수행**

`requested_quantity` 동기화 대상에 포함 (`td.quantity`가 보정된 BUY hold 주문은 `requested_quantity`가 동기화됨) + `status_reason_code` 업데이트:

```sql
-- hold 주문에 reason_code 추가 (선택 사항)
UPDATE trading.order_requests o
SET status_reason_code = 'cancelled_by_hold_decision',
    status_reason_message = 'Backfill: decision_type=hold should not have created order',
    updated_at = NOW(),
    version = version + 1
FROM trading.trade_decisions td
WHERE o.trade_decision_id = td.trade_decision_id
  AND td.decision_type = 'hold'
  AND o.created_at >= '2026-05-26T15:00:00Z'
  AND o.created_at < '2026-05-29T15:00:00Z';
```

**Option B: 그대로 유지**

- 이미 `rejected`(131) / `expired`(9) / `reconcile_required`(2)로 terminal 상태
- 추가 데이터 정리 없이 신규 생성만 방지

**권장: Option A** — 추적성을 위해 `status_reason_code`를 업데이트하되, `status`는 변경하지 않음.

### 4.5 테스트 케이스 설계

```python
# tests/services/test_order_manager_hold_filter.py

async def test_create_order_rejects_hold_decision():
    """HOLD decision_type으로 create_order() 호출 시 ValueError 발생"""
    with pytest.raises(ValueError, match="non-actionable"):
        await order_manager.create_order(
            SubmitOrderRequest(
                ..., decision_type="HOLD", quantity=10, ...
            )
        )

async def test_submit_order_to_broker_rejects_hold():
    """HOLD decision_type으로 submit 시도 시 ValueError 발생"""
    with pytest.raises(ValueError, match="non-actionable"):
        await order_manager.submit_order_to_broker(
            order, broker,
            SubmitOrderRequest(..., decision_type="HOLD", ...)
        )

async def test_translation_returns_none_for_hold():
    """build_submit_order_request_from_decision()이 HOLD에 대해 None 반환"""
    intent = create_order_intent(decision_type="HOLD")
    result = build_submit_order_request_from_decision(intent)
    assert result is None

async def test_approve_and_reduce_still_work():
    """APPROVE/REDUCE는 정상 통과"""
    for dt in ("APPROVE", "REDUCE", "EXIT"):
        intent = create_order_intent(decision_type=dt)
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
```

---

## 5. 보정 순서

### Priority 1: `order_requests.requested_quantity` 동기화 (Backfill 스크립트)

**영향**: 296건 BUY + 19건 SELL 불일치 해소
**리스크**: Low (단순 UPDATE, idempotent)
**도구**: 신규 Python 스크립트 (`scripts/backfill_order_requests_quantity.py`)

**세부 단계**:
1. Backup 테이블 생성 (order_requests_bak_phase7b)
2. Dry-run 실행
3. Safety threshold 검증
4. 실제 UPDATE 실행
5. 사후 검증

### Priority 2: `hold` decision_type 필터링 (코드 수정)

**영향**: 미래 hold 주문 생성 방지
**리스크**: Medium (회귀 위험, 하지만 이미 필터링 로직 존재)
**도구**: [`order_manager.py`](src/agent_trading/services/order_manager.py)에 2줄 추가

**세부 단계**:
1. `create_order()`에 decision_type 검증 추가
2. `submit_order_to_broker()`에 동일 검증 추가
3. 기존 hold 주문 `status_reason_code` 업데이트 (선택 사항)
4. 단위 테스트 추가

### Priority 3: `reconcile_required` 16건 정리

**영향**: 16건 stuck 상태 해소
**리스크**: Low (기존 스크립트 활용, idempotent)
**도구**: 기존 [`backfill_reconcile_required_orders.py`](scripts/backfill_reconcile_required_orders.py)

**세부 단계**:
1. Dry-run으로 대상 확인
2. 실제 실행
3. 해소되지 않은 건 수동 처리 (Option A: 강제 EXPIRED, Option B: broker truth 직접 조회)

### Priority 4: SELL 역방향 왜곡 분석 (분석만)

**영향**: 19건 SELL 불일치 (requested_quantity > td.quantity)
**리스크**: 분석 필요 (td.quantity 보정 여부 결정)
**도구**: 분석 문서만 작성, 코드 변경 없음

**분석 포인트**:
1. `reduce` FILLED 3건: 실제 체결 수량과 `requested_quantity` 비교
2. `exit` REJECTED 7건: `td.quantity=1`이 정상인가?
3. `hold` 5건: 어차피 잘못 생성된 주문이므로 무시 가능

---

## 6. 리스크 및 완화 방안

### 6.1 `order_requests` 변경이 운영 중인 broker sync에 미치는 영향

| 리스크 | 영향 | 완화 방안 |
|--------|------|----------|
| `requested_quantity` 변경으로 sync cycle에서 불일치 감지 | sync cycle이 broker_order와의 차이를 감지하면 불필요한 reconciliation trigger | `requested_quantity`는 `update_status()`에서 수정되지 않는 필드. sync cycle은 `status`만 추적하므로 영향 없음 |
| `updated_at` 변경으로 EOD orphan cleanup 조건 영향 | EOD orphan 조건은 `created_at` 기준이므로 영향 없음 | `_is_eod_orphan()`은 `created_at`만 사용 |

**결론**: `requested_quantity` 변경이 `broker_orders`, `fill_events`, `execution_attempts` 테이블에 미치는 영향은 없음. 이 테이블들은 `order_request_id` FK로 연결되어 있지만, `requested_quantity`를 직접 참조하지 않음.

### 6.2 `hold` 필터링 추가로 인한 회귀 위험

| 리스크 | 완화 방안 |
|--------|----------|
| `SubmitOrderRequest`에 `decision_type` 필드 부재 시 컴파일 에러 | 필드 존재 여부 확인 후 hasattr/isinstance guard 추가 |
| 실수로 APPROVE 주문이 차단됨 | 단위 테스트로 APPROVE/REDUCE/EXIT 정상 통과 확인 |
| 다른 코드 경로(admin_ui 수동 생성 등)에서 `decision_type` 미전달 | Guard 조건: `decision_type`이 명시적으로 `HOLD`/`WATCH`일 때만 차단, `None`/`미전달`은 통과 |

### 6.3 `reconcile_required` backfill 실행 리스크

| 리스크 | 완화 방안 |
|--------|----------|
| Reconciliation run 생성으로 broker budget 소진 | 스크립트가 reconciliation reserve 사용 (`trigger_type="requires_reconciliation"`) |
| 중복 reconciliation run 생성 | `trigger_and_link()`는 active run 존재 시 재사용 (idempotent) |
| 상태 전이 실패 | per-order exception handling으로 다른 주문에 영향 없음 |

---

## 7. 부록: 상세 데이터 분석

### 7.1 `order_requests` 컬럼 상세

| 컬럼 | 타입 | Nullable | 기본값 | 비고 |
|------|------|----------|--------|------|
| `order_request_id` | UUID | NO | gen_random_uuid() | PK |
| `trade_decision_id` | UUID | YES | NULL | FK → trade_decisions |
| `requested_quantity` | NUMERIC | NO | - | **보정 대상** |
| `status` | VARCHAR | NO | - | 현재 상태 |
| `status_reason_code` | VARCHAR | YES | NULL | 사유 코드 |
| `submitted_at` | TIMESTAMPTZ | YES | NULL | broker 제출 시각 |
| `updated_at` | TIMESTAMPTZ | NO | now() | 마지막 수정 시각 |
| `version` | INTEGER | NO | 1 | 낙관적 락 |

### 7.2 `trade_decisions` 관련 컬럼

| 컬럼 | 타입 | Nullable | 기본값 | 비고 |
|------|------|----------|--------|------|
| `trade_decision_id` | UUID | NO | gen_random_uuid() | PK |
| `decision_type` | VARCHAR | NO | 'approve' | approve/hold/reduce/exit |
| `quantity` | NUMERIC | YES | NULL | **Truth source** (Phase 7 보정 완료) |
| `side` | VARCHAR | NO | 'buy' | buy/sell |

### 7.3 데이터 정합성 매트릭스

```
BUY (433건)
├── requested_quantity=1, td.quantity=1 → 137건 (일치, 정상)
├── requested_quantity=1, td.quantity=3~1630 → 296건 (불일치, requested_quantity 왜곡)
└── requested_quantity>1, td.quantity=1 → 0건

SELL (47건)
├── requested_quantity=1, td.quantity=1 → 28건 (일치, 정상)
├── requested_quantity=2~26, td.quantity=1 → 19건 (불일치, td.quantity 왜곡)
└── requested_quantity=1, td.quantity>1 → 0건
```

### 7.4 HOLD 주문 상세

142건 전부 2026-05-27 KST에 생성됨:

```sql
-- 2026-05-27 KST = UTC 2026-05-26 15:00:00Z ~ 2026-05-27 14:59:59Z
SELECT DATE(created_at AT TIME ZONE 'Asia/Seoul') as kst_date,
       decision_type, COUNT(*)
FROM trading.order_requests o
JOIN trading.trade_decisions td ON o.trade_decision_id = td.trade_decision_id
WHERE td.decision_type = 'hold'
  AND o.created_at >= '2026-05-26T15:00:00Z'
  AND o.created_at < '2026-05-29T15:00:00Z'
GROUP BY kst_date, decision_type;
-- 결과: 2026-05-27 | hold | 142
```

### 7.5 `reconcile_required` stuck 패턴

```
5/27 06:05 KST ── 생성 ──→ RECONCILE_REQUIRED
                               │
                               ├── 5/29 06:36 KST: last_synced_at (resolve_unknown_state 실패)
                               │
                               ├── 이후 26시간 동안 sync cycle 미처리
                               │
                               └── 현재: ~66시간 stuck
```

---

## 변경 로그

| 일자 | 변경 내용 | 작성자 |
|------|----------|--------|
| 2026-05-30 | 최초 작성 (설계 단계, Subtask 3에서 구현) | Architect |
