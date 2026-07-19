# VTTC0081R 체결내역 Phase 2

## 목표

`VTTC0081R` 체결 스냅샷을 `order_request`와 직접 연결하고, `order_sync_service`가 BUY/SELL truth 판정 시 연결된 체결 스냅샷을 position 추론보다 우선 사용하는 경로를 추가한다.

## 적용 내용

### 1. 스키마

- `db/migrations/0031_link_fill_snapshots_to_orders.sql`
  - `trading.broker_fill_snapshots.order_request_id UUID NULL`
  - `FK → trading.order_requests(order_request_id)`
  - `(order_request_id, order_date, fill_timestamp)` 인덱스 추가

### 2. 체결 스냅샷 저장 시 주문 직접 연결

- `src/agent_trading/services/fill_history_sync.py`
  - `sync_fill_history_for_account()`에 `broker_order_repo` 주입
  - `broker_native_order_id(ODNO)`로 `broker_orders`를 조회
  - 매칭되면 `order_request_id`를 `BrokerFillSnapshotEntity`에 저장
  - 동일 sync cycle 내 ODNO lookup은 메모리 cache로 재사용

### 3. 저장소/엔티티 확장

- `src/agent_trading/domain/entities.py`
  - `BrokerFillSnapshotEntity.order_request_id` 추가
- `src/agent_trading/repositories/contracts.py`
  - `BrokerFillSnapshotRepository.list_recent(..., order_request_id=None)` 확장
- `src/agent_trading/repositories/memory.py`
  - upsert/list_recent에 `order_request_id` 반영
- `src/agent_trading/repositories/postgres/broker_fill_snapshots.py`
  - insert/upsert/list_recent에 `order_request_id` 반영
  - 기존 row upsert 시 `EXCLUDED.order_request_id`가 있으면 채움

### 4. order sync truth source 전환

- `src/agent_trading/services/order_sync_service.py`
  - `TruthProbeReason.FILL_SNAPSHOT` 추가
  - `_infer_linked_fill_snapshot_truth(order)` 추가
  - `_try_truth_probe()`에서:
    1. `broker_native_order_id` 존재 확인
    2. **linked fill snapshot truth 먼저 확인**
    3. 없으면 기존 `resolve_unknown_state()`
    4. BUY 비단말 상태면 기존 position inference fallback
  - 판정 규칙:
    - linked snapshot 중 `max(filled_quantity) >= requested_quantity` → `FILLED`
    - `0 < max(filled_quantity) < requested_quantity` → `PARTIALLY_FILLED`
  - 상태 사유:
    - `status_reason_code = truth_probe_fill_snapshot`
    - `status_reason_message`에 linked fill snapshot 기반 해결 메시지 기록

### 5. API 노출

- `src/agent_trading/api/schemas.py`
  - `FillHistoryItem.order_request_id` 추가
- `src/agent_trading/api/routes/fill_history.py`
  - `/fill-history` 응답에 `order_request_id` 포함

## 테스트

### 자동 테스트

- `tests/services/test_fill_history_sync.py`
  - VTTC0081R row 적재 시 `ODNO → order_request_id` 직접 연결 검증
- `tests/services/test_order_sync_service.py::TestLinkedFillSnapshotTruth`
  - linked fill snapshot이 있으면 broker truth 호출 전 `FILLED`로 해결되는지 검증
- `tests/api/test_fill_history.py`
  - `/fill-history` 응답에 `order_request_id` 노출 검증

### 실행 결과

- `pytest -q tests/services/test_fill_history_sync.py tests/api/test_fill_history.py tests/services/test_order_sync_service.py::TestLinkedFillSnapshotTruth`
  - `4 passed`
- `pytest -q tests/services/test_order_sync_service.py -k 'truth_probe and not slow'`
  - `4 passed`

## 실제 데이터 반영

### 마이그레이션

- `docker compose exec -T app python -m agent_trading.db.migrations.run`
  - `0031_link_fill_snapshots_to_orders.sql` 적용 완료

### 기존 체결 스냅샷 backfill

신규 fill sync 1회 실행은 당시 paper inquiry budget 부족으로 실패:

- `VTTC0081R failed: [inquiry] Bucket 'inquiry' exhausted (remaining=0/1)`

Phase 2 자체는 코드/스키마 문제와 무관하므로, 기존 row는 SQL로 즉시 backfill:

```sql
UPDATE trading.broker_fill_snapshots bfs
SET order_request_id = bo.order_request_id,
    updated_at = NOW()
FROM trading.broker_orders bo
WHERE bfs.order_request_id IS NULL
  AND bfs.broker_name = bo.broker_name
  AND bfs.broker_native_order_id = bo.broker_native_order_id;
```

결과:

- `broker_fill_snapshots total_rows = 24`
- `linked_rows = 24`

표본 확인:

- `001740 / ODNO=0000033121 / order_request_id=22dadd3b-... / status=filled`
- `001450 / ODNO=0000013026 / order_request_id=a57ed2d1-... / status=filled`

## 기대 효과

1. `paper_truth_missing` 케이스에서 BUY/SELL truth 판정이 position snapshot에만 의존하지 않음
2. 체결 스냅샷 화면에서 주문 상세/제출 이력과 직접 연결 가능한 기반 확보
3. 후속 Phase 3에서 `order_request_id → trade_decision_id → UI cross-link`를 더 쉽게 확장 가능

## 후속 권장 작업

1. `fill sync` budget exhausted 재시도 정책 추가
   - inquiry bucket 부족 시 짧게 대기 후 재시도
2. `fill snapshot` 기반 부분체결 수량 계산 고도화
   - `max(filled_quantity)` 외에 누적/개별 체결 표현 차이 분석
3. `fill-history` API에 `order_request_id`, `symbol`, `ODNO` 필터 추가
