# 000880 Broker Truth Order Recovery — 2026-05-15

## 1. 대상 주문 식별 정보

| 항목 | 값 |
|------|-----|
| `order_request_id` | `3125e4ce-5f14-4d5a-aefe-98d3332c7271` |
| `broker_order_id` | `55dbca29-b996-4192-941f-6e1fa41a4718` |
| `broker_native_order_id` | `0000030092` |
| Broker name | `koreainvestment` (KIS paper) |
| Symbol | 000880 (한화) |
| Side | BUY |
| Order Type | LIMIT |
| Price | ₩145,400 |
| Quantity | 10 shares |
| Created | 2026-05-15 13:11:56 KST |
| Submitted | 2026-05-15 13:12:10 KST (state event 기준) |
| Correlation ID | `paper-loop-000880-1-19304` |

### State History (정상 부분)

| 시간 (KST) | 이전 상태 | 새 상태 | 출처 |
|---|---|---|---|
| 13:12:09 | `draft` | `validated` | internal |
| 13:12:09 | `validated` | `pending_submit` | internal |
| 13:12:10 | `pending_submit` | `submitted` | internal (reason_code=0000030092) |
| 13:15:06 | `submitted` | `reconcile_required` | internal |

### State History (잘못된 부분 — 본 세션)

| 시간 (KST) | 이전 상태 | 새 상태 | 출처 |
|---|---|---|---|
| 14:19:37 | `reconcile_required` | `rejected` | ❌ system_ops_recovery (reason_code=40270000) |
| 14:19:54 | `pending_submit` | `rejected` | ❌ system_ops_recovery (잘못된 중복 이벤트) |

---

## 2. Broker Truth 증거

### Position Snapshots (source_of_truth=broker)

`position_snapshots` 테이블에는 KIS API에서 직접 조회한 데이터가 저장됩니다.  `source_of_truth='broker'` 필드는 이 데이터가 KIS broker API의 응답을 그대로 반영함을 의미합니다.

| snapshot_at (KST) | 수량 | 평균단가 | 시장가 | 평가손익 | 출처 |
|---|---|---|---|---|---|
| 13:49:43 | 10 | ₩145,400 | ₩142,600 | -₩28,000 | broker |
| 13:55:04 | 10 | ₩145,400 | ₩142,500 | -₩29,000 | broker |
| 14:00:28 | 10 | ₩145,400 | ₩141,900 | -₩35,000 | broker |
| 14:05:54 | 10 | ₩145,400 | ₩141,300 | -₩41,000 | broker |
| 14:11:12 | 10 | ₩145,400 | ₩141,800 | -₩36,000 | broker |
| 14:16:25 | 10 | ₩145,400 | ₩142,100 | -₩33,000 | broker |
| 14:20:44 | 10 | ₩145,400 | ₩142,500 | -₩29,000 | broker |
| 14:23:07 | 10 | ₩145,400 | ₩142,500 | -₩29,000 | broker |
| 14:26:01 | 10 | ₩145,400 | ₩142,600 | -₩28,000 | broker |
| 14:28:27 | 10 | ₩145,400 | ₩141,500 | -₩39,000 | broker |

**결론: 000880 10주 @ ₩145,400 매수 포지션이 브로커 계좌에 실제 존재합니다.**  `average_price=145,400`은 주문의 `requested_price=145,400`과 정확히 일치합니다.

### Fill Events

`fill_events` 테이블에는 이 주문에 대한 체결 이벤트가 **0건**입니다.  이는 시스템이 브로커의 체결 데이터를 올바르게 수집하지 못했음을 의미합니다 (시스템 결함).

### Cash Balance

최근 `cash_balance_snapshots` (source_of_truth=broker):
- Available cash: ₩27,329,630
- Settled cash: ₩27,329,630

---

## 3. DB 현재 상태 (오염 범위)

| 테이블 | 컬럼 | 현재값 | 올바른 값 |
|--------|------|--------|-----------|
| `order_requests` | `status` | `rejected` ❌ | `filled` |
| `order_requests` | `status_reason_code` | `40270000` ❌ | `broker_truth_recovery` |
| `order_requests` | `status_reason_message` | `모의투자 상/하한가 초과 (broker error)` ❌ | `Broker position snapshot 기준 filled 복구` |
| `order_requests` | `submitted_at` | `null` ❌ | `2026-05-15T04:12:10.082Z` |
| `broker_orders` | `broker_status` | `rejected` ❌ | `filled` |
| `order_state_events` | 이벤트 2건 | `reconcile_required→rejected`, `pending_submit→rejected` ❌ | 보정 이벤트 추가 필요 |
| `fill_events` | 없음 | 0건 ⚠️ | position 확인되었으나 세부 데이터 없음 |

### 영향 받지 않은 항목 (수정 불필요)
- `trade_decisions`: ✅ 정상 (`decision_type=hold`, `side=buy`, `entry_price=145400`)
- `decision_contexts`: ✅ 정상
- `reconciliation_*`: 관련 없음 (정합성 테이블 미사용)
- 다른 95건의 `pending_submit→rejected` 주문: ✅ 이들은 broker 미도달이므로 `rejected` 유지

---

## 4. 수행한 복구 조치

### 원칙

1. **잘못된 이벤트는 삭제하지 않음** — 감사 추적(audit trail) 보존을 위해 보정 이벤트를 추가
2. **broker truth를 최우선** — position_snapshot 데이터가 broker truth
3. **다른 주문은 건드리지 않음** — 000880 1건만 복구
4. **broker_orders 존재 여부 사전 확인** — UPDATE 전 row 존재 확인
5. **복구 provenance 강력 기록** — `event_source='broker_truth_recovery'`, `reason_code='broker_truth_recovery'`
6. **fill_events에 position-derived recovery 표시** — `source_channel='manual'`, `raw_payload_uri`에 JSON metadata

### Step A: order_requests 복구 ✅ `UPDATE 1`

```sql
UPDATE trading.order_requests
SET status = 'filled',
    status_reason_code = 'broker_truth_recovery',
    status_reason_message = 'Broker position snapshot 기준 filled 복구 (10주 @ 145,400 confirmed, source_of_truth=broker)',
    submitted_at = '2026-05-15T04:12:10.082Z',
    updated_at = NOW()
WHERE order_request_id = '3125e4ce-5f14-4d5a-aefe-98d3332c7271';
```

### Step B: broker_orders 복구 ✅ `UPDATE 1` (row 존재 확인 후 실행)

**사전 확인**: `broker_order_id='55dbca29-b996-4192-941f-6e1fa41a4718'` 존재 확인 완료 (`broker_status='rejected'`)

```sql
UPDATE trading.broker_orders
SET broker_status = 'filled',
    last_synced_at = NOW()
WHERE broker_order_id = '55dbca29-b996-4192-941f-6e1fa41a4718';
```

### Step C: order_state_events 보정 (추가) ✅ `INSERT 0 1`

잘못된 `system_ops_recovery` 이벤트 2건은 삭제하지 않고, 보정 이벤트를 추가합니다.

```sql
INSERT INTO trading.order_state_events (
    order_state_event_id, order_request_id,
    previous_status, new_status,
    event_source, event_timestamp, ingested_at,
    reason_code, raw_event_uri, correlation_id, created_at
) VALUES (
    gen_random_uuid(),
    '3125e4ce-5f14-4d5a-aefe-98d3332c7271',
    'rejected',
    'filled',
    'broker_truth_recovery',
    NOW(), NOW(),
    'broker_truth_recovery',
    NULL,
    'recovery-000880-2026-05-15',
    NOW()
);
```

### Step D: fill_events (position-derived recovery) ✅ `INSERT 0 1` (중복 시 ON CONFLICT DO NOTHING)

Position snapshot 데이터에 기반하여 fill_event를 생성합니다.  수수료/세금 데이터는 broker API에서 확인 불가이므로 0으로 설정합니다.

**참고**: `source_channel` 컬럼은 `CHECK (source_channel IN ('websocket', 'rest_poll', 'backfill', 'manual'))` 제약이 있어 `'broker_truth_recovery'` 사용 불가. 대신 `'manual'` 사용하고 복구 metadata는 `raw_payload_uri`에 JSON으로 저장.

```sql
INSERT INTO trading.fill_events (
    fill_event_id, broker_order_id, broker_fill_id,
    fill_timestamp, fill_price, fill_quantity,
    fill_fee, fill_tax, source_channel,
    raw_payload_uri, created_at
) VALUES (
    gen_random_uuid(),
    '55dbca29-b996-4192-941f-6e1fa41a4718',
    'broker_truth_recovery-0000030092',
    '2026-05-15T04:12:10.082Z',
    145400.00000000,
    10.00000000,
    0, 0,
    'manual',
    '{"recovery_type": "broker_truth_recovery", "source": "position_snapshot", "note": "position-derived recovery: 10주 @ 145,400 confirmed via broker position snapshots"}',
    NOW()
)
ON CONFLICT (broker_order_id, broker_fill_id) DO NOTHING;
```

### 복구 후 검증된 상태

| 테이블 | 컬럼 | 복구 후 값 | 검증 |
|--------|------|-----------|------|
| `order_requests` | `status` | `filled` ✅ | MCP SELECT 확인 |
| `order_requests` | `status_reason_code` | `broker_truth_recovery` ✅ | MCP SELECT 확인 |
| `order_requests` | `status_reason_message` | `Broker position snapshot 기준 filled 복구 (10주 @ 145,400 confirmed, source_of_truth=broker)` ✅ | MCP SELECT 확인 |
| `order_requests` | `submitted_at` | `2026-05-15T04:12:10.082Z` ✅ | MCP SELECT 확인 |
| `broker_orders` | `broker_status` | `filled` ✅ | MCP SELECT 확인 |
| `broker_orders` | `last_synced_at` | `2026-05-15T05:44:12.212Z` ✅ | MCP SELECT 확인 |
| `order_state_events` | 7건 | 기존 5건 + `system_ops_recovery` 2건(잘못됨) + `broker_truth_recovery` 1건(보정) ✅ | MCP SELECT 확인 |
| `fill_events` | 1건 | `source_channel='manual'`, `raw_payload_uri`에 recovery metadata ✅ | MCP SELECT 확인 |

---

## 5. 복구 후 상태

### 최종 State Flow

```
draft → validated → pending_submit → submitted → reconcile_required
                                                          ↓
                                                    rejected (잘못됨 - system_ops_recovery, reason_code=40270000)
                                                          ↓
                                                    filled (보정 - broker_truth_recovery) ✅
```

### order_state_events 전체 이력 (7건)

| # | 이전 상태 | 새 상태 | event_source | reason_code |
|---|-----------|---------|-------------|-------------|
| 1 | `draft` | `validated` | `internal` | `null` |
| 2 | `validated` | `pending_submit` | `internal` | `null` |
| 3 | `pending_submit` | `submitted` | `internal` | `0000030092` |
| 4 | `submitted` | `reconcile_required` | `internal` | `null` |
| 5 | `reconcile_required` | `rejected` | `system_ops_recovery` | `40270000` ❌ |
| 6 | `pending_submit` | `rejected` | `system_ops_recovery` | `40270000` ❌ |
| 7 | `rejected` | `filled` | `broker_truth_recovery` | `broker_truth_recovery` ✅ |

---

## 6. 남은 불확실성

| 항목 | 불확실성 | 영향 |
|------|----------|------|
| **체결 시간** | 정확한 fill timestamp를 알 수 없음. submit 직후(13:12:10)로 추정 | fill_events의 fill_timestamp가 정확하지 않을 수 있음 |
| **수수료/세금** | KIS paper trading의 수수료를 알 수 없음. 0으로 설정 | 회계 정확성에 영향 |
| **broker_fill_id** | KIS의 실제 fill ID를 알 수 없음 | 복구 fill_event에 복구 전용 ID 부여 |
| **브로커 API 직접 조회 불가** | 장중이지만 KIS API로 주문 상태를 직접 확인하지는 못함 | position_snapshot 데이터로 간접 증명 |
| **금일 추가 submit 가능성** | `DEFAULT_MAX_SUBMIT_PER_DAY=1`로 인해 `db_submit_count=1`이 되어 추가 submit 차단 | 설정 변경 필요시 사용자 판단 |

### db_submit_count 영향

`filled`는 `_BUDGET_CONSUMING_STATUSES`에 포함되므로:
- **복구 전**: `db_submit_count = 0` (rejected는 budget 미소비)
- **복구 후**: `db_submit_count = 1` (filled는 budget 소비)
- `DEFAULT_MAX_SUBMIT_PER_DAY = 1`이므로 `effective_submit_count = max(0, 1) = 1`
- `dry_run = 1 >= 1 = True` → **submit gate 다시 CLOSED**

이는 **정합성 복구의 자연스러운 결과**입니다.  이미 체결된 주문이 1건 존재하므로, 오늘 1회 submit 예산을 이미 사용한 것이 맞습니다.

---

## 7. 재발 방지 제안

### 문제 1: reconcile_required를 40270000 실패로 오분류

**원인**: `reconcile_required` 상태는 broker_order가 존재하는 주문입니다 (= broker에 제출됨).  그러나 제가 이 주문을 40270000 `pending_submit` 주문들과 동일하게 취급하여 잘못 `rejected`로 변경했습니다.

**제안**: 
- `reconcile_required` 상태의 주문을 자동 `rejected` 전환 금지
- `reconcile_required`는 broker에 제출된 주문이므로, `pending_submit`(broker 미제출)과 동일하게 취급하면 안 됨
- 운영 가드: `reconcile_required → rejected` 전환 전 반드시 broker truth 확인 절차 필요

### 문제 2: fill_events 미포착

**원인**: 브로커에서 체결되었으나 시스템이 fill_events를 생성하지 못함

**제안**: 
- Snapshot sync 로직에서 position 데이터와 order_requests 간 차이를 감지하여 누락된 fill_events를 자동 보정하는 로직 추가
- 또는 position_snapshot 데이터를 기반으로 주기적인 정합성 검사 실행

### 문제 3: DEFAULT_MAX_SUBMIT_PER_DAY = 1

**원인**: 하루 1회만 submit 가능하도록 설정

**제안**: 
- 현재 설정은 의도된 값일 수 있음 (risk 관리 목적)
- 필요시 운영 정책에 따라 조정

---

## 요약

| 구분 | 내용 |
|------|------|
| **대상 주문 ID** | `3125e4ce-5f14-4d5a-aefe-98d3332c7271` (000880 BUY 10 @ ₩145,400) |
| **Broker truth 확인 결과** | ✅ **체결됨** — position_snapshot 10주 @ ₩145,400 (source_of_truth=broker) |
| **복구 전 상태** | `rejected` (reason_code=40270000) ❌ |
| **복구 후 상태** | `filled` (+ broker_truth_recovery 보정 이벤트) ✅ |
| **수정 항목** | `order_requests` (status, reason_code, submitted_at), `broker_orders` (broker_status), `order_state_events` (보정 추가), `fill_events` (신규) |
| **남은 리스크** | `db_submit_count=1` 재발생으로 submit gate 재차단 (정합성 복구 결과) |
| **실행 방식** | Docker 컨테이너 내 `psql`로 직접 실행 (Python asyncpg 트랜잭션 문제로 인해) |
